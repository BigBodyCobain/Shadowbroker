export const REQUEST_V2_SENDER_SEAL_VERSION_ERROR = 'request_sender_seal_v3_required';

export function requiresCanonicalRequestV2SenderSeal(options: {
  deliveryClass: 'request' | 'shared';
  useSealedSender?: boolean;
}): boolean {
  return options.deliveryClass === 'request' && options.useSealedSender === true;
}

export function ensureCanonicalRequestV2SenderSeal(senderSeal: string): string {
  const normalized = String(senderSeal || '').trim();
  if (!normalized.startsWith('v3:')) {
    throw new Error(REQUEST_V2_SENDER_SEAL_VERSION_ERROR);
  }
  return normalized;
}
