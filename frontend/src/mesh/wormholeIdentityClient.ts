import { controlPlaneJson } from '@/lib/controlPlane';
import {
  cacheWormholeIdentityDescriptor,
  getNodeIdentity,
  getPublicKeyAlgo,
  isSecureModeCached,
  purgeBrowserSigningMaterial,
  setSecureModeCached,
  signEvent,
  signWithStoredKey,
} from '@/mesh/meshIdentity';
import { PROTOCOL_VERSION } from '@/mesh/meshProtocol';
import { fetchWormholeSettings, fetchWormholeState } from '@/mesh/wormholeClient';

export interface WormholeIdentity {
  bootstrapped: boolean;
  bootstrapped_at: number;
  scope?: string;
  gate_id?: string;
  persona_id?: string;
  label?: string;
  node_id: string;
  public_key: string;
  public_key_algo: string;
  sequence: number;
  dh_pub_key?: string;
  dh_algo?: string;
  last_dh_timestamp?: number;
  bundle_fingerprint?: string;
  bundle_sequence?: number;
  bundle_registered_at?: number;
  created_at?: number;
  last_used_at?: number;
  protocol_version: string;
}

export interface WormholeSignedEvent {
  node_id: string;
  public_key: string;
  public_key_algo: string;
  protocol_version: string;
  sequence: number;
  payload: Record<string, unknown>;
  signature: string;
  signature_payload: string;
}

export interface WormholeSignedRawMessage {
  node_id: string;
  public_key: string;
  public_key_algo: string;
  protocol_version: string;
  signature: string;
  message: string;
}

export interface WormholeDmSenderToken {
  ok: boolean;
  sender_token: string;
  expires_at: number;
  delivery_class: string;
}

export interface WormholeDmSenderTokenBatch {
  ok: boolean;
  delivery_class: string;
  tokens: Array<{ sender_token: string; expires_at: number }>;
}

export interface WormholeOpenedSeal {
  ok: boolean;
  sender_id: string;
  seal_verified: boolean;
  public_key?: string;
  public_key_algo?: string;
  timestamp?: number;
  msg_id?: string;
}

export interface WormholeBuiltSeal {
  ok: boolean;
  sender_seal: string;
  sender_id?: string;
  public_key?: string;
  public_key_algo?: string;
  protocol_version?: string;
}

export interface WormholeDeadDropTokenPair {
  ok: boolean;
  peer_id: string;
  epoch: number;
  current: string;
  previous: string;
}

export interface WormholePairwiseAlias {
  ok: boolean;
  peer_id: string;
  shared_alias: string;
  replaced_alias?: string;
  dm_identity_id?: string;
  identity_scope?: string;
  contact?: Record<string, unknown>;
}

export interface WormholeRotatedPairwiseAlias {
  ok: boolean;
  peer_id: string;
  active_alias: string;
  pending_alias: string;
  grace_until: number;
  dm_identity_id?: string;
  identity_scope?: string;
  contact?: Record<string, unknown>;
  rotated?: boolean;
}

export interface WormholeDeadDropTokensBatch {
  ok: boolean;
  tokens: Array<{ peer_id: string; current: string; previous: string; epoch: number }>;
}

export interface WormholeSasPhrase {
  ok: boolean;
  peer_id: string;
  phrase: string;
  words: number;
}

export interface WormholeGatePersonasResponse {
  ok: boolean;
  gate_id: string;
  active_persona_id: string;
  personas: WormholeIdentity[];
}

export interface WormholeComposedGateMessage {
  ok: boolean;
  gate_id: string;
  identity_scope?: string;
  sender_id: string;
  public_key: string;
  public_key_algo: string;
  protocol_version: string;
  sequence: number;
  signature: string;
  epoch: number;
  ciphertext: string;
  nonce: string;
  sender_ref: string;
  format: string;
  key_commitment?: string;
  detail?: string;
}

export interface WormholeDecryptedGateMessage {
  ok: boolean;
  gate_id: string;
  epoch: number;
  plaintext: string;
  identity_scope?: string;
  detail?: string;
  self_authored?: boolean;
  legacy?: boolean;
}

export interface WormholeGateDecryptPayload {
  gate_id: string;
  epoch?: number;
  ciphertext: string;
  nonce?: string;
  sender_ref?: string;
  format?: string;
  gate_envelope?: string;
}

