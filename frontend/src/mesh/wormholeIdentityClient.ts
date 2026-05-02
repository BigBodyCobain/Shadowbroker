import { controlPlaneFetch, controlPlaneJson } from '@/lib/controlPlane';
import { hasLocalControlBridge } from '@/lib/localControlTransport';
import { buildGateAccessHeaders, invalidateGateAccessHeaders } from '@/mesh/gateAccessProof';
import { recordGateCompatTelemetry } from '@/mesh/gateCompatTelemetry';
import { invalidateGateMessageSnapshot } from '@/mesh/gateMessageSnapshot';
import {
  getGateSessionStreamStatus,
  getGateSessionStreamKeyStatus,
  invalidateGateSessionStreamGateContext,
  setGateSessionStreamGateContext,
} from '@/mesh/gateSessionStream';
import {
  composeBrowserGateMessage,
  decryptBrowserGateMessages,
  forgetBrowserGateState,
  getBrowserGateCryptoFailureReason,
  postBrowserGateMessage,
  syncBrowserGateState,
} from '@/mesh/meshGateWorkerClient';
import type { LegacyCompatibilitySnapshot } from '@/mesh/wormholeCompatibility';
import {
  cacheWormholeIdentityDescriptor,
  getNodeIdentity,
  getPublicKeyAlgo,
  getWormholeIdentityDescriptor,
  isSecureModeCached,
  purgeBrowserSigningMaterial,
  setSecureModeCached,
  signEvent,
  signWithStoredKey,
} from '@/mesh/meshIdentity';
import { PROTOCOL_VERSION } from '@/mesh/meshProtocol';
import {
  connectWormhole,
  fetchWormholeSettings,
  fetchWormholeState,
  joinWormhole,
  type PrivateDeliverySummary,
} from '@/mesh/wormholeClient';

const KEY_SESSION_MODE = 'sb_mesh_session_mode';
const KEY_GATE_COMPAT_APPROVALS = 'sb_gate_compat_approvals_v2';
const GATE_LOCAL_RUNTIME_REQUIRED_PREFIX = 'gate_local_runtime_required';
const GATE_LIFECYCLE_PREP_TIMEOUT_MS = 45_000;
const GATE_LIFECYCLE_PREP_POLL_MS = 700;
const GATE_MESSAGE_PREP_TIMEOUT_MS = 60_000;
const WORMHOLE_TRANSPORT_TIER_ORDER: Record<string, number> = {
  public_degraded: 0,
  private_control_only: 1,
  private_transitional: 2,
  private_strong: 3,
};
const wormholeInteractivePrepInflight = new Map<string, Promise<PreparedWormholeInteractiveLane>>();

export interface WormholeIdentity {
  bootstrapped: boolean;
  bootstrapped_at: number;
  scope?: string;
  gate_id?: string;
  persona_id?: string;
  label?: string;
  node_id: string;
  public_key: string;
  public_key_algo: string;
  sequence: number;
  dh_pub_key?: string;
  dh_algo?: string;
  last_dh_timestamp?: number;
  bundle_fingerprint?: string;
  bundle_sequence?: number;
  bundle_registered_at?: number;
  created_at?: number;
  last_used_at?: number;
  protocol_version: string;
}

export interface WormholeDmInviteEnvelope {
  event_type: string;
  payload: Record<string, unknown>;
  node_id: string;
  public_key: string;
  public_key_algo: string;
  protocol_version: string;
  sequence: number;
  signature: string;
  identity_scope?: string;
}

export interface WormholeDmInviteExport {
  ok: boolean;
  peer_id: string;
  trust_fingerprint: string;
  invite: WormholeDmInviteEnvelope;
}

export interface WormholeDmInviteImportResult {
  ok: boolean;
  peer_id: string;
  trust_fingerprint: string;
  trust_level: string;
  detail?: string;
  contact: Record<string, unknown>;
}

export type WormholeDmInviteImportFailure = Partial<WormholeDmInviteImportResult> & {
  ok?: false;
};

export type WormholeDmInviteImportError = Error & {
  result?: WormholeDmInviteImportFailure;
};

export interface WormholeDmRootHealthAlert {
  code: string;
  severity: string;
  detail: string;
  action: string;
  target: string;
  blocking: boolean;
  age_s?: number;
  warning_window_s?: number;
  freshness_window_s?: number;
}

export interface WormholeDmRootHealthMonitoring {
  state: string;
  page_required: boolean;
  ticket_required: boolean;
  runbook_required?: boolean;
  strong_trust_blocked?: boolean;
  status_line?: string;
  summary_state?: string;
  summary_health_state?: string;
  primary_alert?: WormholeDmRootHealthAlert;
  active_alert_codes?: string[];
  recommended_check_interval_s?: number;
}

export interface WormholeDmRootHealthRunbookAction {
  action: string;
  target: string;
  severity: string;
  blocking: boolean;
  urgency?: string;
  title?: string;
  summary?: string;
  reason?: string;
  steps?: string[];
  owner?: string;
}

export interface WormholeDmRootHealthRunbook {
  attention_required: boolean;
  strong_trust_blocked: boolean;
  urgency: string;
  status_line?: string;
  next_action: string;
  next_action_detail?: WormholeDmRootHealthRunbookAction | Record<string, never>;
  actions: WormholeDmRootHealthRunbookAction[];
}

export interface WormholeDmRootHealthSection {
  state: string;
  health_state: string;
  detail?: string;
  source_ref?: string;
  source_scope?: string;
  source_label?: string;
  export_path?: string;
  age_s?: number;
  warning_window_s?: number;
  freshness_window_s?: number;
  manifest_matches_current?: boolean;
  reacquire_required?: boolean;
  independent_quorum_met?: boolean;
  verification_required?: boolean;
}

export interface WormholeDmRootHealth {
  ok: boolean;
  checked_at: number;
  state: string;
  detail: string;
  health_state: string;
  witness_health_state: string;
  transparency_health_state: string;
  strong_trust_blocked: boolean;
  warning_due: boolean;
  next_action: string;
  recommended_actions: string[];
  alert_count: number;
  blocking_alert_count: number;
  warning_alert_count: number;
  alerts: WormholeDmRootHealthAlert[];
  monitoring: WormholeDmRootHealthMonitoring;
  runbook: WormholeDmRootHealthRunbook;
  witness: WormholeDmRootHealthSection;
  transparency: WormholeDmRootHealthSection;
}

export interface WormholeSignedEvent {
  node_id: string;
  public_key: string;
  public_key_algo: string;
  protocol_version: string;
  sequence: number;
  payload: Record<string, unknown>;
  signature: string;
  signature_payload: string;
}

export interface WormholeSignedRawMessage {
  node_id: string;
  public_key: string;
  public_key_algo: string;
  protocol_version: string;
  signature: string;
  message: string;
}

export interface WormholeDmSenderToken {
  ok: boolean;
  sender_token: string;
  expires_at: number;
  delivery_class: string;
}

export interface WormholeDmSenderTokenBatch {
  ok: boolean;
  delivery_class: string;
  tokens: Array<{ sender_token: string; expires_at: number }>;
}

export interface WormholeDmSelftestResult {
  ok: boolean;
  run_id: string;
  mode: string;
  started_at: number;
  completed_at: number;
  transport_tier: string;
  steps: Array<{ name: string; ok: boolean; required?: boolean; detail?: string }>;
  privacy_checks: Array<{ name: string; ok: boolean; detail?: string }>;
  artifacts: {
    plaintext_sha256?: string;
    ciphertext_sha256?: string;
    plaintext_returned?: boolean;
    contact_created?: boolean;
    network_release_attempted?: boolean;
  };
  cleanup?: { ok?: boolean; aliases_removed?: number; sessions_removed?: number; detail?: string };
  unproven_by_this_test?: string[];
  next_hardening?: string[];
}

export interface WormholeOpenedSeal {
  ok: boolean;
  sender_id: string;
  seal_verified: boolean;
  public_key?: string;
  public_key_algo?: string;
  timestamp?: number;
  msg_id?: string;
}

