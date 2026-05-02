import { controlPlaneJson } from '@/lib/controlPlane';
import type { WorkerGateStateSnapshot } from '@/mesh/meshGateWorkerVault';
import type {
  InlineGateCryptoSupport,
  LocalGateComposeResult,
  LocalGateDecryptResult,
} from '@/mesh/meshGateLocalRuntime';

type WorkerRequest =
  | { id: string; action: 'supported' }
  | { id: string; action: 'adopt'; snapshot: WorkerGateStateSnapshot }
  | { id: string; action: 'compose'; gateId: string; plaintext: string; replyTo?: string }
  | {
      id: string;
      action: 'decryptBatch';
      messages: Array<{ gate_id: string; epoch?: number; ciphertext: string }>;
    }
  | { id: string; action: 'forget'; gateId?: string };

type WorkerResponse = { id: string; ok: boolean; result?: unknown; error?: string };
type WorkerRequestPayload = WorkerRequest extends infer Request
  ? Request extends WorkerRequest
    ? Omit<Request, 'id'>
    : never
  : never;

type BrowserGateComposeResult = {
  gate_id: string;
  epoch: number;
  ciphertext: string;
  nonce: string;
};

type BrowserGateDecryptResult = {
  ok: boolean;
  gate_id: string;
  epoch?: number;
  plaintext?: string;
  reply_to?: string;
  detail?: string;
  identity_scope?: string;
};

type BrowserGateCryptoAction = 'compose' | 'post' | 'decrypt';
type BrowserGateRuntimeMode = 'worker' | 'inline';
type BrowserGateLocalRuntimeMode = BrowserGateRuntimeMode | 'unavailable' | 'unknown';
type BrowserGateLocalRuntimeHealth = 'active' | 'degraded' | 'unavailable' | 'unknown';
type BrowserGateSelfEchoEntry = {
  plaintext: string;
  replyTo: string;
  epoch: number;
  cachedAt: number;
};

type SignedGateEnvelope = {
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
  timestamp?: number;
  gate_envelope?: string;
  envelope_hash?: string;
  reply_to?: string;
  detail?: string;
};

let worker: Worker | null = null;
let reqCounter = 0;
let browserGateCryptoSupport: Promise<boolean> | null = null;
let browserGateCryptoSupportReason = '';
let browserGateRuntimeMode: BrowserGateRuntimeMode | null = null;
let browserGateInlineRuntimePromise: Promise<typeof import('./meshGateLocalRuntime')> | null = null;
const pending = new Map<string, { resolve: (v: unknown) => void; reject: (err: Error) => void }>();
const browserGateCryptoFailureReasons = new Map<string, string>();
const browserGateStateSyncFreshUntil = new Map<string, number>();
const BROWSER_GATE_STATE_SYNC_TTL_MS = 15_000;
const browserGateSelfEchoCache = new Map<string, BrowserGateSelfEchoEntry>();
const BROWSER_GATE_SELF_ECHO_TTL_MS = 5 * 60_000;
const BROWSER_GATE_SELF_ECHO_MAX = 256;
const GATE_LOCAL_RUNTIME_EVENT = 'sb:gate-local-runtime';

export interface BrowserGateLocalRuntimeStatus {
  mode: BrowserGateLocalRuntimeMode;
  health: BrowserGateLocalRuntimeHealth;
  reason: string;
  updatedAt: number;
}

let browserGateLocalRuntimeStatus: BrowserGateLocalRuntimeStatus = {
  mode: 'unknown',
  health: 'unknown',
  reason: '',
  updatedAt: 0,
};

function normalizeGateId(gateId: string): string {
  return String(gateId || '').trim().toLowerCase();
}

function dispatchBrowserGateLocalRuntimeStatus(): void {
  if (typeof window === 'undefined') return;
  try {
    window.dispatchEvent(
      new CustomEvent(GATE_LOCAL_RUNTIME_EVENT, {
        detail: getBrowserGateLocalRuntimeStatus(),
      }),
    );
  } catch {
    /* ignore */
  }
}

