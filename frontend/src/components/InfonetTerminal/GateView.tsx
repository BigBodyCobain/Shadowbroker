'use client';

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ArrowDown, ArrowUp, ChevronLeft, RefreshCw, Reply, Search, Send } from 'lucide-react';
import { API_BASE } from '@/lib/api';
import {
  nextGateMessagesPollDelayMs,
  nextGateMessagesWaitRearmDelayMs,
  nextGateMessagesWaitTimeoutMs,
} from '@/mesh/gateMetadataTiming';
import {
  ACTIVE_GATE_ROOM_MESSAGE_LIMIT,
  fetchGateMessageSnapshotState,
  waitForGateMessageSnapshot,
} from '@/mesh/gateMessageSnapshot';
import {
  getGateSessionStreamStatus,
  retainGateSessionStreamGate,
  subscribeGateSessionStreamEvents,
  subscribeGateSessionStreamStatus,
} from '@/mesh/gateSessionStream';
import { nextSequence } from '@/mesh/meshIdentity';
import {
  approveGateCompatFallback,
  decryptWormholeGateMessages,
  fetchWormholeGateKeyStatus,
  hasGateCompatFallbackApproval,
  postWormholeGateMessage,
  prepareWormholeInteractiveLane,
  signMeshEvent,
  syncBrowserWormholeGateState,
  type WormholeGateKeyStatus,
} from '@/mesh/wormholeIdentityClient';
import { gateEnvelopeDisplayText, gateEnvelopeState, isEncryptedGateEnvelope } from '@/mesh/gateEnvelope';
import { validateEventPayload } from '@/mesh/meshSchema';

const GATE_INTROS: Record<string, string> = {
  infonet:
    'Welcome to the Infonet general channel. This is the main commons — discuss anything related to the network, ask questions, share intel. Keep it civil.',
  'general-talk':
    "Off-topic discussion. Talk about whatever you want — just keep it respectful and don't post anything that'll get the gate burned.",
  'gathered-intel':
    'Post verified OSINT findings here. Unverified rumors go in general-talk. Cite your sources or get downvoted into oblivion.',
  'tracked-planes':
    "Military and private aviation tracking discussion. Share callsigns, unusual flight patterns, and transponder anomalies you've spotted on the map.",
  'ukraine-front':
    'Ukraine conflict monitoring. Frontline updates, satellite imagery analysis, and verified ground reports only. No propaganda.',
  'iran-front':
    'Iran and Middle East situational awareness. Missile activity, naval movements, diplomatic developments. Verified sources preferred.',
  'world-news':
    "Breaking world events and geopolitical developments. If it's happening right now and it matters, post it here.",
  'prediction-markets':
    'Discuss prediction market movements, arbitrage opportunities, and consensus shifts. Polymarket and Kalshi analysis welcome.',
  finance:
    'Markets, macro trends, sanctions tracking, and economic intelligence. No financial advice — just signal.',
  cryptography:
    'Encryption protocols, zero-knowledge proofs, post-quantum research, and implementation discussion. Show your math.',
  cryptocurrencies:
    'Crypto markets, DeFi protocols, chain analysis, and privacy coins. No shilling. No pump groups.',
  'meet-chat':
    'Find other sovereigns in your area. Coordinate local meetups, dead drops, or mesh node deployments. Practice good OPSEC.',
  'opsec-lab':
    'Operational security discussion. Share techniques, tools, and threat models. Help each other stay invisible.',
};

interface GateViewProps {
  gateName: string;
  persona: string;
  entryMode?: 'anonymous' | 'persona' | null;
  onBack: () => void;
  onNavigateGate: (gate: string) => void;
  onOpenLiveGate?: (gate: string) => void;
  availableGates: string[];
  /** Open the gate shutdown lifecycle view. */
  onOpenShutdownPetition?: (gate: string) => void;
}

interface GateMessage {
  event_id: string;
  event_type?: string;
  node_id?: string;
  message?: string;
  ciphertext?: string;
  epoch?: number;
  nonce?: string;
  sender_ref?: string;
  format?: string;
  gate_envelope?: string;
  envelope_hash?: string;
  decrypted_message?: string;
  payload?: {
    gate?: string;
    ciphertext?: string;
    nonce?: string;
    sender_ref?: string;
    format?: string;
    gate_envelope?: string;
    envelope_hash?: string;
    reply_to?: string;
  };
  gate?: string;
  timestamp: number;
  sequence?: number;
  signature?: string;
  public_key?: string;
  public_key_algo?: string;
  protocol_version?: string;
  reply_to?: string;
  ephemeral?: boolean;
  system_seed?: boolean;
  fixed_gate?: boolean;
}

interface ReplyContext {
  eventId: string;
  nodeId: string;
}

function timeAgo(timestamp: number): string {
  const ts = Number(timestamp || 0);
  if (!ts) return 'just now';
  const delta = Math.max(0, Math.floor(Date.now() / 1000) - ts);
  if (delta < 60) return `${delta}s`;
  if (delta < 3600) return `${Math.floor(delta / 60)}m`;
  if (delta < 86400) return `${Math.floor(delta / 3600)}h`;
  return `${Math.floor(delta / 86400)}d`;
}

interface ThreadedMessage {
  message: GateMessage;
  depth: number;
}