export interface WormholeBuiltSeal {
  ok: boolean;
  sender_seal: string;
  sender_id?: string;
  public_key?: string;
  public_key_algo?: string;
  protocol_version?: string;
}

export interface WormholeDeadDropTokenPair {
  ok: boolean;
  peer_id: string;
  peer_ref?: string;
  epoch: number;
  current: string;
  previous: string;
}

export interface WormholePairwiseAlias {
  ok: boolean;
  peer_id: string;
  shared_alias: string;
  replaced_alias?: string;
  dm_identity_id?: string;
  identity_scope?: string;
  contact?: Record<string, unknown>;
}

export interface WormholeRotatedPairwiseAlias {
  ok: boolean;
  peer_id: string;
  active_alias: string;
  pending_alias: string;
  grace_until: number;
  dm_identity_id?: string;
  identity_scope?: string;
  contact?: Record<string, unknown>;
  rotated?: boolean;
}

export interface WormholeDeadDropTokensBatch {
  ok: boolean;
  tokens: Array<{ peer_id: string; peer_ref?: string; current: string; previous: string; epoch: number }>;
}

export interface WormholeSasPhrase {
  ok: boolean;
  peer_id: string;
  peer_ref?: string;
  phrase: string;
  words: number;
}

export interface WormholeSasConfirmResult {
  ok: boolean;
  peer_id: string;
  trust_level?: string;
  detail?: string;
  contact?: Record<string, unknown>;
}

export interface WormholeGatePersonasResponse {
  ok: boolean;
  gate_id: string;
  active_persona_id: string;
  personas: WormholeIdentity[];
}

export interface WormholeComposedGateMessage {
  ok: boolean;
  gate_id: string;
  identity_scope?: string;
  sender_id: string;
  public_key: string;
  public_key_algo: string;
  protocol_version: string;
  sequence: number;
  signature: string;
  epoch: number;
  ciphertext: string;
  nonce: string;
  sender_ref: string;
  format: string;
  key_commitment?: string;
  detail?: string;
}

export interface WormholeDecryptedGateMessage {
  ok: boolean;
  gate_id: string;
  epoch: number;
  plaintext: string;
  reply_to?: string;
  identity_scope?: string;
  detail?: string;
  self_authored?: boolean;
  legacy?: boolean;
}

export interface WormholeGateDecryptPayload {
  gate_id: string;
  epoch?: number;
  ciphertext: string;
  nonce?: string;
  sender_ref?: string;
  format?: string;
  gate_envelope?: string;
  envelope_hash?: string;
  recovery_envelope?: boolean;
  compat_decrypt?: boolean;
}

export interface WormholeDecryptedGateMessageBatch {
  ok: boolean;
  detail?: string;
  results: WormholeDecryptedGateMessage[];
}

export interface WormholeGateKeyStatus {
  ok: boolean;
  gate_id: string;
  current_epoch: number;
  previous_epoch?: number;
  key_commitment?: string;
  previous_key_commitment?: string;
  identity_scope?: string;
  identity_node_id?: string;
  sender_ref?: string;
  has_local_access?: boolean;
  rekey_recommended?: boolean;
  rekey_recommended_reason?: string;
  rekey_recommended_at?: number;
  last_rotated_at?: number;
  last_rotation_reason?: string;
  detail?: string;
}

export interface WormholeDmContactsResponse {
  ok: boolean;
  contacts: Record<string, Record<string, unknown>>;
}

export interface WormholeStatusSnapshot {
  ready?: boolean;
  running?: boolean;
  transport_tier?: string;
  transport_active?: string;
  transport_configured?: string;
  arti_ready?: boolean;
  anonymous_mode?: boolean;
  anonymous_mode_ready?: boolean;
  rns_enabled?: boolean;
  rns_ready?: boolean;
  rns_configured_peers?: number;
  rns_active_peers?: number;
  rns_private_dm_direct_ready?: boolean;
  recent_private_clearnet_fallback?: boolean;
  recent_private_clearnet_fallback_at?: number;
  recent_private_clearnet_fallback_reason?: string;
  clearnet_fallback_policy?: string;
  clearnet_fallback_requested?: string;
  legacy_compatibility?: LegacyCompatibilitySnapshot;
  private_delivery?: PrivateDeliverySummary;
}

export interface PreparedWormholeInteractiveLane {
  ready: boolean;
  settingsEnabled: boolean;
  transportTier: string;
  identity: WormholeIdentity | null;
}

export interface ActiveSigningContext {
  source: 'wormhole' | 'browser';
  nodeId: string;
  publicKey: string;
  publicKeyAlgo: string;
}

let wormholeIdentityCache: { value: WormholeIdentity; ts: number } | null = null;
const CACHE_TTL_MS = 3000;
const GATE_KEY_STATUS_BROWSER_CACHE_TTL_MS = 12_000;
const GATE_KEY_STATUS_NATIVE_CACHE_TTL_MS = 4_000;
const GATE_KEY_STATUS_BROWSER_ACTIVE_ROOM_TTL_MS = 24_000;
const GATE_KEY_STATUS_NATIVE_ACTIVE_ROOM_TTL_MS = 8_000;
const GATE_KEY_STATUS_BROWSER_SESSION_STREAM_TTL_MS = 36_000;
const GATE_KEY_STATUS_NATIVE_SESSION_STREAM_TTL_MS = 12_000;
type GateKeyStatusFetchMode = 'default' | 'active_room' | 'session_stream';
const gateKeyStatusCache = new Map<
  string,
  {
    value: WormholeGateKeyStatus;
    expiresAt: number;
    activeRoomExpiresAt: number;
    sessionStreamExpiresAt: number;
  }
>();
const gateKeyStatusInflight = new Map<string, Promise<WormholeGateKeyStatus>>();

function normalizeGateId(gateId: string): string {
  return String(gateId || '').trim().toLowerCase();
}

function gateKeyStatusCacheTtlMs(): number {
  return hasLocalControlBridge()
    ? GATE_KEY_STATUS_NATIVE_CACHE_TTL_MS
    : GATE_KEY_STATUS_BROWSER_CACHE_TTL_MS;
}

function gateKeyStatusActiveRoomTtlMs(): number {
  return hasLocalControlBridge()
    ? GATE_KEY_STATUS_NATIVE_ACTIVE_ROOM_TTL_MS
    : GATE_KEY_STATUS_BROWSER_ACTIVE_ROOM_TTL_MS;
}

function gateKeyStatusSessionStreamTtlMs(): number {
  return hasLocalControlBridge()
    ? GATE_KEY_STATUS_NATIVE_SESSION_STREAM_TTL_MS
    : GATE_KEY_STATUS_BROWSER_SESSION_STREAM_TTL_MS;
}

function gateKeyStatusReusableUntilMs(
  entry: {
    value: WormholeGateKeyStatus;
    expiresAt: number;
    activeRoomExpiresAt: number;
    sessionStreamExpiresAt: number;
  },
  mode: GateKeyStatusFetchMode,
): number {
  if (mode === 'session_stream' && entry.value?.has_local_access) {
    return Math.max(entry.expiresAt, entry.activeRoomExpiresAt, entry.sessionStreamExpiresAt);
  }
  if (mode === 'active_room' && entry.value?.has_local_access) {
    return Math.max(entry.expiresAt, entry.activeRoomExpiresAt);
  }
  return entry.expiresAt;
}

function isGateSessionStreamActiveForGate(gateId: string): boolean {
  const normalized = normalizeGateId(gateId);
  if (!normalized) return false;
  const status = getGateSessionStreamStatus();
  return (
    (status.phase === 'connecting' || status.phase === 'open') &&
    status.subscriptions.includes(normalized)
  );
}

type GateCompatFallbackAction = 'compose' | 'post' | 'decrypt';

const approvedGateCompatFallbacks = new Set<string>();
let gateCompatApprovalScopeCache = '';
let gateCompatApprovalsLoaded = false;

function normalizeGateCompatReason(reason: string): string {
  return String(reason || '').trim().toLowerCase() || 'browser_local_gate_crypto_unavailable';
}

function gateLocalRuntimeRequiredDetail(reason: string): string {
  return `${GATE_LOCAL_RUNTIME_REQUIRED_PREFIX}:${normalizeGateCompatReason(reason)}`;
}