function normalizeBrowserGateRuntimeReason(reason: string): string {
  const detail = String(reason || '').trim().toLowerCase();
  if (!detail) return 'browser_local_gate_crypto_unavailable';
  if (
    detail === 'browser_runtime_unavailable' ||
    detail === 'browser_local_gate_crypto_unavailable' ||
    detail === 'browser_gate_worker_unavailable' ||
    detail === 'browser_gate_webcrypto_unavailable' ||
    detail === 'browser_gate_indexeddb_unavailable' ||
    detail === 'browser_gate_storage_unavailable' ||
    detail === 'browser_gate_wasm_unavailable' ||
    detail === 'browser_gate_state_active_member_missing' ||
    detail === 'worker_gate_wrap_key_missing' ||
    detail === 'gate_mls_decrypt_failed' ||
    detail === 'gate_sign_failed'
  ) {
    return detail;
  }
  if (
    detail.startsWith('browser_gate_state_resync_required:') ||
    detail.startsWith('browser_gate_state_mapping_missing_group:')
  ) {
    return detail;
  }
  if (detail.includes('indexeddb')) return 'browser_gate_indexeddb_unavailable';
  if (detail.includes('database') || detail.includes('idb')) return 'browser_gate_storage_unavailable';
  if (detail.includes('webcrypto') || detail.includes('subtlecrypto') || detail.includes('crypto.subtle')) {
    return 'browser_gate_webcrypto_unavailable';
  }
  if (detail.includes('wasm') || detail.includes('privacy_core')) return 'browser_gate_wasm_unavailable';
  if (detail.includes('worker')) return 'browser_gate_worker_unavailable';
  return detail;
}

function describeBrowserGateLocalRuntimeReason(reason: string): string {
  const detail = normalizeBrowserGateRuntimeReason(reason);
  if (detail === 'browser_gate_worker_unavailable') return 'worker unavailable';
  if (detail === 'browser_gate_webcrypto_unavailable') return 'WebCrypto unavailable';
  if (detail === 'browser_gate_indexeddb_unavailable') return 'IndexedDB unavailable';
  if (detail === 'browser_gate_storage_unavailable' || detail === 'worker_gate_wrap_key_missing') {
    return 'secure storage unavailable';
  }
  if (detail === 'browser_gate_wasm_unavailable') return 'crypto runtime unavailable';
  if (detail.startsWith('browser_gate_state_resync_required:')) return 'state resync required';
  if (
    detail.startsWith('browser_gate_state_mapping_missing_group:') ||
    detail === 'browser_gate_state_active_member_missing'
  ) {
    return 'state incomplete';
  }
  if (detail === 'gate_mls_decrypt_failed') return 'decrypt failed';
  if (detail === 'gate_sign_failed') return 'sign failed';
  if (detail === 'browser_runtime_unavailable') return 'runtime unavailable';
  return detail || 'runtime unavailable';
}

function setBrowserGateLocalRuntimeStatus(
  mode: BrowserGateLocalRuntimeMode,
  health: BrowserGateLocalRuntimeHealth,
  reason: string = '',
): void {
  const normalizedReason = String(reason || '').trim();
  if (
    browserGateLocalRuntimeStatus.mode === mode &&
    browserGateLocalRuntimeStatus.health === health &&
    browserGateLocalRuntimeStatus.reason === normalizedReason
  ) {
    return;
  }
  browserGateLocalRuntimeStatus = {
    mode,
    health,
    reason: normalizedReason,
    updatedAt: Date.now(),
  };
  dispatchBrowserGateLocalRuntimeStatus();
}

function markBrowserGateLocalRuntimeActive(mode: BrowserGateRuntimeMode | null): void {
  if (mode === 'worker') {
    setBrowserGateLocalRuntimeStatus('worker', 'active');
    return;
  }
  if (mode === 'inline') {
    setBrowserGateLocalRuntimeStatus(
      'inline',
      'active',
      normalizeBrowserGateRuntimeReason(browserGateCryptoSupportReason || 'browser_gate_worker_unavailable'),
    );
    return;
  }
  setBrowserGateLocalRuntimeStatus('unknown', 'unknown');
}

function markBrowserGateLocalRuntimeUnavailable(reason: string): void {
  setBrowserGateLocalRuntimeStatus(
    'unavailable',
    'unavailable',
    normalizeBrowserGateRuntimeReason(reason),
  );
}

