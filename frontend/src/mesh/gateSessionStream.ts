import { controlPlaneFetch } from '@/lib/controlPlane';

export type GateSessionStreamPhase =
  | 'idle'
  | 'connecting'
  | 'open'
  | 'closed'
  | 'disabled'
  | 'error';

export interface GateSessionStreamStatus {
  enabled: boolean;
  phase: GateSessionStreamPhase;
  transport: 'sse';
  sessionId: string;
  subscriptions: string[];
  heartbeatS: number;
  batchMs: number;
  lastEventType: string;
  lastEventAt: number;
  detail: string;
}

export interface GateSessionStreamAccess {
  node_id: string;
  proof: string;
  ts: string;
}

export interface GateSessionStreamKeyStatus {
  ok?: boolean;
  gate_id?: string;
  current_epoch?: number;
  has_local_access?: boolean;
  identity_scope?: string;
  identity_node_id?: string;
  identity_persona_id?: string;
  detail?: string;
  format?: string;
}

type GateSessionStreamListener = (status: GateSessionStreamStatus) => void;
type GateSessionStreamEventListener = (event: {
  event: string;
  data: unknown;
  at: number;
}) => void;

const gateSessionStreamListeners = new Set<GateSessionStreamListener>();
const gateSessionStreamEventListeners = new Set<GateSessionStreamEventListener>();
const gateSessionStreamRetainCounts = new Map<string, number>();
const gateSessionStreamSubscriptions = new Set<string>();
const gateSessionStreamGateAccess = new Map<string, GateSessionStreamAccess>();
const gateSessionStreamGateKeyStatus = new Map<string, GateSessionStreamKeyStatus>();
const GATE_SESSION_STREAM_RECONNECT_DELAYS_MS = [1_000, 2_000, 4_000, 8_000] as const;

let gateSessionStreamAbort: AbortController | null = null;
let gateSessionStreamTask: Promise<void> | null = null;
let gateSessionStreamConnectSignature = '';
let gateSessionStreamReconnectTimer: ReturnType<typeof setTimeout> | null = null;
let gateSessionStreamReconnectAttempt = 0;
let gateSessionStreamStatus: GateSessionStreamStatus = {
  enabled: false,
  phase: 'idle',
  transport: 'sse',
  sessionId: '',
  subscriptions: [],
  heartbeatS: 0,
  batchMs: 0,
  lastEventType: '',
  lastEventAt: 0,
  detail: '',
};

function normalizeGateId(gateId: string): string {
  return String(gateId || '').trim().toLowerCase();
}

function gateSessionStreamSnapshot(): GateSessionStreamStatus {
  return {
    ...gateSessionStreamStatus,
    subscriptions: Array.from(gateSessionStreamSubscriptions),
  };
}

function gateSessionStreamSubscriptionSignature(): string {
  return Array.from(gateSessionStreamSubscriptions).sort().join(',');
}

function clearGateSessionStreamReconnect(): void {
  if (gateSessionStreamReconnectTimer) {
    clearTimeout(gateSessionStreamReconnectTimer);
    gateSessionStreamReconnectTimer = null;
  }
}

function emitGateSessionStreamStatus(): void {
  const snapshot = gateSessionStreamSnapshot();
  for (const listener of gateSessionStreamListeners) {
    listener(snapshot);
  }
}

function emitGateSessionStreamEvent(event: string, data: unknown, at: number): void {
  for (const listener of gateSessionStreamEventListeners) {
    listener({ event, data, at });
  }
}

function updateGateSessionStreamStatus(
  patch: Partial<Omit<GateSessionStreamStatus, 'subscriptions'>>,
): void {
  gateSessionStreamStatus = {
    ...gateSessionStreamStatus,
    ...patch,
  };
  emitGateSessionStreamStatus();
}

function syncGateSessionStreamSubscriptionsFromRetains(): void {
  gateSessionStreamSubscriptions.clear();
  for (const [gateId, count] of gateSessionStreamRetainCounts.entries()) {
    if (count > 0) {
      gateSessionStreamSubscriptions.add(gateId);
    }
  }
}

function clearGateSessionStreamGateContext(): void {
  gateSessionStreamGateAccess.clear();
  gateSessionStreamGateKeyStatus.clear();
}

function parseGateSessionStreamEvent(block: string): {
  event: string;
  data: unknown;
} | null {
  const lines = block
    .split('\n')
    .map((line) => line.trimEnd())
    .filter((line) => line.length > 0 && !line.startsWith(':'));
  if (!lines.length) return null;
  let event = 'message';
  const dataLines: string[] = [];
  for (const line of lines) {
    if (line.startsWith('event:')) {
      event = line.slice(6).trim() || 'message';
      continue;
    }
    if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trimStart());
    }
  }
  if (!dataLines.length) {
    return { event, data: null };
  }
  const rawData = dataLines.join('\n');
  try {
    return { event, data: JSON.parse(rawData) };
  } catch {
    return { event, data: rawData };
  }
}