function recordGateLocalRuntimeRequired(
  gateId: string,
  action: GateCompatFallbackAction,
  reason: string,
): void {
  recordGateCompatTelemetry({
    gateId,
    action,
    reason: normalizeGateCompatReason(reason),
    kind: 'required',
  });
}

function buildGateLocalRuntimeRequiredError(
  gateId: string,
  action: GateCompatFallbackAction,
  reason: string,
): Error {
  recordGateLocalRuntimeRequired(gateId, action, reason);
  return new Error(gateLocalRuntimeRequiredDetail(reason));
}

function gateCompatApprovalStorage(): Storage | null {
  if (typeof window === 'undefined') return null;
  try {
    return localStorage.getItem(KEY_SESSION_MODE) !== 'false' ? sessionStorage : localStorage;
  } catch {
    return sessionStorage;
  }
}

function gateCompatApprovalScope(): string {
  const wormholeDescriptor = getWormholeIdentityDescriptor();
  const nodeIdentity = getNodeIdentity();
  const scopeId = String(
    wormholeDescriptor?.nodeId || nodeIdentity?.nodeId || 'default',
  )
    .trim()
    .toLowerCase();
  const storage = gateCompatApprovalStorage();
  const mode = storage === localStorage ? 'persistent' : 'session';
  return `${mode}:${scopeId || 'default'}`;
}

function ensureGateCompatApprovalsLoaded(): void {
  const storage = gateCompatApprovalStorage();
  if (!storage) return;
  const scope = gateCompatApprovalScope();
  if (gateCompatApprovalsLoaded && gateCompatApprovalScopeCache === scope) {
    return;
  }
  approvedGateCompatFallbacks.clear();
  gateCompatApprovalScopeCache = scope;
  gateCompatApprovalsLoaded = true;
  try {
    const raw = storage.getItem(KEY_GATE_COMPAT_APPROVALS);
    if (!raw) return;
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    const scoped = Array.isArray(parsed?.[scope]) ? (parsed[scope] as unknown[]) : [];
    scoped
      .map((value) => normalizeGateId(String(value || '')))
      .filter(Boolean)
      .forEach((gateId) => approvedGateCompatFallbacks.add(gateId));
  } catch {
    /* ignore */
  }
}

function persistGateCompatApprovals(): void {
  const storage = gateCompatApprovalStorage();
  if (!storage) return;
  ensureGateCompatApprovalsLoaded();
  const scope = gateCompatApprovalScope();
  try {
    const raw = storage.getItem(KEY_GATE_COMPAT_APPROVALS);
    const parsed = raw ? (JSON.parse(raw) as Record<string, unknown>) : {};
    const next: Record<string, unknown> = {
      ...(parsed && typeof parsed === 'object' ? parsed : {}),
      [scope]: Array.from(approvedGateCompatFallbacks),
    };
    storage.setItem(KEY_GATE_COMPAT_APPROVALS, JSON.stringify(next));
  } catch {
    /* ignore */
  }
}

function hasApprovedGateCompatFallback(gateId: string): boolean {
  ensureGateCompatApprovalsLoaded();
  const normalized = normalizeGateId(gateId);
  return Boolean(normalized) && approvedGateCompatFallbacks.has(normalized);
}

export function approveGateCompatFallback(gateId: string): void {
  ensureGateCompatApprovalsLoaded();
  const normalized = normalizeGateId(gateId);
  if (normalized) {
    approvedGateCompatFallbacks.add(normalized);
    persistGateCompatApprovals();
  }
}

export function revokeGateCompatFallback(gateId?: string): void {
  ensureGateCompatApprovalsLoaded();
  const normalized = normalizeGateId(gateId || '');
  if (!normalized) {
    approvedGateCompatFallbacks.clear();
    persistGateCompatApprovals();
    return;
  }
  approvedGateCompatFallbacks.delete(normalized);
  persistGateCompatApprovals();
}

export function hasGateCompatFallbackApproval(gateId: string): boolean {
  return hasApprovedGateCompatFallback(gateId);
}

function cacheGateKeyStatus(gateId: string, value: WormholeGateKeyStatus): WormholeGateKeyStatus {
  const normalized = normalizeGateId(gateId || value?.gate_id || '');
  if (normalized) {
    const now = Date.now();
    gateKeyStatusCache.set(normalized, {
      value: {
        ...value,
        gate_id: normalized,
      },
      expiresAt: now + gateKeyStatusCacheTtlMs(),
      activeRoomExpiresAt:
        now +
        (value?.has_local_access ? gateKeyStatusActiveRoomTtlMs() : gateKeyStatusCacheTtlMs()),
      sessionStreamExpiresAt:
        now +
        (value?.has_local_access ? gateKeyStatusSessionStreamTtlMs() : gateKeyStatusCacheTtlMs()),
    });
  }
  return value;
}

export function invalidateWormholeGateKeyStatus(gateId?: string): void {
  const normalized = normalizeGateId(gateId || '');
  if (!normalized) {
    gateKeyStatusCache.clear();
    gateKeyStatusInflight.clear();
    return;
  }
  gateKeyStatusCache.delete(normalized);
  gateKeyStatusInflight.delete(normalized);
}

async function refreshGateSessionStreamBootstrapContext(
  gateId: string,
  options: { keyStatus?: WormholeGateKeyStatus | null } = {},
): Promise<void> {
  const normalized = normalizeGateId(gateId);
  if (!normalized || !isGateSessionStreamActiveForGate(normalized)) {
    return;
  }
  const accessHeaders = await buildGateAccessHeaders(normalized).catch(() => undefined);
  let keyStatus = options.keyStatus || null;
  if (!keyStatus) {
    keyStatus = await fetchWormholeGateKeyStatus(normalized, { force: true }).catch(() => null);
  }
  if (!accessHeaders && !keyStatus) {
    return;
  }
  setGateSessionStreamGateContext(normalized, {
    accessHeaders: accessHeaders || null,
    keyStatus: keyStatus || null,
  });
}

export async function syncBrowserWormholeGateState(
  gateId: string,
  options: { force?: boolean } = {},
): Promise<boolean> {
  if (hasLocalControlBridge()) return true;
  return syncBrowserGateState(gateId, options);
}

async function refreshBrowserWormholeGateState(gateId: string): Promise<void> {
  await forgetBrowserGateState(gateId);
  if (hasLocalControlBridge()) return;
  await syncBrowserGateState(gateId, { force: true }).catch(() => false);
}

function getBrowserSigningContext(): ActiveSigningContext | null {
  const identity = getNodeIdentity();
  if (!identity) return null;
  return {
    source: 'browser',
    nodeId: identity.nodeId,
    publicKey: identity.publicKey,
    publicKeyAlgo: getPublicKeyAlgo(),
  };
}

export async function isWormholeReady(): Promise<boolean> {
  try {
    return Boolean((await fetchWormholeState()).ready);
  } catch {
    return false;
  }
}

export async function fetchWormholeStatus(): Promise<WormholeStatusSnapshot> {
  return (await fetchWormholeState()) as WormholeStatusSnapshot;
}

export async function isWormholeSecureRequired(): Promise<boolean> {
  try {
    const data = await fetchWormholeSettings();
    const value = Boolean(data?.enabled);
    setSecureModeCached(value);
    return value;
  } catch (error) {
    console.warn(
      '[mesh] Wormhole secure-mode status unavailable, keeping cached boundary',
      error,
    );
    return isSecureModeCached();
  }
}

export async function ensureWormholeReadyForSecureAction(action: string): Promise<void> {
  const required = await isWormholeSecureRequired();
  if (!required) return;
  const ready = await isWormholeReady();
  if (!ready) {
    throw new Error(`wormhole_required_for_${action}`);
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    globalThis.setTimeout(resolve, ms);
  });
}

function normalizeWormholeTransportTier(value: string): string {
  const normalized = String(value || '').trim().toLowerCase();
  return normalized || 'public_degraded';
}