function markBrowserGateLocalRuntimeDegraded(
  reason: string,
  preferredMode: BrowserGateRuntimeMode | null = browserGateRuntimeMode,
): void {
  const normalizedReason = normalizeBrowserGateRuntimeReason(reason);
  if (preferredMode === 'worker' || preferredMode === 'inline') {
    setBrowserGateLocalRuntimeStatus(preferredMode, 'degraded', normalizedReason);
    return;
  }
  markBrowserGateLocalRuntimeUnavailable(normalizedReason);
}

export function getBrowserGateLocalRuntimeStatus(): BrowserGateLocalRuntimeStatus {
  return { ...browserGateLocalRuntimeStatus };
}

export function getBrowserGateLocalRuntimeEventName(): string {
  return GATE_LOCAL_RUNTIME_EVENT;
}

export function describeBrowserGateLocalRuntimeStatus(
  status: BrowserGateLocalRuntimeStatus | null | undefined,
): string {
  const current = status || browserGateLocalRuntimeStatus;
  if (current.mode === 'worker' && current.health === 'active') {
    return 'WORKER local gate runtime active';
  }
  if (current.mode === 'inline' && current.health === 'active') {
    return current.reason === 'browser_gate_worker_unavailable'
      ? 'INLINE local gate runtime active (worker unavailable)'
      : 'INLINE local gate runtime active';
  }
  if ((current.mode === 'worker' || current.mode === 'inline') && current.health === 'degraded') {
    return `${current.mode.toUpperCase()} local gate runtime degraded (${describeBrowserGateLocalRuntimeReason(current.reason)})`;
  }
  if (current.mode === 'unavailable' || current.health === 'unavailable') {
    return current.reason
      ? `Local gate runtime unavailable (${describeBrowserGateLocalRuntimeReason(current.reason)})`
      : 'Local gate runtime unavailable';
  }
  return 'Local gate runtime not checked yet';
}

function failureReasonKey(gateId: string, action: BrowserGateCryptoAction): string {
  return `${normalizeGateId(gateId)}::${action}`;
}

function browserGateSelfEchoKey(gateId: string, ciphertext: string): string {
  return `${normalizeGateId(gateId)}::${String(ciphertext || '').trim()}`;
}

function pruneBrowserGateSelfEchoCache(now: number = Date.now()): void {
  for (const [key, entry] of browserGateSelfEchoCache.entries()) {
    if (now - Number(entry.cachedAt || 0) > BROWSER_GATE_SELF_ECHO_TTL_MS) {
      browserGateSelfEchoCache.delete(key);
    }
  }
  while (browserGateSelfEchoCache.size > BROWSER_GATE_SELF_ECHO_MAX) {
    const oldestKey = browserGateSelfEchoCache.keys().next().value;
    if (!oldestKey) break;
    browserGateSelfEchoCache.delete(oldestKey);
  }
}

function rememberBrowserGateSelfEcho(
  gateId: string,
  ciphertext: string,
  plaintext: string,
  replyTo: string,
  epoch: number,
): void {
  const normalizedGate = normalizeGateId(gateId);
  const normalizedCiphertext = String(ciphertext || '').trim();
  if (!normalizedGate || !normalizedCiphertext) return;
  pruneBrowserGateSelfEchoCache();
  const key = browserGateSelfEchoKey(normalizedGate, normalizedCiphertext);
  if (browserGateSelfEchoCache.has(key)) {
    browserGateSelfEchoCache.delete(key);
  }
  browserGateSelfEchoCache.set(key, {
    plaintext: String(plaintext || ''),
    replyTo: String(replyTo || '').trim(),
    epoch: Number(epoch || 0),
    cachedAt: Date.now(),
  });
  pruneBrowserGateSelfEchoCache();
}

function peekBrowserGateSelfEcho(gateId: string, ciphertext: string): BrowserGateSelfEchoEntry | null {
  const normalizedGate = normalizeGateId(gateId);
  const normalizedCiphertext = String(ciphertext || '').trim();
  if (!normalizedGate || !normalizedCiphertext) return null;
  pruneBrowserGateSelfEchoCache();
  const key = browserGateSelfEchoKey(normalizedGate, normalizedCiphertext);
  const cached = browserGateSelfEchoCache.get(key);
  if (!cached) return null;
  browserGateSelfEchoCache.delete(key);
  browserGateSelfEchoCache.set(key, cached);
  return cached;
}

