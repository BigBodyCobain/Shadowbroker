// @ts-nocheck
import { API_BASE } from '@/lib/api';
import type { InfonetNodeStatusSnapshot } from '@/mesh/controlPlaneStatusClient';

export const API = API_BASE;
export const INFONET_HEAD_KEY = 'sb_infonet_head';
export const INFONET_HEAD_HISTORY_KEY = 'sb_infonet_head_history';
export const INFONET_LOCATOR_LIMIT = 32;
export const INFONET_PEERS_KEY = 'sb_infonet_peers';
export const DEFAULT_MESH_ROOTS = [
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

export function sortMeshRoots(
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
export const SETTINGS_FOCUS_KEY = 'sb_settings_focus';
export const WORMHOLE_RETURN_KEY = 'sb_wormhole_return_target';
export const WORMHOLE_READY_EVENT = 'sb:wormhole-ready';
export const DEFAULT_TERMINAL_SIZE = { w: 1040, h: 760 };

export function getTerminalSensitiveItem(key: string): string {
  if (typeof window === 'undefined') return '';
  return getSensitiveBrowserItem(key) || '';
}

export function setTerminalSensitiveItem(key: string, value: string): void {
  if (typeof window === 'undefined') return;
  setSensitiveBrowserItem(key, value);
}

export interface Props {
  isOpen: boolean;
  launchToken?: number;
  onClose: () => void;
  onDmCount?: (count: number) => void;
  onSettingsClick?: () => void;
}

export interface TermLine {
  text: string;
  type: 'input' | 'output' | 'error' | 'system' | 'header' | 'dim';
  actionCommand?: string;
  actionLabel?: string;
}

export interface InfonetEventPayload {
  [key: string]: unknown;
}

export interface InfonetMessageRecord {
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
  gate_envelope?: string;
  envelope_hash?: string;
  payload?: {
    gate?: string;
    ciphertext?: string;
    nonce?: string;
    sender_ref?: string;
    format?: string;
    gate_envelope?: string;
    envelope_hash?: string;
  };
  timestamp: number;
  ephemeral?: boolean;
  system_seed?: boolean;
  fixed_gate?: boolean;
}

export interface InfonetEvent {
  event_id: string;
  event_type: string;
  node_id: string;
  sequence?: number;
  payload?: InfonetEventPayload;
  signature?: string;
  public_key?: string;
  public_key_algo?: string;
}

export interface InfonetMerkleProof {
  leaf?: string;
  index?: number;
  proof?: string[];
}

export interface InfonetSyncResponse {
  ok?: boolean;
  forked?: boolean;
  matched_hash?: string;
  events?: InfonetEvent[];
  merkle_proofs?: InfonetMerkleProof[];
  merkle_root?: string;
  head_hash?: string;
}

export interface GateSummary {
  gate_id: string;
  display_name?: string;
  description?: string;
  message_count?: number;
  fixed?: boolean;
  rules?: {
    min_overall_rep?: number;
  };
}

export interface GateDetailRecord {
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

export function normalizeInfonetMessageRecord(message: InfonetMessageRecord): InfonetMessageRecord {
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
    gate_envelope: String(message.gate_envelope ?? payload.gate_envelope ?? ''),
    envelope_hash: String(message.envelope_hash ?? payload.envelope_hash ?? '') };
}

export interface GateKeyStatusRecord {
  ok?: boolean;
  current_epoch?: number;
  key_commitment?: string;
  has_local_access?: boolean;
  identity_scope?: string;
  rekey_recommended?: boolean;
  rekey_recommended_reason?: string;
}

export interface InboxPreviewRecord {
  sender: string;
  age: string;
  text: string;
  locked?: boolean;
}

export interface GateThreadPreview {
  nodeId: string;
  age: string;
  text: string;
  encrypted?: boolean;
}

export interface MeshStatusResponse {
  signal_counts?: {
    aprs?: number;
    meshtastic?: number;
    js8call?: number;
    total?: number;
  };
}

export function formatNodeMode(mode?: string): string {
  const normalized = String(mode || 'participant').trim().toLowerCase();
  if (!normalized) return 'PARTICIPANT';
  return normalized.toUpperCase();
}

export function shortNodeHash(value?: string, size: number = 14): string {
  const normalized = String(value || '').trim();
  if (!normalized) return 'genesis';
  if (normalized.length <= size) return normalized;
  return `${normalized.slice(0, size)}...`;
}

export function formatNodeTime(ts?: number): string {
  const value = Number(ts || 0);
  if (!Number.isFinite(value) || value <= 0) return 'never';
  return new Date(value * 1000).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit' });
}

export function summarizeNodePeer(peerUrl?: string): string {
  const value = String(peerUrl || '').trim();
  if (!value) return 'none yet';
  try {
    return new URL(value).host || value;
  } catch {
    return value;
  }
}

export function describeBootstrapState(snapshot?: InfonetNodeStatusSnapshot | null): string {
  if (snapshot && !snapshot.node_enabled) return 'READY / DISABLED';
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

export function describeSyncOutcome(snapshot?: InfonetNodeStatusSnapshot | null): string {
  if (snapshot && !snapshot.node_enabled) return 'OFF - click NODE to activate';
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

export function buildNodeRuntimeLines(snapshot: InfonetNodeStatusSnapshot): TermLine[] {
  const bootstrap = snapshot.bootstrap;
  const sync = snapshot.sync_runtime;
  const push = snapshot.push_runtime;
  const lines: TermLine[] = [
    { text: '  NODE RUNTIME', type: 'system' },
    { text: `    Mode:        ${formatNodeMode(snapshot.node_mode)}`, type: 'output' },
    {
      text: `    Bootstrap:   ${describeBootstrapState(snapshot)}`,
      type: bootstrap?.last_bootstrap_error ? 'error' : 'output' },
    {
      text: `    Peers:       ${Number(bootstrap?.sync_peer_count || 0)} sync | ${Number(bootstrap?.push_peer_count || 0)} push | ${Number(bootstrap?.bootstrap_peer_count || 0)} bootstrap`,
      type: 'output' },
    { text: `    Sync Loop:   ${describeSyncOutcome(snapshot)}`, type: 'output' },
    {
      text: `    Next Sync:   ${formatNodeTime(sync?.next_sync_due_at)}`,
      type: 'output' },
  ];
  if (push?.last_event_id) {
    lines.push({
      text: `    Last Push:   ${shortNodeHash(push.last_event_id, 18)} @ ${formatNodeTime(push.last_push_ok_at)}`,
      type: 'output' });
  }
  if (sync?.fork_detected) {
    lines.push({
      text: '    Fork Stop:   automatic sync paused until the fork is resolved',
      type: 'error' });
  }
  if (push?.last_push_error) {
    lines.push({
      text: `    Push Warn:   ${push.last_push_error}`,
      type: 'error' });
  }
  if (!snapshot.node_enabled) {
    lines.push({
      text: '    Activate:    click the NODE button in the top-right controls to join the public testnet seed',
      type: 'dim' });
  }
  lines.push({ text: '', type: 'dim' });
  return lines;
}

export const WELCOME: TermLine[] = [
  { text: '', type: 'dim' },
  { text: '  Docked into the Infonet Commons node.', type: 'header' },
  { text: '', type: 'dim' },
];

export const QUICK_LAUNCHES = [
  { label: 'HELP', panel: 'help', tone: 'yellow' },
  { label: 'APPS', panel: 'apps', tone: 'cyan' },
  { label: 'MESH', panel: 'mesh', tone: 'green' },
  { label: 'GATES (EXPERIMENTAL ENCRYPTION)', panel: 'gates', tone: 'pink' },
  { label: 'MARKETS', panel: 'markets', tone: 'yellow' },
  { label: 'DOSSIER', panel: 'dossier', tone: 'pink' },
  { label: 'INBOX', panel: 'inbox', tone: 'cyan' },
] as const;

export const SOVEREIGNTY_DECLARATION: TermLine[] = [
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
    type: 'output' },
  { text: '  - If your radio broadcasts GPS, your position is visible on the map', type: 'output' },
  { text: '    (disable GPS beacons on hardware to remain geographically anonymous)', type: 'dim' },
  { text: '', type: 'dim' },
  { text: '  Note: RF networks may be IP-traceable. You may not be anonymous.', type: 'dim' },
  { text: '', type: 'dim' },
  {
    text: "  Type 'accept' to generate your Agent ID, or 'decline' for read-only.",
    type: 'system' },
  { text: '', type: 'dim' },
];

export const HELP_SECTIONS: Record<string, string[]> = {
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
    '    gate resync <id>    Resync local native gate state',
    '    say <gate> <msg>    Post to an encrypted gate lane',
    '    Gates run on a transitional private lane through Wormhole.',
    '    Dead Drop / DM is a separate, stronger private lane.',
    '    Public mesh does not route through Wormhole.',
  ],
  inbox: [
    '  EXPERIMENTAL PRIVATE DM INBOX',
    '    inbox               Check pending private messages',
    '    contacts            List saved contacts',
    '    dm                  Start interactive encrypted DM',
    '    dm selftest         Run a local synthetic-peer DM privacy test',
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
  ] };

export const GUIDE_TEXT: TermLine[] = [
  { text: '', type: 'dim' },
  { text: '  HOW THIS WORKS', type: 'header' },
  { text: '', type: 'dim' },
  { text: '  ShadowBroker is a decentralized intelligence network.', type: 'dim' },
  { text: '  It connects to live radio networks (APRS, Meshtastic, JS8Call)', type: 'dim' },
  { text: '  and runs the Infonet — a protocol where every action is', type: 'dim' },
  { text: '  signed, and reputation-scored.', type: 'dim' },
  { text: '', type: 'dim' },
  { text: '  1. CONNECT', type: 'system' },
  { text: "     Type 'connect' to create your local public Agent identity.", type: 'dim' },
  { text: '     This is for public mesh + perimeter activity. It generates', type: 'dim' },
  { text: '     an Ed25519 keypair locally. Your private key never leaves', type: 'dim' },
  { text: '     your device. No registration, no server, no email.', type: 'dim' },
  { text: "     Wormhole provides gates (transitional private lane) and Dead Drop (stronger private DM lane) separately.", type: 'dim' },
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

export type SearchRecord = Record<string, unknown>;

export function asSearchRecords(value: unknown): SearchRecord[] {
  return Array.isArray(value)
    ? value.filter((item): item is SearchRecord => Boolean(item && typeof item === 'object'))
    : [];
}

export function pickRecordText(record: SearchRecord, keys: string[]): string {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return '';
}

export function pickRecordNumber(record: SearchRecord, keys: string[]): number | null {
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

export function recordMatchesQuery(record: SearchRecord, query: string, preferredKeys: string[] = []): boolean {
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

export function formatLatLng(record: SearchRecord): string {
  const lat = pickRecordNumber(record, ['lat', 'latitude']);
  const lng = pickRecordNumber(record, ['lng', 'lon', 'longitude']);
  if (lat == null || lng == null) return 'coords n/a';
  return `${lat.toFixed(2)}, ${lng.toFixed(2)}`;
}