function wormholeTransportTierSatisfied(currentTier: string, minimumTier?: string): boolean {
  if (!minimumTier) return true;
  return (
    (WORMHOLE_TRANSPORT_TIER_ORDER[normalizeWormholeTransportTier(currentTier)] ?? 0) >=
    (WORMHOLE_TRANSPORT_TIER_ORDER[normalizeWormholeTransportTier(minimumTier)] ?? 0)
  );
}

function transportTierFromRuntime(
  runtime: Partial<Pick<WormholeStatusSnapshot, 'ready' | 'transport_tier' | 'transport_active'>> | null | undefined,
): string {
  if (runtime?.ready && !String(runtime?.transport_tier || runtime?.transport_active || '').trim()) {
    return 'private_control_only';
  }
  return normalizeWormholeTransportTier(
    String(runtime?.transport_tier || runtime?.transport_active || 'public_degraded'),
  );
}

function normalizeGateLifecycleError(detail: string): string {
  const message = String(detail || '').trim();
  if (!message) {
    return 'Failed to open the private gate.';
  }
  const lowered = message.toLowerCase();
  if (
    lowered.includes('transport tier insufficient') ||
    lowered.includes('wormhole_required_for_gate')
  ) {
    return 'The obfuscated lane is still starting. Give it a few seconds, then try the gate again.';
  }
  return message;
}

function normalizeWormholeInteractivePrepError(detail: string): string {
  const message = String(detail || '').trim();
  if (!message) {
    return 'Wormhole is still warming up in the background.';
  }
  const lowered = message.toLowerCase();
  if (
    lowered.includes('transport tier insufficient') ||
    lowered.includes('wormhole_required_for_') ||
    lowered.includes('still starting') ||
    lowered.includes('join failed') ||
    lowered.includes('connect failed')
  ) {
    return 'Wormhole is still warming up in the background.';
  }
  return message;
}

export async function prepareWormholeInteractiveLane(
  options: { bootstrapIdentity?: boolean; timeoutMs?: number; minimumTransportTier?: string } = {},
): Promise<PreparedWormholeInteractiveLane> {
  const minimumTransportTier = options.minimumTransportTier
    ? normalizeWormholeTransportTier(options.minimumTransportTier)
    : '';
  const inflightKey = `${options.bootstrapIdentity ? 'identity' : 'runtime'}:${minimumTransportTier || 'ready'}`;
  const existingInflight = wormholeInteractivePrepInflight.get(inflightKey);
  if (existingInflight) {
    return existingInflight;
  }
  const prepTask = (async (): Promise<PreparedWormholeInteractiveLane> => {
    const timeoutMs = Math.max(
      GATE_LIFECYCLE_PREP_POLL_MS,
      Number(options.timeoutMs || GATE_LIFECYCLE_PREP_TIMEOUT_MS),
    );
    let runtime = await fetchWormholeState(true).catch(() => null);
    let settings = await fetchWormholeSettings(true).catch(() => null);
    if (!runtime?.ready) {
      if (settings?.enabled || runtime?.configured) {
        runtime = await connectWormhole().catch((error) => {
          throw new Error(
            normalizeWormholeInteractivePrepError(
              error instanceof Error ? error.message : 'wormhole_connect_failed',
            ),
          );
        });
      } else {
        const joined = await joinWormhole().catch((error) => {
          throw new Error(
            normalizeWormholeInteractivePrepError(
              error instanceof Error ? error.message : 'wormhole_join_failed',
            ),
          );
        });
        runtime = joined?.runtime || runtime;
        settings = joined?.settings || settings;
      }
    }

    const deadline = Date.now() + timeoutMs;
    while (
      Date.now() < deadline &&
      (!runtime?.ready || !wormholeTransportTierSatisfied(transportTierFromRuntime(runtime), minimumTransportTier))
    ) {
      await sleep(GATE_LIFECYCLE_PREP_POLL_MS);
      runtime = await fetchWormholeState(true).catch(() => null);
    }
    const resolvedTransportTier = transportTierFromRuntime(runtime);
    if (!runtime?.ready || !wormholeTransportTierSatisfied(resolvedTransportTier, minimumTransportTier)) {
      throw new Error('Wormhole is still warming up in the background.');
    }

    let identity: WormholeIdentity | null = null;
    if (options.bootstrapIdentity) {
      identity = await fetchWormholeIdentity().catch(async () => {
        try {
          return await bootstrapWormholeIdentity();
        } catch (error) {
          throw new Error(
            normalizeWormholeInteractivePrepError(
              error instanceof Error ? error.message : 'wormhole_identity_bootstrap_failed',
            ),
          );
        }
      });
    }

    return {
      ready: true,
      settingsEnabled: Boolean(settings?.enabled ?? runtime?.configured ?? runtime?.running ?? true),
      transportTier: resolvedTransportTier,
      identity,
    };
  })();
  wormholeInteractivePrepInflight.set(inflightKey, prepTask);
  try {
    return await prepTask;
  } finally {
    if (wormholeInteractivePrepInflight.get(inflightKey) === prepTask) {
      wormholeInteractivePrepInflight.delete(inflightKey);
    }
  }
}

async function ensureWormholeReadyForGateLifecycle(): Promise<void> {
  let runtime = await fetchWormholeState(true).catch(() => null);
  if (runtime?.ready && wormholeTransportTierSatisfied(transportTierFromRuntime(runtime), 'private_control_only')) {
    return;
  }
  try {
    await prepareWormholeInteractiveLane({
      minimumTransportTier: 'private_control_only',
    });
  } catch (error) {
    throw new Error(
      normalizeGateLifecycleError(error instanceof Error ? error.message : 'wormhole_gate_lifecycle_prepare_failed'),
    );
  }
}

export async function fetchWormholeIdentity(): Promise<WormholeIdentity> {
  const now = Date.now();
  if (wormholeIdentityCache && now - wormholeIdentityCache.ts < CACHE_TTL_MS) {
    return wormholeIdentityCache.value;
  }
  const value = await controlPlaneJson<WormholeIdentity>('/api/wormhole/identity', {
    requireAdminSession: false,
  });
  cacheWormholeIdentityDescriptor({
    nodeId: value.node_id,
    publicKey: value.public_key,
    publicKeyAlgo: value.public_key_algo,
  });
  await purgeBrowserSigningMaterial();
  wormholeIdentityCache = { value, ts: now };
  return value;
}

export async function exportWormholeDmInvite(): Promise<WormholeDmInviteExport> {
  return controlPlaneJson<WormholeDmInviteExport>('/api/wormhole/dm/invite', {
    requireAdminSession: false,
  });
}

export async function importWormholeDmInvite(
  invite: Record<string, unknown>,
  alias: string = '',
): Promise<WormholeDmInviteImportResult> {
  const response = await controlPlaneFetch('/api/wormhole/dm/invite/import', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      invite,
      alias,
    }),
  });
  const data = (await response.json().catch(() => ({}))) as WormholeDmInviteImportResult & {
    message?: string;
  };
  if (!response.ok || data?.ok === false) {
    const error = new Error(
      String(data?.detail || data?.message || 'invite import failed'),
    ) as WormholeDmInviteImportError;
    error.name = 'WormholeDmInviteImportError';
    error.result = {
      ok: false,
      peer_id: String(data?.peer_id || ''),
      trust_fingerprint: String(data?.trust_fingerprint || ''),
      trust_level: String(data?.trust_level || ''),
      detail: String(data?.detail || data?.message || 'invite import failed'),
      contact:
        data?.contact && typeof data.contact === 'object' && !Array.isArray(data.contact)
          ? data.contact
          : {},
    };
    throw error;
  }
  return data;
}

export function getWormholeDmInviteImportErrorResult(
  error: unknown,
): WormholeDmInviteImportFailure | null {
  if (!error || typeof error !== 'object') return null;
  const result = (error as WormholeDmInviteImportError).result;
  if (!result || typeof result !== 'object') return null;
  return result;
}

export async function fetchWormholeDmRootHealth(): Promise<WormholeDmRootHealth> {
  return controlPlaneJson<WormholeDmRootHealth>('/api/wormhole/dm/root-health');
}

