import { deadDropToken, deadDropTokensForContacts } from '@/mesh/meshDeadDrop';
import { mailboxClaimToken, mailboxDecoySharedToken } from '@/mesh/meshMailbox';
import {
  deriveSenderSealKey,
  ensureDhKeysFresh,
  deriveSharedKey,
  encryptDM,
  getDHAlgo,
  getNodeIdentity,
  getPublicKeyAlgo,
  nextSequence,
  verifyNodeIdBindingFromPublicKey,
  type Contact,
  type NodeIdentity,
} from '@/mesh/meshIdentity';
import {
  buildWormholeSenderSeal,
  getActiveSigningContext,
  isWormholeSecureRequired,
  issueWormholeDmSenderToken,
  issueWormholeDmSenderTokens,
  registerWormholeDmKey,
  signRawMeshMessage,
  signMeshEvent,
} from '@/mesh/wormholeIdentityClient';
import { PROTOCOL_VERSION, type JsonValue } from '@/mesh/meshProtocol';
import {
  ensureCanonicalRequestV2SenderSeal,
  requiresCanonicalRequestV2SenderSeal,
} from '@/mesh/requestSenderSealPolicy';
import { validateEventPayload } from '@/mesh/meshSchema';

export type MailboxClaim = { type: 'self' | 'requests' | 'shared'; token?: string };

export type DmPublicKeyBundle = {
  ok: boolean;
  agent_id: string;
  dh_pub_key: string;
  dh_algo?: string;
  timestamp?: number;
  signature?: string;
  public_key?: string;
  public_key_algo?: string;
  protocol_version?: string;
  sequence?: number;
  bundle_fingerprint?: string;
};

export type DmMessageEnvelope = {
  sender_id: string;
  ciphertext: string;
  timestamp: number;
  msg_id: string;
  delivery_class?: 'request' | 'shared';
  sender_seal?: string;
  transport?: 'reticulum' | 'relay';
  request_contract_version?: 'request-v2-reduced-v3';
  sender_recovery_required?: boolean;
  sender_recovery_state?: 'pending' | 'verified' | 'failed';
};

export type DmPollResponse = {
  ok: boolean;
  messages: DmMessageEnvelope[];
  count: number;
  detail?: string;
};

export type DmCountResponse = {
  ok: boolean;
  count: number;
  detail?: string;
};

export type DmSendResponse = {
  ok: boolean;
  msg_id?: string;
  detail?: string;
  transport?: 'reticulum' | 'relay';
};

export type DmSendRequest = {
  apiBase: string;
  identity: NodeIdentity;
  recipientId: string;
  recipientDhPub?: string;
  ciphertext: string;
  msgId: string;
  timestamp: number;
  deliveryClass: 'request' | 'shared';
  recipientToken?: string;
  useSealedSender?: boolean;
  format?: 'mls1' | 'dm1';
  sessionWelcome?: string;
};

const KEY_DM_BUNDLE_FINGERPRINT = 'sb_dm_bundle_fingerprint';
const KEY_DM_BUNDLE_SEQUENCE = 'sb_dm_bundle_sequence';
const MIN_SHARED_MAILBOX_CLAIMS = 3;
const MAX_TOTAL_MAILBOX_CLAIMS = 32;
const FIXED_MAILBOX_CLAIMS = 2;
const MAX_SHARED_MAILBOX_CLAIMS = MAX_TOTAL_MAILBOX_CLAIMS - FIXED_MAILBOX_CLAIMS;
const MAILBOX_SHARED_CLAIM_BUCKETS = [3, 6, 12, 24, 30] as const;
const MAILBOX_SHARED_CLAIM_EXPERIMENT_ENABLED =
  process.env.NEXT_PUBLIC_ENABLE_RFC2A_CLAIM_SHAPE === '1';
export const MAILBOX_SHARED_CLAIM_SHAPE_VERSION = MAILBOX_SHARED_CLAIM_EXPERIMENT_ENABLED
  ? 'rfc2a-bucketed-v1'
  : 'legacy-floor-v1';
const senderTokenCache = new Map<string, Array<{ sender_token: string; expires_at: number }>>();
let bundleFingerprintCache = '';