function clearBrowserGateSelfEcho(gateId?: string): void {
  const normalizedGate = normalizeGateId(gateId || '');
  if (!normalizedGate) {
    browserGateSelfEchoCache.clear();
    return;
  }
  for (const key of Array.from(browserGateSelfEchoCache.keys())) {
    if (key.startsWith(`${normalizedGate}::`)) {
      browserGateSelfEchoCache.delete(key);
    }
  }
}

function rememberBrowserGateCryptoFailure(
  gateId: string,
  action: BrowserGateCryptoAction,
  reason: string,
): void {
  const normalized = normalizeGateId(gateId);
  if (!normalized) return;
  browserGateCryptoFailureReasons.set(
    failureReasonKey(normalized, action),
    normalizeBrowserGateRuntimeReason(reason),
  );
}

function clearBrowserGateCryptoFailure(gateId: string, action: BrowserGateCryptoAction): void {
  const normalized = normalizeGateId(gateId);
  if (!normalized) return;
  browserGateCryptoFailureReasons.delete(failureReasonKey(normalized, action));
}

function rememberBrowserGateCryptoFailureForAllActions(gateId: string, reason: string): void {
  (['compose', 'post', 'decrypt'] as BrowserGateCryptoAction[]).forEach((action) =>
    rememberBrowserGateCryptoFailure(gateId, action, reason),
  );
}

function clearBrowserGateCryptoFailureForAllActions(gateId: string): void {
  (['compose', 'post', 'decrypt'] as BrowserGateCryptoAction[]).forEach((action) =>
    clearBrowserGateCryptoFailure(gateId, action),
  );
}

function markBrowserGateStateFresh(gateId: string): void {
  const normalized = normalizeGateId(gateId);
  if (!normalized) return;
  browserGateStateSyncFreshUntil.set(normalized, Date.now() + BROWSER_GATE_STATE_SYNC_TTL_MS);
}

function clearBrowserGateStateFresh(gateId?: string): void {
  const normalized = normalizeGateId(gateId || '');
  if (!normalized) {
    browserGateStateSyncFreshUntil.clear();
    return;
  }
  browserGateStateSyncFreshUntil.delete(normalized);
}

function isBrowserGateStateFresh(gateId: string): boolean {
  const normalized = normalizeGateId(gateId);
  if (!normalized) return false;
  return Number(browserGateStateSyncFreshUntil.get(normalized) || 0) > Date.now();
}

export function getBrowserGateCryptoFailureReason(
  gateId: string,
  action: BrowserGateCryptoAction,
): string {
  return browserGateCryptoFailureReasons.get(failureReasonKey(gateId, action)) || '';
}

function ensureWorker(): Worker {
  if (worker) return worker;
  worker = new Worker(new URL('./meshGate.worker.ts', import.meta.url), { type: 'module' });
  worker.onmessage = (event: MessageEvent<WorkerResponse>) => {
    const msg = event.data;
    const handler = pending.get(msg.id);
    if (!handler) return;
    pending.delete(msg.id);
    if (msg.ok) {
      handler.resolve(msg.result);
    } else {
      handler.reject(new Error(msg.error || 'worker_error'));
    }
  };
  return worker;
}

async function loadInlineRuntime() {
  if (!browserGateInlineRuntimePromise) {
    browserGateInlineRuntimePromise = import('./meshGateLocalRuntime');
  }
  return browserGateInlineRuntimePromise;
}

function callWorker<T>(payload: WorkerRequestPayload): Promise<T> {
  const id = `gatew_${Date.now()}_${reqCounter++}`;
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve: (value: unknown) => resolve(value as T), reject });
    try {
      ensureWorker().postMessage({ ...payload, id } as WorkerRequest);
    } catch (error) {
      pending.delete(id);
      reject(error as Error);
    }
  });
}