export async function bootstrapWormholeIdentity(): Promise<WormholeIdentity> {
  const value = await controlPlaneJson<WormholeIdentity>('/api/wormhole/identity/bootstrap', {
    requireAdminSession: false,
    method: 'POST',
  });
  cacheWormholeIdentityDescriptor({
    nodeId: value.node_id,
    publicKey: value.public_key,
    publicKeyAlgo: value.public_key_algo,
  });
  await purgeBrowserSigningMaterial();
  return value;
}

export async function signViaWormhole(
  eventType: string,
  payload: Record<string, unknown>,
  sequence?: number,
  gateId?: string,
): Promise<WormholeSignedEvent> {
  return controlPlaneJson<WormholeSignedEvent>('/api/wormhole/sign', {
    requireAdminSession: false,
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      event_type: eventType,
      payload,
      sequence,
      gate_id: gateId || '',
    }),
  });
}

export async function enterWormholeGate(
  gateId: string,
  rotate: boolean = false,
): Promise<{ ok: boolean; identity?: WormholeIdentity; detail?: string }> {
  await ensureWormholeReadyForGateLifecycle();
  let result;
  try {
    result = await controlPlaneJson<{ ok: boolean; identity?: WormholeIdentity; detail?: string }>(
      '/api/wormhole/gate/enter',
      {
        requireAdminSession: false,
        capabilityIntent: 'wormhole_gate_persona',
        sessionProfileHint: 'gate_operator',
        enforceProfileHint: true,
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          gate_id: gateId,
          rotate,
        }),
      },
    );
  } catch (error) {
    throw new Error(normalizeGateLifecycleError(error instanceof Error ? error.message : 'wormhole_gate_enter_failed'));
  }
  if (result?.ok) {
    invalidateGateAccessHeaders(gateId);
    invalidateWormholeGateKeyStatus(gateId);
    invalidateGateSessionStreamGateContext(gateId);
    await refreshBrowserWormholeGateState(gateId);
    await refreshGateSessionStreamBootstrapContext(gateId);
  }
  return result;
}

export async function leaveWormholeGate(
  gateId: string,
): Promise<{ ok: boolean; gate_id?: string; cleared?: boolean; detail?: string }> {
  const result = await controlPlaneJson<{ ok: boolean; gate_id?: string; cleared?: boolean; detail?: string }>(
    '/api/wormhole/gate/leave',
    {
      requireAdminSession: false,
      capabilityIntent: 'wormhole_gate_persona',
      sessionProfileHint: 'gate_operator',
      enforceProfileHint: true,
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        gate_id: gateId,
      }),
    },
  );
  if (result?.ok) {
    invalidateGateAccessHeaders(gateId);
    invalidateWormholeGateKeyStatus(gateId);
    invalidateGateSessionStreamGateContext(gateId);
    await forgetBrowserGateState(gateId);
  }
  return result;
}

export async function listWormholeGatePersonas(
  gateId: string,
): Promise<WormholeGatePersonasResponse> {
  return controlPlaneJson<WormholeGatePersonasResponse>(
    `/api/wormhole/gate/${encodeURIComponent(gateId)}/personas`,
    {
      requireAdminSession: false,
      capabilityIntent: 'wormhole_gate_persona',
      sessionProfileHint: 'gate_operator',
      enforceProfileHint: true,
    },
  );
}

export async function createWormholeGatePersona(
  gateId: string,
  label: string,
): Promise<{ ok: boolean; identity?: WormholeIdentity; detail?: string }> {
  await ensureWormholeReadyForGateLifecycle();
  let result;
  try {
    result = await controlPlaneJson<{ ok: boolean; identity?: WormholeIdentity; detail?: string }>(
      '/api/wormhole/gate/persona/create',
      {
        requireAdminSession: false,
        capabilityIntent: 'wormhole_gate_persona',
        sessionProfileHint: 'gate_operator',
        enforceProfileHint: true,
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          gate_id: gateId,
          label,
        }),
      },
    );
  } catch (error) {
    throw new Error(normalizeGateLifecycleError(error instanceof Error ? error.message : 'wormhole_gate_persona_create_failed'));
  }
  if (result?.ok) {
    invalidateGateAccessHeaders(gateId);
    invalidateWormholeGateKeyStatus(gateId);
    invalidateGateSessionStreamGateContext(gateId);
    await refreshBrowserWormholeGateState(gateId);
    await refreshGateSessionStreamBootstrapContext(gateId);
  }
  return result;
}

export async function activateWormholeGatePersona(
  gateId: string,
  personaId: string,
): Promise<{ ok: boolean; identity?: WormholeIdentity; detail?: string }> {
  await ensureWormholeReadyForGateLifecycle();
  let result;
  try {
    result = await controlPlaneJson<{ ok: boolean; identity?: WormholeIdentity; detail?: string }>(
      '/api/wormhole/gate/persona/activate',
      {
        requireAdminSession: false,
        capabilityIntent: 'wormhole_gate_persona',
        sessionProfileHint: 'gate_operator',
        enforceProfileHint: true,
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          gate_id: gateId,
          persona_id: personaId,
        }),
      },
    );
  } catch (error) {
    throw new Error(normalizeGateLifecycleError(error instanceof Error ? error.message : 'wormhole_gate_persona_activate_failed'));
  }
  if (result?.ok) {
    invalidateGateAccessHeaders(gateId);
    invalidateWormholeGateKeyStatus(gateId);
    invalidateGateSessionStreamGateContext(gateId);
    await refreshBrowserWormholeGateState(gateId);
    await refreshGateSessionStreamBootstrapContext(gateId);
  }
  return result;
}

export async function clearWormholeGatePersona(
  gateId: string,
): Promise<{ ok: boolean; identity?: WormholeIdentity; detail?: string }> {
  const result = await controlPlaneJson<{ ok: boolean; identity?: WormholeIdentity; detail?: string }>(
    '/api/wormhole/gate/persona/clear',
    {
      requireAdminSession: false,
      capabilityIntent: 'wormhole_gate_persona',
      sessionProfileHint: 'gate_operator',
      enforceProfileHint: true,
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        gate_id: gateId,
      }),
    },
  );
  if (result?.ok) {
    invalidateGateAccessHeaders(gateId);
    invalidateWormholeGateKeyStatus(gateId);
    invalidateGateSessionStreamGateContext(gateId);
    await refreshBrowserWormholeGateState(gateId);
    await refreshGateSessionStreamBootstrapContext(gateId);
  }
  return result;
}

export async function retireWormholeGatePersona(
  gateId: string,
  personaId: string,
): Promise<{
  ok: boolean;
  retired_persona_id?: string;
  retired_identity?: WormholeIdentity;
  active_identity?: WormholeIdentity;
  detail?: string;
}> {
  const result = await controlPlaneJson<{
    ok: boolean;
    retired_persona_id?: string;
    retired_identity?: WormholeIdentity;
    active_identity?: WormholeIdentity;
    detail?: string;
  }>('/api/wormhole/gate/persona/retire', {
    requireAdminSession: false,
    capabilityIntent: 'wormhole_gate_persona',
    sessionProfileHint: 'gate_operator',
    enforceProfileHint: true,
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      gate_id: gateId,
      persona_id: personaId,
    }),
  });
  if (result?.ok) {
    invalidateGateAccessHeaders(gateId);
    invalidateWormholeGateKeyStatus(gateId);
    invalidateGateSessionStreamGateContext(gateId);
    await refreshBrowserWormholeGateState(gateId);
    await refreshGateSessionStreamBootstrapContext(
      gateId,
      'gate_key_status' in result
        ? { keyStatus: (result as { gate_key_status?: WormholeGateKeyStatus | null }).gate_key_status || null }
        : {},
    );
  }
  return result;
}

function isGateEnvelopeRecoveryFailure(detail: string): boolean {
  return detail === 'gate_envelope_required' || detail === 'gate_envelope_encrypt_failed';
}

