import { API_BASE } from '@/lib/api';
import { hasLocalControlBridge } from '@/lib/localControlTransport';
import { buildGateAccessHeaders } from '@/mesh/gateAccessProof';
import type { GateAccessHeaderMode } from '@/mesh/gateAccessProof';

export interface GateMessageSnapshotRecord {
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
  reply_to?: string;
  gate_envelope?: string;
  envelope_hash?: string;
  payload?: {
    gate?: string;
    ciphertext?: string;
    nonce?: string;
    sender_ref?: string;
    format?: string;
    reply_to?: string;
    gate_envelope?: string;
    envelope_hash?: string;
  };
  timestamp: number;
  ephemeral?: boolean;
  system_seed?: boolean;
  fixed_gate?: boolean;
}

export interface GateMessageSnapshotState {
  messages: GateMessageSnapshotRecord[];
  cursor: number;
  changed?: boolean;
}

export const ACTIVE_GATE_ROOM_MESSAGE_LIMIT = 40;

const GATE_MESSAGES_BROWSER_TTL_MS = 10_000;
const GATE_MESSAGES_NATIVE_TTL_MS = 3_000;

const gateMessageCache = new Map<
  string,
  { limit: number; value: GateMessageSnapshotRecord[]; expiresAt: number; cursor: number }
>();
const gateMessageFetchInflight = new Map<
  string,
  { gateId: string; limit: number; promise: Promise<GateMessageSnapshotState> }
>();
const gateMessageWaitInflight = new Map<
  string,
  {
    gateId: string;
    afterCursor: number;
    limit: number;
    promise: Promise<GateMessageSnapshotState>;
  }
>();

function normalizeGateId(gateId: string): string {
  return String(gateId || '').trim().toLowerCase();
}

function gateMessagesTtlMs(): number {
  return hasLocalControlBridge()
    ? GATE_MESSAGES_NATIVE_TTL_MS
    : GATE_MESSAGES_BROWSER_TTL_MS;
}

export function normalizeGateMessageSnapshotRecord(
  message: GateMessageSnapshotRecord,
): GateMessageSnapshotRecord {
  const payload =
    message.payload && typeof message.payload === 'object'
      ? message.payload
      : undefined;
  return {
    ...message,
    gate: String(message.gate ?? payload?.gate ?? ''),
    ciphertext: String(message.ciphertext ?? payload?.ciphertext ?? ''),
    nonce: String(message.nonce ?? payload?.nonce ?? ''),
    sender_ref: String(message.sender_ref ?? payload?.sender_ref ?? ''),
    format: String(message.format ?? payload?.format ?? ''),
    reply_to: String(message.reply_to ?? payload?.reply_to ?? ''),
    gate_envelope: String(message.gate_envelope ?? payload?.gate_envelope ?? ''),
    envelope_hash: String(message.envelope_hash ?? payload?.envelope_hash ?? ''),
  };
}

export function invalidateGateMessageSnapshot(gateId?: string): void {
  const normalized = normalizeGateId(gateId || '');
  if (!normalized) {
    gateMessageCache.clear();
    gateMessageFetchInflight.clear();
    gateMessageWaitInflight.clear();
    return;
  }
  gateMessageCache.delete(normalized);
  for (const [key, entry] of gateMessageFetchInflight.entries()) {
    if (entry.gateId === normalized) {
      gateMessageFetchInflight.delete(key);
    }
  }
  for (const [key, entry] of gateMessageWaitInflight.entries()) {
    if (entry.gateId === normalized) {
      gateMessageWaitInflight.delete(key);
    }
  }
}

function gateMessageFetchKey(gateId: string, limit: number): string {
  return `${gateId}::fetch::${Math.max(1, Number(limit || 20))}`;
}

function gateMessageWaitKey(gateId: string, afterCursor: number, limit: number): string {
  return `${gateId}::wait::${Math.max(0, Number(afterCursor || 0))}::${Math.max(1, Number(limit || 20))}`;
}

function sliceGateMessageSnapshotState(
  snapshot: GateMessageSnapshotState,
  limit: number,
): GateMessageSnapshotState {
  return {
    ...snapshot,
    messages: snapshot.messages.slice(0, Math.max(1, Number(limit || 20))),
  };
}

function findReusableGateMessageFetchInflight(
  gateId: string,
  limit: number,
): Promise<GateMessageSnapshotState> | null {
  for (const entry of gateMessageFetchInflight.values()) {
    if (entry.gateId === gateId && entry.limit >= limit) {
      return entry.promise.then((snapshot) => sliceGateMessageSnapshotState(snapshot, limit));
    }
  }
  return null;
}

function findReusableGateMessageWaitInflight(
  gateId: string,
  afterCursor: number,
  limit: number,
): Promise<GateMessageSnapshotState> | null {
  for (const entry of gateMessageWaitInflight.values()) {
    if (entry.gateId === gateId && entry.afterCursor === afterCursor && entry.limit >= limit) {
      return entry.promise.then((snapshot) => sliceGateMessageSnapshotState(snapshot, limit));
    }
  }
  return null;
}

function upsertGateMessageSnapshot(
  gateId: string,
  limit: number,
  messages: GateMessageSnapshotRecord[],
  cursor: number,
): GateMessageSnapshotState {
  gateMessageCache.set(gateId, {
    limit,
    value: messages,
    expiresAt: Date.now() + gateMessagesTtlMs(),
    cursor,
  });
  return {
    messages: messages.slice(0, limit),
    cursor,
  };
}