async function callInlineRuntime<T>(payload: WorkerRequestPayload): Promise<T> {
  const runtime = await loadInlineRuntime();
  switch (payload.action) {
    case 'supported':
      return (await runtime.probeInlineGateCryptoSupport()) as T;
    case 'adopt':
      return (await runtime.adoptInlineGateState(payload.snapshot)) as T;
    case 'compose':
      return (await runtime.composeInlineGateMessage(
        payload.gateId,
        payload.plaintext,
        payload.replyTo || '',
      )) as T;
    case 'decryptBatch':
      return (await runtime.decryptInlineGateMessages(payload.messages)) as T;
    case 'forget':
      await runtime.forgetInlineGateState(payload.gateId);
      return true as T;
    default:
      throw new Error('unsupported_gate_runtime_action');
  }
}

async function callGateRuntime<T>(payload: WorkerRequestPayload): Promise<T> {
  if (browserGateRuntimeMode === 'inline') {
    return callInlineRuntime<T>(payload);
  }
  return callWorker<T>(payload);
}

async function ensureInlineBrowserGateCrypto(): Promise<boolean> {
  try {
    const support = await callInlineRuntime<InlineGateCryptoSupport>({ action: 'supported' });
    if (support.supported) {
      browserGateRuntimeMode = 'inline';
      browserGateCryptoSupportReason = normalizeBrowserGateRuntimeReason(
        browserGateCryptoSupportReason || 'browser_gate_worker_unavailable',
      );
      markBrowserGateLocalRuntimeActive('inline');
      return true;
    }
    browserGateCryptoSupportReason = normalizeBrowserGateRuntimeReason(
      support.reason || 'browser_gate_worker_unavailable',
    );
  } catch (error) {
    browserGateCryptoSupportReason = normalizeBrowserGateRuntimeReason(
      error instanceof Error ? error.message : 'browser_gate_worker_unavailable',
    );
    markBrowserGateLocalRuntimeUnavailable(browserGateCryptoSupportReason);
    return false;
  }
  markBrowserGateLocalRuntimeUnavailable(browserGateCryptoSupportReason);
  return false;
}

async function ensureBrowserGateCrypto(): Promise<boolean> {
  if (typeof window === 'undefined') {
    browserGateCryptoSupportReason = 'browser_runtime_unavailable';
    markBrowserGateLocalRuntimeUnavailable(browserGateCryptoSupportReason);
    return false;
  }
  if (!browserGateCryptoSupport) {
    browserGateCryptoSupport = (async () => {
      if (typeof Worker !== 'undefined') {
        try {
          await callWorker<boolean>({ action: 'supported' });
          browserGateRuntimeMode = 'worker';
          browserGateCryptoSupportReason = '';
          markBrowserGateLocalRuntimeActive('worker');
          return true;
        } catch (error) {
          browserGateCryptoSupportReason = normalizeBrowserGateRuntimeReason(
            error instanceof Error ? error.message : 'browser_gate_worker_unavailable',
          );
        }
      } else {
        browserGateCryptoSupportReason = 'browser_gate_worker_unavailable';
      }
      return ensureInlineBrowserGateCrypto();
    })();
  }
  return browserGateCryptoSupport;
}

