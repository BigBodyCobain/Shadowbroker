import type { Contact } from '@/mesh/meshIdentity';
import type { DmSendResponse } from '@/mesh/meshDmClient';
import { updatePrivateDeliveryAction } from '@/mesh/wormholeClient';

export type DmConnectIntent =
  | 'invite_short_address'
  | 'invite_import'
  | 'contact_request'
  | 'contact_accept'
  | 'contact_offer';

export function connectDeliveryMeta(options: {
  intent: DmConnectIntent;
  lookupPeerUrl?: string;
  contact?: Partial<Contact> | null;
}): { connectIntent: DmConnectIntent; lookupPeerUrl?: string } {
  const lookupPeerUrl = String(
    options.lookupPeerUrl || options.contact?.invitePinnedLookupPeerUrl || '',
  )
    .trim()
    .replace(/\/$/, '');
  return {
    connectIntent: options.intent,
    ...(lookupPeerUrl ? { lookupPeerUrl } : {}),
  };
}

/** Fallback when the server queued connect traffic but UI still shows a manual relay step. */
export async function ensureDmOutboxReleased(sent: DmSendResponse): Promise<DmSendResponse> {
  if (!sent.ok) return sent;
  const outboxId = String(sent.outbox_id || '').trim();
  if (!outboxId) return sent;
  if (!sent.queued && !sent.private_transport_pending) return sent;
  try {
    await updatePrivateDeliveryAction(outboxId, 'relay');
  } catch {
    // Backend auto-release may have already approved this outbox item.
  }
  return sent;
}