if (typeof window !== 'undefined') {
  try {
    localStorage.removeItem(KEY_DM_BUNDLE_FINGERPRINT);
    localStorage.removeItem(KEY_DM_BUNDLE_SEQUENCE);
    sessionStorage.removeItem(KEY_DM_BUNDLE_FINGERPRINT);
    sessionStorage.removeItem(KEY_DM_BUNDLE_SEQUENCE);
  } catch {
    /* ignore */
  }
}

function randomHex(bytes: number = 12): string {
  const arr = crypto.getRandomValues(new Uint8Array(bytes));
  return Array.from(arr)
    .map((byte) => byte.toString(16).padStart(2, '0'))
    .join('');
}

function bufToBase64(buf: ArrayBuffer): string {
  return btoa(String.fromCharCode(...new Uint8Array(buf)));
}

async function createSenderSealV3(
  recipientId: string,
  recipientDhPub: string,
  msgId: string,
  timestamp: number,
): Promise<string> {
  const ephemeral = (await crypto.subtle.generateKey('X25519', true, ['deriveBits'])) as CryptoKeyPair;
  const recipientPub = await crypto.subtle.importKey(
    'raw',
    Uint8Array.from(atob(recipientDhPub), (ch) => ch.charCodeAt(0)),
    'X25519',
    false,
    [],
  );
  const secret = await crypto.subtle.deriveBits(
    { name: 'X25519', public: recipientPub },
    ephemeral.privateKey,
    256,
  );
  const ephemeralPubRaw = await crypto.subtle.exportKey('raw', ephemeral.publicKey);
  const ephemeralPub = bufToBase64(ephemeralPubRaw);
  const salt = await crypto.subtle.digest(
    'SHA-256',
    new TextEncoder().encode(
      `SB-SEAL-SALT|${recipientId}|${msgId}|${PROTOCOL_VERSION}|${ephemeralPub}`,
    ),
  );
  const hkdfKey = await crypto.subtle.importKey('raw', secret, 'HKDF', false, ['deriveKey']);
  const sealKey = await crypto.subtle.deriveKey(
    {
      name: 'HKDF',
      hash: 'SHA-256',
      salt,
      info: new TextEncoder().encode('SB-SENDER-SEAL-V3'),
    },
    hkdfKey,
    { name: 'AES-GCM', length: 256 },
    false,
    ['encrypt', 'decrypt'],
  );
  const sealMessage = `seal|v3|${msgId}|${timestamp}|${recipientId}|${ephemeralPub}`;
  const signed = await signRawMeshMessage(sealMessage);
  const isBound = await verifyNodeIdBindingFromPublicKey(
    signed.context.publicKey,
    signed.context.nodeId,
  );
  if (!isBound) {
    throw new Error('Sender seal node binding failed');
  }
  const encrypted = await encryptDM(
    JSON.stringify({
      seal_version: 'v3',
      ephemeral_pub_key: ephemeralPub,
      sender_id: signed.context.nodeId,
      public_key: signed.context.publicKey,
      public_key_algo: signed.context.publicKeyAlgo,
      msg_id: msgId,
      timestamp,
      signature: signed.signature,
      protocol_version: signed.protocolVersion,
    }),
    sealKey,
  );
  return `v3:${ephemeralPub}:${encrypted}`;
}

function setStoredBundleFingerprint(fingerprint: string, sequence: number): void {
  bundleFingerprintCache = String(fingerprint || '');
  if (typeof window === 'undefined') return;
  try {
    localStorage.removeItem(KEY_DM_BUNDLE_FINGERPRINT);
    localStorage.removeItem(KEY_DM_BUNDLE_SEQUENCE);
    sessionStorage.removeItem(KEY_DM_BUNDLE_FINGERPRINT);
    sessionStorage.removeItem(KEY_DM_BUNDLE_SEQUENCE);
  } catch {
    /* ignore */
  }
}

function getStoredBundleFingerprint(): string {
  return bundleFingerprintCache;
}

