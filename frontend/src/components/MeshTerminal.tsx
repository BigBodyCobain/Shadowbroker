'use client';

import React, { useState, useRef, useEffect, useCallback, useMemo } from 'react';
import { Terminal, X, GripHorizontal, Minus } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  getNodeIdentity,
  generateNodeKeys,
  getWormholeIdentityDescriptor,
  hasSovereignty,
  declineSovereignty,
  isDeclined,
  getDHPubKey,
  getDHAlgo,
  generateDHKeys,
  deriveSharedKey,
  decryptDM,
  getContacts,
  addContact,
  blockContact,
  unblockContact,
  getDMNotify,
  setDMNotify,
  signEvent,
  signMessage,
  nextSequence,
  setSequence,
  createIdentityCandidate,
  persistIdentity,
  hydrateWormholeContacts,
  verifyEventSignature,
  getPublicKeyAlgo,
  migrateLegacyNodeIds,
  type NodeIdentity,
} from '@/mesh/meshIdentity';
import { ratchetEncryptDM, ratchetDecryptDM } from '@/mesh/meshDmWorkerClient';
import {
  buildMailboxClaims,
  countDmMailboxes,
  ensureRegisteredDmKey,
  pollDmMailboxes,
  sendDmMessage,
  sharedMailboxToken,
} from '@/mesh/meshDmClient';
import { PROTOCOL_VERSION, buildSignaturePayload } from '@/mesh/meshProtocol';
import { validateEventPayload } from '@/mesh/meshSchema';
import { verifyMerkleProof } from '@/mesh/meshMerkle';
import { API_BASE } from '@/lib/api';
import { controlPlaneJson } from '@/lib/controlPlane';
import { getPrivacyStrictPreference } from '@/lib/privacyBrowserStorage';
import { getDesktopNativeControlAuditReport } from '@/lib/desktopBridge';
import { describeNativeControlError } from '@/lib/desktopControlContract';
import {
  getSensitiveBrowserItem,
  setSensitiveBrowserItem,
} from '@/lib/privacyBrowserStorage';
import {
  fetchInfonetNodeStatusSnapshot,
  type InfonetNodeStatusSnapshot,
} from '@/mesh/controlPlaneStatusClient';
import { fetchWormholeStatus } from '@/mesh/wormholeIdentityClient';
import {
  bootstrapWormholeIdentity,
  clearWormholeGatePersona,
  createWormholeGatePersona,
  decryptWormholeGateMessage,
  fetchWormholeGateKeyStatus,
  rotateWormholeGateKey,
} from '@/mesh/wormholeIdentityClient';
import { fetchWormholeSettings, joinWormhole } from '@/mesh/wormholeClient';
import {
  getMeshTerminalWriteLockReason,
  isMeshTerminalWriteCommand,
} from '@/lib/meshTerminalPolicy';
import {
  gateEnvelopeDisplayText,
  gateEnvelopeState,
  isEncryptedGateEnvelope,
} from '@/mesh/gateEnvelope';

const API = API_BASE;
const INFONET_HEAD_KEY = 'sb_infonet_head';
const INFONET_HEAD_HISTORY_KEY = 'sb_infonet_head_history';
const INFONET_LOCATOR_LIMIT = 32;
const INFONET_PEERS_KEY = 'sb_infonet_peers';
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
const SETTINGS_FOCUS_KEY = 'sb_settings_focus';
const WORMHOLE_RETURN_KEY = 'sb_wormhole_return_target';
const WORMHOLE_READY_EVENT = 'sb:wormhole-ready';
const DEFAULT_TERMINAL_SIZE = { w: 1040, h: 760 };

function getTerminalSensitiveItem(key: string): string {
  if (typeof window === 'undefined') return '';
  return getSensitiveBrowserItem(key) || '';
}

function setTerminalSensitiveItem(key: string, value: string): void {
  if (typeof window === 'undefined') return;
  setSensitiveBrowserItem(key, value);
}

interface Props {
  isOpen: boolean;
  launchToken?: number;
  onClose: () => void;
  onDmCount?: (count: number) => void;
  onSettingsClick?: () => void;
}

interface TermLine {
  text: string;
  type: 'input' | 'output' | 'error' | 'system' | 'header' | 'dim';
  actionCommand?: string;
  actionLabel?: string;
}

interface InfonetEventPayload {
  [key: string]: unknown;
}

interface InfonetMessageRecord {
  event_id: string;
  event_type?: string;
  node_id?: string;
  message?: string;
  ciphertext?: string;
  epoch?: number;
  nonce?: string;
  sender_ref?: string;
  format?: string;
  gate?: string;
  payload?: {
    gate?: string;
    ciphertext?: string;
    nonce?: string;
    sender_ref?: string;
    format?: string;
  };
  timestamp: number;
  ephemeral?: boolean;
  system_seed?: boolean;
  fixed_gate?: boolean;
}

interface InfonetEvent {
  event_id: string;
  event_type: string;
  node_id: string;
  sequence?: number;
  payload?: InfonetEventPayload;
  signature?: string;
  public_key?: string;
  public_key_algo?: string;
}

interface InfonetMerkleProof {
  leaf?: string;
  index?: number;
  proof?: string[];
}

interface InfonetSyncResponse {
  ok?: boolean;
  forked?: boolean;
  matched_hash?: string;
  events?: InfonetEvent[];
  merkle_proofs?: InfonetMerkleProof[];
  merkle_root?: string;
  head_hash?: string;
}

async function buildGateAccessHeaders(gateId: string): Promise<Record<string, string> | undefined> {
  const normalizedGate = String(gateId || '').trim().toLowerCase();
  if (!normalizedGate) return undefined;
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
    return {
      'X-Wormhole-Node-Id': nodeId,
      'X-Wormhole-Gate-Proof': gateProof,
      'X-Wormhole-Gate-Ts': gateTs,
    };
  } catch {
    return undefined;
  }
}

interface GateSummary {
  gate_id: string;
  display_name?: string;
  description?: string;
  message_count?: number;
  fixed?: boolean;
  rules?: {
    min_overall_rep?: number;
  };
}

interface GateDetailRecord {
  ok?: boolean;
  gate_id: string;
  display_name?: string;
  description?: string;
  welcome?: string;
  creator_node_id?: string;
  message_count?: number;
  fixed?: boolean;
  rules?: {
    min_overall_rep?: number;
  };
}

function normalizeInfonetMessageRecord(message: InfonetMessageRecord): InfonetMessageRecord {
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

interface GateKeyStatusRecord {
  ok?: boolean;
  current_epoch?: number;
  key_commitment?: string;
  has_local_access?: boolean;
  identity_scope?: string;
  rekey_recommended?: boolean;
  rekey_recommended_reason?: string;
}

interface InboxPreviewRecord {
  sender: string;
  age: string;
  text: string;
  locked?: boolean;
}

interface GateThreadPreview {
  nodeId: string;
  age: string;
  text: string;
  encrypted?: boolean;
}

interface MeshStatusResponse {
  signal_counts?: {
    aprs?: number;
    meshtastic?: number;
    js8call?: number;
    total?: number;
  };
}

function formatNodeMode(mode?: string): string {
  const normalized = String(mode || 'participant').trim().toLowerCase();
  if (!normalized) return 'PARTICIPANT';
  return normalized.toUpperCase();
}

function shortNodeHash(value?: string, size: number = 14): string {
  const normalized = String(value || '').trim();
  if (!normalized) return 'genesis';
  if (normalized.length <= size) return normalized;
  return `${normalized.slice(0, size)}...`;
}

function formatNodeTime(ts?: number): string {
  const value = Number(ts || 0);
  if (!Number.isFinite(value) || value <= 0) return 'never';
  return new Date(value * 1000).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
  });
}

function summarizeNodePeer(peerUrl?: string): string {
  const value = String(peerUrl || '').trim();
  if (!value) return 'none yet';
  try {
    return new URL(value).host || value;
  } catch {
    return value;
  }
}

function describeBootstrapState(snapshot?: InfonetNodeStatusSnapshot | null): string {
  const bootstrap = snapshot?.bootstrap;
  if (!bootstrap) return 'LOCAL ONLY';
  if (bootstrap.manifest_loaded) {
    return `SIGNED ${bootstrap.manifest_signer_id || 'manifest'}`;
  }
  if (bootstrap.last_bootstrap_error) {
    return `FAILED ${bootstrap.last_bootstrap_error}`;
  }
  return 'LOCAL ONLY';
}

function describeSyncOutcome(snapshot?: InfonetNodeStatusSnapshot | null): string {
  const sync = snapshot?.sync_runtime;
  if (!sync) return 'IDLE';
  const outcome = String(sync.last_outcome || 'idle').trim().toLowerCase();
  if (outcome === 'ok') {
    return `OK @ ${formatNodeTime(sync.last_sync_ok_at)} via ${summarizeNodePeer(sync.last_peer_url)}`;
  }
  if (outcome === 'running') {
    return `RUNNING via ${summarizeNodePeer(sync.last_peer_url)}`;
  }
  if (outcome === 'fork') {
    return `FORK STOP via ${summarizeNodePeer(sync.last_peer_url)}`;
  }
  if (outcome === 'error') {
    return `ERROR ${sync.last_error || 'unknown'}`;
  }
  return 'IDLE';
}

function buildNodeRuntimeLines(snapshot: InfonetNodeStatusSnapshot): TermLine[] {
  const bootstrap = snapshot.bootstrap;
  const sync = snapshot.sync_runtime;
  const push = snapshot.push_runtime;
  const lines: TermLine[] = [
    { text: '  NODE RUNTIME', type: 'system' },
    { text: `    Mode:        ${formatNodeMode(snapshot.node_mode)}`, type: 'output' },
    {
      text: `    Bootstrap:   ${describeBootstrapState(snapshot)}`,
      type: bootstrap?.last_bootstrap_error ? 'error' : 'output',
    },
    {
      text: `    Peers:       ${Number(bootstrap?.sync_peer_count || 0)} sync | ${Number(bootstrap?.push_peer_count || 0)} push | ${Number(bootstrap?.bootstrap_peer_count || 0)} bootstrap`,
      type: 'output',
    },
    { text: `    Sync Loop:   ${describeSyncOutcome(snapshot)}`, type: 'output' },
    {
      text: `    Next Sync:   ${formatNodeTime(sync?.next_sync_due_at)}`,
      type: 'output',
    },
  ];
  if (push?.last_event_id) {
    lines.push({
      text: `    Last Push:   ${shortNodeHash(push.last_event_id, 18)} @ ${formatNodeTime(push.last_push_ok_at)}`,
      type: 'output',
    });
  }
  if (sync?.fork_detected) {
    lines.push({
      text: '    Fork Stop:   automatic sync paused until the fork is resolved',
      type: 'error',
    });
  }
  if (push?.last_push_error) {
    lines.push({
      text: `    Push Warn:   ${push.last_push_error}`,
      type: 'error',
    });
  }
  lines.push({ text: '', type: 'dim' });
  return lines;
}

const WELCOME: TermLine[] = [
  { text: '', type: 'dim' },
  { text: '  Docked into the Infonet Commons node.', type: 'header' },
  { text: '', type: 'dim' },
];

const QUICK_LAUNCHES = [
  { label: 'HELP', panel: 'help', tone: 'yellow' },
  { label: 'APPS', panel: 'apps', tone: 'cyan' },
  { label: 'MESH', panel: 'mesh', tone: 'green' },
  { label: 'GATES (EXPERIMENTAL ENCRYPTION)', panel: 'gates', tone: 'pink' },
  { label: 'MARKETS', panel: 'markets', tone: 'yellow' },
  { label: 'DOSSIER', panel: 'dossier', tone: 'pink' },
  { label: 'INBOX', panel: 'inbox', tone: 'cyan' },
] as const;

const SOVEREIGNTY_DECLARATION: TermLine[] = [
  { text: '', type: 'dim' },
  { text: '  AGENT ACTIVATION', type: 'header' },
  { text: '', type: 'dim' },
  { text: '  By activating your Agent identity, you acknowledge:', type: 'dim' },
  { text: '', type: 'dim' },
  { text: '  - You are solely responsible for your transmissions', type: 'output' },
  { text: '  - Your Agent ID is your identity — abuse it, lose reputation', type: 'output' },
  { text: '  - This network may relay your messages across radio frequencies', type: 'output' },
  { text: '  - No one controls this network. It is decentralized by design.', type: 'output' },
  {
    text: '  - Public Infonet events are signed; degraded RF/router paths are integrity-only and NOT encrypted',
    type: 'output',
  },
  { text: '  - If your radio broadcasts GPS, your position is visible on the map', type: 'output' },
  { text: '    (disable GPS beacons on hardware to remain geographically anonymous)', type: 'dim' },
  { text: '', type: 'dim' },
  { text: '  Note: RF networks may be IP-traceable. You may not be anonymous.', type: 'dim' },
  { text: '', type: 'dim' },
  {
    text: "  Type 'accept' to generate your Agent ID, or 'decline' for read-only.",
    type: 'system',
  },
  { text: '', type: 'dim' },
];

const HELP_SECTIONS: Record<string, string[]> = {
  mesh: [
    '  MESH / RADIO',
    '    mesh                Show active root and radio commands',
    '    mesh region <root>  Switch root (US, EU_868, PL, US/rob/snd, etc.)',
    '    mesh listen [n]     Recent Meshtastic signals from root',
    "    mesh send <msg>     Transmit to root's LongFast channel",
    '    mesh channels       Root counts and channel overview',
    '    MESH uses your public Agent identity. It is public / observable.',
  ],
  gates: [
    '  GATES (EXPERIMENTAL ENCRYPTION)',
    '    gates               List fixed private launch gates',
    '    gate <id>           View gate details',
    '    gate mask <id>      Create and activate a gate face',
    '    gate anon <id>      Return to anonymous gate mode',
    '    gate rekey <id>     Rotate the gate content key',
    '    say <gate> <msg>    Post to an encrypted gate lane',
    '    Gates and Dead Drop run through Wormhole. Public mesh does not.',
  ],
  inbox: [
    '  EXPERIMENTAL PRIVATE DM INBOX',
    '    inbox               Check pending private messages',
    '    contacts            List saved contacts',
    '    dm                  Start interactive encrypted DM',
    '    dm <id> <msg>       Send one-line private message',
    '    dm block <id>       Block a contact',
    '    dm unblock <id>     Unblock a contact',
  ],
  markets: [
    '  MARKETS / ORACLE',
    '    markets [query]     Browse or search prediction markets',
    '    predict <title> yes|no  Place a prediction',
    '    oracle [agent_id]   View oracle profile',
    '    stake <msg_id> ...  Stake oracle rep on a claim',
    '    stakes <msg_id>     View active stakes',
  ],
  infonet: [
    '  INFONET',
    '    infonet             Network status',
    '    messages [gate]     Browse recent Infonet messages',
    '    event <event_id>    View a single event',
    '    ledger [agent_id]   View node activity',
    '    sync [limit]        Pull and verify new events',
    '    merkle              Show merkle root + head hash',
  ],
  ops: [
    '  OPS / DOSSIER / SEARCH',
    '    apps                List terminal-accessible surfaces',
    '    news [query]        Latest headlines or filtered headlines',
    '    dossier <query>     Build a multi-source brief',
    '    place <query>       Search places and infrastructure',
    '    jet <query>         Search jets / flights / operators',
    '    shodan <query>      Search exposed hosts and services',
  ],
};

const GUIDE_TEXT: TermLine[] = [
  { text: '', type: 'dim' },
  { text: '  HOW THIS WORKS', type: 'header' },
  { text: '', type: 'dim' },
  { text: '  ShadowBroker is a decentralized intelligence network.', type: 'dim' },
  { text: '  It connects to live radio networks (APRS, Meshtastic, JS8Call)', type: 'dim' },
  { text: '  and runs the Infonet — a protocol where every action is', type: 'dim' },
  { text: '  signed, public, and reputation-scored.', type: 'dim' },
  { text: '', type: 'dim' },
  { text: '  1. CONNECT', type: 'system' },
  { text: "     Type 'connect' to create your local public Agent identity.", type: 'dim' },
  { text: '     This is for public mesh + perimeter activity. It generates', type: 'dim' },
  { text: '     an Ed25519 keypair locally. Your private key never leaves', type: 'dim' },
  { text: '     your device. No registration, no server, no email.', type: 'dim' },
  { text: "     Wormhole is the separate obfuscated lane for gates + Dead Drop.", type: 'dim' },
  { text: '', type: 'dim' },
  { text: '  2. MONITOR', type: 'system' },
  { text: "     'signals' — see live radio traffic (APRS, LoRa, HF)", type: 'dim' },
  { text: "     'status' — see all network connections + Infonet state", type: 'dim' },
  { text: "     'markets' — browse Polymarket/Kalshi prediction markets", type: 'dim' },
  { text: '', type: 'dim' },
  { text: '  3. PARTICIPATE', type: 'system' },
  { text: "     'send' — transmit a message across radio networks", type: 'dim' },
  { text: "     'vote' — upvote/downvote agents (builds reputation)", type: 'dim' },
  { text: "     'predict' — bet on market outcomes (earn oracle rep)", type: 'dim' },
  { text: "     'gates' — join reputation-gated communities", type: 'dim' },
  { text: '', type: 'dim' },
  { text: '  4. THE RULES', type: 'system' },
  { text: '     Every action is recorded on the Infonet. Your reputation', type: 'dim' },
  { text: '     determines what you can do. Spam = downvotes = invisible.', type: 'dim' },
  { text: '     No admins. No mods. The math decides.', type: 'dim' },
  { text: '', type: 'dim' },
];

type SearchRecord = Record<string, unknown>;

function asSearchRecords(value: unknown): SearchRecord[] {
  return Array.isArray(value)
    ? value.filter((item): item is SearchRecord => Boolean(item && typeof item === 'object'))
    : [];
}

function pickRecordText(record: SearchRecord, keys: string[]): string {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return '';
}

function pickRecordNumber(record: SearchRecord, keys: string[]): number | null {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === 'number' && Number.isFinite(value)) return value;
    if (typeof value === 'string' && value.trim()) {
      const parsed = Number(value);
      if (Number.isFinite(parsed)) return parsed;
    }
  }
  return null;
}

function recordMatchesQuery(record: SearchRecord, query: string, preferredKeys: string[] = []): boolean {
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  const haystack = [
    ...preferredKeys.map((key) => String(record[key] ?? '')),
    ...Object.values(record).map((value) =>
      typeof value === 'string' || typeof value === 'number' ? String(value) : '',
    ),
  ]
    .join(' ')
    .toLowerCase();
  return haystack.includes(needle);
}

function formatLatLng(record: SearchRecord): string {
  const lat = pickRecordNumber(record, ['lat', 'latitude']);
  const lng = pickRecordNumber(record, ['lng', 'lon', 'longitude']);
  if (lat == null || lng == null) return 'coords n/a';
  return `${lat.toFixed(2)}, ${lng.toFixed(2)}`;
}