export interface WormholeDecryptedGateMessageBatch {
  ok: boolean;
  detail?: string;
  results: WormholeDecryptedGateMessage[];
}

export interface WormholeGateKeyStatus {
  ok: boolean;
  gate_id: string;
  current_epoch: number;
  previous_epoch?: number;
  key_commitment?: string;
  previous_key_commitment?: string;
  identity_scope?: string;
  identity_node_id?: string;
  sender_ref?: string;
  has_local_access?: boolean;
  rekey_recommended?: boolean;
  rekey_recommended_reason?: string;
  rekey_recommended_at?: number;
  last_rotated_at?: number;
  last_rotation_reason?: string;
  detail?: string;
}

export interface WormholeDmContactsResponse {
  ok: boolean;
  contacts: Record<string, Record<string, unknown>>;
}

export interface WormholeStatusSnapshot {
  ready?: boolean;
  running?: boolean;
  transport_tier?: string;
  transport_active?: string;
  transport_configured?: string;
  arti_ready?: boolean;
  anonymous_mode?: boolean;
  anonymous_mode_ready?: boolean;
  rns_enabled?: boolean;
  rns_ready?: boolean;
  rns_configured_peers?: number;
  rns_active_peers?: number;
  rns_private_dm_direct_ready?: boolean;
  recent_private_clearnet_fallback?: boolean;
  recent_private_clearnet_fallback_at?: number;
  recent_private_clearnet_fallback_reason?: string;
}

export interface ActiveSigningContext {
  source: 'wormhole' | 'browser';
  nodeId: string;
  publicKey: string;
  publicKeyAlgo: string;
}

let wormholeIdentityCache: { value: WormholeIdentity; ts: number } | null = null;
const CACHE_TTL_MS = 3000;

function getBrowserSigningContext(): ActiveSigningContext | null {
  const identity = getNodeIdentity();
  if (!identity) return null;
  return {
    source: 'browser',
    nodeId: identity.nodeId,
    publicKey: identity.publicKey,
    publicKeyAlgo: getPublicKeyAlgo(),
  };
}

export async function isWormholeReady(): Promise<boolean> {
  try {
    return Boolean((await fetchWormholeState()).ready);
  } catch {
    return false;
  }
}

export async function fetchWormholeStatus(): Promise<WormholeStatusSnapshot> {
  return (await fetchWormholeState()) as WormholeStatusSnapshot;
}

export async function isWormholeSecureRequired(): Promise<boolean> {
  try {
    const data = await fetchWormholeSettings();
    const value = Boolean(data?.enabled);
    setSecureModeCached(value);
    return value;
  } catch (error) {
    console.warn(
      '[mesh] Wormhole secure-mode status unavailable, keeping cached boundary',
      error,
    );
    return isSecureModeCached();
  }
}

export async function ensureWormholeReadyForSecureAction(action: string): Promise<void> {
  const required = await isWormholeSecureRequired();
  if (!required) return;
  const ready = await isWormholeReady();
  if (!ready) {
    throw new Error(`wormhole_required_for_${action}`);
  }
}

export async function fetchWormholeIdentity(): Promise<WormholeIdentity> {
  const now = Date.now();
  if (wormholeIdentityCache && now - wormholeIdentityCache.ts < CACHE_TTL_MS) {
    return wormholeIdentityCache.value;
  }
  const value = await controlPlaneJson<WormholeIdentity>('/api/wormhole/identity', {
    requireAdminSession: false,
  });
  cacheWormholeIdentityDescriptor({
    nodeId: value.node_id,
    publicKey: value.public_key,
    publicKeyAlgo: value.public_key_algo,
  });
  await purgeBrowserSigningMaterial();
  wormholeIdentityCache = { value, ts: now };
  return value;
}

export async function bootstrapWormholeIdentity(): Promise<WormholeIdentity> {
  const value = await controlPlaneJson<WormholeIdentity>('/api/wormhole/identity/bootstrap', {
    requireAdminSession: false,
    method: 'POST',
  });
  cacheWormholeIdentityDescriptor({
    nodeId: value.node_id,
    publicKey: value.public_key,
    publicKeyAlgo: value.public_key_algo,
  });
  await purgeBrowserSigningMaterial();
  return value;
}