function senderTokenCacheKey(
  recipientId: string,
  deliveryClass: 'request' | 'shared',
  recipientToken?: string,
): string {
  return `${deliveryClass}|${recipientId}|${recipientToken || ''}`;
}

function takeCachedSenderToken(
  recipientId: string,
  deliveryClass: 'request' | 'shared',
  recipientToken?: string,
): string {
  const key = senderTokenCacheKey(recipientId, deliveryClass, recipientToken);
  const now = Math.floor(Date.now() / 1000);
  const existing = (senderTokenCache.get(key) || []).filter((item) => item.expires_at > now + 10);
  senderTokenCache.set(key, existing);
  const next = existing.shift();
  senderTokenCache.set(key, existing);
  return String(next?.sender_token || '');
}

async function replenishSenderTokenCache(
  recipientId: string,
  deliveryClass: 'request' | 'shared',
  recipientToken?: string,
): Promise<string> {
  const key = senderTokenCacheKey(recipientId, deliveryClass, recipientToken);
  try {
    const batch = await issueWormholeDmSenderTokens(
      recipientId,
      deliveryClass,
      recipientToken,
      3,
    );
    const tokens = Array.isArray(batch.tokens) ? batch.tokens : [];
    senderTokenCache.set(
      key,
      tokens
        .map((item) => ({
          sender_token: String(item.sender_token || ''),
          expires_at: Number(item.expires_at || 0),
        }))
        .filter((item) => item.sender_token && item.expires_at > 0),
    );
  } catch {
    senderTokenCache.delete(key);
  }
  return takeCachedSenderToken(recipientId, deliveryClass, recipientToken);
}

async function localBundleFingerprint(identity: NodeIdentity, dhPubKey: string, dhAlgo: string): Promise<string> {
  const raw = [
    dhPubKey,
    dhAlgo,
    identity.publicKey,
    getPublicKeyAlgo(),
    PROTOCOL_VERSION,
  ].join('|');
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(raw));
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, '0'))
    .join('');
}

