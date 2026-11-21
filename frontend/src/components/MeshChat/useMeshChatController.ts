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
import { fetchPrivacyProfileSnapshot, setInfonetNodeEnabled } from '@/mesh/controlPlaneStatusClient';
import {
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
  severContact,
  getDMNotify,
  nextSequence,
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
  prepareWormholeInteractiveLane,
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
import { connectDeliveryMeta, ensureDmOutboxReleased } from '@/mesh/dmConnectDelivery';
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

import type {
  GateCompatConsentPromptState,
  MeshMqttRuntime,
  MeshMqttSettings,
  MeshMqttForm,
} from './useMeshChatController.helpers';
import {
  gateCatalogEntryToGate,
  PUBLIC_MESH_ADDRESS_KEY,
  normalizePublicMeshAddress,
  readStoredPublicMeshAddress,
  writeStoredPublicMeshAddress,
  clearStoredPublicMeshAddress,
  createPublicMeshAddress,
  errorMessage,
  describeMeshChatControlError,
  describeGateCompatConsentRequired,
  describeGateLocalRuntimeRequired,
} from './useMeshChatController.helpers';
import { useMeshMuteState } from './useMeshMuteState';
import { useMeshtasticPolling } from './useMeshtasticPolling';
import { useDmPolling } from './useDmPolling';
import { useInfoNetPolling } from './useInfoNetPolling';
import { useMeshSendHandlers } from './useMeshSendHandlers';
import { useDeadDropAccess } from './useDeadDropAccess';

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
  const [activeTab, setActiveTab] = useState<Tab>('dms');
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
  const [meshSessionActive, setMeshSessionActive] = useState(false);
  const [publicMeshAddress, setPublicMeshAddress] = useState('');
  const [meshView, setMeshView] = useState<'channel' | 'inbox' | 'settings' | 'message'>('channel');
  const [meshDirectTarget, setMeshDirectTarget] = useState('');
  const [meshAddressDraft, setMeshAddressDraft] = useState('');
  const [meshMqttSettings, setMeshMqttSettings] = useState<MeshMqttSettings | null>(null);
  const [meshMqttForm, setMeshMqttForm] = useState<MeshMqttForm>({
    broker: 'mqtt.meshtastic.org',
    port: '1883',
    username: '',
    password: '',
    psk: '',
    include_default_roots: true,
    extra_roots: '',
    extra_topics: '',
  });
  const [meshMqttBusy, setMeshMqttBusy] = useState(false);
  const [meshMqttStatusText, setMeshMqttStatusText] = useState('');

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
  const storedPublicMeshAddress = clientHydrated ? readStoredPublicMeshAddress() : '';
  const hasStoredPublicLaneIdentity = clientHydrated && Boolean(storedPublicMeshAddress);
  const publicIdentity = null;
  const activePublicMeshAddress = publicMeshAddress || storedPublicMeshAddress;
  const hasPublicLaneIdentity = meshSessionActive && Boolean(activePublicMeshAddress);
  const hasId = Boolean(identity) && (hasSovereignty() || wormholeEnabled);
  const shouldShowIdentityWarning = activeTab !== 'meshtastic' && !hasId;
  const privateInfonetReady = wormholeEnabled && wormholeReadyState;
  const publicMeshBlockedByWormhole = wormholeEnabled || wormholeReadyState;
  const dmSendQueue = useRef<(() => Promise<void>)[]>([]);
  const meshMqttRuntime = meshMqttSettings?.runtime;
  const meshMqttEnabled = Boolean(meshMqttSettings?.enabled || meshMqttRuntime?.enabled);
  const canUsePublicMeshInput = Boolean(activePublicMeshAddress) && meshMqttEnabled && !publicMeshBlockedByWormhole;
  const meshMqttRunning = Boolean(meshMqttRuntime?.running);
  const meshMqttConnected = Boolean(meshMqttRuntime?.connected);
  const meshMqttConnectionLabel = !meshMqttEnabled
    ? 'MQTT OFF'
    : meshMqttConnected
      ? 'MQTT LIVE'
      : meshMqttRunning
        ? 'MQTT CONNECTING'
        : 'MQTT STARTING';

  const applyMeshMqttSettings = useCallback((data: MeshMqttSettings) => {
    setMeshMqttSettings(data);
    setMeshMqttForm((prev) => ({
      broker: data.broker || prev.broker || 'mqtt.meshtastic.org',
      port: String(data.port || prev.port || '1883'),
      username: data.uses_default_credentials ? '' : data.username || prev.username || '',
      password: '',
      psk: '',
      include_default_roots: Boolean(data.include_default_roots),
      extra_roots: data.extra_roots || '',
      extra_topics: data.extra_topics || '',
    }));
  }, []);

  const refreshMeshMqttSettings = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/settings/meshtastic-mqtt`, { cache: 'no-store' });
      if (!res.ok) return null;
      const data = (await res.json()) as MeshMqttSettings;
      applyMeshMqttSettings(data);
      return data;
    } catch {
      return null;
    }
  }, [applyMeshMqttSettings]);

  const saveMeshMqttSettings = useCallback(
    async (updates: Partial<MeshMqttForm> & { enabled?: boolean } = {}) => {
      setMeshMqttBusy(true);
      setMeshMqttStatusText('');
      try {
        const nextForm = { ...meshMqttForm, ...updates };
          const body: Record<string, unknown> = {
            broker: nextForm.broker.trim() || 'mqtt.meshtastic.org',
            port: Number.parseInt(nextForm.port, 10) || 1883,
            username: nextForm.username.trim(),
            include_default_roots: Boolean(nextForm.include_default_roots),
            extra_roots: nextForm.extra_roots.trim(),
            extra_topics: nextForm.extra_topics.trim(),
          };
          if (!nextForm.username.trim() && !nextForm.password.trim()) {
            body.password = '';
          }
        if (typeof updates.enabled === 'boolean') {
          body.enabled = updates.enabled;
        }
        if (nextForm.password.trim()) {
          body.password = nextForm.password;
        }
        if (nextForm.psk.trim()) {
          body.psk = nextForm.psk.trim();
        }
        const res = await fetch(`${API_BASE}/api/settings/meshtastic-mqtt`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        if (!res.ok) {
          const data = await res.clone().json().catch(() => null) as
            | { detail?: unknown; message?: unknown; error?: unknown }
            | null;
          const detail =
            String(data?.detail || data?.message || data?.error || '').trim() ||
            (await res.text().catch(() => '')).trim();
          throw new Error(describeMeshChatControlError(detail || `HTTP ${res.status}`));
        }
        const data = (await res.json()) as MeshMqttSettings;
        applyMeshMqttSettings(data);
        if (data.enabled) {
          setWormholeEnabled(false);
          setWormholeReadyState(false);
          setWormholeRnsReady(false);
          setWormholeRnsDirectReady(false);
          setWormholeRnsPeers({ active: 0, configured: 0 });
          setSecureModeCached(false);
        }
        const status = data.runtime?.connected
          ? 'MQTT bridge connected.'
          : data.enabled
            ? 'MQTT bridge enabled. Connection may take a few seconds.'
            : 'MQTT bridge disabled.';
        setMeshMqttStatusText(status);
        return { ok: true as const, text: status, data };
      } catch (err) {
        const text = describeMeshChatControlError(errorMessage(err, 'MQTT settings update failed'));
        setMeshMqttStatusText(text);
        return { ok: false as const, text };
      } finally {
        setMeshMqttBusy(false);
      }
    },
    [applyMeshMqttSettings, meshMqttForm],
  );

  const enableMeshMqttBridge = useCallback(async () => {
    const result = await saveMeshMqttSettings({ enabled: true });
    if (!result.ok) {
      throw new Error(result.text);
    }
    return result;
  }, [saveMeshMqttSettings]);
  const dmSendTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const streamEnabledForSelectedGateRef = useRef(false);
  const displayPublicMeshSender = useCallback(
    (sender: string) => {
      if (!sender) return '???';
      if (activePublicMeshAddress && sender.toLowerCase() === activePublicMeshAddress.toLowerCase()) {
        return activePublicMeshAddress.toUpperCase();
      }
      return sender;
    },
    [activePublicMeshAddress],
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

  useEffect(() => {
    if (!clientHydrated) return;
    setPublicMeshAddress(readStoredPublicMeshAddress());
    setMeshSessionActive(false);
    setMeshMessages([]);
    setMeshQuickStatus(null);
  }, [clientHydrated]);

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
            setMeshSessionActive(false);
            setMeshMessages([]);
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
  const {
    mutedUsers,
    setMutedUsers,
    senderPopup,
    setSenderPopup,
    muteConfirm,
    setMuteConfirm,
    popupRef,
    handleMute,
    handleUnmute,
  } = useMeshMuteState();

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
  const [infonetLaunchGate, setInfonetLaunchGate] = useState('');
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
  const publicMeshPrivacyEnforcedRef = useRef(false);

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
      setInfonetLaunchGate(String(launchRequest.gate || '').trim().toLowerCase());
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
  const isBroadcastMeshMessage = useCallback((m: MeshtasticMessage) => {
    const target = String(m.to || 'broadcast').trim().toLowerCase();
    return target === '' || target === 'broadcast' || target === '^all';
  }, []);
  const filteredMeshMessages = useMemo(
    () => meshMessages.filter((m) => isBroadcastMeshMessage(m) && !mutedUsers.has(m.from)),
    [isBroadcastMeshMessage, meshMessages, mutedUsers],
  );
  const meshInboxMessages = useMemo(() => {
    if (!activePublicMeshAddress) return [];
    const target = activePublicMeshAddress.toLowerCase();
    return meshMessages.filter(
      (m) => !mutedUsers.has(m.from) && String(m.to || '').toLowerCase() === target,
    );
  }, [activePublicMeshAddress, meshMessages, mutedUsers]);

  useEffect(() => {
    if (!expanded || activeTab !== 'meshtastic') return;
    let alive = true;
    const tick = async () => {
      const data = await refreshMeshMqttSettings();
      if (!alive || !data) return;
      if (!data.enabled && meshSessionActive) {
        setMeshQuickStatus({
          type: 'err',
          text: 'Public Mesh key is ready, but MQTT is off. Enable MQTT in Settings to join the live public lane.',
        });
      }
    };
    void tick();
    const timer = window.setInterval(() => {
      void tick();
    }, meshMqttEnabled && !meshMqttConnected ? 5_000 : 15_000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [
    activeTab,
    expanded,
    meshMqttConnected,
    meshMqttEnabled,
    meshSessionActive,
    refreshMeshMqttSettings,
  ]);

  // ─── InfoNet Polling ─────────────────────────────────────────────────────
  useInfoNetPolling({
    expanded,
    wormholeEnabled,
    wormholeReadyState,
    selectedGate,
    anonymousDmBlocked,
    privacyProfile,
    setGates,
    setSelectedGate,
    setInfoMessages,
    setGatePersonas,
    setActiveGatePersonaId,
    setGateKeyStatus,
    setGateError,
    setGateCompatActive,
    setGateCompatConsentPrompt,
    setGatePersonaDraftLabel,
    setGatePersonaPromptError,
    setGatePersonaPromptGateId,
    setGatePersonaPromptOpen,
    setGateReplyContext,
    setInfoVerification,
    activeGateSessionRef,
    infoPollSignatureRef,
    infoMessageIdsRef,
    infoGateHeadRef,
    infoGateKeyEpochRef,
    gateCompatApprovalAttemptRef,
    infoPullInFlightRef,
    gateCompatConsentPromptGateRef,
    identity,
    contacts,
    hasId,
    wormholeState,
    activeTab,
    infoMessages,
    gates,
    gateKeyStatus,
    gatePersonas,
    activeGatePersonaId,
    gateCompatActive,
  });

  // ─── Meshtastic Channel Discovery ──────────────────────────────────────
  useEffect(() => {
    if (!expanded || activeTab !== 'meshtastic' || !canUsePublicMeshInput) return;
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
  }, [expanded, activeTab, meshRegion, canUsePublicMeshInput]);

  // ─── Meshtastic Polling ──────────────────────────────────────────────────
  useMeshtasticPolling({
    expanded,
    activeTab,
    canUsePublicMeshInput,
    meshView,
    meshRegion,
    meshChannel,
    setMeshMessages,
    setMeshQuickStatus,
  });

  // ─── DM Polling ──────────────────────────────────────────────────────────
  useDmPolling({
    hasId,
    identity,
    expanded,
    activeTab,
    wormholeEnabled,
    wormholeReadyState,
    anonymousDmBlocked,
    privacyProfile,
    selectedContact,
    dmView,
    contacts,
    accessRequests,
    pendingSent,
    dmConsentScopeId,
    setContacts,
    setDmUnread,
    setUnresolvedSenderSealCount,
    setDmMessages,
    setAccessRequestsState,
    setPendingSentState,
    setLastDmTransport,
    setShowSas,
    setSasPhrase,
    setSasConfirmInput,
  });

  // ─── Send Handlers ───────────────────────────────────────────────────────
  const {
    handleSend,
    sendDecoy,
    handleVote,
    handleCreateGate,
    refreshSelectedGatePersonas,
    refreshSelectedGateKeyStatus,
    handleResyncGateState,
    closeGatePersonaPrompt,
    openGatePersonaPrompt,
    handleCreateGatePersona,
    handleSelectGatePersona,
    handleRetireGatePersona,
    handleRotateGateKey,
    handleUnlockEncryptedGate,
    maybeRotateSharedAlias,
    refreshDmContactState,
    handleRefreshSelectedContact,
    handleResetSelectedContact,
    handleTrustSelectedRemotePrekey,
    handleApproveGateCompatFallback,
    handleConfirmSelectedContactSas,
    handleRecoverSelectedContactRootContinuity,
  } = useMeshSendHandlers({
    activeTab,
    hasId,
    busy,
    inputValue,
    selectedGate,
    selectedGateAccessReady,
    anonymousPublicBlocked,
    privateInfonetReady,
    wormholeEnabled,
    wormholeReadyState,
    anonymousDmBlocked,
    privacyProfile,
    expanded,
    identity,
    contacts,
    selectedContact,
    dmView,
    accessRequests,
    pendingSent,
    dmConsentScopeId,
    lastSendTime,
    meshRegion,
    meshChannel,
    meshDirectTarget,
    meshDestination,
    meshSenderAddress,
    meshMqttEnabled,
    meshSessionActive,
    meshQuickStatus,
    gateCompatConsentPrompt,
    gatePersonaBusy,
    gateKeyBusy,
    gateResyncBusy,
    sasPhrase,
    sasConfirmInput,
    dmMaintenanceBusy,
    setInputValue,
    setSendError,
    setBusy,
    setLastSendTime,
    setContacts,
    setDmMessages,
    setDmUnread,
    setAccessRequestsState,
    setPendingSentState,
    setLastDmTransport,
    setMeshMessages,
    setMeshQuickStatus,
    setMeshSessionActive,
    setMeshView,
    setGateError,
    setGateKeyBusy,
    setGateKeyStatus,
    setGatePersonaBusy,
    setGatePersonaDraftLabel,
    setGatePersonaPromptError,
    setGatePersonaPromptGateId,
    setGatePersonaPromptOpen,
    setGatePersonas,
    setActiveGatePersonaId,
    setGateReplyContext,
    setGateCompatConsentPrompt,
    setGateResyncBusy,
    setInfoMessages,
    setInfoVerification,
    setShowSas,
    setSasConfirmInput,
    setSasPhrase,
    setDmMaintenanceBusy,
    setGates,
    setSelectedGate,
    setGateCompatActive,
    setNewGateId,
    isWormholeSecureRequired,
    isGateSendBlocked,
    getContacts,
    updateContact,
    addContact,
    getAccessRequests,
    setAccessRequests,
    setPendingSent,
    getPendingSent,
    gateReplyContext,
    meshView,
    gateCompatActive,
    canUsePublicMeshInput,
    dmCompose,
    setDmCompose,
    infoInput,
    setInfoInput,
    meshInput,
    setMeshInput,
    meshtasticStatus,
    sendError,
    lastSendTimeRef,
    wormholeReady,
    canPostToGate,
    activeGatePersonaId,
    gatePersonas,
    gateKeyStatus,
    selectedGateLabel,
    hasSovereignty,
    isDeclined,
    nodeId,
  });

  // ─── Dead Drop: Request Access ───────────────────────────────────────────
  const {
    handleRequestAccess,
    handleAcceptRequest,
    handleDenyRequest,
    handleSeverContact,
    handleBlockDM,
    handleVouch,
    handleAddContact,
  } = useDeadDropAccess({
    expanded,
    activeTab,
    hasId,
    identity,
    contacts,
    accessRequests,
    pendingSent,
    dmConsentScopeId,
    selectedContact,
    dmView,
    setContacts,
    setDmMessages,
    setAccessRequestsState,
    setPendingSentState,
    setDmView,
    setSendError,
    setDmUnread,
    privacyProfile,
    wormholeEnabled,
    wormholeReadyState,
    anonymousDmBlocked,
    dmRequestTarget,
    setDmRequestTarget,
    dmRequestStatus,
    setDmRequestStatus,
    setSelectedContact,
    setShowSas,
    setSasPhrase,
    setSasConfirmInput,
    sendDecoy,
    isWormholeSecureRequired,
    getContacts,
    addContact,
    updateContact,
    blockContact,
    severContact,
    setAccessRequests,
    setPendingSent,
    getPendingSent,
    getAccessRequests,
  });

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
  const dashboardRestrictedTab = false;
  const dashboardRestrictedTitle = '';
  const dashboardRestrictedDetail = '';
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
    (activeTab !== 'meshtastic' && !hasId) ||
    busy ||
    (activeTab === 'infonet' && !privateInfonetReady) ||
    (activeTab === 'infonet' && !selectedGate) ||
    (activeTab === 'infonet' &&
      !!selectedGate &&
      wormholeEnabled &&
      wormholeReadyState &&
      !selectedGateAccessReady) ||
    (activeTab === 'infonet' && anonymousPublicBlocked) ||
    (activeTab === 'meshtastic' && !canUsePublicMeshInput) ||
    (activeTab === 'dms' &&
      (dmView !== 'chat' ||
        !selectedContact ||
        (wormholeEnabled && !wormholeReadyState) ||
        anonymousDmBlocked));
  const privateInfonetBlockedDetail = !wormholeEnabled
    ? 'INFONET now lives behind Wormhole. Meshtastic radio chat remains available under the MESHTASTIC tab.'
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

  const disablePrivateNodeForPublicMesh = useCallback(async () => {
    try {
      await setInfonetNodeEnabled(false);
    } catch (err) {
      console.warn(
        '[mesh] private node pre-disable failed before public Mesh activation; MQTT enable will retry lane isolation',
        err,
      );
    }
  }, []);

  const disableWormholeForPublicMesh = useCallback(async () => {
    const requireBackendLeave = wormholeEnabled || wormholeReadyState;
    try {
      await leaveWormhole();
    } catch (err) {
      if (requireBackendLeave) {
        throw err;
      }
    }
    setWormholeEnabled(false);
    setWormholeReadyState(false);
    setWormholeRnsReady(false);
    setWormholeRnsDirectReady(false);
    setWormholeRnsPeers({ active: 0, configured: 0 });
    setSecureModeCached(false);
    await disablePrivateNodeForPublicMesh();
  }, [disablePrivateNodeForPublicMesh, wormholeEnabled, wormholeReadyState]);

  useEffect(() => {
    if (!meshSessionActive || !activePublicMeshAddress || !meshMqttEnabled) {
      publicMeshPrivacyEnforcedRef.current = false;
      return;
    }
    if (publicMeshPrivacyEnforcedRef.current) return;
    publicMeshPrivacyEnforcedRef.current = true;
    void disableWormholeForPublicMesh().catch((err) => {
      publicMeshPrivacyEnforcedRef.current = false;
      const message =
        typeof err === 'object' && err !== null && 'message' in err
          ? String((err as { message?: string }).message)
          : 'unknown error';
      setMeshQuickStatus({
        type: 'err',
        text: `Could not isolate public Mesh lane: ${message}`,
      });
    });
  }, [activePublicMeshAddress, disableWormholeForPublicMesh, meshMqttEnabled, meshSessionActive]);

  const createPublicMeshIdentity = useCallback(
    async ({ closeWizardOnSuccess }: { closeWizardOnSuccess: boolean }) => {
      setIdentityWizardBusy(true);
      setIdentityWizardStatus(null);
      try {
        await disableWormholeForPublicMesh();
        const nextAddress = createPublicMeshAddress();
        await enableMeshMqttBridge();
        writeStoredPublicMeshAddress(nextAddress);
        const readyAddress = nextAddress.toUpperCase();
        setPublicMeshAddress(nextAddress);
        setMeshSessionActive(true);
        setMeshMessages([]);
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
        const message = describeMeshChatControlError(errorMessage(err));
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
    [disableWormholeForPublicMesh, enableMeshMqttBridge],
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

  const handleActivatePublicMeshSession = useCallback(async () => {
    setIdentityWizardBusy(true);
    setIdentityWizardStatus(null);
    setMeshQuickStatus(null);
    try {
      const savedAddress = readStoredPublicMeshAddress();
      if (!savedAddress) {
        const text = 'No saved public mesh key is available. Create a mesh key first.';
        setMeshSessionActive(false);
        setIdentityWizardStatus({ type: 'err', text });
        setMeshQuickStatus({ type: 'err', text });
        return { ok: false as const, text };
      }
      await disableWormholeForPublicMesh();
      await enableMeshMqttBridge();
      const readyAddress = savedAddress.toUpperCase();
      setPublicMeshAddress(savedAddress);
      setMeshSessionActive(true);
      setMeshMessages([]);
      setSendError('');
      const text = `Meshtastic Chat is on. Address ${readyAddress}.`;
      setIdentityWizardStatus({ type: 'ok', text });
      setMeshQuickStatus(null);
      return { ok: true as const, text };
    } catch (err) {
      const message = describeMeshChatControlError(errorMessage(err));
      const text = `Could not turn Meshtastic Chat on: ${message}`;
      setIdentityWizardStatus({ type: 'err', text });
      setMeshQuickStatus({ type: 'err', text });
      return { ok: false as const, text };
    } finally {
      setIdentityWizardBusy(false);
    }
  }, [disableWormholeForPublicMesh, enableMeshMqttBridge]);

  const handleReplyToMeshAddress = useCallback((address: string) => {
    const target = String(address || '').trim();
    if (!target) return;
    setMeshDirectTarget(target);
    setMeshAddressDraft(target);
    setMeshView('channel');
    setSenderPopup(null);
    setTimeout(() => inputRef.current?.focus(), 0);
  }, []);

  const handleLeaveWormholeForPublicMesh = useCallback(async () => {
    const result = hasStoredPublicLaneIdentity
      ? await handleActivatePublicMeshSession()
      : await createPublicMeshIdentity({ closeWizardOnSuccess: false });
    const status = { type: result.ok ? 'ok' as const : 'err' as const, text: result.text };
    setIdentityWizardStatus(status);
    setMeshQuickStatus(result.ok ? null : status);
    if (result.ok) {
      window.setTimeout(() => setIdentityWizardOpen(false), 900);
    }
  }, [createPublicMeshIdentity, handleActivatePublicMeshSession, hasStoredPublicLaneIdentity]);

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
      setMeshSessionActive(false);
      setMeshMessages([]);
      clearStoredPublicMeshAddress();
      setPublicMeshAddress('');
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
    setMeshSessionActive(false);
    setMeshMessages([]);
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

  const enterInfonetWormholeLane = useCallback(async () => {
    setMeshSessionActive(false);
    setMeshMessages([]);
    if (wormholeEnabled && wormholeReadyState) {
      try {
        const wormholeIdentity = await fetchWormholeIdentity();
        setIdentity({
          publicKey: wormholeIdentity.public_key,
          privateKey: '',
          nodeId: wormholeIdentity.node_id,
        });
      } catch {
        // Lane is already up; shell can still open.
      }
      return;
    }

    setIdentityWizardBusy(true);
    try {
      const prepared = await prepareWormholeInteractiveLane({ bootstrapIdentity: true });
      const [settings, runtime] = await Promise.all([
        fetchWormholeSettings(true).catch(() => null),
        fetchWormholeStatus().catch(() => null),
      ]);
      const enabled = Boolean(
        settings?.enabled ?? prepared.settingsEnabled ?? runtime?.running ?? runtime?.ready,
      );
      setSecureModeCached(enabled);
      setWormholeEnabled(enabled);
      setWormholeReadyState(Boolean(runtime?.ready ?? prepared.ready));
      setWormholeRnsReady(Boolean(runtime?.rns_ready));
      setWormholeRnsDirectReady(Boolean(runtime?.rns_private_dm_direct_ready));
      setWormholeRnsPeers({
        active: Number(runtime?.rns_active_peers ?? 0),
        configured: Number(runtime?.rns_configured_peers ?? 0),
      });
      if (prepared.identity) {
        purgeBrowserSigningMaterial();
        purgeBrowserContactGraph();
        await purgeBrowserDmState();
        const hydratedContacts = await hydrateWormholeContacts(true);
        setContacts(hydratedContacts);
        setIdentity({
          publicKey: prepared.identity.public_key,
          privateKey: '',
          nodeId: prepared.identity.node_id,
        });
      }
    } finally {
      setIdentityWizardBusy(false);
    }
  }, [wormholeEnabled, wormholeReadyState]);

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
    meshSessionActive,
    publicMeshAddress,
    activePublicMeshAddress,
    meshView,
    setMeshView,
    meshDirectTarget,
    setMeshDirectTarget,
    meshAddressDraft,
    setMeshAddressDraft,
    meshMqttSettings,
    meshMqttForm,
    setMeshMqttForm,
    meshMqttBusy,
    meshMqttStatusText,
    meshMqttEnabled,
    meshMqttRunning,
    meshMqttConnected,
    meshMqttConnectionLabel,
    saveMeshMqttSettings,
    refreshMeshMqttSettings,
    // Identity
    identity,
    publicIdentity,
    hasStoredPublicLaneIdentity,
    hasPublicLaneIdentity,
    canUsePublicMeshInput,
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
    handleSeverContact,
    handleVouch,
    handleAddContact,
    openChat,
    handleCreatePublicIdentity,
    handleQuickCreatePublicIdentity,
    handleActivatePublicMeshSession,
    handleLeaveWormholeForPublicMesh,
    handleResetPublicIdentity,
    handleBootstrapPrivateIdentity,
    enterInfonetWormholeLane,
    infonetLaunchGate,
    clearInfonetLaunchGate: () => setInfonetLaunchGate(''),
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
