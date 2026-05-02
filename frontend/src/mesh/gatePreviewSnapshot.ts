import { hasLocalControlBridge } from '@/lib/localControlTransport';
import { gateEnvelopeDisplayText, isEncryptedGateEnvelope } from '@/mesh/gateEnvelope';
import {
  fetchGateMessageSnapshot,
  invalidateGateMessageSnapshot,
  type GateMessageSnapshotRecord,
} from '@/mesh/gateMessageSnapshot';
import { decryptWormholeGateMessage } from '@/mesh/wormholeIdentityClient';

export interface GateThreadPreviewSnapshot {
  nodeId: string;
  age: string;
  text: string;
  encrypted?: boolean;
}

const GATE_PREVIEW_BROWSER_TTL_MS = 12_000;
const GATE_PREVIEW_NATIVE_TTL_MS = 4_000;

const gatePreviewCache = new Map<
  string,
  { value: GateThreadPreviewSnapshot[]; expiresAt: number }
>();

function normalizeGateId(gateId: string): string {
  return String(gateId || '').trim().toLowerCase();
}

function gatePreviewTtlMs(): number {
  return hasLocalControlBridge()
    ? GATE_PREVIEW_NATIVE_TTL_MS
    : GATE_PREVIEW_BROWSER_TTL_MS;
}

function previewAge(timestamp: number): string {
  const ageMin = Math.floor((Date.now() / 1000 - Number(timestamp || 0)) / 60);
  return ageMin < 60 ? `${ageMin}m ago` : `${Math.floor(ageMin / 60)}h ago`;
}

export async function describeGateMessagePreview(message: GateMessageSnapshotRecord): Promise<string> {
  const normalized = message;
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
      String(normalized.gate_envelope || ''),
      String(normalized.envelope_hash || ''),
    );
    return gateEnvelopeDisplayText({
      ...normalized,
      decrypted_message: decrypted.ok ? decrypted.plaintext : '',
    }).slice(0, 120);
  } catch {
    return gateEnvelopeDisplayText(normalized).slice(0, 120);
  }
}

export function invalidateGateThreadPreviewSnapshot(gateId?: string): void {
  const normalized = normalizeGateId(gateId || '');
  if (!normalized) {
    gatePreviewCache.clear();
    invalidateGateMessageSnapshot();
    return;
  }
  gatePreviewCache.delete(normalized);
  invalidateGateMessageSnapshot(normalized);
}

export async function fetchGateThreadPreviewSnapshot(
  gateId: string,
  options: { force?: boolean } = {},
): Promise<GateThreadPreviewSnapshot[]> {
  const normalizedGate = normalizeGateId(gateId);
  const cached = gatePreviewCache.get(normalizedGate);
  if (!options.force && cached && cached.expiresAt > Date.now()) {
    return cached.value;
  }
  const messages = (await fetchGateMessageSnapshot(normalizedGate, 6, options)).slice(0, 4);
  const previews = await Promise.all(
    messages.map(async (message) => ({
      nodeId: String(message.node_id || ''),
      age: previewAge(message.timestamp),
      text: await describeGateMessagePreview(message),
      encrypted: isEncryptedGateEnvelope(message),
    })),
  );
  gatePreviewCache.set(normalizedGate, {
    value: previews,
    expiresAt: Date.now() + gatePreviewTtlMs(),
  });
  return previews;
}
