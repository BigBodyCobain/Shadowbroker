export const PROTOCOL_VERSION = 'infonet/2';
export const NETWORK_ID = 'sb-testnet-0';

export type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };

function stableStringify(value: JsonValue): string {
  if (value === null || typeof value !== 'object') {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map((v) => stableStringify(v)).join(',')}]`;
  }
  const obj = value as Record<string, JsonValue>;
  const keys = Object.keys(obj).sort();
  const entries = keys.map((k) => `${JSON.stringify(k)}:${stableStringify(obj[k])}`);
  return `{${entries.join(',')}}`;
}

export function canonicalJson(obj: Record<string, JsonValue>): string {
  return stableStringify(obj);
}

export function normalizeMessagePayload(payload: Record<string, JsonValue>) {
  const normalized: Record<string, JsonValue> = {
    message: String(payload.message ?? ''),
    destination: String(payload.destination ?? ''),
    channel: String(payload.channel ?? 'LongFast'),
    priority: String(payload.priority ?? 'normal'),
    ephemeral: Boolean(payload.ephemeral ?? false),
  };
  const transportLock = String(payload.transport_lock ?? '').toLowerCase();
  if (transportLock) {
    normalized.transport_lock = transportLock;
  }
  return normalized;
}

export function normalizeGateMessagePayload(payload: Record<string, JsonValue>) {
  const epochValue = Number(payload.epoch ?? 0);
  return {
    gate: String(payload.gate ?? '').trim().toLowerCase(),
    epoch: Number.isFinite(epochValue) ? Math.trunc(epochValue) : 0,
    ciphertext: String(payload.ciphertext ?? ''),
    nonce: String(payload.nonce ?? payload.iv ?? ''),
    sender_ref: String(payload.sender_ref ?? ''),
    format: String(payload.format ?? 'g1'),
  };
}

export function normalizeVotePayload(payload: Record<string, JsonValue>) {
  const voteVal = Number(payload.vote ?? 0);
  return {
    target_id: String(payload.target_id ?? ''),
    vote: Number.isFinite(voteVal) ? Math.trunc(voteVal) : 0,
    gate: String(payload.gate ?? ''),
  };
}

export function normalizeGateCreatePayload(payload: Record<string, JsonValue>) {
  return {
    gate_id: String(payload.gate_id ?? '').toLowerCase(),
    display_name: String(payload.display_name ?? ''),
    rules: (payload.rules as JsonValue) ?? {},
  };
}

export function normalizePredictionPayload(payload: Record<string, JsonValue>) {
  return {
    market_title: String(payload.market_title ?? ''),
    side: String(payload.side ?? ''),
    stake_amount: Number(payload.stake_amount ?? 0),
  };
}

export function normalizeStakePayload(payload: Record<string, JsonValue>) {
  return {
    message_id: String(payload.message_id ?? ''),
    poster_id: String(payload.poster_id ?? ''),
    side: String(payload.side ?? ''),
    amount: Number(payload.amount ?? 0),
    duration_days: Number(payload.duration_days ?? 0),
  };
}

export function normalizeDmKeyPayload(payload: Record<string, JsonValue>) {
  return {
    dh_pub_key: String(payload.dh_pub_key ?? ''),
    dh_algo: String(payload.dh_algo ?? ''),
    timestamp: Number(payload.timestamp ?? 0),
  };
}

export function normalizeDmMessagePayload(payload: Record<string, JsonValue>) {
  const normalized: Record<string, JsonValue> = {
    recipient_id: String(payload.recipient_id ?? ''),
    delivery_class: String(payload.delivery_class ?? '').toLowerCase(),
    recipient_token: String(payload.recipient_token ?? ''),
    ciphertext: String(payload.ciphertext ?? ''),
    msg_id: String(payload.msg_id ?? ''),
    timestamp: Number(payload.timestamp ?? 0),
    format: String(payload.format ?? 'dm1').trim().toLowerCase(),
  };
  const sw = payload.session_welcome;
  if (sw) {
    normalized.session_welcome = String(sw);
  }
  const senderSeal = payload.sender_seal;
  if (senderSeal) {
    normalized.sender_seal = String(senderSeal);
  }
  const relaySalt = payload.relay_salt;
  if (relaySalt) {
    normalized.relay_salt = String(relaySalt).trim().toLowerCase();
  }
  return normalized;
}

function normalizeMailboxClaims(payload: Record<string, JsonValue>) {
  const claims = Array.isArray(payload.mailbox_claims) ? payload.mailbox_claims : [];
  return claims.flatMap((claim) => {
    if (!claim || typeof claim !== 'object' || Array.isArray(claim)) return [];
    const record = claim as Record<string, JsonValue>;
    return [
      {
        type: String(record.type ?? '').toLowerCase(),
        token: String(record.token ?? ''),
      },
    ];
  });
}

export function normalizeDmPollPayload(payload: Record<string, JsonValue>) {
  return {
    mailbox_claims: normalizeMailboxClaims(payload),
    timestamp: Number(payload.timestamp ?? 0),
    nonce: String(payload.nonce ?? ''),
  };
}

export function normalizeDmCountPayload(payload: Record<string, JsonValue>) {
  return normalizeDmPollPayload(payload);
}

export function normalizeDmBlockPayload(payload: Record<string, JsonValue>) {
  return {
    blocked_id: String(payload.blocked_id ?? ''),
    action: String(payload.action ?? 'block').toLowerCase(),
  };
}

export function normalizeDmKeyWitnessPayload(payload: Record<string, JsonValue>) {
  return {
    target_id: String(payload.target_id ?? ''),
    dh_pub_key: String(payload.dh_pub_key ?? ''),
    timestamp: Number(payload.timestamp ?? 0),
  };
}

export function normalizeTrustVouchPayload(payload: Record<string, JsonValue>) {
  return {
    target_id: String(payload.target_id ?? ''),
    note: String(payload.note ?? '').slice(0, 140),
    timestamp: Number(payload.timestamp ?? 0),
  };
}

export function normalizeKeyRotatePayload(payload: Record<string, JsonValue>) {
  return {
    old_node_id: String(payload.old_node_id ?? ''),
    old_public_key: String(payload.old_public_key ?? ''),
    old_public_key_algo: String(payload.old_public_key_algo ?? ''),
    new_public_key: String(payload.new_public_key ?? ''),
    new_public_key_algo: String(payload.new_public_key_algo ?? ''),
    timestamp: Number(payload.timestamp ?? 0),
    old_signature: String(payload.old_signature ?? ''),
  };
}

export function normalizeKeyRevokePayload(payload: Record<string, JsonValue>) {
  return {
    revoked_public_key: String(payload.revoked_public_key ?? ''),
    revoked_public_key_algo: String(payload.revoked_public_key_algo ?? ''),
    revoked_at: Number(payload.revoked_at ?? 0),
    grace_until: Number(payload.grace_until ?? 0),
    reason: String(payload.reason ?? '').slice(0, 140),
  };
}

export function normalizeAbuseReportPayload(payload: Record<string, JsonValue>) {
  return {
    target_id: String(payload.target_id ?? ''),
    reason: String(payload.reason ?? '').slice(0, 280),
    gate: String(payload.gate ?? ''),
    evidence: String(payload.evidence ?? '').slice(0, 256),
  };
}

export function normalizePayload(eventType: string, payload: Record<string, JsonValue>) {
  if (eventType === 'message') return normalizeMessagePayload(payload);
  if (eventType === 'gate_message') return normalizeGateMessagePayload(payload);
  if (eventType === 'vote') return normalizeVotePayload(payload);
  if (eventType === 'gate_create') return normalizeGateCreatePayload(payload);
  if (eventType === 'prediction') return normalizePredictionPayload(payload);
  if (eventType === 'stake') return normalizeStakePayload(payload);
  if (eventType === 'dm_key') return normalizeDmKeyPayload(payload);
  if (eventType === 'dm_message') return normalizeDmMessagePayload(payload);
  if (eventType === 'dm_poll') return normalizeDmPollPayload(payload);
  if (eventType === 'dm_count') return normalizeDmCountPayload(payload);
  if (eventType === 'dm_block') return normalizeDmBlockPayload(payload);
  if (eventType === 'dm_key_witness') return normalizeDmKeyWitnessPayload(payload);
  if (eventType === 'trust_vouch') return normalizeTrustVouchPayload(payload);
  if (eventType === 'key_rotate') return normalizeKeyRotatePayload(payload);
  if (eventType === 'key_revoke') return normalizeKeyRevokePayload(payload);
  if (eventType === 'abuse_report') return normalizeAbuseReportPayload(payload);
  return payload;
}

export function buildSignaturePayload(opts: {
  eventType: string;
  nodeId: string;
  sequence: number;
  payload: Record<string, JsonValue>;
}) {
  const normalized = normalizePayload(opts.eventType, opts.payload);
  const payloadJson = canonicalJson(normalized);
  return [
    PROTOCOL_VERSION,
    NETWORK_ID,
    opts.eventType,
    opts.nodeId,
    String(opts.sequence),
    payloadJson,
  ].join('|');
}
