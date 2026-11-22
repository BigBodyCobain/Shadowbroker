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
import { useMeshIdentityHandlers } from './useMeshIdentityHandlers';
import { useMeshMqttSettings } from './useMeshMqttSettings';
import { useMeshChannelsPolling } from './useMeshChannelsPolling';
import { useWormholePolling } from './useWormholePolling';
import { useMeshGateDerivedState } from './useMeshGateDerivedState';
import { useDmSendQueue } from './useDmSendQueue';
import { useMeshIdentitySync } from './useMeshIdentitySync';
import { useMeshInfonetMessages } from './useMeshInfonetMessages';

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

  const {
    applyMeshMqttSettings,
    refreshMeshMqttSettings,
    saveMeshMqttSettings,
    enableMeshMqttBridge,
  } = useMeshMqttSettings({
    meshMqttForm,
    setMeshMqttSettings,
    setMeshMqttForm,
    setMeshMqttBusy,
    setMeshMqttStatusText,
    setWormholeEnabled,
    setWormholeReadyState,
    setWormholeRnsReady,
    setWormholeRnsDirectReady,
    setWormholeRnsPeers,
    setSecureModeCached,
  });
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
  useMeshIdentitySync({
    clientHydrated, identityRefreshToken, wormholeEnabled, wormholeReadyState,
    getNodeIdentity, hasSovereignty, hydrateWormholeContacts, fetchWormholeIdentity,
    purgeBrowserSigningMaterial, purgeBrowserContactGraph, purgeBrowserDmState,
    setContacts, setIdentity,
  });

  useWormholePolling({
    setSecureModeCached, setWormholeEnabled, setMeshSessionActive, setMeshMessages,
    purgeBrowserContactGraph, hydrateWormholeContacts,
    setWormholeReadyState, setAnonymousModeEnabled, setAnonymousModeReady,
    setWormholeRnsReady, setWormholeRnsPeers, setWormholeRnsDirectReady,
    setRecentPrivateFallback, setRecentPrivateFallbackReason,
  });

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

  const { flushDmQueue, enqueueDmSend } = useDmSendQueue(privacyProfile);

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

  const { hydrateInfonetMessages, refreshInfonetMessages } = useMeshInfonetMessages({
    wormholeEnabled, wormholeReadyState, gateDecryptCacheRef, infoCursorRef, infoPollSignatureRef,
    selectedGateRef, repsRef, setGateError, markGateResyncRequired, setInfoMessages, setReps,
    fetchGateMessageSnapshotState, selectedGate,
  });

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
    infoCursorRef,
    refreshInfonetMessages,
    infoPollTimerRef,
    infoWaitAbortRef,
    infoVerificationCacheRef,
    selectedGateRef,
    streamEnabledForSelectedGateRef,
    identity,
    contacts,
    hasId,
    activeTab,
    infoMessages,
    gates,
    gateKeyStatus,
    gatePersonas,
    activeGatePersonaId,
    gateCompatActive,
    gatePersonaBusy,
    gatePersonaPromptOpen,
    gateSessionStreamHydrated,
    gateSessionStreamStatus,
    gatePersonaPromptGateId,
    gatePersonaPromptSeenRef,
    gateReplyContext,
  });

  // ─── Meshtastic Channel Discovery ──────────────────────────────────────
  useMeshChannelsPolling({
    expanded, activeTab, canUsePublicMeshInput, meshRegion, setMeshRoots, setMeshRegion,
  });

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
  } as any);

  // ─── Send Handlers ───────────────────────────────────────────────────────
  const selectedGateKeyEarly = selectedGate.trim().toLowerCase();
  const selectedGateAccessReady = Boolean(
    selectedGateKeyEarly && gateKeyStatus[selectedGateKeyEarly]?.has_local_access,
  );
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
    activePublicMeshAddress,
    decoyEnabled,
    newGateId,
    newGateName,
    newGateMinRep,
    setNewGateName,
    setNewGateMinRep,
    setShowCreateGate,
    openIdentityWizard,
    setPublicMeshAddress,
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
    
    
    
    
    
    
    
    sendError,
    clearGateResyncRequired,
    describeGateLocalRuntimeRequired,
    markGateResyncRequired,
    DM_DECOY_POLL_MS,
    DM_DECOY_POLL_JITTER_MS,
    enqueueDmSend,
    hasStoredPublicLaneIdentity,
    jitterDelay,
    promotePendingAlias,
    randomBase64,
    randomHex,
    refreshNativeAuditReport,
    activeGatePersonaId,
    gatePersonas,
    gateKeyStatus,
    setReps,
    votedOn,
    setVotedOn,
    voteScopeKey,
    hasSovereignty,
    
    
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
    openChat,
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
    ACCESS_REQUEST_BATCH_JITTER_MS,
    addContactId,
    anonymousPublicBlocked,
    enqueueDmSend,
    geoHintEnabled,
    jitterDelay,
    setAddContactId,
    setLastDmTransport,
    setShowAddContact,
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
  const {
    selectedGateKey, selectedGatePersonaList, selectedGateActivePersonaId, selectedGateActivePersona,
    selectedGateMeta, selectedGateCompatActive, selectedGateKeyStatus,
    gatePersonaPromptPersonaList, gatePersonaPromptGateMeta, gatePersonaPromptTitle,
    submitGatePersonaPrompt, selectSavedGatePersona, remainAnonymousInGate, nativeAuditSummary,
  } = useMeshGateDerivedState({
    selectedGate, gatePersonas, activeGatePersonaId, gates, gateCompatActive, gateKeyStatus,
    gatePersonaPromptGateId, gatePersonaDraftLabel, handleCreateGatePersona, handleSelectGatePersona,
    closeGatePersonaPrompt, nativeAuditReport,
  });

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

  const {
    disablePrivateNodeForPublicMesh,
    disableWormholeForPublicMesh,
    createPublicMeshIdentity,
    handleCreatePublicIdentity,
    handleQuickCreatePublicIdentity,
    handleActivatePublicMeshSession,
    handleReplyToMeshAddress,
    handleLeaveWormholeForPublicMesh,
    handleResetPublicIdentity,
    handleBootstrapPrivateIdentity,
    enterInfonetWormholeLane,
  } = useMeshIdentityHandlers({
    wormholeEnabled, wormholeReadyState, meshSessionActive, activePublicMeshAddress, meshMqttEnabled,
    publicMeshPrivacyEnforcedRef, setMeshQuickStatus, setWormholeEnabled, setWormholeReadyState,
    setWormholeRnsReady, setWormholeRnsDirectReady, setWormholeRnsPeers, setIdentityWizardBusy,
    setIdentityWizardStatus, setIdentityWizardOpen, setPublicMeshAddress, setMeshSessionActive, setMeshMessages,
    setSendError, setIdentity, setContacts, setActiveTab, hasStoredPublicLaneIdentity, wormholeDescriptor,
    setMeshDirectTarget, setMeshAddressDraft, setMeshView, setSenderPopup, inputRef,
    enableMeshMqttBridge, errorMessage, describeMeshChatControlError,
  });

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