export async function signViaWormhole(
  eventType: string,
  payload: Record<string, unknown>,
  sequence?: number,
  gateId?: string,
): Promise<WormholeSignedEvent> {
  return controlPlaneJson<WormholeSignedEvent>('/api/wormhole/sign', {
    requireAdminSession: false,
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      event_type: eventType,
      payload,
      sequence,
      gate_id: gateId || '',
    }),
  });
}

export async function enterWormholeGate(
  gateId: string,
  rotate: boolean = false,
): Promise<{ ok: boolean; identity?: WormholeIdentity; detail?: string }> {
  return controlPlaneJson<{ ok: boolean; identity?: WormholeIdentity; detail?: string }>(
    '/api/wormhole/gate/enter',
    {
      requireAdminSession: false,
      capabilityIntent: 'wormhole_gate_persona',
      sessionProfileHint: 'gate_operator',
      enforceProfileHint: true,
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        gate_id: gateId,
        rotate,
      }),
    },
  );
}

export async function leaveWormholeGate(
  gateId: string,
): Promise<{ ok: boolean; gate_id?: string; cleared?: boolean; detail?: string }> {
  return controlPlaneJson<{ ok: boolean; gate_id?: string; cleared?: boolean; detail?: string }>(
    '/api/wormhole/gate/leave',
    {
      requireAdminSession: false,
      capabilityIntent: 'wormhole_gate_persona',
      sessionProfileHint: 'gate_operator',
      enforceProfileHint: true,
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        gate_id: gateId,
      }),
    },
  );
}

export async function listWormholeGatePersonas(
  gateId: string,
): Promise<WormholeGatePersonasResponse> {
  return controlPlaneJson<WormholeGatePersonasResponse>(
    `/api/wormhole/gate/${encodeURIComponent(gateId)}/personas`,
    {
      requireAdminSession: false,
      capabilityIntent: 'wormhole_gate_persona',
      sessionProfileHint: 'gate_operator',
      enforceProfileHint: true,
    },
  );
}

export async function createWormholeGatePersona(
  gateId: string,
  label: string,
): Promise<{ ok: boolean; identity?: WormholeIdentity; detail?: string }> {
  return controlPlaneJson<{ ok: boolean; identity?: WormholeIdentity; detail?: string }>(
    '/api/wormhole/gate/persona/create',
    {
      requireAdminSession: false,
      capabilityIntent: 'wormhole_gate_persona',
      sessionProfileHint: 'gate_operator',
      enforceProfileHint: true,
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        gate_id: gateId,
        label,
      }),
    },
  );
}

export async function activateWormholeGatePersona(
  gateId: string,
  personaId: string,
): Promise<{ ok: boolean; identity?: WormholeIdentity; detail?: string }> {
  return controlPlaneJson<{ ok: boolean; identity?: WormholeIdentity; detail?: string }>(
    '/api/wormhole/gate/persona/activate',
    {
      requireAdminSession: false,
      capabilityIntent: 'wormhole_gate_persona',
      sessionProfileHint: 'gate_operator',
      enforceProfileHint: true,
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        gate_id: gateId,
        persona_id: personaId,
      }),
    },
  );
}

export async function clearWormholeGatePersona(
  gateId: string,
): Promise<{ ok: boolean; identity?: WormholeIdentity; detail?: string }> {
  return controlPlaneJson<{ ok: boolean; identity?: WormholeIdentity; detail?: string }>(
    '/api/wormhole/gate/persona/clear',
    {
      requireAdminSession: false,
      capabilityIntent: 'wormhole_gate_persona',
      sessionProfileHint: 'gate_operator',
      enforceProfileHint: true,
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        gate_id: gateId,
      }),
    },
  );
}

export async function retireWormholeGatePersona(
  gateId: string,
  personaId: string,
): Promise<{
  ok: boolean;
  retired_persona_id?: string;
  retired_identity?: WormholeIdentity;
  active_identity?: WormholeIdentity;
  detail?: string;
}> {
  return controlPlaneJson<{
    ok: boolean;
    retired_persona_id?: string;
    retired_identity?: WormholeIdentity;
    active_identity?: WormholeIdentity;
    detail?: string;
  }>('/api/wormhole/gate/persona/retire', {
    requireAdminSession: false,
    capabilityIntent: 'wormhole_gate_persona',
    sessionProfileHint: 'gate_operator',
    enforceProfileHint: true,
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      gate_id: gateId,
      persona_id: personaId,
    }),
  });
}