function handleGateSessionStreamEvent(event: string, payload: unknown): void {
  const ts = Date.now();
  emitGateSessionStreamEvent(event, payload, ts);
  if (event === 'hello' && payload && typeof payload === 'object') {
    const hello = payload as {
      session_id?: string;
      subscriptions?: unknown;
      gate_access?: unknown;
      gate_key_status?: unknown;
      heartbeat_s?: number;
      batch_ms?: number;
      transport?: string;
    };
    gateSessionStreamSubscriptions.clear();
    if (Array.isArray(hello.subscriptions)) {
      for (const gateId of hello.subscriptions) {
        const normalized = normalizeGateId(String(gateId || ''));
        if (normalized) {
          gateSessionStreamSubscriptions.add(normalized);
        }
      }
    }
    clearGateSessionStreamGateContext();
    if (hello.gate_access && typeof hello.gate_access === 'object') {
      for (const [gateId, access] of Object.entries(hello.gate_access as Record<string, unknown>)) {
        const normalizedGate = normalizeGateId(gateId);
        if (!normalizedGate || !access || typeof access !== 'object') continue;
        const accessRecord = access as Record<string, unknown>;
        const nodeId = String(accessRecord.node_id || '').trim();
        const proof = String(accessRecord.proof || '').trim();
        const ts = String(accessRecord.ts || '').trim();
        if (!nodeId || !proof || !ts) continue;
        gateSessionStreamGateAccess.set(normalizedGate, { node_id: nodeId, proof, ts });
      }
    }
    if (hello.gate_key_status && typeof hello.gate_key_status === 'object') {
      for (const [gateId, status] of Object.entries(hello.gate_key_status as Record<string, unknown>)) {
        const normalizedGate = normalizeGateId(gateId);
        if (!normalizedGate || !status || typeof status !== 'object') continue;
        gateSessionStreamGateKeyStatus.set(normalizedGate, {
          ...(status as GateSessionStreamKeyStatus),
          gate_id: normalizedGate,
        });
      }
    }
    clearGateSessionStreamReconnect();
    gateSessionStreamReconnectAttempt = 0;
    updateGateSessionStreamStatus({
      enabled: true,
      phase: 'open',
      transport: hello.transport === 'sse' ? 'sse' : 'sse',
      sessionId: String(hello.session_id || ''),
      heartbeatS: Math.max(0, Number(hello.heartbeat_s || 0)),
      batchMs: Math.max(0, Number(hello.batch_ms || 0)),
      lastEventType: 'hello',
      lastEventAt: ts,
      detail: '',
    });
    return;
  }
  updateGateSessionStreamStatus({
    lastEventType: event,
    lastEventAt: ts,
  });
}

function scheduleGateSessionStreamReconnect(): void {
  syncGateSessionStreamSubscriptionsFromRetains();
  if (!gateSessionStreamSubscriptionSignature()) {
    return;
  }
  if (gateSessionStreamStatus.phase === 'disabled' || gateSessionStreamReconnectTimer) {
    return;
  }
  const delayMs =
    GATE_SESSION_STREAM_RECONNECT_DELAYS_MS[
      Math.min(gateSessionStreamReconnectAttempt, GATE_SESSION_STREAM_RECONNECT_DELAYS_MS.length - 1)
    ];
  gateSessionStreamReconnectAttempt += 1;
  gateSessionStreamReconnectTimer = setTimeout(() => {
    gateSessionStreamReconnectTimer = null;
    void reconcileGateSessionStreamConnection();
  }, delayMs);
}

