'use client';

import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { API_BASE } from '@/lib/api';
import { classifyTick, jitteredPollDelay, MAX_CATCHUP_POLLS } from '@/lib/dmPollScheduler';
import { shouldQueueDmSend, isGateSendBlocked, isDmPollBlocked } from '@/lib/meshChatPolicies';
import { requestSecureMeshTerminalLauncherOpen } from '@/lib/meshTerminalLauncher';
import {
  getDesktopNativeControlAuditReport,
} from '@/lib/desktopBridge';
import {
  describeNativeControlError,
  extractNativeGateResyncTarget,
} from '@/lib/desktopControlContract';
import type { DesktopControlAuditReport } from '@/lib/desktopControlContract';
import { fetchPrivacyProfileSnapshot } from '@/mesh/controlPlaneStatusClient';
import {
  clearBrowserIdentityState,
  derivePublicMeshAddress,
  generateNodeKeys,
  getNodeIdentity,
  getStoredNodeDescriptor,
  getWormholeIdentityDescriptor,
  hasSovereignty,
  getDHAlgo,
  deriveSharedKey,
  encryptDM,
  decryptDM,
  getContacts,
  addContact,
  updateContact,
  blockContact,
  getDMNotify,
  getPublicKeyAlgo,
  nextSequence,
  signEvent,
  verifyEventSignature,
  verifyRawSignature,
  purgeBrowserContactGraph,
  purgeBrowserSigningMaterial,
  setSecureModeCached,
  migrateLegacyNodeIds,
  hydrateWormholeContacts,
} from '@/mesh/meshIdentity';
import {
  purgeBrowserDmState,
  ratchetEncryptDM,
  ratchetDecryptDM,
  ratchetReset,
} from '@/mesh/meshDmWorkerClient';
import {
  bootstrapDecryptAccessRequest,
  bootstrapEncryptAccessRequest,
  canUseWormholeBootstrap,
} from '@/mesh/wormholeDmBootstrapClient';
import {
  nextGateMessagesPollDelayMs,
  nextGateMessagesWaitRearmDelayMs,
  nextGateMessagesWaitTimeoutMs,
} from '@/mesh/gateMetadataTiming';
import type { GateAccessHeaderMode } from '@/mesh/gateAccessProof';
import {
  fetchGateCatalogSnapshot,
  invalidateGateCatalogSnapshot,
  type GateCatalogEntry,
} from '@/mesh/gateCatalogSnapshot';
import {
  ACTIVE_GATE_ROOM_MESSAGE_LIMIT,
  fetchGateMessageSnapshotState,
  type GateMessageSnapshotState,
  waitForGateMessageSnapshot,
} from '@/mesh/gateMessageSnapshot';
import {
  getGateSessionStreamStatus,
  retainGateSessionStreamGate,
  subscribeGateSessionStreamEvents,
  subscribeGateSessionStreamStatus,
} from '@/mesh/gateSessionStream';
import {
  approveGateCompatFallback,
  acknowledgeWormholeSasFingerprint,
  activateWormholeGatePersona,
  bootstrapWormholeIdentity,
  clearWormholeGatePersona,
  confirmWormholeSasVerification,
  createWormholeGatePersona,
  decryptWormholeGateMessages,
  enterWormholeGate,
  fetchWormholeGateKeyStatus,
  fetchWormholeIdentity,
  fetchWormholeStatus,
  hasGateCompatFallbackApproval,
  isWormholeReady,
  isWormholeSecureRequired,
  issueWormholePairwiseAlias,
  rotateWormholePairwiseAlias,
  listWormholeGatePersonas,
  postWormholeGateMessage,
  recoverWormholeSasRootContinuity,
  resyncWormholeGateState,
  retireWormholeGatePersona,
  rotateWormholeGateKey,
  signMeshEvent,
  syncBrowserWormholeGateState,
} from '@/mesh/wormholeIdentityClient';
import {
  isEncryptedGateEnvelope,
} from '@/mesh/gateEnvelope';
import { fetchWormholeSettings, joinWormhole, leaveWormhole } from '@/mesh/wormholeClient';
import {
  buildMailboxClaims,
  countDmMailboxes,
  ensureRegisteredDmKey,
  fetchDmPublicKey,
  pollDmMailboxes,
  sendOffLedgerConsentMessage,
  sendDmMessage,
  sharedMailboxToken,
} from '@/mesh/meshDmClient';
import {
  allDmPeerIds,
  buildAliasRotateMessage,
  buildContactAcceptMessage,
  buildContactDenyMessage,
  buildContactOfferMessage,
  generateSharedAlias,
  mergeAliasHistory,
  parseAliasRotateMessage,
  parseDmConsentMessage,
  preferredDmPeerId,
} from '@/mesh/meshDmConsent';
import { deriveSasPhrase } from '@/mesh/meshSas';
import { PROTOCOL_VERSION } from '@/mesh/meshProtocol';
import { validateEventPayload } from '@/mesh/meshSchema';
import {
  buildDmTrustHint,
  buildPrivateLaneHint,
  dmTrustPrimaryActionLabel,
  isFirstContactTrustOnly,
  requiresVerifiedFirstContact,
  shortTrustFingerprint,
  shouldAutoRevealSasForTrust,
} from '@/mesh/meshPrivacyHints';
import {
  getSenderRecoveryState,
  requiresSenderRecovery,
  shouldAllowRequestActions,
  shouldKeepUnresolvedRequestVisible,
  shouldPromoteRecoveredSenderForBootstrap,
  shouldPromoteRecoveredSenderForKnownContact,
} from '@/mesh/requestSenderRecovery';

import type {
  MeshChatProps,
  Tab,
  DMView,
  DmTransportMode,
  Gate,
  InfoNetMessage,
  MeshtasticMessage,
  DMMessage,
  AccessRequest,
  SenderPopup,
  GateReplyContext,
  NodeIdentity,
  Contact,
  WormholeGateKeyStatus,
  WormholeIdentity,
} from './types';
import {
  DEFAULT_MESH_ROOTS,
  DM_UNREAD_POLL_EXPANDED_MS,
  DM_UNREAD_POLL_COLLAPSED_MS,
  DM_MESSAGES_POLL_MS,
  DM_DECOY_POLL_MS,
  DM_DECOY_POLL_JITTER_MS,
  ACCESS_REQUEST_BATCH_DELAY_MS,
  ACCESS_REQUEST_BATCH_JITTER_MS,
  SHARED_ALIAS_ROTATE_MS,
  SHARED_ALIAS_GRACE_MS,
  GATE_DECRYPT_CACHE_MAX,
  INFO_VERIFICATION_CACHE_MAX,
} from './types';

import {
  sortMeshRoots,
  normalizeInfoNetMessage,
  gateDecryptCacheKey,
  dmTransportDisplay,
  randomHex,
  jitterDelay,
  sleep,
  randomBase64,
} from './utils';
import {
  getAccessRequests,
  setAccessRequests,
  getPendingSent,
  setPendingSent,
  getGeoHintEnabled,
  getDecoyEnabled,
  getMutedList,
  saveMutedList,
  decryptSenderSealForContact,
  promotePendingAlias,
} from './storage';

function gateCatalogEntryToGate(entry: GateCatalogEntry): Gate {
  return {
    gate_id: String(entry.gate_id || '').trim().toLowerCase(),
    display_name: entry.display_name || entry.gate_id,
    description: entry.description,
    creator: '',
    rules: entry.rules || {},
    message_count: entry.message_count ?? 0,
    fixed: entry.fixed,
  };
}

interface GateCompatConsentPromptState {
  gateId: string;
  action: 'compose' | 'post' | 'decrypt';
  reason: string;
}

function describeGateCompatConsentRequired(): string {
  return 'Local gate runtime is unavailable for this room.';
}

function describeGateLocalRuntimeRequired(detail: string, gateId: string = ''): string {
  const normalized = String(detail || '').trim();
  if (normalized === 'gate_compat_fallback_consent_required') {
    return describeGateCompatConsentRequired();
  }
  if (!normalized.startsWith('gate_local_runtime_required:')) {
    return normalized;
  }
  const reason = normalized.slice('gate_local_runtime_required:'.length);
  const normalizedGate = String(gateId || '').trim().toLowerCase();
  if (!reason || reason === 'browser_local_gate_crypto_unavailable') {
    return 'Local gate runtime is unavailable for this room. Use native desktop or resync local gate state.';
  }
  if (reason === 'browser_gate_worker_unavailable') {
    return 'This runtime cannot keep gate crypto local. Use native desktop or resync local gate state.';
  }
  if (reason.startsWith('browser_gate_state_resync_required:')) {
    return normalizedGate
      ? `Local ${normalizedGate} state needs a resync on this device. Use native desktop or resync local gate state.`
      : 'Local gate state needs a resync on this device. Use native desktop or resync local gate state.';
  }
  if (
    reason.startsWith('browser_gate_state_mapping_missing_group:') ||
    reason === 'browser_gate_state_active_member_missing'
  ) {
    return 'Local gate state is incomplete on this device. Use native desktop or resync local gate state.';
  }
  if (reason === 'worker_gate_wrap_key_missing') {
    return 'Secure local gate storage is unavailable in this browser. Use native desktop or resync local gate state.';
  }
  if (reason === 'gate_mls_decrypt_failed') {
    return 'Local gate decrypt failed on this device. Use native desktop or resync local gate state.';
  }
  return 'Local gate runtime is unavailable for this room. Use native desktop or resync local gate state.';
}

// ─── Controller Hook ────────────────────────────────────────────────────────
// Extracted from MeshChat component. Contains ALL state, effects, and handlers.
// Presentational components receive only the return value of this hook.
// Trust-mutating functions (addContact, updateContact, blockContact,
// purgeBrowserSigningMaterial, purgeBrowserContactGraph, purgeBrowserDmState)
// are called ONLY inside this hook — never exposed to presentational code.

