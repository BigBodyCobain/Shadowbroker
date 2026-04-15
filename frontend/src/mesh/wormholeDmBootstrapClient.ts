import { controlPlaneJson } from '@/lib/controlPlane';
import { ensureWormholeReadyForSecureAction, isWormholeReady, isWormholeSecureRequired } from '@/mesh/wormholeIdentityClient';

export async function canUseWormholeBootstrap(): Promise<boolean> {
  const ready = await isWormholeReady();
  if (!ready && (await isWormholeSecureRequired())) {
    return false;
  }
  return ready;
}

export async function bootstrapEncryptAccessRequest(peerId: string, plaintext: string): Promise<string> {
  await ensureWormholeReadyForSecureAction('bootstrap_encrypt');
  const data = await controlPlaneJson<{ result: string }>('/api/wormhole/dm/bootstrap-encrypt', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      peer_id: peerId,
      plaintext,
    }),
  });
  return String(data.result || '');
}

export async function bootstrapDecryptAccessRequest(senderId: string, ciphertext: string): Promise<string> {
  await ensureWormholeReadyForSecureAction('bootstrap_decrypt');
  const data = await controlPlaneJson<{ result: string }>('/api/wormhole/dm/bootstrap-decrypt', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      sender_id: senderId,
      ciphertext,
    }),
  });
  return String(data.result || '');
}