async function exportGateStateSnapshot(gateId: string): Promise<WorkerGateStateSnapshot> {
  return controlPlaneJson<WorkerGateStateSnapshot>('/api/wormhole/gate/state/export', {
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
}

async function adoptGateStateSnapshot(gateId: string): Promise<void> {
  const snapshot = await exportGateStateSnapshot(gateId);
  await callGateRuntime<WorkerGateStateSnapshot>({
    action: 'adopt',
    snapshot,
  });
}

export async function syncBrowserGateState(
  gateId: string,
  options: { force?: boolean } = {},
): Promise<boolean> {
  const normalizedGate = normalizeGateId(gateId);
  if (!normalizedGate) return false;
  if (!(await ensureBrowserGateCrypto())) {
    rememberBrowserGateCryptoFailureForAllActions(
      normalizedGate,
      browserGateCryptoSupportReason || 'browser_gate_worker_unavailable',
    );
    return false;
  }
  if (!options.force && isBrowserGateStateFresh(normalizedGate)) {
    return true;
  }
  try {
    await adoptGateStateSnapshot(normalizedGate);
    markBrowserGateStateFresh(normalizedGate);
    clearBrowserGateCryptoFailureForAllActions(normalizedGate);
    markBrowserGateLocalRuntimeActive(browserGateRuntimeMode);
    return true;
  } catch (error) {
    const detail = normalizeBrowserGateRuntimeReason(
      (error instanceof Error ? error.message : String(error || '')).trim() ||
        `browser_gate_state_resync_required:${normalizedGate}`,
    );
    rememberBrowserGateCryptoFailureForAllActions(normalizedGate, detail);
    markBrowserGateLocalRuntimeDegraded(detail);
    return false;
  }
}

async function signEncryptedGateMessage(
  gateId: string,
  epoch: number,
  ciphertext: string,
  nonce: string,
  recoveryPlaintext: string,
  replyTo: string = '',
): Promise<SignedGateEnvelope> {
  return controlPlaneJson<SignedGateEnvelope>('/api/wormhole/gate/message/sign-encrypted', {
    requireAdminSession: false,
    capabilityIntent: 'wormhole_gate_content',
    sessionProfileHint: 'gate_operator',
    enforceProfileHint: true,
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      gate_id: gateId,
      epoch,
      ciphertext,
      nonce,
      format: 'mls1',
      reply_to: replyTo,
      compat_reply_to: Boolean(replyTo),
      recovery_plaintext: recoveryPlaintext,
    }),
  });
}

type GatePostResult = { ok: boolean; detail?: string; event_id?: string };

function isGateEnvelopeRecoveryFailure(detail: string): boolean {
  return detail === 'gate_envelope_required' || detail === 'gate_envelope_encrypt_failed';
}

async function postBackendSealedGateMessage(
  gateId: string,
  plaintext: string,
  replyTo: string = '',
): Promise<GatePostResult> {
  return controlPlaneJson<GatePostResult>('/api/wormhole/gate/message/post', {
    requireAdminSession: false,
    capabilityIntent: 'wormhole_gate_content',
    sessionProfileHint: 'gate_operator',
    enforceProfileHint: true,
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      gate_id: normalizeGateId(gateId),
      plaintext,
      reply_to: replyTo,
      compat_plaintext: true,
    }),
  });
}

async function postEncryptedGateMessage(envelope: SignedGateEnvelope): Promise<GatePostResult> {
  return controlPlaneJson<{ ok: boolean; detail?: string }>('/api/wormhole/gate/message/post-encrypted', {
    requireAdminSession: false,
    capabilityIntent: 'wormhole_gate_content',
    sessionProfileHint: 'gate_operator',
    enforceProfileHint: true,
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      gate_id: envelope.gate_id,
      sender_id: envelope.sender_id,
      public_key: envelope.public_key,
      public_key_algo: envelope.public_key_algo,
      signature: envelope.signature,
      sequence: envelope.sequence,
      protocol_version: envelope.protocol_version,
      epoch: envelope.epoch,
      ciphertext: envelope.ciphertext,
      nonce: envelope.nonce,
      sender_ref: envelope.sender_ref,
      format: envelope.format || 'mls1',
      gate_envelope: envelope.gate_envelope || '',
      envelope_hash: envelope.envelope_hash || '',
      reply_to: '',
      compat_reply_to: false,
    }),
  });
}

function isResyncRequired(detail: string, gateId?: string): boolean {
  const normalizedGate = normalizeGateId(gateId || '');
  return detail === `browser_gate_state_resync_required:${normalizedGate}` || detail.startsWith('browser_gate_state_resync_required:');
}