export async function composeWormholeGateMessage(
  gateId: string,
  plaintext: string,
): Promise<WormholeComposedGateMessage> {
  return controlPlaneJson<WormholeComposedGateMessage>('/api/wormhole/gate/message/compose', {
    requireAdminSession: false,
    capabilityIntent: 'wormhole_gate_content',
    sessionProfileHint: 'gate_operator',
    enforceProfileHint: true,
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      gate_id: gateId,
      plaintext,
    }),
  });
}

export async function fetchWormholeGateKeyStatus(
  gateId: string,
): Promise<WormholeGateKeyStatus> {
  return controlPlaneJson<WormholeGateKeyStatus>(
    `/api/wormhole/gate/${encodeURIComponent(gateId)}/key`,
    {
      requireAdminSession: false,
      capabilityIntent: 'wormhole_gate_key',
      sessionProfileHint: 'gate_operator',
      enforceProfileHint: true,
    },
  );
}

export async function rotateWormholeGateKey(
  gateId: string,
  reason: string = 'manual_rotate',
): Promise<WormholeGateKeyStatus & { rotated?: boolean; rotation_reason?: string }> {
  return controlPlaneJson<WormholeGateKeyStatus & { rotated?: boolean; rotation_reason?: string }>(
    '/api/wormhole/gate/key/rotate',
    {
      requireAdminSession: false,
      capabilityIntent: 'wormhole_gate_key',
      sessionProfileHint: 'gate_operator',
      enforceProfileHint: true,
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        gate_id: gateId,
        reason,
      }),
    },
  );
}

export async function decryptWormholeGateMessage(
  gateId: string,
  epoch: number,
  ciphertext: string,
  nonce: string,
  senderRef: string,
): Promise<WormholeDecryptedGateMessage> {
  return controlPlaneJson<WormholeDecryptedGateMessage>('/api/wormhole/gate/message/decrypt', {
    requireAdminSession: false,
    capabilityIntent: 'wormhole_gate_content',
    sessionProfileHint: 'gate_operator',
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      gate_id: gateId,
      epoch,
      ciphertext,
      nonce,
      sender_ref: senderRef,
    }),
  });
}

export async function decryptWormholeGateMessages(
  messages: WormholeGateDecryptPayload[],
): Promise<WormholeDecryptedGateMessageBatch> {
  return controlPlaneJson<WormholeDecryptedGateMessageBatch>('/api/wormhole/gate/messages/decrypt', {
    requireAdminSession: false,
    capabilityIntent: 'wormhole_gate_content',
    sessionProfileHint: 'gate_operator',
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      messages: messages.map((message) => ({
        gate_id: message.gate_id,
        epoch: Number(message.epoch || 0),
        ciphertext: message.ciphertext,
        nonce: message.nonce || '',
        sender_ref: message.sender_ref || '',
        format: message.format || 'mls1',
        gate_envelope: message.gate_envelope || '',
      })),
    }),
  });
}

export async function signRawViaWormhole(message: string): Promise<WormholeSignedRawMessage> {
  return controlPlaneJson<WormholeSignedRawMessage>('/api/wormhole/sign-raw', {
    requireAdminSession: false,
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message }),
  });
}

export async function registerWormholeDmKey(): Promise<WormholeIdentity & { ok: boolean; detail?: string }> {
  return controlPlaneJson<WormholeIdentity & { ok: boolean; detail?: string }>(
    '/api/wormhole/dm/register-key',
    {
    method: 'POST',
    },
  );
}

export async function issueWormholeDmSenderToken(
  recipientId: string,
  deliveryClass: 'request' | 'shared',
  recipientToken?: string,
): Promise<WormholeDmSenderToken> {
  return controlPlaneJson<WormholeDmSenderToken>('/api/wormhole/dm/sender-token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      recipient_id: recipientId,
      delivery_class: deliveryClass,
      recipient_token: recipientToken || '',
    }),
  });
}

