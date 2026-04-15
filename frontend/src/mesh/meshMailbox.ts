import { deleteKey, getKey, setKey } from '@/mesh/meshKeyStore';

const DM_EPOCH_SECONDS = 6 * 60 * 60; // 6 hours
const MAILBOX_CLAIM_KEY_ID = 'sb_mesh_mailbox_claim_key';

function bufToHex(buf: ArrayBuffer): string {
  return Array.from(new Uint8Array(buf))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
}

async function getOrCreateMailboxClaimKey(): Promise<CryptoKey> {
  const existing = await getKey(MAILBOX_CLAIM_KEY_ID);
  if (existing) {
    return existing;
  }
  const key = await crypto.subtle.generateKey(
    { name: 'HMAC', hash: 'SHA-256', length: 256 },
    false,
    ['sign'],
  );
  await setKey(MAILBOX_CLAIM_KEY_ID, key);
  return key;
}

export function currentMailboxEpoch(tsSeconds?: number): number {
  const now = typeof tsSeconds === 'number' ? tsSeconds : Date.now() / 1000;
  return Math.floor(now / DM_EPOCH_SECONDS);
}

export async function mailboxClaimToken(
  claimType: 'requests' | 'self',
  nodeId: string,
): Promise<string> {
  const normalizedNodeId = String(nodeId || '').trim();
  if (!normalizedNodeId) {
    throw new Error('nodeId required for mailbox claim token');
  }
  const key = await getOrCreateMailboxClaimKey();
  const message = new TextEncoder().encode(`sb_mailbox_claim|v1|${claimType}|${normalizedNodeId}`);
  const digest = await crypto.subtle.sign('HMAC', key, message);
  return bufToHex(digest);
}

export async function mailboxDecoySharedToken(index: number, epoch?: number): Promise<string> {
  const key = await getOrCreateMailboxClaimKey();
  const bucket = currentMailboxEpoch(epoch);
  const ordinal = Math.max(0, Number(index || 0));
  const message = new TextEncoder().encode(`sb_mailbox_claim|v1|shared_decoy|${bucket}|${ordinal}`);
  const digest = await crypto.subtle.sign('HMAC', key, message);
  return bufToHex(digest);
}

export async function purgeMailboxClaimKey(): Promise<void> {
  await deleteKey(MAILBOX_CLAIM_KEY_ID);
}
