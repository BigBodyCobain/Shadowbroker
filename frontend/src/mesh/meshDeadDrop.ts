import { currentMailboxEpoch } from '@/mesh/meshMailbox';
import { allDmPeerIds } from '@/mesh/meshDmConsent';
import { deriveSharedSecret, getStoredNodeDescriptor, type Contact } from '@/mesh/meshIdentity';
import {
  deriveWormholeDeadDropTokenPair,
  deriveWormholeDeadDropTokens,
  isWormholeReady,
} from '@/mesh/wormholeIdentityClient';

function bufToHex(buf: ArrayBuffer): string {
  return Array.from(new Uint8Array(buf))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
}

export async function hmacSha256(keyBytes: ArrayBuffer, message: string): Promise<ArrayBuffer> {
  const key = await crypto.subtle.importKey('raw', keyBytes, { name: 'HMAC', hash: 'SHA-256' }, false, [
    'sign',
  ]);
  const data = new TextEncoder().encode(message);
  return crypto.subtle.sign('HMAC', key, data);
}

function contactContext(peerId: string): string | null {
  const identity = getStoredNodeDescriptor();
  if (!identity) return null;
  const ids = [identity.nodeId, peerId].sort().join('|');
  return ids;
}

export async function deadDropToken(peerId: string, peerDhPub: string, epoch?: number): Promise<string> {
  if (await isWormholeReady()) {
    const pair = await deriveWormholeDeadDropTokenPair(peerId, peerDhPub).catch(() => null);
    if (pair?.ok) {
      return epoch === pair.epoch - 1 ? pair.previous : pair.current;
    }
  }
  const ctx = contactContext(peerId);
  if (!ctx) return '';
  const bucket = typeof epoch === 'number' ? epoch : currentMailboxEpoch();
  const secret = await deriveSharedSecret(peerDhPub);
  const digest = await hmacSha256(secret, `sb_dd|v1|${bucket}|${ctx}`);
  return bufToHex(digest);
}

export async function deadDropTokenPair(
  peerId: string,
  peerDhPub: string,
): Promise<{ current: string; previous: string; epoch: number }> {
  const epoch = currentMailboxEpoch();
  const current = await deadDropToken(peerId, peerDhPub, epoch);
  const previous = await deadDropToken(peerId, peerDhPub, epoch - 1);
  return { current, previous, epoch };
}

export async function deadDropTokensForContacts(
  contacts: Record<string, Contact>,
  limit: number = 24,
): Promise<string[]> {
  if (await isWormholeReady()) {
    const items = Object.entries(contacts)
      .filter(([_, contact]) => Boolean(contact?.dhPubKey) && !contact.blocked)
      .flatMap(([peerId, contact]) =>
        allDmPeerIds(peerId, contact).map((candidateId) => ({
          peer_id: candidateId,
          peer_dh_pub: String(contact?.dhPubKey || ''),
        })),
      )
      .slice(0, limit);
    if (items.length > 0) {
      const batch = await deriveWormholeDeadDropTokens(items, limit).catch(() => null);
      if (batch?.ok && Array.isArray(batch.tokens)) {
        const seen = new Set<string>();
        const unique: string[] = [];
        for (const item of batch.tokens) {
          for (const token of [String(item.current || ''), String(item.previous || '')]) {
            if (!token || seen.has(token)) continue;
            seen.add(token);
            unique.push(token);
            if (unique.length >= limit) return unique;
          }
        }
        return unique;
      }
    }
  }
  const tokens: string[] = [];
  for (const [peerId, contact] of Object.entries(contacts)) {
    if (!contact?.dhPubKey || contact.blocked) continue;
    for (const candidateId of allDmPeerIds(peerId, contact)) {
      try {
        const pair = await deadDropTokenPair(candidateId, contact.dhPubKey);
        if (pair.current) tokens.push(pair.current);
        if (pair.previous) tokens.push(pair.previous);
        if (tokens.length >= limit) break;
      } catch {
        /* ignore */
      }
    }
    if (tokens.length >= limit) break;
  }
  // dedupe while preserving order
  const seen = new Set<string>();
  const unique: string[] = [];
  for (const token of tokens) {
    if (seen.has(token)) continue;
    seen.add(token);
    unique.push(token);
    if (unique.length >= limit) break;
  }
  return unique;
}
