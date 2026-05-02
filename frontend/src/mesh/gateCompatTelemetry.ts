import { getNodeIdentity, getWormholeIdentityDescriptor } from '@/mesh/meshIdentity';

const KEY_SESSION_MODE = 'sb_mesh_session_mode';
const KEY_GATE_COMPAT_TELEMETRY = 'sb_gate_compat_telemetry_v1';
const GATE_COMPAT_TELEMETRY_EVENT = 'sb:gate-compat-telemetry';
const MAX_RECENT_EVENTS = 12;
const MAX_RECENT_GATES = 4;

export type GateCompatTelemetryAction = 'compose' | 'post' | 'decrypt';
export type GateCompatTelemetryKind = 'required' | 'used';

type StoredGateCompatReasonBucket = {
  required_count?: number;
  used_count?: number;
  last_at?: number;
  actions?: Partial<Record<GateCompatTelemetryAction, number>>;
  recent_gates?: string[];
};

type StoredGateCompatEvent = {
  gate_id?: string;
  action?: GateCompatTelemetryAction;
  reason?: string;
  kind?: GateCompatTelemetryKind;
  at?: number;
};

type StoredGateCompatScope = {
  total_required?: number;
  total_used?: number;
  last_at?: number;
  by_reason?: Record<string, StoredGateCompatReasonBucket>;
  recent?: StoredGateCompatEvent[];
};

type StoredGateCompatTelemetry = Record<string, StoredGateCompatScope>;

export interface GateCompatTelemetryReasonSummary {
  reason: string;
  label: string;
  requiredCount: number;
  usedCount: number;
  lastAt: number;
  actions: Partial<Record<GateCompatTelemetryAction, number>>;
  recentGates: string[];
}

export interface GateCompatTelemetryRecentEvent {
  gateId: string;
  action: GateCompatTelemetryAction;
  reason: string;
  label: string;
  kind: GateCompatTelemetryKind;
  at: number;
}

export interface GateCompatTelemetrySnapshot {
  totalRequired: number;
  totalUsed: number;
  lastAt: number;
  reasons: GateCompatTelemetryReasonSummary[];
  recent: GateCompatTelemetryRecentEvent[];
}

export interface GateCompatTelemetryTopReason {
  reason: string;
  label: string;
  requiredCount: number;
  usedCount: number;
  lastAt: number;
  recentGates: string[];
}

function compatTelemetryStorageSelection(): {
  storage: Storage | null;
  mode: 'persistent' | 'session';
} {
  if (typeof window === 'undefined') {
    return { storage: null, mode: 'session' };
  }
  try {
    const persistent = window.localStorage;
    const session = window.sessionStorage;
    return persistent.getItem(KEY_SESSION_MODE) !== 'false'
      ? { storage: session, mode: 'session' }
      : { storage: persistent, mode: 'persistent' };
  } catch {
    try {
      return { storage: window.sessionStorage, mode: 'session' };
    } catch {
      return { storage: null, mode: 'session' };
    }
  }
}

function compatTelemetryStorage(): Storage | null {
  return compatTelemetryStorageSelection().storage;
}

function compatTelemetryScope(): string {
  const wormholeDescriptor = getWormholeIdentityDescriptor();
  const nodeIdentity = getNodeIdentity();
  const scopeId = String(wormholeDescriptor?.nodeId || nodeIdentity?.nodeId || 'default')
    .trim()
    .toLowerCase();
  const { mode } = compatTelemetryStorageSelection();
  return `${mode}:${scopeId || 'default'}`;
}

function safeRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : {};
}

function safeInt(value: unknown): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.trunc(parsed) : 0;
}

function normalizeGateId(gateId: string): string {
  return String(gateId || '').trim().toLowerCase();
}

export function normalizeGateCompatReason(reason: string): string {
  return String(reason || '').trim().toLowerCase() || 'browser_local_gate_crypto_unavailable';
}