export async function composeWormholeGateMessage(
  gateId: string,
  plaintext: string,
  replyTo: string = '',
): Promise<WormholeComposedGateMessage> {
  if (!hasLocalControlBridge()) {
    const browserResult = await composeBrowserGateMessage(gateId, plaintext, replyTo);
    if (browserResult) {
      if (!browserResult.ok && isGateEnvelopeRecoveryFailure(String(browserResult.detail || ''))) {
        return controlPlaneJson<WormholeComposedGateMessage>('/api/wormhole/gate/message/compose', {
          requireAdminSession: false,
          capabilityIntent: 'wormhole_gate_content',
          sessionProfileHint: 'gate_operator',
          enforceProfileHint: true,
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            gate_id: gateId,
            plaintext,
            reply_to: replyTo,
            compat_plaintext: true,
          }),
        });
      }
      return browserResult as WormholeComposedGateMessage;
    }
    const fallbackReason =
      getBrowserGateCryptoFailureReason(gateId, 'compose') || 'browser_local_gate_crypto_unavailable';
    throw buildGateLocalRuntimeRequiredError(gateId, 'compose', fallbackReason);
  }
  const compatPlaintext = !hasLocalControlBridge();
  return controlPlaneJson<WormholeComposedGateMessage>('/api/wormhole/gate/message/compose', {
    requireAdminSession: false,
    capabilityIntent: 'wormhole_gate_content',
    sessionProfileHint: 'gate_operator',
    enforceProfileHint: true,
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      gate_id: gateId,
      plaintext,
      reply_to: replyTo,
      compat_plaintext: compatPlaintext,
    }),
  });
}

export async function postWormholeGateMessage(
  gateId: string,
  plaintext: string,
  replyTo: string = '',
): Promise<{ ok: boolean; detail?: string; event_id?: string }> {
  const postViaBackend = (compatPlaintext: boolean) =>
    controlPlaneJson<{ ok: boolean; detail?: string; event_id?: string }>('/api/wormhole/gate/message/post', {
      requireAdminSession: false,
      capabilityIntent: 'wormhole_gate_content',
      sessionProfileHint: 'gate_operator',
      enforceProfileHint: true,
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        gate_id: gateId,
        plaintext,
        reply_to: replyTo,
        compat_plaintext: compatPlaintext,
      }),
    });
  if (!hasLocalControlBridge()) {
    // Gate posting must be an atomic local-node operation: seal the durable
    // envelope, sign, append locally, then queue private release. Browser MLS
    // compose is still useful for compose/decrypt diagnostics, but it is not a
    // reliable commit path for Reddit-style durable gate history.
    const backendResult = await postViaBackend(true);
    if (backendResult?.ok) {
      invalidateGateMessageSnapshot(gateId);
    }
    return backendResult;
  }
  // Do NOT block on wormhole warmup here. Kick it off in the background
  // and post immediately — the backend handles tier enforcement by
  // queuing locally and releasing once the private lane is ready. This
  // avoids the minute-long "dead UI" on first-run Tor/Arti bootstrap.
  void prepareWormholeInteractiveLane({
    minimumTransportTier: 'private_control_only',
    timeoutMs: GATE_MESSAGE_PREP_TIMEOUT_MS,
  }).catch(() => {
    // swallow: background warmup, not user-facing.
  });
  const postRequest = () => postViaBackend(false);
  let result;
  try {
    result = await postRequest();
  } catch (error) {
    const detail = error instanceof Error ? error.message : 'wormhole_gate_message_post_failed';
    if (String(detail || '').toLowerCase().includes('transport tier insufficient')) {
      await prepareWormholeInteractiveLane({
        minimumTransportTier: 'private_control_only',
        timeoutMs: GATE_MESSAGE_PREP_TIMEOUT_MS,
      });
      result = await postRequest();
    } else {
      throw error;
    }
  }
  if (result?.ok) {
    invalidateGateMessageSnapshot(gateId);
  }
  return result;
}

export async function fetchWormholeGateKeyStatus(
  gateId: string,
  options: { force?: boolean; mode?: GateKeyStatusFetchMode } = {},
): Promise<WormholeGateKeyStatus> {
  const normalizedGate = normalizeGateId(gateId);
  const mode =
    options.mode === 'active_room' || options.mode === 'session_stream'
      ? options.mode
      : 'default';
  const cached = gateKeyStatusCache.get(normalizedGate);
  if (!options.force && cached && gateKeyStatusReusableUntilMs(cached, mode) > Date.now()) {
    return cached.value;
  }
  if (!options.force && mode === 'session_stream') {
    const streamStatus = getGateSessionStreamKeyStatus(normalizedGate);
    if (streamStatus && typeof streamStatus === 'object') {
      return cacheGateKeyStatus(normalizedGate, streamStatus as WormholeGateKeyStatus);
    }
  }
  if (!options.force) {
    const inflight = gateKeyStatusInflight.get(normalizedGate);
    if (inflight) {
      return inflight;
    }
  }
  const pending = controlPlaneJson<WormholeGateKeyStatus>(
    `/api/wormhole/gate/${encodeURIComponent(gateId)}/key`,
    {
      requireAdminSession: false,
      capabilityIntent: 'wormhole_gate_key',
      sessionProfileHint: 'gate_operator',
      enforceProfileHint: true,
    },
  ).then((value) => cacheGateKeyStatus(normalizedGate, value));
  if (!options.force) {
    gateKeyStatusInflight.set(normalizedGate, pending);
  }
  try {
    return await pending;
  } finally {
    gateKeyStatusInflight.delete(normalizedGate);
  }
}

export async function rotateWormholeGateKey(
  gateId: string,
  reason: string = 'manual_rotate',
): Promise<WormholeGateKeyStatus & { rotated?: boolean; rotation_reason?: string }> {
  const result = await controlPlaneJson<WormholeGateKeyStatus & { rotated?: boolean; rotation_reason?: string }>(
    '/api/wormhole/gate/key/rotate',
    {
      requireAdminSession: false,
      capabilityIntent: 'wormhole_gate_key',
      sessionProfileHint: 'gate_operator',
      enforceProfileHint: true,
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        gate_id: gateId,
        reason,
      }),
    },
  );
  if (result?.ok) {
    invalidateGateAccessHeaders(gateId);
    invalidateGateSessionStreamGateContext(gateId);
    cacheGateKeyStatus(gateId, result);
    await refreshBrowserWormholeGateState(gateId);
    await refreshGateSessionStreamBootstrapContext(gateId, { keyStatus: result });
  }
  return result;
}

export async function resyncWormholeGateState(
  gateId: string,
): Promise<{
  ok: boolean;
  gate_id?: string;
  epoch?: number;
  active_identity_scope?: string;
  active_persona_id?: string;
  active_node_id?: string;
  detail?: string;
}> {
  const result = await controlPlaneJson<{
    ok: boolean;
    gate_id?: string;
    epoch?: number;
    active_identity_scope?: string;
    active_persona_id?: string;
    active_node_id?: string;
    detail?: string;
  }>('/api/wormhole/gate/state/export', {
    requireAdminSession: false,
    capabilityIntent: 'wormhole_gate_key',
    sessionProfileHint: 'gate_operator',
    enforceProfileHint: true,
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        gate_id: gateId,
      }),
    });
  invalidateGateAccessHeaders(gateId);
  invalidateWormholeGateKeyStatus(gateId);
  invalidateGateSessionStreamGateContext(gateId);
  if (result?.ok) {
    await syncBrowserWormholeGateState(gateId, { force: true }).catch(() => false);
    await refreshGateSessionStreamBootstrapContext(gateId);
  }
  return result;
}

function canRecoverGateHistoryViaEnvelope(
  message: Pick<WormholeGateDecryptPayload, 'gate_envelope' | 'recovery_envelope'> | null | undefined,
): boolean {
  if (!message || message.recovery_envelope) return false;
  return String(message.gate_envelope || '').trim().length > 0;
}

