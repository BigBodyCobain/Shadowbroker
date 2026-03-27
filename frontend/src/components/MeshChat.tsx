'use client';

import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  ChevronUp,
  ChevronDown,
  Send,
  Plus,
  ArrowUp,
  ArrowDown,
  Radio,
  Shield,
  Terminal,
  UserPlus,
  Lock,
  Check,
  X,
  Ban,
  MapPin,
  EyeOff,
  Eye,
} from 'lucide-react';
import { API_BASE } from '@/lib/api';
import { controlPlaneJson } from '@/lib/controlPlane';
import { requestSecureMeshTerminalLauncherOpen } from '@/lib/meshTerminalLauncher';
import {
  loadIdentityBoundSensitiveValue,
  persistIdentityBoundSensitiveValue,
} from '@/lib/identityBoundSensitiveStorage';
import {
  getDesktopNativeControlAuditReport,
} from '@/lib/desktopBridge';
import { describeNativeControlError } from '@/lib/desktopControlContract';
import type { DesktopControlAuditReport } from '@/lib/desktopControlContract';
import { fetchPrivacyProfileSnapshot } from '@/mesh/controlPlaneStatusClient';
import {
  clearBrowserIdentityState,
  decryptSenderSealPayloadLocally,
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
  verifyNodeIdBindingFromPublicKey,
  unwrapSenderSealPayload,
  purgeBrowserContactGraph,
  purgeBrowserSigningMaterial,
  setSecureModeCached,
  migrateLegacyNodeIds,
  hydrateWormholeContacts,
  type NodeIdentity,
  type Contact,
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
  activateWormholeGatePersona,
  bootstrapWormholeIdentity,
  clearWormholeGatePersona,
  createWormholeGatePersona,
  decryptWormholeGateMessages,
  enterWormholeGate,
  fetchWormholeGateKeyStatus,
  fetchWormholeIdentity,
  fetchWormholeStatus,
  isWormholeReady,
  isWormholeSecureRequired,
  issueWormholePairwiseAlias,
  rotateWormholePairwiseAlias,
  listWormholeGatePersonas,
  openWormholeSenderSeal,
  retireWormholeGatePersona,
  rotateWormholeGateKey,
  signMeshEvent,
  type WormholeGateKeyStatus,
  type WormholeIdentity,
} from '@/mesh/wormholeIdentityClient';
import {
  gateEnvelopeDisplayText,
  gateEnvelopeState,
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
  shortTrustFingerprint,
  shouldAutoRevealSasForTrust,
} from '@/mesh/meshPrivacyHints';
import {
  getSenderRecoveryState,
  recoverSenderSealWithFallback,
  requiresSenderRecovery,
  shouldAllowRequestActions,
  shouldKeepUnresolvedRequestVisible,
  shouldPromoteRecoveredSenderForBootstrap,
  shouldPromoteRecoveredSenderForKnownContact,
} from '@/mesh/requestSenderRecovery';
import type { SenderRecoveryState } from '@/mesh/requestSenderRecovery';

// ─── Types ───────────────────────────────────────────────────────────────────

interface Gate {
  gate_id: string;
  display_name: string;
  description?: string;
  welcome?: string;
  creator: string;
  rules: { min_overall_rep?: number };
  message_count: number;
  fixed?: boolean;
  sort_order?: number;
}

interface InfoNetMessage {
  event_id: string;
  event_type?: string;
  node_id?: string;
  message?: string;
  ciphertext?: string;
  epoch?: number;
  nonce?: string;
  sender_ref?: string;
  format?: string;
  decrypted_message?: string;
  payload?: {
    gate?: string;
    ciphertext?: string;
    nonce?: string;
    sender_ref?: string;
    format?: string;
  };
  destination?: string;
  channel?: string;
  priority?: string;
  gate?: string;
  timestamp: number;
  sequence?: number;
  signature?: string;
  public_key?: string;
  public_key_algo?: string;
  protocol_version?: string;
  ephemeral?: boolean;
  system_seed?: boolean;
  fixed_gate?: boolean;
  gate_envelope?: string;
}

interface MeshtasticMessage {
  from: string;
  to?: string;
  text: string;
  region: string;
  root?: string;
  channel: string;
  timestamp: number | string;
}

interface DMMessage {
  sender_id: string;
  ciphertext: string;
  timestamp: number;
  msg_id: string;
  delivery_class?: 'request' | 'shared';
  transport?: 'reticulum' | 'relay';
  request_contract_version?: string;
  sender_recovery_required?: boolean;
  sender_recovery_state?: SenderRecoveryState;
  plaintext?: string;
  sender_seal?: string;
  seal_verified?: boolean;
  seal_resolution_failed?: boolean;
}

interface AccessRequest {
  sender_id: string;
  timestamp: number;
  dh_pub_key?: string;
  dh_algo?: string;
  geo_hint?: string;
  request_contract_version?: string;
  sender_recovery_required?: boolean;
  sender_recovery_state?: SenderRecoveryState;
}

interface SenderPopup {
  userId: string;
  x: number;
  y: number;
  tab: Tab;
  publicKey?: string;
  publicKeyAlgo?: string;
}

interface GateReplyContext {
  eventId: string;
  gateId: string;
  nodeId: string;
}

type Tab = 'infonet' | 'meshtastic' | 'dms';
type DMView = 'contacts' | 'inbox' | 'chat' | 'muted';
type DmTransportMode = 'reticulum' | 'relay' | 'ready' | 'hidden' | 'degraded' | 'blocked';

const DEFAULT_MESH_ROOTS = [
  'US',
  'EU_868',
  'EU_433',
  'CN',
  'JP',
  'KR',
  'TW',
  'RU',
  'IN',
  'ANZ',
  'ANZ_433',
  'NZ_865',
  'TH',
  'UA_868',
  'UA_433',
  'MY_433',
  'MY_919',
  'SG_923',
  'LORA_24',
  'EU',
  'AU',
  'UA',
  'BR',
  'AF',
  'ME',
  'SEA',
  'SA',
  'PL',
] as const;

function sortMeshRoots(
  roots: Iterable<string>,
  counts: Record<string, number> = {},
  currentRoot?: string,
): string[] {
  const unique = Array.from(
    new Set(
      Array.from(roots)
        .map((root) => String(root || '').trim())
        .filter(Boolean),
    ),
  );
  return unique.sort((a, b) => {
    if (a === currentRoot) return -1;
    if (b === currentRoot) return 1;
    const countDelta = (counts[b] || 0) - (counts[a] || 0);
    if (countDelta !== 0) return countDelta;
    return a.localeCompare(b);
  });
}

// Local storage keys for access requests
const ACCESS_REQUESTS_KEY = 'sb_dm_access_requests';
const PENDING_SENT_KEY = 'sb_dm_pending_sent';
const MUTED_KEY = 'sb_mesh_muted';
const GEO_HINT_KEY = 'sb_dm_geo_hint';
const ACCESS_REQ_WRAP_INFO = 'SB-ACCESS-REQUESTS-STORAGE-V1';
const PENDING_WRAP_INFO = 'SB-PENDING-CONTACTS-STORAGE-V1';
const MUTED_WRAP_INFO = 'SB-MUTED-LIST-V1';

function normalizeInfoNetMessage(message: InfoNetMessage): InfoNetMessage {
  const payload =
    message.payload && typeof message.payload === 'object'
      ? message.payload
      : undefined;
  if (!payload) {
    return message;
  }
  return {
    ...message,
    gate: String(message.gate ?? payload.gate ?? ''),
    ciphertext: String(message.ciphertext ?? payload.ciphertext ?? ''),
    nonce: String(message.nonce ?? payload.nonce ?? ''),
    sender_ref: String(message.sender_ref ?? payload.sender_ref ?? ''),
    format: String(message.format ?? payload.format ?? ''),
  };
}

async function buildGateAccessHeaders(gateId: string): Promise<Record<string, string> | undefined> {
  const normalizedGate = String(gateId || '').trim().toLowerCase();
  if (!normalizedGate) return undefined;
  pruneExpiredGateAccessHeaders();
  const cached = gateAccessHeaderCache.get(normalizedGate);
  if (cached && cached.expiresAt > Date.now()) {
    return cached.headers;
  }
  try {
    const proof = await controlPlaneJson<{ node_id?: string; ts?: number; proof?: string }>(
      '/api/wormhole/gate/proof',
      {
        requireAdminSession: false,
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ gate_id: normalizedGate }),
      },
    );
    const nodeId = String(proof.node_id || '').trim();
    const gateProof = String(proof.proof || '').trim();
    const gateTs = String(proof.ts || '').trim();
    if (!nodeId || !gateProof || !gateTs) return undefined;
    const headers = {
      'X-Wormhole-Node-Id': nodeId,
      'X-Wormhole-Gate-Proof': gateProof,
      'X-Wormhole-Gate-Ts': gateTs,
    };
    gateAccessHeaderCache.set(normalizedGate, {
      headers,
      expiresAt: Date.now() + GATE_ACCESS_PROOF_TTL_MS,
    });
    return headers;
  } catch {
    return undefined;
  }
}

const GATE_ACCESS_PROOF_TTL_MS = 45_000;
const GATE_DECRYPT_CACHE_MAX = 256;
const INFO_VERIFICATION_CACHE_MAX = 512;
const gateAccessHeaderCache = new Map<string, { headers: Record<string, string>; expiresAt: number }>();

function pruneExpiredGateAccessHeaders(now: number = Date.now()): void {
  for (const [gateId, entry] of gateAccessHeaderCache.entries()) {
    if (entry.expiresAt <= now) {
      gateAccessHeaderCache.delete(gateId);
    }
  }
}

function gateDecryptCacheKey(message: InfoNetMessage): string {
  const eventId = String(message.event_id || '').trim();
  if (eventId) {
    return eventId;
  }
  return [
    String(message.gate || '').trim().toLowerCase(),
    String(message.ciphertext || '').trim(),
    String(message.sender_ref || '').trim(),
    String(message.nonce || '').trim(),
  ].join('|');
}

const DECOY_KEY = 'sb_dm_decoy';
const DM_UNREAD_POLL_EXPANDED_MS = 15_000;
const DM_UNREAD_POLL_EXPANDED_JITTER_MS = 2_500;
const DM_UNREAD_POLL_COLLAPSED_MS = 60_000;
const DM_UNREAD_POLL_COLLAPSED_JITTER_MS = 10_000;
const DM_MESSAGES_POLL_MS = 10_000;
const DM_MESSAGES_POLL_JITTER_MS = 2_000;
const DM_DECOY_POLL_MS = 210_000;
const DM_DECOY_POLL_JITTER_MS = 90_000;
const ACCESS_REQUEST_BATCH_DELAY_MS = 1_400;
const ACCESS_REQUEST_BATCH_JITTER_MS = 900;
const SHARED_ALIAS_ROTATE_MS = 6 * 60 * 60 * 1000;
const SHARED_ALIAS_GRACE_MS = 45_000;

function scopedDmStateKey(base: string, nodeId?: string): string {
  const resolved = String(nodeId || getNodeIdentity()?.nodeId || 'global').trim() || 'global';
  return `${base}:${resolved}`;
}

async function getAccessRequests(nodeId?: string): Promise<AccessRequest[]> {
  const storageKey = scopedDmStateKey(ACCESS_REQUESTS_KEY, nodeId);
  try {
    const requests = await loadIdentityBoundSensitiveValue<AccessRequest[]>(
      storageKey,
      ACCESS_REQ_WRAP_INFO,
      [],
    );
    const normalized = Array.isArray(requests) ? requests : [];
    return normalized;
  } catch (error) {
    console.warn('[mesh] failed to read encrypted access requests', error);
    return [];
  }
}
function setAccessRequests(reqs: AccessRequest[], nodeId?: string) {
  const storageKey = scopedDmStateKey(ACCESS_REQUESTS_KEY, nodeId);
  void (async () => {
    try {
      await persistIdentityBoundSensitiveValue(storageKey, ACCESS_REQ_WRAP_INFO, reqs);
    } catch (error) {
      console.warn('[mesh] failed to persist encrypted access requests', error);
    }
  })();
}

async function decryptSenderSeal(
  senderSeal: string,
  candidateDhPub: string,
  recipientId: string,
  expectedMsgId: string,
): Promise<{ sender_id: string; seal_verified: boolean } | null> {
  const openLocal = async (): Promise<{ sender_id: string; seal_verified: boolean } | null> => {
    try {
      const sealEnvelope = unwrapSenderSealPayload(senderSeal);
      const sealText = await decryptSenderSealPayloadLocally(
        senderSeal,
        candidateDhPub,
        recipientId,
        expectedMsgId,
      );
      if (!sealText) {
        return null;
      }
      const seal = JSON.parse(sealText || '{}');
      const senderId = String(seal.sender_id || '');
      const publicKey = String(seal.public_key || '');
      const publicKeyAlgo = String(seal.public_key_algo || '');
      const sealMsgId = String(seal.msg_id || '');
      const sealTs = Number(seal.timestamp || 0);
      const signature = String(seal.signature || '');
      if (!senderId || !publicKey || !publicKeyAlgo || !sealMsgId || !signature) {
        return null;
      }
      if (sealMsgId !== expectedMsgId) {
        return null;
      }
      const isBound = await verifyNodeIdBindingFromPublicKey(publicKey, senderId);
      if (!isBound) {
        return { sender_id: senderId, seal_verified: false };
      }
      const sealMessage =
        sealEnvelope.version === 'v3'
          ? `seal|v3|${sealMsgId}|${sealTs}|${recipientId}|${String(sealEnvelope.ephemeralPub || '')}`
          : `seal|${sealMsgId}|${sealTs}|${recipientId}`;
      const verified = await verifyRawSignature({
        message: sealMessage,
        signature,
        publicKey,
        publicKeyAlgo,
      });
      return { sender_id: senderId, seal_verified: verified };
    } catch {
      return null;
    }
  };

  const openHelper = async (): Promise<{ sender_id: string; seal_verified: boolean } | null> => {
    const opened = await openWormholeSenderSeal(
      senderSeal,
      candidateDhPub,
      recipientId,
      expectedMsgId,
    );
    return {
      sender_id: String(opened.sender_id || ''),
      seal_verified: Boolean(opened.seal_verified),
    };
  };

  return recoverSenderSealWithFallback({
    wormholeReady: await isWormholeReady(),
    openLocal,
    openHelper,
  });
}

async function decryptSenderSealForContact(
  senderSeal: string,
  candidateDhPub: string,
  contact: Contact | undefined,
  ownNodeId: string,
  expectedMsgId: string,
): Promise<{ sender_id: string; seal_verified: boolean } | null> {
  for (const recipientId of allDmPeerIds(ownNodeId, { sharedAlias: contact?.sharedAlias })) {
    const opened = await decryptSenderSeal(senderSeal, candidateDhPub, recipientId, expectedMsgId);
    if (opened) return opened;
  }
  return null;
}

function promotePendingAlias(contactId: string, contact: Contact | undefined): Contact | undefined {
  if (!contact?.pendingSharedAlias) return contact;
  const graceUntil = Number(contact.sharedAliasGraceUntil || 0);
  if (graceUntil > Date.now()) return contact;
  const nextAlias = String(contact.pendingSharedAlias || '').trim();
  const currentAlias = String(contact.sharedAlias || '').trim();
  const updates: Partial<Contact> = {
    sharedAlias: nextAlias || currentAlias,
    pendingSharedAlias: undefined,
    sharedAliasGraceUntil: undefined,
    sharedAliasRotatedAt: Date.now(),
    previousSharedAliases: mergeAliasHistory([
      currentAlias,
      ...(contact.previousSharedAliases || []),
    ]),
  };
  updateContact(contactId, updates);
  return getContacts()[contactId];
}

function randomHex(bytes: number = 16): string {
  const buf = new Uint8Array(bytes);
  crypto.getRandomValues(buf);
  return Array.from(buf)
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
}