export default function MeshTerminal({ isOpen, launchToken = 0, onClose, onDmCount, onSettingsClick }: Props) {
  useEffect(() => {
    void migrateLegacyNodeIds().catch((err) => {
      console.warn('[mesh] legacy node-id migration failed in MeshTerminal', err);
    });
  }, []);

  const [lines, setLines] = useState<TermLine[]>([...WELCOME]);
  const [input, setInput] = useState('');
  const [history, setHistory] = useState<string[]>([]);
  const [histIdx, setHistIdx] = useState(-1);
  const [busy, setBusy] = useState(false);
  const [hasBooted, setHasBooted] = useState(false);
  const [minimized, setMinimized] = useState(false);
  const [surfacePanel, setSurfacePanel] = useState<
    'home' | 'help' | 'apps' | 'mesh' | 'gates' | 'markets' | 'inbox' | 'dossier'
  >('home');
  const [gateCatalog, setGateCatalog] = useState<GateSummary[]>([]);
  const [gateCatalogLoading, setGateCatalogLoading] = useState(false);
  const [expandedGateId, setExpandedGateId] = useState<string | null>(null);
  const [expandedGateDetail, setExpandedGateDetail] = useState<GateDetailRecord | null>(null);
  const [expandedGateKey, setExpandedGateKey] = useState<GateKeyStatusRecord | null>(null);
  const [expandedGateMessages, setExpandedGateMessages] = useState<GateThreadPreview[]>([]);
  const [expandedGateLoading, setExpandedGateLoading] = useState<string | null>(null);
  const [activeGateComposeId, setActiveGateComposeId] = useState<string | null>(null);
  const [gateReplyTarget, setGateReplyTarget] = useState<string | null>(null);
  const [gateAccessPromptOpen, setGateAccessPromptOpen] = useState(false);
  const [gateAccessGranted, setGateAccessGranted] = useState(false);
  const [pendingGateCommand, setPendingGateCommand] = useState<string | null>(null);
  const [privateLanePromptOpen, setPrivateLanePromptOpen] = useState(false);
  const [privateLanePromptMode, setPrivateLanePromptMode] = useState<'enter' | 'activate'>(
    'activate',
  );
  const [privateLanePromptBusy, setPrivateLanePromptBusy] = useState(false);
  const [privateLanePromptStatus, setPrivateLanePromptStatus] = useState<{
    type: 'ok' | 'err' | 'dim';
    text: string;
  } | null>(null);
  const [surfaceMarkets, setSurfaceMarkets] = useState<SearchRecord[]>([]);
  const [surfaceMarketsLoading, setSurfaceMarketsLoading] = useState(false);
  const [expandedMarketIndex, setExpandedMarketIndex] = useState<number | null>(null);
  const [surfaceInbox, setSurfaceInbox] = useState<InboxPreviewRecord[]>([]);
  const [surfaceInboxLoading, setSurfaceInboxLoading] = useState(false);
  const [surfaceMeshCounts, setSurfaceMeshCounts] = useState<Record<string, number>>({});
  const [surfaceMeshLoading, setSurfaceMeshLoading] = useState(false);
  // Interactive send flow
  const [sendStep, setSendStep] = useState<null | 'dest' | 'msg'>(null);
  const [sendDest, setSendDest] = useState('');
  // Interactive DM flow
  const [dmStep, setDmStep] = useState<null | 'dest' | 'msg'>(null);
  const [dmDest, setDmDest] = useState('');
  // Sovereignty / identity
  const [sovereigntyPending, setSovereigntyPending] = useState(false);
  const [nodeIdentity, setNodeIdentity] = useState<NodeIdentity | null>(null);
  const [voteDirections, setVoteDirections] = useState<Record<string, 1 | -1>>({});
  const [, setContactsRevision] = useState(0);
  const [wormholeSecureRequired, setWormholeSecureRequired] = useState(false);
  const [wormholeReadyState, setWormholeReadyState] = useState(false);
  const [anonymousModeEnabled, setAnonymousModeEnabled] = useState(false);
  const [anonymousModeReady, setAnonymousModeReady] = useState(false);
  const [infonetNodeStatus, setInfonetNodeStatus] = useState<InfonetNodeStatusSnapshot | null>(null);
  const [infonetNodeStatusError, setInfonetNodeStatusError] = useState('');
  // Meshtastic region
  const [meshRegion, setMeshRegion] = useState('US');
  const [meshRoots, setMeshRoots] = useState<string[]>([...DEFAULT_MESH_ROOTS]);

  // Dragging state
  const [pos, setPos] = useState({ x: 0, y: 0 });
  const [centered, setCentered] = useState(true);
  const dragRef = useRef<{ startX: number; startY: number; origX: number; origY: number } | null>(
    null,
  );

  // Resize state
  const [size, setSize] = useState(DEFAULT_TERMINAL_SIZE);
  const resizeRef = useRef<{
    startX: number;
    startY: number;
    origW: number;
    origH: number;
    origX: number;
    origY: number;
    edge: string;
  } | null>(null);

  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const windowRef = useRef<HTMLDivElement>(null);
  const resetScrollToTopRef = useRef(false);
  const runQuickCommandRef = useRef<(command: string) => void>(() => {});

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const saved = window.localStorage.getItem('sb_terminal_surface');
    if (
      saved === 'help' ||
      saved === 'apps' ||
      saved === 'mesh' ||
      saved === 'markets' ||
      saved === 'inbox' ||
      saved === 'dossier'
    ) {
      setSurfacePanel(saved);
    } else if (saved === 'gates') {
      setSurfacePanel('home');
    }
  }, []);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    window.localStorage.setItem('sb_terminal_surface', surfacePanel);
  }, [surfacePanel]);

  useEffect(() => {
    if (scrollRef.current) {
      if (resetScrollToTopRef.current) {
        scrollRef.current.scrollTop = 0;
        resetScrollToTopRef.current = false;
      } else {
        scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
      }
    }
  }, [lines]);

  useEffect(() => {
    if (isOpen && inputRef.current) {
      setTimeout(() => inputRef.current?.focus(), 100);
    }
    if (isOpen) {
      setMinimized(false);
      setCentered(true);
      setPos({ x: 0, y: 0 });
      setSize(DEFAULT_TERMINAL_SIZE);
      resetScrollToTopRef.current = true;
    }
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen || launchToken <= 0) return;
    setMinimized(false);
    setCentered(true);
    setPos({ x: 0, y: 0 });
    resetScrollToTopRef.current = true;
    setTimeout(() => inputRef.current?.focus(), 50);
  }, [isOpen, launchToken]);

  const refreshPrivateLaneRuntime = useCallback(async () => {
    try {
      const [settings, status] = await Promise.all([
        fetchWormholeSettings(true),
        fetchWormholeStatus().catch(() => null),
      ]);
      const secureRequired = Boolean(settings?.enabled);
      const ready = Boolean(status?.ready);
      const anonymousEnabled = Boolean(settings?.anonymous_mode);
      const anonymousReady = Boolean(status?.anonymous_mode_ready);
      setWormholeSecureRequired(secureRequired);
      setAnonymousModeEnabled(anonymousEnabled);
      setWormholeReadyState(ready);
      setAnonymousModeReady(anonymousReady);
      return {
        secureRequired,
        ready,
        anonymousEnabled,
        anonymousReady,
        hasDescriptor: Boolean(getWormholeIdentityDescriptor()?.nodeId),
      };
    } catch {
      setWormholeSecureRequired(false);
      setAnonymousModeEnabled(false);
      setWormholeReadyState(false);
      setAnonymousModeReady(false);
      return {
        secureRequired: false,
        ready: false,
        anonymousEnabled: false,
        anonymousReady: false,
        hasDescriptor: Boolean(getWormholeIdentityDescriptor()?.nodeId),
      };
    }
  }, []);

  const openPrivateLanePrompt = useCallback(async () => {
    const runtime = await refreshPrivateLaneRuntime();
    setPrivateLanePromptMode(
      runtime.ready || runtime.secureRequired || runtime.hasDescriptor ? 'enter' : 'activate',
    );
    setPrivateLanePromptStatus(null);
    setPrivateLanePromptOpen(true);
  }, [refreshPrivateLaneRuntime]);

  useEffect(() => {
    if (!isOpen || launchToken <= 0) return;
    let cancelled = false;

    const preparePrompt = async () => {
      const runtime = await refreshPrivateLaneRuntime();
      if (cancelled) return;
      setPrivateLanePromptMode(
        runtime.ready || runtime.secureRequired || runtime.hasDescriptor ? 'enter' : 'activate',
      );
      setPrivateLanePromptStatus(null);
      setPrivateLanePromptOpen(true);
    };

    void preparePrompt();
    return () => {
      cancelled = true;
    };
  }, [isOpen, launchToken, refreshPrivateLaneRuntime]);

  useEffect(() => {
    if (!isOpen) return;
    let cancelled = false;

    const refreshSecurityState = async () => {
      const runtime = await refreshPrivateLaneRuntime();
      if (cancelled) return;
      setWormholeSecureRequired(runtime.secureRequired);
      setAnonymousModeEnabled(runtime.anonymousEnabled);
      setWormholeReadyState(runtime.ready);
      setAnonymousModeReady(runtime.anonymousReady);
    };

    refreshSecurityState();
    const interval = setInterval(refreshSecurityState, 5000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [isOpen, refreshPrivateLaneRuntime]);

  useEffect(() => {
    if (!isOpen) return;
    let cancelled = false;

    const refreshNodeRuntime = async () => {
      try {
        const snapshot = await fetchInfonetNodeStatusSnapshot(true);
        if (cancelled) return;
        setInfonetNodeStatus(snapshot);
        setInfonetNodeStatusError('');
      } catch (error) {
        if (cancelled) return;
        const message =
          typeof error === 'object' && error !== null && 'message' in error
            ? String((error as { message?: string }).message || '')
            : '';
        setInfonetNodeStatusError(message || 'node runtime unavailable');
      }
    };

    void refreshNodeRuntime();
    const interval = window.setInterval(() => {
      void refreshNodeRuntime();
    }, 15000);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen || surfacePanel !== 'gates') return;
    let cancelled = false;

    const loadGateCatalog = async () => {
      setGateCatalogLoading(true);
      try {
        const res = await fetch(`${API}/api/mesh/gate/list`);
        const data = await res.json();
        if (cancelled) return;
        setGateCatalog(Array.isArray(data.gates) ? data.gates : []);
      } catch {
        if (!cancelled) setGateCatalog([]);
      } finally {
        if (!cancelled) setGateCatalogLoading(false);
      }
    };

    loadGateCatalog();
    return () => {
      cancelled = true;
    };
  }, [isOpen, surfacePanel, meshRegion]);

  useEffect(() => {
    if (!isOpen || surfacePanel !== 'markets') return;
    let cancelled = false;

    const loadMarkets = async () => {
      setSurfaceMarketsLoading(true);
      try {
        const res = await fetch(`${API}/api/mesh/oracle/markets`);
        const data = await res.json();
        if (cancelled) return;
        const markets = asSearchRecords(
          Array.isArray(data.markets)
            ? data.markets
            : Object.values((data.categories || {}) as Record<string, unknown>).flatMap((items) =>
                Array.isArray(items) ? items : [],
              ),
        );
        setSurfaceMarkets(markets.slice(0, 9));
      } catch {
        if (!cancelled) setSurfaceMarkets([]);
      } finally {
        if (!cancelled) setSurfaceMarketsLoading(false);
      }
    };

    loadMarkets();
    return () => {
      cancelled = true;
    };
  }, [isOpen, surfacePanel, meshRegion]);

  useEffect(() => {
    if (!isOpen || surfacePanel !== 'mesh') return;
    let cancelled = false;

    const loadMeshSurface = async () => {
      setSurfaceMeshLoading(true);
      try {
        const res = await fetch(`${API}/api/mesh/channels`);
        const data = await res.json();
        if (cancelled) return;
        const counts: Record<string, number> = {};
        const knownRoots = Array.isArray(data.known_roots) ? data.known_roots : [];
        Object.entries((data.roots || {}) as Record<string, { nodes?: number }>).forEach(
          ([root, entry]) => {
            counts[root] = Number(entry?.nodes || 0);
          },
        );
        const roots = sortMeshRoots(
          [...DEFAULT_MESH_ROOTS, ...knownRoots, ...Object.keys(counts), meshRegion],
          counts,
          meshRegion,
        );
        setMeshRoots(roots);
        setSurfaceMeshCounts(counts);
      } catch {
        if (!cancelled) setSurfaceMeshCounts({});
      } finally {
        if (!cancelled) setSurfaceMeshLoading(false);
      }
    };

    loadMeshSurface();
    return () => {
      cancelled = true;
    };
  }, [isOpen, surfacePanel, meshRegion]);

  useEffect(() => {
    if (!isOpen || surfacePanel !== 'inbox') return;
    let cancelled = false;

    const loadInboxSurface = async () => {
      if (!nodeIdentity || !hasSovereignty()) {
        setSurfaceInbox([]);
        return;
      }
      setSurfaceInboxLoading(true);
      try {
        const claims = await buildMailboxClaims(getContacts());
        const data = await pollDmMailboxes(API, nodeIdentity, claims);
        if (cancelled) return;
        const msgs = Array.isArray(data.messages) ? data.messages : [];
        const previews: InboxPreviewRecord[] = [];
        for (const message of msgs.slice(0, 6)) {
          const ageMin = Math.floor((Date.now() / 1000 - message.timestamp) / 60);
          const age =
            ageMin < 60 ? `${ageMin}m ago` : `${Math.floor(ageMin / 60)}h ago`;
          try {
            const contacts = getContacts();
            let senderDH = contacts[message.sender_id]?.dhPubKey;
            if (!senderDH) {
              const keyRes = await fetch(
                `${API}/api/mesh/dm/pubkey?agent_id=${encodeURIComponent(message.sender_id)}`,
              );
              const keyData = await keyRes.json();
              if (keyData.ok && keyData.dh_pub_key) {
                senderDH = keyData.dh_pub_key as string;
                addContact(message.sender_id, senderDH, undefined, keyData.dh_algo);
              }
            }
            if (!senderDH) {
              previews.push({
                sender: message.sender_id,
                age,
                text: 'Key unavailable for preview',
                locked: true,
              });
              continue;
            }
            let plaintext = '';
            try {
              plaintext = await ratchetDecryptDM(message.sender_id, message.ciphertext);
            } catch {
              const sharedKey = await deriveSharedKey(senderDH);
              plaintext = await decryptDM(message.ciphertext, sharedKey);
            }
            previews.push({
              sender: message.sender_id,
              age,
              text: plaintext.slice(0, 140),
            });
          } catch {
            previews.push({
              sender: message.sender_id,
              age,
              text: 'Preview unavailable',
              locked: true,
            });
          }
        }
        setSurfaceInbox(previews);
        if (onDmCount) onDmCount(msgs.length);
      } catch {
        if (!cancelled) setSurfaceInbox([]);
      } finally {
        if (!cancelled) setSurfaceInboxLoading(false);
      }
    };

    void loadInboxSurface();
    return () => {
      cancelled = true;
    };
  }, [isOpen, surfacePanel, nodeIdentity, onDmCount]);

  const terminalWriteLockReason = useMemo(
    () =>
      getMeshTerminalWriteLockReason({
        wormholeRequired: wormholeSecureRequired,
        wormholeReady: wormholeReadyState,
        anonymousMode: anonymousModeEnabled,
        anonymousModeReady: anonymousModeReady,
      }),
    [wormholeSecureRequired, wormholeReadyState, anonymousModeEnabled, anonymousModeReady],
  );
  const publicAgentReady = Boolean(nodeIdentity) && hasSovereignty();
  const privateLaneLabel = wormholeSecureRequired
    ? wormholeReadyState
      ? 'EXPERIMENTAL / OBFUSCATED'
      : 'LOCKED'
    : 'OFF / PUBLIC ONLY';
  const privateLaneDetail = wormholeSecureRequired
    ? wormholeReadyState
      ? 'Wormhole is live for encrypted gates and the obfuscated inbox.'
      : 'Wormhole is required for gates and obfuscated inbox, but it is not ready yet.'
    : 'Wormhole is off. Public mesh still works; obfuscated gates and inbox stay locked.';
  const nodeModeLabel = formatNodeMode(infonetNodeStatus?.node_mode);
  const nodeBootstrapLabel = describeBootstrapState(infonetNodeStatus);
  const nodeSyncLabel = describeSyncOutcome(infonetNodeStatus);

  // Re-focus input when command finishes (busy → false)
  useEffect(() => {
    if (!busy && isOpen) {
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [busy, isOpen]);

  // Auto-run status on first open
  useEffect(() => {
    if (isOpen && !hasBooted) {
      setHasBooted(true);
      (async () => {
        const identity = getNodeIdentity();
        const isConnected = identity && hasSovereignty();
        const bootLines: TermLine[] = [];
        let bootPrivateLaneLabel = 'OFF / PUBLIC ONLY';
        let bootPrivateLaneDetail =
          'Wormhole is off. Public mesh works; encrypted gates and obfuscated inbox stay locked.';

        // 1. Always show network status first
        bootLines.push(
          { text: '  Live networks:', type: 'dim' as const },
          { text: '    APRS-IS      Amateur radio operators worldwide', type: 'output' as const },
          { text: '    Meshtastic   LoRa mesh network (off-grid comms)', type: 'output' as const },
          { text: '    JS8Call      HF weak-signal digital mode', type: 'output' as const },
          { text: '    Infonet      ShadowBroker decentralized protocol', type: 'system' as const },
          { text: '', type: 'dim' as const },
        );

        try {
          const [settings, wormholeStatus] = await Promise.all([
            fetchWormholeSettings(),
            fetchWormholeStatus().catch(() => null),
          ]);
          const wormholeOn = Boolean(settings?.enabled);
          const wormholeReady = Boolean(wormholeStatus?.ready);
          const rnsReady = Boolean(wormholeStatus?.rns_ready);
          bootPrivateLaneLabel = !wormholeOn
            ? 'OFF / PUBLIC ONLY'
            : wormholeReady && rnsReady
              ? 'OBFUSCATED / STRONG'
              : 'EXPERIMENTAL / OBFUSCATED';
          bootPrivateLaneDetail = !wormholeOn
            ? 'Wormhole is off. Public mesh works; encrypted gates and obfuscated inbox stay locked.'
            : wormholeReady && rnsReady
              ? 'Wormhole and Reticulum are both ready for the strongest current obfuscated lane.'
              : wormholeReady
                ? 'Wormhole is live for encrypted gates and the obfuscated inbox while stronger transport warms.'
                : 'Wormhole is required for gates and obfuscated inbox, but it is not ready yet.';
        } catch {
          /* ignore */
        }
        bootLines.push(
          {
            text: `  Public mesh lane: ${isConnected ? `PUBLIC AGENT ${identity.nodeId}` : 'NO PUBLIC AGENT YET'}`,
            type: 'system' as const,
          },
          { text: `  Wormhole obfuscated lane: ${bootPrivateLaneLabel}`, type: 'system' as const },
          { text: `  ${bootPrivateLaneDetail}`, type: 'dim' as const },
          {
            text: '  Public mesh uses your Agent identity. Gates and the obfuscated inbox require Wormhole.',
            type: 'dim' as const,
          },
          { text: '', type: 'dim' as const },
        );

        // 2. Fetch live status
        let backendOk = false;
        try {
          const res = await fetch(`${API}/api/mesh/status`);
          const data = (await res.json()) as MeshStatusResponse;
          backendOk = true;
          const aprs = Number(data.signal_counts?.aprs || 0);
          const mesh = Number(data.signal_counts?.meshtastic || 0);
          const js8 = Number(data.signal_counts?.js8call || 0);
          const total = Number(data.signal_counts?.total || aprs + mesh + js8);
          if (total > 0) {
            bootLines.push(
              { text: `  Connected. ${total} active signals:`, type: 'system' as const },
              {
                text: `    APRS ${aprs} | Meshtastic ${mesh} | JS8Call ${js8}`,
                type: 'output' as const,
              },
            );
          } else {
            bootLines.push({ text: '  Connected. Bridges warming up...', type: 'system' as const });
          }
        } catch {
          bootLines.push({
            text: '  Could not reach backend. Is it running?',
            type: 'error' as const,
          });
        }

        // 3. Fetch Infonet status
        if (backendOk) {
          try {
            const data = await fetchInfonetNodeStatusSnapshot(true);
            setInfonetNodeStatus(data);
            setInfonetNodeStatusError('');
            bootLines.push({
              text: `  Infonet: ${data.network_id || 'sb-testnet-0'} | ${data.total_events ?? 0} events | ${data.known_nodes ?? 0} known nodes`,
              type: 'system' as const,
            });
            bootLines.push({
              text: `  Node mode: ${formatNodeMode(data.node_mode)} | ${Number(data.bootstrap?.sync_peer_count || 0)} sync peers | ${Number(data.bootstrap?.push_peer_count || 0)} push peers`,
              type: 'system' as const,
            });
            bootLines.push({
              text: `  Bootstrap: ${describeBootstrapState(data)}`,
              type: data.bootstrap?.last_bootstrap_error ? 'error' : ('dim' as const),
            });
            bootLines.push({
              text: `  Sync loop: ${describeSyncOutcome(data)}`,
              type: 'dim' as const,
            });
          } catch {
            setInfonetNodeStatusError('node runtime unavailable');
            bootLines.push({ text: '  Infonet: offline', type: 'dim' as const });
          }
        }

        bootLines.push({ text: '', type: 'dim' as const });

        // 4. Agent identity — connected vs not
        if (isConnected) {
          // Ensure DH keys exist (backfill for pre-DM users)
          let dhPub = getDHPubKey();
          if (!dhPub) {
            try {
              dhPub = await generateDHKeys();
            } catch (err) {
              console.error('[mesh] DM key bootstrap failed during terminal init', err);
              bootLines.push(
                {
                  text: '  DM obfuscated inbox degraded: unable to generate local DH keys.',
                  type: 'error' as const,
                },
                {
                  text: '  Encrypted DM features may be unavailable until browser storage access is restored.',
                  type: 'dim' as const,
                },
                { text: '', type: 'dim' as const },
              );
            }
          }
          // Register DH key with backend
          if (backendOk && dhPub) {
            try {
              await ensureRegisteredDmKey(API, identity, { force: true });
            } catch {
              /* non-critical */
            }
          }
          bootLines.push(
            { text: `  Public Agent: ${identity.nodeId}`, type: 'header' as const },
            { text: '  Status: ACTIVE for public mesh and perimeter comms', type: 'system' as const },
            { text: '', type: 'dim' as const },
            { text: '  Commands:', type: 'system' as const },
            { text: '    signals    Live radio intercepts', type: 'output' as const },
            { text: '    apps       Terminal intel surfaces', type: 'output' as const },
            { text: '    send       Transmit a signed message', type: 'output' as const },
            { text: '    dm         Encrypted private messages', type: 'output' as const },
            { text: '    dossier    Multi-source brief by name/place/org', type: 'output' as const },
            {
              text: '    markets    Prediction markets (Polymarket/Kalshi)',
              type: 'output' as const,
            },
            { text: '    gates      Community channels', type: 'output' as const },
            { text: '    help       All commands', type: 'output' as const },
            { text: '', type: 'dim' as const },
          );
        } else {
          // Show sovereignty declaration inline
          bootLines.push(...SOVEREIGNTY_DECLARATION);
          setSovereigntyPending(true);
        }

        setLines((prev) => [...prev, ...bootLines]);
      })();
    }
  }, [isOpen, hasBooted]);

  // Load existing identity on mount
  useEffect(() => {
    const existing = getNodeIdentity();
    if (existing) setNodeIdentity(existing);
    void hydrateWormholeContacts()
      .then(() => {
        setContactsRevision((value) => value + 1);
      })
      .catch((err) => {
        console.warn('[mesh] contact hydration failed in MeshTerminal', err);
      });
  }, []);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const refreshIdentity = () => {
      const next = getNodeIdentity();
      setNodeIdentity((prev) => {
        const prevId = prev?.nodeId || '';
        const nextId = next?.nodeId || '';
        const prevKey = prev?.publicKey || '';
        const nextKey = next?.publicKey || '';
        return prevId === nextId && prevKey === nextKey ? prev : next;
      });
      void hydrateWormholeContacts(true)
        .then(() => {
          setContactsRevision((value) => value + 1);
        })
        .catch((err) => {
          console.warn('[mesh] contact refresh failed in MeshTerminal', err);
        });
    };
    window.addEventListener('sb:identity-state-changed', refreshIdentity);
    window.addEventListener('storage', refreshIdentity);
    window.addEventListener('focus', refreshIdentity);
    return () => {
      window.removeEventListener('sb:identity-state-changed', refreshIdentity);
      window.removeEventListener('storage', refreshIdentity);
      window.removeEventListener('focus', refreshIdentity);
    };
  }, []);

  // DM unread count polling (every 15s when connected)
  useEffect(() => {
    if (!nodeIdentity || !hasSovereignty() || !getDMNotify()) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const claims = await buildMailboxClaims(getContacts());
        const data = await countDmMailboxes(API, nodeIdentity, claims);
        if (!cancelled && onDmCount) onDmCount(data.count || 0);
      } catch {
        /* ignore */
      }
    };
    poll(); // immediate
    const iv = setInterval(poll, 15000);
    return () => {
      cancelled = true;
      clearInterval(iv);
    };
  }, [nodeIdentity, onDmCount]);

  // Escape to close
  useEffect(() => {
    if (!isOpen) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [isOpen, onClose]);

  // ─── Drag handling ─────────────────────────────────────────

  const onDragStart = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      if (centered && windowRef.current) {
        // Convert from centered to absolute positioning
        const rect = windowRef.current.getBoundingClientRect();
        setPos({ x: rect.left, y: rect.top });
        setCentered(false);
      }
      dragRef.current = {
        startX: e.clientX,
        startY: e.clientY,
        origX: centered ? windowRef.current?.getBoundingClientRect().left || 0 : pos.x,
        origY: centered ? windowRef.current?.getBoundingClientRect().top || 0 : pos.y,
      };

      const onMove = (ev: MouseEvent) => {
        if (!dragRef.current) return;
        setPos({
          x: dragRef.current.origX + (ev.clientX - dragRef.current.startX),
          y: dragRef.current.origY + (ev.clientY - dragRef.current.startY),
        });
        setCentered(false);
      };
      const onUp = () => {
        dragRef.current = null;
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
      };
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    },
    [centered, pos],
  );

  // ─── Resize handling ────────────────────────────────────────

  const onResizeStart = useCallback(
    (e: React.MouseEvent, edge: string) => {
      e.preventDefault();
      e.stopPropagation();
      // Convert from centered to absolute before resizing
      let curX = pos.x,
        curY = pos.y;
      if (centered && windowRef.current) {
        const rect = windowRef.current.getBoundingClientRect();
        curX = rect.left;
        curY = rect.top;
        setPos({ x: curX, y: curY });
        setCentered(false);
      }
      const rect = windowRef.current?.getBoundingClientRect();
      resizeRef.current = {
        startX: e.clientX,
        startY: e.clientY,
        origW: rect?.width || size.w,
        origH: rect?.height || size.h,
        origX: curX,
        origY: curY,
        edge,
      };
      const onMove = (ev: MouseEvent) => {
        if (!resizeRef.current) return;
        const dx = ev.clientX - resizeRef.current.startX;
        const dy = ev.clientY - resizeRef.current.startY;
        const { edge: ed, origW, origH, origX, origY } = resizeRef.current;
        let newW = origW,
          newH = origH,
          newX = origX,
          newY = origY;
        // East: drag right edge outward
        if (ed.includes('e')) newW = Math.max(360, origW + dx);
        // West: drag left edge — shrinks width, moves position right
        if (ed.includes('w')) {
          newW = Math.max(360, origW - dx);
          newX = origX + (origW - newW);
        }
        // South: drag bottom edge down
        if (ed.includes('s')) newH = Math.max(250, origH + dy);
        // North: drag top edge — shrinks height, moves position down
        if (ed.includes('n')) {
          newH = Math.max(250, origH - dy);
          newY = origY + (origH - newH);
        }
        setSize({ w: newW, h: newH });
        setPos({ x: newX, y: newY });
        setCentered(false);
      };
      const onUp = () => {
        resizeRef.current = null;
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
      };
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    },
    [centered, size, pos],
  );

  // ─── Command helpers ───────────────────────────────────────

  const addLines = useCallback(
    (newLines: TermLine[]) => setLines((prev) => [...prev, ...newLines]),
    [],
  );
  const addOutput = useCallback((text: string) => addLines([{ text, type: 'output' }]), [addLines]);
  const addError = useCallback(
    (text: string) => addLines([{ text: `  ${text}`, type: 'error' }]),
    [addLines],
  );
  const addSystem = useCallback((text: string) => addLines([{ text, type: 'system' }]), [addLines]);

  const getInfonetHeadHistory = useCallback(() => {
    if (typeof window === 'undefined') return [];
    try {
      const raw = getTerminalSensitiveItem(INFONET_HEAD_HISTORY_KEY) || '[]';
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed.filter((v) => typeof v === 'string') : [];
    } catch {
      return [];
    }
  }, []);
  const getInfonetHead = useCallback(
    () => getTerminalSensitiveItem(INFONET_HEAD_KEY),
    [],
  );
  const setInfonetHead = useCallback(
    (head: string) => {
      if (typeof window === 'undefined') return;
      setTerminalSensitiveItem(INFONET_HEAD_KEY, head);
      try {
        const history = getInfonetHeadHistory();
        const next = [head, ...history.filter((h) => h && h !== head)].slice(
        0,
        INFONET_LOCATOR_LIMIT,
      );
      setTerminalSensitiveItem(INFONET_HEAD_HISTORY_KEY, JSON.stringify(next));
      } catch {
        /* ignore */
      }
    },
    [getInfonetHeadHistory],
  );
  const getInfonetLocator = useCallback(() => {
    const head = getInfonetHead();
    const history = getInfonetHeadHistory();
    const merged = [head, ...history].filter(Boolean);
    const unique = Array.from(new Set(merged));
    const genesis = '0'.repeat(64);
    if (!unique.includes(genesis)) unique.push(genesis);
    return unique.slice(0, INFONET_LOCATOR_LIMIT);
  }, [getInfonetHead, getInfonetHeadHistory]);

  const getInfonetPeers = useCallback(() => {
    const envPeers = (process.env.NEXT_PUBLIC_INFONET_PEERS || '')
      .split(',')
      .map((p) => p.trim())
      .filter(Boolean);
    let stored: string[] = [];
    if (typeof window !== 'undefined') {
      try {
        const raw = getTerminalSensitiveItem(INFONET_PEERS_KEY) || '[]';
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) stored = parsed.filter((p) => typeof p === 'string');
      } catch {
        stored = [];
      }
    }
    const merged = [API, ...envPeers, ...stored].filter(Boolean);
    const normalized = merged.map((p) => p.replace(/\/+$/, ''));
    return Array.from(new Set(normalized));
  }, []);

  const setInfonetPeers = useCallback((peers: string[]) => {
    if (typeof window === 'undefined') return;
    const cleaned = peers
      .map((p) => p.trim().replace(/\/+$/, ''))
      .filter(Boolean);
    setTerminalSensitiveItem(INFONET_PEERS_KEY, JSON.stringify(cleaned));
  }, []);

  const cmdStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/mesh/status`);
      const data = (await res.json()) as MeshStatusResponse;
      const aprs = Number(data.signal_counts?.aprs || 0);
      const mesh = Number(data.signal_counts?.meshtastic || 0);
      const js8 = Number(data.signal_counts?.js8call || 0);
      addSystem('');
      addSystem('  NETWORK STATUS');
      addOutput(`    APRS-IS      ${String(aprs).padStart(4)} signals`);
      addOutput(`    Meshtastic   ${String(mesh).padStart(4)} signals`);
      addOutput(`    JS8Call      ${String(js8).padStart(4)} signals`);
      addSystem(
        `    Total        ${String(Number(data.signal_counts?.total || aprs + mesh + js8)).padStart(4)} active`,
      );
      addSystem('');

      // Infonet status
      try {
        const iData = await fetchInfonetNodeStatusSnapshot(true);
        setInfonetNodeStatus(iData);
        setInfonetNodeStatusError('');
        addSystem('  INFONET');
        addOutput(`    Network:     ${iData.network_id || 'sb-testnet-0'}`);
        addOutput(
          `    Events:      ${iData.total_events ?? 0} total | ${iData.known_nodes ?? 0} agents`,
        );
        addOutput(`    Head:        ${iData.head_hash || 'genesis'}`);
        addOutput(`    Valid:       ${iData.valid ? 'YES' : 'NO'}`);
        addLines(buildNodeRuntimeLines(iData));
      } catch {
        setInfonetNodeStatusError('node runtime unavailable');
        addOutput('    Infonet:     offline');
      }
      addSystem('');

      addSystem('  IDENTITY LANES');
      if (nodeIdentity && hasSovereignty()) {
        addOutput(`    Public Agent:   ${nodeIdentity.nodeId}`);
        addOutput('    Public Mesh:    READY');
      } else {
        addLines([
          {
            text: "    Public Agent:   not connected — type 'connect' to create one",
            type: 'dim',
          },
        ]);
      }
      addOutput(`    Wormhole Lane:  ${privateLaneLabel}`);
      addLines([{ text: `    ${privateLaneDetail}`, type: 'dim' }]);
      addSystem('');
    } catch {
      addError('Failed to reach backend');
    }
  }, [addOutput, addError, addSystem, addLines, nodeIdentity, privateLaneDetail, privateLaneLabel]);

  const cmdNode = useCallback(async () => {
    try {
      const data = await fetchInfonetNodeStatusSnapshot(true);
      setInfonetNodeStatus(data);
      setInfonetNodeStatusError('');
      addSystem('');
      addSystem('  PARTICIPANT NODE');
      addOutput(`    Network:     ${data.network_id || 'sb-testnet-0'}`);
      addOutput(`    Head:        ${shortNodeHash(data.head_hash, 18)}`);
      addOutput(`    Valid:       ${data.valid ? 'YES' : 'NO'} — ${data.validation || '?'}`);
      addLines(buildNodeRuntimeLines(data));
    } catch {
      setInfonetNodeStatusError('node runtime unavailable');
      addError('Failed to reach participant-node runtime');
    }
  }, [addError, addLines, addOutput, addSystem]);

  const cmdSignals = useCallback(
    async (n: number = 10) => {
      try {
        const limit = Math.min(Math.max(n, 1), 50);
        const res = await fetch(`${API}/api/mesh/signals?limit=${limit}`);
        const data = await res.json();
        const sigs = Array.isArray(data?.signals) ? data.signals.slice(0, limit) : [];
        if (!sigs.length) {
          addSystem('  No signals in buffer');
          return;
        }
        addSystem('');
        addSystem(`  RECENT SIGNALS (${sigs.length})`);
        for (const s of sigs) {
          const src = (s.source || '?').toUpperCase().padEnd(6);
          const call = (s.callsign || '???').padEnd(12);
          const pos = `${s.lat?.toFixed(2)},${s.lng?.toFixed(2)}`;
          const extra = s.status || s.comment || '';
          addOutput(`    ${src} ${call} ${pos.padEnd(14)} ${extra.slice(0, 30)}`);
        }
        addSystem('');
      } catch {
        addError('Failed to fetch signals');
      }
    },
    [addOutput, addError, addSystem],
  );

  const cmdApps = useCallback(() => {
    addSystem('');
    addSystem('  TERMINAL SURFACES');
    addOutput('    INFONET      Gates, messages, sync, ledger, event lookups');
    addOutput('    MESH         Meshtastic region watch + public mesh send');
    addOutput('    DEAD DROP    Encrypted DM lane and contact controls');
    addOutput('    ORACLE       Markets, predicts, stakes, profiles');
    addOutput('    INTEL        News, dossiers, place search, jet search, Shodan');
    addOutput('    UTILITIES    KiwiSDR nearest, routing audit, identity tools');
    addSystem('');
    addLines([
      {
        text: "  Try: gate infonet | messages infonet | news taiwan | dossier musk | jet adelson | shodan nginx",
        type: 'dim',
      },
    ]);
    addSystem('');
  }, [addLines, addOutput, addSystem]);

  const cmdNews = useCallback(
    async (query: string, limit: number = 8) => {
      try {
        const res = await fetch(`${API}/api/live-data/slow`);
        const data = await res.json();
        const news = asSearchRecords(data?.news);
        const hits = news
          .filter((item) =>
            recordMatchesQuery(item, query, ['title', 'summary', 'source', 'description', 'place']),
          )
          .slice(0, Math.max(1, Math.min(limit, 12)));
        addSystem('');
        addSystem(query ? `  NEWS MATCHES: ${query}` : '  LATEST NEWS');
        if (!hits.length) {
          addSystem('    No headline matches.');
        } else {
          for (const item of hits) {
            const title =
              pickRecordText(item, ['title', 'headline', 'name']) || 'Untitled headline';
            const source = pickRecordText(item, ['source', 'publisher']) || 'unknown';
            const place = pickRecordText(item, ['place', 'region', 'country']);
            addOutput(`    ${title.slice(0, 78)}`);
            addLines([
              {
                text: `      ${source}${place ? ` · ${place}` : ''}`,
                type: 'dim',
              },
            ]);
          }
        }
        addSystem('');
      } catch {
        addError('Failed to fetch news');
      }
    },
    [addError, addLines, addOutput, addSystem],
  );

  const cmdJets = useCallback(
    async (query: string) => {
      if (!query.trim()) {
        addError('Usage: jet <name|tail|operator|callsign>');
        return;
      }
      try {
        const res = await fetch(`${API}/api/live-data/fast`);
        const data = await res.json();
        const sources = [
          { label: 'PRIVATE JET', items: asSearchRecords(data?.private_jets) },
          { label: 'PRIVATE FLIGHT', items: asSearchRecords(data?.private_flights) },
          { label: 'TRACKED FLIGHT', items: asSearchRecords(data?.tracked_flights) },
        ];
        const hits = sources.flatMap((source) =>
          source.items
            .filter((item) =>
              recordMatchesQuery(item, query, [
                'owner',
                'operator',
                'registration',
                'tail',
                'callsign',
                'icao24',
                'name',
                'model',
                'aircraft_type',
              ]),
            )
            .slice(0, 6)
            .map((item) => ({ source: source.label, item })),
        );
        addSystem('');
        addSystem(`  FLIGHT / JET MATCHES: ${query}`);
        if (!hits.length) {
          addSystem('    No matching private aviation hits.');
        } else {
          for (const hit of hits.slice(0, 10)) {
            const title =
              pickRecordText(hit.item, ['registration', 'tail', 'callsign', 'icao24', 'name']) ||
              'unknown-airframe';
            const owner = pickRecordText(hit.item, ['owner', 'operator', 'category', 'model']);
            addOutput(`    ${hit.source.padEnd(14)} ${title}`);
            addLines([
              {
                text: `      ${owner || 'owner/operator n/a'} · ${formatLatLng(hit.item)}`,
                type: 'dim',
              },
            ]);
          }
        }
        addSystem('');
      } catch {
        addError('Failed to search flight data');
      }
    },
    [addError, addLines, addOutput, addSystem],
  );

  const cmdPlaces = useCallback(
    async (query: string) => {
      if (!query.trim()) {
        addError('Usage: place <name|city|country|site>');
        return;
      }
      try {
        const res = await fetch(`${API}/api/live-data/slow`);
        const data = await res.json();
        const sources = [
          { label: 'AIRPORT', items: asSearchRecords(data?.airports) },
          { label: 'BASE', items: asSearchRecords(data?.military_bases) },
          { label: 'DC', items: asSearchRecords(data?.datacenters) },
          { label: 'POWER', items: asSearchRecords(data?.power_plants) },
          { label: 'QUAKE', items: asSearchRecords(data?.earthquakes) },
          { label: 'VOLCANO', items: asSearchRecords(data?.volcanoes) },
        ];
        const hits = sources.flatMap((source) =>
          source.items
            .filter((item) =>
              recordMatchesQuery(item, query, [
                'name',
                'title',
                'place',
                'city',
                'country',
                'state',
                'icao',
                'iata',
                'operator',
              ]),
            )
            .slice(0, 5)
            .map((item) => ({ source: source.label, item })),
        );
        addSystem('');
        addSystem(`  PLACE MATCHES: ${query}`);
        if (!hits.length) {
          addSystem('    No matching place records.');
        } else {
          for (const hit of hits.slice(0, 12)) {
            const title =
              pickRecordText(hit.item, ['name', 'title', 'place', 'city']) || 'unknown-site';
            const sub = pickRecordText(hit.item, ['country', 'state', 'icao', 'iata', 'type']);
            addOutput(`    ${hit.source.padEnd(8)} ${title}`);
            addLines([
              {
                text: `      ${sub || 'detail n/a'} · ${formatLatLng(hit.item)}`,
                type: 'dim',
              },
            ]);
          }
        }
        addSystem('');
      } catch {
        addError('Failed to search place data');
      }
    },
    [addError, addLines, addOutput, addSystem],
  );

  const cmdDossier = useCallback(
    async (query: string) => {
      if (!query.trim()) {
        addError('Usage: dossier <name|place|org>');
        return;
      }
      try {
        const [slowRes, fastRes, marketRes, signalRes] = await Promise.all([
          fetch(`${API}/api/live-data/slow`),
          fetch(`${API}/api/live-data/fast`),
          fetch(`${API}/api/mesh/oracle/search?q=${encodeURIComponent(query)}&limit=5`),
          fetch(`${API}/api/mesh/signals?limit=80`),
        ]);
        const [slow, fast, markets, signals] = await Promise.all([
          slowRes.json(),
          fastRes.json(),
          marketRes.json().catch(() => ({})),
          signalRes.json().catch(() => ({})),
        ]);

        const newsHits = asSearchRecords(slow?.news).filter((item) =>
          recordMatchesQuery(item, query, ['title', 'summary', 'source', 'description', 'place']),
        );
        const jetHits = [
          ...asSearchRecords(fast?.private_jets),
          ...asSearchRecords(fast?.private_flights),
          ...asSearchRecords(fast?.tracked_flights),
        ].filter((item) =>
          recordMatchesQuery(item, query, [
            'owner',
            'operator',
            'registration',
            'tail',
            'callsign',
            'icao24',
            'name',
            'model',
          ]),
        );
        const placeHits = [
          ...asSearchRecords(slow?.airports),
          ...asSearchRecords(slow?.military_bases),
          ...asSearchRecords(slow?.datacenters),
          ...asSearchRecords(slow?.power_plants),
          ...asSearchRecords(slow?.earthquakes),
          ...asSearchRecords(slow?.volcanoes),
        ].filter((item) =>
          recordMatchesQuery(item, query, [
            'name',
            'title',
            'place',
            'city',
            'country',
            'state',
            'icao',
            'iata',
          ]),
        );
        const signalHits = asSearchRecords(signals?.signals).filter((item) =>
          recordMatchesQuery(item, query, ['callsign', 'status', 'comment', 'source', 'region']),
        );
        const marketHits = asSearchRecords(markets?.markets || markets?.cached || []);

        addSystem('');
        addSystem(`  DOSSIER: ${query}`);
        addOutput(
          `    hits · news:${newsHits.length} places:${placeHits.length} flights:${jetHits.length} markets:${marketHits.length} signals:${signalHits.length}`,
        );

        if (newsHits[0]) {
          addSystem('    HEADLINE');
          addLines([
            {
              text: `      ${pickRecordText(newsHits[0], ['title', 'headline', 'name'])}`,
              type: 'dim',
            },
          ]);
        }
        if (placeHits[0]) {
          addSystem('    PLACE');
          addLines([
            {
              text: `      ${pickRecordText(placeHits[0], ['name', 'title', 'place', 'city'])} · ${formatLatLng(placeHits[0])}`,
              type: 'dim',
            },
          ]);
        }
        if (jetHits[0]) {
          addSystem('    AVIATION');
          addLines([
            {
              text: `      ${pickRecordText(jetHits[0], ['registration', 'tail', 'callsign', 'icao24'])} · ${pickRecordText(jetHits[0], ['owner', 'operator', 'model']) || 'owner/operator n/a'}`,
              type: 'dim',
            },
          ]);
        }
        if (marketHits[0]) {
          addSystem('    MARKET');
          addLines([
            {
              text: `      ${pickRecordText(marketHits[0], ['title', 'question'])}`,
              type: 'dim',
            },
          ]);
        }
        if (signalHits[0]) {
          addSystem('    SIGNAL');
          addLines([
            {
              text: `      ${pickRecordText(signalHits[0], ['callsign', 'source'])} · ${pickRecordText(signalHits[0], ['status', 'comment', 'region']) || 'recent activity'}`,
              type: 'dim',
            },
          ]);
        }
        addSystem('');
      } catch {
        addError('Failed to build dossier');
      }
    },
    [addError, addLines, addOutput, addSystem],
  );

  const cmdShodan = useCallback(
    async (args: string[]) => {
      try {
        if (!args.length) {
          const res = await fetch(`${API}/api/tools/shodan/status`);
          const data = await res.json();
          addSystem('');
          addSystem('  SHODAN');
          addOutput(`    Ready:       ${data.ready ? 'YES' : 'NO'}`);
          addOutput(`    Configured:  ${data.configured ? 'YES' : 'NO'}`);
          if (data.detail) addLines([{ text: `      ${data.detail}`, type: 'dim' }]);
          addSystem('');
          return;
        }
        if (args[0]?.toLowerCase() === 'host') {
          const ip = args[1];
          if (!ip) {
            addError('Usage: shodan host <ip>');
            return;
          }
          const res = await fetch(`${API}/api/tools/shodan/host`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ip, history: false }),
          });
          const data = await res.json();
          if (!res.ok) {
            addError(data.detail || 'Shodan host lookup failed');
            return;
          }
          addSystem('');
          addSystem(`  SHODAN HOST: ${ip}`);
          addOutput(`    Org:         ${data.org || 'unknown'}`);
          addOutput(`    OS:          ${data.os || 'unknown'}`);
          addOutput(`    Ports:       ${Array.isArray(data.ports) ? data.ports.join(', ') : 'n/a'}`);
          addOutput(`    Hostnames:   ${Array.isArray(data.hostnames) ? data.hostnames.join(', ') : 'n/a'}`);
          addSystem('');
          return;
        }
        const query = args.join(' ');
        const res = await fetch(`${API}/api/tools/shodan/search`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ query, page: 1, facets: [] }),
        });
        const data = await res.json();
        if (!res.ok) {
          addError(data.detail || 'Shodan search failed');
          return;
        }
        const matches = asSearchRecords(data.matches);
        addSystem('');
        addSystem(`  SHODAN MATCHES: ${query}`);
        if (!matches.length) {
          addSystem('    No host matches.');
        } else {
          for (const item of matches.slice(0, 8)) {
            addOutput(
              `    ${pickRecordText(item, ['ip_str', 'ip']) || 'unknown-ip'} · ${pickRecordText(item, ['org', 'isp']) || 'unknown org'}`,
            );
            addLines([
              {
                text: `      ${pickRecordText(item, ['product', 'os', 'hostnames']) || 'service detail unavailable'}`,
                type: 'dim',
              },
            ]);
          }
        }
        addSystem('');
      } catch {
        addError('Failed to query Shodan');
      }
    },
    [addError, addLines, addOutput, addSystem],
  );

  const cmdMerkle = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/mesh/infonet/merkle`);
      const data = await res.json();
      addSystem('');
      addSystem('  INFONET MERKLE');
      addOutput(`    Merkle Root: ${data.merkle_root || 'genesis'}`);
      addOutput(`    Head Hash:   ${data.head_hash || 'genesis'}`);
      addOutput(`    Count:       ${data.count ?? 0}`);
      addSystem('');
    } catch {
      addError('Failed to fetch merkle root');
    }
  }, [addOutput, addError, addSystem]);

  const cmdSync = useCallback(
    async (limit: number = 100) => {
      try {
        const locator = getInfonetLocator();
        const peers = getInfonetPeers();
        const strictPrivacy = getPrivacyStrictPreference();
        const shuffled = [...peers].sort(() => Math.random() - 0.5);
        const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
        const requests = shuffled.map(async (peer, idx) => {
          try {
            if (strictPrivacy) {
              const jitter = 50 + Math.floor(Math.random() * 350) + idx * 25;
              await sleep(jitter);
            }
            const res = await fetch(`${peer}/api/mesh/infonet/sync`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ locator, limit, include_proofs: true }),
            });
            const data = await res.json();
            if (data.ok === false) return null;
            return { peer, data };
          } catch {
            return null;
          }
        });

        const responses = (await Promise.all(requests)).filter(
          (r): r is { peer: string; data: InfonetSyncResponse } => Boolean(r),
        );
        const failures = peers.length - responses.length;
        if (responses.length === 0) {
          addError('Sync failed: no peers responded');
          return;
        }

        const forkedResponses = responses.filter((r) => r.data.forked);
        const candidates = responses.filter((r) => !r.data.forked);
        if (candidates.length === 0) {
          addError('Fork detected across all peers — no safe head to follow');
          return;
        }

        const groups = new Map<
          string,
          { count: number; samples: { peer: string; data: InfonetSyncResponse }[] }
        >();
        for (const r of candidates) {
          const key = String(r.data.matched_hash || '');
          const group = groups.get(key) || { count: 0, samples: [] };
          group.count += 1;
          group.samples.push(r);
          groups.set(key, group);
        }
        const quorum = Math.floor(candidates.length / 2) + 1;
        let selectedGroup:
          | { count: number; samples: { peer: string; data: InfonetSyncResponse }[] }
          | null = null;
        for (const group of groups.values()) {
          if (!selectedGroup || group.count > selectedGroup.count) selectedGroup = group;
        }
        if (!selectedGroup || selectedGroup.count < quorum) {
          addError('No majority match on locator — sync aborted');
          return;
        }

        const selected = selectedGroup.samples.reduce((best, cur) =>
          (cur.data.events?.length || 0) > (best.data.events?.length || 0) ? cur : best,
        );
        const data = selected.data;
        const events = data.events || [];
        const matched = data.matched_hash || '';
        const forked = false;
        const proofs = Array.isArray(data.merkle_proofs) ? data.merkle_proofs : [];
        const merkleRoot = data.merkle_root || '';
        const peerUsed = selected.peer;
        let verified = 0;
        let failed = 0;
        let unsigned = 0;
        let merkleVerified = 0;
        let merkleFailed = 0;

        for (const e of events) {
          if (!e.signature || !e.public_key || !e.public_key_algo) {
            unsigned += 1;
            continue;
          }
          if (String(e.event_type || '') === 'gate_message') {
            verified += 1;
            continue;
          }
          const ok = await verifyEventSignature({
            eventType: e.event_type,
            nodeId: e.node_id,
            sequence: e.sequence || 0,
            payload: e.payload || {},
            signature: e.signature,
            publicKey: e.public_key,
            publicKeyAlgo: e.public_key_algo,
          });
          if (ok) verified += 1;
          else failed += 1;
        }

        if (merkleRoot && proofs.length) {
          const proofMap = new Map<string, InfonetMerkleProof>();
          for (const p of proofs) {
            if (p?.leaf) proofMap.set(p.leaf, p);
          }
          for (const e of events) {
            const proof = proofMap.get(e.event_id);
            if (!proof) {
              merkleFailed += 1;
              continue;
            }
            const ok = await verifyMerkleProof(
              String(proof.leaf),
              Number(proof.index ?? 0),
              Array.isArray(proof.proof)
                ? proof.proof.map((h) => ({ hash: h, side: 'left' as const }))
                : [],
              merkleRoot,
            );
            if (ok) merkleVerified += 1;
            else merkleFailed += 1;
          }
        }

        addSystem('');
        addSystem('  INFONET SYNC');
        addOutput(`    Remote Head: ${data.head_hash || 'genesis'}`);
        addOutput(`    Locator:     ${locator[0] ? `${locator[0].slice(0, 16)}...` : 'genesis'}`);
        addOutput(`    Matched:     ${matched ? `${matched.slice(0, 16)}...` : 'none'}`);
        addOutput(`    Forked:      ${forked ? 'YES' : 'NO'}`);
        addOutput(
          `    Peers:       ${peers.length} ok / ${candidates.length} safe / ${forkedResponses.length} forked / ${failures} failed`,
        );
        addOutput(`    Quorum:      ${selectedGroup.count}/${candidates.length} (peer ${peerUsed})`);
        addOutput(`    Pulled:      ${events.length}`);
        addOutput(`    Verified:    ${verified}`);
        addOutput(`    Failed:      ${failed}`);
        addOutput(`    Unsigned:    ${unsigned}`);
        addOutput(
          `    Merkle:      ${
            merkleRoot ? `${merkleRoot.slice(0, 16)}...` : 'n/a'
          } (${merkleVerified} ok / ${merkleFailed} fail)`,
        );

        if (forked) {
          addError('Fork detected — head not advanced');
        } else if (failed === 0 && (merkleFailed === 0 || !merkleRoot) && data.head_hash) {
          setInfonetHead(data.head_hash);
          addOutput(`    Head Saved:  ${data.head_hash.slice(0, 16)}...`);
        } else if (failed > 0) {
          addError('Signature failures detected — head not advanced');
        } else if (merkleFailed > 0) {
          addError('Merkle proof failures detected — head not advanced');
        }
        addSystem('');
      } catch {
        addError('Failed to sync Infonet');
      }
    },
    [addOutput, addError, addSystem, getInfonetLocator, getInfonetPeers, setInfonetHead],
  );

  const cmdRevoke = useCallback(
    async (args: string[]) => {
      if (!nodeIdentity || !hasSovereignty()) {
        addError("Not connected. Type 'connect' to activate your Agent identity.");
        return;
      }
      const DEFAULT_GRACE_HOURS = 48;
      const MAX_GRACE_HOURS = 168;
      let graceHours = DEFAULT_GRACE_HOURS;
      let reason = args.join(' ').trim();
      if (args.length > 0) {
        const last = args[args.length - 1];
        const parsed = Number(last);
        if (Number.isFinite(parsed)) {
          graceHours = Math.max(1, Math.min(MAX_GRACE_HOURS, Math.trunc(parsed)));
          reason = args.slice(0, -1).join(' ').trim();
        }
      }
      if (!reason) reason = 'compromised';

      try {
        const revokedAt = Math.floor(Date.now() / 1000);
        const graceUntil = revokedAt + graceHours * 3600;
        const payload = {
          revoked_public_key: nodeIdentity.publicKey,
          revoked_public_key_algo: getPublicKeyAlgo(),
          revoked_at: revokedAt,
          grace_until: graceUntil,
          reason,
        };
        const v = validateEventPayload('key_revoke', payload);
        if (!v.ok) {
          addError(`Invalid payload: ${v.reason}`);
          return;
        }
        const sequence = nextSequence();
        const signature = await signEvent('key_revoke', nodeIdentity.nodeId, sequence, payload);
        const res = await fetch(`${API}/api/mesh/identity/revoke`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            node_id: nodeIdentity.nodeId,
            public_key: nodeIdentity.publicKey,
            public_key_algo: getPublicKeyAlgo(),
            signature,
            sequence,
            protocol_version: PROTOCOL_VERSION,
            revoked_at: revokedAt,
            grace_until: graceUntil,
            reason,
          }),
        });
        const data = await res.json();
        if (data.ok) {
          addSystem(`  Revocation recorded. Grace window: ${graceHours}h.`);
        } else {
          addError(data.detail || 'Revocation failed');
        }
      } catch {
        addError('Revocation failed');
      }
    },
    [addError, addSystem, nodeIdentity],
  );

  const cmdRotate = useCallback(async () => {
    if (!nodeIdentity || !hasSovereignty()) {
      addError("Not connected. Type 'connect' to activate your Agent identity.");
      return;
    }
    try {
      addSystem('  Generating new identity...');
      const { identity: newIdentity, algo: newAlgo } = await createIdentityCandidate();
      const oldAlgo = getPublicKeyAlgo();
      const timestamp = Math.floor(Date.now() / 1000);

      const claimPayload = {
        old_node_id: nodeIdentity.nodeId,
        old_public_key: nodeIdentity.publicKey,
        old_public_key_algo: oldAlgo,
        new_public_key: newIdentity.publicKey,
        new_public_key_algo: newAlgo,
        timestamp,
      };

      const oldSigPayload = buildSignaturePayload({
        eventType: 'key_rotate',
        nodeId: nodeIdentity.nodeId,
        sequence: 0,
        payload: claimPayload,
      });
      const oldSignature = await signMessage(oldSigPayload, nodeIdentity.privateKey, oldAlgo);

      const fullPayload = { ...claimPayload, old_signature: oldSignature };
      const v = validateEventPayload('key_rotate', fullPayload);
      if (!v.ok) {
        addError(`Invalid payload: ${v.reason}`);
        return;
      }
      const sequence = 1;
      const newSigPayload = buildSignaturePayload({
        eventType: 'key_rotate',
        nodeId: newIdentity.nodeId,
        sequence,
        payload: fullPayload,
      });
      const newSignature = await signMessage(newSigPayload, newIdentity.privateKey, newAlgo);

      const res = await fetch(`${API}/api/mesh/identity/rotate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          old_node_id: nodeIdentity.nodeId,
          old_public_key: nodeIdentity.publicKey,
          old_public_key_algo: oldAlgo,
          old_signature: oldSignature,
          new_node_id: newIdentity.nodeId,
          new_public_key: newIdentity.publicKey,
          new_public_key_algo: newAlgo,
          new_signature: newSignature,
          timestamp,
          sequence,
          protocol_version: PROTOCOL_VERSION,
        }),
      });
      const data = await res.json();
      if (!data.ok) {
        addError(data.detail || 'Rotation failed');
        return;
      }

      persistIdentity(newIdentity, newAlgo, sequence);
      setSequence(sequence);
      setNodeIdentity(newIdentity);
      await generateDHKeys();

      addSystem(`  Identity rotated to ${newIdentity.nodeId}`);
    } catch (err) {
      const msg =
        typeof err === 'object' && err !== null && 'message' in err
          ? String((err as { message?: string }).message)
          : '';
      const dhStorageFailure =
        msg !== 'browser_identity_blocked_secure_mode' &&
        /(indexeddb|browser storage|dh key|storage unavailable)/i.test(msg);
      addError(
        msg === 'browser_identity_blocked_secure_mode'
          ? 'Browser identity rotation is disabled in Wormhole secure mode'
          : dhStorageFailure
            ? 'Identity rotation failed: browser storage unavailable for DH key generation'
            : 'Identity rotation failed',
      );
    }
  }, [addError, addSystem, nodeIdentity]);

  const doSend = useCallback(
    async (dest: string, message: string) => {
      // Must be connected to send
      if (!nodeIdentity || !hasSovereignty()) {
        addError("Not connected. Type 'connect' to activate your Agent identity.");
        return;
      }

      addSystem(`  Signing as ${nodeIdentity.nodeId}...`);
      try {
        const sequence = nextSequence();
        const payload = {
          message,
          destination: dest,
          channel: 'LongFast',
          priority: 'normal',
          ephemeral: false,
        };
        const v = validateEventPayload('message', payload);
        if (!v.ok) {
          addError(`Invalid payload: ${v.reason}`);
          return;
        }
        const signature = await signEvent('message', nodeIdentity.nodeId, sequence, payload);

        addSystem(`  Routing to ${dest}...`);
        const res = await fetch(`${API}/api/mesh/send`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            sender_id: nodeIdentity.nodeId,
            node_id: nodeIdentity.nodeId,
            public_key: nodeIdentity.publicKey,
            public_key_algo: getPublicKeyAlgo(),
            signature: signature,
            destination: dest,
            message: message,
            priority: 'normal',
            ephemeral: false,
            sequence,
            protocol_version: PROTOCOL_VERSION,
          }),
        });
        const data = await res.json();
        if (data.results) {
          for (const r of data.results) {
            addLines([
              {
                text: `    [${r.ok ? 'OK' : 'FAIL'}] ${r.transport}: ${r.detail}`,
                type: r.ok ? 'output' : 'error',
              },
            ]);
          }
        }
        if (data.route_reason) addSystem(`    ${data.route_reason}`);
        addSystem('');
      } catch {
        addError('Mesh router unreachable');
      }
    },
    [addLines, addError, addSystem, nodeIdentity],
  );

  // ─── Meshtastic regional send ─────────────────────────────
  const doMeshSend = useCallback(
    async (message: string, region: string) => {
      if (!nodeIdentity || !hasSovereignty()) {
        addError("Public mesh needs a public Agent identity. Type 'connect' first.");
        return;
      }
      addSystem(`  Signing as ${nodeIdentity.nodeId}...`);
      try {
        const sequence = nextSequence();
        const payload = {
          message,
          destination: 'broadcast',
          channel: 'LongFast',
          priority: 'normal',
          ephemeral: false,
          transport_lock: 'meshtastic',
        };
        const v = validateEventPayload('message', payload);
        if (!v.ok) {
          addError(`Invalid payload: ${v.reason}`);
          return;
        }
        const signature = await signEvent('message', nodeIdentity.nodeId, sequence, payload);
        addSystem(`  Publishing to ${region}/LongFast...`);
        const res = await fetch(`${API}/api/mesh/send`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            sender_id: nodeIdentity.nodeId,
            node_id: nodeIdentity.nodeId,
            public_key: nodeIdentity.publicKey,
            public_key_algo: getPublicKeyAlgo(),
            signature,
            destination: 'broadcast',
            message,
            priority: 'normal',
            channel: 'LongFast',
            ephemeral: false,
            transport_lock: 'meshtastic',
            sequence,
            protocol_version: PROTOCOL_VERSION,
            credentials: { mesh_region: region },
          }),
        });
        const data = await res.json();
        if (data.results) {
          for (const r of data.results) {
            addLines([
              {
                text: `    [${r.ok ? 'OK' : 'FAIL'}] ${r.transport}: ${r.detail}`,
                type: r.ok ? 'output' : 'error',
              },
            ]);
          }
        }
        addSystem('');
      } catch {
        addError('Mesh router unreachable');
      }
    },
    [addLines, addError, addSystem, nodeIdentity],
  );

  const startInteractiveSend = useCallback(() => {
    addSystem('');
    addSystem('  SEND MESSAGE');
    addLines([{ text: '  Who do you want to reach?', type: 'dim' }]);
    addLines([{ text: "  Enter a callsign (e.g. KE4EVL-Y) or 'broadcast':", type: 'dim' }]);
    addSystem('');
    setSendStep('dest');
  }, [addSystem, addLines]);

  // ─── Encrypted DM send ──────────────────────────────────
  const doDMSend = useCallback(
    async (recipientId: string, plaintext: string) => {
      if (!nodeIdentity || !hasSovereignty()) {
        addError("Not connected. Type 'connect' to activate your Agent identity.");
        return;
      }

      addSystem(`  Encrypting for ${recipientId}...`);
        try {
          // 1. Get recipient's DH public key (from contacts or server)
          const contacts = getContacts();
          let theirDHPub = contacts[recipientId]?.dhPubKey;
          const contactAlgo = contacts[recipientId]?.dhAlgo;
          const localAlgo = getDHAlgo();
          if (contactAlgo && localAlgo && contactAlgo !== localAlgo) {
            addError('DM key algorithm mismatch. Regenerate keys to match recipient.');
            return;
          }

          if (!theirDHPub) {
            // Fetch from server
            const keyRes = await fetch(
              `${API}/api/mesh/dm/pubkey?agent_id=${encodeURIComponent(recipientId)}`,
            );
            const keyData = await keyRes.json();
            if (!keyData.ok || !keyData.dh_pub_key) {
              addError("Recipient not found or has no DM keys. They need to 'connect' first.");
              return;
            }
            theirDHPub = keyData.dh_pub_key as string;
            // Auto-add to contacts
            addContact(recipientId, theirDHPub, undefined, keyData.dh_algo);
            const localAlgo = getDHAlgo();
            if (keyData.dh_algo && localAlgo && keyData.dh_algo !== localAlgo) {
              addError('DM key algorithm mismatch. Regenerate keys to match recipient.');
              return;
            }
          }

          await ensureRegisteredDmKey(API, nodeIdentity, { force: false });
        // 2. Encrypt via the shared worker ratchet path
        const ciphertext = await ratchetEncryptDM(recipientId, theirDHPub!, plaintext);

        // 3. Send encrypted blob to server
        const msgId = `dm_${Date.now()}_${nodeIdentity.nodeId.slice(-4)}`;
        const timestamp = Math.floor(Date.now() / 1000);
        const recipientToken = await sharedMailboxToken(recipientId, theirDHPub!);
        const data = await sendDmMessage({
          apiBase: API,
          identity: nodeIdentity,
          recipientId,
          ciphertext,
          msgId,
          timestamp,
          deliveryClass: 'shared',
          recipientToken,
        });
        if (data.ok) {
          addSystem(`  Message delivered to dead drop. ID: ${data.msg_id}`);
          addLines([{ text: '  Encrypted end-to-end. Server cannot read this.', type: 'dim' }]);
        } else {
          addError(data.detail || 'DM delivery failed');
        }
      } catch (err) {
        const msg =
          typeof err === 'object' && err !== null && 'message' in err
            ? String((err as { message?: string }).message)
            : 'encryption error';
        addError(`DM failed: ${msg}`);
      }
      addSystem('');
    },
    [addLines, addError, addSystem, nodeIdentity],
  );

  const cmdLog = useCallback(
    async (n: number = 5) => {
      try {
        const res = await fetch(`${API}/api/mesh/log`);
        const data = await res.json();
        const entries = (data.log || []).slice(0, n);
        if (!entries.length) {
          addSystem('  Routing log is empty');
          return;
        }
        addSystem('');
        addSystem(`  MESH ROUTING LOG (${entries.length})`);
        for (const e of entries) {
          addOutput(
            `    ${e.sender} -> ${e.destination} via ${e.routed_via || 'FAILED'} [${e.priority}]`,
          );
          if (e.route_reason) addLines([{ text: `      ${e.route_reason}`, type: 'dim' }]);
        }
        addSystem('');
      } catch {
        addError('Failed to fetch routing log');
      }
    },
    [addOutput, addError, addSystem, addLines],
  );

  const cmdNearest = useCallback(
    async (lat: string, lng: string) => {
      if (!lat || !lng) {
        addError('Usage: nearest <lat> <lng>');
        return;
      }
      try {
        const res = await fetch(`${API}/api/sigint/nearest-sdr?lat=${lat}&lng=${lng}`);
        const data = await res.json();
        const sdrs = data.results || [];
        if (!sdrs.length) {
          addSystem('  No KiwiSDR receivers found');
          return;
        }
        addSystem('');
        addSystem('  NEAREST KIWISDR RECEIVERS');
        for (const s of sdrs) {
          addOutput(`    ${s.name}`);
          addLines([{ text: `      ${s.location || '?'} — ${s.distance_deg} deg`, type: 'dim' }]);
          if (s.url) addLines([{ text: `      ${s.url}`, type: 'dim' }]);
        }
        addSystem('');
      } catch {
        addError('Failed to query SDR network');
      }
    },
    [addOutput, addError, addSystem, addLines],
  );

  const voteScopeKey = useCallback((targetId: string, gateId: string = '') => {
    return `${(gateId || 'public').trim().toLowerCase()}::${String(targetId || '').trim()}`;
  }, []);

  const postGateMessage = useCallback(
    async (gateId: string, plaintext: string) => {
      const sendAttempt = async () => {
        const res = await fetch(`${API}/api/wormhole/gate/message/post`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            gate_id: gateId,
            plaintext,
          }),
        });
        const data = await res.json();
        if (!data.ok) {
          throw new Error(String(data.detail || 'Failed to post to gate'));
        }
        return data;
      };

      return await sendAttempt();
    },
    [addLines, addSystem],
  );

  const requestGateAccess = useCallback((command: string | null = 'gates') => {
    setPendingGateCommand(command);
    setGateAccessPromptOpen(true);
  }, []);

  const activatePrivateLane = useCallback(
    async (nextCommand: string | null = 'gates') => {
      setPrivateLanePromptBusy(true);
      setPrivateLanePromptStatus({
        type: 'dim',
        text: 'Turning on Wormhole and preparing the obfuscated lane...',
      });
      try {
        let runtime = await refreshPrivateLaneRuntime();
        if (!runtime.secureRequired || !runtime.ready) {
          const joined = await joinWormhole();
          setWormholeSecureRequired(Boolean(joined.settings?.enabled ?? joined.runtime?.configured ?? true));
          setAnonymousModeEnabled(Boolean(joined.settings?.anonymous_mode));
          setWormholeReadyState(Boolean(joined.runtime?.ready));
          setAnonymousModeReady(Boolean(joined.runtime?.anonymous_mode_ready));

          let ready = Boolean(joined.runtime?.ready);
          const deadline = Date.now() + 12000;
          while (!ready && Date.now() < deadline) {
            await new Promise((resolve) => window.setTimeout(resolve, 700));
            runtime = await refreshPrivateLaneRuntime();
            ready = runtime.ready;
          }
          if (!ready) {
            setPrivateLanePromptStatus({
              type: 'err',
              text: 'Wormhole is starting up. Give it a few seconds, then try again.',
            });
            return;
          }
        }

        setPrivateLanePromptStatus({
          type: 'dim',
          text: 'Provisioning obfuscated identity and opening the Infonet Commons...',
        });
        const identity = await bootstrapWormholeIdentity();
        setWormholeSecureRequired(true);
        setWormholeReadyState(true);
        setGateAccessGranted(true);
        setPrivateLanePromptStatus({
          type: 'ok',
          text: `Wormhole ready as ${identity.node_id}.`,
        });
        setPrivateLanePromptOpen(false);
        setGateAccessPromptOpen(false);
        setPendingGateCommand(null);
        addSystem(`  Wormhole obfuscated lane ready as ${identity.node_id}.`);
        addLines([
          {
            text: '  Participant-node sync stays on the backend lane. Wormhole now unlocks gates and the obfuscated commons.',
            type: 'dim',
          },
        ]);

        const commandToRun = nextCommand && nextCommand.trim() ? nextCommand : 'gates';
        const targetPanel = commandToRun === 'inbox' ? 'inbox' : 'gates';
        setSurfacePanel(targetPanel);
        window.setTimeout(() => runQuickCommandRef.current(commandToRun), 40);
      } catch (err) {
        const detail = describeNativeControlError(err) || (err instanceof Error ? err.message : '');
        setPrivateLanePromptStatus({
          type: 'err',
          text: detail || 'Failed to enter Wormhole.',
        });
        addError(detail || 'Failed to enter Wormhole.');
      } finally {
        setPrivateLanePromptBusy(false);
      }
    },
    [addError, addLines, addSystem, refreshPrivateLaneRuntime],
  );

  const routeToWormholeSetup = useCallback(() => {
    setGateAccessPromptOpen(false);
    setPendingGateCommand(null);
    setPrivateLanePromptMode('activate');
    setPrivateLanePromptOpen(true);
    void activatePrivateLane('gates');
  }, [activatePrivateLane]);

  const describeGateMessage = useCallback(
    async (message: InfonetMessageRecord): Promise<string> => {
      const normalized = normalizeInfonetMessageRecord(message);
      if (message.system_seed) {
        return String(message.message || '').slice(0, 120);
      }
      if (!isEncryptedGateEnvelope(normalized)) {
        return String(normalized.message || '').slice(0, 80);
      }
      try {
        const decrypted = await decryptWormholeGateMessage(
          String(normalized.gate || ''),
          Number(normalized.epoch || 0),
          String(normalized.ciphertext || ''),
          String(normalized.nonce || ''),
          String(normalized.sender_ref || ''),
        );
        return gateEnvelopeDisplayText({
          ...normalized,
          decrypted_message: decrypted.ok ? decrypted.plaintext : '',
        }).slice(0, 120);
      } catch {
        return gateEnvelopeDisplayText(normalized).slice(0, 120);
      }
    },
    [],
  );

  const openGateCard = useCallback(
    async (gateId: string) => {
      if (!gateId) return;
      if (expandedGateId === gateId && expandedGateDetail) {
        setExpandedGateId(null);
        setExpandedGateDetail(null);
        setExpandedGateKey(null);
        setExpandedGateMessages([]);
        if (activeGateComposeId === gateId) {
          setActiveGateComposeId(null);
          setGateReplyTarget(null);
        }
        return;
      }
      setExpandedGateLoading(gateId);
      try {
        const gateHeaders = await buildGateAccessHeaders(gateId);
        const [gateData, keyData, messageData] = await Promise.all([
          fetch(`${API}/api/mesh/gate/${encodeURIComponent(gateId)}`).then((res) => res.json()),
          fetchWormholeGateKeyStatus(gateId).catch(() => null),
          fetch(`${API}/api/mesh/infonet/messages?gate=${encodeURIComponent(gateId)}&limit=6`, {
            headers: gateHeaders,
          }).then((res) => res.json()),
        ]);
        setExpandedGateId(gateId);
        setExpandedGateDetail(gateData);
        setExpandedGateKey(keyData && keyData.ok ? (keyData as GateKeyStatusRecord) : null);
        setActiveGateComposeId(gateId);
        const msgs = (Array.isArray(messageData.messages) ? messageData.messages : []).map(
          (message: InfonetMessageRecord) => normalizeInfonetMessageRecord(message),
        ) as InfonetMessageRecord[];
        const previews: GateThreadPreview[] = [];
        for (const message of msgs.slice(0, 4)) {
          const ageMin = Math.floor((Date.now() / 1000 - message.timestamp) / 60);
          const age = ageMin < 60 ? `${ageMin}m ago` : `${Math.floor(ageMin / 60)}h ago`;
          const text = await describeGateMessage(message);
          previews.push({
            nodeId: message.node_id || '',
            age,
            text,
            encrypted: isEncryptedGateEnvelope(message),
          });
        }
        setExpandedGateMessages(previews);
      } catch {
        setExpandedGateId(gateId);
        setExpandedGateDetail(null);
        setExpandedGateKey(null);
        setExpandedGateMessages([]);
      } finally {
        setExpandedGateLoading(null);
      }
    },
    [activeGateComposeId, describeGateMessage, expandedGateDetail, expandedGateId],
  );

  const exec = useCallback(
    async (raw: string) => {
      const trimmed = raw.trim();
      if (!trimmed) return;

      const slashMode = trimmed.startsWith('/');
      const normalized = slashMode ? trimmed.slice(1).trim() : trimmed;
      const gateChatMode =
        !slashMode &&
        surfacePanel === 'gates' &&
        Boolean(activeGateComposeId) &&
        !sendStep &&
        !dmStep &&
        !sovereigntyPending;

      if (gateChatMode && activeGateComposeId) {
        addLines([
          {
            text: `  > ${gateReplyTarget ? `@${gateReplyTarget} ` : ''}${trimmed}`,
            type: 'input',
          },
        ]);
        if (terminalWriteLockReason) {
          addError(terminalWriteLockReason);
          return;
        }
        if (!wormholeSecureRequired || !wormholeReadyState) {
          addError('Wormhole obfuscated lane is required for gate posting. Open Wormhole first.');
          return;
        }
        setBusy(true);
        await (async () => {
          try {
            const messageToSend = gateReplyTarget ? `@${gateReplyTarget} ${trimmed}` : trimmed;
            await postGateMessage(activeGateComposeId, messageToSend);
            addSystem(`  Posted to g/${activeGateComposeId}`);
            setGateReplyTarget(null);
            await openGateCard(activeGateComposeId);
          } catch (err) {
            const detail = err instanceof Error && err.message ? err.message : '';
            addError(describeNativeControlError(err) || detail || 'Failed to post to gate');
          } finally {
            setBusy(false);
          }
        })();
        return;
      }

      // ─── Sovereignty declaration flow ───────────────────────
      if (sovereigntyPending) {
        addLines([{ text: `  > ${trimmed}`, type: 'input' }]);
        const lower = trimmed.toLowerCase();
        if (lower === 'accept') {
          if (terminalWriteLockReason) {
            addError(terminalWriteLockReason);
            addLines([
              {
                text: '  Mesh Terminal is read-only for sensitive actions until it is routed through Wormhole.',
                type: 'dim',
              },
            ]);
            return;
          }
          setBusy(true);
          setSovereigntyPending(false);
          try {
            addSystem('  Generating Ed25519 keypair...');
            const identity = await generateNodeKeys();
            setNodeIdentity(identity);
            addSystem('');
            addSystem('  AGENT ACTIVATED');
            addOutput(`    Agent ID:   ${identity.nodeId}`);
            addOutput(`    Public Key: ${identity.publicKey.slice(0, 24)}...`);
            addSystem('    Private key stored locally — never leaves this device.');
            addSystem('');
            // Register DH public key for encrypted DMs
            const dhPub = getDHPubKey();
            if (dhPub) {
              try {
                await ensureRegisteredDmKey(API, identity, { force: true });
                addOutput('    Encrypted DM keys registered.');
              } catch {
                /* non-critical */
              }
            }
            addSystem('');
            addSystem('  You are now an agent on the Infonet.');
            addSystem("  Type 'help' for commands, 'send' to transmit, 'dm' for private messages.");
            addSystem('');
          } catch (err) {
            const msg =
              typeof err === 'object' && err !== null && 'message' in err
                ? String((err as { message?: string }).message)
                : 'unknown error';
            addError(
              msg === 'browser_identity_blocked_secure_mode'
                ? 'Browser identity generation is disabled in Wormhole secure mode'
                : `Key generation failed: ${msg}`,
            );
          }
          setBusy(false);
          return;
        } else if (lower === 'decline') {
          setSovereigntyPending(false);
          declineSovereignty();
          addSystem('');
          addSystem('  Read-only mode active. You can view signals and status.');
          addLines([{ text: "  To activate later, type 'accept' when prompted.", type: 'dim' }]);
          addSystem('');
          return;
        } else {
          addLines([{ text: "  Type 'accept' or 'decline'.", type: 'dim' }]);
          return;
        }
      }

      // ─── Interactive send flow ─────────────────────────────
      if (sendStep === 'dest') {
        addLines([{ text: `  > ${trimmed}`, type: 'input' }]);
        setSendDest(trimmed);
        setSendStep('msg');
        addLines([{ text: `  Destination: ${trimmed}`, type: 'system' }]);
        addLines([{ text: '  Now type your message:', type: 'dim' }]);
        addSystem('');
        return;
      }
      if (sendStep === 'msg') {
        addLines([{ text: `  > ${trimmed}`, type: 'input' }]);
        if (terminalWriteLockReason) {
          addError(terminalWriteLockReason);
          setSendStep(null);
          setSendDest('');
          return;
        }
        setSendStep(null);
        setBusy(true);
        await doSend(sendDest, trimmed);
        setSendDest('');
        setBusy(false);
        return;
      }

      // ─── Interactive DM flow ───────────────────────────────
      if (dmStep === 'dest') {
        addLines([{ text: `  > ${trimmed}`, type: 'input' }]);
        setDmDest(trimmed);
        setDmStep('msg');
        addLines([{ text: `  To: ${trimmed}`, type: 'system' }]);
        addLines([{ text: '  Type your private message:', type: 'dim' }]);
        addSystem('');
        return;
      }
      if (dmStep === 'msg') {
        addLines([{ text: `  > ${trimmed}`, type: 'input' }]);
        if (terminalWriteLockReason) {
          addError(terminalWriteLockReason);
          setDmStep(null);
          setDmDest('');
          return;
        }
        setDmStep(null);
        setBusy(true);
        await doDMSend(dmDest, trimmed);
        setDmDest('');
        setBusy(false);
        return;
      }

      // ─── Normal command flow ───────────────────────────────
      addLines([{ text: `  > ${slashMode ? normalized : trimmed}`, type: 'input' }]);
      setHistory((prev) => [slashMode ? normalized : trimmed, ...prev.slice(0, 49)]);
      setHistIdx(-1);
      setBusy(true);

      const [cmd, ...args] = normalized.split(/\s+/);
      try {
        if (terminalWriteLockReason && isMeshTerminalWriteCommand(cmd, args)) {
          addError(terminalWriteLockReason);
          addLines([
            {
              text: '  Mesh Terminal remains read-only for these actions until it is routed through Wormhole.',
              type: 'dim',
            },
          ]);
          setBusy(false);
          return;
        }
        switch (cmd.toLowerCase()) {
          case 'help': {
            const section = String(args[0] || '').toLowerCase();
            if (!section) {
              addSystem('');
              addSystem('  HELP CATEGORIES');
              addOutput('    help mesh      Public mesh and radio commands');
              addOutput('    help gates     Encrypted gate commons commands');
              addOutput('    help inbox     Experimental obfuscated DM inbox commands');
              addOutput('    help markets   Prediction market and oracle commands');
              addOutput('    help infonet   Ledger, sync, and message browsing');
              addOutput('    help ops       Dossiers, news, Shodan, places, aircraft');
              addSystem('');
              addLines([{ text: '  Click the HELP cards above or type one of the categories for details.', type: 'dim' }]);
              break;
            }
            const sectionLines = HELP_SECTIONS[section];
            if (!sectionLines) {
              addError(`Unknown help category '${section}'. Try: mesh, gates, inbox, markets, infonet, ops`);
              break;
            }
            addSystem('');
            for (const line of sectionLines) {
              if (line.startsWith('  ') && !line.startsWith('    ')) addSystem(line);
              else addOutput(line);
            }
            addSystem('');
            break;
          }
          case 'guide':
            addLines([...GUIDE_TEXT]);
            break;
          case 'clear':
            setLines([
              { text: '', type: 'dim' },
              {
                text:
                  surfacePanel === 'gates' && activeGateComposeId
                    ? `  Cleared. Still inside g/${activeGateComposeId}. Type to post or /help gates for commands.`
                    : surfacePanel === 'mesh'
                      ? `  Cleared. Still in the MESH lane for ${meshRegion}. Type 'mesh listen 12' or 'mesh send <msg>'.`
                      : "  Cleared. Type 'help' for categories or 'clear' again any time.",
                type: 'system',
              },
              { text: '', type: 'dim' },
            ]);
            break;
          case 'status':
            await cmdStatus();
            break;
          case 'signals':
          case 'sig':
            await cmdSignals(parseInt(args[0]) || 10);
            break;
          case 'mesh':
          case 'radio': {
            const availableMeshRoots = meshRoots.length ? meshRoots : [...DEFAULT_MESH_ROOTS];
            const sub = args[0]?.toLowerCase();
            if (!sub) {
              // mesh — show current root + list
              addSystem('');
              addSystem(`  MESHTASTIC RADIO`);
              addSystem(`  Active root: ${meshRegion}`);
              addSystem(`  Channel: LongFast (default PSK)`);
              addSystem('');
              addSystem('  Available roots:');
              addOutput('    ' + availableMeshRoots.join('  '));
              addSystem('');
              addSystem('  Commands:');
              addOutput('    mesh region <root>    Switch root (e.g. mesh region EU_868)');
              addOutput('    mesh listen [n]       Recent signals from active root');
              addOutput("    mesh send <message>   Send to active root's LongFast");
              addOutput('    mesh channels         All roots with signal counts');
              addSystem('');
            } else if (sub === 'region' || sub === 'r') {
              const code = args[1]?.trim();
              if (!code) {
                addError(`  Unknown root. Valid: ${availableMeshRoots.join(', ')}`);
              } else {
                const normalized =
                  availableMeshRoots.find((root) => root.toUpperCase() === code.toUpperCase()) ||
                  code;
                setMeshRegion(normalized);
                addSystem(`  Root set to ${normalized}`);
              }
            } else if (sub === 'listen' || sub === 'l') {
              const n = parseInt(args[1]) || 20;
              try {
                const res = await fetch(
                  `${API}/api/mesh/signals?source=meshtastic&region=${meshRegion}&limit=${n}`,
                );
                const data = await res.json();
                const sigs = data.signals || [];
                if (!sigs.length) {
                  addSystem(`  No Meshtastic signals from ${meshRegion}`);
                } else {
                  addSystem('');
                  addSystem(`  MESHTASTIC ${meshRegion} (${sigs.length}/${data.total} signals)`);
                  for (const s of sigs) {
                    const call = (s.callsign || '???').padEnd(14);
                    const pos = `${s.lat?.toFixed(2)},${s.lng?.toFixed(2)}`.padEnd(14);
                    const ch = s.channel || 'LongFast';
                    const extra = s.status ? ` ${s.status.slice(0, 25)}` : '';
                    addOutput(`    ${call} ${pos} ${ch}${extra}`);
                  }
                  addSystem('');
                }
              } catch {
                addError('Failed to fetch signals');
              }
            } else if (sub === 'send' || sub === 's') {
              const msg = args.slice(1).join(' ');
              if (!msg) {
                addError('  Usage: mesh send <message>');
              } else if (!nodeIdentity || !hasSovereignty()) {
                addError("  Not connected. Type 'connect' first.");
              } else {
                await doMeshSend(msg, meshRegion);
              }
            } else if (sub === 'channels' || sub === 'ch') {
              try {
                const res = await fetch(`${API}/api/mesh/channels`);
                const data = await res.json();
                const counts: Record<string, number> = {};
                const knownRoots = Array.isArray(data.known_roots) ? data.known_roots : [];
                Object.entries((data.roots || {}) as Record<string, { nodes?: number }>).forEach(
                  ([root, entry]) => {
                    counts[root] = Number(entry?.nodes || 0);
                  },
                );
                const roots = sortMeshRoots(
                  [...DEFAULT_MESH_ROOTS, ...knownRoots, ...Object.keys(counts), meshRegion],
                  counts,
                  meshRegion,
                );
                setMeshRoots(roots);
                addSystem('');
                addSystem(
                  `  MESHTASTIC ROOTS (${Number(data.total_live || 0)} live nodes / ${Number(data.total_nodes || 0)} total)`,
                );
                for (const r of roots) {
                  const bar =
                    counts[r] > 0 ? '█'.repeat(Math.min(20, Math.ceil(counts[r] / 10))) : '·';
                  const active = r === meshRegion ? ' ◄' : '';
                  addOutput(`    ${r.padEnd(14)} ${String(counts[r]).padStart(4)} ${bar}${active}`);
                }
                addSystem('');
                addSystem("  Use 'mesh region <root>' to switch");
                addSystem('');
              } catch {
                addError('Failed to fetch signals');
              }
            } else {
              addError(`  Unknown: mesh ${sub}. Try 'mesh' for help.`);
            }
            break;
          }
          case 'send':
            // Check sovereignty before allowing send
            if (!nodeIdentity || !hasSovereignty()) {
              if (isDeclined()) {
                addError("Read-only mode. Type 'connect' to activate your Agent identity.");
              } else {
                addLines([...SOVEREIGNTY_DECLARATION]);
                setSovereigntyPending(true);
              }
              setBusy(false);
              return;
            }
            if (args.length >= 2) {
              await doSend(args[0], args.slice(1).join(' '));
            } else {
              startInteractiveSend();
            }
            break;
          case 'whoami': {
            addSystem('');
            addSystem('  IDENTITY LANES');
            if (nodeIdentity && hasSovereignty()) {
              addOutput(`    Public Agent: ${nodeIdentity.nodeId}`);
              addOutput(`    Public Key: ${nodeIdentity.publicKey.slice(0, 24)}...`);
              addSystem('    Status: ACTIVE — public mesh and perimeter sends sign with this key');
            } else if (isDeclined()) {
              addSystem('    Public Agent: READ-ONLY (declined)');
              addLines([{ text: "    Type 'connect' to create a public Agent.", type: 'dim' }]);
            } else {
              addLines([
                {
                  text: "    Public Agent: not connected — type 'connect' to create one.",
                  type: 'dim',
                },
              ]);
            }
            addOutput(`    Wormhole Lane: ${privateLaneLabel}`);
            addLines([{ text: `    ${privateLaneDetail}`, type: 'dim' }]);
            addSystem('');
            break;
          }
          case 'connect':
          case 'sovereignty':
          case 'sovereign':
          case 'activate':
          case 'join': {
            if (nodeIdentity && hasSovereignty()) {
              addSystem(
                `  Public Agent already active as ${nodeIdentity.nodeId}. Type 'whoami' for lane status.`,
              );
            } else {
              addLines([...SOVEREIGNTY_DECLARATION]);
              setSovereigntyPending(true);
            }
            break;
          }
          case 'rep': {
            // rep <node_id> — full public reputation breakdown
            const targetId = args[0];
            if (!targetId) {
              addError('Usage: rep <node_id>  (e.g. rep !sb_a3f2c891)');
              break;
            }
            try {
              const res = await fetch(
                `${API}/api/mesh/reputation?node_id=${encodeURIComponent(targetId)}`,
              );
              const data = await res.json();
              if (data.ok === false) {
                addError(data.detail);
                break;
              }
              addSystem('');
              addSystem(`  NODE: ${data.node_id || targetId}`);
              addOutput(
                `    Overall Rep: ${data.overall ?? 0}  (${data.upvotes ?? 0} up / ${data.downvotes ?? 0} down)`,
              );
              addOutput(
                `    Node Age:    ${data.node_age_days ?? 0} days${data.is_agent ? '  [AGENT]' : ''}`,
              );
              const gates = data.gates || {};
              if (Object.keys(gates).length > 0) {
                addSystem('    Gate Rep:');
                for (const [gid, score] of Object.entries(gates)) {
                  addOutput(`      ${gid}: ${score}`);
                }
              }
              const votes = data.recent_votes || [];
              if (votes.length > 0) {
                addSystem('    Recent Votes:');
                for (const v of votes.slice(0, 10)) {
                  const dir = v.vote > 0 ? '+1' : '-1';
                  const gStr = v.gate ? ` in ${v.gate}` : '';
                  const agentStr = v.agent_verify ? ' [AGENT]' : '';
                  addOutput(`      ${dir} from ${v.voter}${gStr} (${v.age})${agentStr}`);
                }
              }
              addSystem('');
            } catch {
              addError('Failed to fetch reputation');
            }
            break;
          }
          case 'myrep': {
            if (!nodeIdentity) {
              addError("Not connected. Type 'connect' to activate.");
              break;
            }
            try {
              const res = await fetch(
                `${API}/api/mesh/reputation?node_id=${encodeURIComponent(nodeIdentity.nodeId)}`,
              );
              const data = await res.json();
              addSystem('');
              addSystem(`  YOUR REPUTATION: ${nodeIdentity.nodeId}`);
              addOutput(
                `    Overall: ${data.overall ?? 0}  (${data.upvotes ?? 0} up / ${data.downvotes ?? 0} down)`,
              );
              const gates = data.gates || {};
              if (Object.keys(gates).length > 0) {
                addSystem('    Gate Rep:');
                for (const [gid, score] of Object.entries(gates)) {
                  addOutput(`      ${gid}: ${score}`);
                }
              }
              addSystem('');
            } catch {
              addError('Failed to fetch reputation');
            }
            break;
          }
          case 'vote': {
            // vote <agent_id> up|down [gate]
            if (!nodeIdentity || !hasSovereignty()) {
              addError("Not connected. Type 'connect' to activate your Agent identity.");
              break;
            }
            const vTarget = args[0];
            const vDir = args[1]?.toLowerCase();
            const voteGate =
              String(args[2] || activeGateComposeId || expandedGateId || '').trim().toLowerCase();
            if (!vTarget || !vDir || !['up', 'down'].includes(vDir)) {
              addError('Usage: vote <node_id> up|down [gate]');
              break;
            }
            try {
              const voteVal = vDir === 'up' ? 1 : -1;
              const existingVote = voteDirections[voteScopeKey(vTarget, voteGate)];
              if (existingVote === voteVal) {
                addSystem(
                  `  Vote already set to ${voteVal > 0 ? 'up' : 'down'} on ${vTarget}${voteGate ? ` in g/${voteGate}` : ''}.`,
                );
                break;
              }
              const sequence = nextSequence();
              const votePayload = { target_id: vTarget, vote: voteVal, gate: voteGate };
              const v = validateEventPayload('vote', votePayload);
              if (!v.ok) {
                addError(`Invalid payload: ${v.reason}`);
                break;
              }
              const signature = await signEvent('vote', nodeIdentity.nodeId, sequence, votePayload);
              const res = await fetch(`${API}/api/mesh/vote`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                  voter_id: nodeIdentity.nodeId,
                  voter_pubkey: nodeIdentity.publicKey,
                  target_id: vTarget,
                  vote: voteVal,
                  gate: voteGate || undefined,
                  public_key_algo: getPublicKeyAlgo(),
                  voter_sig: signature,
                  sequence,
                  protocol_version: PROTOCOL_VERSION,
                }),
              });
              const data = await res.json();
              if (data.ok) {
                setVoteDirections((prev) => ({
                  ...prev,
                  [voteScopeKey(vTarget, voteGate)]: voteVal,
                }));
                addSystem(`  ${data.detail}`);
              } else {
                addError(data.detail);
              }
            } catch {
              addError('Failed to cast vote');
            }
            break;
          }
          case 'threshold': {
            const n = parseInt(args[0]);
            if (isNaN(n) || n < 0) {
              const current =
                typeof window !== 'undefined'
                  ? localStorage.getItem('sb_mesh_rep_threshold') || '0'
                  : '0';
              addSystem(`  Current DM threshold: ${current} (min rep to receive messages)`);
              addLines([{ text: '  Usage: threshold <n>  (e.g. threshold 5)', type: 'dim' }]);
              break;
            }
            localStorage.setItem('sb_mesh_rep_threshold', String(n));
            addSystem(`  DM threshold set to ${n}. Only nodes with rep >= ${n} can message you.`);
            break;
          }
          case 'gates': {
            if (!gateAccessGranted) {
              requestGateAccess('gates');
              break;
            }
            try {
              const res = await fetch(`${API}/api/mesh/gate/list`);
              const data = await res.json();
              const gates = data.gates || [];
              addSystem('');
              if (!gates.length) {
                addSystem('  No launch gates are available yet.');
              } else {
                addSystem(`  PRIVATE LAUNCH GATES (${gates.length})`);
                addLines([
                  {
                    text: '  Click a gate row to enter it, or use /gate <gate-id> if you want command mode.',
                    type: 'dim',
                  },
                ]);
                for (const g of gates) {
                  const rules = g.rules || {};
                  const reqStr = rules.min_overall_rep
                    ? `req: ${rules.min_overall_rep} rep`
                    : 'open';
                  addLines([
                    {
                      text: `    ${g.gate_id.padEnd(20)} ${(g.display_name || '').padEnd(20)} ${reqStr}  (${g.message_count} msgs)`,
                      type: 'output',
                      actionCommand: `gate ${g.gate_id}`,
                      actionLabel: 'ENTER',
                    },
                  ]);
                  if (g.description) {
                    addLines([{ text: `      ${g.description}`, type: 'dim' }]);
                  }
                }
                addLines([
                  {
                    text: '  Fixed launch catalog only. Gate creation is disabled in this testnet build.',
                    type: 'dim',
                  },
                ]);
              }
              addSystem('');
            } catch {
              addError('Failed to fetch gates');
            }
            break;
          }
          case 'gate': {
            if (!gateAccessGranted) {
              requestGateAccess(`gate ${args.join(' ')}`.trim());
              break;
            }
            // gate <id> | gate mask <id> | gate anon <id> | gate rekey <id> [reason] | gate audit [limit]
            if (args[0] === 'create') {
              addError('Gate creation is disabled. This testnet uses a fixed private launch catalog.');
            } else if (args[0] === 'audit') {
              const requested = Number.parseInt(String(args[1] || '5'), 10);
              const limit = Number.isFinite(requested) && requested > 0 ? Math.min(requested, 10) : 5;
              const report = getDesktopNativeControlAuditReport(limit);
              addSystem('');
              if (!report || report.totalEvents === 0) {
                addSystem('  NATIVE CONTROL AUDIT');
                addOutput('    No native session-profile audit events have been recorded yet.');
                addSystem('');
                break;
              }
              addSystem(
                `  NATIVE CONTROL AUDIT (${report.totalRecorded || report.totalEvents} recorded${report.totalRecorded > report.totalEvents ? `, ${report.totalEvents} shown` : ''})`,
              );
              addOutput(
                `    Outcomes:    allowed ${report.byOutcome.allowed || 0} | profile_warn ${report.byOutcome.profile_warn || 0} | denied ${(report.byOutcome.profile_denied || 0) + (report.byOutcome.capability_denied || 0) + (report.byOutcome.shim_refused || 0)}`,
              );
              if (report.lastProfileMismatch) {
                addOutput(
                  `    Last drift:  ${report.lastProfileMismatch.command}${report.lastProfileMismatch.targetRef ? ` [${report.lastProfileMismatch.targetRef}]` : ''} -> ${report.lastProfileMismatch.outcome} (${report.lastProfileMismatch.sessionProfile || 'unscoped'})`,
                );
              }
              report.recent.forEach((entry, index) => {
                addOutput(
                  `    ${String(index + 1).padStart(2, '0')}. ${entry.command}${entry.targetRef ? ` [${entry.targetRef}]` : ''}  ${entry.outcome}  profile=${entry.sessionProfile || 'unscoped'}  cap=${entry.expectedCapability}`,
                );
              });
              addSystem('');
            } else if (args[0] === 'mask') {
              const gateId = args[1];
              if (!gateId) {
                addError('Usage: gate mask <id>');
                break;
              }
              if (!wormholeSecureRequired || !wormholeReadyState) {
                addError('Wormhole is not ready. Open Wormhole first, then retry gate unlock.');
                break;
              }
              if (anonymousModeEnabled && !anonymousModeReady) {
                addError('Hidden transport required for anonymous gate personas.');
                break;
              }
              try {
                const created = await createWormholeGatePersona(gateId, `persona-${Date.now().toString().slice(-4)}`);
                if (!created.ok) {
                  addError(created.detail || 'failed to create gate face');
                  break;
                }
                addSystem('');
                addSystem(`  GATE FACE READY: ${gateId}`);
                addOutput(`    Face:       ${created.identity?.label || created.identity?.persona_id || created.identity?.node_id || 'unknown'}`);
                addOutput('    Status:     encrypted gate content unlocked for this face');
                addSystem('');
              } catch (err) {
                addError(
                  describeNativeControlError(err) ||
                    (err instanceof Error && err.message) ||
                    'Failed to create gate face',
                );
              }
            } else if (args[0] === 'anon') {
              const gateId = args[1];
              if (!gateId) {
                addError('Usage: gate anon <id>');
                break;
              }
              try {
                const cleared = await clearWormholeGatePersona(gateId);
                if (!cleared.ok) {
                  addError(cleared.detail || 'failed to return to anonymous mode');
                  break;
                }
                addSystem('');
                addSystem(`  ANONYMOUS SESSION RESTORED: ${gateId}`);
                addOutput('    Status:     rotating anonymous gate key active for this room');
                addSystem('');
              } catch (err) {
                addError(describeNativeControlError(err) || 'Failed to switch to anonymous mode');
              }
            } else if (args[0] === 'rekey') {
              const gateId = args[1];
              const reason = args.slice(2).join('_') || 'operator_reset';
              if (!gateId) {
                addError('Usage: gate rekey <id> [reason]');
                break;
              }
              try {
                const rotated = await rotateWormholeGateKey(gateId, reason);
                if (!rotated.ok) {
                  addError(rotated.detail || 'failed to rotate gate key');
                  break;
                }
                addSystem('');
                addSystem(`  GATE KEY ROTATED: ${rotated.gate_id}`);
                addOutput(`    Epoch:      ${rotated.current_epoch}`);
                addOutput(`    Key:        ${(rotated.key_commitment || '').slice(0, 16)}...`);
                addOutput(`    Reason:     ${rotated.last_rotation_reason || reason}`);
                addSystem('');
              } catch (err) {
                addError(describeNativeControlError(err) || 'Failed to rotate gate key');
              }
            } else if (args[0]) {
              // View gate details
              try {
                const gateId = String(args[0] || '').trim().toLowerCase();
                const [gateRes, keyStatus] = await Promise.all([
                  fetch(`${API}/api/mesh/gate/${encodeURIComponent(gateId)}`).then((res) => res.json()),
                  fetchWormholeGateKeyStatus(gateId).catch(() => null),
                ]);
                const data = gateRes;
                if (data.ok === false) {
                  addError(data.detail);
                  break;
                }
                addSystem('');
                addSystem(`  GATE: ${data.gate_id}`);
                addOutput(`    Name:     ${data.display_name || data.gate_id}`);
                if (data.description) addOutput(`    Brief:    ${data.description}`);
                if (data.welcome) addOutput(`    Welcome:  ${data.welcome}`);
                addOutput(`    Creator:  ${data.creator_node_id}`);
                addOutput(`    Messages: ${data.message_count || 0}`);
                const rules = data.rules || {};
                addOutput(`    Min Rep:  ${rules.min_overall_rep || 'none'}`);
                addOutput(`    Catalog:  ${data.fixed ? 'fixed launch gate' : 'dynamic gate'}`);
                if (keyStatus?.ok) {
                  addOutput(`    Epoch:     ${keyStatus.current_epoch || 0}`);
                  addOutput(
                    `    Key:       ${String(keyStatus.key_commitment || '').slice(0, 16) || 'pending'}${keyStatus.key_commitment ? '...' : ''}`,
                  );
                  addOutput(
                    `    Access:    ${keyStatus.has_local_access ? keyStatus.identity_scope || 'member' : 'locked'}`,
                  );
                  if (keyStatus.identity_scope === 'anonymous' && !keyStatus.has_local_access) {
                    addLines([
                      {
                        text: '    Anonymous gate session is active, but this install has not synced local gate access yet.',
                        type: 'dim',
                      },
                      {
                        text: `    Retry the room or switch to: gate mask ${gateId}`,
                        type: 'dim',
                      },
                    ]);
                  }
                  if (keyStatus.rekey_recommended) {
                    addOutput(
                      `    Rekey:     advised (${String(keyStatus.rekey_recommended_reason || 'review').replace(/_/g, ' ')})`,
                    );
                  }
                }
                addSystem('');
              } catch {
                addError('Failed to fetch gate details');
              }
            } else {
              addError('Usage: gate <id> | gate mask <id> | gate anon <id> | gate rekey <id> [reason] | gate audit [limit]');
            }
            break;
          }
          case 'say': {
            if (!gateAccessGranted) {
              requestGateAccess(`say ${args.join(' ')}`.trim());
              break;
            }
            // say <gate_id> <message>
            if (!wormholeSecureRequired || !wormholeReadyState) {
              addError('Wormhole obfuscated lane is required for gate posting. Open Wormhole first.');
              break;
            }
              const gateId = args[0];
              const gateMsg = args.slice(1).join(' ');
              if (!gateId || !gateMsg) {
                addError('Usage: say <gate_id> <message>');
                break;
            }
              try {
                const data = await postGateMessage(gateId, gateMsg);
                addSystem(`  ${data.detail || `Posted to g/${gateId}`}`);
              } catch (err) {
              const detail = err instanceof Error && err.message ? err.message : '';
              addError(describeNativeControlError(err) || detail || 'Failed to post to gate');
            }
            break;
          }
          case 'apps':
            cmdApps();
            break;
          case 'news':
            await cmdNews(args.join(' '));
            break;
          case 'jet':
          case 'jets':
            await cmdJets(args.join(' '));
            break;
          case 'place':
          case 'places':
            await cmdPlaces(args.join(' '));
            break;
          case 'dossier':
          case 'intel':
            await cmdDossier(args.join(' '));
            break;
          case 'shodan':
            await cmdShodan(args);
            break;
          case 'markets': {
            try {
              const query = args.join(' ').trim();
              const res = await fetch(
                query
                  ? `${API}/api/mesh/oracle/search?q=${encodeURIComponent(query)}&limit=100`
                  : `${API}/api/mesh/oracle/markets`,
              );
              const data = await res.json();
              const markets = query
                ? asSearchRecords(data.results || data.markets || data.cached || [])
                : asSearchRecords(
                    Array.isArray(data.markets)
                      ? data.markets
                      : Object.values((data.categories || {}) as Record<string, unknown>).flatMap(
                          (items) => (Array.isArray(items) ? items : []),
                        ),
                  );
              addSystem('');
              if (!markets.length) {
                addSystem(query ? `  No market matches for '${query}'.` : '  No active prediction markets available.');
              } else {
                addSystem(
                  query
                    ? `  MARKET SEARCH: ${query} (${markets.length})`
                    : `  PREDICTION MARKETS (${markets.length})`,
                );
                for (const m of markets.slice(0, 20)) {
                  const title = pickRecordText(m, ['title', 'question']) || 'untitled market';
                  const pctValue =
                    typeof m.consensus_pct === 'number'
                      ? `${m.consensus_pct}%`
                      : typeof m.probability === 'number'
                        ? `${m.probability}%`
                        : '?%';
                  const category = pickRecordText(m, ['category']);
                  addOutput(`    ${pctValue.padStart(5)}  ${title.slice(0, 60)}`);
                  if (category) {
                    addLines([{ text: `      ${category}`, type: 'dim' }]);
                  }
                }
                if (markets.length > 20)
                  addLines([{ text: `    ... and ${markets.length - 20} more`, type: 'dim' }]);
                addLines([
                  {
                    text: query
                      ? '  Use: predict <market title> yes|no'
                      : "  Tip: markets taiwan | markets bitcoin | markets election",
                    type: 'dim',
                  },
                ]);
              }
              addSystem('');
            } catch {
              addError('Failed to fetch markets');
            }
            break;
          }
          case 'predict': {
            if (!nodeIdentity || !hasSovereignty()) {
              addError("Not connected. Type 'connect' to activate your Agent identity.");
              break;
            }
            // predict <market title words...> yes|no — last word is side
            if (args.length < 2) {
              addError('Usage: predict <market title> yes|no');
              addLines([{ text: '  Example: predict Will Bitcoin hit 100k? yes', type: 'dim' }]);
              break;
            }
            const pSide = args[args.length - 1].toLowerCase();
            if (!['yes', 'no'].includes(pSide)) {
              addError("Last argument must be 'yes' or 'no'");
              break;
            }
              const pTitle = args.slice(0, -1).join(' ');
              try {
                const predictionPayload = {
                  market_title: pTitle,
                  side: pSide,
                  stake_amount: 0,
                };
                const v = validateEventPayload('prediction', predictionPayload);
                if (!v.ok) {
                  addError(`Invalid payload: ${v.reason}`);
                  break;
                }
                const sequence = nextSequence();
                const signature = await signEvent(
                  'prediction',
                  nodeIdentity.nodeId,
                  sequence,
                  predictionPayload,
                );
                const res = await fetch(`${API}/api/mesh/oracle/predict`, {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({
                    node_id: nodeIdentity.nodeId,
                    market_title: pTitle,
                    side: pSide,
                    stake_amount: 0,
                    public_key: nodeIdentity.publicKey,
                    public_key_algo: getPublicKeyAlgo(),
                    signature,
                    sequence,
                    protocol_version: PROTOCOL_VERSION,
                  }),
                });
              const data = await res.json();
              if (data.ok) {
                addSystem(`  ${data.detail}`);
                if (data.probability != null) {
                  const potential =
                    pSide === 'yes'
                      ? (1 - data.probability / 100).toFixed(3)
                      : (data.probability / 100).toFixed(3);
                  addLines([
                    {
                      text: `  Market at ${data.probability}% — potential oracle rep: ${potential}`,
                      type: 'dim',
                    },
                  ]);
                }
              } else {
                addError(data.detail);
              }
            } catch {
              addError('Failed to place prediction');
            }
            break;
          }
          case 'oracle': {
            // oracle [node_id] — view oracle profile
            const oTarget = args[0] || (nodeIdentity?.nodeId ?? '');
            if (!oTarget) {
              addError("Usage: oracle <node_id>  (or just 'oracle' for your own)");
              break;
            }
            try {
              const res = await fetch(
                `${API}/api/mesh/oracle/profile?node_id=${encodeURIComponent(oTarget)}`,
              );
              const data = await res.json();
              if (data.ok === false) {
                addError(data.detail);
                break;
              }
              addSystem('');
              addSystem(`  ORACLE: ${data.node_id}`);
              addOutput(
                `    Oracle Rep:     ${data.oracle_rep} (${data.oracle_rep_locked} locked in stakes)`,
              );
              addOutput(
                `    Predictions:    ${data.predictions_won}W / ${data.predictions_lost}L (${data.win_rate}% win rate)`,
              );
              addOutput(`    Farming Score:  ${data.farming_pct}% easy bets`);
              const stakes = data.active_stakes || [];
              if (stakes.length > 0) {
                addSystem('    Active Stakes:');
                for (const s of stakes) {
                  addOutput(`      ${s.side.toUpperCase()} ${s.amount} rep on msg ${s.message_id}`);
                }
              }
              const history = data.prediction_history || [];
              if (history.length > 0) {
                addSystem('    Prediction History:');
                for (const p of history.slice(0, 10)) {
                  const icon = p.correct ? '+' : '-';
                  addOutput(
                    `      ${icon}${p.rep_earned} ${p.side.toUpperCase()} at ${p.probability}% — ${p.market.slice(0, 40)} (${p.age})`,
                  );
                }
              }
              addSystem('');
            } catch {
              addError('Failed to fetch oracle profile');
            }
            break;
          }
          case 'stake': {
            // stake <msg_id> truth|false <amount> [days]
            if (!nodeIdentity || !hasSovereignty()) {
              addError("Not connected. Type 'connect' to activate your Agent identity.");
              break;
            }
            const sMsgId = args[0];
            const sSide = args[1]?.toLowerCase();
            const sAmount = parseFloat(args[2]);
            const sDays = parseInt(args[3]) || 1;
            if (
              !sMsgId ||
              !sSide ||
              !['truth', 'false'].includes(sSide) ||
              isNaN(sAmount) ||
              sAmount <= 0
            ) {
              addError('Usage: stake <message_id> truth|false <amount> [days 1-7]');
              addLines([{ text: '  Example: stake a1b2c3d4 truth 0.5 3', type: 'dim' }]);
              break;
              }
              try {
                const stakePayload = {
                  message_id: sMsgId,
                  poster_id: '',
                  side: sSide,
                  amount: sAmount,
                  duration_days: sDays,
                };
                const v = validateEventPayload('stake', stakePayload);
                if (!v.ok) {
                  addError(`Invalid payload: ${v.reason}`);
                  break;
                }
                const sequence = nextSequence();
                const signature = await signEvent(
                  'stake',
                  nodeIdentity.nodeId,
                  sequence,
                  stakePayload,
                );
                const res = await fetch(`${API}/api/mesh/oracle/stake`, {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({
                    staker_id: nodeIdentity.nodeId,
                    message_id: sMsgId,
                    poster_id: '',
                    side: sSide,
                    amount: sAmount,
                    duration_days: sDays,
                    public_key: nodeIdentity.publicKey,
                    public_key_algo: getPublicKeyAlgo(),
                    signature,
                    sequence,
                    protocol_version: PROTOCOL_VERSION,
                  }),
                });
              const data = await res.json();
              if (data.ok) addSystem(`  ${data.detail}`);
              else addError(data.detail);
            } catch {
              addError('Failed to place stake');
            }
            break;
          }
          case 'stakes': {
            // stakes <msg_id> — view stakes on a message
            const stMsgId = args[0];
            if (!stMsgId) {
              addError('Usage: stakes <message_id>');
              break;
            }
            try {
              const res = await fetch(
                `${API}/api/mesh/oracle/stakes/${encodeURIComponent(stMsgId)}`,
              );
              const data = await res.json();
              addSystem('');
              addSystem(`  ORACLE STAKES: ${stMsgId}`);
              addOutput(`    TRUTH: ${data.truth_total ?? 0} oracle rep`);
              for (const s of data.truth_stakers || []) {
                addLines([{ text: `      ${s.node_id}: ${s.amount}`, type: 'dim' }]);
              }
              addOutput(`    FALSE: ${data.false_total ?? 0} oracle rep`);
              for (const s of data.false_stakers || []) {
                addLines([{ text: `      ${s.node_id}: ${s.amount}`, type: 'dim' }]);
              }
              if (data.earliest_expiry) {
                const expires = new Date(data.earliest_expiry * 1000).toLocaleString();
                addLines([{ text: `    Earliest resolution: ${expires}`, type: 'dim' }]);
              }
              addSystem('');
            } catch {
              addError('Failed to fetch stakes');
            }
            break;
          }
          case 'log':
            await cmdLog(parseInt(args[0]) || 5);
            break;
          case 'nearest':
          case 'sdr':
            await cmdNearest(args[0], args[1]);
            break;
          case 'infonet': {
            // infonet — Infonet protocol status
            try {
              const data = await fetchInfonetNodeStatusSnapshot(true);
              setInfonetNodeStatus(data);
              setInfonetNodeStatusError('');
              addSystem('');
              addSystem('  INFONET STATUS');
              addOutput(`    Network:     ${data.network_id || 'sb-testnet-0'}`);
              addOutput(
                `    Events:      ${data.total_events ?? 0} total (${data.active_events ?? 0} active)`,
              );
              addOutput(`    Head Hash:   ${data.head_hash || 'genesis'}`);
              addOutput(`    Known Nodes: ${data.known_nodes ?? 0}`);
              addOutput(`    Chain Size:  ${data.chain_size_kb ?? 0} KB`);
              addOutput(`    Unsigned:    ${data.unsigned_events ?? 0}`);
              addOutput(
                `    Valid:       ${data.valid ? 'YES' : 'NO'} — ${data.validation || '?'}`,
              );
              addLines(buildNodeRuntimeLines(data));
              const types = data.event_types || {};
              if (Object.keys(types).length > 0) {
                addSystem('    Event Breakdown:');
                for (const [t, count] of Object.entries(types)) {
                  addOutput(`      ${String(t).padEnd(16)} ${count}`);
                }
              }
              addSystem('');
            } catch {
              setInfonetNodeStatusError('node runtime unavailable');
              addError('Failed to reach Infonet');
            }
            break;
          }
          case 'node':
            await cmdNode();
            break;
          case 'merkle':
            await cmdMerkle();
            break;
          case 'sync':
            await cmdSync(parseInt(args[0]) || 100);
            break;
          case 'peers': {
            const sub = args[0]?.toLowerCase();
            const current = getInfonetPeers();
            if (!sub) {
              addSystem('');
              addSystem(`  INFONET PEERS (${current.length})`);
              for (const peer of current) {
                addOutput(`    ${peer}`);
              }
              addLines([
                {
                  text: "    note: this is the manual browser sync list; backend participant-node peers come from the local peer store and show up in 'node'",
                  type: 'dim',
                },
              ]);
              addSystem('');
              break;
            }
            if (sub === 'add') {
              const url = args[1];
              if (!url) {
                addError('Usage: peers add <url>');
                break;
              }
              const next = Array.from(new Set([...current, url]));
              setInfonetPeers(next.filter((p) => p !== API));
              addSystem(`  Added peer: ${url}`);
              break;
            }
            if (sub === 'remove') {
              const url = args[1];
              if (!url) {
                addError('Usage: peers remove <url>');
                break;
              }
              const next = current.filter((p) => p !== url);
              setInfonetPeers(next.filter((p) => p !== API));
              addSystem(`  Removed peer: ${url}`);
              break;
            }
            if (sub === 'clear') {
              setInfonetPeers([]);
              addSystem('  Cleared stored peers.');
              break;
            }
            addError('Usage: peers [add|remove|clear] <url>');
            break;
          }
          case 'messages': {
            // messages [gate] — browse Infonet messages
            const msgGate = args[0] || '';
            try {
              const url = msgGate
                ? `${API}/api/mesh/infonet/messages?gate=${encodeURIComponent(msgGate)}&limit=20`
                : `${API}/api/mesh/infonet/messages?limit=20`;
              const headers = msgGate ? await buildGateAccessHeaders(msgGate) : undefined;
              const res = await fetch(url, {
                headers,
              });
              const data = await res.json();
              const msgs = (Array.isArray(data.messages) ? data.messages : []).map(
                (message: InfonetMessageRecord) => normalizeInfonetMessageRecord(message),
              ) as InfonetMessageRecord[];
              addSystem('');
              if (!msgs.length) {
                addSystem(
                  msgGate ? `  No messages in gate '${msgGate}'` : '  No messages on Infonet yet',
                );
              } else {
                addSystem(
                  msgGate
                    ? `  MESSAGES IN g/${msgGate} (${msgs.length})`
                    : `  RECENT MESSAGES (${msgs.length})`,
                );
                for (const m of msgs) {
                  if (m.system_seed) {
                    addSystem(`    ${m.fixed_gate ? 'FIXED GATE NOTICE' : 'GATE NOTICE'} [${m.gate || msgGate || 'infonet'}]`);
                    addLines([{ text: `      ${await describeGateMessage(m)}`, type: 'dim' }]);
                    continue;
                  }
                  const age = Math.floor((Date.now() / 1000 - m.timestamp) / 60);
                  const ageStr = age < 60 ? `${age}m` : `${Math.floor(age / 60)}h`;
                  const gateStr = m.gate ? ` [${m.gate}]` : '';
                  const ephStr = m.ephemeral ? ' (ephemeral)' : '';
                  const encState = gateEnvelopeState(m);
                  const encLabel =
                    encState === 'decrypted'
                      ? ' [enc:open]'
                      : encState === 'locked'
                        ? ' [enc:locked]'
                        : '';
                  addOutput(`    ${m.node_id || ''} ${ageStr} ago${gateStr}${ephStr}${encLabel}`);
                  addLines([{ text: `      ${await describeGateMessage(m)}`, type: 'dim' }]);
                  if (isEncryptedGateEnvelope(m)) {
                    const metaBits = [];
                    if (Number(m.epoch ?? 0) > 0) {
                      metaBits.push(`epoch=${Number(m.epoch ?? 0)}`);
                    }
                    if (m.sender_ref) {
                      metaBits.push(`sender_ref=${String(m.sender_ref)}`);
                    }
                    if (metaBits.length) {
                      addLines([{ text: `      ${metaBits.join(' ')}`, type: 'dim' }]);
                    }
                  }
                  addLines([{ text: `      id: ${m.event_id.slice(0, 16)}...`, type: 'dim' }]);
                }
              }
              addSystem('');
            } catch {
              addError('Failed to fetch messages');
            }
            break;
          }
          case 'event': {
            // event <event_id> — look up an Infonet event
            const evtId = args[0];
            if (!evtId) {
              addError('Usage: event <event_id>');
              break;
            }
            try {
              const res = await fetch(`${API}/api/mesh/infonet/event/${encodeURIComponent(evtId)}`);
              const data = await res.json();
              if (data.ok === false) {
                addError(data.detail);
                break;
              }
              addSystem('');
              addSystem(`  INFONET EVENT`);
              addOutput(`    ID:        ${data.event_id}`);
              addOutput(`    Type:      ${data.event_type}`);
              addOutput(`    Node:      ${data.node_id}`);
              addOutput(`    Seq:       ${data.sequence}`);
              addOutput(`    Prev Hash: ${(data.prev_hash || '').slice(0, 16)}...`);
              addOutput(`    Network:   ${data.network_id || '?'}`);
              const ts = new Date(data.timestamp * 1000).toLocaleString();
              addOutput(`    Time:      ${ts}`);
              if (data.signature) {
                addOutput(`    Signature: ${data.signature.slice(0, 32)}...`);
              }
              addSystem('    Payload:');
              const payload = data.payload || {};
              for (const [k, v] of Object.entries(payload)) {
                if (k.startsWith('_')) continue;
                addLines([{ text: `      ${k}: ${String(v).slice(0, 60)}`, type: 'dim' }]);
              }
              addSystem('');
            } catch {
              addError('Failed to fetch event');
            }
            break;
          }
          case 'ledger': {
            // ledger [node_id] — view a node's Infonet activity
            const ledgerTarget = args[0] || (nodeIdentity?.nodeId ?? '');
            if (!ledgerTarget) {
              addError("Usage: ledger <node_id>  (or just 'ledger' for your own)");
              break;
            }
            try {
              const res = await fetch(
                `${API}/api/mesh/infonet/node/${encodeURIComponent(ledgerTarget)}?limit=20`,
              );
              const data = await res.json();
              const events = data.events || [];
              addSystem('');
              if (!events.length) {
                addSystem(`  No Infonet activity for ${ledgerTarget}`);
              } else {
                addSystem(`  INFONET ACTIVITY: ${ledgerTarget} (${events.length} events)`);
                for (const e of events) {
                  const age = Math.floor((Date.now() / 1000 - e.timestamp) / 60);
                  const ageStr =
                    age < 60
                      ? `${age}m`
                      : age < 1440
                        ? `${Math.floor(age / 60)}h`
                        : `${Math.floor(age / 1440)}d`;
                  const payload = e.payload || {};
                  let detail = '';
                  if (e.event_type === 'message' || e.event_type === 'gate_message') {
                    detail = (payload.message || '').slice(0, 40);
                  } else if (e.event_type === 'vote') {
                    detail = `${payload.vote > 0 ? '+1' : '-1'} on ${payload.target_id}`;
                  } else if (e.event_type === 'gate_create') {
                    detail = `created g/${payload.gate_id}`;
                  } else if (e.event_type === 'prediction') {
                    detail = `${payload.side} on ${(payload.market_title || '').slice(0, 30)}`;
                  } else if (e.event_type === 'stake') {
                    detail = `${payload.side} ${payload.amount} on ${payload.message_id}`;
                  } else if (e.event_type === 'key_rotate') {
                    detail = `rotated from ${String(payload.old_node_id || '').slice(0, 12)}`;
                  } else if (e.event_type === 'key_revoke') {
                    const until = payload.grace_until
                      ? new Date(Number(payload.grace_until) * 1000).toLocaleString()
                      : 'unknown';
                    detail = `revoked key (grace until ${until})`;
                  }
                  addOutput(`    [${e.event_type.padEnd(14)}] ${ageStr} ago  ${detail}`);
                }
              }
              addSystem('');
            } catch {
              addError('Failed to fetch node activity');
            }
            break;
          }
          case 'rotate':
            await cmdRotate();
            break;
          case 'revoke':
            await cmdRevoke(args);
            break;
          // ─── Encrypted DM Commands ───────────────────────────
          case 'dm': {
            if (!nodeIdentity || !hasSovereignty()) {
              addError("Not connected. Type 'connect' to activate your Agent identity.");
              break;
            }
            const sub = args[0]?.toLowerCase();

            // dm add <agent_id> [alias]
            if (sub === 'add') {
              const targetId = args[1];
              if (!targetId) {
                addError('Usage: dm add <agent_id> [alias]');
                break;
              }
              try {
                const res = await fetch(
                  `${API}/api/mesh/dm/pubkey?agent_id=${encodeURIComponent(targetId)}`,
                );
                const data = await res.json();
                if (!data.ok || !data.dh_pub_key) {
                  addError('Agent not found or has no DM keys.');
                  break;
                }
                const alias = args[2] || undefined;
                addContact(targetId, data.dh_pub_key, alias, data.dh_algo);
                addSystem(`  Contact added: ${targetId}${alias ? ` (${alias})` : ''}`);
              } catch {
                addError('Failed to fetch agent key');
              }
              break;
            }

            // dm block <agent_id>
            if (sub === 'block') {
              const targetId = args[1];
              if (!targetId) {
                addError('Usage: dm block <agent_id>');
                break;
              }
              blockContact(targetId);
              try {
                const sequence = nextSequence();
                const blockPayload = { blocked_id: targetId, action: 'block' };
                const v = validateEventPayload('dm_block', blockPayload);
                if (!v.ok) {
                  addError(`Invalid payload: ${v.reason}`);
                  break;
                }
                const signature = await signEvent(
                  'dm_block',
                  nodeIdentity.nodeId,
                  sequence,
                  blockPayload,
                );
                await fetch(`${API}/api/mesh/dm/block`, {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({
                    agent_id: nodeIdentity.nodeId,
                    blocked_id: targetId,
                    action: 'block',
                    public_key: nodeIdentity.publicKey,
                    public_key_algo: getPublicKeyAlgo(),
                    signature,
                    sequence,
                    protocol_version: PROTOCOL_VERSION,
                  }),
                });
              } catch {
                /* local block still works */
              }
              addSystem(`  Blocked ${targetId}. Their messages will be dropped.`);
              break;
            }

            // dm unblock <agent_id>
            if (sub === 'unblock') {
              const targetId = args[1];
              if (!targetId) {
                addError('Usage: dm unblock <agent_id>');
                break;
              }
              unblockContact(targetId);
              try {
                const sequence = nextSequence();
                const blockPayload = { blocked_id: targetId, action: 'unblock' };
                const v = validateEventPayload('dm_block', blockPayload);
                if (!v.ok) {
                  addError(`Invalid payload: ${v.reason}`);
                  break;
                }
                const signature = await signEvent(
                  'dm_block',
                  nodeIdentity.nodeId,
                  sequence,
                  blockPayload,
                );
                await fetch(`${API}/api/mesh/dm/block`, {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({
                    agent_id: nodeIdentity.nodeId,
                    blocked_id: targetId,
                    action: 'unblock',
                    public_key: nodeIdentity.publicKey,
                    public_key_algo: getPublicKeyAlgo(),
                    signature,
                    sequence,
                    protocol_version: PROTOCOL_VERSION,
                  }),
                });
              } catch {
                /* local unblock still works */
              }
              addSystem(`  Unblocked ${targetId}.`);
              break;
            }

            // dm notify on|off
            if (sub === 'notify') {
              const val = args[1]?.toLowerCase();
              if (val === 'on') {
                setDMNotify(true);
                addSystem('  DM notifications ON.');
              } else if (val === 'off') {
                setDMNotify(false);
                addSystem('  DM notifications OFF.');
                if (onDmCount) onDmCount(0);
              } else {
                addSystem(`  DM notifications: ${getDMNotify() ? 'ON' : 'OFF'}`);
                addLines([{ text: '  Usage: dm notify on|off', type: 'dim' }]);
              }
              break;
            }

            // dm <agent_id> <message> — direct one-liner send
            if (sub && sub.startsWith('!sb_')) {
              const msg = args.slice(1).join(' ');
              if (!msg) {
                // Start interactive DM with this recipient
                setDmDest(sub);
                setDmStep('msg');
                addSystem('');
                addSystem(`  DM to ${sub}`);
                addLines([{ text: '  Type your private message:', type: 'dim' }]);
                addSystem('');
                break;
              }
              await doDMSend(sub, msg);
              break;
            }

            // bare "dm" — interactive flow
            if (!sub) {
              addSystem('');
              addSystem('  ENCRYPTED DM');
              addLines([{ text: '  Enter recipient Agent ID (e.g. !sb_a3f2c891):', type: 'dim' }]);
              addSystem('');
              setDmStep('dest');
              break;
            }

            addError('Usage: dm [agent_id] [msg] | dm add/block/unblock/notify');
            break;
          }

          case 'inbox': {
            if (!nodeIdentity || !hasSovereignty()) {
              addError("Not connected. Type 'connect' to activate your Agent identity.");
              break;
            }
            addSystem('  Checking dead drop...');
            try {
              const claims = await buildMailboxClaims(getContacts());
              const data = await pollDmMailboxes(API, nodeIdentity, claims);
              const msgs = data.messages || [];
              if (msgs.length === 0) {
                addSystem('  No pending messages.');
                addSystem('');
                break;
              }
              addSystem(`  ${msgs.length} message${msgs.length > 1 ? 's' : ''} retrieved:`);
              addSystem('');
              for (const m of msgs) {
                const age = Math.floor((Date.now() / 1000 - m.timestamp) / 60);
                const ageStr = age < 60 ? `${age}m ago` : `${Math.floor(age / 60)}h ago`;
                try {
                  // Get sender's DH key
                  const contacts = getContacts();
                  let senderDH = contacts[m.sender_id]?.dhPubKey;
                  if (!senderDH) {
                    const keyRes = await fetch(
                      `${API}/api/mesh/dm/pubkey?agent_id=${encodeURIComponent(m.sender_id)}`,
                    );
                    const keyData = await keyRes.json();
                    if (keyData.ok && keyData.dh_pub_key) {
                      senderDH = keyData.dh_pub_key as string;
                      addContact(m.sender_id, senderDH!, undefined, keyData.dh_algo);
                    }
                  }
                  if (!senderDH) {
                    addOutput(`  [${m.sender_id}] ${ageStr} — (cannot decrypt: no key)`);
                    continue;
                  }
                  let plaintext = '';
                  try {
                    plaintext = await ratchetDecryptDM(m.sender_id, m.ciphertext);
                  } catch {
                    const sharedKey = await deriveSharedKey(senderDH);
                    plaintext = await decryptDM(m.ciphertext, sharedKey);
                  }
                  addOutput(`  [${m.sender_id}] ${ageStr}`);
                  addLines([{ text: `    ${plaintext}`, type: 'output' }]);
                } catch {
                  addOutput(`  [${m.sender_id}] ${ageStr} — (decryption failed)`);
                }
                addSystem('');
              }
              // Clear badge
              if (onDmCount) onDmCount(0);
            } catch {
              addError('Failed to check inbox');
            }
            break;
          }

          case 'contacts': {
            const contacts = getContacts();
            const ids = Object.keys(contacts);
            if (ids.length === 0) {
              addSystem("  No contacts. Use 'dm add <agent_id>' to add one.");
              break;
            }
            addSystem('');
            addSystem(`  CONTACTS (${ids.length})`);
            for (const id of ids) {
              const c = contacts[id];
              const status = c.blocked ? 'BLOCKED' : 'active';
              const alias = c.alias ? ` (${c.alias})` : '';
              addOutput(`    ${id}${alias} — ${status}`);
            }
            addSystem('');
            break;
          }

          default: {
            const suggestions: Record<string, string> = {
              stat: 'status',
              stats: 'status',
              info: 'status',
              signal: 'signals',
              listen: 'signals',
              rx: 'signals',
              msg: 'send',
              message: 'send',
              tx: 'send',
              transmit: 'send',
              logs: 'log',
              history: 'log',
              audit: 'log',
              find: 'nearest',
              locate: 'nearest',
              meshtastic: 'mesh',
              lora: 'mesh',
              radio: 'mesh',
              region: 'mesh',
              tutorial: 'guide',
              intro: 'guide',
              howto: 'guide',
              how: 'guide',
              '?': 'help',
              commands: 'help',
              id: 'whoami',
              identity: 'whoami',
              me: 'whoami',
              node: 'whoami',
              agent: 'whoami',
              reputation: 'rep',
              score: 'rep',
              upvote: 'vote',
              downvote: 'vote',
              community: 'gates',
              rooms: 'gates',
              channels: 'gates',
              bet: 'predict',
              prediction: 'predict',
              forecast: 'predict',
              market: 'markets',
              bets: 'markets',
              predictions: 'markets',
              headlines: 'news',
              intel: 'dossier',
              brief: 'dossier',
              dossier: 'dossier',
              lookup: 'place',
              location: 'place',
              geo: 'place',
              jet: 'jets',
              aircraft: 'jets',
              plane: 'jets',
              recon: 'apps',
              tools: 'apps',
              surfaces: 'apps',
              staking: 'stake',
              wager: 'stake',
              blockchain: 'infonet',
              hashchain: 'infonet',
              chain: 'infonet',
              block: 'infonet',
              merkle: 'merkle',
              root: 'merkle',
              sync: 'sync',
              verify: 'sync',
              msgs: 'messages',
              browse: 'messages',
              feed: 'messages',
              events: 'infonet',
              activity: 'ledger',
              net: 'infonet',
              mail: 'inbox',
              email: 'inbox',
              unread: 'inbox',
              check: 'inbox',
              pm: 'dm',
              whisper: 'dm',
              private: 'dm',
              encrypt: 'dm',
              contact: 'contacts',
              friends: 'contacts',
              people: 'contacts',
            };
            const suggestion = suggestions[cmd.toLowerCase()];
            if (suggestion) {
              addLines([{ text: `  Did you mean '${suggestion}'?`, type: 'dim' }]);
            } else {
              addLines([
                {
                  text: `  '${cmd}' is not a command. Type 'help' to see what's available.`,
                  type: 'dim',
                },
              ]);
            }
          }
        }
      } catch (err) {
        const msg =
          typeof err === 'object' && err !== null && 'message' in err
            ? String((err as { message?: string }).message)
            : '';
        addError(msg || 'Something went wrong');
      }
      setBusy(false);
    },
    [
      addLines,
      addOutput,
      addError,
      addSystem,
      cmdStatus,
      cmdNode,
      cmdSignals,
      cmdMerkle,
      cmdSync,
      cmdRevoke,
      cmdRotate,
      getInfonetPeers,
      setInfonetPeers,
      doSend,
      doMeshSend,
      doDMSend,
      cmdLog,
      cmdNearest,
      sendStep,
      sendDest,
      startInteractiveSend,
      dmStep,
      dmDest,
      meshRegion,
      meshRoots,
      sovereigntyPending,
      terminalWriteLockReason,
      nodeIdentity,
      onDmCount,
      surfacePanel,
      activeGateComposeId,
      gateReplyTarget,
      gateAccessGranted,
      expandedGateId,
      voteDirections,
      voteScopeKey,
      wormholeSecureRequired,
      wormholeReadyState,
      anonymousModeEnabled,
      anonymousModeReady,
      privateLaneLabel,
      privateLaneDetail,
      postGateMessage,
      requestGateAccess,
      openGateCard,
      describeGateMessage,
      cmdApps,
      cmdNews,
      cmdJets,
      cmdPlaces,
      cmdDossier,
      cmdShodan,
    ],
  );

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const handleWormholeReady = (event: Event) => {
      const target = (event as CustomEvent<{ target?: string }>).detail?.target || 'gates';
      if (target !== 'gates') return;
      setGateAccessGranted(true);
      setGateAccessPromptOpen(false);
      setPendingGateCommand(null);
      setSurfacePanel('gates');
      setTimeout(() => {
        void exec('gates');
        inputRef.current?.focus();
      }, 40);
    };
    window.addEventListener(WORMHOLE_READY_EVENT, handleWormholeReady as EventListener);
    return () => {
      window.removeEventListener(WORMHOLE_READY_EVENT, handleWormholeReady as EventListener);
    };
  }, [exec]);

  const handleKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !busy) {
      exec(input);
      setInput('');
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      if (history.length > 0) {
        const next = Math.min(histIdx + 1, history.length - 1);
        setHistIdx(next);
        setInput(history[next]);
      }
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      if (histIdx > 0) {
        setHistIdx(histIdx - 1);
        setInput(history[histIdx - 1]);
      } else {
        setHistIdx(-1);
        setInput('');
      }
    }
  };

  const runQuickCommand = useCallback(
    (command: string) => {
      if (busy) return;
      setInput('');
      void exec(command);
    },
    [busy, exec],
  );

  useEffect(() => {
    runQuickCommandRef.current = runQuickCommand;
  }, [runQuickCommand]);

  const openSurface = useCallback(
    (panel: (typeof QUICK_LAUNCHES)[number]['panel']) => {
      if (panel === 'gates' && !gateAccessGranted) {
        requestGateAccess('gates');
        return;
      }
      setSurfacePanel(panel);
    },
    [gateAccessGranted, requestGateAccess],
  );

  const chipTone = (tone: (typeof QUICK_LAUNCHES)[number]['tone']) => {
    switch (tone) {
      case 'green':
        return 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300 hover:border-emerald-400/70 hover:bg-emerald-500/15';
      case 'pink':
        return 'border-fuchsia-500/40 bg-fuchsia-500/10 text-fuchsia-300 hover:border-fuchsia-400/70 hover:bg-fuchsia-500/15';
      case 'yellow':
        return 'border-amber-400/40 bg-amber-400/10 text-amber-200 hover:border-amber-300/70 hover:bg-amber-400/15';
      default:
        return 'border-cyan-500/40 bg-cyan-500/10 text-cyan-300 hover:border-cyan-400/70 hover:bg-cyan-500/15';
    }
  };

  const lineColor = (type: TermLine['type']) => {
    switch (type) {
      case 'input':
        return 'text-cyan-200';
      case 'output':
        return 'text-slate-200';
      case 'error':
        return 'text-rose-300';
      case 'system':
        return 'text-cyan-300/85';
      case 'header':
        return 'text-amber-200 font-semibold tracking-[0.18em]';
      case 'dim':
        return 'text-slate-500';
    }
  };

  const renderStyledLine = (line: TermLine, index: number) => {
    const tokenClasses: Array<{ pattern: RegExp; className: string }> = [
      { pattern: /\b(MESHTASTIC|MESH|RADIO)\b/gi, className: 'text-emerald-300' },
      { pattern: /\b(GATES?|COMMONS|INBOX|DM|DEAD DROP)\b/gi, className: 'text-fuchsia-300' },
      { pattern: /\b(MARKETS?|ORACLE|COMMANDS?|OPS|DOSSIER|PREDICT)\b/gi, className: 'text-amber-200' },
      { pattern: /\b(INFONET|SHODAN|STATUS|SIGNALS?)\b/gi, className: 'text-cyan-300' },
      { pattern: /\b(LOCKED|READ ONLY|FAILED|ERROR|DENIED)\b/gi, className: 'text-rose-300' },
      { pattern: /\b(READY|ACTIVE|OPEN|UNLOCK|YES)\b/gi, className: 'text-emerald-300' },
    ];

    const segments: Array<{ text: string; className?: string }> = [{ text: line.text }];
    for (const token of tokenClasses) {
      const nextSegments: Array<{ text: string; className?: string }> = [];
      for (const segment of segments) {
        if (segment.className) {
          nextSegments.push(segment);
          continue;
        }
        let lastIndex = 0;
        const regex = new RegExp(token.pattern.source, token.pattern.flags);
        let match: RegExpExecArray | null;
        while ((match = regex.exec(segment.text)) !== null) {
          if (match.index > lastIndex) {
            nextSegments.push({ text: segment.text.slice(lastIndex, match.index) });
          }
          nextSegments.push({ text: match[0], className: token.className });
          lastIndex = match.index + match[0].length;
        }
        if (lastIndex < segment.text.length) {
          nextSegments.push({ text: segment.text.slice(lastIndex) });
        }
      }
      segments.splice(0, segments.length, ...nextSegments);
    }

    const lineChrome =
      line.type === 'header'
        ? 'border-l-2 border-amber-300/35 pl-3 bg-amber-400/[0.03]'
        : line.type === 'error'
          ? 'border-l-2 border-rose-400/35 pl-3 bg-rose-400/[0.03]'
          : line.type === 'system'
            ? 'border-l border-cyan-400/20 pl-3'
            : line.type === 'input'
              ? 'border-l border-cyan-400/18 pl-3'
              : 'pl-3';

    const content = (
      <>
        {segments.map((segment, segmentIndex) => (
          <span key={`${index}-${segmentIndex}`} className={segment.className}>
            {segment.text || '\u00A0'}
          </span>
        ))}
      </>
    );

    if (line.actionCommand) {
      return (
        <button
          key={index}
          type="button"
          onClick={() => runQuickCommand(line.actionCommand!)}
          className={`group flex w-full items-center justify-between gap-3 text-[12px] leading-[1.8] whitespace-pre-wrap break-all border border-fuchsia-500/15 bg-fuchsia-500/[0.03] pr-3 text-left font-mono transition-all hover:border-fuchsia-400/35 hover:bg-fuchsia-500/[0.08] ${lineColor(line.type)} ${lineChrome}`}
        >
          <span className="min-w-0 flex-1">{content}</span>
          <span className="shrink-0 border border-fuchsia-500/25 px-2 py-0.5 text-[13px] tracking-[0.18em] text-fuchsia-200 transition-colors group-hover:border-fuchsia-400/45 group-hover:text-fuchsia-100">
            {line.actionLabel || 'OPEN'}
          </span>
        </button>
      );
    }

    return (
      <div
        key={index}
        className={`text-[12px] leading-[1.8] whitespace-pre-wrap break-all font-mono ${lineColor(line.type)} ${lineChrome}`}
      >
        {content}
      </div>
    );
  };

  const renderSurfacePanel = () => {
    const cardBase =
      'border bg-black/55 px-4 py-3 text-left font-mono transition-all hover:-translate-y-0.5';

    switch (surfacePanel) {
      case 'help':
        return (
          <div className="grid gap-3 md:grid-cols-3">
            {[
              ['MESH / RADIO', 'Public mesh root watch, signals, and LongFast send.', 'mesh', 'border-emerald-500/25 text-emerald-300', 'help mesh'],
              ['GATES (EXPERIMENTAL ENCRYPTION)', 'Open gate details, unlock a gate face, and post into the commons.', 'gates', 'border-fuchsia-500/25 text-fuchsia-300', 'help gates'],
              ['PRIVATE DM INBOX', 'Contacts, inbox previews, and private message flows.', 'inbox', 'border-cyan-500/25 text-cyan-300', 'help inbox'],
              ['MARKETS / ORACLE', 'Prediction markets, oracle profiles, and stakes.', 'markets', 'border-amber-400/25 text-amber-200', 'help markets'],
              ['INFONET', 'Messages, ledger, sync, and event views.', 'gates', 'border-cyan-500/25 text-cyan-300', 'help infonet'],
              ['OPS / DOSSIER', 'News, dossiers, Shodan, places, and aircraft.', 'apps', 'border-amber-400/25 text-amber-200', 'help ops'],
            ].map(([title, desc, _panel, tone, command]) => (
              <button
                key={title}
                type="button"
                onClick={() => runQuickCommand(String(command))}
                className={`${cardBase} ${tone}`}
              >
                <div className="text-sm tracking-[0.24em]">{title}</div>
                <div className="mt-2 text-[11px] leading-6 text-slate-400">{desc}</div>
                <div className="mt-3 text-[12px] tracking-[0.16em] text-slate-500">
                  {String(command)}
                </div>
              </button>
            ))}
          </div>
        );
      case 'apps':
        return (
          <div className="grid gap-3 md:grid-cols-3">
            {[
              ['MARKETS', 'Browse prediction markets', () => runQuickCommand('markets'), 'border-amber-400/25 text-amber-200'],
              ['DOSSIER PRESETS', 'Open guided dossier presets', () => openSurface('dossier'), 'border-fuchsia-500/25 text-fuchsia-300'],
              ['NEWS', 'Pull latest headlines', () => runQuickCommand('news'), 'border-cyan-500/25 text-cyan-300'],
              ['SHODAN', 'Search exposed hosts and services', () => runQuickCommand('shodan'), 'border-cyan-500/25 text-cyan-300'],
              ['MESH RADIO', 'Open the public mesh command lane', () => openSurface('mesh'), 'border-emerald-500/25 text-emerald-300'],
              ['PRIVATE DM INBOX', 'Check the experimental private dead drop', () => openSurface('inbox'), 'border-fuchsia-500/25 text-fuchsia-300'],
            ].map(([title, desc, action, tone]) => (
              <button key={title as string} type="button" onClick={action as () => void} className={`${cardBase} ${tone}`}>
                <div className="text-sm tracking-[0.24em]">{title as string}</div>
                <div className="mt-2 text-[11px] leading-6 text-slate-400">{desc as string}</div>
              </button>
            ))}
          </div>
        );
      case 'dossier':
        return (
          <div className="grid gap-3 md:grid-cols-3">
            {[
              ['PERSON', 'dossier elon musk', 'Build a quick person brief by name'],
              ['PLACE', 'dossier tel aviv', 'Summarize a place-based brief'],
              ['ORG', 'dossier spacex', 'Scan headlines, signals, and markets around an org'],
              ['JET / PLANE', 'jet musk', 'Look up operator or aircraft-linked records'],
              ['SITE', 'place ramstein', 'Check airports, bases, datacenters, power nodes'],
              ['NEWS FLASH', 'news taiwan', 'Pull a fast topical news sweep'],
            ].map(([title, command, desc]) => (
              <button
                key={title}
                type="button"
                onClick={() => runQuickCommand(String(command))}
                className={`${cardBase} border-fuchsia-500/25 text-fuchsia-300 hover:border-fuchsia-400/45 hover:bg-fuchsia-500/10`}
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="text-sm tracking-[0.24em]">{title}</div>
                  <div className="text-[12px] tracking-[0.16em] text-amber-200">{command}</div>
                </div>
                <div className="mt-2 text-[11px] leading-6 text-slate-400">{desc}</div>
              </button>
            ))}
          </div>
        );
      case 'mesh':
        return (
          <div className="space-y-3">
            <div className="grid gap-3 md:grid-cols-2">
              <div className="border border-emerald-500/20 bg-black/45 px-4 py-3 font-mono">
                <div className="text-sm tracking-[0.24em] text-emerald-300">PUBLIC MESH LANE</div>
                <div className="mt-2 text-[11px] leading-6 text-slate-300">
                  {publicAgentReady
                    ? `Public Agent active as ${nodeIdentity?.nodeId || 'unknown'}`
                    : 'No public Agent yet. Type connect to create one for mesh posting.'}
                </div>
                <div className="mt-2 text-sm leading-5 text-emerald-200/75">
                  Meshtastic traffic is public / observable. Wormhole is not required here.
                </div>
              </div>
              <div className="border border-cyan-500/20 bg-black/45 px-4 py-3 font-mono">
                <div className="text-sm tracking-[0.24em] text-cyan-300">WORMHOLE OBFUSCATED LANE</div>
                <div className="mt-2 text-[11px] leading-6 text-slate-300">
                  {privateLaneLabel}
                </div>
                <div className="mt-2 text-sm leading-5 text-cyan-200/75">
                  {privateLaneDetail}
                </div>
              </div>
            </div>
            <div className="grid gap-3 md:grid-cols-3">
              {[
                !publicAgentReady
                  ? ['CONNECT', 'Create a public Agent identity for mesh posting', () => runQuickCommand('connect')]
                  : null,
                ['LISTEN', `Watch ${meshRegion} public mesh traffic`, () => runQuickCommand('mesh listen 12')],
                ['CHANNELS', 'See regional activity counts', () => runQuickCommand('mesh channels')],
                ['SIGNALS', 'Open the wider intercept board', () => runQuickCommand('signals 12')],
              ]
                .filter((x): x is [string, string, () => void] => x !== null)
                .map(([title, desc, action]) => (
                <button
                  key={title}
                  type="button"
                  onClick={action}
                  className={`${cardBase} border-emerald-500/25 text-emerald-300`}
                >
                  <div className="text-sm tracking-[0.24em]">{title}</div>
                  <div className="mt-2 text-[11px] leading-6 text-slate-400">{desc}</div>
                </button>
              ))}
            </div>
            <div className="text-sm tracking-[0.26em] text-emerald-300">MESH ROOT CARDS</div>
            {surfaceMeshLoading ? (
              <div className="border border-emerald-500/20 bg-black/45 px-4 py-5 text-[11px] font-mono text-slate-400">
                Loading mesh channels...
              </div>
            ) : (
              <div className="grid gap-3 md:grid-cols-4">
                {Object.entries(surfaceMeshCounts)
                  .sort((a, b) => b[1] - a[1])
                  .slice(0, 8)
                  .map(([region, count]) => (
                    <div
                      key={region}
                      className={`border px-4 py-3 font-mono transition-all hover:-translate-y-0.5 ${
                        region === meshRegion
                          ? 'border-emerald-400/45 bg-emerald-500/10'
                          : 'border-emerald-500/20 bg-black/50 hover:border-emerald-400/35 hover:bg-emerald-500/6'
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <div className="text-[11px] tracking-[0.22em] text-emerald-200">{region}</div>
                        <div className="text-sm text-emerald-300">{count}</div>
                      </div>
                      <div className="mt-3 flex flex-wrap gap-2">
                        <button
                          type="button"
                          onClick={() => {
                            setMeshRegion(region);
                            runQuickCommand(`mesh listen 12`);
                          }}
                          className="border border-emerald-500/20 bg-emerald-500/8 px-3 py-1.5 text-[13px] tracking-[0.18em] text-emerald-300 hover:bg-emerald-500/14"
                        >
                          LISTEN
                        </button>
                        <button
                          type="button"
                          onClick={() => setMeshRegion(region)}
                          className="border border-cyan-500/20 bg-cyan-500/8 px-3 py-1.5 text-[13px] tracking-[0.18em] text-cyan-300 hover:bg-cyan-500/14"
                        >
                          SELECT
                        </button>
                      </div>
                    </div>
                  ))}
              </div>
            )}
          </div>
        );
      case 'markets':
        return (
          <div className="space-y-3">
            <div className="grid gap-3 md:grid-cols-3">
              {[
                ['ALL MARKETS', 'Open the current market board', () => runQuickCommand('markets')],
                ['TAIWAN', 'Search Taiwan-linked markets', () => runQuickCommand('markets taiwan')],
                ['BITCOIN', 'Search BTC-linked markets', () => runQuickCommand('markets bitcoin')],
              ].map(([title, desc, action]) => (
                <button
                  key={title as string}
                  type="button"
                  onClick={action as () => void}
                  className={`${cardBase} border-amber-400/25 text-amber-200`}
                >
                  <div className="text-sm tracking-[0.24em]">{title as string}</div>
                  <div className="mt-2 text-[11px] leading-6 text-slate-400">{desc as string}</div>
                </button>
              ))}
            </div>
            <div className="text-sm tracking-[0.26em] text-amber-200">LIVE MARKET CARDS</div>
            {surfaceMarketsLoading ? (
              <div className="border border-amber-400/20 bg-black/45 px-4 py-5 text-[11px] font-mono text-slate-400">
                Loading market cards...
              </div>
            ) : (
              <div className="grid gap-3 md:grid-cols-3">
                {surfaceMarkets.map((market, idx) => {
                  const title = pickRecordText(market, ['title', 'question']) || `market-${idx + 1}`;
                  const category = pickRecordText(market, ['category']) || 'market';
                  const pctValue =
                    typeof market.consensus_pct === 'number'
                      ? `${market.consensus_pct}%`
                      : typeof market.probability === 'number'
                        ? `${market.probability}%`
                        : '?%';
                  const expanded = expandedMarketIndex === idx;
                  return (
                    <div
                      key={`${title}-${idx}`}
                      className="border border-amber-400/20 bg-black/50 px-4 py-4 font-mono transition-all hover:-translate-y-0.5 hover:border-amber-300/45 hover:bg-amber-400/6"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="text-[11px] leading-6 text-amber-100">{title}</div>
                        <div className="border border-amber-400/20 bg-amber-400/8 px-2 py-1 text-[13px] text-amber-200">
                          {pctValue}
                        </div>
                      </div>
                      <div className="mt-2 text-[13px] tracking-[0.16em] text-slate-500">{category}</div>
                      <div className="mt-4 flex flex-wrap gap-2">
                        <button
                          type="button"
                          onClick={() =>
                            setExpandedMarketIndex((prev) => (prev === idx ? null : idx))
                          }
                          className="border border-amber-400/20 bg-amber-400/8 px-3 py-1.5 text-[13px] tracking-[0.18em] text-amber-200 hover:bg-amber-400/14"
                        >
                          {expanded ? 'HIDE' : 'OPEN'}
                        </button>
                        <button
                          type="button"
                          onClick={() => runQuickCommand(`markets ${title}`)}
                          className="border border-amber-400/20 bg-amber-400/8 px-3 py-1.5 text-[13px] tracking-[0.18em] text-amber-200 hover:bg-amber-400/14"
                        >
                          BOARD
                        </button>
                        <button
                          type="button"
                          onClick={() => runQuickCommand(`oracle ${nodeIdentity?.nodeId || ''}`.trim())}
                          className="border border-cyan-500/20 bg-cyan-500/8 px-3 py-1.5 text-[13px] tracking-[0.18em] text-cyan-300 hover:bg-cyan-500/14"
                        >
                          PROFILE
                        </button>
                      </div>
                      {expanded && (
                        <div className="mt-4 border border-amber-400/15 bg-black/35 px-3 py-3 text-sm leading-6 text-slate-300">
                          <div className="text-[13px] tracking-[0.18em] text-amber-200">MARKET DETAIL</div>
                          <div className="mt-2">Question: {title}</div>
                          <div>Category: {category}</div>
                          <div>Consensus: {pctValue}</div>
                          <div className="mt-3 text-slate-500">
                            Use the board view to search for the exact market title, then route into prediction or oracle profile commands from the command line when you need precision.
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        );
      case 'inbox':
        const contactEntries = Object.entries(getContacts());
        return (
          <div className="space-y-3">
            <div className="grid gap-3 md:grid-cols-3">
              {[
                ['CHECK INBOX', 'Pull pending experimental obfuscated DM messages', () => runQuickCommand('inbox')],
                ['CONTACTS', 'Show saved obfuscated contacts', () => runQuickCommand('contacts')],
                ['START DM', 'Begin an encrypted obfuscated message flow', () => runQuickCommand('dm')],
              ].map(([title, desc, action]) => (
                <button
                  key={title as string}
                  type="button"
                  onClick={action as () => void}
                  className={`${cardBase} border-cyan-500/25 text-cyan-300`}
                >
                  <div className="text-sm tracking-[0.24em]">{title as string}</div>
                  <div className="mt-2 text-[11px] leading-6 text-slate-400">{desc as string}</div>
                </button>
              ))}
            </div>
            <div className="text-sm tracking-[0.26em] text-cyan-300">EXPERIMENTAL PRIVATE DM INBOX</div>
            {surfaceInboxLoading ? (
              <div className="border border-cyan-500/20 bg-black/45 px-4 py-5 text-[11px] font-mono text-slate-400">
                Checking inbox...
              </div>
            ) : surfaceInbox.length === 0 ? (
              <div className="border border-cyan-500/20 bg-black/45 px-4 py-5 text-[11px] font-mono text-slate-400">
                No inbox previews available.
              </div>
            ) : (
              <div className="grid gap-3 md:grid-cols-2">
                {surfaceInbox.map((message, idx) => (
                  <div
                    key={`${message.sender}-${idx}`}
                    className="border border-cyan-500/20 bg-black/50 px-4 py-4 font-mono transition-all hover:-translate-y-0.5 hover:border-cyan-400/35 hover:bg-cyan-500/6"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div className="text-[11px] tracking-[0.18em] text-cyan-200">{message.sender}</div>
                      <div className="text-[13px] text-slate-500">{message.age}</div>
                    </div>
                    <div className="mt-3 text-[11px] leading-6 text-slate-300">
                      {message.text}
                    </div>
                    <div className="mt-4 flex flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={() => runQuickCommand('inbox')}
                        className="border border-cyan-500/20 bg-cyan-500/8 px-3 py-1.5 text-[13px] tracking-[0.18em] text-cyan-300 hover:bg-cyan-500/14"
                      >
                        OPEN
                      </button>
                      <button
                        type="button"
                        onClick={() => runQuickCommand(`dm ${message.sender}`)}
                        className="border border-fuchsia-500/20 bg-fuchsia-500/8 px-3 py-1.5 text-[13px] tracking-[0.18em] text-fuchsia-300 hover:bg-fuchsia-500/14"
                      >
                        REPLY
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
            <div className="text-sm tracking-[0.26em] text-fuchsia-300">CONTACT CARDS</div>
            {contactEntries.length === 0 ? (
              <div className="border border-fuchsia-500/20 bg-black/45 px-4 py-5 text-[11px] font-mono text-slate-400">
                No saved contacts yet.
              </div>
            ) : (
              <div className="grid gap-3 md:grid-cols-2">
                {contactEntries.slice(0, 6).map(([contactId, contact]) => (
                  <div
                    key={contactId}
                    className="border border-fuchsia-500/20 bg-black/50 px-4 py-4 font-mono transition-all hover:-translate-y-0.5 hover:border-fuchsia-400/35 hover:bg-fuchsia-500/6"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div className="text-[11px] tracking-[0.18em] text-fuchsia-200">
                        {contact.alias || contactId}
                      </div>
                      <div className="text-[13px] text-slate-500">
                        {contact.blocked ? 'BLOCKED' : 'ACTIVE'}
                      </div>
                    </div>
                    {contact.alias && (
                      <div className="mt-1 text-[13px] tracking-[0.14em] text-slate-500">{contactId}</div>
                    )}
                    <div className="mt-4 flex flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={() => runQuickCommand(`dm ${contactId}`)}
                        className="border border-cyan-500/20 bg-cyan-500/8 px-3 py-1.5 text-[13px] tracking-[0.18em] text-cyan-300 hover:bg-cyan-500/14"
                      >
                        MESSAGE
                      </button>
                      <button
                        type="button"
                        onClick={() => runQuickCommand(contact.blocked ? `dm unblock ${contactId}` : `dm block ${contactId}`)}
                        className="border border-fuchsia-500/20 bg-fuchsia-500/8 px-3 py-1.5 text-[13px] tracking-[0.18em] text-fuchsia-300 hover:bg-fuchsia-500/14"
                      >
                        {contact.blocked ? 'UNBLOCK' : 'BLOCK'}
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      case 'gates':
        return (
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <div className="text-sm tracking-[0.28em] text-fuchsia-300">
                GATES (EXPERIMENTAL ENCRYPTION)
              </div>
              <button
                type="button"
                onClick={() => runQuickCommand('gates')}
                className="border border-fuchsia-500/25 bg-fuchsia-500/8 px-3 py-1.5 text-[13px] font-mono tracking-[0.22em] text-fuchsia-200 hover:bg-fuchsia-500/14"
              >
                OPEN GATE LOG
              </button>
            </div>
            {gateCatalogLoading ? (
              <div className="border border-fuchsia-500/20 bg-black/45 px-4 py-5 text-[11px] font-mono text-slate-400">
                Loading gate catalog...
              </div>
            ) : gateCatalog.length === 0 ? (
              <div className="border border-fuchsia-500/20 bg-black/45 px-4 py-5 text-[11px] font-mono text-slate-400">
                No launch gates available.
              </div>
            ) : (
              <div className="grid gap-3 md:grid-cols-2">
                {gateCatalog.map((gate) => {
                  const minRep = gate.rules?.min_overall_rep;
                  const expanded = expandedGateId === gate.gate_id;
                  return (
                    <div
                      key={gate.gate_id}
                      className="border border-fuchsia-500/20 bg-black/50 px-4 py-4 font-mono shadow-[inset_0_0_0_1px_rgba(217,70,239,0.04)] transition-all hover:-translate-y-0.5 hover:border-fuchsia-400/45 hover:bg-fuchsia-500/6"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <div className="text-[11px] tracking-[0.22em] text-fuchsia-200">
                            {(gate.display_name || gate.gate_id).toUpperCase()}
                          </div>
                          <div className="mt-1 text-[13px] tracking-[0.16em] text-fuchsia-300/75">
                            {gate.gate_id}
                          </div>
                        </div>
                        <div className="text-[13px] text-slate-500">
                          {typeof gate.message_count === 'number' ? `${gate.message_count} msgs` : 'catalog'}
                        </div>
                      </div>
                      <div className="mt-3 min-h-[40px] text-[11px] leading-6 text-slate-400">
                        {gate.description || 'Encrypted commons lane.'}
                      </div>
                      <div className="mt-3 flex items-center justify-between text-[13px] tracking-[0.16em]">
                        <span className="text-amber-200">{minRep ? `REQ ${minRep} REP` : 'OPEN'}</span>
                        <span className="text-cyan-300">{gate.fixed ? 'FIXED LAUNCH GATE' : 'GATE'}</span>
                      </div>
                      <div className="mt-4 flex flex-wrap gap-2">
                        <button
                          type="button"
                          onClick={() => openGateCard(gate.gate_id)}
                          className="border border-cyan-500/25 bg-cyan-500/8 px-3 py-1.5 text-[13px] tracking-[0.18em] text-cyan-300 hover:bg-cyan-500/14"
                        >
                          {expanded ? 'HIDE' : 'OPEN'}
                        </button>
                        <button
                          type="button"
                          onClick={() => runQuickCommand(`messages ${gate.gate_id}`)}
                          className="border border-emerald-500/25 bg-emerald-500/8 px-3 py-1.5 text-[13px] tracking-[0.18em] text-emerald-300 hover:bg-emerald-500/14"
                        >
                          MESSAGES
                        </button>
                        <button
                          type="button"
                          onClick={() => {
                            setActiveGateComposeId(gate.gate_id);
                            setGateReplyTarget(null);
                            setSurfacePanel('gates');
                            setTimeout(() => inputRef.current?.focus(), 40);
                          }}
                          className="border border-amber-400/25 bg-amber-400/8 px-3 py-1.5 text-[13px] tracking-[0.18em] text-amber-200 hover:bg-amber-400/14"
                        >
                          POST
                        </button>
                        <button
                          type="button"
                          onClick={() => runQuickCommand(`gate mask ${gate.gate_id}`)}
                          className="border border-fuchsia-500/25 bg-fuchsia-500/8 px-3 py-1.5 text-[13px] tracking-[0.18em] text-fuchsia-200 hover:bg-fuchsia-500/14"
                        >
                          UNLOCK
                        </button>
                      </div>
                      {expandedGateLoading === gate.gate_id && (
                        <div className="mt-4 border border-fuchsia-500/15 bg-black/35 px-3 py-3 text-sm text-slate-400">
                          Loading gate detail...
                        </div>
                      )}
                      {expanded && expandedGateDetail && (
                        <div className="mt-4 space-y-3 border border-fuchsia-500/15 bg-black/40 px-4 py-4">
                          <div className="grid gap-3 md:grid-cols-2">
                            <div>
                              <div className="text-[13px] tracking-[0.18em] text-fuchsia-300">WELCOME</div>
                              <div className="mt-2 text-[11px] leading-6 text-slate-400">
                                {expandedGateDetail.welcome || expandedGateDetail.description || 'Encrypted commons lane.'}
                              </div>
                            </div>
                            <div className="space-y-2 text-sm">
                              <div className="flex items-center justify-between">
                                <span className="text-slate-500">Creator</span>
                                <span className="text-cyan-300">{expandedGateDetail.creator_node_id || 'unknown'}</span>
                              </div>
                              <div className="flex items-center justify-between">
                                <span className="text-slate-500">Messages</span>
                                <span className="text-cyan-300">{expandedGateDetail.message_count || 0}</span>
                              </div>
                              {expandedGateKey && (
                                <>
                                  <div className="flex items-center justify-between">
                                    <span className="text-slate-500">Epoch</span>
                                    <span className="text-fuchsia-200">{String(expandedGateKey.current_epoch || 0)}</span>
                                  </div>
                                  <div className="flex items-center justify-between">
                                    <span className="text-slate-500">Access</span>
                                    <span className="text-emerald-300">
                                      {expandedGateKey.has_local_access
                                        ? String(expandedGateKey.identity_scope || 'member')
                                        : 'locked'}
                                    </span>
                                  </div>
                                </>
                              )}
                            </div>
                          </div>
                          {expandedGateMessages.length > 0 && (
                            <div>
                              <div className="text-[13px] tracking-[0.18em] text-fuchsia-300">THREAD SNAPSHOT</div>
                              <div className="mt-3 grid gap-3">
                                {expandedGateMessages.map((message, messageIndex) => (
                                  <div
                                    key={`${message.nodeId}-${messageIndex}`}
                                    className="border border-cyan-500/15 bg-black/35 px-3 py-3 text-left transition-all hover:border-cyan-400/30 hover:bg-cyan-500/6"
                                  >
                                    <div className="flex items-center justify-between gap-3">
                                      <div className="text-sm tracking-[0.16em] text-cyan-200">{message.nodeId}</div>
                                      <div className="text-[13px] text-slate-500">{message.age}</div>
                                    </div>
                                    <div className="mt-2 text-[11px] leading-6 text-slate-300">{message.text}</div>
                                    {message.encrypted && (
                                      <div className="mt-2 text-[13px] tracking-[0.16em] text-fuchsia-300">
                                        EXPERIMENTAL ENCRYPTION
                                      </div>
                                    )}
                                    <div className="mt-3 flex flex-wrap gap-2">
                                      <button
                                        type="button"
                                        onClick={() => runQuickCommand(`messages ${gate.gate_id}`)}
                                        className="border border-cyan-500/20 bg-cyan-500/8 px-3 py-1.5 text-[13px] tracking-[0.18em] text-cyan-300 hover:bg-cyan-500/14"
                                      >
                                        THREAD
                                      </button>
                                      <button
                                        type="button"
                                        onClick={() => {
                                          setActiveGateComposeId(gate.gate_id);
                                          setGateReplyTarget(message.nodeId);
                                          setTimeout(() => inputRef.current?.focus(), 40);
                                        }}
                                        className="border border-amber-400/20 bg-amber-400/8 px-3 py-1.5 text-[13px] tracking-[0.18em] text-amber-200 hover:bg-amber-400/14"
                                      >
                                        REPLY
                                      </button>
                                      <button
                                        type="button"
                                        onClick={() => runQuickCommand(`rep ${message.nodeId}`)}
                                        className="border border-cyan-500/20 bg-cyan-500/8 px-3 py-1.5 text-[13px] tracking-[0.18em] text-cyan-300 hover:bg-cyan-500/14"
                                      >
                                        REP
                                      </button>
                                      <button
                                        type="button"
                                        onClick={() => runQuickCommand(`vote ${message.nodeId} up ${gate.gate_id}`)}
                                        className={`border px-3 py-1.5 text-[13px] tracking-[0.18em] transition-colors ${
                                          voteDirections[voteScopeKey(message.nodeId, gate.gate_id)] === 1
                                            ? 'border-emerald-400/35 bg-emerald-500/16 text-emerald-100'
                                            : 'border-emerald-500/20 bg-emerald-500/8 text-emerald-300 hover:bg-emerald-500/14'
                                        }`}
                                      >
                                        UP
                                      </button>
                                      <button
                                        type="button"
                                        onClick={() => runQuickCommand(`vote ${message.nodeId} down ${gate.gate_id}`)}
                                        className={`border px-3 py-1.5 text-[13px] tracking-[0.18em] transition-colors ${
                                          voteDirections[voteScopeKey(message.nodeId, gate.gate_id)] === -1
                                            ? 'border-rose-400/35 bg-rose-500/16 text-rose-100'
                                            : 'border-rose-500/20 bg-rose-500/8 text-rose-300 hover:bg-rose-500/14'
                                        }`}
                                      >
                                        DOWN
                                      </button>
                                    </div>
                                  </div>
                                ))}
                              </div>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        );
      default:
        return null;
    }
  };

  const confirmGateAccess = useCallback(() => {
    if (!wormholeSecureRequired || !wormholeReadyState) {
      routeToWormholeSetup();
      return;
    }
    if (typeof window !== 'undefined') {
      try {
        sessionStorage.removeItem(WORMHOLE_RETURN_KEY);
      } catch {
        /* ignore */
      }
    }
    setGateAccessGranted(true);
    setGateAccessPromptOpen(false);
    const nextCommand = pendingGateCommand;
    setPendingGateCommand(null);
    setSurfacePanel('gates');
    if (nextCommand && nextCommand !== 'gates') {
      setTimeout(() => runQuickCommand(nextCommand), 40);
    } else {
      setTimeout(() => runQuickCommand('gates'), 40);
    }
  }, [
    pendingGateCommand,
    routeToWormholeSetup,
    runQuickCommand,
    wormholeReadyState,
    wormholeSecureRequired,
  ]);

  const confirmPrivateLanePrompt = useCallback(() => {
    void activatePrivateLane('gates');
  }, [activatePrivateLane]);

  const dismissPrivateLanePrompt = useCallback(() => {
    setPrivateLanePromptOpen(false);
    setPrivateLanePromptStatus(null);
    addSystem('  Staying on the public lane for now.');
    addLines([
      {
        text: "  Mesh stays public. Type 'gates' or tap ENTER WORMHOLE later when you want the obfuscated commons.",
        type: 'dim',
      },
    ]);
  }, [addLines, addSystem]);

  const denyGateAccess = useCallback(() => {
    setGateAccessPromptOpen(false);
    setPendingGateCommand(null);
    setSurfacePanel('home');
    if (typeof window !== 'undefined') {
      try {
        sessionStorage.removeItem(WORMHOLE_RETURN_KEY);
      } catch {
        /* ignore */
      }
    }
    addSystem('  Gate access denied. Infonet Commons gates remain restricted.');
  }, [addSystem]);

  // Position + size style
  const sizeStyle: React.CSSProperties = {
    width: size.w,
    height: size.h,
    maxWidth: 'calc(100vw - 4rem)',
    maxHeight: 'calc(100vh - 4rem)',
  };
  const absoluteStyle: React.CSSProperties = {
    position: 'fixed',
    top: pos.y,
    left: pos.x,
    ...sizeStyle,
  };

  return (
    <AnimatePresence>
      {isOpen && (
        <>
          {privateLanePromptOpen && (
            <div className="fixed inset-0 z-[310] bg-black/60 backdrop-blur-[2px]">
              <div className="pointer-events-none absolute inset-0 flex items-center justify-center p-4">
                <div className="pointer-events-auto w-full max-w-lg border border-cyan-500/25 bg-black/95 p-5 font-mono shadow-[0_0_42px_rgba(34,211,238,0.12)]">
                  <div className="text-sm tracking-[0.28em] text-cyan-300">
                    {privateLanePromptMode === 'enter' ? 'ENTER WORMHOLE' : 'ACTIVATE WORMHOLE'}
                  </div>
                  <div className="mt-3 text-[13px] leading-7 text-slate-200">
                    {privateLanePromptMode === 'enter'
                      ? 'Obfuscated lane detected. Enter Wormhole now to sync into the Infonet Commons and communicate through gates.'
                      : 'No obfuscated lane is active yet. Activate Wormhole now and enter the Infonet Commons?'}
                  </div>
                  <div className="mt-4 border border-cyan-500/14 bg-cyan-950/10 px-4 py-3 text-sm leading-6 text-slate-300">
                    <div className="text-cyan-300">What this does</div>
                    <div className="mt-2">Wormhole turns on the obfuscated lane for gates and the obfuscated commons.</div>
                    <div>If a Wormhole identity already exists, it is reused. If one does not exist yet, it is bootstrapped once.</div>
                    <div>Participant-node sync and public chain hosting stay on the backend node lane.</div>
                    <div>Public mesh stays public and separate.</div>
                  </div>
                  {privateLanePromptStatus && (
                    <div
                      className={`mt-4 border px-3 py-2 text-sm leading-6 ${
                        privateLanePromptStatus.type === 'err'
                          ? 'border-rose-500/25 bg-rose-500/10 text-rose-200'
                          : privateLanePromptStatus.type === 'ok'
                            ? 'border-emerald-500/25 bg-emerald-500/10 text-emerald-200'
                            : 'border-cyan-500/18 bg-cyan-500/8 text-cyan-200'
                      }`}
                    >
                      {privateLanePromptStatus.text}
                    </div>
                  )}
                  <div className="mt-4 flex flex-wrap items-center gap-2">
                    <button
                      type="button"
                      onClick={confirmPrivateLanePrompt}
                      disabled={privateLanePromptBusy}
                      className="border border-cyan-500/25 bg-cyan-500/10 px-4 py-2 text-sm tracking-[0.22em] text-cyan-100 transition-colors hover:bg-cyan-500/16 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {privateLanePromptBusy
                        ? 'ENTERING...'
                        : privateLanePromptMode === 'enter'
                          ? 'YES, ENTER'
                          : 'YES, GENERATE'}
                    </button>
                    <button
                      type="button"
                      onClick={dismissPrivateLanePrompt}
                      disabled={privateLanePromptBusy}
                      className="border border-slate-500/20 bg-white/5 px-4 py-2 text-sm tracking-[0.22em] text-slate-300 transition-colors hover:bg-white/8 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      STAY PUBLIC
                    </button>
                    {onSettingsClick && (
                      <button
                        type="button"
                        onClick={() => {
                          if (typeof window !== 'undefined') {
                            try {
                              sessionStorage.setItem(SETTINGS_FOCUS_KEY, 'wormhole-gates');
                              sessionStorage.setItem(WORMHOLE_RETURN_KEY, 'gates');
                            } catch {
                              /* ignore */
                            }
                          }
                          onSettingsClick();
                        }}
                        disabled={privateLanePromptBusy}
                        className="border border-slate-500/20 bg-white/5 px-4 py-2 text-sm tracking-[0.22em] text-slate-400 transition-colors hover:bg-white/8 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        ADVANCED
                      </button>
                    )}
                  </div>
                </div>
              </div>
            </div>
          )}
          {gateAccessPromptOpen && (
            <div className="fixed inset-0 z-[309] bg-black/55 backdrop-blur-[2px]">
              <div className="pointer-events-none absolute inset-0 flex items-center justify-center p-4">
                <div className="pointer-events-auto w-full max-w-md border border-fuchsia-500/25 bg-black/95 p-5 font-mono shadow-[0_0_40px_rgba(217,70,239,0.12)]">
                  <div className="text-sm tracking-[0.28em] text-fuchsia-300">
                    ENTER INFONET COMMONS
                  </div>
                  <div className="mt-3 text-[12px] leading-6 text-slate-300">
                    Gates live behind Wormhole in this build. Enter now?
                  </div>
                  <div className="mt-3 text-sm leading-5 text-slate-500">
                    {wormholeSecureRequired
                      ? wormholeReadyState
                        ? 'Yes takes you straight into the gates.'
                        : 'Yes turns on Wormhole and provisions an obfuscated lane identity, then sends you into gates.'
                      : 'Yes turns on Wormhole and provisions an obfuscated lane identity, then sends you into gates.'}
                  </div>
                  <div className="mt-4 flex items-center gap-2">
                    <button
                      type="button"
                      onClick={confirmGateAccess}
                      className="border border-fuchsia-500/25 bg-fuchsia-500/10 px-4 py-2 text-sm tracking-[0.22em] text-fuchsia-200 transition-colors hover:bg-fuchsia-500/16"
                    >
                      YES
                    </button>
                    <button
                      type="button"
                      onClick={denyGateAccess}
                      className="border border-slate-500/20 bg-white/5 px-4 py-2 text-sm tracking-[0.22em] text-slate-300 transition-colors hover:bg-white/8"
                    >
                      NO
                    </button>
                  </div>
                </div>
              </div>
            </div>
          )}
          {minimized && (
            <motion.button
              type="button"
              initial={{ opacity: 0, y: -24 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -24 }}
              onClick={() => {
                setMinimized(false);
                setCentered(true);
                setTimeout(() => inputRef.current?.focus(), 80);
              }}
              className="fixed top-0 left-1/2 -translate-x-1/2 z-[305] flex items-center gap-2 rounded-b border border-cyan-800/30 border-t-0 bg-cyan-950/40 px-4 py-1.5 text-cyan-700 transition-colors hover:bg-cyan-950/60 hover:text-cyan-300 hover:border-cyan-500/40"
            >
              <Terminal size={11} className="text-cyan-400" />
              <span className="text-[11px] font-mono font-bold tracking-[0.22em]">
                TERMINAL
              </span>
            </motion.button>
          )}

          {!minimized && (
            <div
              style={centered ? {
                position: 'fixed',
                top: 0,
                left: 0,
                right: 0,
                bottom: 0,
                zIndex: 300,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                pointerEvents: 'none',
              } : { display: 'contents' }}
            >
              <motion.div
                ref={windowRef}
                initial={{ opacity: 0, scale: 0.95, y: 16 }}
                animate={{ opacity: 1, scale: 1, y: 0 }}
                exit={{ opacity: 0, scale: 0.95, y: 16 }}
                transition={{ type: 'spring', damping: 28, stiffness: 350 }}
                style={centered ? { ...sizeStyle, pointerEvents: 'auto' } : absoluteStyle}
                className={centered
                  ? "z-[300] max-w-[95vw] max-h-[90vh] overflow-hidden border border-cyan-500/18 bg-black/96 text-slate-100 shadow-[0_30px_80px_rgba(0,0,0,0.78),0_0_0_1px_rgba(34,211,238,0.1),0_0_42px_rgba(34,211,238,0.05)] backdrop-blur-sm"
                  : "fixed z-[300] max-w-[95vw] max-h-[90vh] overflow-hidden border border-cyan-500/18 bg-black/96 text-slate-100 shadow-[0_30px_80px_rgba(0,0,0,0.78),0_0_0_1px_rgba(34,211,238,0.1),0_0_42px_rgba(34,211,238,0.05)] backdrop-blur-sm"
                }
              >
              <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top,rgba(34,211,238,0.05),transparent_28%),radial-gradient(circle_at_50%_18%,rgba(217,70,239,0.05),transparent_18%),linear-gradient(180deg,rgba(2,4,8,0.995),rgba(0,0,0,0.995))]" />
              <div className="pointer-events-none absolute inset-0 opacity-[0.06] [background-image:linear-gradient(rgba(34,211,238,0.14)_1px,transparent_1px),linear-gradient(90deg,rgba(34,211,238,0.08)_1px,transparent_1px)] [background-size:100%_26px,26px_100%]" />

              <div
                onMouseDown={(e) => onResizeStart(e, 'n')}
                className="absolute top-0 left-2 right-2 h-1.5 cursor-n-resize z-[310]"
              />
              <div
                onMouseDown={(e) => onResizeStart(e, 's')}
                className="absolute bottom-0 left-2 right-2 h-1.5 cursor-s-resize z-[310]"
              />
              <div
                onMouseDown={(e) => onResizeStart(e, 'w')}
                className="absolute left-0 top-2 bottom-2 w-1.5 cursor-w-resize z-[310]"
              />
              <div
                onMouseDown={(e) => onResizeStart(e, 'e')}
                className="absolute right-0 top-2 bottom-2 w-1.5 cursor-e-resize z-[310]"
              />
              <div
                onMouseDown={(e) => onResizeStart(e, 'nw')}
                className="absolute top-0 left-0 w-3 h-3 cursor-nw-resize z-[311]"
              />
              <div
                onMouseDown={(e) => onResizeStart(e, 'ne')}
                className="absolute top-0 right-0 w-3 h-3 cursor-ne-resize z-[311]"
              />
              <div
                onMouseDown={(e) => onResizeStart(e, 'sw')}
                className="absolute bottom-0 left-0 w-3 h-3 cursor-sw-resize z-[311]"
              />
              <div
                onMouseDown={(e) => onResizeStart(e, 'se')}
                className="absolute bottom-0 right-0 w-3 h-3 cursor-se-resize z-[311]"
              />

              <div className="relative flex h-full flex-col">
                <div
                  onMouseDown={onDragStart}
                  className="flex h-11 min-h-[44px] items-center justify-between border-b border-cyan-500/12 bg-[linear-gradient(90deg,rgba(4,8,12,0.98),rgba(6,10,14,0.96),rgba(10,4,12,0.94))] px-4 select-none cursor-move"
                >
                  <div className="flex items-center gap-2">
                    <GripHorizontal className="h-3.5 w-3.5 text-cyan-500/55" />
                    <div className="relative h-7 w-7 rounded-full border border-cyan-400/30 bg-cyan-500/8">
                      <div className="absolute inset-1 rounded-full border border-cyan-400/40" />
                      <div className="absolute inset-[9px] rounded-full bg-cyan-300 shadow-[0_0_14px_rgba(34,211,238,0.9)]" />
                      <div className="absolute left-1/2 top-0 h-full w-px -translate-x-1/2 bg-cyan-400/20" />
                      <div className="absolute top-1/2 left-0 h-px w-full -translate-y-1/2 bg-cyan-400/20" />
                    </div>
                  </div>

                  <div className="text-center">
                    <div className="text-[12px] tracking-[0.32em] text-slate-500">
                      type clear to wipe output · gates require wormhole · mesh stays public
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => {
                        openSurface('inbox');
                        runQuickCommand('inbox');
                      }}
                      className="border border-cyan-500/18 bg-cyan-500/8 px-2.5 py-1 text-[12px] tracking-[0.18em] text-cyan-300 transition-colors hover:bg-cyan-500/14"
                    >
                      PRIVATE DM INBOX
                    </button>
                    {nodeIdentity && hasSovereignty() && (
                      <span className="border border-cyan-500/20 bg-cyan-500/10 px-2 py-1 text-[12px] tracking-[0.18em] text-cyan-300">
                        {nodeIdentity.nodeId.slice(0, 14)}
                      </span>
                    )}
                    {terminalWriteLockReason && (
                      <span className="border border-amber-400/25 bg-amber-400/10 px-2 py-1 text-[12px] tracking-[0.18em] text-amber-200">
                        READ ONLY
                      </span>
                    )}
                    {busy && (
                      <span className="border border-fuchsia-500/25 bg-fuchsia-500/10 px-2 py-1 text-[12px] tracking-[0.18em] text-fuchsia-200">
                        RUNNING
                      </span>
                    )}
                    <button
                      type="button"
                      onClick={() => setMinimized(true)}
                      className="p-1.5 text-slate-500 transition-colors hover:bg-white/5 hover:text-amber-200"
                      title="Minimize terminal"
                    >
                      <Minus className="h-3.5 w-3.5" />
                    </button>
                    <button
                      type="button"
                      onClick={onClose}
                      className="p-1.5 text-slate-500 transition-colors hover:bg-white/5 hover:text-rose-300"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>

                <div
                  ref={scrollRef}
                  className="relative flex-1 overflow-y-auto styled-scrollbar select-text"
                  onClick={() => {
                    const sel = window.getSelection();
                    if (!sel || sel.isCollapsed) inputRef.current?.focus();
                  }}
                >
                  <div className="mx-auto w-full max-w-[1180px] px-6 py-6">
                    <div className="mb-6 border border-cyan-500/14 bg-black/72 px-6 py-5 shadow-[inset_0_0_0_1px_rgba(34,211,238,0.05)]">
                      <div className="flex flex-col items-center text-center">
                        <div className="relative mb-4 h-16 w-16 rounded-full border border-cyan-400/30 bg-cyan-500/8">
                          <div className="absolute inset-2 rounded-full border border-cyan-400/35" />
                          <div className="absolute inset-[18px] rounded-full bg-cyan-300 shadow-[0_0_20px_rgba(34,211,238,0.85)]" />
                          <div className="absolute left-1/2 top-0 h-full w-px -translate-x-1/2 bg-cyan-400/20" />
                          <div className="absolute top-1/2 left-0 h-px w-full -translate-y-1/2 bg-cyan-400/20" />
                        </div>
                        <div className="text-sm tracking-[0.38em] text-cyan-300">INFONET</div>
                        <div className="mt-2 text-[30px] font-semibold leading-none tracking-[0.32em] text-cyan-100">
                          THE INFONET COMMONS
                        </div>
                        <div className="mt-2 text-sm tracking-[0.28em] text-fuchsia-300">
                          OPSINT DECK · COMMONS NODE
                        </div>
                        <div className="mt-4 max-w-[760px] text-[11px] leading-6 text-slate-400">
                          Experimental operator deck for encrypted gates, mesh comms, dossiers, prediction markets, and live intel routing.
                        </div>
                      </div>

                      <div className="mt-5 grid w-full gap-2 text-[13px] font-mono md:grid-cols-4">
                        <div className="border border-cyan-500/20 bg-cyan-500/8 px-3 py-2 text-cyan-300">
                          INFONET · experimental encryption
                        </div>
                        <div className="border border-emerald-500/20 bg-emerald-500/8 px-3 py-2 text-emerald-300">
                          MESH · public / observable
                        </div>
                        <div className="border border-fuchsia-500/20 bg-fuchsia-500/8 px-3 py-2 text-fuchsia-300">
                          GATES · experimental encryption
                        </div>
                        <div className="border border-amber-400/20 bg-amber-400/8 px-3 py-2 text-amber-200">
                          COMMANDS · type or click to launch
                        </div>
                      </div>

                      <div className="mt-5 grid gap-3 xl:grid-cols-[1.45fr_1fr]">
                        <div className="border border-cyan-500/16 bg-black/40 px-4 py-3">
                          <div className="flex items-center justify-between gap-3">
                            <div>
                              <div className="text-[13px] tracking-[0.24em] text-cyan-300">
                                PARTICIPANT NODE
                              </div>
                              <div className="mt-1 text-sm leading-5 text-slate-400">
                                Automatic bootstrap and sync now live on the backend lane. This node can keep a local chain even with Wormhole off.
                              </div>
                            </div>
                            <div className="border border-cyan-500/20 bg-cyan-500/8 px-3 py-1.5 text-[13px] tracking-[0.22em] text-cyan-200">
                              {nodeModeLabel}
                            </div>
                          </div>

                          <div className="mt-3 grid gap-2 md:grid-cols-3 text-[13px] font-mono">
                            <div className="border border-emerald-500/20 bg-emerald-500/8 px-3 py-2 text-emerald-200">
                              <div className="text-[12px] tracking-[0.2em] text-emerald-300">CHAIN</div>
                              <div className="mt-1 text-[13px] text-emerald-100">
                                {shortNodeHash(infonetNodeStatus?.head_hash, 18)}
                              </div>
                              <div className="mt-1 text-[12px] text-emerald-200/70">
                                {Number(infonetNodeStatus?.total_events || 0)} events • {Number(infonetNodeStatus?.known_nodes || 0)} nodes
                              </div>
                            </div>
                            <div className="border border-cyan-500/20 bg-cyan-500/8 px-3 py-2 text-cyan-200">
                              <div className="text-[12px] tracking-[0.2em] text-cyan-300">PEERS</div>
                              <div className="mt-1 text-[13px] text-cyan-100">
                                {Number(infonetNodeStatus?.bootstrap?.sync_peer_count || 0)} sync
                              </div>
                              <div className="mt-1 text-[12px] text-cyan-200/70">
                                {Number(infonetNodeStatus?.bootstrap?.push_peer_count || 0)} push • {Number(infonetNodeStatus?.bootstrap?.bootstrap_peer_count || 0)} bootstrap
                              </div>
                            </div>
                            <div className="border border-fuchsia-500/20 bg-fuchsia-500/8 px-3 py-2 text-fuchsia-200">
                              <div className="text-[12px] tracking-[0.2em] text-fuchsia-300">SYNC LOOP</div>
                              <div className="mt-1 text-[13px] text-fuchsia-100">{nodeSyncLabel}</div>
                              <div className="mt-1 text-[12px] text-fuchsia-200/70">
                                next {formatNodeTime(infonetNodeStatus?.sync_runtime?.next_sync_due_at)}
                              </div>
                            </div>
                          </div>

                          <div className="mt-3 border border-cyan-500/12 bg-cyan-950/8 px-3 py-2 text-[13px] font-mono leading-[1.65] text-slate-300">
                            <div className="flex items-center justify-between gap-3">
                              <span className="text-cyan-300">Bootstrap</span>
                              <span className="text-right text-slate-400">{nodeBootstrapLabel}</span>
                            </div>
                            <div className="mt-1 flex items-center justify-between gap-3">
                              <span className="text-cyan-300">Last peer</span>
                              <span className="text-right text-slate-400">
                                {summarizeNodePeer(infonetNodeStatus?.sync_runtime?.last_peer_url)}
                              </span>
                            </div>
                            {infonetNodeStatusError && (
                              <div className="mt-2 text-amber-200/80">{infonetNodeStatusError}</div>
                            )}
                          </div>
                        </div>

                        <div className="border border-amber-400/16 bg-amber-400/6 px-4 py-3 text-sm leading-6 text-amber-100/85">
                          <div className="text-[13px] font-mono tracking-[0.24em] text-amber-300">
                            WORMHOLE OPTIONAL FOR NODE SYNC
                          </div>
                        <div className="mt-2">
                          Participant-node bootstrap, sync, and public chain hosting run on the backend lane without Wormhole.
                        </div>
                        <div className="mt-2 text-amber-200/75">
                          Turn Wormhole on for gates, obfuscated inbox, and the stronger obfuscated lane only.
                        </div>
                        <div className="mt-3 border border-amber-400/16 bg-black/20 px-3 py-2 text-[13px] font-mono leading-[1.65] text-amber-100/80">
                          obfuscated lane now: {privateLaneLabel}
                        </div>
                        <button
                          type="button"
                          onClick={() => void openPrivateLanePrompt()}
                          disabled={busy || privateLanePromptBusy}
                          className="mt-3 inline-flex items-center border border-amber-300/20 bg-amber-400/10 px-3 py-2 text-[13px] font-mono tracking-[0.22em] text-amber-100 transition-colors hover:bg-amber-400/16 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          {wormholeSecureRequired && wormholeReadyState
                            ? 'ENTER WORMHOLE'
                            : 'GENERATE PRIVATE KEY'}
                        </button>
                      </div>
                      </div>

                      <div className="mt-5 flex flex-wrap justify-center gap-2">
                        {QUICK_LAUNCHES.map((item) => (
                          <button
                            key={item.label}
                            type="button"
                            onClick={() => openSurface(item.panel)}
                            disabled={busy}
                            className={`px-3 py-2 text-sm font-mono tracking-[0.26em] transition-all disabled:cursor-not-allowed disabled:opacity-50 ${chipTone(item.tone)}`}
                          >
                            {item.label}
                          </button>
                        ))}
                      </div>

                      <div className="mt-5">
                        {renderSurfacePanel()}
                      </div>
                    </div>

                    <div className="space-y-1">
                      {lines.map((line, i) => renderStyledLine(line, i))}
                    </div>
                  </div>
                </div>

                <div className="border-t border-cyan-500/15 bg-[linear-gradient(180deg,rgba(7,11,15,0.98),rgba(5,8,12,0.98))] px-4 py-3">
                  <div className="mb-2 flex items-center justify-between text-[13px] font-mono tracking-[0.22em]">
                    <div className="flex items-center gap-3">
                      <span className="text-cyan-300">COMMAND LINE</span>
                      <span className="text-emerald-300">MESH / RADIO</span>
                      <span className="text-fuchsia-300">GATES / COMMONS</span>
                      <span className="text-amber-200">OPS / DOSSIER</span>
                      {activeGateComposeId && (
                        <span className="border border-fuchsia-500/20 bg-fuchsia-500/8 px-2 py-1 text-[12px] tracking-[0.16em] text-fuchsia-200">
                          POSTING TO g/{activeGateComposeId}
                        </span>
                      )}
                      {gateReplyTarget && (
                        <span className="border border-amber-400/20 bg-amber-400/8 px-2 py-1 text-[12px] tracking-[0.16em] text-amber-200">
                          REPLY @{gateReplyTarget}
                        </span>
                      )}
                    </div>
                    <span className="text-slate-500">
                      {activeGateComposeId
                        ? 'TYPE TO POST · / FOR COMMANDS · CLEAR KEEPS YOUR GATE OPEN'
                        : 'ENTER TO EXECUTE · TYPE CLEAR TO WIPE OUTPUT'}
                    </span>
                  </div>

                  <div className="flex items-center gap-3 border border-cyan-500/20 bg-black/25 px-3 py-3 shadow-[inset_0_0_0_1px_rgba(34,211,238,0.04)]">
                    <span className="shrink-0 text-[12px] text-cyan-300 select-none font-mono">
                      &gt;
                    </span>
                    <div className="flex-1 relative font-mono text-[12px]">
                      <input
                        ref={inputRef}
                        type="text"
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        onKeyDown={handleKey}
                        disabled={busy}
                        className="w-full border-none bg-transparent font-mono text-[12px] text-cyan-100 outline-none caret-transparent placeholder:text-cyan-900/80"
                        placeholder={
                          busy
                            ? ''
                            : sovereigntyPending
                              ? 'accept or decline...'
                              : sendStep === 'dest'
                                ? "callsign or 'broadcast'..."
                                : sendStep === 'msg'
                                  ? 'type your message...'
                                : dmStep === 'dest'
                                    ? 'agent ID (e.g. !sb_a3f2c891)...'
                                : dmStep === 'msg'
                                      ? 'type your private message...'
                                      : terminalWriteLockReason
                                        ? 'read-only under Wormhole security policy...'
                                        : activeGateComposeId
                                          ? `post to g/${activeGateComposeId}${gateReplyTarget ? ` reply @${gateReplyTarget}` : ''}...`
                                          : 'enter command...'
                        }
                        spellCheck={false}
                        autoComplete="off"
                      />
                      {!busy && (
                        <span
                          className="absolute top-0 pointer-events-none h-full flex items-center"
                          style={{ left: `${input.length * 7.2}px` }}
                        >
                          <span className="inline-block h-[16px] w-[7px] bg-cyan-300 shadow-[0_0_10px_rgba(34,211,238,0.8)] animate-[blink_1s_step-end_infinite]" />
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            </motion.div>
            </div>
          )}
        </>
      )}
    </AnimatePresence>
  );
}