export async function decryptWormholeGateMessage(
  gateId: string,
  epoch: number,
  ciphertext: string,
  nonce: string,
  senderRef: string,
  gateEnvelope: string = '',
  envelopeHash: string = '',
  recoveryEnvelope: boolean = false,
): Promise<WormholeDecryptedGateMessage> {
  if (!hasLocalControlBridge() && !recoveryEnvelope) {
    const browserBatch = await decryptBrowserGateMessages([
      {
        gate_id: gateId,
        epoch,
        ciphertext,
      },
    ]);
    const first = browserBatch?.results?.[0];
    if (first?.ok) {
      return first as WormholeDecryptedGateMessage;
    }
    if (canRecoverGateHistoryViaEnvelope({ gate_envelope: gateEnvelope })) {
      return decryptWormholeGateMessage(
        gateId,
        epoch,
        ciphertext,
        nonce,
        senderRef,
        gateEnvelope,
        envelopeHash,
        true,
      );
    }
    if (first) {
      return first as WormholeDecryptedGateMessage;
    }
    const fallbackReason =
      getBrowserGateCryptoFailureReason(gateId, 'decrypt') || 'browser_local_gate_crypto_unavailable';
    throw buildGateLocalRuntimeRequiredError(gateId, 'decrypt', fallbackReason);
  }
  const compatDecrypt = !hasLocalControlBridge() && !recoveryEnvelope;
  return controlPlaneJson<WormholeDecryptedGateMessage>('/api/wormhole/gate/message/decrypt', {
    requireAdminSession: false,
    capabilityIntent: 'wormhole_gate_content',
    sessionProfileHint: 'gate_operator',
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      gate_id: gateId,
      epoch,
      ciphertext,
      nonce,
      sender_ref: senderRef,
      gate_envelope: gateEnvelope,
      envelope_hash: envelopeHash,
      recovery_envelope: recoveryEnvelope,
      compat_decrypt: compatDecrypt,
    }),
  });
}

export async function decryptWormholeGateMessages(
  messages: WormholeGateDecryptPayload[],
): Promise<WormholeDecryptedGateMessageBatch> {
  const browserGateIds = Array.from(
    new Set(
      messages
        .map((message) => normalizeGateId(String(message.gate_id || '')))
        .filter(Boolean),
    ),
  );
  if (
    !hasLocalControlBridge() &&
    messages.length > 0 &&
    messages.every(
      (message) =>
        !message.recovery_envelope &&
        String(message.format || 'mls1').toLowerCase() === 'mls1' &&
        message.compat_decrypt !== true,
    )
  ) {
    const browserBatch = await decryptBrowserGateMessages(
      messages.map((message) => ({
        gate_id: message.gate_id,
        epoch: Number(message.epoch || 0),
        ciphertext: message.ciphertext,
      })),
    );
    const recoveryIndexes = messages
      .map((message, index) => ({
        index,
        message,
        result: browserBatch?.results?.[index],
      }))
      .filter(({ message, result }) => canRecoverGateHistoryViaEnvelope(message) && !result?.ok);
    if (recoveryIndexes.length > 0) {
      const recoveredBatch = await decryptWormholeGateMessages(
        recoveryIndexes.map(({ message }) => ({
          ...message,
          recovery_envelope: true,
          compat_decrypt: false,
        })),
      );
      const baseResults =
        browserBatch?.results?.slice() ||
        messages.map((message) => ({
          ok: false,
          gate_id: String(message.gate_id || ''),
          epoch: Number(message.epoch || 0),
          detail: gateLocalRuntimeRequiredDetail(
            getBrowserGateCryptoFailureReason(String(message.gate_id || ''), 'decrypt') ||
              'browser_local_gate_crypto_unavailable',
          ),
        }));
      const recoveredResults = Array.isArray(recoveredBatch?.results) ? recoveredBatch.results : [];
      recoveryIndexes.forEach(({ index }, recoveryIndex) => {
        const recovered = recoveredResults[recoveryIndex];
        if (recovered) {
          baseResults[index] = recovered;
        }
      });
      return {
        ok: true,
        detail: browserBatch?.detail || recoveredBatch?.detail,
        results: baseResults as WormholeDecryptedGateMessage[],
      };
    }
    if (browserBatch) {
      return browserBatch as WormholeDecryptedGateMessageBatch;
    }
    const fallbackReason =
      getBrowserGateCryptoFailureReason(browserGateIds[0] || '', 'decrypt') ||
      'browser_local_gate_crypto_unavailable';
    browserGateIds.forEach((gateId) =>
      recordGateLocalRuntimeRequired(
        gateId,
        'decrypt',
        getBrowserGateCryptoFailureReason(gateId, 'decrypt') ||
          'browser_local_gate_crypto_unavailable',
      ),
    );
    throw new Error(gateLocalRuntimeRequiredDetail(fallbackReason));
  }
  const compatDecrypt = !hasLocalControlBridge();
  return controlPlaneJson<WormholeDecryptedGateMessageBatch>('/api/wormhole/gate/messages/decrypt', {
    requireAdminSession: false,
    capabilityIntent: 'wormhole_gate_content',
    sessionProfileHint: 'gate_operator',
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      messages: messages.map((message) => ({
        gate_id: message.gate_id,
        epoch: Number(message.epoch || 0),
        ciphertext: message.ciphertext,
        nonce: message.nonce || '',
        sender_ref: message.sender_ref || '',
        format: message.format || 'mls1',
        gate_envelope: message.gate_envelope || '',
        envelope_hash: message.envelope_hash || '',
        recovery_envelope: Boolean(message.recovery_envelope),
        compat_decrypt:
          message.compat_decrypt ??
          (compatDecrypt && !Boolean(message.recovery_envelope)),
      })),
    }),
  });
}

export async function signRawViaWormhole(message: string): Promise<WormholeSignedRawMessage> {
  return controlPlaneJson<WormholeSignedRawMessage>('/api/wormhole/sign-raw', {
    requireAdminSession: false,
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message }),
  });
}

export async function registerWormholeDmKey(): Promise<WormholeIdentity & { ok: boolean; detail?: string }> {
  return controlPlaneJson<WormholeIdentity & { ok: boolean; detail?: string }>(
    '/api/wormhole/dm/register-key',
    {
    method: 'POST',
    },
  );
}

export async function issueWormholeDmSenderToken(
  recipientId: string,
  deliveryClass: 'request' | 'shared',
  recipientToken?: string,
): Promise<WormholeDmSenderToken> {
  return controlPlaneJson<WormholeDmSenderToken>('/api/wormhole/dm/sender-token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      recipient_id: recipientId,
      delivery_class: deliveryClass,
      recipient_token: recipientToken || '',
    }),
  });
}

export async function issueWormholeDmSenderTokens(
  recipientId: string,
  deliveryClass: 'request' | 'shared',
  recipientToken?: string,
  count: number = 3,
): Promise<WormholeDmSenderTokenBatch> {
  return controlPlaneJson<WormholeDmSenderTokenBatch>('/api/wormhole/dm/sender-token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      recipient_id: recipientId,
      delivery_class: deliveryClass,
      recipient_token: recipientToken || '',
      count,
    }),
  });
}

export async function runWormholeDmSelftest(message = ''): Promise<WormholeDmSelftestResult> {
  return controlPlaneJson<WormholeDmSelftestResult>('/api/wormhole/dm/selftest', {
    method: 'POST',
    requireAdminSession: false,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message }),
  });
}

export async function openWormholeSenderSeal(
  senderSeal: string,
  candidateDhPub: string,
  recipientId: string,
  expectedMsgId: string,
): Promise<WormholeOpenedSeal> {
  return controlPlaneJson<WormholeOpenedSeal>('/api/wormhole/dm/open-seal', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      sender_seal: senderSeal,
      candidate_dh_pub: candidateDhPub,
      recipient_id: recipientId,
      expected_msg_id: expectedMsgId,
    }),
  });
}

export async function buildWormholeSenderSeal(
  recipientId: string,
  recipientDhPub: string,
  msgId: string,
  timestamp: number,
): Promise<WormholeBuiltSeal> {
  return controlPlaneJson<WormholeBuiltSeal>('/api/wormhole/dm/build-seal', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      recipient_id: recipientId,
      recipient_dh_pub: recipientDhPub,
      msg_id: msgId,
      timestamp,
    }),
  });
}

export async function deriveWormholeDeadDropTokenPair(
  peerId: string,
  peerDhPub: string,
  peerRef: string = '',
): Promise<WormholeDeadDropTokenPair> {
  return controlPlaneJson<WormholeDeadDropTokenPair>('/api/wormhole/dm/dead-drop-token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      peer_id: peerId,
      peer_dh_pub: peerDhPub,
      peer_ref: peerRef,
    }),
  });
}