export async function composeBrowserGateMessage(
  gateId: string,
  plaintext: string,
  replyTo: string = '',
): Promise<SignedGateEnvelope | null> {
  if (!(await ensureBrowserGateCrypto())) {
    rememberBrowserGateCryptoFailure(
      gateId,
      'compose',
      browserGateCryptoSupportReason || 'browser_gate_worker_unavailable',
    );
    return null;
  }
  const normalizedGate = normalizeGateId(gateId);
  for (let attempt = 0; attempt < 2; attempt += 1) {
    let local: BrowserGateComposeResult;
    try {
      local = await callGateRuntime<BrowserGateComposeResult | LocalGateComposeResult>({
        action: 'compose',
        gateId: normalizedGate,
        plaintext,
        replyTo,
      }) as BrowserGateComposeResult;
    } catch (error) {
      const detail = normalizeBrowserGateRuntimeReason(error instanceof Error ? error.message : String(error || ''));
      if (isResyncRequired(detail, normalizedGate) && attempt === 0) {
        if (await syncBrowserGateState(normalizedGate, { force: true })) {
          continue;
        }
        return null;
      }
      rememberBrowserGateCryptoFailure(normalizedGate, 'compose', detail || 'browser_local_gate_crypto_unavailable');
      markBrowserGateLocalRuntimeDegraded(detail);
      return null;
    }
    const signed = await signEncryptedGateMessage(
      normalizedGate,
      Number(local.epoch || 0),
      String(local.ciphertext || ''),
      String(local.nonce || ''),
      plaintext,
      replyTo,
    );
    if (!signed.ok && String(signed.detail || '') === 'gate_state_stale' && attempt === 0) {
      if (await syncBrowserGateState(normalizedGate, { force: true })) {
        continue;
      }
      return null;
    }
    if (signed.ok) {
      rememberBrowserGateSelfEcho(
        normalizedGate,
        String(signed.ciphertext || local.ciphertext || ''),
        plaintext,
        replyTo,
        Number(signed.epoch || local.epoch || 0),
      );
    }
    markBrowserGateStateFresh(normalizedGate);
    clearBrowserGateCryptoFailure(normalizedGate, 'compose');
    markBrowserGateLocalRuntimeActive(browserGateRuntimeMode);
    return signed;
  }
  rememberBrowserGateCryptoFailure(normalizedGate, 'compose', 'browser_local_gate_crypto_unavailable');
  markBrowserGateLocalRuntimeDegraded('browser_local_gate_crypto_unavailable');
  return null;
}

export async function postBrowserGateMessage(
  gateId: string,
  plaintext: string,
  replyTo: string = '',
): Promise<GatePostResult | null> {
  const signed = await composeBrowserGateMessage(gateId, plaintext, replyTo);
  if (!signed) {
    rememberBrowserGateCryptoFailure(
      gateId,
      'post',
      getBrowserGateCryptoFailureReason(gateId, 'compose') || 'browser_local_gate_crypto_unavailable',
    );
    return null;
  }
  if (!signed.ok) {
    if (isGateEnvelopeRecoveryFailure(String(signed.detail || ''))) {
      const fallback = await postBackendSealedGateMessage(gateId, plaintext, replyTo);
      if (fallback?.ok) {
        clearBrowserGateCryptoFailure(gateId, 'post');
        markBrowserGateLocalRuntimeActive(browserGateRuntimeMode);
      }
      return fallback;
    }
    return { ok: false, detail: signed.detail || 'gate_sign_failed' };
  }
  if (!String(signed.gate_envelope || '').trim() || !String(signed.envelope_hash || '').trim()) {
    const fallback = await postBackendSealedGateMessage(gateId, plaintext, replyTo);
    if (fallback?.ok) {
      clearBrowserGateCryptoFailure(gateId, 'post');
      markBrowserGateLocalRuntimeActive(browserGateRuntimeMode);
      return fallback;
    }
    rememberBrowserGateCryptoFailure(gateId, 'post', fallback?.detail || 'gate_envelope_required');
    markBrowserGateLocalRuntimeDegraded(fallback?.detail || 'gate_envelope_required');
    return fallback || { ok: false, detail: 'gate_envelope_required' };
  }
  const result = await postEncryptedGateMessage(signed);
  if (result?.ok) {
    clearBrowserGateCryptoFailure(gateId, 'post');
    markBrowserGateLocalRuntimeActive(browserGateRuntimeMode);
  } else if (result?.detail && String(result.detail || '') !== 'gate_sign_failed') {
    markBrowserGateLocalRuntimeDegraded(String(result.detail || 'browser_local_gate_crypto_unavailable'));
  }
  return result;
}