async function consumeGateSessionStreamBody(
  response: Response,
  signal: AbortSignal,
): Promise<void> {
  const body = response.body;
  if (!body) {
    updateGateSessionStreamStatus({
      enabled: false,
      phase: 'error',
      detail: 'gate_session_stream_body_missing',
    });
    return;
  }
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const normalizedBuffer = buffer.replace(/\r\n/g, '\n');
    let delimiter = normalizedBuffer.indexOf('\n\n');
    if (delimiter >= 0) {
      let remaining = normalizedBuffer;
      while (delimiter >= 0) {
        const block = remaining.slice(0, delimiter);
        const parsed = parseGateSessionStreamEvent(block);
        if (parsed) {
          handleGateSessionStreamEvent(parsed.event, parsed.data);
        }
        remaining = remaining.slice(delimiter + 2);
        delimiter = remaining.indexOf('\n\n');
      }
      buffer = remaining;
    } else {
      buffer = normalizedBuffer;
    }
    if (done) {
      const trailing = buffer.trim();
      if (trailing) {
        const parsed = parseGateSessionStreamEvent(trailing);
        if (parsed) {
          handleGateSessionStreamEvent(parsed.event, parsed.data);
        }
      }
      break;
    }
    if (signal.aborted) {
      return;
    }
  }
  if (!signal.aborted) {
    updateGateSessionStreamStatus({
      enabled: false,
      phase: 'closed',
      detail: 'gate_session_stream_closed',
    });
    scheduleGateSessionStreamReconnect();
  }
}

export function getGateSessionStreamStatus(): GateSessionStreamStatus {
  return gateSessionStreamSnapshot();
}

export function subscribeGateSessionStreamStatus(
  listener: GateSessionStreamListener,
): () => void {
  gateSessionStreamListeners.add(listener);
  listener(gateSessionStreamSnapshot());
  return () => {
    gateSessionStreamListeners.delete(listener);
  };
}

export function subscribeGateSessionStreamEvents(
  listener: GateSessionStreamEventListener,
): () => void {
  gateSessionStreamEventListeners.add(listener);
  return () => {
    gateSessionStreamEventListeners.delete(listener);
  };
}

export function getGateSessionStreamAccessHeaders(gateId: string): Record<string, string> | undefined {
  const access = gateSessionStreamGateAccess.get(normalizeGateId(gateId));
  if (!access) return undefined;
  return {
    'X-Wormhole-Node-Id': access.node_id,
    'X-Wormhole-Gate-Proof': access.proof,
    'X-Wormhole-Gate-Ts': access.ts,
  };
}

export function getGateSessionStreamKeyStatus(gateId: string): GateSessionStreamKeyStatus | null {
  return gateSessionStreamGateKeyStatus.get(normalizeGateId(gateId)) || null;
}

export function setGateSessionStreamGateContext(
  gateId: string,
  options: {
    accessHeaders?: Record<string, string> | null;
    keyStatus?: GateSessionStreamKeyStatus | null;
  },
): void {
  const normalized = normalizeGateId(gateId);
  if (!normalized) return;
  const accessHeaders = options.accessHeaders;
  if (accessHeaders) {
    const nodeId = String(accessHeaders['X-Wormhole-Node-Id'] || '').trim();
    const proof = String(accessHeaders['X-Wormhole-Gate-Proof'] || '').trim();
    const ts = String(accessHeaders['X-Wormhole-Gate-Ts'] || '').trim();
    if (nodeId && proof && ts) {
      gateSessionStreamGateAccess.set(normalized, { node_id: nodeId, proof, ts });
    }
  }
  const keyStatus = options.keyStatus;
  if (keyStatus && typeof keyStatus === 'object') {
    gateSessionStreamGateKeyStatus.set(normalized, {
      ...keyStatus,
      gate_id: normalized,
    });
  }
}

export function invalidateGateSessionStreamGateContext(gateId?: string): void {
  const normalized = normalizeGateId(gateId || '');
  if (!normalized) {
    clearGateSessionStreamGateContext();
    return;
  }
  gateSessionStreamGateAccess.delete(normalized);
  gateSessionStreamGateKeyStatus.delete(normalized);
}

export function setGateSessionStreamSubscriptions(gates: Iterable<string>): void {
  gateSessionStreamRetainCounts.clear();
  gateSessionStreamSubscriptions.clear();
  clearGateSessionStreamGateContext();
  for (const gateId of gates) {
    const normalized = normalizeGateId(String(gateId || ''));
    if (normalized) {
      gateSessionStreamSubscriptions.add(normalized);
      gateSessionStreamRetainCounts.set(normalized, 1);
    }
  }
  emitGateSessionStreamStatus();
}

export function disconnectGateSessionStream(detail: string = 'gate_session_stream_stopped'): void {
  const controller = gateSessionStreamAbort;
  gateSessionStreamAbort = null;
  gateSessionStreamTask = null;
  clearGateSessionStreamReconnect();
  gateSessionStreamReconnectAttempt = 0;
  if (controller) {
    controller.abort();
  }
  gateSessionStreamConnectSignature = '';
  clearGateSessionStreamGateContext();
  updateGateSessionStreamStatus({
    enabled: false,
    phase: 'closed',
    detail,
  });
}

