import { deriveSharedSecret, getNodeIdentity } from '@/mesh/meshIdentity';
import { hmacSha256 } from '@/mesh/meshDeadDrop';
import { deriveWormholeSasPhrase, isWormholeReady } from '@/mesh/wormholeIdentityClient';

const SAS_WORDS = [
  'able',
  'acid',
  'aged',
  'also',
  'area',
  'army',
  'atom',
  'aunt',
  'away',
  'baby',
  'back',
  'bake',
  'ball',
  'band',
  'bank',
  'base',
  'bean',
  'bear',
  'belt',
  'bird',
  'book',
  'boom',
  'boot',
  'boss',
  'bowl',
  'burn',
  'cafe',
  'calm',
  'camp',
  'card',
  'cash',
  'cell',
  'chat',
  'city',
  'clay',
  'cloud',
  'coin',
  'cool',
  'crew',
  'data',
  'dawn',
  'desk',
  'dome',
  'door',
  'dust',
  'eagle',
  'east',
  'easy',
  'echo',
  'edge',
  'envy',
  'fair',
  'farm',
  'fast',
  'file',
  'flag',
  'foam',
  'fold',
  'food',
  'game',
  'gate',
  'gear',
  'glow',
  'gold',
];

function sasContext(peerId: string): string | null {
  const identity = getNodeIdentity();
  if (!identity) return null;
  const ids = [identity.nodeId, peerId].sort().join('|');
  return ids;
}

function bytesToWords(bytes: Uint8Array, count: number): string[] {
  const out: string[] = [];
  let acc = 0;
  let accBits = 0;
  for (const b of bytes) {
    acc = (acc << 8) | b;
    accBits += 8;
    while (accBits >= 6 && out.length < count) {
      const idx = (acc >> (accBits - 6)) & 0x3f;
      out.push(SAS_WORDS[idx]);
      accBits -= 6;
    }
    if (out.length >= count) break;
  }
  return out;
}

export async function deriveSasPhrase(peerId: string, peerDhPub: string, words: number = 8): Promise<string> {
  if (await isWormholeReady()) {
    const result = await deriveWormholeSasPhrase(peerId, peerDhPub, words).catch(() => null);
    if (result?.ok && result.phrase) {
      return String(result.phrase || '');
    }
  }
  const ctx = sasContext(peerId);
  if (!ctx) return '';
  const secret = await deriveSharedSecret(peerDhPub);
  const digest = await hmacSha256(secret, `sb_sas|v1|${ctx}`);
  const bytes = new Uint8Array(digest);
  const phrase = bytesToWords(bytes, words);
  return phrase.join(' ');
}