export function useMeshChatController({
  onFlyTo,
  expanded: expandedProp,
  onExpandedChange,
  onSettingsClick,
  onTerminalToggle,
  launchRequest,
}: MeshChatProps) {
  useEffect(() => {
    void migrateLegacyNodeIds().catch((err) => {
      console.warn('[mesh] legacy node-id migration failed in MeshChat', err);
    });
  }, []);

  const [internalExpanded, setInternalExpanded] = useState(true);
  const [gateSessionStreamStatus, setGateSessionStreamStatus] = useState(() => getGateSessionStreamStatus());
  const [gateSessionStreamHydrated, setGateSessionStreamHydrated] = useState(false);
  const [clientHydrated, setClientHydrated] = useState(false);
  const [identityRefreshToken, setIdentityRefreshToken] = useState(0);
  const expanded = expandedProp !== undefined ? expandedProp : internalExpanded;
  const setExpanded = (val: boolean | ((prev: boolean) => boolean)) => {
    const newVal = typeof val === 'function' ? val(expanded) : val;
    setInternalExpanded(newVal);
    onExpandedChange?.(newVal);
  };
  const [activeTab, setActiveTab] = useState<Tab>('meshtastic');
  const openTerminal = useCallback(() => {
    if (onTerminalToggle) {
      onTerminalToggle();
      return;
    }
    requestSecureMeshTerminalLauncherOpen(`mesh-chat:${activeTab}`);
  }, [activeTab, onTerminalToggle]);
  const [inputValue, setInputValue] = useState('');
  const [busy, setBusy] = useState(false);
  const [sendError, setSendError] = useState('');
  const [lastSendTime, setLastSendTime] = useState(0);
  const [identityWizardOpen, setIdentityWizardOpen] = useState(false);
  const [infonetUnlockOpen, setInfonetUnlockOpen] = useState(false);
  const [deadDropUnlockOpen, setDeadDropUnlockOpen] = useState(false);
  const [identityWizardBusy, setIdentityWizardBusy] = useState(false);
  const [identityWizardStatus, setIdentityWizardStatus] = useState<{ type: 'ok' | 'err'; text: string } | null>(null);
  const [meshQuickStatus, setMeshQuickStatus] = useState<{ type: 'ok' | 'err'; text: string } | null>(null);
  const [publicMeshAddress, setPublicMeshAddress] = useState('');
  const [meshView, setMeshView] = useState<'channel' | 'inbox'>('channel');
  const [meshDirectTarget, setMeshDirectTarget] = useState('');

  // Identity
  const [identity, setIdentity] = useState<NodeIdentity | null>(null);
  const [wormholeEnabled, setWormholeEnabled] = useState(false);
  const [wormholeReadyState, setWormholeReadyState] = useState(false);
  const [wormholeRnsReady, setWormholeRnsReady] = useState(false);
  const [wormholeRnsPeers, setWormholeRnsPeers] = useState({ active: 0, configured: 0 });
  const [wormholeRnsDirectReady, setWormholeRnsDirectReady] = useState(false);
  const [recentPrivateFallback, setRecentPrivateFallback] = useState(false);
  const [recentPrivateFallbackReason, setRecentPrivateFallbackReason] = useState('');
  const [unresolvedSenderSealCount, setUnresolvedSenderSealCount] = useState(0);
  const [privacyProfile, setPrivacyProfile] = useState<'default' | 'high'>('default');
  const publicIdentity = clientHydrated ? getNodeIdentity() : null;
  const hasPublicLaneIdentity = clientHydrated && Boolean(publicIdentity) && hasSovereignty();
  const hasId = Boolean(identity) && (hasSovereignty() || wormholeEnabled);
  const shouldShowIdentityWarning = activeTab !== 'meshtastic' && !hasId;
  const privateInfonetReady = wormholeEnabled && wormholeReadyState;
  const publicMeshBlockedByWormhole = wormholeEnabled && wormholeReadyState && !hasPublicLaneIdentity;
  const dmSendQueue = useRef<(() => Promise<void>)[]>([]);
  const dmSendTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const streamEnabledForSelectedGateRef = useRef(false);
  const displayPublicMeshSender = useCallback(
    (sender: string) => {
      if (!sender) return '???';
      if (
        hasPublicLaneIdentity &&
        publicIdentity?.nodeId &&
        publicMeshAddress &&
        sender.toLowerCase() === publicIdentity.nodeId.toLowerCase()
      ) {
        return publicMeshAddress.toUpperCase();
      }
      return sender;
    },
    [hasPublicLaneIdentity, publicIdentity?.nodeId, publicMeshAddress],
  );

  const openIdentityWizard = useCallback(
    (notice: { type: 'ok' | 'err'; text: string } | null = null) => {
      setIdentityWizardStatus(notice);
      setIdentityWizardOpen(true);
    },
    [],
  );

  useEffect(() => {
    setClientHydrated(true);
  }, []);

  useEffect(
    () =>
      subscribeGateSessionStreamStatus((nextStatus) => {
        setGateSessionStreamStatus(nextStatus);
        setGateSessionStreamHydrated(true);
      }),
    [],
  );

  useEffect(() => {
    if (activeTab !== 'meshtastic') {
      setMeshQuickStatus(null);
    }
  }, [activeTab]);

  useEffect(() => {
    if (!clientHydrated || typeof window === 'undefined') return;
    const refreshIdentity = () => setIdentityRefreshToken((value) => value + 1);
    window.addEventListener('sb:identity-state-changed', refreshIdentity);
    window.addEventListener('storage', refreshIdentity);
    window.addEventListener('focus', refreshIdentity);
    return () => {
      window.removeEventListener('sb:identity-state-changed', refreshIdentity);
      window.removeEventListener('storage', refreshIdentity);
      window.removeEventListener('focus', refreshIdentity);
    };
  }, [clientHydrated]);

  useEffect(() => {
    let alive = true;
    const syncIdentity = async () => {
      const localIdentity = getNodeIdentity();
      if (localIdentity && hasSovereignty()) {
        try {
          const hydratedContacts = await hydrateWormholeContacts(true);
          if (alive) setContacts(hydratedContacts);
        } catch {
          if (alive) setContacts(getContacts());
        }
        if (alive) setIdentity(localIdentity);
        return;
      }
      if (wormholeEnabled && wormholeReadyState) {
        try {
          const wormholeIdentity = await fetchWormholeIdentity();
          purgeBrowserSigningMaterial();
          purgeBrowserContactGraph();
          await purgeBrowserDmState();
          const hydratedContacts = await hydrateWormholeContacts(true);
          if (!alive) return;
          setContacts(hydratedContacts);
          setIdentity({
            publicKey: wormholeIdentity.public_key,
            privateKey: '',
            nodeId: wormholeIdentity.node_id,
          });
          return;
        } catch {
          /* ignore */
        }
      }
      if (alive) setIdentity(null);
    };
    void syncIdentity();
    return () => {
      alive = false;
    };
  }, [clientHydrated, identityRefreshToken, wormholeEnabled, wormholeReadyState]);

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const poll = async () => {
      try {
        const [settingsRes, statusRes] = await Promise.allSettled([
          fetchWormholeSettings(),
          fetchWormholeStatus(),
        ]);
        if (!alive) return;
        if (settingsRes.status === 'fulfilled') {
          const data = settingsRes.value;
          const enabled = Boolean(data?.enabled);
          setSecureModeCached(enabled);
          setWormholeEnabled(enabled);
          if (enabled) {
            purgeBrowserContactGraph();
            void hydrateWormholeContacts();
          }
        }
        if (statusRes.status === 'fulfilled') {
          const data = statusRes.value;
          setWormholeReadyState(Boolean(data?.ready));
          setAnonymousModeEnabled(Boolean(data?.anonymous_mode));
          setAnonymousModeReady(Boolean(data?.anonymous_mode_ready));
          setWormholeRnsReady(Boolean(data?.rns_ready));
          setWormholeRnsPeers({
            active: Number(data?.rns_active_peers || 0),
            configured: Number(data?.rns_configured_peers || 0),
          });
          setWormholeRnsDirectReady(Boolean(data?.rns_private_dm_direct_ready));
          setRecentPrivateFallback(Boolean(data?.recent_private_clearnet_fallback));
          setRecentPrivateFallbackReason(
            String(data?.recent_private_clearnet_fallback_reason || '').trim(),
          );
        } else {
          setWormholeReadyState(false);
          setAnonymousModeReady(false);
          setWormholeRnsReady(false);
          setWormholeRnsPeers({ active: 0, configured: 0 });
          setWormholeRnsDirectReady(false);
          setRecentPrivateFallback(false);
          setRecentPrivateFallbackReason('');
        }
      } catch {
        if (!alive) return;
        setWormholeReadyState(false);
        setAnonymousModeReady(false);
        setWormholeRnsReady(false);
        setWormholeRnsPeers({ active: 0, configured: 0 });
        setWormholeRnsDirectReady(false);
        setRecentPrivateFallback(false);
        setRecentPrivateFallbackReason('');
      } finally {
        if (alive) timer = setTimeout(poll, 5000);
      }
    };
    void poll();
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
  }, []);

  useEffect(() => {
    let alive = true;
    fetchPrivacyProfileSnapshot()
      .then((data) => {
        const profile = (data?.profile || 'default').toLowerCase();
        if (alive && (profile === 'high' || profile === 'default')) {
          setPrivacyProfile(profile);
        }
      })
      .catch(() => null);
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    let alive = true;
    const senderId = publicIdentity?.nodeId || '';
    if (!senderId || !globalThis.crypto?.subtle) {
      setPublicMeshAddress('');
      return;
    }
    derivePublicMeshAddress(senderId)
      .then((addr) => {
        if (alive) setPublicMeshAddress(addr);
      })
      .catch(() => {
        if (alive) setPublicMeshAddress('');
      });
    return () => {
      alive = false;
    };
  }, [publicIdentity?.nodeId]);

  const flushDmQueue = useCallback(async () => {
    const queue = dmSendQueue.current.splice(0);
    if (dmSendTimer.current) {
      clearTimeout(dmSendTimer.current);
      dmSendTimer.current = null;
    }
    for (const task of queue) {
      try {
        await task();
      } catch {
        /* ignore */
      }
    }
  }, []);

  const enqueueDmSend = useCallback(
    (task: () => Promise<void>) => {
      return new Promise<void>((resolve) => {
        const wrapped = async () => {
          try {
            await task();
          } catch {
            /* ignore */
          } finally {
            resolve();
          }
        };
        if (!shouldQueueDmSend(privacyProfile)) {
          void wrapped();
          return;
        }
        dmSendQueue.current.push(wrapped);
        if (!dmSendTimer.current) {
          const delay = 120 + Math.random() * 180;
          dmSendTimer.current = setTimeout(() => {
            void flushDmQueue();
          }, delay);
        }
      });
    },
    [privacyProfile, flushDmQueue],
  );

  // ─── Mute State ─────────────────────────────────────────────────────────
  const [mutedUsers, setMutedUsers] = useState<Set<string>>(new Set());
  const [senderPopup, setSenderPopup] = useState<SenderPopup | null>(null);
  const [muteConfirm, setMuteConfirm] = useState<string | null>(null);
  const popupRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    void getMutedList(getNodeIdentity()?.nodeId).then((ids) => {
      if (!cancelled) {
        setMutedUsers(new Set(ids));
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  // Close popup on click outside
  useEffect(() => {
    if (!senderPopup) return;
    const handle = (e: MouseEvent) => {
      if (popupRef.current && !popupRef.current.contains(e.target as Node)) {
        setSenderPopup(null);
      }
    };
    document.addEventListener('mousedown', handle);
    return () => document.removeEventListener('mousedown', handle);
  }, [senderPopup]);

  const handleMute = (userId: string) => {
    const updated = new Set(mutedUsers);
    updated.add(userId);
    setMutedUsers(updated);
    saveMutedList([...updated], getNodeIdentity()?.nodeId);
    setSenderPopup(null);
    setMuteConfirm(null);
  };

  const handleUnmute = (userId: string) => {
    const updated = new Set(mutedUsers);
    updated.delete(userId);
    setMutedUsers(updated);
    saveMutedList([...updated], getNodeIdentity()?.nodeId);
    setSenderPopup(null);
  };

  const handleLocateUser = async (callsign: string) => {
    setSenderPopup(null);
    if (!onFlyTo) return;
    try {
      const res = await fetch(`${API_BASE}/api/mesh/signals?source=meshtastic&limit=500`);
      if (res.ok) {
        const data = await res.json();
        const signals = data.signals || [];
        const match = signals.find(
          (s: { callsign?: string; lat?: number; lng?: number }) =>
            s.callsign === callsign && s.lat && s.lng,
        );
        if (match) {
          onFlyTo(match.lat, match.lng);
        } else {
          setSendError('no position data');
          setTimeout(() => setSendError(''), 3000);
        }
      }
    } catch {
      setSendError('locate failed');
      setTimeout(() => setSendError(''), 3000);
    }
  };

  const handleSenderClick = (
    userId: string,
    e: React.MouseEvent,
    tab: Tab,
    meta?: { publicKey?: string; publicKeyAlgo?: string },
  ) => {
    e.stopPropagation();
    const rect = (e.target as HTMLElement).getBoundingClientRect();
    setSenderPopup({
      userId,
      x: rect.left,
      y: rect.bottom + 4,
      tab,
      publicKey: String(meta?.publicKey || '').trim(),
      publicKeyAlgo: String(meta?.publicKeyAlgo || '').trim(),
    });
  };

  // ─── InfoNet State ───────────────────────────────────────────────────────
  const [gates, setGates] = useState<Gate[]>([]);
  const [selectedGate, setSelectedGate] = useState<string>('');
  const [infoMessages, setInfoMessages] = useState<InfoNetMessage[]>([]);
  const [infoVerification, setInfoVerification] = useState<
    Record<string, 'verified' | 'failed' | 'unsigned'>
  >({});
  const [reps, setReps] = useState<Record<string, number>>({});
  const repsRef = useRef(reps);
  const [votedOn, setVotedOn] = useState<Record<string, 1 | -1>>({});

  const [gateReplyContext, setGateReplyContext] = useState<GateReplyContext | null>(null);
  const [showCreateGate, setShowCreateGate] = useState(false);
  const [newGateId, setNewGateId] = useState('');
  const [newGateName, setNewGateName] = useState('');
  const [newGateMinRep, setNewGateMinRep] = useState(0);
  const [gateError, setGateError] = useState('');
  const [gateCompatConsentPrompt, setGateCompatConsentPrompt] = useState<GateCompatConsentPromptState | null>(null);
  const [gateCompatActive, setGateCompatActive] = useState<Record<string, true>>({});
  const [gateResyncTarget, setGateResyncTarget] = useState('');
  const activeGateSessionRef = useRef<string>('');
  const [gatePersonas, setGatePersonas] = useState<Record<string, WormholeIdentity[]>>({});
  const [activeGatePersonaId, setActiveGatePersonaId] = useState<Record<string, string>>({});
  const [gatePersonaBusy, setGatePersonaBusy] = useState(false);
  const [gateKeyStatus, setGateKeyStatus] = useState<Record<string, WormholeGateKeyStatus>>({});
  const [gateKeyBusy, setGateKeyBusy] = useState(false);
  const [gateResyncBusy, setGateResyncBusy] = useState(false);
  const [gatePersonaPromptOpen, setGatePersonaPromptOpen] = useState(false);
  const [gatePersonaPromptGateId, setGatePersonaPromptGateId] = useState('');
  const [gatePersonaDraftLabel, setGatePersonaDraftLabel] = useState('');
  const [gatePersonaPromptError, setGatePersonaPromptError] = useState('');
  const gatePersonaPromptSeenRef = useRef<Set<string>>(new Set());
  const [nativeAuditReport, setNativeAuditReport] = useState<DesktopControlAuditReport | null>(null);
  const gateDecryptCacheRef = useRef<Map<string, { plaintext: string; epoch: number; replyTo?: string }>>(new Map());
  const infoVerificationCacheRef = useRef<Map<string, 'verified' | 'failed' | 'unsigned'>>(
    new Map(),
  );
  const infoPollSignatureRef = useRef<string>('');
  const infoCursorRef = useRef(0);
  const selectedGateRef = useRef<string>('');
  const infoPollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const infoWaitAbortRef = useRef<AbortController | null>(null);

  const refreshNativeAuditReport = useCallback((limit: number = 5) => {
    setNativeAuditReport(getDesktopNativeControlAuditReport(limit));
  }, []);

  const voteScopeKey = useCallback((targetId: string, gateId: string = '') => {
    return `${String(gateId || 'public').trim().toLowerCase()}::${String(targetId || '').trim()}`;
  }, []);

  const focusInputComposer = useCallback(() => {
    const input = inputRef.current;
    if (!input) return;
    input.focus();
    const nextCursor = input.value.length;
    input.setSelectionRange(nextCursor, nextCursor);
    setInputFocused(true);
    setInputCursorIndex(nextCursor);
  }, []);

  const markGateResyncRequired = useCallback((err: unknown, gateIdHint?: string): boolean => {
    const gateId = String(extractNativeGateResyncTarget(err) || gateIdHint || '')
      .trim()
      .toLowerCase();
    if (!gateId) return false;
    setGateResyncTarget(gateId);
    return true;
  }, []);

  const clearGateResyncRequired = useCallback((gateId?: string) => {
    const normalized = String(gateId || '')
      .trim()
      .toLowerCase();
    setGateResyncTarget((prev) => {
      if (!prev) return prev;
      if (!normalized) return '';
      return prev === normalized ? '' : prev;
    });
  }, []);

  const handleReplyToGateMessage = useCallback(
    (message: InfoNetMessage) => {
      const eventId = String(message.event_id || '').trim();
      const gateId = String(message.gate || selectedGate || '').trim().toLowerCase();
      const nodeId = String(message.node_id || '').trim();
      if (!eventId || !gateId || !nodeId) return;
      setGateReplyContext({ eventId, gateId, nodeId });
      focusInputComposer();
    },
    [focusInputComposer, selectedGate],
  );

  const hydrateInfonetMessages = useCallback(
    async (messages: InfoNetMessage[]): Promise<InfoNetMessage[]> => {
      const baseMessages = (Array.isArray(messages) ? messages : []).map(normalizeInfoNetMessage);
      if (!wormholeEnabled || !wormholeReadyState) {
        return baseMessages.map((message) => ({ ...message, decrypted_message: '' }));
      }
      const hydrated: Array<InfoNetMessage | null> = baseMessages.map((message) => {
        if (!isEncryptedGateEnvelope(message)) {
          return { ...message, decrypted_message: '' };
        }
        const cacheKey = gateDecryptCacheKey(message);
        const cached = gateDecryptCacheRef.current.get(cacheKey);
        if (!cached) {
          return null;
        }
        gateDecryptCacheRef.current.delete(cacheKey);
        gateDecryptCacheRef.current.set(cacheKey, cached);
        return {
          ...message,
          epoch: Number(cached.epoch || message.epoch || 0),
          decrypted_message: String(cached.plaintext || ''),
          reply_to: String(cached.replyTo || message.reply_to || ''),
        };
      });

      const pendingDecrypts = baseMessages
        .map((message, index) => ({ index, message }))
        .filter(({ message, index }) => isEncryptedGateEnvelope(message) && hydrated[index] === null)
        .map(({ index, message }) => ({
          index,
          message,
          cacheKey: gateDecryptCacheKey(message),
        }));

      if (pendingDecrypts.length > 0) {
        try {
          const batch = await decryptWormholeGateMessages(
            pendingDecrypts.map(({ message }) => ({
              gate_id: String(message.gate || ''),
              epoch: 0,
              ciphertext: String(message.ciphertext || ''),
              nonce: String(message.nonce || ''),
              sender_ref: String(message.sender_ref || ''),
              format: String(message.format || 'mls1'),
              gate_envelope: String(message.gate_envelope || ''),
              envelope_hash: String(message.envelope_hash || ''),
            })),
          );
          const results = Array.isArray(batch.results) ? batch.results : [];
          const compatDecryptBlocked = results.some(
            (result) => !result?.ok && String(result?.detail || '') === 'gate_backend_decrypt_recovery_only',
          );
          if (compatDecryptBlocked) {
            setGateError(
              'Service-side gate decrypt is disabled on this runtime. Use native desktop or an explicit recovery path.',
            );
          }
          pendingDecrypts.forEach(({ index, message, cacheKey }, resultIndex) => {
            const decrypted = results[resultIndex];
            if (decrypted?.ok) {
              const selfAuthored = Boolean(decrypted.self_authored);
              const entry = {
                epoch: Number(decrypted.epoch || message.epoch || 0),
                plaintext: selfAuthored && !decrypted.plaintext
                  ? (decrypted.legacy
                    ? '[legacy gate message — pre-encryption-fix]'
                    : '[your message — plaintext not cached]')
                  : String(decrypted.plaintext || ''),
                replyTo: String(decrypted.reply_to || '').trim(),
              };
              if (gateDecryptCacheRef.current.has(cacheKey)) {
                gateDecryptCacheRef.current.delete(cacheKey);
              }
              gateDecryptCacheRef.current.set(cacheKey, entry);
              if (gateDecryptCacheRef.current.size > GATE_DECRYPT_CACHE_MAX) {
                const oldestKey = gateDecryptCacheRef.current.keys().next().value;
                if (oldestKey) {
                  gateDecryptCacheRef.current.delete(oldestKey);
                }
              }
              hydrated[index] = {
                ...message,
                epoch: entry.epoch,
                decrypted_message: entry.plaintext,
                reply_to: entry.replyTo || String(message.reply_to || ''),
              };
              return;
            }
            hydrated[index] = { ...message, decrypted_message: '' };
          });
        } catch (err) {
          const gateIdHint = String(pendingDecrypts[0]?.message?.gate || '').trim().toLowerCase();
          const detail = err instanceof Error ? err.message : '';
          if (
            detail === 'gate_compat_fallback_consent_required' ||
            detail.startsWith('gate_local_runtime_required:')
          ) {
            setGateError(describeGateLocalRuntimeRequired(detail, gateIdHint));
          } else if (markGateResyncRequired(err, gateIdHint)) {
            setGateError(
              describeNativeControlError(err) || 'Gate state changed on another path. Resync before retrying.',
            );
          }
          pendingDecrypts.forEach(({ index, message }) => {
            hydrated[index] = { ...message, decrypted_message: '' };
          });
        }
      }

      return hydrated.map(
        (message, index) => message ?? { ...baseMessages[index], decrypted_message: '' },
      );
    },
    [markGateResyncRequired, wormholeEnabled, wormholeReadyState],
  );

  useEffect(() => {
    selectedGateRef.current = String(selectedGate || '').trim().toLowerCase();
    infoCursorRef.current = 0;
  }, [selectedGate]);

  const refreshInfonetMessages = useCallback(
    async ({
      gateId,
      force = false,
      snapshot,
      proofMode,
    }: {
      gateId?: string;
      force?: boolean;
      snapshot?: GateMessageSnapshotState;
      proofMode?: GateAccessHeaderMode;
    } = {}): Promise<boolean> => {
      try {
        const targetGate = String(gateId ?? selectedGateRef.current ?? '')
          .trim()
          .toLowerCase();
        let rawMessages: InfoNetMessage[] = [];
        if (targetGate) {
          const nextSnapshot =
            snapshot ??
            (await fetchGateMessageSnapshotState(targetGate, ACTIVE_GATE_ROOM_MESSAGE_LIMIT, {
              force,
              proofMode,
            }));
          if (targetGate === selectedGateRef.current) {
            infoCursorRef.current = nextSnapshot.cursor;
          }
          rawMessages = nextSnapshot.messages.map((message) =>
            normalizeInfoNetMessage(message as InfoNetMessage),
          );
        } else {
          infoCursorRef.current = 0;
          const params = new URLSearchParams({ limit: '30' });
          const res = await fetch(`${API_BASE}/api/mesh/infonet/messages?${params}`);
          if (!res.ok) {
            return false;
          }
          const data = await res.json();
          rawMessages = Array.isArray(data.messages)
            ? (data.messages as InfoNetMessage[]).map(normalizeInfoNetMessage)
            : [];
        }
        const pollSignature = [
          targetGate,
          wormholeEnabled ? '1' : '0',
          wormholeReadyState ? '1' : '0',
          rawMessages.map((message) => String(message.event_id || '')).join('|'),
        ].join('::');
        if (targetGate && targetGate !== selectedGateRef.current) {
          return true;
        }
        if (force || infoPollSignatureRef.current !== pollSignature) {
          const hydrated = await hydrateInfonetMessages(rawMessages);
          if (targetGate && targetGate !== selectedGateRef.current) {
            return true;
          }
          infoPollSignatureRef.current = pollSignature;
          setInfoMessages(hydrated.reverse());
        } else {
          infoPollSignatureRef.current = pollSignature;
        }

        const nodeIds = [
          ...new Set(
            rawMessages
              .map((message: InfoNetMessage) => String(message.node_id || '').trim())
              .filter(Boolean),
          ),
        ];
        const uncachedNodeIds = nodeIds.filter(
          (nid) => !Object.prototype.hasOwnProperty.call(repsRef.current, nid),
        );
        if (uncachedNodeIds.length > 0) {
          try {
            const repParams = new URLSearchParams();
            uncachedNodeIds.slice(0, 100).forEach((nid) => repParams.append('node_id', nid));
            const repRes = await fetch(`${API_BASE}/api/mesh/reputation/batch?${repParams.toString()}`);
            if (repRes.ok) {
              const repData = await repRes.json();
              const reputations =
                repData && typeof repData.reputations === 'object' && repData.reputations
                  ? repData.reputations
                  : {};
              setReps((prev) => {
                let changed = false;
                const next = { ...prev };
                for (const [nid, value] of Object.entries(reputations)) {
                  const overall = Number(value || 0);
                  if (next[nid] !== overall) {
                    next[nid] = overall;
                    changed = true;
                  }
                }
                return changed ? next : prev;
              });
            }
          } catch {
            /* ignore */
          }
        }
        return true;
      } catch {
        return false;
      }
    },
    [hydrateInfonetMessages, wormholeEnabled, wormholeReadyState],
  );

  // ─── Meshtastic State ────────────────────────────────────────────────────
  const [meshRegion, setMeshRegion] = useState('US');
  const [meshRoots, setMeshRoots] = useState<string[]>([...DEFAULT_MESH_ROOTS]);
  const [meshChannel, setMeshChannel] = useState('LongFast');
  const [meshChannels, setMeshChannels] = useState<string[]>(['LongFast']);
  const [activeChannels, setActiveChannels] = useState<Set<string>>(new Set());
  const [meshMessages, setMeshMessages] = useState<MeshtasticMessage[]>([]);

  // ─── DM / Dead Drop State ────────────────────────────────────────────────
  const [contacts, setContacts] = useState<Record<string, Contact>>({});
  const [selectedContact, setSelectedContact] = useState<string>('');
  const [dmView, setDmView] = useState<DMView>('contacts');
  const [dmMessages, setDmMessages] = useState<DMMessage[]>([]);
  const [dmMaintenanceBusy, setDmMaintenanceBusy] = useState(false);
  const [lastDmTransport, setLastDmTransport] = useState<'reticulum' | 'relay' | ''>('');
  const [anonymousModeEnabled, setAnonymousModeEnabled] = useState(false);
  const [anonymousModeReady, setAnonymousModeReady] = useState(false);
  const anonymousPublicBlocked = anonymousModeEnabled && !anonymousModeReady;
  const anonymousDmBlocked = anonymousModeEnabled && !anonymousModeReady;
  const secureDmBlocked = (wormholeEnabled && !wormholeReadyState) || anonymousDmBlocked;
  const [sasPhrase, setSasPhrase] = useState<string>('');
  const [showSas, setShowSas] = useState<boolean>(false);
  const [sasConfirmInput, setSasConfirmInput] = useState<string>('');
  const [geoHintEnabled, setGeoHintEnabledState] = useState<boolean>(false);
  const [decoyEnabled, setDecoyEnabledState] = useState<boolean>(false);
  const [dmUnread, setDmUnread] = useState(0);
  const [accessRequests, setAccessRequestsState] = useState<AccessRequest[]>([]);
  const [pendingSent, setPendingSentState] = useState<string[]>([]);
  const [addContactId, setAddContactId] = useState('');
  const [showAddContact, setShowAddContact] = useState(false);
  const [inputCursorIndex, setInputCursorIndex] = useState(0);
  const [inputFocused, setInputFocused] = useState(false);
  const dmConsentScopeId = identity?.nodeId || '';

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const cursorMirrorRef = useRef<HTMLDivElement>(null);
  const cursorMarkerRef = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const el = messagesEndRef.current;
    if (!el) return;
    // Find the nearest scrollable ancestor (overflow-y: auto/scroll) and scroll
    // only that container — NOT the outer HUD panel which causes the whole UI to jump.
    let container = el.parentElement;
    while (container) {
      const overflow = getComputedStyle(container).overflowY;
      if (overflow === 'auto' || overflow === 'scroll') break;
      container = container.parentElement;
    }
    if (container) {
      container.scrollTop = container.scrollHeight;
    }
  }, [infoMessages, meshMessages, dmMessages]);

  useEffect(() => {
    if (expanded) setTimeout(() => inputRef.current?.focus(), 100);
  }, [expanded, activeTab]);

  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = '0px';
    const nextHeight = Math.min(Math.max(el.scrollHeight, 18), 96);
    el.style.height = `${nextHeight}px`;
    el.style.overflowY = el.scrollHeight > 96 ? 'auto' : 'hidden';
  }, [inputValue, expanded, activeTab]);

  useEffect(() => {
    const el = inputRef.current;
    const mirror = cursorMirrorRef.current;
    if (!el || !mirror) return;
    mirror.scrollTop = el.scrollTop;
  }, [inputValue, inputCursorIndex, expanded, activeTab]);

  const syncCursorPosition = useCallback(() => {
    const el = inputRef.current;
    if (!el) return;
    setInputCursorIndex(el.selectionStart ?? inputValue.length);
  }, [inputValue.length]);


  useEffect(() => {
    repsRef.current = reps;
  }, [reps]);

  // Load request/contact metadata from identity-bound encrypted browser storage.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const [requests, pending] = await Promise.all([
        getAccessRequests(dmConsentScopeId),
        getPendingSent(dmConsentScopeId),
      ]);
      if (cancelled) return;
      setAccessRequestsState(requests);
      setPendingSentState(pending);
    })();
    setGeoHintEnabledState(getGeoHintEnabled());
    setDecoyEnabledState(getDecoyEnabled());
    return () => {
      cancelled = true;
    };
  }, [expanded, activeTab, dmConsentScopeId]);

  useEffect(() => {
    if (!launchRequest) return;
    setExpanded(true);
    setActiveTab(launchRequest.tab);
    if (launchRequest.tab === 'infonet' && launchRequest.gate) {
      setSelectedGate(String(launchRequest.gate || '').trim().toLowerCase());
    }
    if (launchRequest.tab === 'dms') {
      const peerId = String(launchRequest.peerId || '').trim();
      if (peerId) {
        setSelectedContact(peerId);
        setDmView('chat');
        setDmMessages([]);
        setShowSas(Boolean(launchRequest.showSas));
      } else {
        setDmView('contacts');
      }
    }
    if (launchRequest.tab === 'meshtastic') {
      setMeshView('channel');
    }
  }, [launchRequest?.nonce]);

  useEffect(() => {
    if (activeTab !== 'infonet' || privateInfonetReady) {
      setInfonetUnlockOpen(false);
    }
  }, [activeTab, privateInfonetReady]);

  useEffect(() => {
    if (activeTab !== 'dms' || !secureDmBlocked) {
      setDeadDropUnlockOpen(false);
    }
  }, [activeTab, secureDmBlocked]);

  // ─── Filtered messages (exclude muted users) ─────────────────────────────

  const filteredInfoMessages = useMemo(
    () => infoMessages.filter((m) => !m.node_id || !mutedUsers.has(m.node_id)),
    [infoMessages, mutedUsers],
  );
  const filteredMeshMessages = useMemo(
    () => meshMessages.filter((m) => !mutedUsers.has(m.from)),
    [meshMessages, mutedUsers],
  );
  const meshInboxMessages = useMemo(() => {
    if (!publicMeshAddress) return [];
    const target = publicMeshAddress.toLowerCase();
    return filteredMeshMessages.filter((m) => String(m.to || '').toLowerCase() === target);
  }, [filteredMeshMessages, publicMeshAddress]);

  // ─── InfoNet Polling ─────────────────────────────────────────────────────

  useEffect(() => {
    if (!expanded) return;
    const fetchGates = async () => {
      try {
        const nextGates = (await fetchGateCatalogSnapshot()).map(gateCatalogEntryToGate);
        setGates(nextGates);
        if (nextGates.length > 0) {
          setSelectedGate((prev) => prev || String(nextGates[0].gate_id || '').trim().toLowerCase());
        }
      } catch {
        /* ignore */
      }
    };
    void fetchGates();
  }, [expanded]);

  useEffect(() => {
    if (!wormholeEnabled || !wormholeReadyState) return;
    let cancelled = false;
    const nextGate = selectedGate.trim().toLowerCase();

    const ensureGateAccess = async () => {
      try {
        if (activeGateSessionRef.current !== nextGate) {
          activeGateSessionRef.current = '';
          infoPollSignatureRef.current = '';
          if (!cancelled) {
            setInfoMessages([]);
          }
        }
        if (!nextGate) return;
        if (activeGateSessionRef.current === nextGate) return;

        const personasData = await listWormholeGatePersonas(nextGate).catch(() => null);
        if (cancelled) return;
        const personas =
          personasData?.ok && Array.isArray(personasData.personas) ? personasData.personas : [];
        const activePersonaId =
          personasData?.ok ? String(personasData.active_persona_id || '').trim() : '';
        if (personasData?.ok) {
          setGatePersonas((prev) => ({ ...prev, [nextGate]: personas }));
          setActiveGatePersonaId((prev) => ({
            ...prev,
            [nextGate]: activePersonaId,
          }));
        }

        let status = await fetchWormholeGateKeyStatus(nextGate, { mode: 'active_room' }).catch(() => null);
        if (cancelled) return;
        if (status) {
          const nextStatus = status as WormholeGateKeyStatus;
          setGateKeyStatus((prev) => ({ ...prev, [nextGate]: nextStatus }));
        }
        if (status?.ok && status.has_local_access) {
          await syncBrowserWormholeGateState(nextGate).catch(() => false);
          activeGateSessionRef.current = nextGate;
          setGateError('');
          return;
        }
        if (!activePersonaId) {
          const entered = await enterWormholeGate(nextGate, false).catch(() => null);
          if (cancelled || !entered?.ok) {
            if (!cancelled) {
              setGateError(String(entered?.detail || 'Failed to enter anonymous gate session'));
            }
            return;
          }
          status = await fetchWormholeGateKeyStatus(nextGate, { mode: 'active_room' }).catch(() => null);
          if (cancelled) return;
          if (status) {
            const nextStatus = status as WormholeGateKeyStatus;
            setGateKeyStatus((prev) => ({ ...prev, [nextGate]: nextStatus }));
          }
          if (!cancelled && status?.ok && status.has_local_access) {
            await syncBrowserWormholeGateState(nextGate).catch(() => false);
            setGateError('');
            activeGateSessionRef.current = nextGate;
            return;
          }
        } else {
          const ensured = await activateWormholeGatePersona(nextGate, activePersonaId).catch(() => null);
          if (cancelled || !ensured?.ok) {
            if (!cancelled) {
              setGateError(String(ensured?.detail || 'Failed to activate gate face'));
            }
            return;
          }
          status = await fetchWormholeGateKeyStatus(nextGate, { mode: 'active_room' }).catch(() => null);
          if (cancelled) return;
          if (status) {
            const nextStatus = status as WormholeGateKeyStatus;
            setGateKeyStatus((prev) => ({ ...prev, [nextGate]: nextStatus }));
          }
          if (!cancelled && status?.ok && status.has_local_access) {
            await syncBrowserWormholeGateState(nextGate).catch(() => false);
            setGateError('');
            activeGateSessionRef.current = nextGate;
            return;
          }
        }

        if (!cancelled) {
          setGateError(String(status?.detail || 'Failed to prepare private gate access'));
        }
      } catch {
        if (!cancelled) {
          setGateError('Failed to prepare private gate access');
        }
      }
    };

    void ensureGateAccess();
    return () => {
      cancelled = true;
    };
  }, [selectedGate, wormholeEnabled, wormholeReadyState]);

  useEffect(() => {
    return () => {
      activeGateSessionRef.current = '';
    };
  }, []);

  useEffect(() => {
    if (!wormholeEnabled || !wormholeReadyState || !selectedGate) return;
    let cancelled = false;
    const gateId = selectedGate.trim().toLowerCase();
    const loadGatePersonas = async () => {
      try {
        const data = await listWormholeGatePersonas(gateId).catch(() => null);
        if (!data?.ok || cancelled) return;
        setGatePersonas((prev) => ({ ...prev, [gateId]: Array.isArray(data.personas) ? data.personas : [] }));
        setActiveGatePersonaId((prev) => ({
          ...prev,
          [gateId]: String(data.active_persona_id || ''),
        }));
      } catch {
        /* ignore */
      }
    };
    loadGatePersonas();
    return () => {
      cancelled = true;
    };
  }, [selectedGate, wormholeEnabled, wormholeReadyState]);

  useEffect(() => {
    if (!gateReplyContext) return;
    if (!selectedGate || gateReplyContext.gateId !== String(selectedGate || '').trim().toLowerCase()) {
      setGateReplyContext(null);
    }
  }, [gateReplyContext, selectedGate]);

  const streamEnabledForSelectedGate =
    Boolean(selectedGate) &&
    gateSessionStreamStatus.phase === 'open' &&
    gateSessionStreamStatus.subscriptions.includes(String(selectedGate || '').trim().toLowerCase());
  const streamPreferredForSelectedGate =
    Boolean(selectedGate) &&
    (gateSessionStreamStatus.phase === 'connecting' || gateSessionStreamStatus.phase === 'open') &&
    gateSessionStreamStatus.subscriptions.includes(String(selectedGate || '').trim().toLowerCase());

  useEffect(() => {
    if (!wormholeEnabled || !wormholeReadyState || !selectedGate) return;
    let cancelled = false;
    const gateId = selectedGate.trim().toLowerCase();
    const loadGateKeyStatus = async () => {
      try {
        const data = await fetchWormholeGateKeyStatus(gateId, {
          mode: streamPreferredForSelectedGate ? 'session_stream' : 'active_room',
        }).catch(() => null);
        if (!data || cancelled) return;
        if (data.ok && data.has_local_access && !streamPreferredForSelectedGate) {
          void syncBrowserWormholeGateState(gateId).catch(() => false);
        }
        setGateKeyStatus((prev) => ({ ...prev, [gateId]: data }));
      } catch {
        /* ignore */
      }
    };
    void loadGateKeyStatus();
    return () => {
      cancelled = true;
    };
  }, [selectedGate, wormholeEnabled, wormholeReadyState, gatePersonaBusy, streamPreferredForSelectedGate]);

  useEffect(() => {
    if (
      !expanded ||
      activeTab !== 'infonet' ||
      !wormholeEnabled ||
      !wormholeReadyState ||
      !selectedGate
    ) {
      return;
    }
    const gateId = selectedGate.trim().toLowerCase();
    const gateStatus = gateId ? gateKeyStatus[gateId] || null : null;
    if (!gateId || !gateStatus?.has_local_access || gatePersonaBusy || gatePersonaPromptOpen) {
      return;
    }
    return retainGateSessionStreamGate(gateId);
  }, [
    expanded,
    activeTab,
    selectedGate,
    gateKeyStatus,
    gatePersonaBusy,
    gatePersonaPromptOpen,
    wormholeEnabled,
    wormholeReadyState,
  ]);

  useEffect(() => {
    streamEnabledForSelectedGateRef.current = streamPreferredForSelectedGate;
  }, [streamPreferredForSelectedGate]);

  useEffect(() => {
    if (
      !expanded ||
      activeTab !== 'infonet' ||
      !wormholeEnabled ||
      !wormholeReadyState ||
      !streamEnabledForSelectedGate
    ) {
      return;
    }
    return subscribeGateSessionStreamEvents((event) => {
      if (event.event !== 'gate_update' || !event.data || typeof event.data !== 'object') {
        return;
      }
      const activeGateId = String(selectedGateRef.current || '').trim().toLowerCase();
      if (!activeGateId) {
        return;
      }
      const updates = Array.isArray((event.data as { updates?: unknown }).updates)
        ? ((event.data as { updates?: Array<{ gate_id?: string; cursor?: number }> }).updates || [])
        : [];
      const matching = updates.find(
        (update) => String(update?.gate_id || '').trim().toLowerCase() === activeGateId,
      );
      if (!matching) {
        return;
      }
      void refreshInfonetMessages({
        gateId: activeGateId,
        force: true,
        proofMode: 'session_stream',
      });
    });
  }, [
    activeTab,
    expanded,
    refreshInfonetMessages,
    streamEnabledForSelectedGate,
    wormholeEnabled,
    wormholeReadyState,
  ]);

  useEffect(() => {
    setGateCompatConsentPrompt(null);
    const gateId = String(selectedGate || '').trim().toLowerCase();
    if (!gateId) return;
    setGateCompatActive((prev) => {
      if (hasGateCompatFallbackApproval(gateId)) {
        return prev[gateId] ? prev : { ...prev, [gateId]: true };
      }
      if (!prev[gateId]) return prev;
      const next = { ...prev };
      delete next[gateId];
      return next;
    });
  }, [selectedGate]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const handleCompatFallback = (event: Event) => {
      const detail =
        event instanceof CustomEvent && event.detail && typeof event.detail === 'object'
          ? (event.detail as { gateId?: string })
          : null;
      const eventGateId = String(detail?.gateId || '').trim().toLowerCase();
      if (!eventGateId) return;
      setGateCompatActive((prev) => (prev[eventGateId] ? prev : { ...prev, [eventGateId]: true }));
    };
    window.addEventListener('sb:gate-compat-fallback', handleCompatFallback as EventListener);
    return () => {
      window.removeEventListener('sb:gate-compat-fallback', handleCompatFallback as EventListener);
    };
  }, []);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const handleCompatConsentRequired = (event: Event) => {
      const detail =
        event instanceof CustomEvent && event.detail && typeof event.detail === 'object'
          ? (event.detail as GateCompatConsentPromptState)
          : null;
      const eventGateId = String(detail?.gateId || '').trim().toLowerCase();
      if (!eventGateId || eventGateId !== selectedGateRef.current || !detail) {
        return;
      }
      setGateCompatConsentPrompt({
        gateId: eventGateId,
        action: detail.action,
        reason: String(detail.reason || ''),
      });
      setGateError('Local gate crypto is unavailable for this room.');
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
  }, []);

  useEffect(() => {
    if (
      activeTab !== 'infonet' ||
      !wormholeEnabled ||
      !wormholeReadyState ||
      !selectedGate ||
      gatePersonaBusy ||
      gatePersonaPromptOpen
    ) {
      return;
    }
    const gateId = selectedGate.trim().toLowerCase();
    if (!gateId || gatePersonaPromptSeenRef.current.has(gateId)) return;
    const status = gateKeyStatus[gateId];
    const knownPersonas = gatePersonas[gateId] || [];
    if (!status || status.identity_scope !== 'anonymous' || status.has_local_access) return;
    if (knownPersonas.length === 0) return;
    gatePersonaPromptSeenRef.current.add(gateId);
    setGatePersonaPromptGateId(gateId);
    setGatePersonaDraftLabel('');
    setGatePersonaPromptError('');
    setGatePersonaPromptOpen(true);
  }, [
    activeTab,
    gateKeyStatus,
    gatePersonas,
    gatePersonaBusy,
    gatePersonaPromptOpen,
    selectedGate,
    wormholeEnabled,
    wormholeReadyState,
  ]);

  useEffect(() => {
    if (!gatePersonaPromptOpen) return;
    const gateId = selectedGate.trim().toLowerCase();
    if (!gateId || (gatePersonaPromptGateId && gatePersonaPromptGateId !== gateId)) {
      setGatePersonaPromptOpen(false);
      setGatePersonaPromptGateId('');
      setGatePersonaDraftLabel('');
      setGatePersonaPromptError('');
    }
  }, [gatePersonaPromptGateId, gatePersonaPromptOpen, selectedGate]);

  useEffect(() => {
    if (!gateSessionStreamHydrated) return;
    const isLiveStreamPreferredForSelectedGate = () => {
      const liveStreamStatus = getGateSessionStreamStatus();
      return (
        Boolean(selectedGate) &&
        (liveStreamStatus.phase === 'connecting' || liveStreamStatus.phase === 'open') &&
        liveStreamStatus.subscriptions.includes(String(selectedGate || '').trim().toLowerCase())
      );
    };
    const liveStreamPreferredForSelectedGateNow =
      streamPreferredForSelectedGate || isLiveStreamPreferredForSelectedGate();
    streamEnabledForSelectedGateRef.current = liveStreamPreferredForSelectedGateNow;
    if (!expanded || activeTab !== 'infonet') return;
    const gateId = selectedGate.trim().toLowerCase();
    const gateStatus = gateId ? gateKeyStatus[gateId] || null : null;
    const gateAccessReady = !gateId || Boolean(gateStatus?.has_local_access);
    if (gateId && (!gateAccessReady || gatePersonaBusy || gatePersonaPromptOpen)) {
      return;
    }
    let cancelled = false;
    const clearRetry = () => {
      if (infoPollTimerRef.current) {
        clearTimeout(infoPollTimerRef.current);
        infoPollTimerRef.current = null;
      }
    };

    const scheduleRetry = () => {
      if (cancelled || streamEnabledForSelectedGateRef.current) return;
      clearRetry();
      infoPollTimerRef.current = setTimeout(() => {
        infoPollTimerRef.current = null;
        void runNext();
      }, nextGateMessagesPollDelayMs());
    };

    const startWaitIfNeeded = () => {
      queueMicrotask(() => {
        streamEnabledForSelectedGateRef.current =
          streamPreferredForSelectedGate || isLiveStreamPreferredForSelectedGate();
        if (!cancelled && !streamEnabledForSelectedGateRef.current) {
          void runNext();
        }
      });
    };

    const runNext = async () => {
      streamEnabledForSelectedGateRef.current =
        streamPreferredForSelectedGate || isLiveStreamPreferredForSelectedGate();
      if (cancelled || streamEnabledForSelectedGateRef.current) return;
      if (!gateId) {
        const ok = await refreshInfonetMessages({ gateId: '' });
        if (cancelled) return;
        if (!ok) {
          scheduleRetry();
          return;
        }
        scheduleRetry();
        return;
      }
      const controller = new AbortController();
      infoWaitAbortRef.current = controller;
      try {
        const snapshot = await waitForGateMessageSnapshot(
          gateId,
          infoCursorRef.current,
          ACTIVE_GATE_ROOM_MESSAGE_LIMIT,
          {
          timeoutMs: nextGateMessagesWaitTimeoutMs(),
          signal: controller.signal,
          },
        );
        infoWaitAbortRef.current = null;
        if (cancelled) return;
        infoCursorRef.current = snapshot.cursor;
        if (snapshot.changed) {
          await refreshInfonetMessages({ gateId, snapshot });
          void runNext();
          return;
        }
        clearRetry();
        infoPollTimerRef.current = setTimeout(() => {
          infoPollTimerRef.current = null;
          void runNext();
        }, nextGateMessagesWaitRearmDelayMs());
      } catch {
        infoWaitAbortRef.current = null;
        if (cancelled || controller.signal.aborted) {
          return;
        }
        const ok = await refreshInfonetMessages({ gateId, force: true });
        if (cancelled) return;
        if (!ok) {
          scheduleRetry();
          return;
        }
        startWaitIfNeeded();
      }
    };

    if (gateId && liveStreamPreferredForSelectedGateNow) {
      void refreshInfonetMessages({ gateId, proofMode: 'session_stream' });
      return () => {
        cancelled = true;
        clearRetry();
        if (infoWaitAbortRef.current) {
          infoWaitAbortRef.current.abort();
          infoWaitAbortRef.current = null;
        }
      };
    }

    void refreshInfonetMessages({ gateId: selectedGate }).then((ok) => {
      streamEnabledForSelectedGateRef.current =
        streamPreferredForSelectedGate || isLiveStreamPreferredForSelectedGate();
      if (cancelled) return;
      if (!ok) {
        scheduleRetry();
        return;
      }
      if (!streamEnabledForSelectedGateRef.current) {
        startWaitIfNeeded();
      }
    });

    return () => {
      cancelled = true;
      clearRetry();
      if (infoWaitAbortRef.current) {
        infoWaitAbortRef.current.abort();
        infoWaitAbortRef.current = null;
      }
    };
  }, [
    expanded,
    activeTab,
    selectedGate,
    gateKeyStatus,
    gatePersonaBusy,
    gatePersonaPromptOpen,
    gateSessionStreamHydrated,
    refreshInfonetMessages,
    streamPreferredForSelectedGate,
  ]);

  useEffect(() => {
    return () => {
      if (infoPollTimerRef.current) {
        clearTimeout(infoPollTimerRef.current);
        infoPollTimerRef.current = null;
      }
      if (infoWaitAbortRef.current) {
        infoWaitAbortRef.current.abort();
        infoWaitAbortRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      if (!infoMessages.length) {
        setInfoVerification({});
        return;
      }
      const results: Record<string, 'verified' | 'failed' | 'unsigned'> = {};
      const toVerify = infoMessages.filter((message) => {
        const eventType = message.event_type || (message.gate ? 'gate_message' : 'message');
        if (eventType === 'gate_message') {
          return false;
        }
        const cacheKey = String(message.event_id || '').trim();
        if (cacheKey && infoVerificationCacheRef.current.has(cacheKey)) {
          results[cacheKey] = infoVerificationCacheRef.current.get(cacheKey)!;
          return false;
        }
        return true;
      });
      const verified = await Promise.all(
        toVerify.map(async (m) => {
          if (!m.signature || !m.public_key || !m.public_key_algo || !m.sequence) {
            return [String(m.event_id || ''), 'unsigned'] as const;
          }
          const eventType = m.event_type || (m.gate ? 'gate_message' : 'message');
          const payload = {
            message: m.message,
            destination: m.destination ?? 'broadcast',
            channel: m.channel ?? 'LongFast',
            priority: m.priority ?? 'normal',
            ephemeral: Boolean(m.ephemeral),
          };
          const ok = await verifyEventSignature({
            eventType,
            nodeId: String(m.node_id || ''),
            sequence: m.sequence || 0,
            payload,
            signature: m.signature,
            publicKey: m.public_key,
            publicKeyAlgo: m.public_key_algo,
          });
          return [String(m.event_id || ''), ok ? 'verified' : 'failed'] as const;
        }),
      );
      for (const [eventId, status] of verified) {
        if (!eventId) continue;
        results[eventId] = status;
        infoVerificationCacheRef.current.set(eventId, status);
        if (infoVerificationCacheRef.current.size > INFO_VERIFICATION_CACHE_MAX) {
          const oldestKey = infoVerificationCacheRef.current.keys().next().value;
          if (oldestKey) {
            infoVerificationCacheRef.current.delete(oldestKey);
          }
        }
      }
      if (!cancelled) setInfoVerification(results);
    };
    run();
    return () => {
      cancelled = true;
    };
  }, [infoMessages]);

  // ─── Meshtastic Channel Discovery ──────────────────────────────────────
  useEffect(() => {
    if (!expanded || activeTab !== 'meshtastic') return;
    let cancelled = false;
    const fetchChannels = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/mesh/channels`);
        if (res.ok && !cancelled) {
          const stats = await res.json();
          const rootCounts: Record<string, number> = {};
          const knownRoots = Array.isArray(stats.known_roots) ? stats.known_roots : [];
          Object.entries((stats.roots || {}) as Record<string, { nodes?: number }>).forEach(
            ([root, data]) => {
              rootCounts[root] = Number(data?.nodes || 0);
            },
          );
          const roots = sortMeshRoots(
            [...DEFAULT_MESH_ROOTS, ...knownRoots, ...Object.keys(rootCounts), meshRegion],
            rootCounts,
            meshRegion,
          );
          setMeshRoots(roots);

          // Collect channels from selected root/region + global message log
          const chSet = new Set<string>(['LongFast']);
          const active = new Set<string>();
          const meshData = stats.roots?.[meshRegion] || stats.regions?.[meshRegion];
          if (meshData?.channels) {
            Object.entries(meshData.channels).forEach(([ch, count]) => {
              chSet.add(ch);
              if ((count as number) > 0) active.add(ch);
            });
          }
          if (stats.channel_messages) {
            Object.entries(stats.channel_messages).forEach(([ch, count]) => {
              chSet.add(ch);
              if ((count as number) > 0) active.add(ch);
            });
          }
          // Sort: LongFast first, then active channels, then alphabetical
          const sorted = Array.from(chSet).sort((a, b) => {
            if (a === 'LongFast') return -1;
            if (b === 'LongFast') return 1;
            const aActive = active.has(a) ? 0 : 1;
            const bActive = active.has(b) ? 0 : 1;
            if (aActive !== bActive) return aActive - bActive;
            return a.localeCompare(b);
          });
          setMeshChannels(sorted);
          setActiveChannels(active);
        }
      } catch {
        /* ignore */
      }
    };
    fetchChannels();
    const iv = setInterval(fetchChannels, 30000); // Refresh channel list every 30s
    return () => {
      cancelled = true;
      clearInterval(iv);
    };
  }, [expanded, activeTab, meshRegion]);

  // ─── Meshtastic Polling ──────────────────────────────────────────────────

  useEffect(() => {
    if (!expanded || activeTab !== 'meshtastic') return;
    let cancelled = false;
    const poll = async () => {
      try {
        const params = new URLSearchParams({
          limit: meshView === 'inbox' ? '100' : '30',
          region: meshRegion,
          channel: meshChannel,
        });
        const res = await fetch(`${API_BASE}/api/mesh/messages?${params}`);
        if (res.ok && !cancelled) {
          const data = await res.json();
          setMeshMessages(Array.isArray(data) ? [...data].reverse() : []);
        }
      } catch {
        /* ignore */
      }
    };
    poll();
    const iv = setInterval(poll, 8000);
    return () => {
      cancelled = true;
      clearInterval(iv);
    };
  }, [expanded, activeTab, meshRegion, meshChannel, meshView]);

  // ─── DM Polling ──────────────────────────────────────────────────────────

  useEffect(() => {
    setContacts(getContacts());
  }, [expanded, activeTab]);

  // Poll unread count — slower when collapsed to reduce network/CPU usage
  useEffect(() => {
    if (!hasId || !getDMNotify() || (expanded && activeTab === 'dms')) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const schedule = () => {
      const baseDelay = expanded ? DM_UNREAD_POLL_EXPANDED_MS : DM_UNREAD_POLL_COLLAPSED_MS;
      timer = setTimeout(
        poll,
        jitteredPollDelay(baseDelay, { profile: privacyProfile }),
      );
    };
    const poll = async () => {
      if (isDmPollBlocked(wormholeEnabled, wormholeReadyState, anonymousDmBlocked)) {
        if (!cancelled) setDmUnread(0);
        if (!cancelled) schedule();
        return;
      }
      try {
        const claims = await buildMailboxClaims(getContacts());
        const data = await countDmMailboxes(API_BASE, identity!, claims);
        if (data.ok && !cancelled) {
          setDmUnread(data.count || 0);
        } else if (!cancelled) {
          setUnresolvedSenderSealCount(0);
        }
      } catch {
        if (!cancelled) setUnresolvedSenderSealCount(0);
      } finally {
        if (!cancelled) schedule();
      }
    };
    poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [
    hasId,
    identity,
    expanded,
    activeTab,
    wormholeEnabled,
    wormholeReadyState,
    anonymousDmBlocked,
    privacyProfile,
  ]);

  // Poll DM messages — also detect access requests (messages from unknown senders)
  useEffect(() => {
    if (!expanded || activeTab !== 'dms' || !hasId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let catchUpBudget = MAX_CATCHUP_POLLS;
    const poll = async (includeCount = true) => {
      let hasMore = false;
      if (isDmPollBlocked(wormholeEnabled, wormholeReadyState, anonymousDmBlocked)) {
        if (!cancelled) {
          setDmMessages([]);
          setDmUnread(0);
        }
        return;
      }
      try {
        const claims = await buildMailboxClaims(getContacts());
        const pollPromise = pollDmMailboxes(API_BASE, identity!, claims);
        const countPromise = includeCount
          ? countDmMailboxes(API_BASE, identity!, claims).catch(() => ({ ok: false, count: 0 }))
          : null;
        const [data, countResult] = await Promise.all([pollPromise, countPromise]);
        if (data.ok && !cancelled) {
          hasMore = Boolean(data.has_more);
          if (countResult) {
            setDmUnread(Number(countResult.count || 0));
          }
          const msgs: DMMessage[] = (data.messages || []).map((message) => ({
            ...message,
            transport: message.transport || 'relay',
            sender_recovery_state: getSenderRecoveryState(message),
            seal_resolution_failed: getSenderRecoveryState(message) === 'failed',
          }));
          const currentContacts = getContacts();
          const newRequests: AccessRequest[] = [];
          const knownMsgs: DMMessage[] = [];
          let unresolvedSeals = 0;
          const secureRequired = await isWormholeSecureRequired();

          for (const rawMessage of msgs) {
            let m = { ...rawMessage };
            let parsedFromSeal: ReturnType<typeof parseDmConsentMessage> | null = null;
            const senderSeal = String(m.sender_seal || '');
            const recoveryRequired = requiresSenderRecovery(m);
            const allowOpaqueRequestInbox = shouldKeepUnresolvedRequestVisible(m);

            if (recoveryRequired && senderSeal) {
              for (const [contactId, contact] of Object.entries(currentContacts)) {
                if (!contact.dhPubKey || contact.blocked) continue;
                const resolved = await decryptSenderSealForContact(
                  senderSeal,
                  contact.dhPubKey,
                  contact,
                  identity!.nodeId,
                  m.msg_id,
                );
                if (resolved && shouldPromoteRecoveredSenderForKnownContact(resolved, contactId)) {
                  m = {
                    ...m,
                    sender_id: resolved.sender_id,
                    seal_verified: resolved.seal_verified,
                    sender_recovery_state: 'verified',
                  };
                  break;
                }
              }

              if (
                m.sender_id.startsWith('sealed:') &&
                m.ciphertext.startsWith('x3dh1:') &&
                (await canUseWormholeBootstrap())
              ) {
                try {
                  const requestText = await bootstrapDecryptAccessRequest('', m.ciphertext);
                  parsedFromSeal = parseDmConsentMessage(requestText);
                  if (parsedFromSeal?.kind === 'contact_offer' && parsedFromSeal.dh_pub_key) {
                    const resolved = await decryptSenderSealForContact(
                      senderSeal,
                      parsedFromSeal.dh_pub_key,
                      undefined,
                      identity!.nodeId,
                      m.msg_id,
                    );
                    if (resolved && shouldPromoteRecoveredSenderForBootstrap(resolved)) {
                      m = {
                        ...m,
                        sender_id: resolved.sender_id,
                        seal_verified: resolved.seal_verified,
                        sender_recovery_state: 'verified',
                      };
                    }
                  }
                } catch {
                  parsedFromSeal = null;
                }
              }

              if (m.sender_id.startsWith('sealed:')) {
                unresolvedSeals += 1;
                m = {
                  ...m,
                  seal_resolution_failed: true,
                  seal_verified: false,
                  sender_recovery_state: 'failed',
                };
              }
            }

            if (
              currentContacts[m.sender_id] &&
              currentContacts[m.sender_id].dhPubKey &&
              !currentContacts[m.sender_id].blocked
            ) {
              knownMsgs.push(m);
            } else if (
              !currentContacts[m.sender_id]?.blocked &&
              (!m.sender_id.startsWith('sealed:') || allowOpaqueRequestInbox)
            ) {
              // Unknown sender = access request
              const senderContact = currentContacts[m.sender_id];
              const existing = accessRequests;
              let consent = parsedFromSeal;
              try {
                if (!consent && m.ciphertext.startsWith('x3dh1:') && (await canUseWormholeBootstrap())) {
                  const requestText = await bootstrapDecryptAccessRequest(
                    allowOpaqueRequestInbox ? '' : m.sender_id,
                    m.ciphertext,
                  );
                  consent = parseDmConsentMessage(requestText);
                } else if (!consent && !secureRequired) {
                  const senderKey = await fetchDmPublicKey(
                    API_BASE,
                    m.sender_id,
                    senderContact?.invitePinnedPrekeyLookupHandle,
                  );
                  if (senderKey?.dh_pub_key) {
                    const sharedKey = await deriveSharedKey(String(senderKey.dh_pub_key));
                    const requestText = await decryptDM(m.ciphertext, sharedKey);
                    consent = parseDmConsentMessage(requestText);
                  }
                }
              } catch {
                consent = null;
              }
              if (consent?.kind === 'contact_accept' && consent.shared_alias) {
                const senderKey = await fetchDmPublicKey(
                  API_BASE,
                  m.sender_id,
                  senderContact?.invitePinnedPrekeyLookupHandle,
                ).catch(() => null);
                if (senderKey?.dh_pub_key) {
                  addContact(m.sender_id, String(senderKey.dh_pub_key), undefined, senderKey.dh_algo);
                  updateContact(m.sender_id, {
                    dhAlgo: senderKey.dh_algo,
                    remotePrekeyLookupMode:
                      String(senderKey.lookup_mode || '').trim().toLowerCase() ||
                      senderContact?.remotePrekeyLookupMode,
                    sharedAlias: consent.shared_alias,
                    previousSharedAliases: [],
                    pendingSharedAlias: undefined,
                    sharedAliasGraceUntil: undefined,
                    sharedAliasRotatedAt: Date.now(),
                  });
                  const remainingPending = pendingSent.filter((id) => id !== m.sender_id);
                  setPendingSent(remainingPending, dmConsentScopeId);
                  setPendingSentState(remainingPending);
                  setContacts(getContacts());
                }
                } else if (consent?.kind === 'contact_deny') {
                  const remainingPending = pendingSent.filter((id) => id !== m.sender_id);
                  setPendingSent(remainingPending, dmConsentScopeId);
                  setPendingSentState(remainingPending);
                } else {
                  const existingReq = existing.find((r) => r.sender_id === m.sender_id);
                  const shouldCreateUnresolvedRequest = shouldKeepUnresolvedRequestVisible(m);
                  if (!existingReq && (consent?.kind === 'contact_offer' || shouldCreateUnresolvedRequest)) {
                    newRequests.push({
                      sender_id: m.sender_id,
                      timestamp: m.timestamp,
                      dh_pub_key: consent?.kind === 'contact_offer' ? consent.dh_pub_key : undefined,
                      dh_algo: consent?.kind === 'contact_offer' ? consent.dh_algo : undefined,
                      geo_hint: consent?.kind === 'contact_offer' ? consent.geo_hint : undefined,
                      request_contract_version: m.request_contract_version,
                      sender_recovery_required: m.sender_recovery_required,
                      sender_recovery_state: m.sender_recovery_state,
                    });
                  } else if (
                    existingReq &&
                    consent?.kind === 'contact_offer' &&
                    !existingReq.dh_pub_key &&
                    consent.dh_pub_key
                  ) {
                    const updated = existing.map((r) =>
                      r.sender_id === m.sender_id
                        ? {
                          ...r,
                          dh_pub_key: consent.dh_pub_key,
                          dh_algo: consent.dh_algo || r.dh_algo,
                          geo_hint: consent.geo_hint || r.geo_hint,
                          request_contract_version: m.request_contract_version || r.request_contract_version,
                          sender_recovery_required:
                            m.sender_recovery_required ?? r.sender_recovery_required,
                          sender_recovery_state: m.sender_recovery_state || r.sender_recovery_state,
                        }
                        : r,
                    );
                  setAccessRequests(updated, dmConsentScopeId);
                  setAccessRequestsState(updated);
                }
              }
            }
          }

          // Save new access requests
          if (newRequests.length > 0) {
            const all = [...accessRequests, ...newRequests];
            setAccessRequests(all, dmConsentScopeId);
            setAccessRequestsState(all);
          }
          setUnresolvedSenderSealCount(unresolvedSeals);

          // Decrypt messages from selected contact
          if (selectedContact && dmView === 'chat') {
            const contactInfo = currentContacts[selectedContact];
            if (contactInfo?.dhPubKey) {
              const decrypted: DMMessage[] = [];
              const secureRequired = await isWormholeSecureRequired();
              for (const m of knownMsgs.filter((m) => m.sender_id === selectedContact)) {
                try {
                  let plaintext = '';
                  try {
                    plaintext = await ratchetDecryptDM(selectedContact, m.ciphertext);
                  } catch (err) {
                    const message =
                      typeof err === 'object' && err !== null && 'message' in err
                        ? String((err as { message?: string }).message)
                        : '';
                    if (message === 'legacy') {
                      if (secureRequired) {
                        throw new Error('legacy_dm_blocked_in_secure_mode');
                      }
                      const sharedKey = await deriveSharedKey(contactInfo.dhPubKey!);
                      plaintext = await decryptDM(m.ciphertext, sharedKey);
                    } else {
                      throw err;
                    }
                  }
                  let sealVerified: boolean | undefined;
                  let sealResolutionFailed = Boolean(m.seal_resolution_failed);
                  if (m.sender_seal) {
                    try {
                      const opened = await decryptSenderSealForContact(
                        m.sender_seal,
                        contactInfo.dhPubKey!,
                        contactInfo,
                        identity!.nodeId,
                        m.msg_id,
                      );
                      if (opened?.sender_id === m.sender_id) {
                        sealVerified = opened.seal_verified;
                      } else {
                        sealVerified = false;
                        sealResolutionFailed = true;
                      }
                    } catch {
                      sealVerified = false;
                      sealResolutionFailed = true;
                    }
                  }
                  const aliasRotate = parseAliasRotateMessage(plaintext);
                  if (aliasRotate?.shared_alias) {
                    updateContact(selectedContact, {
                      sharedAlias: aliasRotate.shared_alias,
                      pendingSharedAlias: undefined,
                      sharedAliasGraceUntil: undefined,
                      sharedAliasRotatedAt: Date.now(),
                      previousSharedAliases: mergeAliasHistory([
                        currentContacts[selectedContact]?.sharedAlias,
                        ...(currentContacts[selectedContact]?.previousSharedAliases || []),
                      ]),
                    });
                    setContacts(getContacts());
                    continue;
                  }
                  decrypted.push({
                    ...m,
                    plaintext,
                    seal_verified: sealVerified,
                    seal_resolution_failed: sealResolutionFailed,
                  });
                } catch {
                  decrypted.push({ ...m, plaintext: '[decryption failed]' });
                }
              }
              setDmMessages(decrypted);
              const latestTransport = [...decrypted]
                .sort((a, b) => Number(b.timestamp || 0) - Number(a.timestamp || 0))
                .find((item) => item.transport)?.transport;
              if (latestTransport === 'reticulum' || latestTransport === 'relay') {
                setLastDmTransport(latestTransport);
              }
              if (decrypted.length > 0) setDmUnread(0);
            }
          }
        }
      } catch {
        /* ignore */
      } finally {
        if (!cancelled) {
          const classification = classifyTick(hasMore, catchUpBudget, DM_MESSAGES_POLL_MS, {
            profile: privacyProfile,
          });
          catchUpBudget = classification.newBudget;
          timer = setTimeout(() => void poll(classification.refreshCount), classification.delay);
        }
      }
    };
    void poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [
    expanded,
    activeTab,
    selectedContact,
    hasId,
    identity,
    dmView,
    wormholeEnabled,
    wormholeReadyState,
    anonymousDmBlocked,
    privacyProfile,
  ]);

  // SAS phrase for active DM contact
  useEffect(() => {
    let cancelled = false;
    setShowSas(false);
    setSasPhrase('');
    setSasConfirmInput('');
    const run = async () => {
      if (!selectedContact) return;
      const contactInfo = contacts[selectedContact];
      if (!contactInfo?.dhPubKey) return;
      try {
        const phrase = await deriveSasPhrase(
          selectedContact,
          contactInfo.dhPubKey,
          8,
          preferredDmPeerId(selectedContact, contactInfo),
        );
        if (!cancelled) setSasPhrase(phrase);
      } catch {
        if (!cancelled) setSasPhrase('');
      }
    };
    run();
    return () => {
      cancelled = true;
    };
  }, [selectedContact, contacts[selectedContact]?.dhPubKey]);

  useEffect(() => {
    if (!selectedContact) return;
    const contactInfo = contacts[selectedContact];
    if (shouldAutoRevealSasForTrust(contactInfo)) {
      setShowSas(true);
    }
  }, [
    selectedContact,
    contacts[selectedContact]?.remotePrekeyMismatch,
    contacts[selectedContact]?.verify_mismatch,
    contacts[selectedContact]?.remotePrekeyFingerprint,
    contacts[selectedContact]?.remotePrekeyPinnedAt,
    contacts[selectedContact]?.verify_registry,
    contacts[selectedContact]?.verify_inband,
    contacts[selectedContact]?.verified,
  ]);

  // Refresh witness/vouch counts when opening a chat
  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      if (!selectedContact) return;
      const contactInfo = getContacts()[selectedContact];
      if (!contactInfo?.dhPubKey) return;
      try {
        const witnessRes = await fetch(
          `${API_BASE}/api/mesh/dm/witness?target_id=${encodeURIComponent(
            selectedContact,
          )}&dh_pub_key=${encodeURIComponent(contactInfo.dhPubKey)}`,
        );
        if (witnessRes.ok && !cancelled) {
          const witnessData = await witnessRes.json();
          updateContact(selectedContact, {
            witness_count: witnessData.count || 0,
            witness_checked_at: Date.now(),
          });
          setContacts(getContacts());
        }
        const vouchRes = await fetch(
          `${API_BASE}/api/mesh/trust/vouches?node_id=${encodeURIComponent(selectedContact)}`,
        );
        if (vouchRes.ok && !cancelled) {
          const vouchData = await vouchRes.json();
          updateContact(selectedContact, {
            vouch_count: vouchData.count || 0,
            vouch_checked_at: Date.now(),
          });
          setContacts(getContacts());
        }
      } catch {
        /* ignore */
      }
    };
    run();
    return () => {
      cancelled = true;
    };
  }, [selectedContact]);

  // ─── Send Handlers ───────────────────────────────────────────────────────

  const handleSend = async () => {
    const msg = inputValue.trim();
    if (!msg || !hasId || busy) return;

    const cooldownMs = activeTab === 'dms' ? 0 : 30_000;
    const now = Date.now();
    const elapsed = now - lastSendTime;
    if (cooldownMs > 0 && elapsed < cooldownMs) {
      const wait = Math.ceil((cooldownMs - elapsed) / 1000);
      setSendError(`cooldown: ${wait}s`);
      setTimeout(() => setSendError(''), 3000);
      return;
    }

    if (anonymousPublicBlocked && (activeTab === 'infonet' || activeTab === 'meshtastic')) {
      setSendError('hidden transport required for public posting');
      setTimeout(() => setSendError(''), 4000);
      return;
    }

    if (activeTab === 'infonet' && !privateInfonetReady) {
      setSendError('wormhole required for infonet');
      setTimeout(() => setSendError(''), 4000);
      return;
    }

    if (isGateSendBlocked(activeTab, Boolean(selectedGate), selectedGateAccessReady)) {
      setSendError('gate access still syncing');
      setTimeout(() => setSendError(''), 4000);
      return;
    }

    setInputValue('');
    setSendError('');
    setBusy(true);
    setLastSendTime(now);

    try {
        if (activeTab === 'infonet' && selectedGate) {
          const gateReplyPrefix =
            gateReplyContext && gateReplyContext.gateId === String(selectedGate).trim().toLowerCase()
              ? `>>${gateReplyContext.eventId.slice(0, 8)} @${gateReplyContext.nodeId.slice(0, 12)} `
              : '';
          const gateData = await postWormholeGateMessage(
            selectedGate,
            `${gateReplyPrefix}${msg}`,
            gateReplyContext?.gateId === String(selectedGate).trim().toLowerCase()
              ? gateReplyContext?.eventId || ''
              : '',
          ).catch((error) => ({
            ok: false,
            detail: error instanceof Error ? error.message : 'gate post failed',
          }));
          if (gateData?.ok === false) {
            setInputValue(msg);
            setLastSendTime(0);
            const detail = gateData?.detail || 'gate post failed';
            setSendError(
              detail === 'gate_backend_plaintext_compat_required'
                ? 'Service-side gate send is disabled on this runtime. Use native desktop or an explicit compatibility override.'
                : detail === 'gate_compat_fallback_consent_required' || detail.startsWith('gate_local_runtime_required:')
                  ? describeGateLocalRuntimeRequired(detail, selectedGate)
                  : detail,
            );
            if (markGateResyncRequired(detail, selectedGate)) {
              setGateError(
                describeNativeControlError(detail) ||
                  'Gate state changed on another path. Resync before retrying.',
              );
            }
            setTimeout(() => setSendError(''), 4000);
            return;
        }
        clearGateResyncRequired(selectedGate);
        setInfoMessages((prev) => [
          ...prev,
          {
            event_id: `_pending_${Date.now()}`,
            event_type: 'gate_message',
            gate: String(selectedGate || '').trim().toLowerCase(),
            node_id: String(identity?.nodeId || ''),
            message: `${gateReplyPrefix}${msg}`,
            decrypted_message: `${gateReplyPrefix}${msg}`,
            timestamp: Math.floor(Date.now() / 1000),
            ephemeral: true,
          },
        ]);
        setGateReplyContext(null);
        } else if (activeTab === 'meshtastic') {
          if (!publicIdentity || !hasSovereignty()) {
            setInputValue(msg);
            setLastSendTime(0);
            setSendError('public mesh identity needed');
            openIdentityWizard({
              type: 'err',
              text: 'Quick fix: create a public mesh identity below, then retry your send.',
            });
            setTimeout(() => setSendError(''), 4000);
            setBusy(false);
            return;
          }
          const meshDestination = meshDirectTarget.trim() || 'broadcast';
          const sequence = nextSequence();
          const payload = {
            message: msg,
            destination: meshDestination,
            channel: meshChannel,
            priority: 'normal',
            ephemeral: false,
            transport_lock: 'meshtastic',
          };
          const v = validateEventPayload('message', payload);
          if (!v.ok) {
            setInputValue(msg);
            setLastSendTime(0);
            setSendError(`invalid payload: ${v.reason}`);
            setTimeout(() => setSendError(''), 4000);
            setBusy(false);
            return;
          }
          const signature = await signEvent('message', publicIdentity.nodeId, sequence, payload);
          const sendRes = await fetch(`${API_BASE}/api/mesh/send`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              destination: meshDestination,
              message: msg,
              channel: meshChannel,
              priority: 'normal',
              ephemeral: false,
              transport_lock: 'meshtastic',
              sender_id: publicIdentity.nodeId,
              node_id: publicIdentity.nodeId,
              public_key: publicIdentity.publicKey,
              public_key_algo: getPublicKeyAlgo(),
              signature,
              sequence,
              protocol_version: PROTOCOL_VERSION,
              credentials: { mesh_region: meshRegion },
            }),
          });
        if (!sendRes.ok) {
          setInputValue(msg);
          setLastSendTime(0); // Don't burn cooldown on failure
          setSendError(sendRes.status === 429 ? 'rate limited' : 'send failed');
          setTimeout(() => setSendError(''), 4000);
          return;
        }
        const sendData = await sendRes.json();
        if (!sendData.ok) {
          setInputValue(msg);
          setLastSendTime(0);
          if (sendData.detail === 'Invalid signature') {
            setSendError('public mesh signature failed');
            openIdentityWizard({
              type: 'err',
              text: 'This public mesh identity did not verify. Reset it, recreate it, then retry.',
            });
          } else {
            setSendError(sendData.detail || 'send failed');
          }
          setTimeout(() => setSendError(''), 4000);
          return;
        }
        // Re-fetch — backend injects our msg into the bridge feed after publish
        await new Promise((r) => setTimeout(r, 500));
        const params = new URLSearchParams({
          limit: '30',
          region: meshRegion,
          channel: meshChannel,
        });
        const mRes = await fetch(`${API_BASE}/api/mesh/messages?${params}`);
        if (mRes.ok) {
          const data = await mRes.json();
          setMeshMessages(Array.isArray(data) ? [...data].reverse() : []);
        }
        } else if (activeTab === 'dms' && selectedContact && dmView === 'chat') {
          if (anonymousDmBlocked) {
            setInputValue(msg);
            setLastSendTime(0);
            setSendError('hidden transport required for anonymous dm');
            setTimeout(() => setSendError(''), 4000);
            setBusy(false);
            return;
          }
          const contactInfo = contacts[selectedContact];
          if (contactInfo?.remotePrekeyMismatch) {
            setInputValue(msg);
            setLastSendTime(0);
            setShowSas(true);
            setSendError('remote prekey changed — verify before sending');
            setTimeout(() => setSendError(''), 5000);
            setBusy(false);
            return;
          }
          if (contactInfo?.verify_mismatch) {
            setInputValue(msg);
            setLastSendTime(0);
            setShowSas(true);
            setSendError('contact key mismatch — verify before sending');
            setTimeout(() => setSendError(''), 5000);
            setBusy(false);
            return;
          }
          if (contactInfo?.dhPubKey) {
            const localDhAlgo = getDHAlgo();
            if (contactInfo.dhAlgo && localDhAlgo && contactInfo.dhAlgo !== localDhAlgo) {
              setSendError('dm key mismatch');
              setTimeout(() => setSendError(''), 4000);
              return;
            }
            try {
              await ensureRegisteredDmKey(API_BASE, identity!, { force: false });
              const rotatedContact = await maybeRotateSharedAlias(selectedContact, contactInfo);
              const promotion = promotePendingAlias(selectedContact, rotatedContact);
              if (promotion) updateContact(selectedContact, promotion.delta.updates);
              const effectiveContact = promotion?.promoted || rotatedContact;
              const sharedPeerId = preferredDmPeerId(selectedContact, effectiveContact);
              const ciphertext = await ratchetEncryptDM(selectedContact, effectiveContact.dhPubKey!, msg);
              const recipientToken = await sharedMailboxToken(sharedPeerId, effectiveContact.dhPubKey!);
              const msgId = `dm_${Date.now()}_${identity!.nodeId.slice(-4)}`;
              const timestamp = Math.floor(Date.now() / 1000);
              await enqueueDmSend(async () => {
                const sent = await sendDmMessage({
                  apiBase: API_BASE,
                  identity: identity!,
                  recipientId: sharedPeerId,
                  recipientDhPub: effectiveContact.dhPubKey,
                  ciphertext,
                  msgId,
                  timestamp,
                  deliveryClass: 'shared',
                  recipientToken,
                  useSealedSender: true,
                });
                if (!sent.ok) {
                  throw new Error(sent.detail || 'secure_dm_send_failed');
                }
                if (sent.transport === 'reticulum' || sent.transport === 'relay') {
                  setLastDmTransport(sent.transport);
                }
              });
            } catch (error) {
              setInputValue(msg);
              setLastSendTime(0);
              const detail = error instanceof Error ? error.message : '';
              if (detail.toLowerCase().includes('prekey') || detail.toLowerCase().includes('verify')) {
                setShowSas(true);
              }
              setSendError(detail || 'secure dm send failed');
              setTimeout(() => setSendError(''), 4000);
              setBusy(false);
              return;
            }
          }
        }
    } catch (err) {
      setInputValue(msg);
      setLastSendTime(0);
      const detail = err instanceof Error && err.message ? err.message : '';
      const nativeDetail = describeNativeControlError(err);
      if (activeTab === 'infonet') {
        refreshNativeAuditReport();
      }
      if (activeTab === 'infonet') {
        if (markGateResyncRequired(err, selectedGate)) {
          setGateError(
            nativeDetail || detail || 'Gate state changed on another path. Resync before retrying.',
          );
        }
        setSendError(
          nativeDetail || detail || 'encrypted gate send failed',
        );
      } else {
        setSendError(nativeDetail || detail || 'send failed');
      }
      setTimeout(() => setSendError(''), 4000);
    }
    setBusy(false);
  };

  const sendDecoy = useCallback(async () => {
    if (!hasId || !identity) return;
    if (anonymousDmBlocked) return;
    try {
      if (!(await canUseWormholeBootstrap())) return;
      await ensureRegisteredDmKey(API_BASE, identity, { force: false });
      const msgId = `dm_${Date.now()}_${identity.nodeId.slice(-4)}`;
      const timestamp = Math.floor(Date.now() / 1000);
      const padLen = 72 + Math.floor(Math.random() * 88);
      const ciphertext = randomBase64(padLen);
      const recipientId = `decoy_${randomHex(6)}`;
      const recipientToken = randomHex(24);
      const sent = await sendDmMessage({
        apiBase: API_BASE,
        identity,
        recipientId,
        ciphertext,
        msgId,
        timestamp,
        deliveryClass: 'shared',
        recipientToken,
        useSealedSender: false,
      });
      if (sent.transport === 'reticulum' || sent.transport === 'relay') {
        setLastDmTransport(sent.transport);
      }
    } catch {
      /* ignore */
    }
  }, [hasId, identity, anonymousDmBlocked]);

  // Decoy traffic (optional)
  useEffect(() => {
    if (!decoyEnabled || !hasId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const schedule = () => {
      const delay = jitterDelay(DM_DECOY_POLL_MS, DM_DECOY_POLL_JITTER_MS);
      timer = setTimeout(async () => {
        await sendDecoy();
        if (!cancelled) schedule();
      }, delay);
    };
    schedule();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [decoyEnabled, hasId, sendDecoy]);

  const handleVote = async (targetId: string, vote: 1 | -1, gateIdOverride?: string) => {
    if (!hasId) return;
    if (anonymousPublicBlocked) return;
    if (!privateInfonetReady) return;
    const voteGate = String(gateIdOverride || selectedGate || '').trim().toLowerCase();
    const scopeKey = voteScopeKey(targetId, voteGate);
    // If already voted same direction, ignore
    if (votedOn[scopeKey] === vote) return;
    setVotedOn((prev) => ({ ...prev, [scopeKey]: vote }));
    try {
      const sequence = nextSequence();
      const votePayload = { target_id: targetId, vote, gate: voteGate };
      const v = validateEventPayload('vote', votePayload);
      if (!v.ok) return;
      const signed = await signMeshEvent('vote', votePayload, sequence, {
        gateId: voteGate || undefined,
      });
      await fetch(`${API_BASE}/api/mesh/vote`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          voter_id: signed.context.nodeId,
          target_id: targetId,
          vote,
          gate: voteGate || undefined,
          voter_pubkey: signed.context.publicKey,
          public_key_algo: signed.context.publicKeyAlgo,
          voter_sig: signed.signature,
          sequence: signed.sequence,
          protocol_version: signed.protocolVersion,
        }),
      });
      const res = await fetch(
        `${API_BASE}/api/mesh/reputation?node_id=${encodeURIComponent(targetId)}`,
      );
      if (res.ok) {
        const data = await res.json();
        setReps((prev) => ({ ...prev, [targetId]: data.overall || 0 }));
      }
    } catch {
      /* ignore */
    }
  };

  const handleCreateGate = async () => {
    if (!hasId || !newGateId.trim()) return;
    if (!privateInfonetReady) {
      setGateError('wormhole required for private infonet');
      return;
    }
    if (anonymousPublicBlocked) {
      setGateError('hidden transport required for gate creation');
      return;
    }
    setGateError('');
    try {
      const gatePayload = {
        gate_id: newGateId.trim(),
        display_name: newGateName.trim() || newGateId.trim(),
        rules: { min_overall_rep: newGateMinRep },
      };
      const v = validateEventPayload('gate_create', gatePayload);
      if (!v.ok) {
        setGateError(`invalid payload: ${v.reason}`);
        return;
      }
      const sequence = nextSequence();
      const signed = await signMeshEvent('gate_create', gatePayload, sequence);
      const createRes = await fetch(`${API_BASE}/api/mesh/gate/create`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          creator_id: signed.context.nodeId,
          gate_id: gatePayload.gate_id,
          display_name: gatePayload.display_name,
          rules: gatePayload.rules,
          creator_pubkey: signed.context.publicKey,
          public_key_algo: signed.context.publicKeyAlgo,
          creator_sig: signed.signature,
          sequence: signed.sequence,
          protocol_version: signed.protocolVersion,
        }),
      });
      const createData = await createRes.json();
      if (!createData.ok) {
        setGateError(createData.detail || 'Failed to create gate');
        return;
      }
      invalidateGateCatalogSnapshot();
      const nextGates = (await fetchGateCatalogSnapshot({ force: true }).catch(() => [])).map(
        gateCatalogEntryToGate,
      );
      if (nextGates.length > 0) {
        setGates(nextGates);
      }
      setSelectedGate(newGateId.trim().toLowerCase());
      setShowCreateGate(false);
      setNewGateId('');
      setNewGateName('');
      setNewGateMinRep(0);
    } catch {
      setGateError('Network error — try again');
    }
  };

  const refreshSelectedGatePersonas = useCallback(async (gateId: string) => {
    const gateKey = gateId.trim().toLowerCase();
    if (!gateKey || !wormholeEnabled || !wormholeReadyState) return;
    const data = await listWormholeGatePersonas(gateKey);
    if (!data.ok) return;
    setGatePersonas((prev) => ({ ...prev, [gateKey]: Array.isArray(data.personas) ? data.personas : [] }));
    setActiveGatePersonaId((prev) => ({
      ...prev,
      [gateKey]: String(data.active_persona_id || ''),
    }));
  }, [wormholeEnabled, wormholeReadyState]);

  const refreshSelectedGateKeyStatus = useCallback(async (gateId: string) => {
    const gateKey = gateId.trim().toLowerCase();
    if (!gateKey || !wormholeEnabled || !wormholeReadyState) return;
    const data = await fetchWormholeGateKeyStatus(gateKey);
    setGateKeyStatus((prev) => ({ ...prev, [gateKey]: data }));
  }, [wormholeEnabled, wormholeReadyState]);

  const handleResyncGateState = useCallback(
    async (gateIdOverride?: string): Promise<boolean> => {
      const gateId = String(gateIdOverride || selectedGate || '').trim().toLowerCase();
      if (!gateId || !wormholeEnabled || !wormholeReadyState || gateResyncBusy) return false;
      setGateResyncBusy(true);
      setGateError('');
      try {
        const resynced = await resyncWormholeGateState(gateId);
        if (!resynced.ok) {
          throw new Error(resynced.detail || 'gate_state_resync_failed');
        }
        clearGateResyncRequired(gateId);
        await refreshSelectedGateKeyStatus(gateId).catch(() => null);
        await refreshSelectedGatePersonas(gateId).catch(() => null);
        if (selectedGate === gateId) {
          await refreshInfonetMessages({ gateId, force: true });
        }
        setSendError('gate state resynced — retry the room action');
        window.setTimeout(() => setSendError(''), 4000);
        refreshNativeAuditReport();
        return true;
      } catch (err) {
        const detail =
          describeNativeControlError(err) ||
          (err instanceof Error && err.message) ||
          'Failed to resync gate state';
        setGateError(detail);
        markGateResyncRequired(err, gateId);
        return false;
      } finally {
        setGateResyncBusy(false);
      }
    },
    [
      clearGateResyncRequired,
      gateResyncBusy,
      markGateResyncRequired,
      refreshNativeAuditReport,
      refreshInfonetMessages,
      refreshSelectedGateKeyStatus,
      refreshSelectedGatePersonas,
      selectedGate,
      wormholeEnabled,
      wormholeReadyState,
    ],
  );

  const closeGatePersonaPrompt = useCallback(() => {
    setGatePersonaPromptOpen(false);
    setGatePersonaPromptGateId('');
    setGatePersonaDraftLabel('');
    setGatePersonaPromptError('');
  }, []);

  const openGatePersonaPrompt = useCallback(
    (gateIdOverride?: string) => {
      const gateId = String(gateIdOverride || selectedGate || '').trim().toLowerCase();
      if (!gateId) return;
      gatePersonaPromptSeenRef.current.add(gateId);
      setGatePersonaPromptGateId(gateId);
      setGatePersonaDraftLabel('');
      setGatePersonaPromptError('');
      setGatePersonaPromptOpen(true);
    },
    [selectedGate],
  );

  const handleCreateGatePersona = async (labelOverride?: string): Promise<boolean> => {
    const gateId = selectedGate.trim().toLowerCase();
    if (!gateId || !wormholeEnabled || !wormholeReadyState || gatePersonaBusy) return false;
    if (anonymousPublicBlocked) {
      setGateError('hidden transport required for anonymous gate personas');
      return false;
    }
    setGatePersonaBusy(true);
    setGateError('');
    setGatePersonaPromptError('');
    try {
      const existing = gatePersonas[gateId] || [];
      const nextLabel =
        String(labelOverride || '').trim() || `anon_${String(existing.length + 1).padStart(2, '0')}`;
      const created = await createWormholeGatePersona(gateId, nextLabel);
      if (!created.ok) {
        throw new Error(created.detail || 'persona_create_failed');
      }
      clearGateResyncRequired(gateId);
      await refreshSelectedGatePersonas(gateId);
      await refreshSelectedGateKeyStatus(gateId);
      return true;
    } catch (err) {
      const detail = describeNativeControlError(err) || 'Failed to create persona';
      setGateError(detail);
      setGatePersonaPromptError(detail);
      markGateResyncRequired(err, gateId);
      return false;
    } finally {
      refreshNativeAuditReport();
      setGatePersonaBusy(false);
    }
  };

  const handleSelectGatePersona = async (personaId: string): Promise<boolean> => {
    const gateId = selectedGate.trim().toLowerCase();
    if (!gateId || !wormholeEnabled || !wormholeReadyState || gatePersonaBusy) return false;
    if (anonymousPublicBlocked) {
      setGateError('hidden transport required for anonymous gate personas');
      return false;
    }
    setGatePersonaBusy(true);
    setGateError('');
    setGatePersonaPromptError('');
    try {
      const response =
        personaId === '__anon__'
          ? await clearWormholeGatePersona(gateId)
          : await activateWormholeGatePersona(gateId, personaId);
      if (!response.ok) {
        throw new Error(response.detail || 'persona_activate_failed');
      }
      clearGateResyncRequired(gateId);
      await refreshSelectedGatePersonas(gateId);
      await refreshSelectedGateKeyStatus(gateId);
      refreshNativeAuditReport();
      return true;
    } catch (err) {
      const detail = describeNativeControlError(err) || 'Failed to switch gate persona';
      setGateError(detail);
      setGatePersonaPromptError(detail);
      markGateResyncRequired(err, gateId);
      return false;
    } finally {
      refreshNativeAuditReport();
      setGatePersonaBusy(false);
    }
  };

  const handleRetireGatePersona = async () => {
    const gateId = selectedGate.trim().toLowerCase();
    const personaId = gateId ? activeGatePersonaId[gateId] || '' : '';
    if (!gateId || !personaId || !wormholeEnabled || !wormholeReadyState || gatePersonaBusy) return;
    if (anonymousPublicBlocked) {
      setGateError('hidden transport required for anonymous gate personas');
      return;
    }
    setGatePersonaBusy(true);
    setGateError('');
    try {
      const retired = await retireWormholeGatePersona(gateId, personaId);
      if (!retired.ok) {
        throw new Error(retired.detail || 'persona_retire_failed');
      }
      clearGateResyncRequired(gateId);
      await refreshSelectedGatePersonas(gateId);
      await refreshSelectedGateKeyStatus(gateId);
      refreshNativeAuditReport();
    } catch (err) {
      setGateError(describeNativeControlError(err) || 'Failed to retire persona');
      markGateResyncRequired(err, gateId);
    } finally {
      refreshNativeAuditReport();
      setGatePersonaBusy(false);
    }
  };

  const handleRotateGateKey = async () => {
    const gateId = selectedGate.trim().toLowerCase();
    if (!gateId || !wormholeEnabled || !wormholeReadyState || gateKeyBusy) return;
    setGateKeyBusy(true);
    setGateError('');
    try {
      const rotated = await rotateWormholeGateKey(gateId, 'operator_reset');
      if (!rotated.ok) {
        throw new Error(rotated.detail || 'gate_key_rotate_failed');
      }
      clearGateResyncRequired(gateId);
      setGateKeyStatus((prev) => ({ ...prev, [gateId]: rotated }));
      await refreshSelectedGatePersonas(gateId);
      refreshNativeAuditReport();
    } catch (err) {
      setGateError(describeNativeControlError(err) || 'Failed to rotate gate key');
      markGateResyncRequired(err, gateId);
    } finally {
      refreshNativeAuditReport();
      setGateKeyBusy(false);
    }
  };

  const handleUnlockEncryptedGate = useCallback(() => {
    openGatePersonaPrompt();
  }, [openGatePersonaPrompt]);

  const maybeRotateSharedAlias = async (
    contactId: string,
    contact: Contact,
    options?: { force?: boolean },
  ): Promise<Contact> => {
    const promotion = promotePendingAlias(contactId, contact);
    if (promotion) updateContact(contactId, promotion.delta.updates);
    const refreshed = promotion?.promoted || contact;
    const currentAlias = String(refreshed.sharedAlias || '').trim();
    if (!currentAlias || !refreshed.dhPubKey) {
      return refreshed;
    }
    if (String(refreshed.pendingSharedAlias || '').trim()) {
      return refreshed;
    }
    const lastRotatedAt = Number(refreshed.sharedAliasRotatedAt || 0);
    if (!options?.force && lastRotatedAt > 0 && Date.now() - lastRotatedAt < SHARED_ALIAS_ROTATE_MS) {
      return refreshed;
    }
    let nextAlias = '';
    try {
      const rotated = await rotateWormholePairwiseAlias(
        contactId,
        refreshed.dhPubKey,
        SHARED_ALIAS_GRACE_MS,
      );
      nextAlias = String(rotated.pending_alias || '').trim();
    } catch {
      nextAlias = '';
    }
    if (!nextAlias) {
      nextAlias = generateSharedAlias();
    }
    const controlPlaintext = buildAliasRotateMessage(nextAlias);
    const controlCiphertext = await ratchetEncryptDM(contactId, refreshed.dhPubKey, controlPlaintext);
    const recipientToken = await sharedMailboxToken(currentAlias, refreshed.dhPubKey);
    const msgId = `dm_${Date.now()}_${identity!.nodeId.slice(-4)}`;
    const timestamp = Math.floor(Date.now() / 1000);
    await enqueueDmSend(async () => {
      const sent = await sendDmMessage({
        apiBase: API_BASE,
        identity: identity!,
        recipientId: currentAlias,
        recipientDhPub: refreshed.dhPubKey,
        ciphertext: controlCiphertext,
        msgId,
        timestamp,
        deliveryClass: 'shared',
        recipientToken,
        useSealedSender: true,
      });
      if (!sent.ok) {
        throw new Error(sent.detail || 'alias_rotate_send_failed');
      }
      if (sent.transport === 'reticulum' || sent.transport === 'relay') {
        setLastDmTransport(sent.transport);
      }
    });
    updateContact(contactId, {
      pendingSharedAlias: nextAlias,
      sharedAliasGraceUntil: Date.now() + SHARED_ALIAS_GRACE_MS,
      sharedAliasRotatedAt: Date.now(),
      previousSharedAliases: mergeAliasHistory([
        refreshed.sharedAlias,
        ...(refreshed.previousSharedAliases || []),
      ]),
    });
    setContacts(getContacts());
    return getContacts()[contactId] || refreshed;
  };

  const refreshDmContactState = async (
    contactId: string,
    options?: { rotateAlias?: boolean; resetRatchet?: boolean },
  ): Promise<void> => {
    const targetId = String(contactId || '').trim();
    if (!targetId || !identity) return;
    const existing = getContacts()[targetId];
    const lookupHandle = String(existing?.invitePinnedPrekeyLookupHandle || '').trim();
    if (!lookupHandle) {
      throw new Error(
        'import or re-import a signed invite before refreshing this contact; legacy direct lookup is disabled',
      );
    }
    const registry = await fetchDmPublicKey(API_BASE, targetId, lookupHandle).catch(() => null);
    if (!registry?.dh_pub_key) {
      throw new Error(
        'invite-scoped lookup failed for this contact; re-import a signed invite and try again',
      );
    }
    if (registry?.dh_pub_key) {
      addContact(targetId, String(registry.dh_pub_key), undefined, registry.dh_algo);
      let registryOk = true;
      if (registry.signature && registry.public_key && registry.public_key_algo) {
        try {
          const keyPayload = {
            dh_pub_key: registry.dh_pub_key,
            dh_algo: registry.dh_algo,
            timestamp: registry.timestamp,
          };
          registryOk = await verifyEventSignature({
            eventType: 'dm_key',
            nodeId: targetId,
            sequence: Number(registry.sequence || 0),
            payload: keyPayload,
            signature: registry.signature,
            publicKey: registry.public_key,
            publicKeyAlgo: registry.public_key_algo,
          });
        } catch {
          registryOk = false;
        }
      }
      const prior = getContacts()[targetId] || existing;
      const inbandOk = Boolean(prior?.verify_inband);
      const registryKey = String(registry.dh_pub_key || '');
      const inbandKey = String(prior?.dhPubKey || '');
      const verified = inbandOk && registryOk && inbandKey === registryKey;
      updateContact(targetId, {
        dhAlgo: registry.dh_algo || prior?.dhAlgo,
        verify_registry: registryOk,
        verified,
        verify_mismatch: inbandOk && registryOk && inbandKey !== registryKey,
        verified_at: verified ? Date.now() : prior?.verified_at,
        remotePrekeyTransparencyHead:
          String(registry.prekey_transparency_head || '') ||
          prior?.remotePrekeyTransparencyHead,
        remotePrekeyTransparencySize:
          Number(registry.prekey_transparency_size || 0) || prior?.remotePrekeyTransparencySize,
        remotePrekeyTransparencySeenAt: registry.prekey_transparency_head
          ? Date.now()
          : prior?.remotePrekeyTransparencySeenAt,
        remotePrekeyLookupMode:
          String(registry.lookup_mode || '').trim().toLowerCase() ||
          prior?.remotePrekeyLookupMode,
        witness_count:
          Number(registry.witness_count || 0) || prior?.witness_count,
        witness_checked_at:
          Number(registry.witness_latest_at || 0) || prior?.witness_checked_at,
      });
    }
    const latest = getContacts()[targetId] || existing;
    if (latest?.dhPubKey) {
      try {
        const witnessRes = await fetch(
          `${API_BASE}/api/mesh/dm/witness?target_id=${encodeURIComponent(
            targetId,
          )}&dh_pub_key=${encodeURIComponent(latest.dhPubKey)}`,
        );
        if (witnessRes.ok) {
          const witnessData = await witnessRes.json();
          updateContact(targetId, {
            witness_count: witnessData.count || 0,
            witness_checked_at: Date.now(),
          });
        }
      } catch {
        /* ignore */
      }
    }
    try {
      const vouchRes = await fetch(
        `${API_BASE}/api/mesh/trust/vouches?node_id=${encodeURIComponent(targetId)}`,
      );
      if (vouchRes.ok) {
        const vouchData = await vouchRes.json();
        updateContact(targetId, {
          vouch_count: vouchData.count || 0,
          vouch_checked_at: Date.now(),
        });
      }
    } catch {
      /* ignore */
    }
    if (options?.resetRatchet) {
      await ratchetReset(targetId);
    }
    const refreshed = getContacts()[targetId];
    if (options?.rotateAlias && refreshed?.dhPubKey) {
      await maybeRotateSharedAlias(targetId, refreshed, { force: true });
    }
    const hydratedContacts = await hydrateWormholeContacts(true).catch(() => getContacts());
    setContacts(hydratedContacts);
  };

  const handleRefreshSelectedContact = async (): Promise<void> => {
    if (!selectedContact || dmMaintenanceBusy) return;
    setDmMaintenanceBusy(true);
    try {
      await refreshDmContactState(selectedContact, { rotateAlias: true });
    } catch (err) {
      const detail = err instanceof Error ? err.message : 'dm refresh failed';
      setSendError(detail);
      setTimeout(() => setSendError(''), 3000);
    } finally {
      setDmMaintenanceBusy(false);
    }
  };

  const handleResetSelectedContact = async (): Promise<void> => {
    if (!selectedContact || dmMaintenanceBusy) return;
    setDmMaintenanceBusy(true);
    try {
      await refreshDmContactState(selectedContact, { rotateAlias: true, resetRatchet: true });
    } catch (err) {
      const detail = err instanceof Error ? err.message : 'dm reset failed';
      setSendError(detail);
      setTimeout(() => setSendError(''), 3000);
    } finally {
      setDmMaintenanceBusy(false);
    }
  };

  const handleTrustSelectedRemotePrekey = async (): Promise<void> => {
    if (!selectedContact || dmMaintenanceBusy) return;
    const contactInfo = getContacts()[selectedContact] || contacts[selectedContact];
    if (contactInfo?.remotePrekeyRootMismatch) {
      setSendError(
        'stable root changed; use RECOVER ROOT or replace the signed invite before trusting this contact again',
      );
      setTimeout(() => setSendError(''), 3000);
      return;
    }
    setDmMaintenanceBusy(true);
    try {
      const result = await acknowledgeWormholeSasFingerprint(selectedContact);
      if (!result?.ok) {
        throw new Error(String(result?.detail || 'failed to acknowledge changed fingerprint'));
      }
      const hydratedContacts = await hydrateWormholeContacts(true).catch(() => getContacts());
      setContacts(hydratedContacts);
      setShowSas(true);
      setSasConfirmInput('');
    } catch (err) {
      const detail = err instanceof Error ? err.message : 'failed to acknowledge changed fingerprint';
      setSendError(detail);
      setTimeout(() => setSendError(''), 3000);
    } finally {
      setDmMaintenanceBusy(false);
    }
  };

  const handleApproveGateCompatFallback = useCallback(async () => {
    if (!gateCompatConsentPrompt?.gateId) return;
    const approvedGateId = gateCompatConsentPrompt.gateId;
    const action = gateCompatConsentPrompt.action;
    approveGateCompatFallback(approvedGateId);
    setGateCompatActive((prev) => (prev[approvedGateId] ? prev : { ...prev, [approvedGateId]: true }));
    setGateCompatConsentPrompt(null);
    setGateError('');
    setSendError('');
    if (action === 'decrypt') {
      await refreshInfonetMessages({ gateId: approvedGateId, force: true });
      return;
    }
    await handleSend();
  }, [gateCompatConsentPrompt, handleSend, refreshInfonetMessages]);

  const handleConfirmSelectedContactSas = async (): Promise<void> => {
    if (!selectedContact || dmMaintenanceBusy) return;
    const contactInfo = getContacts()[selectedContact] || contacts[selectedContact];
    const proof = String(sasConfirmInput || '').trim();
    if (!proof) {
      setSendError('type the SAS phrase to confirm verification');
      setTimeout(() => setSendError(''), 3000);
      return;
    }
    setDmMaintenanceBusy(true);
    try {
      const result = await confirmWormholeSasVerification(
        selectedContact,
        proof,
        preferredDmPeerId(selectedContact, contactInfo),
        8,
      );
      if (!result?.ok) {
        throw new Error(String(result?.detail || 'sas verification failed'));
      }
      const hydratedContacts = await hydrateWormholeContacts(true).catch(() => getContacts());
      setContacts(hydratedContacts);
      setSasConfirmInput('');
      setShowSas(true);
    } catch (err) {
      const detail = err instanceof Error ? err.message : 'sas verification failed';
      setSendError(detail);
      setTimeout(() => setSendError(''), 3000);
    } finally {
      setDmMaintenanceBusy(false);
    }
  };

  const handleRecoverSelectedContactRootContinuity = async (): Promise<void> => {
    if (!selectedContact || dmMaintenanceBusy) return;
    const contactInfo = getContacts()[selectedContact] || contacts[selectedContact];
    const proof = String(sasConfirmInput || '').trim();
    if (!proof) {
      setSendError('type the SAS phrase to recover the changed stable root');
      setTimeout(() => setSendError(''), 3000);
      return;
    }
    setDmMaintenanceBusy(true);
    try {
      const result = await recoverWormholeSasRootContinuity(
        selectedContact,
        proof,
        preferredDmPeerId(selectedContact, contactInfo),
        8,
      );
      if (!result?.ok) {
        throw new Error(String(result?.detail || 'stable root recovery failed'));
      }
      const hydratedContacts = await hydrateWormholeContacts(true).catch(() => getContacts());
      setContacts(hydratedContacts);
      setSasConfirmInput('');
      setShowSas(true);
    } catch (err) {
      const detail = err instanceof Error ? err.message : 'stable root recovery failed';
      setSendError(detail);
      setTimeout(() => setSendError(''), 3000);
    } finally {
      setDmMaintenanceBusy(false);
    }
  };

  // ─── Dead Drop: Request Access ───────────────────────────────────────────

  const handleRequestAccess = async (targetId: string) => {
    if (!hasId) return;
    if (anonymousDmBlocked) {
      setSendError('hidden transport required for anonymous dm');
      setTimeout(() => setSendError(''), 3000);
      return;
    }
    if (requiresVerifiedFirstContact(getContacts()[targetId])) {
      setSendError('import a signed invite before first secure contact; TOFU requests are disabled');
      setTimeout(() => setSendError(''), 4000);
      return;
    }
    if (wormholeEnabled && !wormholeReadyState) {
      setSendError('wormhole required for dead drop');
      setTimeout(() => setSendError(''), 3000);
      return;
    }
    try {
      const registration = await ensureRegisteredDmKey(API_BASE, identity!, { force: false });
      const myPub = registration.dhPubKey;
      if (!myPub) return;
      const dhAlgo = registration.dhAlgo || getDHAlgo() || 'X25519';
      const targetContact = getContacts()[targetId];
      const lookupHandle = String(targetContact?.invitePinnedPrekeyLookupHandle || '').trim();
      if (!lookupHandle) {
        throw new Error(
          'import or re-import a signed invite before sending a contact request; legacy direct lookup is disabled',
        );
      }
      const targetKey = await fetchDmPublicKey(API_BASE, targetId, lookupHandle);
      if (!targetKey?.dh_pub_key) {
        throw new Error(
          'invite-scoped lookup failed for this contact; re-import a signed invite and try again',
        );
      }
      let geoHint = '';
      if (geoHintEnabled && typeof navigator !== 'undefined' && navigator.geolocation) {
        try {
          const pos = await new Promise<GeolocationPosition>((resolve, reject) => {
            navigator.geolocation.getCurrentPosition(resolve, reject, {
              maximumAge: 60_000,
              timeout: 2000,
            });
          });
          const lat = Number(pos.coords.latitude.toFixed(2));
          const lng = Number(pos.coords.longitude.toFixed(2));
          if (Number.isFinite(lat) && Number.isFinite(lng)) {
            geoHint = `${lat},${lng}`;
          }
        } catch {
          geoHint = '';
        }
      }
      const requestPlaintext = buildContactOfferMessage(myPub, dhAlgo, geoHint || undefined);
      let ciphertext = '';
      const secureRequired = await isWormholeSecureRequired();
      if (await canUseWormholeBootstrap()) {
        try {
          ciphertext = await bootstrapEncryptAccessRequest(targetId, requestPlaintext);
        } catch {
          ciphertext = '';
        }
      }
      if (!ciphertext && !secureRequired) {
        const sharedKey = await deriveSharedKey(String(targetKey.dh_pub_key));
        ciphertext = await encryptDM(requestPlaintext, sharedKey);
      }
      if (!ciphertext) {
        throw new Error('secure bootstrap unavailable');
      }
      const msgId = `dm_${Date.now()}_${identity!.nodeId.slice(-4)}`;
      const msgTimestamp = Math.floor(Date.now() / 1000);
      await sleep(jitterDelay(ACCESS_REQUEST_BATCH_DELAY_MS, ACCESS_REQUEST_BATCH_JITTER_MS));
      await enqueueDmSend(async () => {
        const sent = await sendOffLedgerConsentMessage({
          apiBase: API_BASE,
          identity: identity!,
          recipientId: targetId,
          recipientDhPub: String(targetKey.dh_pub_key),
          ciphertext,
          msgId,
          timestamp: msgTimestamp,
        });
        if (!sent.ok) {
          throw new Error(sent.detail || 'access_request_send_failed');
        }
        if (sent.transport === 'reticulum' || sent.transport === 'relay') {
          setLastDmTransport(sent.transport);
        }
      });
      const updated = [...pendingSent, targetId];
      setPendingSent(updated, dmConsentScopeId);
      setPendingSentState(updated);
    } catch (err) {
      const detail = err instanceof Error ? err.message : 'contact request failed';
      setSendError(detail);
      setTimeout(() => setSendError(''), 4000);
    }
  };

  const handleAcceptRequest = async (senderId: string) => {
    if (!hasId) return;
    if (requiresVerifiedFirstContact(getContacts()[senderId])) {
      setSendError('import a signed invite before accepting an unverified request');
      setTimeout(() => setSendError(''), 4000);
      return;
    }
    if (anonymousDmBlocked) {
      setSendError('hidden transport required for anonymous dm');
      setTimeout(() => setSendError(''), 3000);
      return;
    }
    try {
      const req = accessRequests.find((r) => r.sender_id === senderId);
      const existingContact = getContacts()[senderId];
      const registry = await fetchDmPublicKey(
        API_BASE,
        senderId,
        existingContact?.invitePinnedPrekeyLookupHandle,
      ).catch(() => null);
      const resolvedDhPubKey = String(registry?.dh_pub_key || req?.dh_pub_key || '').trim();
      const resolvedDhAlgo = String(registry?.dh_algo || req?.dh_algo || 'X25519').trim();
      if (!resolvedDhPubKey) {
        throw new Error('remote dm key unavailable for this request');
      }

      addContact(senderId, resolvedDhPubKey, undefined, resolvedDhAlgo);
      const inbandKey = req?.dh_pub_key;
      const registryKey = String(registry?.dh_pub_key || '');
      const inbandOk = Boolean(inbandKey);
      let registryOk = Boolean(registryKey);
      if (registryOk && registry?.signature && registry?.public_key && registry?.public_key_algo) {
        try {
          const keyPayload = {
            dh_pub_key: registry.dh_pub_key,
            dh_algo: registry.dh_algo,
            timestamp: registry.timestamp,
          };
          registryOk = await verifyEventSignature({
            eventType: 'dm_key',
            nodeId: senderId,
            sequence: Number(registry.sequence || 0),
            payload: keyPayload,
            signature: registry.signature,
            publicKey: registry.public_key,
            publicKeyAlgo: registry.public_key_algo,
          });
        } catch {
          registryOk = false;
        }
      }
      const match = inbandOk && registryOk ? inbandKey === registryKey : false;
      updateContact(senderId, {
        verify_inband: inbandOk,
        verify_registry: registryOk,
        verified: match,
        verify_mismatch: inbandOk && registryOk && !match,
        verified_at: match ? Date.now() : undefined,
        dhAlgo: resolvedDhAlgo,
        remotePrekeyTransparencyHead:
          String(registry?.prekey_transparency_head || '') ||
          existingContact?.remotePrekeyTransparencyHead,
        remotePrekeyTransparencySize:
          Number(registry?.prekey_transparency_size || 0) ||
          existingContact?.remotePrekeyTransparencySize,
        remotePrekeyTransparencySeenAt: registry?.prekey_transparency_head
          ? Date.now()
          : existingContact?.remotePrekeyTransparencySeenAt,
        remotePrekeyLookupMode:
          String(registry?.lookup_mode || '').trim().toLowerCase() ||
          existingContact?.remotePrekeyLookupMode,
        witness_count: Number(registry?.witness_count || 0) || existingContact?.witness_count,
        witness_checked_at:
          Number(registry?.witness_latest_at || 0) || existingContact?.witness_checked_at,
      });
      if (registry?.dh_pub_key) {
        try {
          const witnessPayload = {
            target_id: senderId,
            dh_pub_key: registry.dh_pub_key,
            timestamp: Math.floor(Date.now() / 1000),
          };
          const wValid = validateEventPayload('dm_key_witness', witnessPayload);
          if (wValid.ok) {
            const wSeq = nextSequence();
            const signedWitness = await signMeshEvent('dm_key_witness', witnessPayload, wSeq);
            await fetch(`${API_BASE}/api/mesh/dm/witness`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                witness_id: signedWitness.context.nodeId,
                target_id: senderId,
                dh_pub_key: registry.dh_pub_key,
                timestamp: witnessPayload.timestamp,
                public_key: signedWitness.context.publicKey,
                public_key_algo: signedWitness.context.publicKeyAlgo,
                signature: signedWitness.signature,
                sequence: signedWitness.sequence,
                protocol_version: signedWitness.protocolVersion,
              }),
            });
          }
          const witnessRes = await fetch(
            `${API_BASE}/api/mesh/dm/witness?target_id=${encodeURIComponent(
              senderId,
            )}&dh_pub_key=${encodeURIComponent(registry.dh_pub_key)}`,
          );
          if (witnessRes.ok) {
            const witnessData = await witnessRes.json();
            updateContact(senderId, {
              witness_count: witnessData.count || 0,
              witness_checked_at: Date.now(),
            });
          }
          const vouchRes = await fetch(
            `${API_BASE}/api/mesh/trust/vouches?node_id=${encodeURIComponent(senderId)}`,
          );
          if (vouchRes.ok) {
            const vouchData = await vouchRes.json();
            updateContact(senderId, {
              vouch_count: vouchData.count || 0,
              vouch_checked_at: Date.now(),
            });
          }
        } catch {
          /* ignore */
        }
      }
      const updated = accessRequests.filter((r) => r.sender_id !== senderId);
      setAccessRequests(updated, dmConsentScopeId);
      setAccessRequestsState(updated);
      setContacts(getContacts());
      const registration = await ensureRegisteredDmKey(API_BASE, identity!, { force: false });
      if (registration.ok) {
        let sharedAlias = '';
        try {
          const pairwiseAlias = await issueWormholePairwiseAlias(senderId, resolvedDhPubKey);
          if (pairwiseAlias.ok) {
            sharedAlias = String(pairwiseAlias.shared_alias || '').trim();
          }
        } catch {
          sharedAlias = '';
        }
        if (!sharedAlias) {
          sharedAlias = generateSharedAlias();
        }
        const grantedPlaintext = buildContactAcceptMessage(sharedAlias);
        let ciphertext = '';
        const secureRequired = await isWormholeSecureRequired();
        if (await canUseWormholeBootstrap()) {
          try {
            ciphertext = await bootstrapEncryptAccessRequest(senderId, grantedPlaintext);
          } catch {
            ciphertext = '';
          }
        }
        if (!ciphertext && !secureRequired) {
          const sharedKey = await deriveSharedKey(resolvedDhPubKey);
          ciphertext = await encryptDM(grantedPlaintext, sharedKey);
        }
        if (!ciphertext) {
          throw new Error('access_granted_bootstrap_failed');
        }
        const msgId = `dm_${Date.now()}_${identity!.nodeId.slice(-4)}`;
        const msgTimestamp = Math.floor(Date.now() / 1000);
        await enqueueDmSend(async () => {
          const sent = await sendOffLedgerConsentMessage({
            apiBase: API_BASE,
            identity: identity!,
            recipientId: senderId,
            recipientDhPub: resolvedDhPubKey,
            ciphertext,
            msgId,
            timestamp: msgTimestamp,
          });
          if (!sent.ok) {
            throw new Error(sent.detail || 'access_granted_send_failed');
          }
          if (sent.transport === 'reticulum' || sent.transport === 'relay') {
            setLastDmTransport(sent.transport);
          }
        });
        updateContact(senderId, {
          sharedAlias,
          previousSharedAliases: [],
          pendingSharedAlias: undefined,
          sharedAliasGraceUntil: undefined,
          sharedAliasRotatedAt: Date.now(),
        });
        setContacts(getContacts());
      }
    } catch (err) {
      const detail = err instanceof Error ? err.message : 'accept failed';
      setSendError(detail);
      setTimeout(() => setSendError(''), 4000);
    }
  };

  const handleDenyRequest = (senderId: string) => {
    void (async () => {
      if (requiresVerifiedFirstContact(getContacts()[senderId])) {
        setSendError('import a signed invite before denying an unverified request');
        setTimeout(() => setSendError(''), 4000);
        return;
      }
      try {
        const req = accessRequests.find((r) => r.sender_id === senderId);
        const existingContact = getContacts()[senderId];
        const targetKey =
          req?.dh_pub_key
            ? { dh_pub_key: req.dh_pub_key, dh_algo: req.dh_algo || 'X25519' }
            : await fetchDmPublicKey(
                API_BASE,
                senderId,
                existingContact?.invitePinnedPrekeyLookupHandle,
              ).catch(() => null);
        if (identity && targetKey?.dh_pub_key) {
          const denyPlaintext = buildContactDenyMessage('declined');
          let ciphertext = '';
          const secureRequired = await isWormholeSecureRequired();
          if (await canUseWormholeBootstrap()) {
            try {
              ciphertext = await bootstrapEncryptAccessRequest(senderId, denyPlaintext);
            } catch {
              ciphertext = '';
            }
          }
          if (!ciphertext && !secureRequired) {
            const sharedKey = await deriveSharedKey(String(targetKey.dh_pub_key));
            ciphertext = await encryptDM(denyPlaintext, sharedKey);
          }
          if (ciphertext) {
            const msgId = `dm_${Date.now()}_${identity.nodeId.slice(-4)}`;
            const msgTimestamp = Math.floor(Date.now() / 1000);
            await enqueueDmSend(async () => {
              await sendOffLedgerConsentMessage({
                apiBase: API_BASE,
                identity,
                recipientId: senderId,
                recipientDhPub: String(targetKey.dh_pub_key || ''),
                ciphertext,
                msgId,
                timestamp: msgTimestamp,
              });
            });
          }
        }
      } catch {
        /* ignore */
      } finally {
        const updated = accessRequests.filter((r) => r.sender_id !== senderId);
        setAccessRequests(updated, dmConsentScopeId);
        setAccessRequestsState(updated);
      }
    })();
  };

  const handleBlockDM = async (agentId: string) => {
    blockContact(agentId);
    setContacts(getContacts());
    // Also remove from access requests
    const updated = accessRequests.filter((r) => r.sender_id !== agentId);
    setAccessRequests(updated, dmConsentScopeId);
    setAccessRequestsState(updated);
    if (selectedContact === agentId) {
      setSelectedContact('');
      setDmView('contacts');
    }
    try {
      if (!identity) return;
      const sequence = nextSequence();
      const blockPayload = { blocked_id: agentId, action: 'block' };
      const v = validateEventPayload('dm_block', blockPayload);
      if (!v.ok) return;
      const signed = await signMeshEvent('dm_block', blockPayload, sequence);
      await fetch(`${API_BASE}/api/mesh/dm/block`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          agent_id: signed.context.nodeId,
          blocked_id: agentId,
          action: 'block',
          public_key: signed.context.publicKey,
          public_key_algo: signed.context.publicKeyAlgo,
          signature: signed.signature,
          sequence: signed.sequence,
          protocol_version: signed.protocolVersion,
        }),
      });
    } catch {
      /* ignore */
    }
  };

  const handleVouch = async (targetId: string) => {
    if (!identity) return;
    if (anonymousPublicBlocked) return;
    try {
      const timestamp = Math.floor(Date.now() / 1000);
      const payload = { target_id: targetId, note: '', timestamp };
      const v = validateEventPayload('trust_vouch', payload);
      if (!v.ok) return;
      const sequence = nextSequence();
      const signed = await signMeshEvent('trust_vouch', payload, sequence);
      const res = await fetch(`${API_BASE}/api/mesh/trust/vouch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          voucher_id: signed.context.nodeId,
          target_id: targetId,
          note: '',
          timestamp,
          public_key: signed.context.publicKey,
          public_key_algo: signed.context.publicKeyAlgo,
          signature: signed.signature,
          sequence: signed.sequence,
          protocol_version: signed.protocolVersion,
        }),
      });
      if (res.ok) {
        const data = await res.json();
        if (data.ok) {
          const current = getContacts();
          const prev = current[targetId]?.vouch_count || 0;
          updateContact(targetId, { vouch_count: prev + 1, vouch_checked_at: Date.now() });
          setContacts(getContacts());
        }
      }
    } catch {
      /* ignore */
    }
  };

  const handleAddContact = async () => {
    const cid = addContactId.trim();
    if (!cid || !hasId) return;
    try {
        const data = await fetchDmPublicKey(API_BASE, cid, undefined, {
          allowLegacyAgentId: true,
        });
        if (data?.dh_pub_key) {
            addContact(cid, data.dh_pub_key, undefined, data.dh_algo);
            let registryOk = true;
            if (data.signature && data.public_key && data.public_key_algo) {
              try {
                const keyPayload = {
                  dh_pub_key: data.dh_pub_key,
                  dh_algo: data.dh_algo,
                  timestamp: data.timestamp,
                };
                registryOk = await verifyEventSignature({
                  eventType: 'dm_key',
                  nodeId: cid,
                  sequence: Number(data.sequence || 0),
                  payload: keyPayload,
                  signature: data.signature,
                  publicKey: data.public_key,
                  publicKeyAlgo: data.public_key_algo,
                });
              } catch {
                registryOk = false;
              }
            }
            updateContact(cid, {
              verify_registry: registryOk,
              verified: false,
              verify_mismatch: false,
              dhAlgo: data.dh_algo,
              remotePrekeyTransparencyHead: String(data.prekey_transparency_head || ''),
              remotePrekeyTransparencySize: Number(data.prekey_transparency_size || 0),
              remotePrekeyTransparencySeenAt: data.prekey_transparency_head ? Date.now() : 0,
              remotePrekeyLookupMode: String(data.lookup_mode || '').trim().toLowerCase(),
              witness_count: Number(data.witness_count || 0),
              witness_checked_at: Number(data.witness_latest_at || 0),
            });
            try {
              const witnessRes = await fetch(
                `${API_BASE}/api/mesh/dm/witness?target_id=${encodeURIComponent(
                  cid,
                )}&dh_pub_key=${encodeURIComponent(data.dh_pub_key)}`,
              );
              if (witnessRes.ok) {
                const witnessData = await witnessRes.json();
                updateContact(cid, {
                  witness_count: witnessData.count || 0,
                  witness_checked_at: Date.now(),
                });
              }
              const vouchRes = await fetch(
                `${API_BASE}/api/mesh/trust/vouches?node_id=${encodeURIComponent(cid)}`,
              );
              if (vouchRes.ok) {
                const vouchData = await vouchRes.json();
                updateContact(cid, {
                  vouch_count: vouchData.count || 0,
                  vouch_checked_at: Date.now(),
                });
              }
            } catch {
              /* ignore */
            }
          setContacts(getContacts());
          setSelectedContact(cid);
          setDmView('chat');
          setShowAddContact(false);
          setAddContactId('');
          if (String(data.lookup_mode || '').trim().toLowerCase() === 'legacy_agent_id') {
            setSendError(
              'contact added through legacy direct lookup; import or re-import a signed invite to replace stable-ID lookup',
            );
            setTimeout(() => setSendError(''), 4000);
          }
        }
    } catch {
      /* ignore */
    }
  };

  const openChat = (contactId: string) => {
    setSelectedContact(contactId);
    setDmView('chat');
    setDmMessages([]);
  };

  // ─── Render ──────────────────────────────────────────────────────────────

  const contactList = useMemo(
    () => Object.entries(contacts).filter(([_, c]) => !c.blocked),
    [contacts],
  );
  const totalDmNotify = dmUnread + accessRequests.length;
  const mutedArray = useMemo(() => [...mutedUsers], [mutedUsers]);
  const selectedContactInfo = selectedContact ? contacts[selectedContact] || null : null;
  const senderPopupContact = senderPopup ? contacts[senderPopup.userId] || null : null;
  const dmTransportMode: DmTransportMode = secureDmBlocked
    ? 'blocked'
    : anonymousModeEnabled && anonymousModeReady
      ? 'hidden'
      : wormholeEnabled
      ? lastDmTransport || 'ready'
      : 'degraded';
  const dmTransportStatus = dmTransportDisplay(dmTransportMode);
  const dmTrustHint = buildDmTrustHint(selectedContactInfo);
  const dmTrustPrimaryAction = dmTrustPrimaryActionLabel(selectedContactInfo);
  const wormholeDescriptor = getWormholeIdentityDescriptor();
  const dashboardRestrictedTab: boolean = activeTab === 'infonet' || activeTab === 'dms';
  const dashboardRestrictedTitle = activeTab === 'infonet' ? 'INFONET RESTRICTED' : 'DEAD DROP RESTRICTED';
  const dashboardRestrictedDetail =
    activeTab === 'infonet'
      ? 'Private Wormhole gate activity is staying in the terminal for this build. Dashboard integration is coming soon.'
      : 'Secure Dead Drop stays in the terminal for this build. Dashboard inbox and compose surfaces are coming soon.';
  const selectedGateKey = selectedGate.trim().toLowerCase();
  const selectedGatePersonaList = selectedGateKey ? gatePersonas[selectedGateKey] || [] : [];
  const selectedGateActivePersonaId = selectedGateKey ? activeGatePersonaId[selectedGateKey] || '' : '';
  const selectedGateActivePersona = useMemo(
    () =>
      selectedGateActivePersonaId
        ? selectedGatePersonaList.find(
            (persona) => String(persona.persona_id || '') === selectedGateActivePersonaId,
          ) || null
        : null,
    [selectedGateActivePersonaId, selectedGatePersonaList],
  );
  const selectedGateMeta = useMemo(
    () => gates.find((gate) => gate.gate_id === selectedGateKey) || null,
    [gates, selectedGateKey],
  );
  const selectedGateCompatActive = useMemo(
    () => Boolean(selectedGateKey && gateCompatActive[selectedGateKey]),
    [gateCompatActive, selectedGateKey],
  );
  const selectedGateKeyStatus = useMemo(
    () => (selectedGateKey ? gateKeyStatus[selectedGateKey] || null : null),
    [gateKeyStatus, selectedGateKey],
  );
  const selectedGateAccessReady = Boolean(selectedGateKeyStatus?.has_local_access);
  const gatePersonaPromptPersonaList =
    gatePersonaPromptGateId ? gatePersonas[gatePersonaPromptGateId] || [] : [];
  const gatePersonaPromptGateMeta = useMemo(
    () =>
      gates.find(
        (gate) => gate.gate_id === (gatePersonaPromptGateId || '').trim().toLowerCase(),
      ) || null,
    [gatePersonaPromptGateId, gates],
  );
  const gatePersonaPromptTitle =
    gatePersonaPromptGateMeta?.display_name || gatePersonaPromptGateId || selectedGate;
  const submitGatePersonaPrompt = useCallback(async () => {
    const ok = await handleCreateGatePersona(gatePersonaDraftLabel);
    if (ok) {
      closeGatePersonaPrompt();
    }
  }, [closeGatePersonaPrompt, gatePersonaDraftLabel, handleCreateGatePersona]);
  const selectSavedGatePersona = useCallback(
    async (personaId: string) => {
      const ok = await handleSelectGatePersona(personaId);
      if (ok) {
        closeGatePersonaPrompt();
      }
    },
    [closeGatePersonaPrompt, handleSelectGatePersona],
  );
  const remainAnonymousInGate = useCallback(() => {
    closeGatePersonaPrompt();
  }, [closeGatePersonaPrompt]);
  const nativeAuditSummary = useMemo(() => {
    if (!nativeAuditReport?.totalEvents) return null;
    const recent = nativeAuditReport.recent[0] || null;
    const byOutcome = nativeAuditReport.byOutcome || {};
    const mismatchCount = (byOutcome.profile_warn || 0) + (byOutcome.profile_denied || 0);
    const deniedCount =
      (byOutcome.profile_denied || 0) +
      (byOutcome.capability_denied || 0) +
      (byOutcome.shim_refused || 0);
    return {
      recent,
      mismatchCount,
      deniedCount,
    };
  }, [nativeAuditReport]);

  const privateInfonetTransportReady = privateInfonetReady && wormholeRnsReady;
  const privateLaneHint = buildPrivateLaneHint({
    activeTab,
    recentPrivateFallback,
    recentPrivateFallbackReason,
    dmTransportMode,
    privateInfonetReady,
    privateInfonetTransportReady,
  });
  const inputDisabled =
    !hasId ||
    busy ||
    (activeTab === 'infonet' && !privateInfonetReady) ||
    (activeTab === 'infonet' && !selectedGate) ||
    (activeTab === 'infonet' &&
      !!selectedGate &&
      wormholeEnabled &&
      wormholeReadyState &&
      !selectedGateAccessReady) ||
    ((activeTab === 'infonet' || activeTab === 'meshtastic') && anonymousPublicBlocked) ||
    (activeTab === 'dms' &&
      (dmView !== 'chat' ||
        !selectedContact ||
        (wormholeEnabled && !wormholeReadyState) ||
        anonymousDmBlocked));
  const privateInfonetBlockedDetail = !wormholeEnabled
    ? 'INFONET now lives behind Wormhole. Public mesh remains available under the MESH tab.'
    : !wormholeReadyState
      ? 'Wormhole is enabled, but the local private agent is not ready yet. INFONET stays locked until the private lane is up.'
      : 'Wormhole is up, but Reticulum is still warming on the private lane. Gate chat can run in transitional mode while strongest transport posture comes online. For strongest content privacy, use Dead Drop.';

  useEffect(() => {
    if (!selectedGate || !wormholeEnabled || !wormholeReadyState) {
      setNativeAuditReport(getDesktopNativeControlAuditReport(5));
      return;
    }
    refreshNativeAuditReport(5);
  }, [refreshNativeAuditReport, selectedGate, wormholeEnabled, wormholeReadyState]);

  useEffect(() => {
    setGateError('');
  }, [selectedGate]);

  // Re-focus input on any click inside the panel (terminal always captures keystrokes)
  const handlePanelClick = useCallback(
    (e: React.MouseEvent) => {
      const target = e.target as HTMLElement;
      // Don't steal focus from selects, buttons, or other inputs
      if (
        target.tagName === 'SELECT' ||
        target.tagName === 'BUTTON' ||
        ((target.tagName === 'INPUT' || target.tagName === 'TEXTAREA') && target !== inputRef.current) ||
        target.closest('select') ||
        target.closest('button')
      )
        return;
      if (!inputDisabled) {
        setTimeout(() => inputRef.current?.focus(), 0);
      }
    },
    [inputDisabled],
  );

  const createPublicMeshIdentity = useCallback(
    async ({ closeWizardOnSuccess }: { closeWizardOnSuccess: boolean }) => {
      setIdentityWizardBusy(true);
      setIdentityWizardStatus(null);
      try {
        const nextIdentity = await generateNodeKeys();
        const nextAddress = await derivePublicMeshAddress(nextIdentity.nodeId).catch(() => '');
        const readyAddress = (nextAddress || nextIdentity.nodeId).toUpperCase();
        setIdentity(nextIdentity);
        setPublicMeshAddress(nextAddress || nextIdentity.nodeId);
        setSendError('');
        const successText = `Mesh key ready. Address ${readyAddress} is live for this testnet session.`;
        setIdentityWizardStatus({
          type: 'ok',
          text: successText,
        });
        if (closeWizardOnSuccess) {
          window.setTimeout(() => setIdentityWizardOpen(false), 900);
        }
        return { ok: true as const, text: successText };
      } catch (err) {
        const message =
          typeof err === 'object' && err !== null && 'message' in err
            ? String((err as { message?: string }).message)
            : 'unknown error';
        const errorText =
          message === 'browser_identity_blocked_secure_mode'
            ? 'Mesh key creation is blocked while Wormhole secure mode is active. Turn Wormhole off first if you want a separate public mesh key.'
            : `Could not create public mesh key: ${message}`;
        setIdentityWizardStatus({
          type: 'err',
          text: errorText,
        });
        return { ok: false as const, text: errorText };
      } finally {
        setIdentityWizardBusy(false);
      }
    },
    [],
  );

  const handleCreatePublicIdentity = useCallback(async () => {
    await createPublicMeshIdentity({ closeWizardOnSuccess: true });
  }, [createPublicMeshIdentity]);

  const handleQuickCreatePublicIdentity = useCallback(async () => {
    setMeshQuickStatus(null);
    const result = await createPublicMeshIdentity({ closeWizardOnSuccess: false });
    setMeshQuickStatus({ type: result.ok ? 'ok' : 'err', text: result.text });
    if (!result.ok) {
      setIdentityWizardOpen(true);
    }
  }, [createPublicMeshIdentity]);

  const handleReplyToMeshAddress = useCallback((address: string) => {
    const target = String(address || '').trim();
    if (!target) return;
    setMeshDirectTarget(target);
    setMeshView('inbox');
    setSenderPopup(null);
    setTimeout(() => inputRef.current?.focus(), 0);
  }, []);

  const handleLeaveWormholeForPublicMesh = useCallback(async () => {
    setIdentityWizardBusy(true);
    setIdentityWizardStatus(null);
    setMeshQuickStatus(null);
    try {
      await leaveWormhole();
      setWormholeEnabled(false);
      setWormholeReadyState(false);
      setWormholeRnsReady(false);
      setWormholeRnsDirectReady(false);
      setWormholeRnsPeers({ active: 0, configured: 0 });
      setSecureModeCached(false);
      const result = await createPublicMeshIdentity({ closeWizardOnSuccess: false });
      const status = { type: result.ok ? 'ok' as const : 'err' as const, text: result.text };
      setIdentityWizardStatus(status);
      setMeshQuickStatus(status);
      if (result.ok) {
        window.setTimeout(() => setIdentityWizardOpen(false), 900);
      }
    } catch (err) {
      const message =
        typeof err === 'object' && err !== null && 'message' in err
          ? String((err as { message?: string }).message)
          : 'unknown error';
      const text = `Could not turn Wormhole off for public mesh: ${message}`;
      setIdentityWizardStatus({ type: 'err', text });
      setMeshQuickStatus({ type: 'err', text });
    } finally {
      setIdentityWizardBusy(false);
    }
  }, [createPublicMeshIdentity]);

  const handleResetPublicIdentity = useCallback(async () => {
    if (wormholeEnabled && wormholeReadyState) {
      setIdentityWizardStatus({
        type: 'err',
        text: 'Reset is blocked while Wormhole secure mode is active. Turn Wormhole off first.',
      });
      return;
    }
    setIdentityWizardBusy(true);
    setIdentityWizardStatus(null);
    try {
      await clearBrowserIdentityState();
      setIdentity(null);
      setContacts({});
      setSelectedContact('');
      setDmMessages([]);
      setAccessRequestsState([]);
      setPendingSentState([]);
      setIdentityWizardStatus({
        type: 'ok',
        text: 'Public mesh identity cleared. Start a fresh one when you are ready.',
      });
    } catch (err) {
      const message =
        typeof err === 'object' && err !== null && 'message' in err
          ? String((err as { message?: string }).message)
          : 'unknown error';
      setIdentityWizardStatus({
        type: 'err',
        text: `Could not clear public identity: ${message}`,
      });
    } finally {
      setIdentityWizardBusy(false);
    }
  }, [wormholeEnabled, wormholeReadyState]);

  const handleBootstrapPrivateIdentity = useCallback(async () => {
    if (wormholeEnabled && wormholeReadyState) {
      setIdentityWizardStatus({
        type: 'ok',
        text: wormholeDescriptor?.nodeId
          ? `Wormhole is already active as ${wormholeDescriptor.nodeId}. Gates and Dead Drop are ready now.`
          : 'Wormhole is already active. Gates and Dead Drop are ready now.',
      });
      setActiveTab('infonet');
      window.setTimeout(() => setIdentityWizardOpen(false), 700);
      return;
    }
    setIdentityWizardBusy(true);
    setIdentityWizardStatus(null);
    try {
      if (!wormholeEnabled || !wormholeReadyState) {
        const joined = await joinWormhole();
        const runtime = joined.runtime;
        setWormholeEnabled(Boolean(joined.settings?.enabled ?? runtime?.configured ?? true));
        setWormholeReadyState(Boolean(runtime?.ready));
        setWormholeRnsReady(Boolean(runtime?.rns_ready));
        setWormholeRnsDirectReady(Boolean(runtime?.rns_private_dm_direct_ready));
        setWormholeRnsPeers({
          active: Number(runtime?.rns_active_peers ?? 0),
          configured: Number(runtime?.rns_configured_peers ?? 0),
        });
        if (!runtime?.ready) {
          setIdentityWizardStatus({
            type: 'ok',
            text: 'Wormhole key is provisioning. Give it a moment, then tap ENTER INFONET again.',
          });
          return;
        }
      }
      const wormholeIdentity = await bootstrapWormholeIdentity();
      purgeBrowserSigningMaterial();
      purgeBrowserContactGraph();
      await purgeBrowserDmState();
      const hydratedContacts = await hydrateWormholeContacts(true);
      setContacts(hydratedContacts);
      setIdentity({
        publicKey: wormholeIdentity.public_key,
        privateKey: '',
        nodeId: wormholeIdentity.node_id,
      });
      setIdentityWizardStatus({
        type: 'ok',
        text: `Wormhole private identity ready as ${wormholeIdentity.node_id}. Dead Drop and private signing now use the local Wormhole agent instead of browser-held keys.`,
      });
      setActiveTab('infonet');
      window.setTimeout(() => setIdentityWizardOpen(false), 700);
    } catch (err) {
      const message =
        typeof err === 'object' && err !== null && 'message' in err
          ? String((err as { message?: string }).message)
          : 'unknown error';
      setIdentityWizardStatus({
        type: 'err',
        text: `Could not bootstrap Wormhole identity: ${message}`,
      });
    } finally {
      setIdentityWizardBusy(false);
    }
  }, [wormholeDescriptor?.nodeId, wormholeEnabled, wormholeReadyState]);
  return {
    // UI state
    expanded,
    setExpanded,
    activeTab,
    setActiveTab,
    inputValue,
    setInputValue,
    busy,
    sendError,
    setSendError,
    identityWizardOpen,
    setIdentityWizardOpen,
    infonetUnlockOpen,
    setInfonetUnlockOpen,
    deadDropUnlockOpen,
    setDeadDropUnlockOpen,
    identityWizardBusy,
    identityWizardStatus,
    setIdentityWizardStatus,
    meshQuickStatus,
    publicMeshAddress,
    meshView,
    setMeshView,
    meshDirectTarget,
    setMeshDirectTarget,
    // Identity
    identity,
    publicIdentity,
    hasPublicLaneIdentity,
    hasId,
    shouldShowIdentityWarning,
    wormholeEnabled,
    wormholeReadyState,
    wormholeRnsReady,
    wormholeRnsPeers,
    wormholeRnsDirectReady,
    privateInfonetReady,
    publicMeshBlockedByWormhole,
    anonymousModeEnabled,
    anonymousModeReady,
    anonymousPublicBlocked,
    anonymousDmBlocked,
    unresolvedSenderSealCount,
    privacyProfile,
    // Frozen contract items
    enqueueDmSend,
    flushDmQueue,
    secureDmBlocked,
    selectedGateAccessReady,
    selectedGateKeyStatus,
    // InfoNet
    gates,
    selectedGate,
    setSelectedGate,
    filteredInfoMessages,
    infoVerification,
    reps,
    votedOn,
    gateReplyContext,
    setGateReplyContext,
    showCreateGate,
    setShowCreateGate,
    newGateId,
    setNewGateId,
    newGateName,
    setNewGateName,
    newGateMinRep,
    setNewGateMinRep,
    gateError,
    setGateError,
    gateCompatConsentPrompt,
    gateResyncTarget,
    gatePersonaBusy,
    gateKeyBusy,
    gateResyncBusy,
    gatePersonaPromptOpen,
    selectedGatePersonaList,
    selectedGateActivePersona,
    selectedGateActivePersonaId,
    selectedGateCompatActive,
    selectedGateMeta,
    nativeAuditReport,
    nativeAuditSummary,
    gatePersonaPromptTitle,
    gatePersonaPromptPersonaList,
    gatePersonaDraftLabel,
    setGatePersonaDraftLabel,
    gatePersonaPromptError,
    setGatePersonaPromptError,
    gatePersonaPromptGateId,
    // Meshtastic
    meshRegion,
    setMeshRegion,
    meshRoots,
    meshChannel,
    setMeshChannel,
    meshChannels,
    activeChannels,
    filteredMeshMessages,
    meshInboxMessages,
    // Dead Drop / DM
    contacts,
    contactList,
    selectedContact,
    setSelectedContact,
    selectedContactInfo,
    dmView,
    setDmView,
    dmMessages,
    setDmMessages,
    dmMaintenanceBusy,
    lastDmTransport,
    sasPhrase,
    showSas,
    setShowSas,
    sasConfirmInput,
    setSasConfirmInput,
    geoHintEnabled,
    decoyEnabled,
    dmUnread,
    accessRequests,
    pendingSent,
    addContactId,
    setAddContactId,
    showAddContact,
    setShowAddContact,
    totalDmNotify,
    dmTransportMode,
    dmTransportStatus,
    dmTrustHint,
    dmTrustPrimaryAction,
    // Mute
    mutedUsers,
    mutedArray,
    senderPopup,
    setSenderPopup,
    muteConfirm,
    setMuteConfirm,
    senderPopupContact,
    // Handlers
    handleSend,
    handleVote,
    handleCreateGate,
    handleCreateGatePersona,
    handleSelectGatePersona,
    handleRetireGatePersona,
    handleRotateGateKey,
    handleResyncGateState,
    handleApproveGateCompatFallback,
    handleUnlockEncryptedGate,
    handleReplyToGateMessage,
    handleReplyToMeshAddress,
    handleSenderClick,
    handleMute,
    handleUnmute,
    handleLocateUser,
    handleRequestAccess,
    handleAcceptRequest,
    handleDenyRequest,
    handleBlockDM,
    handleVouch,
    handleAddContact,
    openChat,
    handleCreatePublicIdentity,
    handleQuickCreatePublicIdentity,
    handleLeaveWormholeForPublicMesh,
    handleResetPublicIdentity,
    handleBootstrapPrivateIdentity,
    handleRefreshSelectedContact,
    handleResetSelectedContact,
    handleTrustSelectedRemotePrekey,
    handleConfirmSelectedContactSas,
    handleRecoverSelectedContactRootContinuity,
    openIdentityWizard,
    openGatePersonaPrompt,
    closeGatePersonaPrompt,
    submitGatePersonaPrompt,
    selectSavedGatePersona,
    remainAnonymousInGate,
    displayPublicMeshSender,
    voteScopeKey,
    openTerminal,
    focusInputComposer,
    refreshNativeAuditReport,
    // Derived display
    inputDisabled,
    privateLaneHint,
    privateInfonetBlockedDetail,
    privateInfonetTransportReady,
    dashboardRestrictedTab,
    dashboardRestrictedTitle,
    dashboardRestrictedDetail,
    wormholeDescriptor,
    // Refs
    messagesEndRef,
    inputRef,
    popupRef,
    cursorMirrorRef,
    cursorMarkerRef,
    inputCursorIndex,
    setInputCursorIndex,
    inputFocused,
    setInputFocused,
    handlePanelClick,
    syncCursorPosition,
    recentPrivateFallback,
    recentPrivateFallbackReason,
    // Props pass-through
    onSettingsClick,
  };
}