export function getGateMessageSnapshotCursor(gateId: string): number {
  const cached = gateMessageCache.get(normalizeGateId(gateId));
  return cached ? Math.max(0, Number(cached.cursor || 0)) : 0;
}

export async function fetchGateMessageSnapshotState(
  gateId: string,
  limit: number = 20,
  options: { force?: boolean; signal?: AbortSignal; proofMode?: GateAccessHeaderMode } = {},
): Promise<GateMessageSnapshotState> {
  const normalizedGate = normalizeGateId(gateId);
  if (!normalizedGate) {
    return { messages: [], cursor: 0 };
  }
  const normalizedLimit = Math.max(1, Number(limit || 20));
  const cached = gateMessageCache.get(normalizedGate);
  if (
    !options.force &&
    cached &&
    cached.expiresAt > Date.now() &&
    cached.limit >= normalizedLimit
  ) {
    return {
      messages: cached.value.slice(0, normalizedLimit),
      cursor: Math.max(0, Number(cached.cursor || 0)),
    };
  }
  const inflightKey = gateMessageFetchKey(normalizedGate, normalizedLimit);
  if (!options.force) {
    const inflight = gateMessageFetchInflight.get(inflightKey)?.promise;
    if (inflight) {
      return inflight;
    }
    const reusableInflight = findReusableGateMessageFetchInflight(normalizedGate, normalizedLimit);
    if (reusableInflight) {
      return reusableInflight;
    }
  }
  const pending = (async () => {
    const headers = await buildGateAccessHeaders(normalizedGate, {
      mode: options.proofMode === 'session_stream' ? 'session_stream' : 'default',
    });
    if (!headers) {
      throw new Error('Gate proof unavailable');
    }
    const response = await fetch(
      `${API_BASE}/api/mesh/infonet/messages?gate=${encodeURIComponent(normalizedGate)}&limit=${normalizedLimit}`,
      { headers, signal: options.signal },
    );
    const data = await response.json().catch(() => ({}));
    const messages = (Array.isArray(data?.messages) ? data.messages : []).map((message: unknown) =>
      normalizeGateMessageSnapshotRecord(message as GateMessageSnapshotRecord),
    );
    const cursor = Math.max(0, Number(data?.cursor || messages.length || 0));
    return upsertGateMessageSnapshot(normalizedGate, normalizedLimit, messages, cursor);
  })();
  if (!options.force) {
    gateMessageFetchInflight.set(inflightKey, {
      gateId: normalizedGate,
      limit: normalizedLimit,
      promise: pending,
    });
  }
  try {
    return await pending;
  } finally {
    gateMessageFetchInflight.delete(inflightKey);
  }
}

export async function fetchGateMessageSnapshot(
  gateId: string,
  limit: number = 20,
  options: { force?: boolean; signal?: AbortSignal } = {},
): Promise<GateMessageSnapshotRecord[]> {
  const snapshot = await fetchGateMessageSnapshotState(gateId, limit, options);
  return snapshot.messages;
}

export async function waitForGateMessageSnapshot(
  gateId: string,
  afterCursor: number,
  limit: number = 20,
  options: { timeoutMs?: number; signal?: AbortSignal } = {},
): Promise<GateMessageSnapshotState> {
  const normalizedGate = normalizeGateId(gateId);
  if (!normalizedGate) {
    return { messages: [], cursor: 0, changed: false };
  }
  const normalizedLimit = Math.max(1, Number(limit || 20));
  const normalizedAfterCursor = Math.max(0, Number(afterCursor || 0));
  const timeoutMs = Math.max(1_000, Number(options.timeoutMs || 25_000));
  const inflightKey = gateMessageWaitKey(normalizedGate, normalizedAfterCursor, normalizedLimit);
  const inflight = gateMessageWaitInflight.get(inflightKey)?.promise;
  if (inflight) {
    return inflight;
  }
  const reusableInflight = findReusableGateMessageWaitInflight(
    normalizedGate,
    normalizedAfterCursor,
    normalizedLimit,
  );
  if (reusableInflight) {
    return reusableInflight;
  }
  const pending = (async () => {
    const headers = await buildGateAccessHeaders(normalizedGate, { mode: 'wait' });
    if (!headers) {
      throw new Error('Gate proof unavailable');
    }
    const response = await fetch(
      `${API_BASE}/api/mesh/infonet/messages/wait?gate=${encodeURIComponent(normalizedGate)}&after=${normalizedAfterCursor}&limit=${normalizedLimit}&timeout_ms=${timeoutMs}`,
      { headers, signal: options.signal },
    );
    const data = await response.json().catch(() => ({}));
    const messages = (Array.isArray(data?.messages) ? data.messages : []).map((message: unknown) =>
      normalizeGateMessageSnapshotRecord(message as GateMessageSnapshotRecord),
    );
    const cursor = Math.max(0, Number(data?.cursor || messages.length || normalizedAfterCursor));
    const changed = Boolean(data?.changed);
    const snapshot = upsertGateMessageSnapshot(
      normalizedGate,
      normalizedLimit,
      messages,
      cursor,
    );
    return {
      ...snapshot,
      changed,
    };
  })();
  gateMessageWaitInflight.set(inflightKey, {
    gateId: normalizedGate,
    afterCursor: normalizedAfterCursor,
    limit: normalizedLimit,
    promise: pending,
  });
  try {
    return await pending;
  } finally {
    gateMessageWaitInflight.delete(inflightKey);
  }
}
