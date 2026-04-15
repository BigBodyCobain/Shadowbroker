import { normalizePayload, type JsonValue } from '@/mesh/meshProtocol';

export type ValidationResult = { ok: true } | { ok: false; reason: string };

function requireFields(payload: Record<string, JsonValue>, fields: string[]): ValidationResult {
  for (const field of fields) {
    if (!(field in payload)) {
      return { ok: false, reason: `Missing field: ${field}` };
    }
  }
  return { ok: true };
}

function validateMessage(payload: Record<string, JsonValue>): ValidationResult {
  const req = requireFields(payload, ['message', 'destination', 'channel', 'priority', 'ephemeral']);
  if (!req.ok) return req;
  const priority = String(payload.priority ?? '');
  if (!['normal', 'high', 'emergency', 'low'].includes(priority)) {
    return { ok: false, reason: 'Invalid priority' };
  }
  if (typeof payload.ephemeral !== 'boolean') {
    return { ok: false, reason: 'ephemeral must be boolean' };
  }
  const transportLock = String(payload.transport_lock ?? '').toLowerCase();
  if (transportLock && transportLock !== 'meshtastic') {
    return { ok: false, reason: 'Invalid transport_lock' };
  }
  return { ok: true };
}

function validateGateMessage(payload: Record<string, JsonValue>): ValidationResult {
  const req = requireFields(payload, ['gate', 'epoch', 'ciphertext', 'nonce', 'sender_ref']);
  if (!req.ok) return req;
  if ('message' in payload) {
    return { ok: false, reason: 'plaintext gate message field is not allowed' };
  }
  const gate = String(payload.gate ?? '').trim().toLowerCase();
  if (!gate) {
    return { ok: false, reason: 'gate cannot be empty' };
  }
  const epoch = Number(payload.epoch ?? 0);
  if (!Number.isFinite(epoch) || Math.trunc(epoch) <= 0) {
    return { ok: false, reason: 'epoch must be a positive integer' };
  }
  if (!String(payload.ciphertext ?? '').trim()) {
    return { ok: false, reason: 'ciphertext cannot be empty' };
  }
  if (!String(payload.nonce ?? '').trim()) {
    return { ok: false, reason: 'nonce cannot be empty' };
  }
  if (!String(payload.sender_ref ?? '').trim()) {
    return { ok: false, reason: 'sender_ref cannot be empty' };
  }
  if (String(payload.format ?? 'g1').trim().toLowerCase() !== 'g1') {
    return { ok: false, reason: 'Unsupported gate message format' };
  }
  return { ok: true };
}

function validateVote(payload: Record<string, JsonValue>): ValidationResult {
  const req = requireFields(payload, ['target_id', 'vote', 'gate']);
  if (!req.ok) return req;
  const vote = Number(payload.vote);
  if (![1, -1].includes(vote)) {
    return { ok: false, reason: 'Invalid vote' };
  }
  return { ok: true };
}

function validateGateCreate(payload: Record<string, JsonValue>): ValidationResult {
  const req = requireFields(payload, ['gate_id', 'display_name', 'rules']);
  if (!req.ok) return req;
  if (typeof payload.rules !== 'object') {
    return { ok: false, reason: 'rules must be an object' };
  }
  return { ok: true };
}

function validatePrediction(payload: Record<string, JsonValue>): ValidationResult {
  return requireFields(payload, ['market_title', 'side', 'stake_amount']);
}

function validateStake(payload: Record<string, JsonValue>): ValidationResult {
  return requireFields(payload, ['message_id', 'poster_id', 'side', 'amount', 'duration_days']);
}

function validateDmKey(payload: Record<string, JsonValue>): ValidationResult {
  const req = requireFields(payload, ['dh_pub_key', 'dh_algo', 'timestamp']);
  if (!req.ok) return req;
  const algo = String(payload.dh_algo ?? '');
  if (!['X25519', 'ECDH', 'ECDH_P256'].includes(algo)) {
    return { ok: false, reason: 'Invalid dh_algo' };
  }
  return { ok: true };
}

function validateDmMessage(payload: Record<string, JsonValue>): ValidationResult {
  const req = requireFields(payload, [
    'recipient_id',
    'delivery_class',
    'recipient_token',
    'ciphertext',
    'msg_id',
    'timestamp',
  ]);
  if (!req.ok) return req;
  const deliveryClass = String(payload.delivery_class ?? '').toLowerCase();
  if (!['request', 'shared'].includes(deliveryClass)) {
    return { ok: false, reason: 'Invalid delivery_class' };
  }
  if (deliveryClass === 'shared' && !String(payload.recipient_token ?? '').trim()) {
    return { ok: false, reason: 'recipient_token required for shared delivery' };
  }
  return { ok: true };
}