function jitterDelay(baseMs: number, spreadMs: number): number {
  const jitter = Math.floor((Math.random() * 2 - 1) * spreadMs);
  return Math.max(3000, baseMs + jitter);
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function dmTransportDisplay(mode: DmTransportMode): { label: string; className: string } {
  switch (mode) {
    case 'reticulum':
      return {
        label: 'DIRECT PRIVATE',
        className: 'border-green-500/30 text-green-400 bg-green-950/20',
      };
    case 'relay':
      return {
        label: 'RELAY FALLBACK',
        className: 'border-yellow-500/30 text-yellow-400 bg-yellow-950/20',
      };
    case 'ready':
      return {
        label: 'SECURE READY',
        className: 'border-cyan-500/30 text-cyan-400 bg-cyan-950/20',
      };
    case 'hidden':
      return {
        label: 'HIDDEN RELAY',
        className: 'border-cyan-500/30 text-cyan-300 bg-cyan-950/20',
      };
    case 'blocked':
      return {
        label: 'WORMHOLE BLOCKED',
        className: 'border-red-500/30 text-red-400 bg-red-950/20',
      };
    default:
      return {
        label: 'PUBLIC / DEGRADED',
        className: 'border-orange-500/30 text-orange-400 bg-orange-950/20',
      };
  }
}

function randomBase64(bytes: number = 64): string {
  const buf = new Uint8Array(bytes);
  crypto.getRandomValues(buf);
  return btoa(String.fromCharCode(...buf));
}
async function getPendingSent(nodeId?: string): Promise<string[]> {
  const storageKey = scopedDmStateKey(PENDING_SENT_KEY, nodeId);
  try {
    const pending = await loadIdentityBoundSensitiveValue<string[]>(storageKey, PENDING_WRAP_INFO, []);
    const normalized = Array.isArray(pending) ? pending : [];
    return normalized;
  } catch (error) {
    console.warn('[mesh] failed to read encrypted pending contacts', error);
    return [];
  }
}
function setPendingSent(ids: string[], nodeId?: string) {
  const storageKey = scopedDmStateKey(PENDING_SENT_KEY, nodeId);
  void (async () => {
    try {
      await persistIdentityBoundSensitiveValue(storageKey, PENDING_WRAP_INFO, ids);
    } catch (error) {
      console.warn('[mesh] failed to persist encrypted pending contacts', error);
    }
  })();
}
function getGeoHintEnabled(): boolean {
  try {
    return localStorage.getItem(GEO_HINT_KEY) === 'true';
  } catch {
    return false;
  }
}
function setGeoHintEnabled(value: boolean) {
  localStorage.setItem(GEO_HINT_KEY, value ? 'true' : 'false');
}
function getDecoyEnabled(): boolean {
  try {
    return localStorage.getItem(DECOY_KEY) === 'true';
  } catch {
    return false;
  }
}
function setDecoyEnabled(value: boolean) {
  localStorage.setItem(DECOY_KEY, value ? 'true' : 'false');
}
async function getMutedList(nodeId?: string): Promise<string[]> {
  const storageKey = scopedDmStateKey(MUTED_KEY, nodeId);
  try {
    const muted = await loadIdentityBoundSensitiveValue<string[]>(
      storageKey,
      MUTED_WRAP_INFO,
      [],
      { legacyKey: MUTED_KEY },
    );
    const normalized = Array.isArray(muted) ? muted : [];
    return normalized;
  } catch {
    return [];
  }
}
function saveMutedList(ids: string[], nodeId?: string) {
  const storageKey = scopedDmStateKey(MUTED_KEY, nodeId);
  void (async () => {
    try {
      await persistIdentityBoundSensitiveValue(storageKey, MUTED_WRAP_INFO, ids, {
        legacyKey: MUTED_KEY,
      });
    } catch {
      /* ignore */
    }
  })();
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

// Alternating message colors — client-side only, not stored
const MSG_COLORS = ['text-cyan-300', 'text-[#ff69b4]', 'text-yellow-300', 'text-gray-200'];

function timeAgo(ts: number): string {
  const now = Date.now() / 1000;
  const diff = now - ts;
  if (diff < 60) return `${Math.floor(diff)}s`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h`;
  return `${Math.floor(diff / 86400)}d`;
}

// ─── Rep Badge ───────────────────────────────────────────────────────────────

function RepBadge({ rep }: { rep: number }) {
  const color =
    rep >= 50
      ? 'text-yellow-400'
      : rep >= 10
        ? 'text-cyan-400'
        : rep > 0
          ? 'text-cyan-600'
          : rep < 0
            ? 'text-red-400'
            : 'text-gray-600';
  return (
    <span className={`text-[13px] font-mono font-bold ${color} shrink-0`}>
      {rep >= 0 ? '+' : ''}
      {rep}
    </span>
  );
}

// ─── Component ───────────────────────────────────────────────────────────────

interface MeshChatProps {
  onFlyTo?: (lat: number, lng: number) => void;
  expanded?: boolean;
  onExpandedChange?: (expanded: boolean) => void;
  onSettingsClick?: () => void;
  onTerminalToggle?: () => void;
  launchRequest?: { tab: Tab; gate?: string; nonce: number } | null;
}

const MeshChat = React.memo(function MeshChat({
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
        if (privacyProfile !== 'high') {
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
  const activeGateSessionRef = useRef<string>('');
  const [gatePersonas, setGatePersonas] = useState<Record<string, WormholeIdentity[]>>({});
  const [activeGatePersonaId, setActiveGatePersonaId] = useState<Record<string, string>>({});
  const [gatePersonaBusy, setGatePersonaBusy] = useState(false);
  const [gateKeyStatus, setGateKeyStatus] = useState<Record<string, WormholeGateKeyStatus>>({});
  const [gateKeyBusy, setGateKeyBusy] = useState(false);
  const [gatePersonaPromptOpen, setGatePersonaPromptOpen] = useState(false);
  const [gatePersonaPromptGateId, setGatePersonaPromptGateId] = useState('');
  const [gatePersonaDraftLabel, setGatePersonaDraftLabel] = useState('');
  const [gatePersonaPromptError, setGatePersonaPromptError] = useState('');
  const gatePersonaPromptSeenRef = useRef<Set<string>>(new Set());
  const [nativeAuditReport, setNativeAuditReport] = useState<DesktopControlAuditReport | null>(null);
  const gateDecryptCacheRef = useRef<Map<string, { plaintext: string; epoch: number }>>(new Map());
  const infoVerificationCacheRef = useRef<Map<string, 'verified' | 'failed' | 'unsigned'>>(
    new Map(),
  );
  const infoPollSignatureRef = useRef<string>('');

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
            })),
          );
          const results = Array.isArray(batch.results) ? batch.results : [];
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
              };
              return;
            }
            hydrated[index] = { ...message, decrypted_message: '' };
          });
        } catch {
          pendingDecrypts.forEach(({ index, message }) => {
            hydrated[index] = { ...message, decrypted_message: '' };
          });
        }
      }

      return hydrated.map(
        (message, index) => message ?? { ...baseMessages[index], decrypted_message: '' },
      );
    },
    [wormholeEnabled, wormholeReadyState],
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
        const res = await fetch(`${API_BASE}/api/mesh/gate/list`);
        if (res.ok) {
          const data = await res.json();
          setGates(data.gates || []);
          if (!selectedGate && data.gates?.length) {
            setSelectedGate(data.gates[0].gate_id);
          }
        }
      } catch {
        /* ignore */
      }
    };
    fetchGates();
  }, [expanded, selectedGate]);

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

        let status = await fetchWormholeGateKeyStatus(nextGate).catch(() => null);
        if (cancelled) return;
        if (status) {
          const nextStatus = status as WormholeGateKeyStatus;
          setGateKeyStatus((prev) => ({ ...prev, [nextGate]: nextStatus }));
        }
        if (status?.ok && status.has_local_access) {
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
          status = await fetchWormholeGateKeyStatus(nextGate).catch(() => null);
          if (cancelled) return;
          if (status) {
            const nextStatus = status as WormholeGateKeyStatus;
            setGateKeyStatus((prev) => ({ ...prev, [nextGate]: nextStatus }));
          }
          if (!cancelled && status?.ok && status.has_local_access) {
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
          status = await fetchWormholeGateKeyStatus(nextGate).catch(() => null);
          if (cancelled) return;
          if (status) {
            const nextStatus = status as WormholeGateKeyStatus;
            setGateKeyStatus((prev) => ({ ...prev, [nextGate]: nextStatus }));
          }
          if (!cancelled && status?.ok && status.has_local_access) {
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

  useEffect(() => {
    if (!wormholeEnabled || !wormholeReadyState || !selectedGate) return;
    let cancelled = false;
    const gateId = selectedGate.trim().toLowerCase();
    const loadGateKeyStatus = async () => {
      try {
        const data = await fetchWormholeGateKeyStatus(gateId).catch(() => null);
        if (!data || cancelled) return;
        setGateKeyStatus((prev) => ({ ...prev, [gateId]: data }));
      } catch {
        /* ignore */
      }
    };
    void loadGateKeyStatus();
    return () => {
      cancelled = true;
    };
  }, [selectedGate, wormholeEnabled, wormholeReadyState, gatePersonaBusy]);

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
    if (!expanded || activeTab !== 'infonet') return;
    const gateId = selectedGate.trim().toLowerCase();
    const gateStatus = gateId ? gateKeyStatus[gateId] || null : null;
    const gateAccessReady = !gateId || Boolean(gateStatus?.has_local_access);
    if (gateId && (!gateAccessReady || gatePersonaBusy || gatePersonaPromptOpen)) {
      return;
    }
    let cancelled = false;
    const poll = async () => {
      try {
        const params = new URLSearchParams({ limit: '30' });
        if (selectedGate) params.set('gate', selectedGate);
        const headers = selectedGate ? await buildGateAccessHeaders(selectedGate) : undefined;
        if (selectedGate && !headers) {
          return;
        }
        const res = await fetch(`${API_BASE}/api/mesh/infonet/messages?${params}`, {
          headers,
        });
        if (res.ok && !cancelled) {
          const data = await res.json();
          const rawMessages = Array.isArray(data.messages)
            ? (data.messages as InfoNetMessage[]).map(normalizeInfoNetMessage)
            : [];
          const pollSignature = [
            selectedGate,
            wormholeEnabled ? '1' : '0',
            wormholeReadyState ? '1' : '0',
            rawMessages.map((message) => String(message.event_id || '')).join('|'),
          ].join('::');
          if (infoPollSignatureRef.current !== pollSignature) {
            const hydrated = await hydrateInfonetMessages(rawMessages);
            if (!cancelled) {
              infoPollSignatureRef.current = pollSignature;
              setInfoMessages(hydrated.reverse());
            }
          }
          const nodeIds = [
            ...new Set(
              rawMessages
                .map((m: InfoNetMessage) => String(m.node_id || '').trim())
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
              const r = await fetch(`${API_BASE}/api/mesh/reputation/batch?${repParams.toString()}`);
              if (r.ok) {
                const rd = await r.json();
                const reputations =
                  rd && typeof rd.reputations === 'object' && rd.reputations ? rd.reputations : {};
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
        }
      } catch {
        /* ignore */
      }
    };
    poll();
    const iv = setInterval(poll, 10000);
    return () => {
      cancelled = true;
      clearInterval(iv);
    };
  }, [
    expanded,
    activeTab,
    selectedGate,
    gateKeyStatus,
    gatePersonaBusy,
    gatePersonaPromptOpen,
    hydrateInfonetMessages,
  ]);

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
    if (!hasId || !getDMNotify()) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const schedule = () => {
      const delay = expanded
        ? jitterDelay(DM_UNREAD_POLL_EXPANDED_MS, DM_UNREAD_POLL_EXPANDED_JITTER_MS)
        : jitterDelay(DM_UNREAD_POLL_COLLAPSED_MS, DM_UNREAD_POLL_COLLAPSED_JITTER_MS);
      timer = setTimeout(poll, delay);
    };
    const poll = async () => {
      if ((wormholeEnabled && !wormholeReadyState) || anonymousDmBlocked) {
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
  }, [hasId, identity, expanded, wormholeEnabled, wormholeReadyState, anonymousDmBlocked]);

  // Poll DM messages — also detect access requests (messages from unknown senders)
  useEffect(() => {
    if (!expanded || activeTab !== 'dms' || !hasId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const schedule = () => {
      timer = setTimeout(poll, jitterDelay(DM_MESSAGES_POLL_MS, DM_MESSAGES_POLL_JITTER_MS));
    };
    const poll = async () => {
      if ((wormholeEnabled && !wormholeReadyState) || anonymousDmBlocked) {
        if (!cancelled) setDmMessages([]);
        if (!cancelled) schedule();
        return;
      }
      try {
        const claims = await buildMailboxClaims(getContacts());
        const data = await pollDmMailboxes(API_BASE, identity!, claims);
        if (data.ok && !cancelled) {
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
                  const senderKey = await fetchDmPublicKey(API_BASE, m.sender_id);
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
                const senderKey = await fetchDmPublicKey(API_BASE, m.sender_id).catch(() => null);
                if (senderKey?.dh_pub_key) {
                  addContact(m.sender_id, String(senderKey.dh_pub_key), undefined, senderKey.dh_algo);
                  updateContact(m.sender_id, {
                    dhAlgo: senderKey.dh_algo,
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
        if (!cancelled) schedule();
      }
    };
    poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [expanded, activeTab, selectedContact, hasId, identity, dmView, wormholeEnabled, wormholeReadyState, anonymousDmBlocked]);

  // SAS phrase for active DM contact
  useEffect(() => {
    let cancelled = false;
    setShowSas(false);
    setSasPhrase('');
    const run = async () => {
      if (!selectedContact) return;
      const contactInfo = contacts[selectedContact];
      if (!contactInfo?.dhPubKey) return;
      try {
        const phrase = await deriveSasPhrase(selectedContact, contactInfo.dhPubKey);
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

    if (activeTab === 'infonet' && selectedGate && !selectedGateAccessReady) {
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
          const gateRes = await fetch(`${API_BASE}/api/wormhole/gate/message/post`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              gate_id: selectedGate,
              plaintext: `${gateReplyPrefix}${msg}`,
            }),
          });
          const gateData = await gateRes.json().catch(() => ({}));
          if (!gateRes.ok || gateData?.ok === false) {
            setInputValue(msg);
            setLastSendTime(0);
            setSendError(gateData?.detail || 'gate post failed');
            setTimeout(() => setSendError(''), 4000);
            return;
        }
        const params = new URLSearchParams({ limit: '30', gate: selectedGate });
        const res = await fetch(`${API_BASE}/api/mesh/infonet/messages?${params}`, {
          headers: await buildGateAccessHeaders(selectedGate),
        });
        if (res.ok) {
          const data = await res.json();
          const hydrated = await hydrateInfonetMessages([...(data.messages || [])]);
          setInfoMessages(hydrated.reverse());
        }
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
              const effectiveContact = promotePendingAlias(selectedContact, rotatedContact) || rotatedContact;
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
      const res = await fetch(`${API_BASE}/api/mesh/gate/list`);
      if (res.ok) {
        const data = await res.json();
        setGates(data.gates || []);
        setSelectedGate(newGateId.trim().toLowerCase());
      }
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
      await refreshSelectedGatePersonas(gateId);
      await refreshSelectedGateKeyStatus(gateId);
      return true;
    } catch (err) {
      const detail = describeNativeControlError(err) || 'Failed to create persona';
      setGateError(detail);
      setGatePersonaPromptError(detail);
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
      await refreshSelectedGatePersonas(gateId);
      await refreshSelectedGateKeyStatus(gateId);
      refreshNativeAuditReport();
      return true;
    } catch (err) {
      const detail = describeNativeControlError(err) || 'Failed to switch gate persona';
      setGateError(detail);
      setGatePersonaPromptError(detail);
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
      await refreshSelectedGatePersonas(gateId);
      await refreshSelectedGateKeyStatus(gateId);
      refreshNativeAuditReport();
    } catch (err) {
      setGateError(describeNativeControlError(err) || 'Failed to retire persona');
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
      setGateKeyStatus((prev) => ({ ...prev, [gateId]: rotated }));
      await refreshSelectedGatePersonas(gateId);
      refreshNativeAuditReport();
    } catch (err) {
      setGateError(describeNativeControlError(err) || 'Failed to rotate gate key');
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
    const refreshed = promotePendingAlias(contactId, contact) || contact;
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
    const registry = await fetchDmPublicKey(API_BASE, targetId).catch(() => null);
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
    } catch {
      setSendError('dm refresh failed');
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
    } catch {
      setSendError('dm reset failed');
      setTimeout(() => setSendError(''), 3000);
    } finally {
      setDmMaintenanceBusy(false);
    }
  };

  const handleTrustSelectedRemotePrekey = async (): Promise<void> => {
    if (!selectedContact || dmMaintenanceBusy) return;
    const contactInfo = getContacts()[selectedContact] || contacts[selectedContact];
    const observedFingerprint = String(contactInfo?.remotePrekeyObservedFingerprint || '')
      .trim()
      .toLowerCase();
    if (!observedFingerprint) {
      setSendError('no observed remote prekey to trust');
      setTimeout(() => setSendError(''), 3000);
      return;
    }
    const now = Math.floor(Date.now() / 1000);
    setDmMaintenanceBusy(true);
    try {
      updateContact(selectedContact, {
        remotePrekeyFingerprint: observedFingerprint,
        remotePrekeyObservedFingerprint: observedFingerprint,
        remotePrekeyPinnedAt: now,
        remotePrekeyLastSeenAt: now,
        remotePrekeyMismatch: false,
      });
      const hydratedContacts = await hydrateWormholeContacts(true).catch(() => getContacts());
      setContacts(hydratedContacts);
      setShowSas(true);
    } catch {
      setSendError('failed to trust remote prekey');
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
      const targetKey = await fetchDmPublicKey(API_BASE, targetId);
      if (!targetKey?.dh_pub_key) return;
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
    } catch {
      /* ignore */
    }
  };

  const handleAcceptRequest = async (senderId: string) => {
    if (!hasId) return;
    if (anonymousDmBlocked) {
      setSendError('hidden transport required for anonymous dm');
      setTimeout(() => setSendError(''), 3000);
      return;
    }
    try {
      // Fetch their pubkey
      const res = await fetch(
        `${API_BASE}/api/mesh/dm/pubkey?agent_id=${encodeURIComponent(senderId)}`,
      );
        if (res.ok) {
          const data = await res.json();
          if (data.dh_pub_key) {
            addContact(senderId, data.dh_pub_key, undefined, data.dh_algo);
            const req = accessRequests.find((r) => r.sender_id === senderId);
            const inbandKey = req?.dh_pub_key;
            const registryKey = String(data.dh_pub_key || '');
            const inbandOk = Boolean(inbandKey);
            let registryOk = Boolean(registryKey);
            if (registryOk && data.signature && data.public_key && data.public_key_algo) {
              try {
                const keyPayload = {
                  dh_pub_key: data.dh_pub_key,
                  dh_algo: data.dh_algo,
                  timestamp: data.timestamp,
                };
                registryOk = await verifyEventSignature({
                  eventType: 'dm_key',
                  nodeId: senderId,
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
            const match = inbandOk && registryOk ? inbandKey === registryKey : false;
            updateContact(senderId, {
              verify_inband: inbandOk,
              verify_registry: registryOk,
              verified: match,
              verify_mismatch: inbandOk && registryOk && !match,
              verified_at: match ? Date.now() : undefined,
              dhAlgo: data.dh_algo || req?.dh_algo,
            });
            try {
              const witnessPayload = {
                target_id: senderId,
                dh_pub_key: data.dh_pub_key,
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
                    dh_pub_key: data.dh_pub_key,
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
                )}&dh_pub_key=${encodeURIComponent(data.dh_pub_key)}`,
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
          // Remove from access requests
          const updated = accessRequests.filter((r) => r.sender_id !== senderId);
          setAccessRequests(updated, dmConsentScopeId);
          setAccessRequestsState(updated);
          setContacts(getContacts());
          // Deliver the private consent handoff off-ledger, then switch future
          // shared traffic onto the pairwise alias.
          const registration = await ensureRegisteredDmKey(API_BASE, identity!, { force: false });
          if (registration.ok) {
            let sharedAlias = '';
            try {
              const pairwiseAlias = await issueWormholePairwiseAlias(
                senderId,
                String(data.dh_pub_key || ''),
              );
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
              const sharedKey = await deriveSharedKey(String(data.dh_pub_key));
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
                recipientDhPub: String(data.dh_pub_key || ''),
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
        }
      }
    } catch {
      /* ignore */
    }
  };

  const handleDenyRequest = (senderId: string) => {
    void (async () => {
      try {
        const req = accessRequests.find((r) => r.sender_id === senderId);
        const targetKey =
          req?.dh_pub_key
            ? { dh_pub_key: req.dh_pub_key, dh_algo: req.dh_algo || 'X25519' }
            : await fetchDmPublicKey(API_BASE, senderId).catch(() => null);
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
        const res = await fetch(`${API_BASE}/api/mesh/dm/pubkey?agent_id=${encodeURIComponent(cid)}`);
        if (res.ok) {
          const data = await res.json();
          if (data.dh_pub_key) {
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
  const useSavedGatePersona = useCallback(
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

  return (
    <div
      onClick={handlePanelClick}
      className={`pointer-events-auto flex flex-col ${expanded ? 'flex-1 min-h-[300px]' : 'flex-shrink-0'}`}
    >
      {/* Single unified box — matches Data Layers panel skin */}
      <div
        className={`bg-[#0a0a0a]/90 backdrop-blur-sm border border-cyan-900/40 flex flex-col relative overflow-hidden`}
        style={{ boxShadow: '0 0 15px rgba(8,145,178,0.06), inset 0 0 20px rgba(0,0,0,0.4)', ...(expanded ? { flex: '1 1 0', minHeight: 0 } : {}) }}
      >
        {/* HEADER */}
        <div
          onClick={() => setExpanded(!expanded)}
          className="flex justify-between items-center p-4 cursor-pointer hover:bg-[var(--bg-secondary)]/50 transition-colors border-b border-[var(--border-primary)]/50 shrink-0 select-none"
        >
          <div className="flex items-center gap-2">
            <span className="text-cyan-800/50 font-mono text-[13px] select-none">──</span>
            <span className="text-[12px] text-cyan-400/90 font-mono tracking-widest" style={{ textShadow: '0 0 8px rgba(34,211,238,0.3)' }}>
              MESH CHAT
            </span>
            <span className="text-cyan-800/50 font-mono text-[13px] select-none overflow-hidden whitespace-nowrap flex-1">──────────────────────────────</span>
          </div>
          <div className="flex items-center gap-2">
            {totalDmNotify > 0 && (
              <span className="flex items-center gap-1">
                <span className="w-2 h-2 rounded-full bg-cyan-400 animate-[blink_1s_step-end_infinite]" />
                <span className="text-[13px] font-mono text-cyan-400">{totalDmNotify}</span>
              </span>
            )}
            {expanded ? (
              <ChevronUp size={14} className="text-cyan-400" />
            ) : (
              <ChevronDown size={14} className="text-cyan-400" />
            )}
          </div>
        </div>

        {/* EXPANDED BODY */}
        {expanded && (
          <div className="flex-1 min-h-0 flex flex-col overflow-hidden">
            {/* TAB BAR */}
            <div className="flex border-b border-[var(--border-primary)]/50 shrink-0">
              {[
                { key: 'infonet' as Tab, label: 'INFONET', icon: <Shield size={10} />, badge: 0 },
                { key: 'meshtastic' as Tab, label: 'MESH', icon: <Radio size={10} />, badge: 0 },
                {
                  key: 'dms' as Tab,
                  label: 'DEAD DROP',
                  icon: <Lock size={10} />,
                  badge: totalDmNotify,
                },
              ].map((tab) => (
                <button
                  key={tab.key}
                  onClick={() => {
                    setActiveTab(tab.key);
                    if (tab.key === 'dms') setDmView('contacts');
                  }}
                  className={`flex-1 flex items-center justify-center gap-1 py-1.5 text-[12px] font-mono tracking-wider transition-colors ${
                    activeTab === tab.key
                      ? 'text-cyan-300 bg-cyan-950/50 font-bold border-b border-cyan-500/50'
                      : 'text-[var(--text-muted)] hover:text-cyan-600 border-b border-cyan-900/20'
                  }`}
                >
                  {tab.icon}
                  {tab.label}
                  {tab.badge > 0 && (
                    <span className="ml-0.5 w-1.5 h-1.5 rounded-full bg-cyan-400 animate-[blink_1s_step-end_infinite]" />
                  )}
                </button>
              ))}
              <button
                onClick={() => {
                  setIdentityWizardStatus(null);
                  setIdentityWizardOpen(true);
                }}
                className="px-3 flex items-center justify-center border-b border-cyan-900/20 text-[var(--text-muted)] hover:text-cyan-400 hover:bg-cyan-950/30 transition-colors"
                title="Identity and OPSEC setup"
              >
                <UserPlus size={11} />
              </button>
            </div>

            {privacyProfile === 'high' && !wormholeEnabled && (
              <div className="px-3 py-2 text-sm font-mono text-red-400/90 border-b border-red-900/30 bg-red-950/20 leading-[1.65] shrink-0">
                High Privacy is ON but Wormhole is OFF. Private messaging is blocked until
                Wormhole is enabled.
              </div>
            )}

            {activeTab !== 'meshtastic' && wormholeEnabled && !wormholeReadyState && (
              <div className="px-3 py-2 text-sm font-mono text-red-400/90 border-b border-red-900/30 bg-red-950/20 leading-[1.65] shrink-0">
                Wormhole secure mode is enabled but the local agent is not ready. Dead Drop is
                blocked until Wormhole is running.
              </div>
            )}

            {activeTab !== 'meshtastic' && wormholeEnabled && wormholeReadyState && (
              <div className="px-3 py-2 text-sm font-mono text-yellow-400/80 border-b border-yellow-900/20 bg-yellow-950/10 leading-[1.65] shrink-0">
                Wormhole secure mode is active. Experimental private-lane operations are routed
                through the local agent and current secure transport paths.
              </div>
            )}

            {activeTab !== 'meshtastic' && wormholeEnabled && wormholeReadyState && !wormholeRnsReady && (
              <div className="px-3 py-2 text-sm font-mono text-amber-300/90 border-b border-amber-900/30 bg-amber-950/20 leading-[1.65] shrink-0">
                EXPERIMENTAL ENCRYPTION. Wormhole is up, gate chat is available, and Reticulum is
                still warming on the strongest lane. Direct private DM posture remains separate in
                this testnet build.
              </div>
            )}

            {anonymousModeEnabled && !anonymousModeReady && (
              <div className="px-3 py-2 text-sm font-mono text-red-400/90 border-b border-red-900/30 bg-red-950/20 leading-[1.65] shrink-0">
                Anonymous mode is active, but hidden transport is not ready. Dead Drop is blocked
                until Wormhole is running over Tor, I2P, or Mixnet.
              </div>
            )}

            {/* No identity warning */}
            {shouldShowIdentityWarning && (
              <div className="px-3 py-2 text-sm font-mono text-yellow-500/80 border-b border-yellow-900/20 bg-yellow-950/10 leading-[1.65] shrink-0">
                <Lock size={9} className="inline mr-1" />
                Run <span className="text-cyan-400">connect</span> in MeshTerminal first, or open
                <button
                  onClick={() => {
                    setIdentityWizardStatus(null);
                    setIdentityWizardOpen(true);
                  }}
                  className="ml-1 text-cyan-400 hover:text-cyan-300 underline underline-offset-2"
                >
                  IDENTITY SETUP
                </button>
              </div>
            )}

            {privateLaneHint && (
              <div
                className={`px-3 py-2 border-b leading-[1.65] shrink-0 ${
                  privateLaneHint.severity === 'danger'
                    ? 'border-red-900/30 bg-red-950/20 text-red-300'
                    : 'border-amber-900/30 bg-amber-950/10 text-amber-200'
                }`}
              >
                <div className="text-[13px] font-mono tracking-[0.18em] mb-1">
                  {privateLaneHint.title}
                </div>
                <div className="text-sm font-mono">{privateLaneHint.detail}</div>
              </div>
            )}

            {/* CONTENT AREA */}
            <div className="flex-1 overflow-hidden flex flex-col min-h-0">
              {dashboardRestrictedTab && (
                <div className="flex-1 overflow-y-auto styled-scrollbar px-4 py-6 border-l-2 border-cyan-800/25 flex items-center justify-center">
                  <div className="max-w-md w-full border border-cyan-900/30 bg-cyan-950/10 px-5 py-6 text-center">
                    <div className="inline-flex items-center justify-center w-11 h-11 border border-cyan-700/40 bg-black/30 text-cyan-300 mb-3">
                      {activeTab === 'infonet' ? <Shield size={17} /> : <Lock size={17} />}
                    </div>
                    <div className="text-sm font-mono tracking-[0.24em] text-cyan-300 mb-2">
                      {dashboardRestrictedTitle}
                    </div>
                    <div className="text-sm font-mono text-[var(--text-secondary)] leading-[1.75]">
                      {dashboardRestrictedDetail}
                    </div>
                    <div className="mt-3 text-[13px] font-mono text-cyan-300/70 leading-[1.7]">
                      Use the terminal to enter Wormhole, join private gates, and work secure contact
                      flows until the dashboard client lands.
                    </div>
                  </div>
                </div>
              )}
              {/* ─── InfoNet Tab ─── */}
              {!dashboardRestrictedTab && activeTab === 'infonet' && (
                <>
                  {!privateInfonetReady ? (
                    <div className="flex-1 overflow-y-auto styled-scrollbar px-4 py-6 border-l-2 border-cyan-800/25 flex items-center justify-center">
                      <div className="max-w-sm w-full border border-cyan-900/30 bg-cyan-950/10 px-4 py-5 text-center">
                        <div className="inline-flex items-center justify-center w-10 h-10 border border-cyan-700/40 bg-black/30 text-cyan-300 mb-3">
                          <Shield size={16} />
                        </div>
                        <div className="text-sm font-mono tracking-[0.24em] text-cyan-300 mb-2">
                          PRIVATE INFONET LOCKED
                        </div>
                        <div className="text-sm font-mono text-[var(--text-secondary)] leading-[1.7]">
                          Experimental private gate chat lives behind Wormhole now.
                        </div>
                        <div className="mt-2 text-[13px] font-mono text-cyan-300/70">
                          Use the unlock prompt below for the full private-lane brief. Dead Drop
                          remains the strongest current message lane.
                        </div>
                      </div>
                    </div>
                  ) : (
                    <>
                  <div className="flex items-center gap-1.5 px-3 py-1.5 border-b border-[var(--border-primary)]/30 shrink-0">
                    <select
                      value={selectedGate}
                      onChange={(e) => setSelectedGate(e.target.value)}
                      className="flex-1 bg-[var(--bg-secondary)]/50 border border-[var(--border-primary)] text-sm font-mono text-cyan-300 px-2 py-1 outline-none focus:border-cyan-700/50"
                    >
                      <option value="">All Gates</option>
                      {gates.map((g) => (
                        <option key={g.gate_id} value={g.gate_id}>
                          {g.display_name || g.gate_id}{g.fixed ? ' [FIXED]' : ''} ({g.message_count})
                        </option>
                      ))}
                    </select>
                    <button
                      onClick={() => {
                        setShowCreateGate(false);
                        setGateError('Launch catalog is fixed for this testnet build');
                      }}
                      disabled
                      className="p-1 text-[var(--text-muted)]/50 disabled:opacity-40"
                      title="Fixed launch gate catalog"
                    >
                      <Plus size={12} />
                    </button>
                  </div>

                  {privateInfonetReady && !wormholeRnsReady && (
                    <div className="px-3 py-2 border-b border-amber-900/20 bg-amber-950/10 shrink-0">
                      <div className="text-[12px] font-mono tracking-[0.28em] text-amber-300/90">
                        EXPERIMENTAL ENCRYPTION
                      </div>
                      <div className="mt-1 text-sm font-mono text-amber-100/80 leading-[1.65]">
                        Gate chat is live on the private Wormhole lane while Reticulum finishes
                        warming. Strongest private posture and direct private DM readiness stay
                        separate.
                      </div>
                      <div className="mt-1 text-[13px] font-mono text-amber-300/70 leading-[1.6]">
                        Gate messages are still synced on the shared private-lane Infonet surface
                        in this build. Use Dead Drop for the strongest content privacy.
                      </div>
                      <div className="mt-1 text-[13px] font-mono text-amber-300/75">
                        RNS peers {wormholeRnsPeers.active}/{wormholeRnsPeers.configured}
                        {wormholeRnsDirectReady
                          ? ' • direct private DM path ready'
                          : ' • direct peer paths still warming'}
                      </div>
                    </div>
                  )}

                  {selectedGate && wormholeEnabled && wormholeReadyState && (
                    <div className="flex items-center gap-1.5 px-3 py-1.5 border-b border-[var(--border-primary)]/20 shrink-0 bg-cyan-950/10">
                      <div className="text-[12px] font-mono tracking-[0.28em] text-cyan-400/80 whitespace-nowrap">
                        GATE FACE
                      </div>
                      <select
                        value={selectedGateActivePersonaId || '__anon__'}
                        onChange={(e) => void handleSelectGatePersona(e.target.value)}
                        disabled={gatePersonaBusy || anonymousPublicBlocked}
                        className="flex-1 bg-[var(--bg-secondary)]/40 border border-[var(--border-primary)] text-[13px] font-mono text-cyan-300 px-2 py-1 outline-none focus:border-cyan-700/50 disabled:opacity-60"
                      >
                        <option value="__anon__">ANON SESSION</option>
                        {selectedGatePersonaList.map((persona) => (
                          <option key={persona.persona_id || persona.node_id} value={persona.persona_id || ''}>
                            {persona.label || persona.persona_id || persona.node_id.slice(0, 10)}
                          </option>
                        ))}
                      </select>
                      <button
                        onClick={() => openGatePersonaPrompt()}
                        disabled={gatePersonaBusy || anonymousPublicBlocked}
                        className="px-2 py-1 text-[12px] font-mono tracking-[0.2em] border border-cyan-700/40 text-cyan-300 hover:bg-cyan-950/40 disabled:opacity-60 transition-colors"
                        title="Create a gate-local face"
                      >
                        NEW FACE
                      </button>
                      <button
                        onClick={() => void handleRetireGatePersona()}
                        disabled={
                          gatePersonaBusy ||
                          anonymousPublicBlocked ||
                          !selectedGateActivePersonaId
                        }
                        className="px-2 py-1 text-[12px] font-mono tracking-[0.2em] border border-red-700/40 text-red-300 hover:bg-red-950/40 disabled:opacity-60 transition-colors"
                        title="Retire the active gate persona"
                      >
                        RETIRE
                      </button>
                    </div>
                  )}

                  {selectedGate && wormholeEnabled && wormholeReadyState && (
                    <div className="px-3 py-1.5 border-b border-[var(--border-primary)]/20 shrink-0 bg-[var(--bg-secondary)]/20 text-[12px] font-mono text-[var(--text-muted)] leading-relaxed">
                      <div className="text-cyan-300/80 mb-1">
                        {selectedGateActivePersona
                          ? `Active face: ${selectedGateActivePersona.label || selectedGateActivePersona.persona_id || selectedGateActivePersona.node_id}`
                          : 'Active face: anonymous session'}
                        {selectedGatePersonaList.length > 0
                          ? ` | saved personas: ${selectedGatePersonaList.length}`
                          : ' | no saved personas yet'}
                      </div>
                      Anonymous gate entry rotates to a fresh gate-scoped session identity and
                      does not emit a public join/leave breadcrumb.
                    </div>
                  )}

                  {selectedGate && wormholeEnabled && wormholeReadyState && selectedGateKeyStatus && (
                    <div className="px-3 py-2 border-b border-cyan-900/20 bg-cyan-950/5 shrink-0">
                      <div className="flex items-center gap-2 text-[12px] font-mono tracking-[0.24em] text-cyan-300/90">
                        <span>GATE KEY</span>
                        <span className="text-cyan-500/60">/</span>
                        <span>EPOCH {selectedGateKeyStatus.current_epoch || 0}</span>
                        {selectedGateKeyStatus.rekey_recommended && (
                          <span className="border border-amber-700/60 px-1 text-amber-300">
                            REKEY ADVISED
                          </span>
                        )}
                        <button
                          onClick={() => void handleRotateGateKey()}
                          disabled={gateKeyBusy}
                          className="ml-auto px-2 py-1 text-[12px] font-mono tracking-[0.2em] border border-cyan-700/40 text-cyan-300 hover:bg-cyan-950/40 disabled:opacity-60 transition-colors"
                          title="Rotate the current gate content key"
                        >
                          {gateKeyBusy ? 'ROTATING' : 'ROTATE KEY'}
                        </button>
                      </div>
                      <div className="mt-1 text-[13px] font-mono text-cyan-100/80 leading-[1.65]">
                        {selectedGateKeyStatus.has_local_access
                          ? `Access live via ${selectedGateKeyStatus.identity_scope || 'member'} identity ${String(selectedGateKeyStatus.sender_ref || selectedGateKeyStatus.identity_node_id || '').slice(0, 16)}`
                          : selectedGateKeyStatus.identity_scope === 'anonymous'
                          ? 'Anonymous gate session is active, but this install has not synced gate access yet. Refresh or reopen the gate if it does not clear.'
                          : 'No local gate key access yet. Enter the gate through Wormhole to unwrap the current epoch.'}
                      </div>
                      <div className="mt-1 text-[12px] font-mono text-cyan-300/65 leading-[1.65]">
                        {selectedGateKeyStatus.key_commitment
                          ? `KEY ${selectedGateKeyStatus.key_commitment.slice(0, 12)}`
                          : 'KEY PENDING'}
                        {selectedGateKeyStatus.previous_epoch
                          ? ` • previous epoch ${selectedGateKeyStatus.previous_epoch}`
                          : ''}
                        {selectedGateKeyStatus.last_rotated_at
                          ? ` • rotated ${timeAgo(selectedGateKeyStatus.last_rotated_at)}`
                          : ''}
                      </div>
                      {nativeAuditSummary && (
                        <div className="mt-2 border border-cyan-900/30 bg-cyan-950/20 px-2 py-1.5 text-[12px] font-mono text-cyan-200/75 leading-[1.7]">
                          <div className="flex items-center gap-2 text-cyan-300/85 tracking-[0.18em]">
                            <span>NATIVE AUDIT</span>
                            <span className="text-cyan-500/60">/</span>
                            <span>
                              {nativeAuditReport?.totalRecorded || nativeAuditReport?.totalEvents || 0} RECORDED
                            </span>
                            {nativeAuditReport &&
                              nativeAuditReport.totalRecorded > nativeAuditReport.totalEvents && (
                                <span className="text-cyan-400/60">
                                  ({nativeAuditReport.totalEvents} shown)
                                </span>
                              )}
                            <button
                              onClick={() => refreshNativeAuditReport(5)}
                              className="ml-auto px-1.5 py-0.5 border border-cyan-800/40 text-cyan-300/80 hover:bg-cyan-950/40 transition-colors"
                              title="Refresh native session-profile audit report"
                            >
                              REFRESH
                            </button>
                          </div>
                          <div className="mt-1">
                            {nativeAuditSummary.recent
                              ? `Last: ${nativeAuditSummary.recent.command}${nativeAuditSummary.recent.targetRef ? ` [${nativeAuditSummary.recent.targetRef}]` : ''} -> ${nativeAuditSummary.recent.outcome}`
                              : 'No native gate audit events yet.'}
                          </div>
                          <div className="text-cyan-300/60">
                            Profile mismatches: {nativeAuditSummary.mismatchCount} • denied: {nativeAuditSummary.deniedCount}
                          </div>
                          {nativeAuditReport?.lastProfileMismatch && (
                            <div className="text-amber-300/70">
                              {`Last mismatch: ${nativeAuditReport.lastProfileMismatch.command}${nativeAuditReport.lastProfileMismatch.targetRef ? ` [${nativeAuditReport.lastProfileMismatch.targetRef}]` : ''} (${nativeAuditReport.lastProfileMismatch.sessionProfile || 'unscoped'} -> ${nativeAuditReport.lastProfileMismatch.expectedCapability})`}
                            </div>
                          )}
                        </div>
                      )}
                      {selectedGateKeyStatus.rekey_recommended_reason && (
                        <div className="mt-1 text-[12px] font-mono text-amber-300/75 leading-[1.6]">
                          Rekey recommendation: {selectedGateKeyStatus.rekey_recommended_reason.replace(/_/g, ' ')}
                        </div>
                      )}
                      {selectedGateKeyStatus.identity_scope === 'anonymous' &&
                        !selectedGateKeyStatus.has_local_access && (
                        <div className="mt-2 flex items-center gap-2">
                          <button
                            onClick={() => void handleUnlockEncryptedGate()}
                            disabled={gatePersonaBusy}
                            className="px-2 py-1 text-[12px] font-mono tracking-[0.2em] border border-cyan-700/40 text-cyan-300 hover:bg-cyan-950/40 disabled:opacity-60 transition-colors"
                          >
                            {gatePersonaBusy
                              ? 'UNLOCKING'
                              : selectedGatePersonaList.length > 0
                                ? 'USE SAVED FACE'
                                : 'CREATE GATE FACE'}
                          </button>
                          <span className="text-[12px] font-mono text-cyan-300/55">
                            {selectedGatePersonaList.length > 0
                              ? 'Switch to a saved face if this install still cannot unlock the room anonymously.'
                              : 'Create a gate-local face only if anonymous unlock still fails on this install.'}
                          </span>
                        </div>
                      )}
                    </div>
                  )}

                  {selectedGateMeta && (
                    <div className="px-3 py-2 border-b border-cyan-900/20 bg-cyan-950/10 shrink-0">
                      <div className="flex items-center gap-2 text-[12px] font-mono tracking-[0.24em] text-cyan-300/90">
                        <span>{selectedGateMeta.fixed ? 'FIXED GATE' : 'PRIVATE GATE'}</span>
                        <span className="text-cyan-500/60">/</span>
                        <span>{selectedGateMeta.display_name || selectedGateMeta.gate_id}</span>
                      </div>
                      {selectedGateMeta.description && (
                        <div className="mt-1 text-sm font-mono text-cyan-100/80 leading-[1.65]">
                          {selectedGateMeta.description}
                        </div>
                      )}
                      <div className="mt-1 text-[12px] font-mono text-cyan-300/65">
                        {selectedGateMeta.rules?.min_overall_rep
                          ? `ENTRY FLOOR ${selectedGateMeta.rules.min_overall_rep} REP`
                          : 'ENTRY FLOOR OPEN'}
                        {' • '}
                        {selectedGateMeta.message_count} MSGS
                      </div>
                    </div>
                  )}

                  {/* Create gate form */}
                  <AnimatePresence>
                    {showCreateGate && (
                      <motion.div
                        initial={{ height: 0 }}
                        animate={{ height: 'auto' }}
                        exit={{ height: 0 }}
                        className="overflow-hidden border-b border-[var(--border-primary)]/30 shrink-0"
                      >
                        <div className="px-3 py-2 space-y-1.5">
                          <div className="text-[12px] font-mono text-[var(--text-muted)] leading-relaxed mb-1">
                            Gates are rep-gated communities. Only nodes meeting the minimum
                            reputation can post.
                          </div>
                          <input
                            value={newGateId}
                            onChange={(e) => {
                              setNewGateId(e.target.value);
                              setGateError('');
                            }}
                            placeholder="gate-id (alphanumeric + hyphens, max 32)"
                            className="w-full bg-[var(--bg-secondary)]/50 border border-[var(--border-primary)] text-sm font-mono text-cyan-300 px-2 py-1 outline-none placeholder:text-[var(--text-muted)]"
                          />
                          <input
                            value={newGateName}
                            onChange={(e) => setNewGateName(e.target.value)}
                            placeholder="Display Name (optional)"
                            className="w-full bg-[var(--bg-secondary)]/50 border border-[var(--border-primary)] text-sm font-mono text-cyan-300 px-2 py-1 outline-none placeholder:text-[var(--text-muted)]"
                          />
                          <div className="flex items-center gap-2">
                            <label
                              className="text-[13px] font-mono text-[var(--text-muted)]"
                              title="Minimum overall reputation score needed to post in this gate. 0 = open to all."
                            >
                              MIN REP:
                            </label>
                            <input
                              type="number"
                              min={0}
                              value={newGateMinRep}
                              onChange={(e) => setNewGateMinRep(parseInt(e.target.value) || 0)}
                              className="w-16 bg-[var(--bg-secondary)]/50 border border-[var(--border-primary)] text-sm font-mono text-cyan-300 px-2 py-1 outline-none"
                            />
                            <span className="text-[12px] text-[var(--text-muted)] font-mono">
                              {newGateMinRep === 0 ? 'open' : 'gated'}
                            </span>
                            <button
                              onClick={handleCreateGate}
                              disabled={!newGateId.trim() || !hasId}
                              className="ml-auto text-[13px] font-mono px-2 py-1 bg-cyan-900/20 text-cyan-400 hover:bg-cyan-800/30 disabled:opacity-30 transition-colors"
                            >
                              CREATE
                            </button>
                          </div>
                          {gateError && (
                            <div className="text-[13px] font-mono text-red-400 mt-0.5">
                              {gateError}
                            </div>
                          )}
                        </div>
                      </motion.div>
                    )}
                  </AnimatePresence>

                  {/* Messages — terminal log style */}
                  <div className="flex-1 overflow-y-auto styled-scrollbar px-3 py-1.5 border-l-2 border-cyan-800/25">
                    {filteredInfoMessages.length === 0 && (
                      <div className="py-4 space-y-3">
                        <div className="text-sm font-mono text-[var(--text-muted)] text-center leading-[1.65]">
                          {selectedGate ? 'No messages in this gate yet' : 'Select a gate or browse all'}
                        </div>
                        {selectedGateMeta && (
                          <div className="border border-cyan-900/30 bg-cyan-950/10 px-3 py-3 max-w-xl mx-auto">
                            <div className="text-[12px] font-mono tracking-[0.28em] text-cyan-300/85">
                              SYSTEM WELCOME
                            </div>
                            <div className="mt-2 text-sm font-mono text-cyan-100/80 leading-[1.7]">
                              {selectedGateMeta.welcome || selectedGateMeta.description || 'Private gate is live. Say something worth keeping.'}
                            </div>
                            <div className="mt-2 text-[13px] font-mono text-cyan-300/65 leading-[1.7]">
                              Start with a source, a thesis, a clean question, or a useful observation.
                            </div>
                          </div>
                        )}
                      </div>
                    )}
                    {filteredInfoMessages.map((m, i) => (
                      m.system_seed ? (
                        <div key={m.event_id} className="border border-cyan-900/30 bg-cyan-950/10 px-3 py-3 max-w-xl">
                          <div className="text-[12px] font-mono tracking-[0.28em] text-cyan-300/85">
                            {m.fixed_gate ? 'FIXED GATE NOTICE' : 'GATE NOTICE'}
                          </div>
                          <div className="mt-2 text-sm font-mono text-cyan-100/80 leading-[1.7]">
                            {m.message}
                          </div>
                        </div>
                      ) : (
                      <div key={m.event_id} className="group py-0.5 leading-[1.65]">
                        <div className="flex gap-1.5 text-sm font-mono">
                          <RepBadge rep={m.node_id ? (reps[m.node_id] ?? 0) : 0} />
                          {m.node_id ? (
                            <button
                              onClick={(e) =>
                                handleSenderClick(String(m.node_id), e, 'infonet', {
                                  publicKey: String(m.public_key || ''),
                                  publicKeyAlgo: String(m.public_key_algo || ''),
                                })
                              }
                              className="text-green-400 shrink-0 hover:text-green-300 hover:underline cursor-pointer"
                              title={m.public_key ? `PUBLIC KEY: ${m.public_key}` : String(m.node_id)}
                            >
                              {m.node_id.slice(0, 12)}
                            </button>
                          ) : null}
                          {isEncryptedGateEnvelope(m) && (
                            <span
                              className={`text-[12px] font-mono px-1 border ${
                                gateEnvelopeState(m) === 'decrypted'
                                  ? 'text-cyan-300 border-cyan-700/60'
                                  : 'text-amber-300 border-amber-700/60'
                              }`}
                            >
                              {gateEnvelopeState(m) === 'decrypted' ? 'DECRYPTED' : 'KEY LOCKED'}
                            </span>
                          )}
                          {infoVerification[m.event_id] && (
                            <span
                              className={`text-[12px] font-mono px-1 border ${
                                infoVerification[m.event_id] === 'verified'
                                  ? 'text-green-400 border-green-700/60'
                                  : infoVerification[m.event_id] === 'failed'
                                    ? 'text-red-400 border-red-700/60'
                                    : 'text-yellow-400 border-yellow-700/60'
                              }`}
                            >
                              {infoVerification[m.event_id] === 'verified'
                                ? 'VERIFIED'
                                : infoVerification[m.event_id] === 'failed'
                                  ? 'FAILED'
                                  : 'UNSIGNED'}
                            </span>
                          )}
                          <span
                            className={`${MSG_COLORS[i % MSG_COLORS.length]} break-words whitespace-pre-wrap flex-1 ${
                              isEncryptedGateEnvelope(m) && !String(m.decrypted_message || '').trim()
                                ? 'italic opacity-80'
                                : ''
                            }`}
                          >
                            {gateEnvelopeDisplayText(m)}
                          </span>
                          <span className="text-[var(--text-muted)] shrink-0 text-[13px]">
                            {timeAgo(m.timestamp)}
                          </span>
                        </div>
                        {isEncryptedGateEnvelope(m) && (
                          <div className="ml-6 mt-0.5 text-[12px] font-mono text-cyan-500/60 tracking-[0.14em]">
                            EPOCH {m.epoch ?? 0}
                            {m.sender_ref ? ` / ${m.sender_ref}` : ''}
                          </div>
                        )}
                        {hasId && m.node_id && m.node_id !== identity!.nodeId && (
                          <div className="flex items-center gap-0.5 ml-6">
                            <button
                              onClick={() => handleReplyToGateMessage(m)}
                              className={`px-1.5 py-0.5 text-[12px] font-mono tracking-[0.14em] transition-colors ${
                                gateReplyContext?.eventId === m.event_id
                                  ? 'text-amber-200 border border-amber-500/30 bg-amber-500/12'
                                  : 'text-cyan-600/70 border border-cyan-700/20 hover:text-amber-200 hover:border-amber-500/30 hover:bg-amber-500/10'
                              }`}
                            >
                              REPLY
                            </button>
                            <button
                              onClick={() => handleVote(String(m.node_id), 1, String(m.gate || selectedGate || ''))}
                              className={`p-0.5 transition-colors ${
                                votedOn[voteScopeKey(String(m.node_id), String(m.gate || selectedGate || ''))] === 1
                                  ? 'text-cyan-400'
                                  : 'text-cyan-600/60 hover:text-cyan-400'
                              }`}
                            >
                              <ArrowUp size={9} />
                            </button>
                            <span
                              className={`text-[12px] font-mono min-w-[14px] text-center ${
                                (reps[m.node_id] ?? 0) > 0
                                  ? 'text-cyan-500'
                                  : (reps[m.node_id] ?? 0) < 0
                                    ? 'text-red-400'
                                    : 'text-cyan-600/60'
                              }`}
                            >
                              {reps[m.node_id] ?? 0}
                            </span>
                            <button
                              onClick={() => handleVote(String(m.node_id), -1, String(m.gate || selectedGate || ''))}
                              className={`p-0.5 transition-colors ${
                                votedOn[voteScopeKey(String(m.node_id), String(m.gate || selectedGate || ''))] === -1
                                  ? 'text-red-400'
                                  : 'text-cyan-600/60 hover:text-red-400'
                              }`}
                            >
                              <ArrowDown size={9} />
                            </button>
                          </div>
                        )}
                      </div>
                      )
                    ))}
                    <div ref={messagesEndRef} />
                  </div>
                    </>
                  )}
                </>
              )}

              {/* ─── Meshtastic Tab ─── */}
              {activeTab === 'meshtastic' && (
                <>
                  <div className="flex items-center gap-1.5 px-3 py-1.5 border-b border-[var(--border-primary)]/30 shrink-0">
                    <select
                      value={meshRegion}
                      onChange={(e) => setMeshRegion(e.target.value)}
                      title="Meshtastic MQTT root"
                      className="bg-[var(--bg-secondary)]/50 border border-[var(--border-primary)] text-[12px] font-mono text-cyan-300 px-2 py-1 outline-none focus:border-cyan-700/50"
                      style={{ width: '132px' }}
                    >
                      {meshRoots.map((r) => (
                        <option key={r} value={r}>
                          {r}
                        </option>
                      ))}
                    </select>
                    <select
                      value={meshChannel}
                      onChange={(e) => setMeshChannel(e.target.value)}
                      className="flex-1 bg-[var(--bg-secondary)]/50 border border-[var(--border-primary)] text-[12px] font-mono text-green-400 px-2 py-1 outline-none focus:border-cyan-700/50"
                    >
                      {meshChannels.map((ch) => (
                        <option key={ch} value={ch}>
                          {activeChannels.has(ch) ? `* ${ch}` : `  ${ch}`}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="flex items-center justify-between gap-2 px-3 py-1 border-b border-[var(--border-primary)]/20 shrink-0 bg-green-950/10">
                    <div className="flex items-center gap-1">
                      <button
                        onClick={() => setMeshView('channel')}
                        className={`px-2 py-0.5 text-[11px] font-mono tracking-wider border transition-colors ${
                          meshView === 'channel'
                            ? 'border-green-500/40 text-green-300 bg-green-950/30'
                            : 'border-[var(--border-primary)]/40 text-[var(--text-muted)] hover:text-green-300'
                        }`}
                      >
                        CHANNEL
                      </button>
                      <button
                        onClick={() => setMeshView('inbox')}
                        className={`px-2 py-0.5 text-[11px] font-mono tracking-wider border transition-colors ${
                          meshView === 'inbox'
                            ? 'border-amber-500/40 text-amber-300 bg-amber-950/20'
                            : 'border-[var(--border-primary)]/40 text-[var(--text-muted)] hover:text-amber-300'
                        }`}
                      >
                        INBOX
                      </button>
                    </div>
                    <div className="text-[10px] font-mono text-[var(--text-muted)] truncate">
                      {publicMeshAddress ? `ADDR ${publicMeshAddress.toUpperCase()}` : 'NO PUBLIC MESH ADDRESS'}
                    </div>
                  </div>
                  <div className="flex-1 overflow-y-auto styled-scrollbar px-3 py-1.5 border-l-2 border-cyan-800/25">
                    {meshView === 'channel' && filteredMeshMessages.length === 0 && (
                      <div className="text-[12px] font-mono text-[var(--text-muted)] text-center py-4 leading-[1.65]">
                        No messages from {meshRegion} / {meshChannel}
                      </div>
                    )}
                    {meshView === 'inbox' && (
                      <>
                        {!publicMeshAddress && (
                          <div className="text-[12px] font-mono text-[var(--text-muted)] text-center py-4 leading-[1.65]">
                            Create or load a public mesh identity to see direct Meshtastic traffic.
                          </div>
                        )}
                        {publicMeshAddress && meshInboxMessages.length === 0 && (
                          <div className="text-[12px] font-mono text-[var(--text-muted)] text-center py-4 leading-[1.65]">
                            No public direct messages addressed to {publicMeshAddress.toUpperCase()} yet.
                          </div>
                        )}
                        {meshInboxMessages.map((m, i) => (
                          <div key={`${m.timestamp}-${i}`} className="py-0.5 leading-[1.65]">
                            <div className="flex items-start gap-1.5 text-[12px] font-mono">
                              <button
                                onClick={(e) => handleSenderClick(m.from, e, 'meshtastic')}
                                className="text-amber-300 shrink-0 hover:text-amber-200 hover:underline cursor-pointer"
                              >
                                {displayPublicMeshSender(m.from)}
                              </button>
                              <div className="flex-1 min-w-0">
                                <div className="text-[10px] text-amber-200/70 mb-0.5">
                                  TO {publicMeshAddress.toUpperCase()}
                                </div>
                                <div className="break-words whitespace-pre-wrap text-amber-100/90">
                                  {m.text}
                                </div>
                              </div>
                              <span className="text-[var(--text-muted)] shrink-0 text-[11px]">
                                {timeAgo(
                                  typeof m.timestamp === 'number'
                                    ? m.timestamp
                                    : Date.parse(m.timestamp || ''),
                                )}
                              </span>
                            </div>
                          </div>
                        ))}
                      </>
                    )}
                    {meshView === 'channel' &&
                      filteredMeshMessages.map((m, i) => (
                        <div key={`${m.timestamp}-${i}`} className="py-0.5 leading-[1.65]">
                          <div className="flex gap-1.5 text-[12px] font-mono">
                            <button
                              onClick={(e) => handleSenderClick(m.from, e, 'meshtastic')}
                              className="text-green-400 shrink-0 hover:text-green-300 hover:underline cursor-pointer"
                            >
                              {displayPublicMeshSender(m.from)}
                            </button>
                            <span
                              className={`${MSG_COLORS[i % MSG_COLORS.length]} break-words whitespace-pre-wrap flex-1`}
                            >
                              {m.text}
                            </span>
                            <span className="text-[var(--text-muted)] shrink-0 text-[11px]">
                              {timeAgo(
                                typeof m.timestamp === 'number'
                                  ? m.timestamp
                                  : Date.parse(m.timestamp || ''),
                              )}
                            </span>
                          </div>
                        </div>
                      ))}
                    <div ref={messagesEndRef} />
                  </div>
                </>
              )}

              {/* ─── Dead Drop Tab ─── */}
              {!dashboardRestrictedTab && activeTab === 'dms' && (
                <>
                  {/* Sub-nav: Contacts | Inbox | Muted | (back to contacts from chat) */}
                  <div className="flex items-center gap-1 px-3 py-1.5 border-b border-[var(--border-primary)]/30 shrink-0">
                    {dmView === 'chat' ? (
                      <>
                        <button
                          onClick={() => {
                            setDmView('contacts');
                            setSelectedContact('');
                            setDmMessages([]);
                          }}
                          className="text-[13px] font-mono text-[var(--text-muted)] hover:text-cyan-400 transition-colors"
                        >
                          &lt; BACK
                        </button>
                        <span className="text-sm font-mono text-cyan-400 ml-2 truncate">
                          {selectedContact.slice(0, 16)}
                        </span>
                        {(() => {
                          const c = contacts[selectedContact];
                          if (!c) return null;
                          if (c.remotePrekeyMismatch) {
                            return (
                              <span className="ml-2 text-[12px] font-mono px-1.5 py-0.5 border border-orange-500/40 text-orange-300 bg-orange-950/20">
                                PREKEY CHANGED
                              </span>
                            );
                          }
                          if (c.verify_mismatch) {
                            return (
                              <span className="ml-2 text-[12px] font-mono px-1.5 py-0.5 border border-red-500/40 text-red-400 bg-red-950/20">
                                KEY MISMATCH
                              </span>
                            );
                          }
                          if (c.verified) {
                            return (
                              <span className="ml-2 text-[12px] font-mono px-1.5 py-0.5 border border-green-500/40 text-green-400 bg-green-950/20">
                                DUAL VERIFIED
                              </span>
                            );
                          }
                          if (c.verify_registry && !c.verify_inband) {
                            return (
                              <span className="ml-2 text-[12px] font-mono px-1.5 py-0.5 border border-yellow-500/30 text-yellow-300 bg-yellow-950/10">
                                REGISTRY ONLY
                              </span>
                            );
                          }
                          if (c.verify_inband && !c.verify_registry) {
                            return (
                              <span className="ml-2 text-[12px] font-mono px-1.5 py-0.5 border border-yellow-500/30 text-yellow-300 bg-yellow-950/10">
                                INBAND ONLY
                              </span>
                            );
                          }
                          if (isFirstContactTrustOnly(c)) {
                            return (
                              <span className="ml-2 text-[12px] font-mono px-1.5 py-0.5 border border-amber-500/30 text-amber-300 bg-amber-950/10">
                                TOFU ONLY
                              </span>
                            );
                          }
                          return null;
                        })()}
                        {(() => {
                          const c = contacts[selectedContact];
                          if (!c) return null;
                          if (c.witness_count && c.witness_count > 0) {
                            return (
                              <span className="ml-2 text-[12px] font-mono px-1.5 py-0.5 border border-cyan-500/30 text-cyan-300 bg-cyan-950/10">
                                WITNESSED {c.witness_count}
                              </span>
                            );
                          }
                          return null;
                        })()}
                        {(() => {
                          const c = contacts[selectedContact];
                          if (!c) return null;
                          if (c.vouch_count && c.vouch_count > 0) {
                            return (
                              <span className="ml-2 text-[12px] font-mono px-1.5 py-0.5 border border-purple-500/30 text-purple-300 bg-purple-950/10">
                                VOUCHES {c.vouch_count}
                              </span>
                            );
                          }
                          return null;
                        })()}
                        <button
                          onClick={() => setShowSas((prev) => !prev)}
                          className="ml-auto text-[12px] font-mono px-2 py-0.5 border border-cyan-800/40 text-cyan-400/90 hover:text-cyan-300 hover:border-cyan-600/60 transition-colors"
                        >
                          {showSas ? 'HIDE SAS' : dmTrustPrimaryAction}
                        </button>
                        <button
                          onClick={() => handleVouch(selectedContact)}
                          className="ml-2 text-[12px] font-mono px-2 py-0.5 border border-purple-800/40 text-purple-400/90 hover:text-purple-300 hover:border-purple-600/60 transition-colors"
                        >
                          VOUCH
                        </button>
                        <button
                          onClick={() => void handleRefreshSelectedContact()}
                          disabled={dmMaintenanceBusy}
                          className="ml-2 text-[12px] font-mono px-2 py-0.5 border border-amber-800/40 text-amber-300/90 hover:text-amber-200 hover:border-amber-600/60 transition-colors disabled:opacity-40"
                        >
                          REFRESH
                        </button>
                        <button
                          onClick={() => void handleResetSelectedContact()}
                          disabled={dmMaintenanceBusy}
                          className="ml-2 text-[12px] font-mono px-2 py-0.5 border border-red-800/40 text-red-300/90 hover:text-red-200 hover:border-red-600/60 transition-colors disabled:opacity-40"
                        >
                          RESET
                        </button>
                      </>
                    ) : (
                      <>
                        <button
                          onClick={() => setDmView('contacts')}
                          className={`text-[13px] font-mono px-2 py-0.5 transition-colors ${
                            dmView === 'contacts'
                              ? 'text-cyan-400 bg-cyan-950/30'
                              : 'text-[var(--text-muted)] hover:text-gray-400'
                          }`}
                        >
                          CONTACTS
                        </button>
                        <button
                          onClick={() => setDmView('inbox')}
                          className={`text-[13px] font-mono px-2 py-0.5 transition-colors flex items-center gap-1 ${
                            dmView === 'inbox'
                              ? 'text-cyan-400 bg-cyan-950/30'
                              : 'text-[var(--text-muted)] hover:text-gray-400'
                          }`}
                        >
                          INBOX
                          {accessRequests.length > 0 && (
                            <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-[blink_1s_step-end_infinite]" />
                          )}
                        </button>
                        <button
                          onClick={() => setDmView('muted')}
                          className={`text-[13px] font-mono px-2 py-0.5 transition-colors flex items-center gap-1 ${
                            dmView === 'muted'
                              ? 'text-cyan-400 bg-cyan-950/30'
                              : 'text-[var(--text-muted)] hover:text-gray-400'
                          }`}
                        >
                          <EyeOff size={8} />
                          MUTED
                          {mutedArray.length > 0 && (
                            <span className="text-[11px] text-[var(--text-muted)]">
                              ({mutedArray.length})
                            </span>
                          )}
                        </button>
                        <button
                          onClick={() => setShowAddContact(!showAddContact)}
                          disabled={secureDmBlocked}
                          className="ml-auto p-1 hover:bg-[var(--hover-accent)] text-[var(--text-muted)] hover:text-cyan-400 transition-colors"
                          title="Request access"
                        >
                          <UserPlus size={11} />
                        </button>
                      </>
                    )}
                  </div>
                  {dmView === 'chat' && showSas && sasPhrase && (
                    <div className="px-3 pb-1 text-[13px] font-mono text-cyan-400/80 border-b border-[var(--border-primary)]/20">
                      SAS: <span className="text-cyan-300">{sasPhrase}</span>
                      {selectedContactInfo && isFirstContactTrustOnly(selectedContactInfo) && (
                        <div className="mt-1 text-[12px] font-mono text-amber-300/90 leading-[1.65]">
                          First contact is still TOFU-only. Compare this phrase out of band before
                          treating the sender as verified.
                        </div>
                      )}
                    </div>
                  )}

                  {activeTab === 'dms' && !secureDmBlocked && (
                    <div className="px-3 py-1.5 border-b border-[var(--border-primary)]/20 shrink-0 flex items-center gap-2">
                      <span
                        className={`text-[12px] font-mono px-1.5 py-0.5 border ${dmTransportStatus.className}`}
                      >
                        {dmTransportStatus.label}
                      </span>
                      <span className="text-[12px] font-mono text-[var(--text-muted)]">
                        {dmTransportMode === 'reticulum'
                          ? 'Direct private delivery active.'
                          : dmTransportMode === 'hidden'
                            ? 'Hidden transport active.'
                            : dmTransportMode === 'relay'
                              ? 'Relay fallback active.'
                              : dmTransportMode === 'ready'
                                ? 'Private lane ready.'
                        : 'Lower-trust mode.'}
                      </span>
                    </div>
                  )}

                  {activeTab === 'dms' && unresolvedSenderSealCount > 0 && (
                    <div className="px-3 py-2 border-b border-red-900/30 bg-red-950/18 text-red-300 leading-[1.65] shrink-0">
                      <div className="text-[13px] font-mono tracking-[0.18em] mb-1">
                        UNRESOLVED SEALED SENDERS
                      </div>
                      <div className="text-sm font-mono">
                        {unresolvedSenderSealCount} sealed-sender message
                        {unresolvedSenderSealCount === 1 ? '' : 's'} could not be mapped to a
                        trusted contact or verified sender key. Keep Wormhole reachable and refresh
                        contact trust before relying on them.
                      </div>
                    </div>
                  )}

                  {activeTab === 'dms' && dmView === 'chat' && dmTrustHint && selectedContactInfo && (
                    <div
                      className={`px-3 py-2 border-b leading-[1.65] shrink-0 ${
                        dmTrustHint.severity === 'danger'
                          ? 'border-red-900/30 bg-red-950/20 text-red-300'
                          : 'border-amber-900/30 bg-amber-950/10 text-amber-200'
                      }`}
                    >
                      <div className="flex items-start gap-2">
                        <div className="flex-1 min-w-0">
                          <div className="text-[13px] font-mono tracking-[0.18em] mb-1">
                            {dmTrustHint.title}
                          </div>
                          <div className="text-sm font-mono">{dmTrustHint.detail}</div>
                          {selectedContactInfo.remotePrekeyMismatch && (
                            <div className="mt-2 text-[13px] font-mono text-red-200/85">
                              pinned {shortTrustFingerprint(selectedContactInfo.remotePrekeyFingerprint)} • observed{' '}
                              {shortTrustFingerprint(selectedContactInfo.remotePrekeyObservedFingerprint)}
                            </div>
                          )}
                          {!selectedContactInfo.remotePrekeyMismatch &&
                            isFirstContactTrustOnly(selectedContactInfo) &&
                            selectedContactInfo.remotePrekeyFingerprint && (
                            <div className="mt-2 text-[13px] font-mono text-amber-200/85">
                              first-sight pin {shortTrustFingerprint(selectedContactInfo.remotePrekeyFingerprint)} •
                              verify before sensitive use
                            </div>
                          )}
                        </div>
                        <div className="flex items-center gap-1.5 shrink-0">
                          <button
                            onClick={() => setShowSas(true)}
                            className="text-[12px] font-mono px-2 py-0.5 border border-cyan-800/40 text-cyan-300 hover:text-cyan-200 hover:border-cyan-600/60 transition-colors"
                          >
                            {dmTrustPrimaryAction}
                          </button>
                          {selectedContactInfo.remotePrekeyMismatch && (
                            <button
                              onClick={() => void handleTrustSelectedRemotePrekey()}
                              disabled={dmMaintenanceBusy}
                              className="text-[12px] font-mono px-2 py-0.5 border border-orange-700/40 text-orange-300 hover:text-orange-200 hover:border-orange-500/60 transition-colors disabled:opacity-40"
                            >
                              TRUST NEW KEY
                            </button>
                          )}
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Add contact / request access form */}
                  <AnimatePresence>
                    {showAddContact && dmView !== 'chat' && !secureDmBlocked && (
                      <motion.div
                        initial={{ height: 0 }}
                        animate={{ height: 'auto' }}
                        exit={{ height: 0 }}
                        className="overflow-hidden border-b border-[var(--border-primary)]/30 shrink-0"
                      >
                        <div className="px-3 py-2 space-y-1.5">
                          <div className="text-[13px] font-mono text-[var(--text-muted)] leading-[1.65]">
                            Enter an Agent ID to request Dead Drop access. They must accept before
                            you can exchange messages.
                          </div>
                          <div className="flex items-center gap-1.5">
                            <input
                              value={addContactId}
                              onChange={(e) => setAddContactId(e.target.value)}
                              placeholder="!sb_a3f2c891..."
                              className="flex-1 bg-[var(--bg-secondary)]/50 border border-[var(--border-primary)] text-sm font-mono text-cyan-300 px-2 py-1 outline-none placeholder:text-[var(--text-muted)]"
                              onKeyDown={(e) => {
                                if (e.key === 'Enter') {
                                  handleAddContact().catch(() =>
                                    handleRequestAccess(addContactId.trim()),
                                  );
                                }
                              }}
                            />
                            <button
                              onClick={() => {
                                handleAddContact().catch(() =>
                                  handleRequestAccess(addContactId.trim()),
                                );
                              }}
                              disabled={!addContactId.trim() || !hasId}
                              className="text-[13px] font-mono px-2 py-1 bg-cyan-900/20 text-cyan-400 hover:bg-cyan-800/30 disabled:opacity-30 transition-colors"
                            >
                              REQUEST
                            </button>
                          </div>
                          {pendingSent.includes(addContactId.trim()) && (
                            <div className="text-[13px] font-mono text-yellow-500/70">
                              Request already sent
                            </div>
                          )}
                        </div>
                      </motion.div>
                    )}
                  </AnimatePresence>

                  {/* Content area */}
                  <div className="flex-1 overflow-y-auto styled-scrollbar px-3 py-1.5 space-y-0.5 border-l-2 border-cyan-800/25">
                    {secureDmBlocked && (
                      <div className="flex h-full min-h-[220px] items-center justify-center py-6">
                        <div className="max-w-sm w-full border border-cyan-900/30 bg-cyan-950/10 px-4 py-5 text-center">
                          <div className="inline-flex items-center justify-center w-10 h-10 border border-cyan-700/40 bg-black/30 text-cyan-300 mb-3">
                            <Lock size={16} />
                          </div>
                          <div className="text-sm font-mono tracking-[0.24em] text-cyan-300 mb-2">
                            DEAD DROP LOCKED
                          </div>
                          <div className="text-sm font-mono text-[var(--text-secondary)] leading-[1.7]">
                            Need Wormhole activated.
                          </div>
                          <div className="mt-2 text-[13px] font-mono text-cyan-300/70">
                            Contacts, inbox, and private messages unlock once the private lane is up.
                          </div>
                        </div>
                      </div>
                    )}

                    {/* CONTACTS VIEW */}
                    {!secureDmBlocked && dmView === 'contacts' && (
                      <>
                        {contactList.length === 0 && (
                          <div className="text-sm font-mono text-[var(--text-muted)] text-center py-4 leading-[1.65]">
                            No contacts yet. Use <span className="text-cyan-500/70">+</span> to
                            request access.
                          </div>
                        )}
                        {contactList.map(([id, c]) => (
                          <div
                            key={id}
                            className="flex items-center gap-2 py-1.5 border-b border-[var(--border-primary)]/30 last:border-0 cursor-pointer hover:bg-[var(--bg-secondary)]/50 px-1 -mx-1 transition-colors"
                            onClick={() => openChat(id)}
                          >
                            <Lock size={10} className="text-[var(--text-muted)] shrink-0" />
                            <span className="text-sm font-mono text-cyan-300 truncate">
                              {c.alias || id.slice(0, 16)}
                            </span>
                            {c.remotePrekeyMismatch && (
                              <span className="text-[11px] font-mono px-1.5 py-0.5 border border-orange-500/40 text-orange-300 bg-orange-950/20">
                                REVERIFY
                              </span>
                            )}
                            {!c.remotePrekeyMismatch && c.verify_mismatch && (
                              <span className="text-[11px] font-mono px-1.5 py-0.5 border border-red-500/40 text-red-300 bg-red-950/20">
                                MISMATCH
                              </span>
                            )}
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                handleBlockDM(id);
                              }}
                              className="ml-auto p-0.5 text-[var(--text-muted)] hover:text-red-400 hover:bg-red-900/20 transition-colors"
                              title="Block"
                            >
                              <Ban size={10} />
                            </button>
                          </div>
                        ))}
                        {pendingSent.length > 0 && (
                          <>
                            <div className="text-[13px] font-mono text-[var(--text-muted)] mt-2 mb-1">
                              PENDING SENT
                            </div>
                            {pendingSent.map((id) => (
                              <div
                                key={id}
                                className="flex items-center gap-2 py-1 text-sm font-mono text-[var(--text-muted)]"
                              >
                                <span className="w-1.5 h-1.5 rounded-full bg-yellow-600/50" />
                                <span className="truncate">{id.slice(0, 16)}</span>
                                <span className="ml-auto text-[12px] text-[var(--text-muted)]">
                                  awaiting
                                </span>
                              </div>
                            ))}
                          </>
                        )}
                      </>
                    )}

                    {/* INBOX VIEW — access requests */}
                    {!secureDmBlocked && dmView === 'inbox' && (
                      <>
                        {accessRequests.length === 0 && (
                          <div className="text-sm font-mono text-[var(--text-muted)] text-center py-4 leading-[1.65]">
                            No incoming requests
                          </div>
                        )}
                        {accessRequests.map((req) => {
                          const requestActionsAllowed = shouldAllowRequestActions(req);
                          const recoveryState = req.sender_recovery_state;
                          return (
                            <div
                              key={req.sender_id}
                              className="py-2 border-b border-[var(--border-primary)]/30 last:border-0"
                            >
                              <div className="flex items-center gap-1.5">
                                <UserPlus size={10} className="text-cyan-500 shrink-0" />
                                <span className="text-sm font-mono text-cyan-300 truncate">
                                  {req.sender_id.slice(0, 16)}
                                </span>
                                {recoveryState === 'verified' && (
                                  <span className="text-[12px] font-mono px-1.5 py-0.5 border border-green-500/30 text-green-400 bg-green-950/20">
                                    VERIFIED
                                  </span>
                                )}
                                {recoveryState === 'pending' && (
                                  <span className="text-[12px] font-mono px-1.5 py-0.5 border border-yellow-500/30 text-yellow-300 bg-yellow-950/20">
                                    RECOVERY PENDING
                                  </span>
                                )}
                                {recoveryState === 'failed' && (
                                  <span className="text-[12px] font-mono px-1.5 py-0.5 border border-red-500/30 text-red-300 bg-red-950/20">
                                    RECOVERY FAILED
                                  </span>
                                )}
                                <span className="text-[12px] font-mono text-[var(--text-muted)] ml-auto shrink-0">
                                  {timeAgo(req.timestamp)}
                                </span>
                              </div>
                              <div className="text-[13px] font-mono text-[var(--text-muted)] mt-0.5 leading-[1.65]">
                                Requesting Dead Drop access
                              </div>
                              {req.geo_hint && (
                                <div className="text-[12px] font-mono text-[var(--text-muted)] mt-0.5">
                                  Geo hint (not proof): {req.geo_hint}
                                </div>
                              )}
                              {!requestActionsAllowed && (
                                <div className="text-[12px] font-mono text-yellow-300 mt-0.5 leading-[1.65]">
                                  Sender authority is not verified yet. Actions stay disabled until
                                  local recovery succeeds.
                                </div>
                              )}
                              <div className="flex items-center gap-1.5 mt-1.5">
                                <button
                                  onClick={() => handleAcceptRequest(req.sender_id)}
                                  disabled={!requestActionsAllowed}
                                  className={`flex items-center gap-1 text-[13px] font-mono px-2 py-0.5 transition-colors ${
                                    requestActionsAllowed
                                      ? 'bg-cyan-900/20 text-cyan-400 hover:bg-cyan-800/30'
                                      : 'bg-cyan-950/10 text-cyan-700 cursor-not-allowed opacity-50'
                                  }`}
                                >
                                  <Check size={9} /> ACCEPT
                                </button>
                                <button
                                  onClick={() => handleDenyRequest(req.sender_id)}
                                  disabled={!requestActionsAllowed}
                                  className={`flex items-center gap-1 text-[13px] font-mono px-2 py-0.5 transition-colors ${
                                    requestActionsAllowed
                                      ? 'bg-gray-900/30 text-gray-400 hover:bg-gray-800/40'
                                      : 'bg-gray-950/20 text-gray-600 cursor-not-allowed opacity-50'
                                  }`}
                                >
                                  <X size={9} /> DENY
                                </button>
                                <button
                                  onClick={() => handleBlockDM(req.sender_id)}
                                  disabled={!requestActionsAllowed}
                                  className={`flex items-center gap-1 text-[13px] font-mono px-2 py-0.5 ml-auto transition-colors ${
                                    requestActionsAllowed
                                      ? 'text-[var(--text-muted)] hover:text-red-400 hover:bg-red-900/20'
                                      : 'text-[var(--text-muted)] opacity-50 cursor-not-allowed'
                                  }`}
                                >
                                  <Ban size={9} /> BLOCK
                                </button>
                              </div>
                            </div>
                          );
                        })}
                      </>
                    )}

                    {/* MUTED LIST VIEW */}
                    {!secureDmBlocked && dmView === 'muted' && (
                      <>
                        {mutedArray.length === 0 && (
                          <div className="text-sm font-mono text-[var(--text-muted)] text-center py-4 leading-[1.65]">
                            No muted users
                          </div>
                        )}
                        {mutedArray.map((uid) => (
                          <div
                            key={uid}
                            className="flex items-center gap-2 py-1.5 border-b border-[var(--border-primary)]/30 last:border-0 px-1 -mx-1"
                          >
                            <EyeOff size={10} className="text-[var(--text-muted)] shrink-0" />
                            <span className="text-sm font-mono text-[var(--text-secondary)] truncate flex-1">
                              {uid.slice(0, 20)}
                            </span>
                            <button
                              onClick={() => handleUnmute(uid)}
                              className="flex items-center gap-1 text-[12px] font-mono px-2 py-0.5 bg-cyan-900/20 text-cyan-500 hover:bg-cyan-800/30 transition-colors"
                            >
                              <Eye size={8} /> UNMUTE
                            </button>
                          </div>
                        ))}
                      </>
                    )}

                    {/* CHAT VIEW */}
                    {!secureDmBlocked && dmView === 'chat' && (
                      <>
                        {dmMessages.length === 0 && (
                          <div className="text-sm font-mono text-[var(--text-muted)] text-center py-4 leading-[1.65]">
                            <Lock size={11} className="inline mr-1 mb-0.5" />
                            E2E encrypted dead drop — no messages yet
                          </div>
                        )}
                        {dmMessages.map((m) => (
                          <div key={m.msg_id} className="py-0.5 leading-[1.65]">
                            <div className="flex gap-1.5 text-sm font-mono">
                              <span
                                className={`shrink-0 ${
                                  m.sender_id === identity?.nodeId
                                    ? 'text-cyan-500'
                                    : 'text-cyan-400'
                                }`}
                              >
                                {m.sender_id === identity?.nodeId
                                  ? 'you'
                                  : m.sender_id.slice(0, 12)}
                              </span>
                              {m.sender_id !== identity?.nodeId && m.seal_verified === true && (
                                <span className="text-[12px] font-mono px-1.5 py-0.5 border border-green-500/30 text-green-400 bg-green-950/20">
                                  VERIFIED
                                </span>
                              )}
                              {m.sender_id !== identity?.nodeId && m.seal_resolution_failed && (
                                <span className="text-[12px] font-mono px-1.5 py-0.5 border border-red-500/30 text-red-300 bg-red-950/20">
                                  SEAL UNRESOLVED
                                </span>
                              )}
                              {m.sender_id !== identity?.nodeId &&
                                !m.seal_resolution_failed &&
                                m.seal_verified === false && (
                                <span className="text-[12px] font-mono px-1.5 py-0.5 border border-red-500/30 text-red-400 bg-red-950/20">
                                  UNVERIFIED
                                </span>
                              )}
                              {m.transport && (
                                <span
                                  className={`text-[12px] font-mono px-1.5 py-0.5 border ${
                                    m.transport === 'reticulum'
                                      ? 'border-green-500/30 text-green-400 bg-green-950/20'
                                      : 'border-yellow-500/30 text-yellow-400 bg-yellow-950/20'
                                  }`}
                                >
                                  {m.transport === 'reticulum' ? 'DIRECT' : 'RELAY'}
                                </span>
                              )}
                              <span className="text-[var(--text-secondary)] break-words whitespace-pre-wrap flex-1">
                                {m.plaintext || '[encrypted]'}
                              </span>
                              <span className="text-[var(--text-muted)] shrink-0 text-[13px]">
                                {timeAgo(m.timestamp)}
                              </span>
                            </div>
                          </div>
                        ))}
                      </>
                    )}
                    <div ref={messagesEndRef} />
                  </div>
                </>
              )}
            </div>

            {/* INPUT BAR */}
            {dashboardRestrictedTab ? (
              <div className="mx-2 mb-2 mt-1 border border-cyan-800/40 bg-black/30 shrink-0 relative">
                <span className="absolute -top-[7px] left-3 bg-[var(--bg-primary)] px-1 text-[11px] font-mono text-cyan-700/60 tracking-[0.15em] select-none">
                  ACCESS
                </span>
                <div className="px-3 py-3 flex flex-col gap-2">
                  <div className="text-[12px] font-mono tracking-widest text-[var(--text-muted)] uppercase">
                    {activeTab === 'infonet'
                      ? '→ PRIVATE INFONET / TERMINAL ONLY'
                      : '→ DEAD DROP / TERMINAL ONLY'}
                  </div>
                  <div className="text-[13px] font-mono text-[var(--text-secondary)] leading-[1.65]">
                    {activeTab === 'infonet'
                      ? 'Private gate posting and reading are restricted to the terminal for now. Dashboard support is coming soon.'
                      : 'Secure messages are restricted to the terminal for now. Dashboard inbox, requests, and compose are coming soon.'}
                  </div>
                  <button
                    onClick={openTerminal}
                    className="mt-1 w-full flex items-center justify-between gap-2 px-3 py-2 border border-cyan-700/40 bg-cyan-950/15 text-cyan-300 hover:bg-cyan-950/25 hover:border-cyan-500/50 transition-colors"
                  >
                    <span className="inline-flex items-center gap-2 text-sm font-mono tracking-[0.2em]">
                      <Terminal size={11} />
                      OPEN TERMINAL
                    </span>
                    <span className="text-[12px] font-mono text-cyan-300/70">
                      COMING TO DASHBOARD SOON
                    </span>
                  </button>
                </div>
              </div>
            ) : (
            <div className="mx-2 mb-2 mt-1 border border-cyan-800/40 bg-black/30 shrink-0 relative">
              <span className="absolute -top-[7px] left-3 bg-[var(--bg-primary)] px-1 text-[11px] font-mono text-cyan-700/60 tracking-[0.15em] select-none">INPUT</span>
              {/* Destination indicator / error */}
              <div className="flex items-center gap-1 px-3 pt-2.5 pb-0">
                {sendError ? (
                  <>
                    <span className="text-[11px] font-mono tracking-widest text-red-400/80 uppercase animate-pulse">
                      ✕ {sendError}
                    </span>
                    {activeTab === 'meshtastic' && (
                      <button
                        onClick={() =>
                          openIdentityWizard({
                            type: 'err',
                            text: 'Public mesh send needs a working public identity. Create or reset it here.',
                          })
                        }
                        className="ml-auto px-1.5 py-0.5 text-[11px] font-mono tracking-[0.16em] border border-red-700/40 text-red-300 hover:bg-red-950/20 transition-colors"
                      >
                        FIX
                      </button>
                    )}
                  </>
                ) : (
                  <span className="text-[11px] font-mono tracking-widest text-[var(--text-muted)] uppercase">
                    {activeTab === 'infonet'
                      ? privateInfonetReady
                        ? `→ INFONET${selectedGate ? ` / ${selectedGate}` : ''}${privateInfonetTransportReady ? '' : ' / EXPERIMENTAL ENCRYPTION'}`
                        : '→ PRIVATE LANE LOCKED'
                      : activeTab === 'meshtastic'
                        ? hasPublicLaneIdentity
                          ? meshDirectTarget
                            ? `→ MESH / TO ${meshDirectTarget.toUpperCase()}`
                            : `→ MESH / ${meshRegion} / ${meshChannel}`
                          : '→ MESH LOCKED'
                        : activeTab === 'dms' && secureDmBlocked
                          ? '→ DEAD DROP LOCKED'
                        : dmView === 'chat' && selectedContact
                          ? `→ DEAD DROP / ${selectedContact.slice(0, 14)}`
                          : '→ SELECT TARGET'}
                  </span>
                )}
              </div>
              {activeTab === 'meshtastic' && !hasPublicLaneIdentity && !sendError && (
                <div
                  className={`px-3 pt-1 text-[12px] font-mono leading-[1.5] ${
                    meshQuickStatus?.type === 'err'
                      ? 'text-red-300/80'
                      : meshQuickStatus?.type === 'ok'
                        ? 'text-green-300/80'
                        : 'text-green-300/70'
                  }`}
                >
                  {meshQuickStatus?.text ||
                    (publicMeshBlockedByWormhole
                      ? 'Wormhole is active. Turn it off here and we will mint a separate public mesh key for you.'
                      : 'Public mesh posting needs a mesh key. One tap gets you a fresh address.')}
                </div>
              )}
              <div className="flex items-center gap-2 px-3 pb-2 pt-1">
                {activeTab === 'infonet' && !privateInfonetReady ? (
                  <button
                    onClick={() => setInfonetUnlockOpen(true)}
                    className="w-full flex items-center justify-between gap-2 px-3 py-2 border border-cyan-700/40 bg-cyan-950/15 text-cyan-300 hover:bg-cyan-950/25 hover:border-cyan-500/50 transition-colors"
                  >
                    <span className="inline-flex items-center gap-2 text-sm font-mono tracking-[0.2em]">
                      <Shield size={11} />
                      UNLOCK INFONET
                    </span>
                    <span className="text-[12px] font-mono text-cyan-300/70">
                      OPEN PRIVATE LANE BRIEF
                    </span>
                  </button>
                ) : activeTab === 'dms' && secureDmBlocked ? (
                  <button
                    onClick={() => setDeadDropUnlockOpen(true)}
                    className="w-full flex items-center justify-between gap-2 px-3 py-2 border border-cyan-700/40 bg-cyan-950/15 text-cyan-300 hover:bg-cyan-950/25 hover:border-cyan-500/50 transition-colors"
                  >
                    <span className="inline-flex items-center gap-2 text-sm font-mono tracking-[0.2em]">
                      <Lock size={11} />
                      UNLOCK DEAD DROP
                    </span>
                    <span className="text-[12px] font-mono text-cyan-300/70">
                      NEED WORMHOLE
                    </span>
                  </button>
                ) : activeTab === 'meshtastic' && !hasPublicLaneIdentity ? (
                  <button
                    onClick={() => {
                      if (publicMeshBlockedByWormhole) {
                        void handleLeaveWormholeForPublicMesh();
                        return;
                      }
                      void handleQuickCreatePublicIdentity();
                    }}
                    disabled={identityWizardBusy}
                    className="w-full flex items-center justify-between gap-2 px-3 py-2 border border-green-700/40 bg-green-950/15 text-green-300 hover:bg-green-950/25 hover:border-green-500/50 transition-colors"
                  >
                    <span className="inline-flex items-center gap-2 text-sm font-mono tracking-[0.2em]">
                      <Radio size={11} />
                      {identityWizardBusy
                        ? 'GETTING MESH KEY'
                        : publicMeshBlockedByWormhole
                          ? 'TURN OFF WORMHOLE FOR MESH'
                          : 'GET MESH KEY'}
                    </span>
                    <span className="text-[12px] font-mono text-green-300/70">
                      {identityWizardBusy
                        ? 'WORKING...'
                        : publicMeshBlockedByWormhole
                          ? 'AUTO FIX'
                          : 'ONE TAP'}
                    </span>
                  </button>
                ) : activeTab === 'meshtastic' && meshDirectTarget ? (
                  <button
                    onClick={() => setMeshDirectTarget('')}
                    className="w-full flex items-center justify-between gap-2 px-3 py-2 border border-amber-700/40 bg-amber-950/10 text-amber-200 hover:bg-amber-950/20 hover:border-amber-500/50 transition-colors"
                  >
                    <span className="inline-flex items-center gap-2 text-sm font-mono tracking-[0.2em]">
                      <Send size={11} />
                      DIRECT TO {meshDirectTarget.toUpperCase()}
                    </span>
                    <span className="text-[12px] font-mono text-amber-200/70">RETURN TO CHANNEL</span>
                  </button>
                ) : activeTab === 'infonet' &&
                  privateInfonetReady &&
                  selectedGateKeyStatus?.identity_scope === 'anonymous' &&
                  !selectedGateKeyStatus?.has_local_access ? (
                  <button
                    onClick={() => void handleUnlockEncryptedGate()}
                    className="w-full flex items-center justify-between gap-2 px-3 py-2 border border-amber-700/40 bg-amber-950/10 text-amber-200 hover:bg-amber-950/20 hover:border-amber-500/50 transition-colors"
                  >
                    <span className="inline-flex items-center gap-2 text-sm font-mono tracking-[0.2em]">
                      <Lock size={11} />
                      UNLOCK ENCRYPTED GATE
                    </span>
                    <span className="text-[12px] font-mono text-amber-200/70">
                      {selectedGatePersonaList.length > 0 ? 'USE GATE FACE' : 'CREATE GATE FACE'}
                    </span>
                  </button>
                ) : (
                  <>
                    <span className="text-[11px] text-cyan-400 select-none shrink-0 font-mono" style={{ textShadow: '0 0 6px rgba(34,211,238,0.4)' }}>
                      &gt;
                    </span>
                    <div className="relative flex-1">
                      {activeTab === 'infonet' && gateReplyContext && (
                        <div className="mb-2 flex items-center justify-between gap-2 rounded border border-amber-500/20 bg-amber-500/8 px-2 py-1 text-[12px] font-mono tracking-[0.14em] text-amber-100">
                          <span>
                            REPLYING TO {gateReplyContext.nodeId.slice(0, 12)} / {gateReplyContext.eventId.slice(0, 8)}
                          </span>
                          <button
                            onClick={() => setGateReplyContext(null)}
                            className="text-amber-200/80 transition-colors hover:text-amber-100"
                          >
                            CLEAR
                          </button>
                        </div>
                      )}
                      <div
                        ref={cursorMirrorRef}
                        aria-hidden="true"
                        className="absolute inset-0 overflow-hidden whitespace-pre-wrap break-words text-[11px] font-mono leading-[1.65] pointer-events-none invisible"
                      >
                        {inputValue.slice(0, inputCursorIndex)}
                        <span ref={cursorMarkerRef} className="inline-block w-0 h-[14px] align-text-top" />
                        {inputValue.slice(inputCursorIndex) || ' '}
                      </div>
                      <textarea
                        ref={inputRef}
                        value={inputValue}
                        onChange={(e) => {
                          setInputValue(e.target.value);
                          setInputCursorIndex(e.target.selectionStart ?? e.target.value.length);
                        }}
                        onSelect={syncCursorPosition}
                        onClick={syncCursorPosition}
                        onKeyUp={syncCursorPosition}
                        onFocus={() => {
                          setInputFocused(true);
                          syncCursorPosition();
                        }}
                        onBlur={() => setInputFocused(false)}
                        onScroll={() => {
                          const mirror = cursorMirrorRef.current;
                          if (mirror && inputRef.current) mirror.scrollTop = inputRef.current.scrollTop;
                        }}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' && !e.shiftKey) {
                            e.preventDefault();
                            handleSend();
                          }
                        }}
                        placeholder=""
                        disabled={inputDisabled}
                        rows={1}
                        className="w-full bg-transparent text-[11px] font-mono text-cyan-400 outline-none border-none resize-none placeholder:text-[var(--text-muted)] disabled:opacity-30 leading-[1.65] caret-transparent min-h-[18px] max-h-24 pr-1"
                      />
                      {!busy && !inputDisabled && inputFocused && (
                        <span
                          className="absolute pointer-events-none w-[7px] h-[14px] bg-cyan-400/90 animate-[blink_1s_step-end_infinite]"
                          style={{
                            left: `${cursorMarkerRef.current?.offsetLeft ?? 0}px`,
                            top: `${cursorMarkerRef.current?.offsetTop ?? 1}px`,
                            boxShadow: '0 0 8px rgba(34,211,238,0.45)',
                          }}
                        />
                      )}
                    </div>
                    <button
                      onClick={handleSend}
                      disabled={!inputValue.trim() || inputDisabled}
                      className="p-1 border border-cyan-800/40 text-cyan-500 hover:text-cyan-300 hover:border-cyan-500/50 hover:bg-cyan-950/30 disabled:opacity-20 transition-colors"
                    >
                      <Send size={10} />
                    </button>
                  </>
                )}
              </div>
            </div>
            )}
          </div>
        )}
      </div>

      {gatePersonaPromptOpen && (
        <div className="fixed inset-0 z-[455] bg-black/80 backdrop-blur-sm p-4 flex items-center justify-center">
          <div className="w-full max-w-md border border-fuchsia-800/50 bg-[var(--bg-primary)] shadow-[0_0_34px_rgba(236,72,153,0.12)]">
            <div className="flex items-center justify-between px-4 py-3 border-b border-fuchsia-800/40">
              <div>
                <div className="text-sm font-mono tracking-[0.24em] text-fuchsia-300">
                  GATE FACE
                </div>
                <div className="text-[13px] font-mono text-[var(--text-muted)] mt-1">
                  {gatePersonaPromptTitle
                    ? `Entering ${String(gatePersonaPromptTitle).toUpperCase()}`
                    : 'Choose how you enter this gate'}
                </div>
              </div>
              <button
                onClick={closeGatePersonaPrompt}
                className="text-[var(--text-muted)] hover:text-fuchsia-300 transition-colors"
                title="Close gate face chooser"
              >
                <X size={13} />
              </button>
            </div>

            <div className="px-4 py-4 space-y-3">
              <div className="border border-fuchsia-800/25 bg-fuchsia-950/10 px-3 py-3 text-sm font-mono text-fuchsia-100/85 leading-[1.7]">
                Stay anonymous in this gate or create a gate-only face. Face names stay inside
                this gate and cannot be changed in this build.
              </div>

              {gatePersonaPromptPersonaList.length > 0 && (
                <div className="border border-cyan-800/25 bg-cyan-950/10 px-3 py-3">
                  <div className="text-[12px] font-mono tracking-[0.18em] text-cyan-300 mb-2">
                    SAVED FACES
                  </div>
                  <div className="space-y-2">
                    {gatePersonaPromptPersonaList.map((persona) => (
                      <button
                        key={persona.persona_id || persona.node_id}
                        onClick={() => void useSavedGatePersona(String(persona.persona_id || ''))}
                        disabled={gatePersonaBusy}
                        className="w-full flex items-center justify-between gap-2 px-3 py-2 border border-cyan-700/35 bg-black/20 text-left text-sm font-mono text-cyan-200 hover:bg-cyan-950/20 hover:border-cyan-500/50 disabled:opacity-50 transition-colors"
                      >
                        <span>
                          {persona.label || persona.persona_id || String(persona.node_id || '').slice(0, 12)}
                        </span>
                        <span className="text-[12px] tracking-[0.16em] text-cyan-300/70">
                          USE FACE
                        </span>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              <div className="border border-fuchsia-800/25 bg-black/20 px-3 py-3 space-y-2">
                <div className="text-[12px] font-mono tracking-[0.18em] text-fuchsia-300">
                  CREATE NEW FACE
                </div>
                <input
                  value={gatePersonaDraftLabel}
                  onChange={(e) => {
                    setGatePersonaDraftLabel(e.target.value.slice(0, 24));
                    setGatePersonaPromptError('');
                  }}
                  placeholder="gate name / handle"
                  className="w-full bg-black/30 border border-fuchsia-700/35 text-sm font-mono text-fuchsia-100 px-3 py-2 outline-none placeholder:text-fuchsia-200/35 focus:border-fuchsia-500/55"
                />
                <div className="text-[12px] font-mono text-fuchsia-200/55 leading-[1.5]">
                  Example: `signalfox`, `source-a`, `ops-lantern`
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => void submitGatePersonaPrompt()}
                    disabled={gatePersonaBusy || gatePersonaDraftLabel.trim().length < 2}
                    className="px-3 py-1.5 border border-fuchsia-600/40 bg-fuchsia-950/20 text-sm font-mono tracking-[0.18em] text-fuchsia-200 hover:bg-fuchsia-950/30 hover:border-fuchsia-400/50 disabled:opacity-50 transition-colors"
                  >
                    {gatePersonaBusy ? 'CREATING' : 'CREATE FACE'}
                  </button>
                  <button
                    onClick={remainAnonymousInGate}
                    disabled={gatePersonaBusy}
                    className="px-3 py-1.5 border border-amber-700/35 bg-amber-950/10 text-sm font-mono tracking-[0.18em] text-amber-200 hover:bg-amber-950/20 hover:border-amber-500/50 disabled:opacity-50 transition-colors"
                  >
                    REMAIN ANONYMOUS
                  </button>
                </div>
              </div>

              {gatePersonaPromptError && (
                <div className="border border-red-700/35 bg-red-950/10 px-3 py-2 text-sm font-mono text-red-300">
                  {gatePersonaPromptError}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {identityWizardOpen && (
        <div className="fixed inset-0 z-[450] bg-black/75 backdrop-blur-sm p-3 flex items-center justify-center">
          <div className="w-full max-w-md border border-cyan-800/50 bg-[var(--bg-primary)] shadow-[0_0_30px_rgba(0,255,255,0.08)]">
            <div className="flex items-center justify-between px-3 py-2 border-b border-[var(--border-primary)]/40">
                <div>
                <div className="text-sm font-mono tracking-[0.24em] text-cyan-400">KEY SETUP</div>
                <div className="text-[13px] font-mono text-[var(--text-muted)] mt-1">
                  Get a public mesh key or enter Wormhole.
                </div>
              </div>
              <button
                onClick={() => setIdentityWizardOpen(false)}
                className="text-[var(--text-muted)] hover:text-cyan-300 transition-colors"
                title="Close identity setup"
              >
                <X size={13} />
              </button>
            </div>

            <div className="px-3 py-3 space-y-2.5">
              <div className="grid grid-cols-2 gap-2 text-[12px] font-mono">
                <div className="border border-amber-500/20 bg-amber-950/10 px-2.5 py-2 text-amber-200/85 leading-[1.5]">
                  <div className="text-amber-300 tracking-[0.18em] mb-1">PUBLIC MESH</div>
                  Public lane. One tap gets you a posting key.
                </div>
                <div className="border border-cyan-500/20 bg-cyan-950/10 px-2.5 py-2 text-cyan-200/85 leading-[1.5]">
                  <div className="text-cyan-300 tracking-[0.18em] mb-1">WORMHOLE</div>
                  Experimental obfuscation lane for gates and Dead Drop.
                </div>
              </div>

              <div className="border border-[var(--border-primary)]/40 bg-black/20 px-3 py-2">
                <div className="text-[13px] font-mono tracking-[0.18em] text-cyan-300 mb-1">
                  CURRENT STATE
                </div>
                <div className="grid grid-cols-1 gap-1 text-[13px] font-mono text-[var(--text-secondary)] leading-[1.5]">
                  <div>Public mesh key: {hasPublicLaneIdentity ? 'active' : 'not issued'}</div>
                  <div>Public mesh address: {hasPublicLaneIdentity && publicMeshAddress ? publicMeshAddress.toUpperCase() : 'not ready'}</div>
                  <div>Wormhole lane: {wormholeEnabled && wormholeReadyState ? 'active' : wormholeEnabled ? 'starting' : 'off'}</div>
                  <div>Wormhole descriptor: {wormholeDescriptor?.nodeId || 'not cached yet'}</div>
                </div>
              </div>

              <div className="grid grid-cols-1 gap-2">
                <button
                  onClick={() => {
                    if (publicMeshBlockedByWormhole) {
                      void handleLeaveWormholeForPublicMesh();
                      return;
                    }
                    void handleCreatePublicIdentity();
                  }}
                  disabled={identityWizardBusy}
                  className="w-full text-left px-3 py-2 border border-green-500/30 bg-green-950/10 hover:bg-green-950/20 text-sm font-mono text-green-300 disabled:opacity-50"
                >
                  {hasPublicLaneIdentity
                    ? 'MESH KEY ACTIVE'
                    : publicMeshBlockedByWormhole
                      ? 'TURN OFF WORMHOLE FOR MESH'
                      : 'GET MESH KEY'}
                  <div className="mt-1 text-[13px] text-green-200/70 normal-case tracking-normal leading-[1.45]">
                    {hasPublicLaneIdentity
                      ? 'Your public mesh key is already live for posting.'
                      : publicMeshBlockedByWormhole
                        ? 'One tap turns Wormhole off and mints a separate public mesh key.'
                        : 'One tap for a working mesh key and address.'}
                  </div>
                </button>

                <button
                  onClick={() => void handleBootstrapPrivateIdentity()}
                  disabled={identityWizardBusy}
                  className="w-full text-left px-3 py-2 border border-cyan-500/30 bg-cyan-950/10 hover:bg-cyan-950/20 text-sm font-mono text-cyan-300 disabled:opacity-50"
                >
                  {wormholeEnabled && wormholeReadyState ? 'ENTER INFONET' : 'GET WORMHOLE KEY'}
                  <div className="mt-1 text-[13px] text-cyan-200/70 normal-case tracking-normal leading-[1.45]">
                    {wormholeEnabled && wormholeReadyState
                      ? 'Wormhole is already live. Jump straight into gates and the private inbox.'
                      : 'Use this for gates, experimental obfuscation, and the private inbox.'}
                  </div>
                </button>

                <div className="flex items-center gap-2">
                  <button
                    onClick={() => void handleResetPublicIdentity()}
                    disabled={identityWizardBusy}
                    className="flex-1 text-left px-3 py-2 border border-red-500/30 bg-red-950/10 hover:bg-red-950/20 text-sm font-mono text-red-300 disabled:opacity-50"
                  >
                    RESET PUBLIC IDENTITY
                  </button>
                  {publicMeshBlockedByWormhole && (
                    <button
                      onClick={() => void handleLeaveWormholeForPublicMesh()}
                      disabled={identityWizardBusy}
                      className="px-3 py-2 border border-green-500/30 bg-green-950/10 text-sm font-mono text-green-300 hover:bg-green-950/20 disabled:opacity-50"
                    >
                      TURN OFF WORMHOLE
                    </button>
                  )}
                  {onSettingsClick && (
                    <button
                      onClick={() => {
                        setIdentityWizardOpen(false);
                        onSettingsClick();
                      }}
                      className="px-3 py-2 border border-[var(--border-primary)] text-sm font-mono text-[var(--text-secondary)] hover:text-cyan-300 hover:border-cyan-500/40"
                    >
                      OPEN SETTINGS
                    </button>
                  )}
                </div>
              </div>

              {identityWizardStatus && (
                <div
                  className={`px-3 py-2 border text-sm font-mono leading-[1.65] ${
                    identityWizardStatus.type === 'ok'
                      ? 'border-green-500/30 bg-green-950/10 text-green-300'
                      : 'border-red-500/30 bg-red-950/10 text-red-300'
                  }`}
                >
                  {identityWizardStatus.text}
                </div>
              )}

              <div className="text-[12px] font-mono text-[var(--text-muted)] leading-[1.5]">
                Testnet note: mesh is public, gates use experimental encryption, and Dead Drop is the strongest current lane.
              </div>
            </div>
          </div>
        </div>
      )}

      {infonetUnlockOpen && (
        <div className="fixed inset-0 z-[460] bg-black/80 backdrop-blur-sm p-4 flex items-center justify-center">
          <div className="w-full max-w-xl border border-cyan-800/50 bg-[var(--bg-primary)] shadow-[0_0_34px_rgba(0,255,255,0.1)]">
            <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--border-primary)]/40">
              <div>
                <div className="text-sm font-mono tracking-[0.24em] text-cyan-400">
                  PRIVATE INFONET LOCKED
                </div>
                <div className="text-[13px] font-mono text-[var(--text-muted)] mt-1">
                  INFONET is the private Wormhole lane. Public perimeter traffic stays under MESH.
                </div>
              </div>
              <button
                onClick={() => setInfonetUnlockOpen(false)}
                className="text-[var(--text-muted)] hover:text-cyan-300 transition-colors"
                title="Close private lane brief"
              >
                <X size={13} />
              </button>
            </div>

            <div className="px-4 py-4 space-y-4">
              <div className="border border-cyan-800/30 bg-cyan-950/10 px-3 py-3 text-sm font-mono text-[var(--text-secondary)] leading-[1.8] space-y-2">
                <div>
                  INFONET is the private lane now. Public perimeter traffic lives under the
                  <span className="text-green-300"> MESH </span>
                  tab.
                </div>
                <div>{privateInfonetBlockedDetail}</div>
                <div>
                  Use Wormhole to enter private gates, personas, gate chat, and the serious
                  testnet path.
                </div>
              </div>

              <div className="border border-amber-500/20 bg-amber-950/10 px-3 py-3 text-sm font-mono text-amber-100/85 leading-[1.75]">
                <div className="text-[13px] tracking-[0.18em] text-amber-300 mb-1">TRUST MODES</div>
                <div><span className="text-orange-300">PUBLIC / DEGRADED</span> — public mesh and perimeter feeds.</div>
                <div><span className="text-yellow-300">EXPERIMENTAL ENCRYPTION</span> — Wormhole lane active, strongest transport posture still warming.</div>
                <div><span className="text-green-300">PRIVATE / STRONG</span> — Wormhole and Reticulum are both ready.</div>
              </div>

              <div className="flex flex-wrap gap-2">
                <button
                  onClick={() => {
                    setInfonetUnlockOpen(false);
                    onSettingsClick?.();
                  }}
                  className="px-3 py-1.5 border border-cyan-500/40 bg-cyan-950/20 text-sm font-mono text-cyan-300 hover:bg-cyan-950/35 transition-colors"
                >
                  OPEN WORMHOLE
                </button>
                <button
                  onClick={() => {
                    setInfonetUnlockOpen(false);
                    openTerminal();
                  }}
                  className="px-3 py-1.5 border border-green-500/40 bg-green-950/20 text-sm font-mono text-green-300 hover:bg-green-950/35 transition-colors inline-flex items-center gap-1.5"
                >
                  <Terminal size={11} />
                  TERMINAL
                </button>
                <button
                  onClick={() => {
                    setInfonetUnlockOpen(false);
                    setActiveTab('meshtastic');
                  }}
                  className="px-3 py-1.5 border border-amber-500/40 bg-amber-950/20 text-sm font-mono text-amber-300 hover:bg-amber-950/35 transition-colors"
                >
                  GO TO MESH
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {deadDropUnlockOpen && (
        <div className="fixed inset-0 z-[460] bg-black/80 backdrop-blur-sm p-4 flex items-center justify-center">
          <div className="w-full max-w-lg border border-cyan-800/50 bg-[var(--bg-primary)] shadow-[0_0_34px_rgba(0,255,255,0.1)]">
            <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--border-primary)]/40">
              <div>
                <div className="text-sm font-mono tracking-[0.24em] text-cyan-400">
                  DEAD DROP LOCKED
                </div>
                <div className="text-[13px] font-mono text-[var(--text-muted)] mt-1">
                  Dead Drop is the private inbox lane. Public mesh does not substitute for it.
                </div>
              </div>
              <button
                onClick={() => setDeadDropUnlockOpen(false)}
                className="text-[var(--text-muted)] hover:text-cyan-300 transition-colors"
                title="Close dead drop brief"
              >
                <X size={13} />
              </button>
            </div>

            <div className="px-4 py-4 space-y-4">
              <div className="border border-cyan-800/30 bg-cyan-950/10 px-3 py-3 text-sm font-mono text-[var(--text-secondary)] leading-[1.8] space-y-2">
                <div>Need Wormhole activated.</div>
                <div>
                  Dead Drop handles private contacts, inbox requests, and message exchange on the
                  private lane.
                </div>
                <div>
                  Public mesh stays public. Dead Drop does not downgrade into the perimeter just to
                  look available.
                </div>
              </div>

              <div className="flex flex-wrap gap-2">
                <button
                  onClick={() => {
                    setDeadDropUnlockOpen(false);
                    onSettingsClick?.();
                  }}
                  className="px-3 py-1.5 border border-cyan-500/40 bg-cyan-950/20 text-sm font-mono text-cyan-300 hover:bg-cyan-950/35 transition-colors"
                >
                  OPEN WORMHOLE
                </button>
                <button
                  onClick={() => {
                    setDeadDropUnlockOpen(false);
                    openTerminal();
                  }}
                  className="px-3 py-1.5 border border-green-500/40 bg-green-950/20 text-sm font-mono text-green-300 hover:bg-green-950/35 transition-colors inline-flex items-center gap-1.5"
                >
                  <Terminal size={11} />
                  TERMINAL
                </button>
                <button
                  onClick={() => {
                    setDeadDropUnlockOpen(false);
                    setActiveTab('meshtastic');
                  }}
                  className="px-3 py-1.5 border border-amber-500/40 bg-amber-950/20 text-sm font-mono text-amber-300 hover:bg-amber-950/35 transition-colors"
                >
                  GO TO MESH
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ─── SENDER POPUP (fixed position) ─── */}
      {senderPopup && (
        <div
          ref={popupRef}
          className="fixed z-[500] bg-[var(--bg-primary)]/95 border border-[var(--border-primary)] shadow-[0_4px_20px_rgba(0,0,0,0.4)] backdrop-blur-sm py-1 min-w-[140px]"
          style={{ left: senderPopup.x, top: senderPopup.y }}
        >
          <div className="px-3 py-1 border-b border-[var(--border-primary)]/50">
            <span className="text-[13px] font-mono text-cyan-400 tracking-wider">
              {senderPopup.userId.slice(0, 16)}
            </span>
          </div>

          {senderPopup.tab === 'infonet' && (
            <div className="px-3 py-2 border-b border-[var(--border-primary)]/50">
              <div className="text-[12px] font-mono text-[var(--text-muted)] tracking-[0.18em]">
                PUBLIC KEY
              </div>
              <div
                className="mt-1 text-[12px] font-mono text-green-300/90 break-all leading-[1.55]"
                title={senderPopup.publicKey || 'not advertised on this event'}
              >
                {senderPopup.publicKey || 'not advertised on this event'}
              </div>
              {senderPopup.publicKeyAlgo ? (
                <div className="mt-1 text-[12px] font-mono text-cyan-500/80">
                  {senderPopup.publicKeyAlgo}
                </div>
              ) : null}
            </div>
          )}

          {/* MUTE / UNMUTE */}
          {mutedUsers.has(senderPopup.userId) ? (
            <button
              onClick={() => handleUnmute(senderPopup.userId)}
              className="w-full flex items-center gap-2 px-3 py-1.5 text-[13px] font-mono text-[var(--text-secondary)] hover:bg-[var(--bg-secondary)]/50 transition-colors"
            >
              <Eye size={10} /> UNMUTE
            </button>
          ) : (
            <button
              onClick={() => setMuteConfirm(senderPopup.userId)}
              className="w-full flex items-center gap-2 px-3 py-1.5 text-[13px] font-mono text-red-400/80 hover:bg-red-900/10 transition-colors"
            >
              <EyeOff size={10} /> MUTE
            </button>
          )}

          {/* LOCATE — meshtastic only */}
          {senderPopup.tab === 'meshtastic' && (
            <>
              <button
                onClick={() => handleReplyToMeshAddress(senderPopup.userId)}
                className="w-full flex items-center gap-2 px-3 py-1.5 text-[13px] font-mono text-green-300 hover:bg-green-950/20 transition-colors"
              >
                <Send size={10} /> REPLY
              </button>
              <button
                onClick={() => handleLocateUser(senderPopup.userId)}
                className="w-full flex items-center gap-2 px-3 py-1.5 text-[13px] font-mono text-[var(--text-secondary)] hover:bg-[var(--bg-secondary)]/50 transition-colors"
              >
                <MapPin size={10} /> LOCATE
              </button>
            </>
          )}

          {/* CONTACT PATH — infonet only */}
          {senderPopup.tab === 'infonet' && hasId && senderPopup.userId !== identity?.nodeId && (
            <>
              {senderPopupContact && !senderPopupContact.blocked ? (
                <button
                  onClick={() => {
                    setActiveTab('dms');
                    openChat(senderPopup.userId);
                    setSenderPopup(null);
                  }}
                  className="w-full flex items-center gap-2 px-3 py-1.5 text-[13px] font-mono text-green-300 hover:bg-green-950/20 transition-colors"
                >
                  <Send size={10} /> OPEN DM
                </button>
              ) : (
                <button
                  onClick={() => {
                    handleRequestAccess(senderPopup.userId);
                    setSenderPopup(null);
                  }}
                  className="w-full flex items-center gap-2 px-3 py-1.5 text-[13px] font-mono text-[var(--text-secondary)] hover:bg-[var(--bg-secondary)]/50 transition-colors"
                >
                  <UserPlus size={10} /> REQUEST CONTACT
                </button>
              )}
              {!senderPopupContact?.blocked ? (
                <button
                  onClick={() => {
                    void handleBlockDM(senderPopup.userId);
                    setSenderPopup(null);
                  }}
                  className="w-full flex items-center gap-2 px-3 py-1.5 text-[13px] font-mono text-red-400/80 hover:bg-red-900/10 transition-colors"
                >
                  <Ban size={10} /> BLOCK
                </button>
              ) : (
                <div className="px-3 py-1.5 text-[12px] font-mono text-red-300/70 tracking-[0.18em]">
                  CONTACT BLOCKED
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* ─── MUTE CONFIRMATION DIALOG ─── */}
      {muteConfirm && (
        <div className="fixed inset-0 z-[600] flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="bg-[var(--bg-primary)] border border-[var(--border-primary)] p-4 max-w-[260px] w-full">
            <div className="text-sm font-mono text-[var(--text-secondary)] mb-1">
              CONFIRM MUTE
            </div>
            <div className="text-[13px] font-mono text-[var(--text-muted)] mb-3 leading-[1.65]">
              Mute <span className="text-cyan-400">{muteConfirm.slice(0, 16)}</span>? Their messages
              will be hidden. You can unmute from Dead Drop &gt; MUTED.
            </div>
            <div className="flex items-center gap-2 justify-end">
              <button
                onClick={() => {
                  setMuteConfirm(null);
                  setSenderPopup(null);
                }}
                className="text-[13px] font-mono px-3 py-1 bg-[var(--bg-secondary)]/50 text-[var(--text-muted)] hover:bg-[var(--bg-secondary)] transition-colors"
              >
                CANCEL
              </button>
              <button
                onClick={() => handleMute(muteConfirm)}
                className="text-[13px] font-mono px-3 py-1 bg-red-900/30 text-red-400 hover:bg-red-800/40 transition-colors"
              >
                MUTE
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
});

export default MeshChat;
