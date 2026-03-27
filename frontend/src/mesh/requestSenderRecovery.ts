export type RecoveredSenderSeal = {
  sender_id: string;
  seal_verified: boolean;
} | null;

export const REQUEST_V2_REDUCED_VERSION = 'request-v2-reduced-v3';

export type SenderRecoveryState = 'pending' | 'verified' | 'failed';

type SenderRecoveryEnvelopeLike = {
  delivery_class?: string;
  sender_id?: string;
  sender_seal?: string;
  request_contract_version?: string;
  sender_recovery_required?: boolean;
  sender_recovery_state?: string;
};

export function isCanonicalReducedRequestEnvelope(
  message: SenderRecoveryEnvelopeLike,
): boolean {
  return (
    String(message.request_contract_version || '').trim() === REQUEST_V2_REDUCED_VERSION &&
    message.sender_recovery_required === true
  );
}

export function requiresSenderRecovery(
  message: SenderRecoveryEnvelopeLike,
): boolean {
  if (isCanonicalReducedRequestEnvelope(message)) {
    return true;
  }
  return Boolean(
    String(message.sender_seal || '').trim() &&
      String(message.sender_id || '').trim().startsWith('sealed:'),
  );
}

export function getSenderRecoveryState(
  message: SenderRecoveryEnvelopeLike,
): SenderRecoveryState | undefined {
  const state = String(message.sender_recovery_state || '')
    .trim()
    .toLowerCase();
  if (state === 'pending' || state === 'verified' || state === 'failed') {
    return state;
  }
  if (isCanonicalReducedRequestEnvelope(message)) {
    return 'pending';
  }
  return undefined;
}

export function shouldAllowRequestActions(
  message: Pick<
    SenderRecoveryEnvelopeLike,
    'request_contract_version' | 'sender_recovery_required' | 'sender_recovery_state'
  >,
): boolean {
  if (!isCanonicalReducedRequestEnvelope(message)) {
    return true;
  }
  return getSenderRecoveryState(message) === 'verified';
}

export function shouldKeepUnresolvedRequestVisible(
  message: Pick<
    SenderRecoveryEnvelopeLike,
    | 'delivery_class'
    | 'request_contract_version'
    | 'sender_recovery_required'
    | 'sender_recovery_state'
  >,
): boolean {
  if (String(message.delivery_class || '').trim().toLowerCase() !== 'request') {
    return false;
  }
  const state = getSenderRecoveryState(message);
  return isCanonicalReducedRequestEnvelope(message) && (state === 'pending' || state === 'failed');
}

export function shouldPromoteRecoveredSenderForKnownContact(
  resolved: RecoveredSenderSeal,
  contactId: string,
): boolean {
  return Boolean(
    resolved &&
      resolved.seal_verified === true &&
      String(resolved.sender_id || '').trim() === String(contactId || '').trim(),
  );
}

export function shouldPromoteRecoveredSenderForBootstrap(
  resolved: RecoveredSenderSeal,
): boolean {
  return Boolean(
    resolved &&
      resolved.seal_verified === true &&
      String(resolved.sender_id || '').trim(),
  );
}

export async function recoverSenderSealWithFallback(options: {
  wormholeReady: boolean;
  openLocal: () => Promise<RecoveredSenderSeal>;
  openHelper: () => Promise<RecoveredSenderSeal>;
}): Promise<RecoveredSenderSeal> {
  const localResolved = await options.openLocal();
  if (localResolved) {
    return localResolved;
  }
  if (!options.wormholeReady) {
    return null;
  }
  try {
    return await options.openHelper();
  } catch {
    return null;
  }
}
