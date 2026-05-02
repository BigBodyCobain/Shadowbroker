import { controlPlaneJson } from '@/lib/controlPlane';
import { hasLocalControlBridge } from '@/lib/localControlTransport';
import { getGateSessionStreamAccessHeaders } from '@/mesh/gateSessionStream';

const GATE_ACCESS_PROOF_BROWSER_TTL_MS = 52_000;
const GATE_ACCESS_PROOF_NATIVE_TTL_MS = 35_000;
const GATE_ACCESS_PROOF_EXTENDED_BROWSER_MAX_AGE_MS = 58_000;
const GATE_ACCESS_PROOF_EXTENDED_NATIVE_MAX_AGE_MS = 58_000;

export type GateAccessHeaderMode = 'default' | 'wait' | 'session_stream';

export const gateAccessHeaderCache = new Map<
  string,
  { headers: Record<string, string>; expiresAt: number; proofTsMs: number }
>();
const gateAccessHeaderInflight = new Map<string, Promise<Record<string, string> | undefined>>();

function normalizeGateId(gateId: string): string {
  return String(gateId || '').trim().toLowerCase();
}

function gateAccessProofTtlMs(): number {
  return hasLocalControlBridge()
    ? GATE_ACCESS_PROOF_NATIVE_TTL_MS
    : GATE_ACCESS_PROOF_BROWSER_TTL_MS;
}

function gateAccessProofExtendedMaxAgeMs(): number {
  return hasLocalControlBridge()
    ? GATE_ACCESS_PROOF_EXTENDED_NATIVE_MAX_AGE_MS
    : GATE_ACCESS_PROOF_EXTENDED_BROWSER_MAX_AGE_MS;
}

function gateAccessHeaderReusableUntilMs(entry: {
  expiresAt: number;
  proofTsMs: number;
}, mode: GateAccessHeaderMode): number {
  if (mode === 'default' || !Number.isFinite(entry.proofTsMs) || entry.proofTsMs <= 0) {
    return entry.expiresAt;
  }
  return Math.max(entry.expiresAt, entry.proofTsMs + gateAccessProofExtendedMaxAgeMs());
}

export function pruneExpiredGateAccessHeaders(now: number = Date.now()): void {
  for (const [gateId, entry] of gateAccessHeaderCache.entries()) {
    if (gateAccessHeaderReusableUntilMs(entry, 'wait') <= now) {
      gateAccessHeaderCache.delete(gateId);
    }
  }
}

export function invalidateGateAccessHeaders(gateId?: string): void {
  const normalized = normalizeGateId(gateId || '');
  if (!normalized) {
    gateAccessHeaderCache.clear();
    gateAccessHeaderInflight.clear();
    return;
  }
  gateAccessHeaderCache.delete(normalized);
  gateAccessHeaderInflight.delete(normalized);
}

export async function buildGateAccessHeaders(
  gateId: string,
  options: { mode?: GateAccessHeaderMode } = {},
): Promise<Record<string, string> | undefined> {
  const normalizedGate = normalizeGateId(gateId);
  if (!normalizedGate) return undefined;
  const mode =
    options.mode === 'wait' || options.mode === 'session_stream'
      ? options.mode
      : 'default';
  pruneExpiredGateAccessHeaders();
  const cached = gateAccessHeaderCache.get(normalizedGate);
  if (cached && gateAccessHeaderReusableUntilMs(cached, mode) > Date.now()) {
    return cached.headers;
  }
  if (mode === 'session_stream') {
    const streamHeaders = getGateSessionStreamAccessHeaders(normalizedGate);
    if (streamHeaders) {
      const proofTsMs = Math.max(
        0,
        Number.parseInt(String(streamHeaders['X-Wormhole-Gate-Ts'] || '0'), 10) * 1000,
      );
      gateAccessHeaderCache.set(normalizedGate, {
        headers: streamHeaders,
        expiresAt: Date.now() + gateAccessProofTtlMs(),
        proofTsMs,
      });
      return streamHeaders;
    }
  }
  const inflight = gateAccessHeaderInflight.get(normalizedGate);
  if (inflight) {
    return inflight;
  }
  const pending = (async () => {
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
      const proofTsMs = Math.max(0, Number(gateTs || 0)) * 1000;
      const headers = {
        'X-Wormhole-Node-Id': nodeId,
        'X-Wormhole-Gate-Proof': gateProof,
        'X-Wormhole-Gate-Ts': gateTs,
      };
      gateAccessHeaderCache.set(normalizedGate, {
        headers,
        expiresAt: Date.now() + gateAccessProofTtlMs(),
        proofTsMs,
      });
      return headers;
    } catch {
      return undefined;
    } finally {
      gateAccessHeaderInflight.delete(normalizedGate);
    }
  })();
  gateAccessHeaderInflight.set(normalizedGate, pending);
  return pending;
}