export async function issueWormholePairwiseAlias(
  peerId: string,
  peerDhPub: string,
): Promise<WormholePairwiseAlias> {
  return controlPlaneJson<WormholePairwiseAlias>('/api/wormhole/dm/pairwise-alias', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      peer_id: peerId,
      peer_dh_pub: peerDhPub,
    }),
  });
}

export async function rotateWormholePairwiseAlias(
  peerId: string,
  peerDhPub: string,
  graceMs: number,
): Promise<WormholeRotatedPairwiseAlias> {
  return controlPlaneJson<WormholeRotatedPairwiseAlias>('/api/wormhole/dm/pairwise-alias/rotate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      peer_id: peerId,
      peer_dh_pub: peerDhPub,
      grace_ms: graceMs,
    }),
  });
}

export async function deriveWormholeDeadDropTokens(
  contacts: Array<{ peer_id: string; peer_dh_pub: string; peer_ref?: string; peer_refs?: string[] }>,
  limit: number = 24,
): Promise<WormholeDeadDropTokensBatch> {
  return controlPlaneJson<WormholeDeadDropTokensBatch>('/api/wormhole/dm/dead-drop-tokens', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      contacts,
      limit,
    }),
  });
}

export async function deriveWormholeSasPhrase(
  peerId: string,
  peerDhPub: string,
  words: number = 8,
  peerRef: string = '',
): Promise<WormholeSasPhrase> {
  return controlPlaneJson<WormholeSasPhrase>('/api/wormhole/dm/sas', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      peer_id: peerId,
      peer_dh_pub: peerDhPub,
      words,
      peer_ref: peerRef,
    }),
  });
}

export async function confirmWormholeSasVerification(
  peerId: string,
  sasPhrase: string,
  peerRef: string = '',
  words: number = 8,
): Promise<WormholeSasConfirmResult> {
  return controlPlaneJson<WormholeSasConfirmResult>('/api/wormhole/dm/sas/confirm', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      peer_id: peerId,
      sas_phrase: sasPhrase,
      peer_ref: peerRef,
      words,
    }),
  });
}

export async function acknowledgeWormholeSasFingerprint(
  peerId: string,
): Promise<WormholeSasConfirmResult> {
  return controlPlaneJson<WormholeSasConfirmResult>('/api/wormhole/dm/sas/acknowledge', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      peer_id: peerId,
    }),
  });
}

export async function recoverWormholeSasRootContinuity(
  peerId: string,
  sasPhrase: string,
  peerRef: string = '',
  words: number = 8,
): Promise<WormholeSasConfirmResult> {
  return controlPlaneJson<WormholeSasConfirmResult>('/api/wormhole/dm/sas/recover-root', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      peer_id: peerId,
      sas_phrase: sasPhrase,
      peer_ref: peerRef,
      words,
    }),
  });
}

export async function listWormholeDmContacts(): Promise<WormholeDmContactsResponse> {
  return controlPlaneJson<WormholeDmContactsResponse>('/api/wormhole/dm/contacts');
}

export async function putWormholeDmContact(
  peerId: string,
  contact: Record<string, unknown>,
): Promise<{ ok: boolean; peer_id: string; contact: Record<string, unknown> }> {
  return controlPlaneJson('/api/wormhole/dm/contact', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      peer_id: peerId,
      contact,
    }),
  });
}

export async function deleteWormholeDmContact(
  peerId: string,
): Promise<{ ok: boolean; peer_id: string; deleted: boolean }> {
  return controlPlaneJson(`/api/wormhole/dm/contact/${encodeURIComponent(peerId)}`, {
    method: 'DELETE',
  });
}

export async function getActiveSigningContext(): Promise<ActiveSigningContext | null> {
  const secureRequired = await isWormholeSecureRequired();
  if (await isWormholeReady()) {
    const identity = await fetchWormholeIdentity();
    if (identity?.node_id && identity?.public_key) {
      return {
        source: 'wormhole',
        nodeId: identity.node_id,
        publicKey: identity.public_key,
        publicKeyAlgo: identity.public_key_algo,
      };
    }
  }
  if (secureRequired) {
    return null;
  }
  return getBrowserSigningContext();
}

export async function signMeshEvent(
  eventType: string,
  payload: Record<string, unknown>,
  sequence: number,
  options?: { gateId?: string },
): Promise<{ signature: string; context: ActiveSigningContext; protocolVersion: string; sequence: number }> {
  await ensureWormholeReadyForSecureAction(`sign_${eventType}`);
  const context = await getActiveSigningContext();
  if (!context) {
    throw new Error('No identity available for signing');
  }
  if (context.source === 'wormhole') {
    try {
      const signed = await signViaWormhole(
        eventType,
        payload,
        sequence,
        options?.gateId,
      );
      return {
        signature: signed.signature,
        context: {
          source: 'wormhole',
          nodeId: signed.node_id,
          publicKey: signed.public_key,
          publicKeyAlgo: signed.public_key_algo,
        },
        protocolVersion: signed.protocol_version,
        sequence: signed.sequence,
      };
    } catch {
      if (await isWormholeSecureRequired()) {
        throw new Error(`wormhole_sign_failed_${eventType}`);
      }
      console.warn(
        '[PRIVACY] Wormhole signing failed for %s — falling back to browser-side signing. ' +
          'Private key material is active in browser memory. Enable secure mode to block this fallback.',
        eventType,
      );
      if (typeof window !== 'undefined') {
        window.dispatchEvent(new CustomEvent('sb:signing-fallback', { detail: { eventType } }));
      }
      const browserContext = getBrowserSigningContext();
      if (!browserContext) throw new Error('No identity available for signing');
      return {
        signature: await signEvent(eventType, browserContext.nodeId, sequence, payload),
        context: browserContext,
        protocolVersion: PROTOCOL_VERSION,
        sequence,
      };
    }
  }
  return {
    signature: await signEvent(eventType, context.nodeId, sequence, payload),
    context,
    protocolVersion: PROTOCOL_VERSION,
    sequence,
  };
}

export async function signRawMeshMessage(
  message: string,
): Promise<{ signature: string; context: ActiveSigningContext; protocolVersion: string }> {
  await ensureWormholeReadyForSecureAction('sign_raw');
  const context = await getActiveSigningContext();
  if (!context) {
    throw new Error('No identity available for signing');
  }
  if (context.source === 'wormhole') {
    try {
      const signed = await signRawViaWormhole(message);
      return {
        signature: signed.signature,
        context: {
          source: 'wormhole',
          nodeId: signed.node_id,
          publicKey: signed.public_key,
          publicKeyAlgo: signed.public_key_algo,
        },
        protocolVersion: signed.protocol_version,
      };
    } catch {
      if (await isWormholeSecureRequired()) {
        throw new Error('wormhole_sign_raw_failed');
      }
      console.warn(
        '[PRIVACY] Wormhole raw signing failed — falling back to browser-side signing. ' +
          'Private key material is active in browser memory. Enable secure mode to block this fallback.',
      );
      if (typeof window !== 'undefined') {
        window.dispatchEvent(
          new CustomEvent('sb:signing-fallback', { detail: { eventType: 'sign_raw' } }),
        );
      }
      const identity = getNodeIdentity();
      if (!identity) throw new Error('No identity available for signing');
      const sig = await signWithStoredKey(message).catch(() => {
        throw new Error('browser_signing_key_unavailable');
      });
      return {
        signature: sig,
        context: {
          source: 'browser',
          nodeId: identity.nodeId,
          publicKey: identity.publicKey,
          publicKeyAlgo: getPublicKeyAlgo(),
        },
        protocolVersion: PROTOCOL_VERSION,
      };
    }
  }
  const identity = getNodeIdentity();
  if (!identity) throw new Error('No identity available for signing');
  const sig = await signWithStoredKey(message).catch(() => {
    throw new Error('browser_signing_key_unavailable');
  });
  return {
    signature: sig,
    context,
    protocolVersion: PROTOCOL_VERSION,
  };
}
