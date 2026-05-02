import type { InfoNetMessage, DmTransportMode } from './types';
export {
  buildGateAccessHeaders,
  gateAccessHeaderCache,
  invalidateGateAccessHeaders,
  pruneExpiredGateAccessHeaders,
} from '@/mesh/gateAccessProof';

// ─── Pure helpers ────────────────────────────────────────────────────────────

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

export function normalizeInfoNetMessage(message: InfoNetMessage): InfoNetMessage {
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
    reply_to: String(message.reply_to ?? payload.reply_to ?? ''),
    ciphertext: String(message.ciphertext ?? payload.ciphertext ?? ''),
    nonce: String(message.nonce ?? payload.nonce ?? ''),
    sender_ref: String(message.sender_ref ?? payload.sender_ref ?? ''),
    format: String(message.format ?? payload.format ?? ''),
    envelope_hash: String(message.envelope_hash ?? payload.envelope_hash ?? ''),
  };
}

export function gateDecryptCacheKey(message: InfoNetMessage): string {
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

export function timeAgo(ts: number): string {
  const now = Date.now() / 1000;
  const diff = now - ts;
  if (diff < 60) return `${Math.floor(diff)}s`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h`;
  return `${Math.floor(diff / 86400)}d`;
}

export function dmTransportDisplay(mode: DmTransportMode): { label: string; className: string } {
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

export function randomHex(bytes: number = 16): string {
  const buf = new Uint8Array(bytes);
  crypto.getRandomValues(buf);
  return Array.from(buf)
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
}

export function jitterDelay(baseMs: number, spreadMs: number): number {
  const jitter = Math.floor((Math.random() * 2 - 1) * spreadMs);
  return Math.max(3000, baseMs + jitter);
}

export function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export function randomBase64(bytes: number = 64): string {
  const buf = new Uint8Array(bytes);
  crypto.getRandomValues(buf);
  return btoa(String.fromCharCode(...buf));
}

// ─── Gate access header cache (module singleton) ─────────────────────────────