export async function issueWormholeDmSenderTokens(
  recipientId: string,
  deliveryClass: 'request' | 'shared',
  recipientToken?: string,
  count: number = 3,
): Promise<WormholeDmSenderTokenBatch> {
  return controlPlaneJson<WormholeDmSenderTokenBatch>('/api/wormhole/dm/sender-token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      recipient_id: recipientId,
      delivery_class: deliveryClass,
      recipient_token: recipientToken || '',
      count,
    }),
  });
}

export async function openWormholeSenderSeal(
  senderSeal: string,
  candidateDhPub: string,
  recipientId: string,
  expectedMsgId: string,
): Promise<WormholeOpenedSeal> {
  return controlPlaneJson<WormholeOpenedSeal>('/api/wormhole/dm/open-seal', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      sender_seal: senderSeal,
      candidate_dh_pub: candidateDhPub,
      recipient_id: recipientId,
      expected_msg_id: expectedMsgId,
    }),
  });
}

export async function buildWormholeSenderSeal(
  recipientId: string,
  recipientDhPub: string,
  msgId: string,
  timestamp: number,
): Promise<WormholeBuiltSeal> {
  return controlPlaneJson<WormholeBuiltSeal>('/api/wormhole/dm/build-seal', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      recipient_id: recipientId,
      recipient_dh_pub: recipientDhPub,
      msg_id: msgId,
      timestamp,
    }),
  });
}

export async function deriveWormholeDeadDropTokenPair(
  peerId: string,
  peerDhPub: string,
): Promise<WormholeDeadDropTokenPair> {
  return controlPlaneJson<WormholeDeadDropTokenPair>('/api/wormhole/dm/dead-drop-token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      peer_id: peerId,
      peer_dh_pub: peerDhPub,
    }),
  });
}

export async function issueWormholePairwiseAlias(
  peerId: string,
  peerDhPub: string,
): Promise<WormholePairwiseAlias> {
  return controlPlaneJson<WormholePairwiseAlias>('/api/wormhole/dm/pairwise-alias', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      peer_id: peerId,
      peer_dh_pub: peerDhPub,
    }),
  });
}

export async function rotateWormholePairwiseAlias(
  peerId: string,
  peerDhPub: string,
  graceMs: number,
): Promise<WormholeRotatedPairwiseAlias> {
  return controlPlaneJson<WormholeRotatedPairwiseAlias>('/api/wormhole/dm/pairwise-alias/rotate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      peer_id: peerId,
      peer_dh_pub: peerDhPub,
      grace_ms: graceMs,
    }),
  });
}

export async function deriveWormholeDeadDropTokens(
  contacts: Array<{ peer_id: string; peer_dh_pub: string }>,
  limit: number = 24,
): Promise<WormholeDeadDropTokensBatch> {
  return controlPlaneJson<WormholeDeadDropTokensBatch>('/api/wormhole/dm/dead-drop-tokens', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      contacts,
      limit,
    }),
  });
}

export async function deriveWormholeSasPhrase(
  peerId: string,
  peerDhPub: string,
  words: number = 8,
): Promise<WormholeSasPhrase> {
  return controlPlaneJson<WormholeSasPhrase>('/api/wormhole/dm/sas', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      peer_id: peerId,
      peer_dh_pub: peerDhPub,
      words,
    }),
  });
}

export async function listWormholeDmContacts(): Promise<WormholeDmContactsResponse> {
  return controlPlaneJson<WormholeDmContactsResponse>('/api/wormhole/dm/contacts');
}

export async function putWormholeDmContact(
  peerId: string,
  contact: Record<string, unknown>,
): Promise<{ ok: boolean; peer_id: string; contact: Record<string, unknown> }> {
  return controlPlaneJson('/api/wormhole/dm/contact', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      peer_id: peerId,
      contact,
    }),
  });
}

export async function deleteWormholeDmContact(
  peerId: string,
): Promise<{ ok: boolean; peer_id: string; deleted: boolean }> {
  return controlPlaneJson(`/api/wormhole/dm/contact/${encodeURIComponent(peerId)}`, {
    method: 'DELETE',
  });
}