export async function ensureRegisteredDmKey(
  apiBase: string,
  identity: NodeIdentity,
  opts?: { force?: boolean },
): Promise<{ ok: boolean; dhPubKey?: string; dhAlgo?: string; acceptedSequence?: number; bundleFingerprint?: string; detail?: string }> {
  const signingContext = await getActiveSigningContext();
  if (signingContext?.source === 'wormhole') {
    try {
      const data = await registerWormholeDmKey();
      if (data.ok) {
        if (data.bundle_fingerprint && data.bundle_sequence) {
          setStoredBundleFingerprint(data.bundle_fingerprint, data.bundle_sequence);
        }
        return {
          ok: true,
          dhPubKey: data.dh_pub_key,
          dhAlgo: data.dh_algo,
          acceptedSequence: Number(data.bundle_sequence || data.sequence || 0),
          bundleFingerprint: data.bundle_fingerprint,
        };
      }
      return { ok: false, detail: data.detail || 'Failed to register Wormhole DM key' };
    } catch {
      if (await isWormholeSecureRequired()) {
        return { ok: false, detail: 'Wormhole DM key registration required in secure mode' };
      }
      const localIdentity = getNodeIdentity();
      if (!localIdentity) {
        return { ok: false, detail: 'Wormhole DM key registration failed' };
      }
      identity = localIdentity;
    }
  }

  const { pub: dhPubKey, rotated } = await ensureDhKeysFresh();
  if (!dhPubKey) return { ok: false, detail: 'Missing DH public key' };
  const dhAlgo = getDHAlgo();
  const fingerprint = await localBundleFingerprint(identity, dhPubKey, dhAlgo);
  if (!opts?.force && !rotated && fingerprint === getStoredBundleFingerprint()) {
    return { ok: true, dhPubKey, dhAlgo };
  }

  const timestamp = Math.floor(Date.now() / 1000);
  const payload = { dh_pub_key: dhPubKey, dh_algo: dhAlgo, timestamp };
  const valid = validateEventPayload('dm_key', payload as Record<string, JsonValue>);
  if (!valid.ok) return { ok: false, detail: valid.reason };
  const sequence = nextSequence();
  const signed = await signMeshEvent('dm_key', payload, sequence);
  const res = await fetch(`${apiBase}/api/mesh/dm/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      agent_id: signed.context.nodeId,
      dh_pub_key: dhPubKey,
      dh_algo: dhAlgo,
      timestamp,
      public_key: signed.context.publicKey,
      public_key_algo: signed.context.publicKeyAlgo,
      signature: signed.signature,
      sequence: signed.sequence,
      protocol_version: signed.protocolVersion,
    }),
  });
  const data = await res.json();
  if (data.ok) {
    setStoredBundleFingerprint(data.bundle_fingerprint || fingerprint, data.accepted_sequence || sequence);
  }
  return {
    ok: Boolean(data.ok),
    dhPubKey,
    dhAlgo,
    acceptedSequence: Number(data.accepted_sequence || sequence),
    bundleFingerprint: String(data.bundle_fingerprint || fingerprint),
    detail: data.detail,
  };
}

export async function fetchDmPublicKey(
  apiBase: string,
  agentId: string,
): Promise<DmPublicKeyBundle | null> {
  const res = await fetch(`${apiBase}/api/mesh/dm/pubkey?agent_id=${encodeURIComponent(agentId)}`);
  const data = await res.json();
  return data.ok ? data : null;
}

function spreadClaimPositions(totalClaims: number, spreadClaims: number): Set<number> {
  if (spreadClaims <= 0) return new Set();
  const positions = new Set<number>();
  for (let index = 0; index < spreadClaims; index += 1) {
    const position = Math.floor(((index + 0.5) * totalClaims) / spreadClaims);
    positions.add(Math.min(totalClaims - 1, position));
  }
  return positions;
}

function interleaveSharedClaims(realTokens: string[], decoyTokens: string[]): MailboxClaim[] {
  const totalClaims = realTokens.length + decoyTokens.length;
  if (!totalClaims) return [];
  const spreadRealTokens = realTokens.length > 0 && realTokens.length <= decoyTokens.length;
  const spreadTokens = spreadRealTokens ? realTokens : decoyTokens;
  const fillTokens = spreadRealTokens ? decoyTokens : realTokens;
  const spreadTokenPositions = spreadClaimPositions(totalClaims, spreadTokens.length);
  const claims: MailboxClaim[] = [];
  let spreadIndex = 0;
  let fillIndex = 0;
  for (let slot = 0; slot < totalClaims; slot += 1) {
    if (spreadTokenPositions.has(slot) && spreadIndex < spreadTokens.length) {
      claims.push({ type: 'shared', token: spreadTokens[spreadIndex] });
      spreadIndex += 1;
      continue;
    }
    if (fillIndex < fillTokens.length) {
      claims.push({ type: 'shared', token: fillTokens[fillIndex] });
      fillIndex += 1;
      continue;
    }
    claims.push({ type: 'shared', token: spreadTokens[spreadIndex] });
    spreadIndex += 1;
  }
  return claims;
}

async function buildLegacySharedMailboxClaims(sharedTokens: string[]): Promise<MailboxClaim[]> {
  const claims = sharedTokens.map((token) => ({ type: 'shared' as const, token }));
  for (let index = sharedTokens.length; index < MIN_SHARED_MAILBOX_CLAIMS; index += 1) {
    claims.push({ type: 'shared', token: await mailboxDecoySharedToken(index) });
  }
  return claims;
}

function sharedClaimBucketSize(realSharedClaims: number): number | null {
  if (!MAILBOX_SHARED_CLAIM_EXPERIMENT_ENABLED) {
    return null;
  }
  if (realSharedClaims > MAX_SHARED_MAILBOX_CLAIMS) {
    return null;
  }
  return (
    MAILBOX_SHARED_CLAIM_BUCKETS.find((bucketSize) => realSharedClaims <= bucketSize) ??
    MAX_SHARED_MAILBOX_CLAIMS
  );
}

async function buildBucketedSharedMailboxClaims(sharedTokens: string[]): Promise<MailboxClaim[]> {
  const bucketSize = sharedClaimBucketSize(sharedTokens.length);
  if (bucketSize == null) {
    return buildLegacySharedMailboxClaims(sharedTokens);
  }
  const decoyTokens: string[] = [];
  for (let index = 0; index < bucketSize - sharedTokens.length; index += 1) {
    decoyTokens.push(await mailboxDecoySharedToken(index));
  }
  return interleaveSharedClaims(sharedTokens, decoyTokens);
}

export async function buildMailboxClaims(contacts: Record<string, Contact>): Promise<MailboxClaim[]> {
  const identity = getNodeIdentity();
  if (!identity?.nodeId) {
    throw new Error('No local identity available for mailbox claims');
  }
  const claims: MailboxClaim[] = [
    {
      type: 'self',
      token: await mailboxClaimToken('self', identity.nodeId),
    },
    {
      type: 'requests',
      token: await mailboxClaimToken('requests', identity.nodeId),
    },
  ];
  const sharedTokens = Array.from(new Set((await deadDropTokensForContacts(contacts)).filter(Boolean)));
  claims.push(...(await buildBucketedSharedMailboxClaims(sharedTokens)));
  return claims;
}

async function signedMailboxRequest(
  apiBase: string,
  identity: NodeIdentity,
  eventType: 'dm_poll' | 'dm_count',
  mailboxClaims: MailboxClaim[],
) {
  const payload = {
    mailbox_claims: mailboxClaims.map((claim) => ({
      type: claim.type,
      token: claim.token || '',
    })),
    timestamp: Math.floor(Date.now() / 1000),
    nonce: randomHex(16),
  };
  const valid = validateEventPayload(eventType, payload as Record<string, JsonValue>);
  if (!valid.ok) {
    throw new Error(valid.reason);
  }
  const sequence = nextSequence();
  const signed = await signMeshEvent(eventType, payload, sequence);
  const res = await fetch(`${apiBase}/api/mesh/dm/${eventType === 'dm_poll' ? 'poll' : 'count'}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      agent_id: signed.context.nodeId,
      mailbox_claims: payload.mailbox_claims,
      timestamp: payload.timestamp,
      nonce: payload.nonce,
      public_key: signed.context.publicKey,
      public_key_algo: signed.context.publicKeyAlgo,
      signature: signed.signature,
      sequence: signed.sequence,
      protocol_version: signed.protocolVersion,
    }),
  });
  return res.json();
}

