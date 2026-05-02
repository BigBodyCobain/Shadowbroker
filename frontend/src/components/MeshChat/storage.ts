import {
  loadIdentityBoundSensitiveValue,
  persistIdentityBoundSensitiveValue,
} from '@/lib/identityBoundSensitiveStorage';
import {
  decryptSenderSealPayloadLocally,
  getNodeIdentity,
  unwrapSenderSealPayload,
  verifyNodeIdBindingFromPublicKey,
  verifyRawSignature,
} from '@/mesh/meshIdentity';
import type { Contact } from '@/mesh/meshIdentity';
import {
  isWormholeReady,
  openWormholeSenderSeal,
} from '@/mesh/wormholeIdentityClient';
import {
  recoverSenderSealWithFallback,
} from '@/mesh/requestSenderRecovery';
import { allDmPeerIds, mergeAliasHistory } from '@/mesh/meshDmConsent';
import type { AccessRequest } from './types';

// ─── Local storage keys ─────────────────────────────────────────────────────

const ACCESS_REQUESTS_KEY = 'sb_dm_access_requests';
const PENDING_SENT_KEY = 'sb_dm_pending_sent';
const MUTED_KEY = 'sb_mesh_muted';
const GEO_HINT_KEY = 'sb_dm_geo_hint';
const ACCESS_REQ_WRAP_INFO = 'SB-ACCESS-REQUESTS-STORAGE-V1';
const PENDING_WRAP_INFO = 'SB-PENDING-CONTACTS-STORAGE-V1';
const MUTED_WRAP_INFO = 'SB-MUTED-LIST-V1';

export const DECOY_KEY = 'sb_dm_decoy';

// ─── Scoped state helpers ───────────────────────────────────────────────────

export function scopedDmStateKey(base: string, nodeId?: string): string {
  const resolved = String(nodeId || getNodeIdentity()?.nodeId || 'global').trim() || 'global';
  return `${base}:${resolved}`;
}

export async function getAccessRequests(nodeId?: string): Promise<AccessRequest[]> {
  const storageKey = scopedDmStateKey(ACCESS_REQUESTS_KEY, nodeId);
  try {
    const requests = await loadIdentityBoundSensitiveValue<AccessRequest[]>(
      storageKey,
      ACCESS_REQ_WRAP_INFO,
      [],
    );
    const normalized = Array.isArray(requests) ? requests : [];
    return normalized;
  } catch (error) {
    console.warn('[mesh] failed to read encrypted access requests', error);
    return [];
  }
}

export function setAccessRequests(reqs: AccessRequest[], nodeId?: string) {
  const storageKey = scopedDmStateKey(ACCESS_REQUESTS_KEY, nodeId);
  void (async () => {
    try {
      await persistIdentityBoundSensitiveValue(storageKey, ACCESS_REQ_WRAP_INFO, reqs);
    } catch (error) {
      console.warn('[mesh] failed to persist encrypted access requests', error);
    }
  })();
}

export async function getPendingSent(nodeId?: string): Promise<string[]> {
  const storageKey = scopedDmStateKey(PENDING_SENT_KEY, nodeId);
  try {
    const pending = await loadIdentityBoundSensitiveValue<string[]>(storageKey, PENDING_WRAP_INFO, []);
    const normalized = Array.isArray(pending) ? pending : [];
    return normalized;
  } catch (error) {
    console.warn('[mesh] failed to read encrypted pending contacts', error);
    return [];
  }
}

export function setPendingSent(ids: string[], nodeId?: string) {
  const storageKey = scopedDmStateKey(PENDING_SENT_KEY, nodeId);
  void (async () => {
    try {
      await persistIdentityBoundSensitiveValue(storageKey, PENDING_WRAP_INFO, ids);
    } catch (error) {
      console.warn('[mesh] failed to persist encrypted pending contacts', error);
    }
  })();
}

export function getGeoHintEnabled(): boolean {
  try {
    return localStorage.getItem(GEO_HINT_KEY) === 'true';
  } catch {
    return false;
  }
}

export function setGeoHintEnabled(value: boolean) {
  localStorage.setItem(GEO_HINT_KEY, value ? 'true' : 'false');
}

export function getDecoyEnabled(): boolean {
  try {
    return localStorage.getItem(DECOY_KEY) === 'true';
  } catch {
    return false;
  }
}

export function setDecoyEnabled(value: boolean) {
  localStorage.setItem(DECOY_KEY, value ? 'true' : 'false');
}