export function connectGateSessionStream(options: { enabled?: boolean } = {}): GateSessionStreamStatus {
  if (options.enabled === false) {
    disconnectGateSessionStream('gate_session_stream_disabled');
    updateGateSessionStreamStatus({
      phase: 'disabled',
      detail: 'gate_session_stream_disabled',
    });
    return gateSessionStreamSnapshot();
  }
  if (gateSessionStreamTask) {
    return gateSessionStreamSnapshot();
  }
  clearGateSessionStreamReconnect();
  gateSessionStreamConnectSignature = gateSessionStreamSubscriptionSignature();
  const controller = new AbortController();
  gateSessionStreamAbort = controller;
  updateGateSessionStreamStatus({
    enabled: true,
    phase: 'connecting',
    sessionId: '',
    heartbeatS: 0,
    batchMs: 0,
    lastEventType: '',
    lastEventAt: 0,
    detail: '',
  });
  const params = new URLSearchParams();
  const gates = Array.from(gateSessionStreamSubscriptions);
  if (gates.length) {
    params.set('gates', gates.join(','));
  }
  const path = `/api/mesh/infonet/session-stream${params.size ? `?${params.toString()}` : ''}`;
  gateSessionStreamTask = (async () => {
    try {
      const response = await controlPlaneFetch(path, {
        requireAdminSession: true,
        cache: 'no-store',
        headers: { Accept: 'text/event-stream' },
        signal: controller.signal,
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        const detail = String(data?.detail || 'gate_session_stream_unavailable');
        updateGateSessionStreamStatus({
          enabled: false,
          phase: detail === 'gate_session_stream_disabled' ? 'disabled' : 'error',
          detail,
        });
        if (detail !== 'gate_session_stream_disabled') {
          scheduleGateSessionStreamReconnect();
        }
        return;
      }
      await consumeGateSessionStreamBody(response, controller.signal);
    } catch (error) {
      if (controller.signal.aborted) {
        return;
      }
      updateGateSessionStreamStatus({
        enabled: false,
        phase: 'error',
        detail:
          error instanceof Error && error.message
            ? error.message
            : 'gate_session_stream_failed',
      });
      scheduleGateSessionStreamReconnect();
    } finally {
      if (gateSessionStreamAbort === controller) {
        gateSessionStreamAbort = null;
      }
      gateSessionStreamTask = null;
    }
  })();
  return gateSessionStreamSnapshot();
}

function reconcileGateSessionStreamConnection(): GateSessionStreamStatus {
  syncGateSessionStreamSubscriptionsFromRetains();
  const signature = gateSessionStreamSubscriptionSignature();
  emitGateSessionStreamStatus();
  if (!signature) {
    clearGateSessionStreamReconnect();
    gateSessionStreamReconnectAttempt = 0;
    if (gateSessionStreamTask || gateSessionStreamAbort) {
      disconnectGateSessionStream('gate_session_stream_idle');
    }
    updateGateSessionStreamStatus({
      enabled: false,
      phase: 'idle',
      sessionId: '',
      heartbeatS: 0,
      batchMs: 0,
      lastEventType: '',
      lastEventAt: 0,
      detail: '',
    });
    return gateSessionStreamSnapshot();
  }
  if (gateSessionStreamStatus.phase === 'disabled') {
    clearGateSessionStreamReconnect();
    return gateSessionStreamSnapshot();
  }
  if (gateSessionStreamTask && gateSessionStreamConnectSignature === signature) {
    return gateSessionStreamSnapshot();
  }
  if (gateSessionStreamTask || gateSessionStreamAbort) {
    disconnectGateSessionStream('gate_session_stream_restarting');
  }
  return connectGateSessionStream();
}

export function retainGateSessionStreamGate(gateId: string): () => void {
  const normalized = normalizeGateId(gateId);
  if (!normalized) {
    return () => {};
  }
  gateSessionStreamRetainCounts.set(
    normalized,
    Math.max(0, Number(gateSessionStreamRetainCounts.get(normalized) || 0)) + 1,
  );
  reconcileGateSessionStreamConnection();
  return () => {
    releaseGateSessionStreamGate(normalized);
  };
}

export function releaseGateSessionStreamGate(gateId: string): GateSessionStreamStatus {
  const normalized = normalizeGateId(gateId);
  if (!normalized) {
    return gateSessionStreamSnapshot();
  }
  const current = Math.max(0, Number(gateSessionStreamRetainCounts.get(normalized) || 0));
  if (current <= 1) {
    gateSessionStreamRetainCounts.delete(normalized);
  } else {
    gateSessionStreamRetainCounts.set(normalized, current - 1);
  }
  return reconcileGateSessionStreamConnection();
}