export async function pollDmMailboxes(
  apiBase: string,
  identity: NodeIdentity,
  mailboxClaims: MailboxClaim[],
): Promise<DmPollResponse> {
  return signedMailboxRequest(apiBase, identity, 'dm_poll', mailboxClaims);
}

export async function countDmMailboxes(
  apiBase: string,
  identity: NodeIdentity,
  mailboxClaims: MailboxClaim[],
): Promise<DmCountResponse> {
  return signedMailboxRequest(apiBase, identity, 'dm_count', mailboxClaims);
}

export async function buildSenderSeal(
  recipientId: string,
  recipientDhPub: string,
  msgId: string,
  timestamp: number,
): Promise<string> {
  const signingContext = await getActiveSigningContext();
  if (signingContext?.source === 'wormhole') {
    const built = await buildWormholeSenderSeal(recipientId, recipientDhPub, msgId, timestamp);
    if (!built?.ok || !built.sender_seal) {
      throw new Error('wormhole_sender_seal_failed');
    }
    return String(built.sender_seal || '');
  }
  try {
    return await createSenderSealV3(recipientId, recipientDhPub, msgId, timestamp);
  } catch {
    const sealMessage = `seal|${msgId}|${timestamp}|${recipientId}`;
    const signed = await signRawMeshMessage(sealMessage);
    const isBound = await verifyNodeIdBindingFromPublicKey(
      signed.context.publicKey,
      signed.context.nodeId,
    );
    if (!isBound) {
      throw new Error('Sender seal node binding failed');
    }
    const sealKey = await deriveSenderSealKey(recipientDhPub, recipientId, msgId);
    const encrypted = await encryptDM(
      JSON.stringify({
        seal_version: 'v2',
        sender_id: signed.context.nodeId,
        public_key: signed.context.publicKey,
        public_key_algo: signed.context.publicKeyAlgo,
        msg_id: msgId,
        timestamp,
        signature: signed.signature,
        protocol_version: signed.protocolVersion,
      }),
      sealKey,
    );
    return `v2:${encrypted}`;
  }
}