export function describeGateCompatReason(reason: string, gateId: string = ''): string {
  const normalizedGate = normalizeGateId(gateId);
  const detail = normalizeGateCompatReason(reason);
  if (detail === 'browser_runtime_unavailable') {
    return 'This runtime cannot host local gate crypto.';
  }
  if (detail === 'browser_local_gate_crypto_unavailable') {
    return 'Local gate crypto failed on this device.';
  }
  if (detail === 'browser_gate_worker_unavailable') {
    return 'This runtime cannot use the local gate worker.';
  }
  if (detail === 'browser_gate_webcrypto_unavailable') {
    return 'This runtime lacks the WebCrypto features required for local gate crypto.';
  }
  if (detail === 'browser_gate_indexeddb_unavailable') {
    return 'This runtime cannot persist local gate state.';
  }
  if (detail === 'browser_gate_storage_unavailable') {
    return 'Secure local gate storage failed in this browser.';
  }
  if (detail === 'browser_gate_wasm_unavailable') {
    return 'Local gate crypto could not load on this device.';
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
  if (detail === 'gate_sign_failed') {
    return 'Local gate signing failed on this device.';
  }
  return 'Local gate crypto failed on this device.';
}

function readStoredTelemetry(): StoredGateCompatTelemetry {
  const storage = compatTelemetryStorage();
  if (!storage) return {};
  try {
    const raw = storage.getItem(KEY_GATE_COMPAT_TELEMETRY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as unknown;
    return parsed && typeof parsed === 'object' ? (parsed as StoredGateCompatTelemetry) : {};
  } catch {
    return {};
  }
}

function writeStoredTelemetry(next: StoredGateCompatTelemetry): void {
  const storage = compatTelemetryStorage();
  if (!storage) return;
  try {
    storage.setItem(KEY_GATE_COMPAT_TELEMETRY, JSON.stringify(next));
  } catch {
    /* ignore */
  }
}

function dispatchTelemetryUpdate(snapshot: GateCompatTelemetrySnapshot): void {
  if (typeof window === 'undefined') return;
  try {
    window.dispatchEvent(
      new CustomEvent(GATE_COMPAT_TELEMETRY_EVENT, {
        detail: snapshot,
      }),
    );
  } catch {
    /* ignore */
  }
}

export function getGateCompatTelemetryEventName(): string {
  return GATE_COMPAT_TELEMETRY_EVENT;
}

export function formatGateCompatSeenAt(timestamp: number): string {
  if (!timestamp) return 'never';
  try {
    return new Date(timestamp).toISOString().replace('T', ' ').slice(0, 16) + 'Z';
  } catch {
    return 'never';
  }
}

export function getGateCompatTelemetrySnapshot(): GateCompatTelemetrySnapshot {
  const all = readStoredTelemetry();
  const scope = compatTelemetryScope();
  const current = safeRecord(all?.[scope]);
  const reasonsRecord = safeRecord(current.by_reason);
  const reasons = Object.entries(reasonsRecord)
    .map(([reason, value]) => {
      const bucket = safeRecord(value);
      const actionsRecord = safeRecord(bucket.actions);
      const actions: Partial<Record<GateCompatTelemetryAction, number>> = {};
      (['compose', 'post', 'decrypt'] as GateCompatTelemetryAction[]).forEach((action) => {
        const count = safeInt(actionsRecord[action]);
        if (count > 0) actions[action] = count;
      });
      const recentGates = Array.isArray(bucket.recent_gates)
        ? bucket.recent_gates.map((item) => normalizeGateId(String(item || ''))).filter(Boolean)
        : [];
      return {
        reason,
        label: describeGateCompatReason(reason, recentGates[0] || ''),
        requiredCount: safeInt(bucket.required_count),
        usedCount: safeInt(bucket.used_count),
        lastAt: safeInt(bucket.last_at),
        actions,
        recentGates,
      };
    })
    .sort((a, b) => {
      const aScore = a.requiredCount + a.usedCount;
      const bScore = b.requiredCount + b.usedCount;
      if (bScore !== aScore) return bScore - aScore;
      return b.lastAt - a.lastAt;
    });

  const recent = Array.isArray(current.recent)
    ? current.recent
        .map((value) => safeRecord(value))
        .map((entry) => {
          const gateId = normalizeGateId(String(entry.gate_id || ''));
          const reason = normalizeGateCompatReason(String(entry.reason || ''));
          const action = (String(entry.action || 'decrypt').trim().toLowerCase() ||
            'decrypt') as GateCompatTelemetryAction;
          const kind = (String(entry.kind || 'required').trim().toLowerCase() ||
            'required') as GateCompatTelemetryKind;
          const at = safeInt(entry.at);
          return {
            gateId,
            action,
            reason,
            label: describeGateCompatReason(reason, gateId),
            kind,
            at,
          };
        })
        .filter((entry) => entry.gateId)
    : [];

  return {
    totalRequired: safeInt(current.total_required),
    totalUsed: safeInt(current.total_used),
    lastAt: safeInt(current.last_at),
    reasons,
    recent,
  };
}

export function summarizeGateCompatTelemetry(
  snapshot: GateCompatTelemetrySnapshot | null | undefined,
  limit: number = 3,
): GateCompatTelemetryTopReason[] {
  const current = snapshot || {
    totalRequired: 0,
    totalUsed: 0,
    lastAt: 0,
    reasons: [],
    recent: [],
  };
  return current.reasons.slice(0, Math.max(1, limit)).map((item) => ({
    reason: item.reason,
    label: item.label,
    requiredCount: item.requiredCount,
    usedCount: item.usedCount,
    lastAt: item.lastAt,
    recentGates: item.recentGates,
  }));
}

export function recordGateCompatTelemetry(input: {
  gateId: string;
  action: GateCompatTelemetryAction;
  reason: string;
  kind: GateCompatTelemetryKind;
  at?: number;
}): void {
  const storage = compatTelemetryStorage();
  if (!storage) return;
  const gateId = normalizeGateId(input.gateId);
  if (!gateId) return;
  const action = (String(input.action || 'decrypt').trim().toLowerCase() ||
    'decrypt') as GateCompatTelemetryAction;
  const reason = normalizeGateCompatReason(input.reason);
  const kind = (String(input.kind || 'required').trim().toLowerCase() ||
    'required') as GateCompatTelemetryKind;
  const at = safeInt(input.at || Date.now()) || Date.now();

  const all = readStoredTelemetry();
  const scope = compatTelemetryScope();
  const current: StoredGateCompatScope = all[scope] || {};
  const byReason: Record<string, StoredGateCompatReasonBucket> = current.by_reason || {};
  const bucket: StoredGateCompatReasonBucket = byReason[reason] || {};
  const actions: Partial<Record<GateCompatTelemetryAction, number>> = bucket.actions || {};
  const recentGates = Array.isArray(bucket.recent_gates)
    ? bucket.recent_gates.map((item) => normalizeGateId(String(item || ''))).filter(Boolean)
    : [];
  const nextRecentGates = [gateId, ...recentGates.filter((value) => value !== gateId)].slice(
    0,
    MAX_RECENT_GATES,
  );
  const nextRecent = [
    {
      gate_id: gateId,
      action,
      reason,
      kind,
      at,
    },
    ...(Array.isArray(current.recent) ? current.recent : []),
  ].slice(0, MAX_RECENT_EVENTS);

  const nextScope: StoredGateCompatScope = {
    ...current,
    total_required: safeInt(current.total_required) + (kind === 'required' ? 1 : 0),
    total_used: safeInt(current.total_used) + (kind === 'used' ? 1 : 0),
    last_at: at,
    by_reason: {
      ...byReason,
      [reason]: {
        ...bucket,
        required_count: safeInt(bucket.required_count) + (kind === 'required' ? 1 : 0),
        used_count: safeInt(bucket.used_count) + (kind === 'used' ? 1 : 0),
        last_at: at,
        actions: {
          ...actions,
          [action]: safeInt(actions[action]) + 1,
        },
        recent_gates: nextRecentGates,
      },
    },
    recent: nextRecent,
  };

  writeStoredTelemetry({
    ...all,
    [scope]: nextScope,
  });
  dispatchTelemetryUpdate(getGateCompatTelemetrySnapshot());
}