export async function getMutedList(nodeId?: string): Promise<string[]> {
  const storageKey = scopedDmStateKey(MUTED_KEY, nodeId);
  try {
    const muted = await loadIdentityBoundSensitiveValue<string[]>(
      storageKey,
      MUTED_WRAP_INFO,
      [],
      { legacyKey: MUTED_KEY },
    );
    const normalized = Array.isArray(muted) ? muted : [];
    return normalized;
  } catch {
    return [];
  }
}

export function saveMutedList(ids: string[], nodeId?: string) {
  const storageKey = scopedDmStateKey(MUTED_KEY, nodeId);
  void (async () => {
    try {
      await persistIdentityBoundSensitiveValue(storageKey, MUTED_WRAP_INFO, ids, {
        legacyKey: MUTED_KEY,
      });
    } catch {
      /* ignore */
    }
  })();
}

// ─── Sender seal decryption ─────────────────────────────────────────────────

export async function decryptSenderSeal(
  senderSeal: string,
  candidateDhPub: string,
  recipientId: string,
  expectedMsgId: string,
): Promise<{ sender_id: string; seal_verified: boolean } | null> {
  const openLocal = async (): Promise<{ sender_id: string; seal_verified: boolean } | null> => {
    try {
      const sealEnvelope = unwrapSenderSealPayload(senderSeal);
      const sealText = await decryptSenderSealPayloadLocally(
        senderSeal,
        candidateDhPub,
        recipientId,
        expectedMsgId,
      );
      if (!sealText) {
        return null;
      }
      const seal = JSON.parse(sealText || '{}');
      const senderId = String(seal.sender_id || '');
      const publicKey = String(seal.public_key || '');
      const publicKeyAlgo = String(seal.public_key_algo || '');
      const sealMsgId = String(seal.msg_id || '');
      const sealTs = Number(seal.timestamp || 0);
      const signature = String(seal.signature || '');
      if (!senderId || !publicKey || !publicKeyAlgo || !sealMsgId || !signature) {
        return null;
      }
      if (sealMsgId !== expectedMsgId) {
        return null;
      }
      const isBound = await verifyNodeIdBindingFromPublicKey(publicKey, senderId);
      if (!isBound) {
        return { sender_id: senderId, seal_verified: false };
      }
      const sealMessage =
        sealEnvelope.version === 'v3'
          ? `seal|v3|${sealMsgId}|${sealTs}|${recipientId}|${String(sealEnvelope.ephemeralPub || '')}`
          : `seal|${sealMsgId}|${sealTs}|${recipientId}`;
      const verified = await verifyRawSignature({
        message: sealMessage,
        signature,
        publicKey,
        publicKeyAlgo,
      });
      return { sender_id: senderId, seal_verified: verified };
    } catch {
      return null;
    }
  };

  const openHelper = async (): Promise<{ sender_id: string; seal_verified: boolean } | null> => {
    const opened = await openWormholeSenderSeal(
      senderSeal,
      candidateDhPub,
      recipientId,
      expectedMsgId,
    );
    return {
      sender_id: String(opened.sender_id || ''),
      seal_verified: Boolean(opened.seal_verified),
    };
  };

  return recoverSenderSealWithFallback({
    wormholeReady: await isWormholeReady(),
    openLocal,
    openHelper,
  });
}

export async function decryptSenderSealForContact(
  senderSeal: string,
  candidateDhPub: string,
  contact: Contact | undefined,
  ownNodeId: string,
  expectedMsgId: string,
): Promise<{ sender_id: string; seal_verified: boolean } | null> {
  for (const recipientId of allDmPeerIds(ownNodeId, { sharedAlias: contact?.sharedAlias })) {
    const opened = await decryptSenderSeal(senderSeal, candidateDhPub, recipientId, expectedMsgId);
    if (opened) return opened;
  }
  return null;
}

export interface AliasDelta {
  updates: Partial<Contact>;
  promoted: Contact;
}

export function promotePendingAlias(contactId: string, contact: Contact | undefined): { delta: AliasDelta; promoted: Contact } | null {
  if (!contact?.pendingSharedAlias) return null;
  const graceUntil = Number(contact.sharedAliasGraceUntil || 0);
  if (graceUntil > Date.now()) return null;
  const nextAlias = String(contact.pendingSharedAlias || '').trim();
  const currentAlias = String(contact.sharedAlias || '').trim();
  const updates: Partial<Contact> = {
    sharedAlias: nextAlias || currentAlias,
    pendingSharedAlias: undefined,
    sharedAliasGraceUntil: undefined,
    sharedAliasRotatedAt: Date.now(),
    previousSharedAliases: mergeAliasHistory([
      currentAlias,
      ...(contact.previousSharedAliases || []),
    ]),
  };
  const promoted: Contact = { ...contact, ...updates } as Contact;
  return { delta: { updates, promoted }, promoted };
}