export async function sendDmMessage(request: DmSendRequest): Promise<DmSendResponse> {
  const payloadFormat = request.format || 'mls1';
  let senderSeal = '';
  let senderToken = '';
  let relaySalt = '';
  const requireCanonicalV3Seal = requiresCanonicalRequestV2SenderSeal({
    deliveryClass: request.deliveryClass,
    useSealedSender: request.useSealedSender,
  });
  if (request.useSealedSender && request.recipientDhPub) {
    senderSeal = await buildSenderSeal(
      request.recipientId,
      request.recipientDhPub,
      request.msgId,
      request.timestamp,
    );
    if (requireCanonicalV3Seal) {
      senderSeal = ensureCanonicalRequestV2SenderSeal(senderSeal);
    }
    relaySalt = randomHex(16);
  }

  const dmPayload: Record<string, unknown> = {
    recipient_id: request.recipientId,
    delivery_class: request.deliveryClass,
    recipient_token: request.recipientToken || '',
    ciphertext: request.ciphertext,
    msg_id: request.msgId,
    timestamp: request.timestamp,
    format: payloadFormat,
  };
  if (request.sessionWelcome) {
    dmPayload.session_welcome = request.sessionWelcome;
  }
  if (senderSeal) {
    dmPayload.sender_seal = senderSeal;
  }
  if (relaySalt) {
    dmPayload.relay_salt = relaySalt;
  }
  const valid = validateEventPayload('dm_message', dmPayload as Record<string, JsonValue>);
  if (!valid.ok) {
    throw new Error(valid.reason);
  }
  const sequence = nextSequence();
  const signed = await signMeshEvent('dm_message', dmPayload, sequence);
  if (senderSeal && signed.context.source === 'wormhole') {
    try {
      senderToken = takeCachedSenderToken(
        request.recipientId,
        request.deliveryClass,
        request.recipientToken || '',
      );
      if (!senderToken) {
        senderToken = await replenishSenderTokenCache(
          request.recipientId,
          request.deliveryClass,
          request.recipientToken || '',
        );
      }
      if (!senderToken) {
        const issued = await issueWormholeDmSenderToken(
          request.recipientId,
          request.deliveryClass,
          request.recipientToken || '',
        );
        senderToken = String(issued.sender_token || '');
      }
    } catch {
      senderToken = '';
    }
  }
  const res = await fetch(`${request.apiBase}/api/mesh/dm/send`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      sender_id: senderSeal && senderToken ? '' : signed.context.nodeId,
      sender_token: senderToken,
      recipient_id: senderSeal && senderToken ? '' : request.recipientId,
      delivery_class: request.deliveryClass,
      recipient_token: request.recipientToken || '',
      ciphertext: request.ciphertext,
      format: payloadFormat,
      session_welcome: request.sessionWelcome || '',
      sender_seal: senderSeal,
      relay_salt: relaySalt,
      msg_id: request.msgId,
      timestamp: request.timestamp,
      public_key: senderSeal && senderToken ? '' : signed.context.publicKey,
      public_key_algo: senderSeal && senderToken ? '' : signed.context.publicKeyAlgo,
      signature: signed.signature,
      sequence: signed.sequence,
      protocol_version: senderSeal && senderToken ? '' : signed.protocolVersion,
    }),
  });
  return res.json();
}

export async function sendOffLedgerConsentMessage(
  request: Omit<DmSendRequest, 'deliveryClass' | 'useSealedSender'>,
): Promise<DmSendResponse> {
  return sendDmMessage({
    ...request,
    deliveryClass: 'request',
    useSealedSender: true,
  });
}

export async function sharedMailboxToken(peerId: string, peerDhPub: string): Promise<string> {
  return deadDropToken(peerId, peerDhPub);
}

export function currentIdentity(): NodeIdentity | null {
  return getNodeIdentity();
}