/** Build a flat depth-ordered list: root messages first, then their replies indented beneath. */
function buildThreadedList(messages: GateMessage[]): ThreadedMessage[] {
  const byId = new Map<string, GateMessage>();
  const childrenOf = new Map<string, GateMessage[]>();

  for (const msg of messages) {
    const id = String(msg.event_id || '');
    if (id) byId.set(id, msg);
    const parent = String(msg.reply_to || '').trim();
    if (parent) {
      const siblings = childrenOf.get(parent) || [];
      siblings.push(msg);
      childrenOf.set(parent, siblings);
    }
  }

  const result: ThreadedMessage[] = [];
  const visited = new Set<string>();

  function walk(msg: GateMessage, depth: number) {
    const id = String(msg.event_id || '');
    if (visited.has(id)) return;
    visited.add(id);
    result.push({ message: msg, depth: Math.min(depth, 4) });
    const children = childrenOf.get(id) || [];
    children.sort((a, b) => (a.timestamp || 0) - (b.timestamp || 0));
    for (const child of children) {
      walk(child, depth + 1);
    }
  }

  // Roots: messages with no reply_to, or reply_to pointing to a missing parent
  const roots = messages.filter((msg) => {
    const parent = String(msg.reply_to || '').trim();
    return !parent || !byId.has(parent);
  });
  roots.sort((a, b) => (a.timestamp || 0) - (b.timestamp || 0));
  for (const root of roots) {
    walk(root, 0);
  }
  // Any orphans not yet visited (shouldn't happen, but safety net)
  for (const msg of messages) {
    if (!visited.has(String(msg.event_id || ''))) {
      walk(msg, 0);
    }
  }
  return result;
}

function normalizeGateMessage(message: GateMessage): GateMessage {
  if (!message || typeof message !== 'object') {
    return {
      event_id: '',
      timestamp: 0,
    };
  }
  const payload = message.payload && typeof message.payload === 'object' ? message.payload : undefined;
  return {
    ...message,
    gate: String(message.gate ?? payload?.gate ?? ''),
    ciphertext: String(message.ciphertext ?? payload?.ciphertext ?? ''),
    nonce: String(message.nonce ?? payload?.nonce ?? ''),
    sender_ref: String(message.sender_ref ?? payload?.sender_ref ?? ''),
    format: String(message.format ?? payload?.format ?? ''),
    gate_envelope: String(message.gate_envelope ?? payload?.gate_envelope ?? ''),
    envelope_hash: String(message.envelope_hash ?? payload?.envelope_hash ?? ''),
    reply_to: String(message.reply_to ?? payload?.reply_to ?? ''),
  };
}

function describeGateCompatError(detail: string, gateId: string = ''): string {
  const normalized = String(detail || '').trim();
  const lowered = normalized.toLowerCase();
  if (
    lowered.includes('transport tier insufficient') ||
    lowered.includes('warming up in the background')
  ) {
    return 'The obfuscated lane is still warming up in the background. Stay in the room and posting should unlock shortly.';
  }
  if (normalized === 'gate_compat_fallback_consent_required') {
    return 'Local gate runtime is unavailable for this room.';
  }
  if (normalized.startsWith('gate_local_runtime_required:')) {
    const reason = normalized.slice('gate_local_runtime_required:'.length);
    return `${describeGateCompatReason(reason, gateId)} Use native desktop or resync local gate state.`;
  }
  if (normalized === 'gate_backend_plaintext_compat_required') {
    return 'Service-side gate send is disabled on this runtime. Use native desktop or an explicit compatibility override.';
  }
  if (normalized === 'gate_envelope_required') {
    return 'Local gate sealing is warming up. Your draft is still here.';
  }
  if (normalized === 'gate_envelope_encrypt_failed') {
    return 'Local gate sealing could not finish. Your draft is still here.';
  }
  return normalized;
}

function describeGateCompatConsentPrompt(action: string): string {
  switch (String(action || '')) {
    case 'decrypt':
      return 'Use compatibility mode for this room to read messages on this device.';
    case 'compose':
    case 'post':
      return 'Use compatibility mode for this room to send messages on this device.';
    default:
      return 'Use compatibility mode for this room on this device.';
  }
}

function describeGateCompatReason(reason: string, gateId: string): string {
  const normalizedGate = String(gateId || '').trim().toLowerCase();
  const detail = String(reason || '').trim().toLowerCase();
  if (!detail || detail === 'browser_local_gate_crypto_unavailable') {
    return 'Local gate crypto failed on this device.';
  }
  if (detail === 'browser_gate_worker_unavailable') {
    return 'This runtime cannot use the local gate worker.';
  }
  if (detail.startsWith('browser_gate_state_resync_required:')) {
    return normalizedGate
      ? `Local ${normalizedGate} state needs a resync on this device.`
      : 'Local gate state needs a resync on this device.';
  }
  if (
    detail.startsWith('browser_gate_state_mapping_missing_group:') ||
    detail === 'browser_gate_state_active_member_missing'
  ) {
    return 'Local gate state is incomplete on this device.';
  }
  if (detail === 'worker_gate_wrap_key_missing') {
    return 'Secure local gate storage is unavailable in this browser.';
  }
  if (detail === 'gate_mls_decrypt_failed') {
    return 'Local gate decrypt failed on this device.';
  }
  return 'Local gate crypto failed on this device.';
}

interface GateCompatConsentPromptState {
  gateId: string;
  action: 'compose' | 'post' | 'decrypt';
  reason: string;
}