export async function decryptBrowserGateMessages(
  messages: Array<{ gate_id: string; epoch?: number; ciphertext: string }>,
): Promise<{ ok: boolean; detail?: string; results: BrowserGateDecryptResult[] } | null> {
  const gateIds = Array.from(new Set(messages.map((message) => normalizeGateId(message.gate_id)).filter(Boolean)));
  if (!(await ensureBrowserGateCrypto())) {
    gateIds.forEach((gateId) =>
      rememberBrowserGateCryptoFailure(
        gateId,
        'decrypt',
        browserGateCryptoSupportReason || 'browser_gate_worker_unavailable',
      ),
    );
    return null;
  }
  let batchError = '';
  let batch = await callGateRuntime<BrowserGateDecryptResult[] | LocalGateDecryptResult[]>({
      action: 'decryptBatch',
      messages,
    }).catch((error) => {
      batchError = normalizeBrowserGateRuntimeReason(
        error instanceof Error ? error.message : 'browser_local_gate_crypto_unavailable',
      );
      return null;
    });
  if (!batch) {
    gateIds.forEach((gateId) =>
      rememberBrowserGateCryptoFailure(gateId, 'decrypt', batchError || 'browser_local_gate_crypto_unavailable'),
    );
    markBrowserGateLocalRuntimeDegraded(batchError || 'browser_local_gate_crypto_unavailable');
    return null;
  }
  const resyncGateIds = Array.from(
    new Set(
      batch
        .filter((result) => !result?.ok && isResyncRequired(String(result?.detail || ''), String(result?.gate_id || '')))
        .map((result) => normalizeGateId(String(result.gate_id || '')))
        .filter(Boolean),
    ),
  );
  if (resyncGateIds.length > 0) {
    const synced = await Promise.all(
      resyncGateIds.map((gateId) => syncBrowserGateState(gateId, { force: true })),
    );
    if (synced.some((value) => !value)) {
      return null;
    }
    batch = await callGateRuntime<BrowserGateDecryptResult[] | LocalGateDecryptResult[]>({
      action: 'decryptBatch',
      messages,
    }).catch((error) => {
      batchError = normalizeBrowserGateRuntimeReason(
        error instanceof Error ? error.message : 'browser_local_gate_crypto_unavailable',
      );
      return null;
    });
    if (!batch) {
      gateIds.forEach((gateId) =>
        rememberBrowserGateCryptoFailure(gateId, 'decrypt', batchError || 'browser_local_gate_crypto_unavailable'),
      );
      markBrowserGateLocalRuntimeDegraded(batchError || 'browser_local_gate_crypto_unavailable');
      return null;
    }
  }
  const normalizedBatch = (batch as BrowserGateDecryptResult[]).map((result, index) => {
    if (result?.ok || String(result?.detail || '').trim() !== 'gate_mls_decrypt_failed') {
      return result;
    }
    const source = messages[index];
    const cached = peekBrowserGateSelfEcho(
      String(source?.gate_id || result?.gate_id || ''),
      String(source?.ciphertext || ''),
    );
    if (!cached) {
      return result;
    }
    return {
      ok: true,
      gate_id: normalizeGateId(String(source?.gate_id || result?.gate_id || '')),
      epoch: Number(cached.epoch || source?.epoch || result?.epoch || 0),
      plaintext: cached.plaintext,
      reply_to: cached.replyTo,
      identity_scope: 'browser_self_echo',
    } satisfies BrowserGateDecryptResult;
  });
  const degradedDetail = normalizedBatch.find(
    (result) => !result?.ok && String(result?.detail || '').trim(),
  )?.detail;
  if (degradedDetail) {
    markBrowserGateLocalRuntimeDegraded(String(degradedDetail));
  } else {
    markBrowserGateLocalRuntimeActive(browserGateRuntimeMode);
  }
  gateIds.forEach((gateId) => {
    markBrowserGateStateFresh(gateId);
    clearBrowserGateCryptoFailure(gateId, 'decrypt');
  });
  return {
    ok: true,
    detail: degradedDetail,
    results: normalizedBatch,
  };
}

export async function forgetBrowserGateState(gateId?: string): Promise<void> {
  clearBrowserGateStateFresh(gateId);
  clearBrowserGateSelfEcho(gateId);
  if (!(await ensureBrowserGateCrypto())) return;
  await callGateRuntime<boolean>({
    action: 'forget',
    gateId,
  }).catch(() => {});
}