function validateMailboxClaims(
  claims: JsonValue,
): ValidationResult {
  if (!Array.isArray(claims) || claims.length === 0) {
    return { ok: false, reason: 'mailbox_claims must be a non-empty list' };
  }
  for (const claim of claims) {
    if (!claim || typeof claim !== 'object' || Array.isArray(claim)) {
      return { ok: false, reason: 'mailbox_claims entries must be objects' };
    }
    const record = claim as Record<string, JsonValue>;
    const claimType = String(record.type ?? '').toLowerCase();
    if (!['self', 'requests', 'shared'].includes(claimType)) {
      return { ok: false, reason: 'Invalid mailbox claim type' };
    }
    if (!String(record.token ?? '').trim()) {
      return { ok: false, reason: `${claimType} mailbox claims require token` };
    }
  }
  return { ok: true };
}

function validateDmPoll(payload: Record<string, JsonValue>): ValidationResult {
  const req = requireFields(payload, ['mailbox_claims', 'timestamp', 'nonce']);
  if (!req.ok) return req;
  return validateMailboxClaims(payload.mailbox_claims);
}

function validateDmCount(payload: Record<string, JsonValue>): ValidationResult {
  return validateDmPoll(payload);
}

function validateDmBlock(payload: Record<string, JsonValue>): ValidationResult {
  const req = requireFields(payload, ['blocked_id', 'action']);
  if (!req.ok) return req;
  const action = String(payload.action ?? '');
  if (!['block', 'unblock'].includes(action)) {
    return { ok: false, reason: 'Invalid action' };
  }
  return { ok: true };
}

function validateDmKeyWitness(payload: Record<string, JsonValue>): ValidationResult {
  const req = requireFields(payload, ['target_id', 'dh_pub_key', 'timestamp']);
  if (!req.ok) return req;
  const ts = Number(payload.timestamp ?? 0);
  if (!Number.isFinite(ts) || ts <= 0) {
    return { ok: false, reason: 'Invalid timestamp' };
  }
  return { ok: true };
}

function validateTrustVouch(payload: Record<string, JsonValue>): ValidationResult {
  const req = requireFields(payload, ['target_id', 'timestamp']);
  if (!req.ok) return req;
  const ts = Number(payload.timestamp ?? 0);
  if (!Number.isFinite(ts) || ts <= 0) {
    return { ok: false, reason: 'Invalid timestamp' };
  }
  return { ok: true };
}

function validateKeyRotate(payload: Record<string, JsonValue>): ValidationResult {
  return requireFields(payload, [
    'old_node_id',
    'old_public_key',
    'old_public_key_algo',
    'new_public_key',
    'new_public_key_algo',
    'timestamp',
    'old_signature',
  ]);
}

function validateKeyRevoke(payload: Record<string, JsonValue>): ValidationResult {
  const req = requireFields(payload, [
    'revoked_public_key',
    'revoked_public_key_algo',
    'revoked_at',
    'grace_until',
    'reason',
  ]);
  if (!req.ok) return req;
  const revokedAt = Number(payload.revoked_at ?? 0);
  const graceUntil = Number(payload.grace_until ?? 0);
  if (!Number.isFinite(revokedAt) || revokedAt <= 0) {
    return { ok: false, reason: 'revoked_at must be positive' };
  }
  if (!Number.isFinite(graceUntil) || graceUntil < revokedAt) {
    return { ok: false, reason: 'grace_until must be >= revoked_at' };
  }
  return { ok: true };
}

function validateAbuseReport(payload: Record<string, JsonValue>): ValidationResult {
  const req = requireFields(payload, ['target_id', 'reason']);
  if (!req.ok) return req;
  if (!String(payload.reason ?? '').trim()) {
    return { ok: false, reason: 'reason cannot be empty' };
  }
  return { ok: true };
}

const validators: Record<string, (payload: Record<string, JsonValue>) => ValidationResult> = {
  message: validateMessage,
  gate_message: validateGateMessage,
  vote: validateVote,
  gate_create: validateGateCreate,
  prediction: validatePrediction,
  stake: validateStake,
  dm_key: validateDmKey,
  dm_message: validateDmMessage,
  dm_poll: validateDmPoll,
  dm_count: validateDmCount,
  dm_block: validateDmBlock,
  dm_key_witness: validateDmKeyWitness,
  trust_vouch: validateTrustVouch,
  key_rotate: validateKeyRotate,
  key_revoke: validateKeyRevoke,
  abuse_report: validateAbuseReport,
};

export function validateEventPayload(
  eventType: string,
  payload: Record<string, JsonValue>,
): ValidationResult {
  const validator = validators[eventType];
  if (!validator) {
    return { ok: false, reason: 'Unknown event_type' };
  }
  const normalized = normalizePayload(eventType, payload);
  if (JSON.stringify(normalized) !== JSON.stringify(payload)) {
    return { ok: false, reason: 'Payload is not normalized' };
  }
  if (eventType !== 'message' && 'ephemeral' in payload) {
    return { ok: false, reason: 'ephemeral not allowed for this event type' };
  }
  return validator(payload);
}