export async function getActiveSigningContext(): Promise<ActiveSigningContext | null> {
  const secureRequired = await isWormholeSecureRequired();
  if (await isWormholeReady()) {
    const identity = await fetchWormholeIdentity();
    if (identity?.node_id && identity?.public_key) {
      return {
        source: 'wormhole',
        nodeId: identity.node_id,
        publicKey: identity.public_key,
        publicKeyAlgo: identity.public_key_algo,
      };
    }
  }
  if (secureRequired) {
    return null;
  }
  return getBrowserSigningContext();
}

export async function signMeshEvent(
  eventType: string,
  payload: Record<string, unknown>,
  sequence: number,
  options?: { gateId?: string },
): Promise<{ signature: string; context: ActiveSigningContext; protocolVersion: string; sequence: number }> {
  await ensureWormholeReadyForSecureAction(`sign_${eventType}`);
  const context = await getActiveSigningContext();
  if (!context) {
    throw new Error('No identity available for signing');
  }
  if (context.source === 'wormhole') {
    try {
      const signed = await signViaWormhole(
        eventType,
        payload,
        sequence,
        options?.gateId,
      );
      return {
        signature: signed.signature,
        context: {
          source: 'wormhole',
          nodeId: signed.node_id,
          publicKey: signed.public_key,
          publicKeyAlgo: signed.public_key_algo,
        },
        protocolVersion: signed.protocol_version,
        sequence: signed.sequence,
      };
    } catch {
      if (await isWormholeSecureRequired()) {
        throw new Error(`wormhole_sign_failed_${eventType}`);
      }
      console.warn(
        '[PRIVACY] Wormhole signing failed for %s — falling back to browser-side signing. ' +
          'Private key material is active in browser memory. Enable secure mode to block this fallback.',
        eventType,
      );
      if (typeof window !== 'undefined') {
        window.dispatchEvent(new CustomEvent('sb:signing-fallback', { detail: { eventType } }));
      }
      const browserContext = getBrowserSigningContext();
      if (!browserContext) throw new Error('No identity available for signing');
      return {
        signature: await signEvent(eventType, browserContext.nodeId, sequence, payload),
        context: browserContext,
        protocolVersion: PROTOCOL_VERSION,
        sequence,
      };
    }
  }
  return {
    signature: await signEvent(eventType, context.nodeId, sequence, payload),
    context,
    protocolVersion: PROTOCOL_VERSION,
    sequence,
  };
}

export async function signRawMeshMessage(
  message: string,
): Promise<{ signature: string; context: ActiveSigningContext; protocolVersion: string }> {
  await ensureWormholeReadyForSecureAction('sign_raw');
  const context = await getActiveSigningContext();
  if (!context) {
    throw new Error('No identity available for signing');
  }
  if (context.source === 'wormhole') {
    try {
      const signed = await signRawViaWormhole(message);
      return {
        signature: signed.signature,
        context: {
          source: 'wormhole',
          nodeId: signed.node_id,
          publicKey: signed.public_key,
          publicKeyAlgo: signed.public_key_algo,
        },
        protocolVersion: signed.protocol_version,
      };
    } catch {
      if (await isWormholeSecureRequired()) {
        throw new Error('wormhole_sign_raw_failed');
      }
      console.warn(
        '[PRIVACY] Wormhole raw signing failed — falling back to browser-side signing. ' +
          'Private key material is active in browser memory. Enable secure mode to block this fallback.',
      );
      if (typeof window !== 'undefined') {
        window.dispatchEvent(
          new CustomEvent('sb:signing-fallback', { detail: { eventType: 'sign_raw' } }),
        );
      }
      const identity = getNodeIdentity();
      if (!identity) throw new Error('No identity available for signing');
      const sig = await signWithStoredKey(message).catch(() => {
        throw new Error('browser_signing_key_unavailable');
      });
      return {
        signature: sig,
        context: {
          source: 'browser',
          nodeId: identity.nodeId,
          publicKey: identity.publicKey,
          publicKeyAlgo: getPublicKeyAlgo(),
        },
        protocolVersion: PROTOCOL_VERSION,
      };
    }
  }
  const identity = getNodeIdentity();
  if (!identity) throw new Error('No identity available for signing');
  const sig = await signWithStoredKey(message).catch(() => {
    throw new Error('browser_signing_key_unavailable');
  });
  return {
    signature: sig,
    context,
    protocolVersion: PROTOCOL_VERSION,
  };
}