export default function GateView({
  gateName,
  persona,
  entryMode = null,
  onBack,
  onNavigateGate,
  onOpenLiveGate: _onOpenLiveGate,
  availableGates,
  onOpenShutdownPetition,
}: GateViewProps) {
  const [searchInput, setSearchInput] = useState('');
  const [messages, setMessages] = useState<GateMessage[]>([]);
  // Self-authored plaintext, keyed by real event_id returned from the POST.
  // This lives in React state ONLY — pure RAM, dies with the tab, never
  // written to disk or sessionStorage. It exists so a refresh that replaces
  // the messages array with ciphertext from the server doesn't wipe the
  // author's view of what they just said. MLS's forward-secrecy property
  // (sender can't re-decrypt own output) is preserved on the wire / on disk.
  const [selfAuthoredByEventId, setSelfAuthoredByEventId] = useState<Record<string, string>>({});
  const [composer, setComposer] = useState('');
  const [busy, setBusy] = useState(false);
  const [roomError, setRoomError] = useState('');
  const [status, setStatus] = useState<WormholeGateKeyStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [replyContext, setReplyContext] = useState<ReplyContext | null>(null);
  const [reps, setReps] = useState<Record<string, number>>({});
  const [voteNotice, setVoteNotice] = useState('');
  const [votedOn, setVotedOn] = useState<Record<string, 1 | -1>>({});
  const [compatActive, setCompatActive] = useState(false);
  const [compatConsentPrompt, setCompatConsentPrompt] = useState<GateCompatConsentPromptState | null>(null);
  const [streamStatus, setStreamStatus] = useState(() => getGateSessionStreamStatus());
  const [streamStatusHydrated, setStreamStatusHydrated] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const pollTimerRef = useRef<number | null>(null);
  const waitAbortRef = useRef<AbortController | null>(null);
  const gateCursorRef = useRef(0);
  const repsRef = useRef<Record<string, number>>({});
  const streamEnabledForGateRef = useRef(false);

  const gateId = useMemo(() => String(gateName || '').trim().toLowerCase(), [gateName]);
  const introMessage =
    GATE_INTROS[gateId] || 'Welcome to this gate. Be civil. The Shadowbroker is watching.';

  useEffect(() => {
    setCompatActive(hasGateCompatFallbackApproval(gateId));
    setCompatConsentPrompt(null);
    gateCursorRef.current = 0;
  }, [gateId]);

  useEffect(
    () =>
      subscribeGateSessionStreamStatus((nextStatus) => {
        setStreamStatus(nextStatus);
        setStreamStatusHydrated(true);
      }),
    [],
  );

  useEffect(() => {
    if (!gateId || !status?.has_local_access) {
      return;
    }
    return retainGateSessionStreamGate(gateId);
  }, [gateId, status?.has_local_access]);

  useEffect(() => {
    if (!gateId || !status?.has_local_access) {
      return;
    }
    void prepareWormholeInteractiveLane({
      minimumTransportTier: 'private_control_only',
    }).catch(() => undefined);
  }, [gateId, status?.has_local_access]);

  const streamEnabledForGate =
    Boolean(gateId) &&
    streamStatus.phase === 'open' &&
    streamStatus.subscriptions.includes(gateId);
  const streamPreferredForGate =
    Boolean(gateId) &&
    (streamStatus.phase === 'connecting' || streamStatus.phase === 'open') &&
    streamStatus.subscriptions.includes(gateId);

  useEffect(() => {
    streamEnabledForGateRef.current = streamPreferredForGate;
  }, [streamPreferredForGate]);

  const searchMatch = searchInput.startsWith('g/')
    ? availableGates.find((g) => g.startsWith(searchInput.slice(2).toLowerCase()))
    : null;

  const voteScopeKey = useCallback((targetId: string) => `${gateId}::${String(targetId || '').trim()}`, [gateId]);

  const hydrateMessages = useCallback(async (
    rawMessages: GateMessage[],
  ): Promise<{ messages: GateMessage[]; compatDecryptBlocked: boolean; roomError?: string }> => {
    const baseMessages = (Array.isArray(rawMessages) ? rawMessages : []).map(normalizeGateMessage);
    const encrypted = baseMessages
      .map((message, index) => ({ message, index }))
      .filter(({ message }) => isEncryptedGateEnvelope(message));

    if (!encrypted.length) {
      return {
        messages: baseMessages.map((message) => ({ ...message, decrypted_message: '' })),
        compatDecryptBlocked: false,
        roomError: '',
      };
    }

    try {
      const batch = await decryptWormholeGateMessages(
        encrypted.map(({ message }) => {
          const gateEnvelope = String(message.gate_envelope || '');
          return {
            gate_id: String(message.gate || gateId),
            epoch: Number(message.epoch || 0),
            ciphertext: String(message.ciphertext || ''),
            nonce: String(message.nonce || ''),
            sender_ref: String(message.sender_ref || ''),
            format: String(message.format || 'mls1'),
            gate_envelope: gateEnvelope,
            envelope_hash: String(message.envelope_hash || ''),
            // If a gate_envelope is present, go straight to the backend
            // envelope-fast-path by signaling recovery_envelope=true.
            // This skips browser-side MLS (which has empty state across
            // fresh anon sessions) and uses the durable AES-GCM envelope
            // keyed under gate_secret — which EVERY gate member can
            // decrypt as long as they hold the current gate_secret.
            recovery_envelope: gateEnvelope.length > 0,
          };
        }),
      );
      const results = Array.isArray(batch.results) ? batch.results : [];
      const nextMessages = [...baseMessages];
      encrypted.forEach(({ index, message }, resultIndex) => {
        const decrypted = results[resultIndex];
        const decryptedReplyTo = decrypted?.ok ? String(decrypted.reply_to || '').trim() : '';
        nextMessages[index] = {
          ...message,
          decrypted_message: decrypted?.ok
            ? (decrypted.self_authored && !decrypted.plaintext
              ? (decrypted.legacy
                ? '[legacy gate message — pre-encryption-fix]'
                : '[your message — plaintext not cached]')
              : String(decrypted.plaintext || ''))
            : '',
          epoch: decrypted?.ok ? Number(decrypted.epoch || message.epoch || 0) : message.epoch,
          reply_to: decryptedReplyTo || String(message.reply_to || ''),
        };
      });
      return {
        messages: nextMessages,
        compatDecryptBlocked: false,
        roomError: '',
      };
    } catch (error) {
      const detail = error instanceof Error ? error.message : '';
      if (
        detail === 'gate_compat_fallback_consent_required' ||
        detail.startsWith('gate_local_runtime_required:')
      ) {
        return {
          messages: baseMessages.map((message) => ({ ...message, decrypted_message: '' })),
          compatDecryptBlocked: false,
          roomError: describeGateCompatError(detail, gateId),
        };
      }
      return {
        messages: baseMessages.map((message) => ({ ...message, decrypted_message: '' })),
        compatDecryptBlocked: false,
        roomError: '',
      };
    }
  }, [gateId]);

  const applyGateMessages = useCallback(
    async (rawMessages: GateMessage[]) => {
      const normalizedMessages = Array.isArray(rawMessages) ? rawMessages : [];
      const hydrated = await hydrateMessages(normalizedMessages);
      const chronological = [...hydrated.messages].reverse();
      setMessages(chronological);
      if (hydrated.roomError) {
        setRoomError(hydrated.roomError);
      } else if (!hydrated.compatDecryptBlocked) {
        setRoomError('');
      }

      const uniqueEventIds = Array.from(
        new Set(
          chronological
            .map((message) => String(message.event_id || '').trim())
            .filter(Boolean),
        ),
      );
      if (uniqueEventIds.length > 0) {
        try {
        const uncachedEventIds = uniqueEventIds.filter(
          (eventId) => !Object.prototype.hasOwnProperty.call(repsRef.current, eventId),
        );
        if (uncachedEventIds.length === 0) {
          return;
        }
        const params = new URLSearchParams();
        for (const eid of uncachedEventIds) params.append('node_id', eid);
        const repRes = await fetch(`${API_BASE}/api/mesh/reputation/batch?${params}`);
        if (repRes.ok) {
          const repData = await repRes.json();
          const freshReps: Record<string, number> = {};
          if (repData.reputations && typeof repData.reputations === 'object') {
            for (const [k, v] of Object.entries(repData.reputations)) {
                freshReps[k] = Number(v || 0);
              }
            }
            if (Object.keys(freshReps).length > 0) {
              setReps((prev) => ({ ...prev, ...freshReps }));
            }
          }
        } catch {
          /* ignore batch rep fetch failure */
        }
      }
    },
    [hydrateMessages],
  );

  const refreshGate = useCallback(async (options: { force?: boolean } = {}): Promise<boolean> => {
    if (!gateId) return false;
    setLoading(true);
    try {
      const streamOwned = streamEnabledForGateRef.current;
      const nextStatus = await fetchWormholeGateKeyStatus(gateId, {
        force: options.force,
        mode: streamOwned ? 'session_stream' : 'active_room',
      });
      setStatus(nextStatus);
      if (!nextStatus?.ok || !nextStatus.has_local_access) {
        gateCursorRef.current = 0;
        setMessages([]);
        setRoomError(String(nextStatus?.detail || 'Gate access still syncing'));
        return false;
      }
      if (options.force || !streamOwned || !status?.has_local_access) {
        await syncBrowserWormholeGateState(gateId).catch(() => false);
      }
      const snapshot = await fetchGateMessageSnapshotState(gateId, ACTIVE_GATE_ROOM_MESSAGE_LIMIT, {
        force: options.force,
        proofMode: streamOwned ? 'session_stream' : 'default',
      });
      gateCursorRef.current = snapshot.cursor;
      await applyGateMessages(snapshot.messages as GateMessage[]);
      return true;
    } catch (error) {
      setRoomError(error instanceof Error ? error.message : 'Failed to load gate room');
      return false;
    } finally {
      setLoading(false);
    }
  }, [applyGateMessages, gateId, status?.has_local_access]);

  useEffect(() => {
    if (!gateId || !status?.has_local_access || !streamEnabledForGate) {
      return;
    }
    return subscribeGateSessionStreamEvents((event) => {
      if (event.event !== 'gate_update' || !event.data || typeof event.data !== 'object') {
        return;
      }
      const updates = Array.isArray((event.data as { updates?: unknown }).updates)
        ? ((event.data as { updates?: Array<{ gate_id?: string; cursor?: number }> }).updates || [])
        : [];
      const matching = updates.find(
        (update) => String(update?.gate_id || '').trim().toLowerCase() === gateId,
      );
      if (!matching) {
        return;
      }
      void (async () => {
        try {
          const snapshot = await fetchGateMessageSnapshotState(
            gateId,
            ACTIVE_GATE_ROOM_MESSAGE_LIMIT,
            { force: true, proofMode: 'session_stream' },
          );
          gateCursorRef.current = snapshot.cursor;
          await applyGateMessages(snapshot.messages as GateMessage[]);
        } catch {
          await refreshGate({ force: true });
        }
      })();
    });
  }, [applyGateMessages, gateId, refreshGate, status?.has_local_access, streamEnabledForGate]);

  // Active gate rooms now wait for server-side change instead of issuing a fresh fetch on every cycle.
  useEffect(() => {
    if (!streamStatusHydrated) {
      return;
    }
    const isLiveStreamPreferredForGate = () => {
      const liveStreamStatus = getGateSessionStreamStatus();
      return (
        Boolean(gateId) &&
        (liveStreamStatus.phase === 'connecting' || liveStreamStatus.phase === 'open') &&
        liveStreamStatus.subscriptions.includes(gateId)
      );
    };
    const liveStreamPreferred = streamPreferredForGate || isLiveStreamPreferredForGate();
    streamEnabledForGateRef.current = liveStreamPreferred;
    let cancelled = false;
    const clearRetry = () => {
      if (pollTimerRef.current) {
        window.clearTimeout(pollTimerRef.current);
        pollTimerRef.current = null;
      }
    };

    const scheduleRetry = () => {
      if (cancelled || streamEnabledForGateRef.current) return;
      clearRetry();
      pollTimerRef.current = window.setTimeout(() => {
        pollTimerRef.current = null;
        void waitForNextChange();
      }, nextGateMessagesPollDelayMs());
    };

    const startWaitIfNeeded = () => {
      queueMicrotask(() => {
        streamEnabledForGateRef.current =
          streamPreferredForGate || isLiveStreamPreferredForGate();
        if (!cancelled && !streamEnabledForGateRef.current) {
          void waitForNextChange();
        }
      });
    };

    const waitForNextChange = async () => {
      streamEnabledForGateRef.current =
        streamPreferredForGate || isLiveStreamPreferredForGate();
      if (cancelled || !gateId || streamEnabledForGateRef.current) return;
      const controller = new AbortController();
      waitAbortRef.current = controller;
      try {
        const snapshot = await waitForGateMessageSnapshot(
          gateId,
          gateCursorRef.current,
          ACTIVE_GATE_ROOM_MESSAGE_LIMIT,
          {
            timeoutMs: nextGateMessagesWaitTimeoutMs(),
            signal: controller.signal,
          },
        );
        waitAbortRef.current = null;
        if (cancelled) return;
        gateCursorRef.current = snapshot.cursor;
        if (snapshot.changed) {
          await applyGateMessages(snapshot.messages as GateMessage[]);
          void waitForNextChange();
          return;
        }
        clearRetry();
        pollTimerRef.current = window.setTimeout(() => {
          pollTimerRef.current = null;
          void waitForNextChange();
        }, nextGateMessagesWaitRearmDelayMs());
      } catch (error) {
        waitAbortRef.current = null;
        if (cancelled || controller.signal.aborted) {
          return;
        }
        const ready = await refreshGate({ force: true });
        if (!ready) {
          setRoomError(error instanceof Error ? error.message : 'Failed to load gate room');
          scheduleRetry();
          return;
        }
        startWaitIfNeeded();
      }
    };

    if (liveStreamPreferred) {
      void refreshGate();
      return () => {
        cancelled = true;
        clearRetry();
        if (waitAbortRef.current) {
          waitAbortRef.current.abort();
          waitAbortRef.current = null;
        }
      };
    }

    void refreshGate().then((ready) => {
      streamEnabledForGateRef.current =
        streamPreferredForGate || isLiveStreamPreferredForGate();
      if (!cancelled && ready && !streamEnabledForGateRef.current) {
        startWaitIfNeeded();
      }
    });

    return () => {
      cancelled = true;
      clearRetry();
      if (waitAbortRef.current) {
        waitAbortRef.current.abort();
        waitAbortRef.current = null;
      }
    };
  }, [applyGateMessages, gateId, refreshGate, streamPreferredForGate, streamStatusHydrated]);

  useEffect(() => {
    setCompatConsentPrompt(null);
  }, [gateId]);

  useEffect(() => {
    repsRef.current = reps;
  }, [reps]);

  useEffect(() => {
    const handleCompatFallback = (event: Event) => {
      const detail =
        event instanceof CustomEvent && event.detail && typeof event.detail === 'object'
          ? (event.detail as { gateId?: string; action?: string })
          : {};
      const eventGateId = String(detail.gateId || '').trim().toLowerCase();
      if (!eventGateId || eventGateId !== gateId) {
        return;
      }
      setCompatActive(true);
    };
    window.addEventListener('sb:gate-compat-fallback', handleCompatFallback as EventListener);
    return () => {
      window.removeEventListener('sb:gate-compat-fallback', handleCompatFallback as EventListener);
    };
  }, [gateId]);

  useEffect(() => {
    const handleCompatConsentRequired = (event: Event) => {
      const detail =
        event instanceof CustomEvent && event.detail && typeof event.detail === 'object'
          ? (event.detail as GateCompatConsentPromptState)
          : null;
      const eventGateId = String(detail?.gateId || '').trim().toLowerCase();
      if (!eventGateId || eventGateId !== gateId || !detail) {
        return;
      }
      setCompatConsentPrompt({
        gateId: eventGateId,
        action: detail.action,
        reason: String(detail.reason || ''),
      });
    };
    window.addEventListener(
      'sb:gate-compat-consent-required',
      handleCompatConsentRequired as EventListener,
    );
    return () => {
      window.removeEventListener(
        'sb:gate-compat-consent-required',
        handleCompatConsentRequired as EventListener,
      );
    };
  }, [gateId]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSearchKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      const target = searchInput.trim().toLowerCase();
      if (target.startsWith('g/')) {
        const nextGate = target.slice(2);
        if (availableGates.includes(nextGate)) {
          onNavigateGate(nextGate);
          setSearchInput('');
        }
      }
    }
  };

  const handleSend = useCallback(async () => {
    const msg = composer.trim();
    if (!msg || busy || !gateId) return;
    if (!status?.has_local_access) {
      setRoomError('Gate access still syncing');
      return;
    }
    setBusy(true);
    setRoomError('');
    try {
      const gatePost = await postWormholeGateMessage(gateId, msg, replyContext?.eventId || '').catch((error) => ({
        ok: false,
        detail: error instanceof Error ? error.message : 'Gate post failed',
      }));
      if (gatePost?.ok === false) {
        throw new Error(describeGateCompatError(String(gatePost.detail || 'Gate post failed'), gateId));
      }
      setComposer('');
      setReplyContext(null);
      // Capture the server-assigned event_id and remember the plaintext we
      // just authored, keyed by that event_id. The refresh will bring back
      // the same event as ciphertext; during render we paint over its
      // decrypted_message with what we typed. Pure React state — when the
      // tab closes, this map vanishes.
      const realEventId = String((gatePost as { event_id?: string })?.event_id || '');
      if (realEventId) {
        setSelfAuthoredByEventId((prev) => ({ ...prev, [realEventId]: msg }));
      }
      // Optimistic placeholder so the post appears instantly even before
      // the next refresh round-trip completes. Uses the real event_id when
      // available so the refresh merges cleanly rather than duplicating.
      setMessages((prev) => [
        ...prev,
        {
          event_id: realEventId || `_pending_${Date.now()}`,
          message: msg,
          decrypted_message: msg,
          timestamp: Math.floor(Date.now() / 1000),
          node_id: persona,
          gate: gateId,
          reply_to: replyContext?.eventId || '',
          ephemeral: true,
        } as GateMessage,
      ]);
    } catch (error) {
      const errMsg = error instanceof Error ? error.message : 'Gate post failed';
      // Suppress technical sequence/replay errors — just show a clean retry hint
      if (/replay|sequence/i.test(errMsg)) {
        setRoomError('Message could not be posted — try again');
      } else {
        setRoomError(errMsg);
      }
    } finally {
      setBusy(false);
    }
  }, [busy, composer, gateId, persona, replyContext, status?.has_local_access]);

  const approveCompatFallback = useCallback(() => {
    if (!compatConsentPrompt?.gateId) return;
    approveGateCompatFallback(compatConsentPrompt.gateId);
    const action = compatConsentPrompt.action;
    setCompatActive(true);
    setCompatConsentPrompt(null);
    setRoomError('');
    if (action === 'decrypt') {
      void refreshGate({ force: true });
      return;
    }
    void handleSend();
  }, [compatConsentPrompt, handleSend, refreshGate]);

  const handleVote = useCallback(async (eventId: string, vote: 1 | -1) => {
    if (!eventId || !gateId || votedOn[voteScopeKey(eventId)] === vote) return;
    setVotedOn((prev) => ({ ...prev, [voteScopeKey(eventId)]: vote }));
    try {
      const payload = { target_id: eventId, vote, gate: gateId };
      const valid = validateEventPayload('vote', payload);
      if (!valid.ok) {
        throw new Error(`invalid vote payload: ${valid.reason}`);
      }
      const sequence = nextSequence();
      const signed = await signMeshEvent('vote', payload, sequence, { gateId });
      const response = await fetch(`${API_BASE}/api/mesh/vote`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          voter_id: signed.context.nodeId,
          target_id: eventId,
          vote,
          gate: gateId,
          voter_pubkey: signed.context.publicKey,
          public_key_algo: signed.context.publicKeyAlgo,
          voter_sig: signed.signature,
          sequence: signed.sequence,
          protocol_version: signed.protocolVersion,
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || data?.ok === false) {
        throw new Error(String(data?.detail || 'Vote failed'));
      }
      // Use the real weight from the backend for the optimistic score update.
      // The next poll cycle (8s) will reconcile with the real backend score.
      const w = typeof data?.weight === 'number' ? data.weight : 1;
      setReps((prev) => ({
        ...prev,
        [eventId]: Math.round(((prev[eventId] ?? 0) + vote * w) * 10) / 10,
      }));
    } catch (err) {
      // Revert vote state
      setVotedOn((prev) => {
        const next = { ...prev };
        delete next[voteScopeKey(eventId)];
        return next;
      });
      // Show brief notice for duplicate votes
      const msg = err instanceof Error ? err.message : '';
      if (/already set|one vote/i.test(msg)) {
        setVoteNotice('One vote per post');
        setTimeout(() => setVoteNotice(''), 3000);
      }
    }
  }, [gateId, voteScopeKey, votedOn]);

  // Overlay self-authored plaintexts onto the refreshed message list.
  // Lives only in this component's React state; a tab close wipes it.
  const messagesWithSelfOverlay = useMemo(
    () =>
      messages.map((m) => {
        const eid = String(m.event_id || '');
        const selfText = eid ? selfAuthoredByEventId[eid] : '';
        if (!selfText) return m;
        return { ...m, decrypted_message: selfText };
      }),
    [messages, selfAuthoredByEventId],
  );
  const threadedMessages = useMemo(
    () => buildThreadedList(messagesWithSelfOverlay),
    [messagesWithSelfOverlay],
  );

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden">
      <div className="border-b border-gray-800 pb-4 mb-4 shrink-0">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <button
              onClick={onBack}
              className="flex items-center text-cyan-500 hover:text-cyan-400 transition-all uppercase text-xs tracking-widest border border-cyan-900/50 px-3 py-1 bg-cyan-900/10 hover:bg-cyan-900/30 hover:border-cyan-500/50"
            >
              <ChevronLeft size={14} className="mr-1" />
              RETURN TO MAIN
            </button>
            {onOpenShutdownPetition && (
              <button
                onClick={() => onOpenShutdownPetition(gateName)}
                title="Open gate shutdown lifecycle (suspend / shutdown / appeal)"
                className="flex items-center text-amber-500 hover:text-amber-400 transition-all uppercase text-xs tracking-widest border border-amber-900/50 px-3 py-1 bg-amber-900/10 hover:bg-amber-900/30 hover:border-amber-500/50"
              >
                SHUTDOWN STATUS
              </button>
            )}
          </div>
          <div className="text-gray-500 text-xs">
            LOGGED IN AS:{' '}
            <span
              className={
                persona === 'shadowbroker' ? 'text-red-500 animate-pulse font-bold' : 'text-green-400'
              }
            >
              {persona}
            </span>
          </div>
        </div>

        <div className="flex items-center justify-between gap-4 mt-4">
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-2xl font-bold text-cyan-400 uppercase tracking-widest">g/{gateId}</h1>
              {compatActive ? (
                <span className="border border-amber-500/40 bg-amber-950/20 px-2 py-0.5 text-[10px] font-mono tracking-[0.2em] text-amber-200">
                  COMPAT
                </span>
              ) : null}
            </div>
            <p className="text-gray-500 text-sm mt-1">Fixed obfuscated gate. Creation is disabled for this testnet.</p>
          </div>
          <button
            onClick={() => void refreshGate({ force: true })}
            className="inline-flex items-center gap-2 px-3 py-2 border border-cyan-500/30 bg-cyan-950/20 text-cyan-300 hover:bg-cyan-900/30 transition-colors text-sm uppercase tracking-[0.22em]"
          >
            <RefreshCw size={13} />
            Refresh
          </button>
        </div>

        <div className="mt-4 p-3 border border-gray-800 bg-gray-900/20 text-xs text-gray-400">
          <p className="font-bold text-cyan-400 mb-1">=== GATE RULES ===</p>
          <p>1. FIXED LAUNCH CATALOG: no new gates can be created in this build.</p>
          <p>2. POSTS + REPLIES PERSIST ON THE OBFUSCATED GATE STORE FOR NODES THAT CARRY THIS GATE.</p>
          <p>3. GATE VOTES USE THE EXISTING PUBLIC LEDGER VOTE CONTRACT FOR RECORDKEEPING.</p>
        </div>

        <div className="mt-4 p-3 border border-amber-900/30 bg-amber-950/10 text-[11px] text-amber-200/80 leading-relaxed">
          {entryMode === 'anonymous'
            ? 'Anonymous session is active for this gate. The backend rotates a fresh gate-scoped public key here. You can read, post, reply, and cast the current gate-scoped votes from this room.'
            : 'Saved gate face is active for this room. Posts stay scoped to this gate while the room history persists on the obfuscated gate lane.'}
        </div>

        <div className="mt-3 text-sm font-mono text-cyan-400/85">
          {status?.has_local_access
            ? `LIVE ROOM READY • ${status.identity_scope || entryMode || 'gate'} access`
            : loading
              ? 'CONNECTING TO OBFUSCATED GATE LANE...'
              : String(status?.detail || 'Gate access still syncing')}
        </div>
      </div>

      <div className="mb-4 relative shrink-0">
        <div className="flex items-center border border-gray-800 bg-[#0a0a0a] p-2">
          <Search size={14} className="text-gray-600 mr-2" />
          <input
            type="text"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            onKeyDown={handleSearchKeyDown}
            placeholder="Search posts or type g/[gate] to jump..."
            className="bg-transparent border-none outline-none text-white w-full text-sm placeholder-gray-700"
            spellCheck={false}
          />
        </div>
        {searchMatch && searchInput.length > 2 && (
          <div className="absolute top-full left-0 mt-1 bg-[#0a0a0a] border border-gray-800 p-2 text-xs text-gray-400 z-20">
            Jump to:{' '}
            <span
              className="text-white font-bold cursor-pointer"
              onClick={() => {
                onNavigateGate(searchMatch);
                setSearchInput('');
              }}
            >
              g/{searchMatch}
            </span>
          </div>
        )}
      </div>

      {roomError && !compatConsentPrompt ? (
        <div className="mb-3 shrink-0 border border-red-900/30 bg-red-950/10 px-3 py-2 text-[11px] text-red-300">
          {roomError}
        </div>
      ) : null}
      {compatConsentPrompt ? (
        <div className="mb-3 shrink-0 border border-amber-500/30 bg-amber-950/15 px-3 py-2 text-[11px] text-amber-100/90">
          <div className="text-[12px] font-mono tracking-[0.2em] text-amber-300">COMPAT MODE</div>
          <div className="mt-1 leading-[1.7]">
            {describeGateCompatConsentPrompt(compatConsentPrompt.action)}
          </div>
          <div className="mt-1 text-[11px] text-amber-200/70">
            {describeGateCompatReason(compatConsentPrompt.reason, compatConsentPrompt.gateId)}
          </div>
          <div className="mt-2 flex items-center gap-2">
            <button
              onClick={approveCompatFallback}
              className="px-3 py-1.5 border border-amber-500/40 bg-amber-950/20 text-[11px] font-mono tracking-[0.18em] text-amber-100 hover:bg-amber-900/30 transition-colors"
            >
              ENABLE FOR ROOM
            </button>
            <span className="text-[11px] text-amber-200/70">Weaker privacy on this device.</span>
          </div>
        </div>
      ) : null}
      {voteNotice ? (
        <div className="mb-2 shrink-0 border border-yellow-800/30 bg-yellow-950/10 px-3 py-1.5 text-sm text-yellow-400/80 font-mono">
          {voteNotice}
        </div>
      ) : null}

      <div className="flex-1 overflow-y-auto pr-2 space-y-3 pb-4 styled-scrollbar">
        {!messages.length && (
          <div className="border border-gray-800 bg-gray-900/10 p-3">
            <div className="text-xs mb-1 text-gray-500">
              Posted by:{' '}
              <span className="text-red-500 font-bold animate-pulse drop-shadow-[0_0_5px_rgba(239,68,68,0.8)]">
                shadowbroker
              </span>
              <span className="text-gray-600 ml-2">PINNED</span>
            </div>
            <h2 className="text-sm md:text-base text-gray-300 leading-relaxed">{introMessage}</h2>
            <div className="mt-3 pt-2 border-t border-gray-800/50 text-sm text-amber-400/70 tracking-wider uppercase">
              Fixed launch gate for the testnet catalog. Dynamic gate creation is disabled.
            </div>
          </div>
        )}

        {threadedMessages.map(({ message, depth }) =>
          message.system_seed ? (
            <div key={message.event_id} className="border border-cyan-900/30 bg-cyan-950/10 px-3 py-3 max-w-3xl">
              <div className="text-[12px] font-mono tracking-[0.28em] text-cyan-300/85">
                {message.fixed_gate ? 'FIXED GATE NOTICE' : 'GATE NOTICE'}
              </div>
              <div className="mt-2 text-sm font-mono text-cyan-100/80 leading-[1.7]">
                {message.message}
              </div>
            </div>
          ) : (
            <div
              key={message.event_id}
              className="flex"
              style={{ paddingLeft: depth * 24 }}
            >
              {depth > 0 && (
                <div className="flex-shrink-0 w-[2px] bg-cyan-900/30 mr-3 self-stretch" />
              )}
              <div className={`flex-1 border ${depth > 0 ? 'border-gray-800/40 bg-black/10' : 'border-gray-800/70 bg-black/20'} px-3 py-3`}>
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 text-sm font-mono">
                      <span className="text-green-400">
                        @{String(
                          (message as unknown as { sender_handle?: string }).sender_handle
                            || ((message as unknown as { payload?: { sender_handle?: string } }).payload?.sender_handle)
                            || String(message.node_id || '').replace(/^!sb_/, '').slice(0, 8)
                            || String(message.public_key || '').slice(0, 8)
                            || 'anon_????',
                        )}
                      </span>
                      {isEncryptedGateEnvelope(message) ? (
                        <span
                          className={`text-[12px] px-1 border ${
                            gateEnvelopeState(message) === 'decrypted'
                              ? 'text-cyan-300 border-cyan-700/60'
                              : 'text-amber-300 border-amber-700/60'
                          }`}
                        >
                          {gateEnvelopeState(message) === 'decrypted' ? 'DECRYPTED' : 'SEALED'}
                        </span>
                      ) : null}
                      <span className="text-[var(--text-muted)] text-[13px]">{timeAgo(message.timestamp)}</span>
                    </div>
                    <div
                      className={`mt-2 text-[12px] leading-[1.7] whitespace-pre-wrap break-words ${
                        isEncryptedGateEnvelope(message) && !String(message.decrypted_message || '').trim()
                          ? 'text-gray-500 italic'
                          : 'text-gray-200'
                      }`}
                    >
                      {gateEnvelopeDisplayText(message)}
                    </div>
                    <div className="mt-3 flex items-center gap-2">
                      <button
                        onClick={() =>
                          setReplyContext({
                            eventId: String(message.event_id || ''),
                            nodeId: String(message.node_id || ''),
                          })
                        }
                        className="inline-flex items-center gap-1 px-2 py-1 text-[13px] uppercase tracking-[0.18em] border border-cyan-900/40 text-cyan-400 hover:bg-cyan-950/20"
                      >
                        <Reply size={11} />
                        Reply
                      </button>
                      {message.event_id ? (
                        <>
                          <button
                            onClick={() => void handleVote(String(message.event_id || ''), 1)}
                            className={`inline-flex items-center gap-1 px-2 py-1 text-[13px] uppercase tracking-[0.18em] border ${
                              votedOn[voteScopeKey(String(message.event_id || ''))] === 1
                                ? 'border-cyan-400/60 text-cyan-300 bg-cyan-950/20'
                                : 'border-cyan-900/40 text-cyan-500 hover:bg-cyan-950/20'
                            }`}
                          >
                            <ArrowUp size={11} />
                            Up
                          </button>
                          <button
                            onClick={() => void handleVote(String(message.event_id || ''), -1)}
                            className={`inline-flex items-center gap-1 px-2 py-1 text-[13px] uppercase tracking-[0.18em] border ${
                              votedOn[voteScopeKey(String(message.event_id || ''))] === -1
                                ? 'border-red-400/60 text-red-300 bg-red-950/20'
                                : 'border-cyan-900/40 text-red-400 hover:bg-red-950/20'
                            }`}
                          >
                            <ArrowDown size={11} />
                            Down
                          </button>
                          <span className="text-sm font-mono text-cyan-400/70">
                            SCORE {(() => { const s = reps[String(message.event_id || '')] ?? 0; return s % 1 === 0 ? s : s.toFixed(1); })()}
                          </span>
                        </>
                      ) : null}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          ),
        )}
        <div ref={messagesEndRef} />
      </div>

      <div className="shrink-0 pt-3 mt-2 border-t border-gray-800/50">
        {replyContext ? (
          <div className="mb-2 flex items-center justify-between gap-2 border border-amber-900/30 bg-amber-950/10 px-3 py-2 text-sm text-amber-200/80">
            <span>
              Replying to @{replyContext.eventId.slice(0, 8)}
            </span>
            <button
              onClick={() => setReplyContext(null)}
              className="text-amber-300 hover:text-amber-100 uppercase tracking-[0.18em]"
            >
              Clear
            </button>
          </div>
        ) : null}

        <div className="flex items-end gap-3">
          <textarea
            ref={textareaRef}
            value={composer}
            onChange={(e) => {
              setComposer(e.target.value);
              if (roomError) {
                setRoomError('');
              }
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                void handleSend();
              }
            }}
            placeholder="Post into this gate..."
            className="flex-1 min-h-[72px] max-h-[140px] bg-black/40 border border-cyan-900/40 text-gray-100 px-3 py-2 outline-none resize-y placeholder:text-gray-700"
            spellCheck={false}
          />
          <button
            onClick={() => void handleSend()}
            disabled={busy || !composer.trim() || !status?.has_local_access}
            className="inline-flex items-center gap-2 px-4 py-3 border border-cyan-500/40 bg-cyan-950/20 text-cyan-300 hover:bg-cyan-900/30 transition-colors text-sm uppercase tracking-[0.22em] disabled:opacity-40"
          >
            <Send size={13} />
            Post
          </button>
        </div>
      </div>
    </div>
  );
}
