/**
 * Sovereign Node Identity — Ed25519/ECDSA keypair for mesh authentication.
 *
 * Every ShadowBroker node generates a keypair locally. The public key becomes
 * the Node ID. The private key never leaves the device. All outbound messages
 * are signed with the private key.
 *
 * No registration. No server. No email. You just exist.
 */

import { buildSignaturePayload, PROTOCOL_VERSION, type JsonValue } from '@/mesh/meshProtocol';
import { deleteKey, getKey, setKey } from '@/mesh/meshKeyStore';
import { purgeMailboxClaimKey } from '@/mesh/meshMailbox';
import { controlPlaneJson } from '@/lib/controlPlane';

// storage keys
const KEY_PUBKEY = 'sb_mesh_pubkey';
const KEY_PRIVKEY = 'sb_mesh_privkey';
const KEY_NODE_ID = 'sb_mesh_node_id';
const KEY_SOVEREIGNTY = 'sb_mesh_sovereignty_accepted';
const KEY_WORMHOLE_PUBKEY = 'sb_wormhole_desc_pubkey';
const KEY_WORMHOLE_NODE_ID = 'sb_wormhole_desc_node_id';
const KEY_WORMHOLE_ALGO = 'sb_wormhole_desc_algo';
const KEY_DH_PUBKEY = 'sb_mesh_dh_pubkey';
const KEY_DH_PRIVKEY = 'sb_mesh_dh_privkey';
const KEY_DH_ALGO = 'sb_mesh_dh_algo';
const KEY_DH_LAST_ROTATION = 'sb_mesh_dh_last_ts';
const KEY_DH_PRIV_IDB = 'sb_mesh_dh_priv';
const KEY_DH_PREV_PRIV_IDB = 'sb_mesh_dh_prev_priv';
const KEY_SIGN_PRIV_IDB = 'sb_mesh_sign_priv';
const KEY_CONTACTS = 'sb_mesh_contacts';
const KEY_DM_NOTIFY = 'sb_mesh_dm_notify';
const KEY_DM_BUNDLE_FINGERPRINT = 'sb_dm_bundle_fingerprint';
const KEY_DM_BUNDLE_SEQUENCE = 'sb_dm_bundle_sequence';
const KEY_RATCHET = 'sb_mesh_dm_ratchet';
const KEY_RATCHET_TELEMETRY = 'sb_mesh_ratchet_telemetry';
const KEY_SEQUENCE = 'sb_mesh_sequence';
const KEY_SESSION_MODE = 'sb_mesh_session_mode';
const KEY_ALGO = 'sb_mesh_algo';
const KEY_WORMHOLE_SECURE_REQUIRED = 'sb_wormhole_secure_required';
const RATCHET_CRYPTO_DB = 'sb_mesh_ratchet_crypto';
const IDENTITY_STATE_EVENT = 'sb:identity-state-changed';
const MESH_STORAGE_PREFIXES = ['sb_mesh_', 'sb_wormhole_', 'sb_dm_'] as const;
const CONTACTS_ENCRYPTED_PREFIX = 'enc:';
const CONTACTS_WRAP_CONTEXT = 'SB-CONTACTS-WRAP-V1';
const CONTACTS_WRAP_INFO = 'SB-CONTACTS-STORAGE-V1';

function emitIdentityStateChange(): void {
  if (typeof window === 'undefined') return;
  try {
    window.dispatchEvent(new CustomEvent(IDENTITY_STATE_EVENT));
  } catch {
    /* ignore */
  }
}

function isSessionMode(): boolean {
  if (typeof window === 'undefined') return false;
  try {
    return localStorage.getItem(KEY_SESSION_MODE) !== 'false';
  } catch {
    return true;
  }
}

function getStorage(): Storage | null {
  if (typeof window === 'undefined') return null;
  try {
    return isSessionMode() ? sessionStorage : localStorage;
  } catch {
    return sessionStorage;
  }
}

function getAlternateStorage(store: Storage | null): Storage | null {
  if (typeof window === 'undefined' || !store) return null;
  return store === sessionStorage ? localStorage : sessionStorage;
}

function storageGet(key: string): string | null {
  const store = getStorage();
  if (!store) return null;
  const primaryValue = store.getItem(key);
  if (primaryValue !== null) return primaryValue;
  const alternate = getAlternateStorage(store);
  if (!alternate) return null;
  const migratedValue = alternate.getItem(key);
  if (migratedValue !== null) {
    store.setItem(key, migratedValue);
    alternate.removeItem(key);
  }
  return migratedValue;
}

function storageSet(key: string, value: string): void {
  const store = getStorage();
  if (!store) return;
  store.setItem(key, value);
  const alternate = getAlternateStorage(store);
  if (alternate) alternate.removeItem(key);
}

function storageRemove(key: string): void {
  for (const store of [localStorage, sessionStorage]) {
    try {
      store.removeItem(key);
    } catch {
      /* ignore */
    }
  }
}

function removeLegacyPrivateKeyCopies(): void {
  if (typeof window === 'undefined') return;
  for (const store of [localStorage, sessionStorage]) {
    try {
      store.removeItem(KEY_PRIVKEY);
    } catch {
      /* ignore */
    }
  }
}

function clearPrefixedStorage(store: Storage): void {
  const keys: string[] = [];
  for (let i = 0; i < store.length; i += 1) {
    const key = store.key(i);
    if (key && MESH_STORAGE_PREFIXES.some((prefix) => key.startsWith(prefix))) {
      keys.push(key);
    }
  }
  for (const key of keys) {
    try {
      store.removeItem(key);
    } catch {
      /* ignore */
    }
  }
}

async function deleteDatabaseIfPresent(name: string): Promise<void> {
  if (typeof indexedDB === 'undefined') return;
  await new Promise<void>((resolve) => {
    try {
      const req = indexedDB.deleteDatabase(name);
      req.onsuccess = () => resolve();
      req.onerror = () => resolve();
      req.onblocked = () => resolve();
    } catch {
      resolve();
    }
  });
}

export interface NodeIdentity {
  publicKey: string; // Base64-encoded public key
  privateKey: string; // Base64-encoded private key (never sent to server)
  nodeId: string; // !sb_ + first 16 hex chars of public key hash
}

export interface NodeDescriptor {
  publicKey: string;
  nodeId: string;
  publicKeyAlgo: string;
}

function isLegacyNodeId(nodeId: string): boolean {
  const value = String(nodeId || '').trim();
  return /^!sb_[0-9a-f]{8}$/i.test(value);
}

async function migrateStoredNodeIdIfLegacy(
  publicKeyBase64: string,
  nodeId: string,
  persist: (nextNodeId: string) => void,
): Promise<string> {
  const current = await deriveNodeIdFromPublicKey(publicKeyBase64);
  if (!isLegacyNodeId(nodeId) || nodeId === current) return current;
  persist(current);
  return current;
}

export function setSecureModeCached(enabled: boolean): void {
  if (typeof window === 'undefined') return;
  try {
    const nextValue = enabled ? 'true' : 'false';
    const previousValue = sessionStorage.getItem(KEY_WORMHOLE_SECURE_REQUIRED);
    sessionStorage.setItem(KEY_WORMHOLE_SECURE_REQUIRED, nextValue);
    if (previousValue !== nextValue) {
      emitIdentityStateChange();
    }
  } catch {
    /* ignore */
  }
}

export function isSecureModeCached(): boolean {
  if (typeof window === 'undefined') return false;
  try {
    return sessionStorage.getItem(KEY_WORMHOLE_SECURE_REQUIRED) === 'true';
  } catch {
    return false;
  }
}

export function cachePublicIdentity(descriptor: NodeDescriptor): void {
  if (typeof window === 'undefined') return;
  storageSet(KEY_PUBKEY, descriptor.publicKey);
  storageSet(KEY_NODE_ID, descriptor.nodeId);
  storageSet(KEY_ALGO, descriptor.publicKeyAlgo || 'Ed25519');
  storageSet(KEY_SOVEREIGNTY, 'true');
  emitIdentityStateChange();
}

export function cacheWormholeIdentityDescriptor(descriptor: NodeDescriptor): void {
  if (typeof window === 'undefined') return;
  try {
    sessionStorage.setItem(KEY_WORMHOLE_PUBKEY, descriptor.publicKey);
    sessionStorage.setItem(KEY_WORMHOLE_NODE_ID, descriptor.nodeId);
    sessionStorage.setItem(KEY_WORMHOLE_ALGO, descriptor.publicKeyAlgo || 'Ed25519');
    emitIdentityStateChange();
  } catch {
    /* ignore */
  }
}

export function getStoredNodeDescriptor(): NodeDescriptor | null {
  if (typeof window === 'undefined') return null;
  const publicKey = storageGet(KEY_PUBKEY);
  const nodeId = storageGet(KEY_NODE_ID);
  if (!publicKey || !nodeId) return null;
  return {
    publicKey,
    nodeId,
    publicKeyAlgo: storageGet(KEY_ALGO) || 'Ed25519',
  };
}

export function getWormholeIdentityDescriptor(): NodeDescriptor | null {
  if (typeof window === 'undefined') return null;
  try {
    const publicKey = sessionStorage.getItem(KEY_WORMHOLE_PUBKEY);
    const nodeId = sessionStorage.getItem(KEY_WORMHOLE_NODE_ID);
    if (!publicKey || !nodeId) return null;
    return {
      publicKey,
      nodeId,
      publicKeyAlgo: sessionStorage.getItem(KEY_WORMHOLE_ALGO) || 'Ed25519',
    };
  } catch {
    return null;
  }
}

export function clearWormholeIdentityDescriptor(): void {
  if (typeof window === 'undefined') return;
  try {
    sessionStorage.removeItem(KEY_WORMHOLE_PUBKEY);
    sessionStorage.removeItem(KEY_WORMHOLE_NODE_ID);
    sessionStorage.removeItem(KEY_WORMHOLE_ALGO);
    emitIdentityStateChange();
  } catch {
    /* ignore */
  }
}

export async function purgeBrowserSigningMaterial(): Promise<void> {
  if (typeof window === 'undefined') return;
  for (const store of [localStorage, sessionStorage]) {
    try {
      store.removeItem(KEY_PRIVKEY);
      store.removeItem(KEY_SEQUENCE);
    } catch {
      /* ignore */
    }
  }
  await deleteKey(KEY_SIGN_PRIV_IDB);
}

export function purgeBrowserContactGraph(): void {
  if (typeof window === 'undefined') return;
  contactCache = {};
  contactsHydration = null;
  for (const store of [localStorage, sessionStorage]) {
    try {
      store.removeItem(KEY_CONTACTS);
    } catch {
      /* ignore */
    }
  }
}

export async function clearBrowserIdentityState(): Promise<void> {
  if (typeof window === 'undefined') return;
  contactCache = {};
  contactsHydration = null;
  for (const store of [localStorage, sessionStorage]) {
    try {
      store.removeItem(KEY_PUBKEY);
      store.removeItem(KEY_PRIVKEY);
      store.removeItem(KEY_NODE_ID);
      store.removeItem(KEY_SOVEREIGNTY);
      store.removeItem(KEY_SEQUENCE);
      store.removeItem(KEY_ALGO);
      store.removeItem(KEY_DH_PUBKEY);
      store.removeItem(KEY_DH_PRIVKEY);
      store.removeItem(KEY_DH_ALGO);
      store.removeItem(KEY_DH_LAST_ROTATION);
      store.removeItem(KEY_CONTACTS);
      store.removeItem(KEY_DM_NOTIFY);
      store.removeItem(KEY_WORMHOLE_PUBKEY);
      store.removeItem(KEY_WORMHOLE_NODE_ID);
      store.removeItem(KEY_WORMHOLE_ALGO);
      store.removeItem(KEY_WORMHOLE_SECURE_REQUIRED);
      store.removeItem(KEY_DM_BUNDLE_FINGERPRINT);
      store.removeItem(KEY_DM_BUNDLE_SEQUENCE);
      store.removeItem(KEY_RATCHET);
      store.removeItem(KEY_RATCHET_TELEMETRY);
      store.removeItem(KEY_SESSION_MODE);
    } catch {
      /* ignore */
    }
    clearPrefixedStorage(store);
  }
  await deleteKey(KEY_DH_PRIV_IDB);
  await deleteKey(KEY_DH_PREV_PRIV_IDB);
  await deleteKey(KEY_SIGN_PRIV_IDB);
  await purgeMailboxClaimKey();
  await deleteDatabaseIfPresent(RATCHET_CRYPTO_DB);
  await deleteDatabaseIfPresent('sb_mesh_dm_worker');
  emitIdentityStateChange();
}

export async function derivePublicMeshAddress(senderId: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(senderId));
  const bytes = Array.from(new Uint8Array(digest).slice(0, 4));
  return `!${bytes.map((b) => b.toString(16).padStart(2, '0')).join('')}`;
}

async function assertBrowserCustodyAllowed(): Promise<void> {
  if (isSecureModeCached()) {
    throw new Error('browser_identity_blocked_secure_mode');
  }
}

export function getPublicKeyAlgo(): string {
  if (typeof window === 'undefined') return 'Ed25519';
  return storageGet(KEY_ALGO) || 'Ed25519';
}

function normalizeAlgo(value: string): 'Ed25519' | 'ECDSA' {
  const val = (value || '').toUpperCase();
  if (val === 'ED25519' || val === 'EDDSA') return 'Ed25519';
  return 'ECDSA';
}

export function getSequence(): number {
  if (typeof window === 'undefined') return 0;
  const raw = storageGet(KEY_SEQUENCE);
  const val = raw ? parseInt(raw, 10) : 0;
  return Number.isFinite(val) ? val : 0;
}

export function setSequence(value: number): void {
  if (typeof window === 'undefined') return;
  storageSet(KEY_SEQUENCE, String(value));
}

export function nextSequence(): number {
  const current = getSequence();
  const next = current + 1;
  storageSet(KEY_SEQUENCE, String(next));
  return next;
}

/** Convert ArrayBuffer to hex string. */
function bufToHex(buf: ArrayBuffer): string {
  return Array.from(new Uint8Array(buf))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
}

/** Convert ArrayBuffer to Base64 string. */
function bufToBase64(buf: ArrayBuffer): string {
  return btoa(String.fromCharCode(...new Uint8Array(buf)));
}

/** Convert Base64 string to ArrayBuffer. */
function base64ToBuf(b64: string): ArrayBuffer {
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes.buffer;
}

function utf8ToBuf(value: string): Uint8Array<ArrayBuffer> {
  return new TextEncoder().encode(value);
}

/** Generate a Node ID from the public key: !sb_ + first 16 hex chars of SHA-256. */
async function deriveNodeId(publicKeyRaw: ArrayBuffer): Promise<string> {
  const hash = await crypto.subtle.digest('SHA-256', publicKeyRaw);
  return NODE_ID_PREFIX + bufToHex(hash).slice(0, NODE_ID_HEX_LEN);
}

export async function deriveNodeIdFromPublicKey(publicKeyBase64: string): Promise<string> {
  const raw = base64ToBuf(publicKeyBase64);
  return deriveNodeId(raw);
}

export async function verifyNodeIdBindingFromPublicKey(
  publicKeyBase64: string,
  nodeId: string,
): Promise<boolean> {
  try {
    const raw = base64ToBuf(publicKeyBase64);
    const current = await deriveNodeId(raw);
    return current === String(nodeId || '');
  } catch {
    return false;
  }
}

export async function migrateLegacyNodeIds(): Promise<void> {
  if (typeof window === 'undefined') return;

  const publicKey = storageGet(KEY_PUBKEY);
  const nodeId = storageGet(KEY_NODE_ID);
  if (publicKey && nodeId && isLegacyNodeId(nodeId)) {
    try {
      const current = await migrateStoredNodeIdIfLegacy(publicKey, nodeId, (nextNodeId) => {
        storageSet(KEY_NODE_ID, nextNodeId);
      });
      if (current !== nodeId) {
        console.warn(`[mesh] migrated legacy browser node id ${nodeId} -> ${current}`);
      }
    } catch (err) {
      console.warn(`[mesh] failed to migrate legacy browser node id ${nodeId}`, err);
    }
  }

  try {
    const wormholePub = sessionStorage.getItem(KEY_WORMHOLE_PUBKEY);
    const wormholeNode = sessionStorage.getItem(KEY_WORMHOLE_NODE_ID);
    if (wormholePub && wormholeNode && isLegacyNodeId(wormholeNode)) {
      try {
        const current = await migrateStoredNodeIdIfLegacy(wormholePub, wormholeNode, (nextNodeId) => {
          sessionStorage.setItem(KEY_WORMHOLE_NODE_ID, nextNodeId);
        });
        if (current !== wormholeNode) {
          console.warn(`[mesh] migrated legacy Wormhole descriptor ${wormholeNode} -> ${current}`);
        }
      } catch (err) {
        console.warn(`[mesh] failed to migrate legacy Wormhole descriptor ${wormholeNode}`, err);
      }
    }
  } catch {
    /* ignore */
  }
}

async function generateKeyPairRaw(): Promise<{
  publicKey: string;
  privateKey: string;
  nodeId: string;
  algo: string;
}> {
  let keyPair: CryptoKeyPair;
  let algo: string;

  try {
    keyPair = await crypto.subtle.generateKey('Ed25519', true, ['sign', 'verify']);
    algo = 'Ed25519';
  } catch {
    keyPair = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, true, [
      'sign',
      'verify',
    ]);
    algo = 'ECDSA';
  }

  const pubRaw = await crypto.subtle.exportKey('raw', keyPair.publicKey);
  const privJwk = await crypto.subtle.exportKey('jwk', keyPair.privateKey);

  const publicKey = bufToBase64(pubRaw);
  const privateKey = JSON.stringify(privJwk);
  const nodeId = await deriveNodeId(pubRaw);

  // Store signing private key as non-extractable CryptoKey in IndexedDB
  try {
    const nonExtractable = await crypto.subtle.importKey(
      'jwk',
      privJwk,
      algo === 'Ed25519' ? 'Ed25519' : { name: 'ECDSA', namedCurve: 'P-256' },
      false,
      ['sign'],
    );
    await setKey(KEY_SIGN_PRIV_IDB, nonExtractable);
  } catch (err) {
    console.warn(
      '[mesh] signing key IndexedDB storage unavailable — key will not persist for this session',
      err,
    );
  }

  return { publicKey, privateKey, nodeId, algo };
}

/**
 * Ensure the signing private key lives in IndexedDB as a non-extractable
 * CryptoKey. Migrates from localStorage JWK on first call if needed,
 * then removes the localStorage copy.
 */
async function ensureSigningPrivateKey(): Promise<CryptoKey | null> {
  const existing = await getKey(KEY_SIGN_PRIV_IDB);
  if (existing) return existing;

  // Migrate from legacy localStorage JWK
  const legacy = storageGet(KEY_PRIVKEY);
  if (!legacy) return null;
  try {
    const jwk = JSON.parse(legacy);
    const algo = normalizeAlgo(storageGet(KEY_ALGO) || 'Ed25519');
    const imported = await crypto.subtle.importKey(
      'jwk',
      jwk,
      algo === 'Ed25519' ? 'Ed25519' : { name: 'ECDSA', namedCurve: 'P-256' },
      false,
      ['sign'],
    );
    await setKey(KEY_SIGN_PRIV_IDB, imported);
    // Clear the extractable JWK from localStorage after successful migration
    removeLegacyPrivateKeyCopies();
    return imported;
  } catch (err) {
    console.warn(
      '[mesh] legacy signing key migration failed — clearing extractable browser copy',
      err,
    );
    removeLegacyPrivateKeyCopies();
    return null;
  }
}

async function deriveIdentityBoundWrapKey(info: string): Promise<CryptoKey> {
  const descriptor = getStoredNodeDescriptor();
  if (!descriptor?.publicKey || !descriptor.nodeId) {
    throw new Error('No local identity available for encrypted browser storage');
  }

  let dhPubKey = getDHPubKey();
  let dhAlgo = getDHAlgo() || 'X25519';
  let dhPrivKey = await ensureDhPrivateKey();
  if (!dhPubKey || !dhPrivKey) {
    dhPubKey = await generateDHKeys();
    dhAlgo = getDHAlgo() || dhAlgo;
    dhPrivKey = await ensureDhPrivateKey();
  }
  if (!dhPubKey || !dhPrivKey) {
    throw new Error('No DH key available for contact encryption');
  }

  const dhPubRaw = base64ToBuf(dhPubKey);
  let selfPubKey: CryptoKey;
  let sharedSecret: ArrayBuffer;
  if (dhAlgo === 'X25519') {
    selfPubKey = await crypto.subtle.importKey('raw', dhPubRaw, 'X25519', false, []);
    sharedSecret = await crypto.subtle.deriveBits(
      { name: 'X25519', public: selfPubKey },
      dhPrivKey,
      256,
    );
  } else {
    selfPubKey = await crypto.subtle.importKey(
      'raw',
      dhPubRaw,
      { name: 'ECDH', namedCurve: 'P-256' },
      false,
      [],
    );
    sharedSecret = await crypto.subtle.deriveBits(
      { name: 'ECDH', public: selfPubKey },
      dhPrivKey,
      256,
    );
  }

  const hkdfKey = await crypto.subtle.importKey('raw', sharedSecret, 'HKDF', false, ['deriveKey']);
  return crypto.subtle.deriveKey(
    {
      name: 'HKDF',
      hash: 'SHA-256',
      salt: utf8ToBuf(
        `${CONTACTS_WRAP_CONTEXT}|${descriptor.nodeId}|${descriptor.publicKey}|${PROTOCOL_VERSION}`,
      ),
      info: utf8ToBuf(info),
    },
    hkdfKey,
    { name: 'AES-GCM', length: 256 },
    false,
    ['encrypt', 'decrypt'],
  );
}

export async function encryptIdentityBoundStoragePayload(value: unknown, info: string): Promise<string> {
  const key = await deriveIdentityBoundWrapKey(info);
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const encoded = new TextEncoder().encode(JSON.stringify(value));
  const ciphertext = await crypto.subtle.encrypt(
    {
      name: 'AES-GCM',
      iv,
      additionalData: new TextEncoder().encode(info),
    },
    key,
    encoded,
  );
  const combined = new Uint8Array(iv.length + ciphertext.byteLength);
  combined.set(iv, 0);
  combined.set(new Uint8Array(ciphertext), iv.length);
  return `${CONTACTS_ENCRYPTED_PREFIX}${bufToBase64(combined.buffer)}`;
}

export async function decryptIdentityBoundStoragePayload<T>(
  raw: string,
  info: string,
  fallback: T,
): Promise<T> {
  const value = String(raw || '').trim();
  if (!value) return fallback;
  if (!value.startsWith(CONTACTS_ENCRYPTED_PREFIX)) {
    return JSON.parse(value) as T;
  }
  const key = await deriveIdentityBoundWrapKey(info);
  const payload = value.slice(CONTACTS_ENCRYPTED_PREFIX.length);
  const combined = new Uint8Array(base64ToBuf(payload));
  const iv = combined.slice(0, 12);
  const ciphertext = combined.slice(12);
  const decrypted = await crypto.subtle.decrypt(
    {
      name: 'AES-GCM',
      iv,
      additionalData: new TextEncoder().encode(info),
    },
    key,
    ciphertext,
  );
  return JSON.parse(new TextDecoder().decode(decrypted)) as T;
}

async function encryptContactsPayload(contacts: Record<string, Contact>): Promise<string> {
  return encryptIdentityBoundStoragePayload(contacts, CONTACTS_WRAP_INFO);
}

async function decryptContactsPayload(raw: string): Promise<Record<string, Contact>> {
  return normalizeContactMap(
    await decryptIdentityBoundStoragePayload<Record<string, Contact>>(raw, CONTACTS_WRAP_INFO, {}),
  );
}

/**
 * Sign a message using the stored non-extractable signing key from IndexedDB.
 * This is the preferred signing path — avoids exposing raw key material.
 */
export async function signWithStoredKey(message: string): Promise<string> {
  const signingKey = await ensureSigningPrivateKey();
  if (!signingKey) throw new Error('No signing key available');
  const algo = normalizeAlgo(storageGet(KEY_ALGO) || 'Ed25519');
  const data = new TextEncoder().encode(message);
  let signature: ArrayBuffer;
  if (algo === 'Ed25519') {
    signature = await crypto.subtle.sign('Ed25519', signingKey, data);
  } else {
    signature = await crypto.subtle.sign({ name: 'ECDSA', hash: 'SHA-256' }, signingKey, data);
  }
  return bufToHex(signature);
}

export function persistIdentity(identity: NodeIdentity, algo: string, sequence: number) {
  if (isSecureModeCached()) {
    throw new Error('browser_identity_blocked_secure_mode');
  }
  storageSet(KEY_PUBKEY, identity.publicKey);
  storageSet(KEY_NODE_ID, identity.nodeId);
  storageSet(KEY_SOVEREIGNTY, 'true');
  storageSet(KEY_SEQUENCE, String(sequence));
  storageSet(KEY_ALGO, algo);
  removeLegacyPrivateKeyCopies();
  emitIdentityStateChange();
}

export async function createIdentityCandidate(): Promise<{ identity: NodeIdentity; algo: string }> {
  await assertBrowserCustodyAllowed();
  const { publicKey, privateKey, nodeId, algo } = await generateKeyPairRaw();
  return { identity: { publicKey, privateKey, nodeId }, algo };
}

/**
 * Generate a new Ed25519 keypair (falls back to ECDSA P-256 if unsupported).
 * Stores in active storage (local or session) and returns the identity.
 */
export async function generateNodeKeys(): Promise<NodeIdentity> {
  await assertBrowserCustodyAllowed();
  const { publicKey, privateKey, nodeId, algo } = await generateKeyPairRaw();

  persistIdentity({ publicKey, privateKey, nodeId }, algo, 0);

  // Also generate X25519 DH keypair for encrypted DMs
  await generateDHKeys();

  return { publicKey, privateKey, nodeId };
}

/** Retrieve existing identity from active storage, or null if not initialized.
 *
 * The privateKey field is intentionally kept empty. Signing uses the
 * non-extractable IndexedDB key, and any legacy JWK copy is scrubbed during
 * migration. Callers that need to sign
 * should use `signWithStoredKey()` or `signEvent()` instead of reading
 * privateKey directly.
 */
export function getNodeIdentity(): NodeIdentity | null {
  if (typeof window === 'undefined') return null;
  if (isSecureModeCached()) return null;
  const publicKey = storageGet(KEY_PUBKEY);
  const nodeId = storageGet(KEY_NODE_ID);
  if (!publicKey || !nodeId) return null;
  if (storageGet(KEY_PRIVKEY)) {
    void ensureSigningPrivateKey();
  }
  return { publicKey, privateKey: '', nodeId };
}

/** Check if user has accepted the sovereignty declaration. */
export function hasSovereignty(): boolean {
  if (typeof window === 'undefined') return false;
  return storageGet(KEY_SOVEREIGNTY) === 'true';
}

/** Mark sovereignty as declined (read-only mode). */
export function declineSovereignty(): void {
  storageSet(KEY_SOVEREIGNTY, 'declined');
}

/** Check if sovereignty has been explicitly declined. */
export function isDeclined(): boolean {
  if (typeof window === 'undefined') return false;
  return storageGet(KEY_SOVEREIGNTY) === 'declined';
}

/**
 * Sign a message string with the node's private key.
 * Returns a hex-encoded signature.
 */
export async function signMessage(
  message: string,
  privateKeyJson: string,
  algoOverride?: string,
): Promise<string> {
  const normalizedPrivateKey = String(privateKeyJson || '').trim();
  if (!normalizedPrivateKey) {
    throw new Error('Explicit private signing material required');
  }
  const jwk = JSON.parse(normalizedPrivateKey);
  const algo = algoOverride || storageGet('sb_mesh_algo') || 'Ed25519';

  let cryptoKey: CryptoKey;
  if (normalizeAlgo(algo) === 'Ed25519') {
    cryptoKey = await crypto.subtle.importKey('jwk', jwk, 'Ed25519', false, ['sign']);
  } else {
    cryptoKey = await crypto.subtle.importKey(
      'jwk',
      jwk,
      { name: 'ECDSA', namedCurve: 'P-256' },
      false,
      ['sign'],
    );
  }

  const data = new TextEncoder().encode(message);
  let signature: ArrayBuffer;
  if (normalizeAlgo(algo) === 'Ed25519') {
    signature = await crypto.subtle.sign('Ed25519', cryptoKey, data);
  } else {
    signature = await crypto.subtle.sign({ name: 'ECDSA', hash: 'SHA-256' }, cryptoKey, data);
  }

  return bufToHex(signature);
}

export async function signEvent(
  eventType: string,
  nodeId: string,
  sequence: number,
  payload: Record<string, unknown>,
): Promise<string> {
  const payloadStr = buildSignaturePayload({
    eventType,
    nodeId,
    sequence,
    payload: payload as Record<string, JsonValue>,
  });
  return signWithStoredKey(payloadStr);
}

const VERIFY_KEY_CACHE_MAX = 512;
const verifyKeyCache = new Map<string, Promise<CryptoKey>>();

function verifyKeyCacheKey(publicKeyBase64: string, algo: string): string {
  return `${normalizeAlgo(algo)}:${publicKeyBase64}`;
}

async function importVerifyCryptoKey(
  publicKeyBase64: string,
  algo: string,
): Promise<CryptoKey> {
  const normalizedAlgo = normalizeAlgo(algo);
  const cacheKey = verifyKeyCacheKey(publicKeyBase64, normalizedAlgo);
  const existing = verifyKeyCache.get(cacheKey);
  if (existing) {
    return existing;
  }
  const promise = (async () => {
    const pubRaw = base64ToBuf(publicKeyBase64);
    if (normalizedAlgo === 'Ed25519') {
      return crypto.subtle.importKey('raw', pubRaw, 'Ed25519', false, ['verify']);
    }
    return crypto.subtle.importKey(
      'raw',
      pubRaw,
      { name: 'ECDSA', namedCurve: 'P-256' },
      false,
      ['verify'],
    );
  })().catch((error) => {
    verifyKeyCache.delete(cacheKey);
    throw error;
  });
  verifyKeyCache.set(cacheKey, promise);
  if (verifyKeyCache.size > VERIFY_KEY_CACHE_MAX) {
    const oldestKey = verifyKeyCache.keys().next().value;
    if (oldestKey) {
      verifyKeyCache.delete(oldestKey);
    }
  }
  return promise;
}

/**
 * Verify a signature against a public key and message.
 */
export async function verifySignature(
  message: string,
  signature: string,
  publicKeyBase64: string,
): Promise<boolean> {
  return verifySignatureWithAlgo(message, signature, publicKeyBase64);
}

async function verifySignatureWithAlgo(
  message: string,
  signature: string,
  publicKeyBase64: string,
  algoOverride?: string,
): Promise<boolean> {
  const algo = normalizeAlgo(algoOverride || storageGet('sb_mesh_algo') || 'Ed25519');
  const cryptoKey = await importVerifyCryptoKey(publicKeyBase64, algo);

  const data = new TextEncoder().encode(message);
  const sigBuf = new Uint8Array(signature.match(/.{2}/g)!.map((h) => parseInt(h, 16))).buffer;

  if (algo === 'Ed25519') {
    return crypto.subtle.verify('Ed25519', cryptoKey, sigBuf, data);
  } else {
    return crypto.subtle.verify({ name: 'ECDSA', hash: 'SHA-256' }, cryptoKey, sigBuf, data);
  }
}

export async function verifyRawSignature(opts: {
  message: string;
  signature: string;
  publicKey: string;
  publicKeyAlgo: string;
}): Promise<boolean> {
  try {
    return await verifySignatureWithAlgo(
      opts.message,
      opts.signature,
      opts.publicKey,
      opts.publicKeyAlgo,
    );
  } catch {
    return false;
  }
}

export async function verifyEventSignature(opts: {
  eventType: string;
  nodeId: string;
  sequence: number;
  payload: Record<string, unknown>;
  signature: string;
  publicKey: string;
  publicKeyAlgo: string;
}): Promise<boolean> {
  const bound = await verifyNodeIdBindingFromPublicKey(opts.publicKey, opts.nodeId);
  if (!bound) return false;

  const payloadStr = buildSignaturePayload({
    eventType: opts.eventType,
    nodeId: opts.nodeId,
    sequence: opts.sequence,
    payload: opts.payload as Record<string, JsonValue>,
  });

  return verifySignatureWithAlgo(payloadStr, opts.signature, opts.publicKey, opts.publicKeyAlgo);
}

// ─── DH Key Exchange (X25519 / ECDH P-256 fallback) ─────────────────────

/**
 * Generate an X25519 DH keypair for encrypted DMs.
 * Falls back to ECDH P-256 if X25519 is unsupported.
 * Stores in active storage. Returns the Base64 public key.
 */
export async function generateDHKeys(): Promise<string> {
  await assertBrowserCustodyAllowed();
  const previousPrivKey = await getKey(KEY_DH_PRIV_IDB);
  let keyPair: CryptoKeyPair;
  let dhAlgo: string;

  try {
    keyPair = (await crypto.subtle.generateKey('X25519', true, ['deriveBits', 'deriveKey'])) as CryptoKeyPair;
    dhAlgo = 'X25519';
  } catch {
    keyPair = (await crypto.subtle.generateKey({ name: 'ECDH', namedCurve: 'P-256' }, true, [
      'deriveBits',
      'deriveKey',
    ])) as CryptoKeyPair;
    dhAlgo = 'ECDH';
  }

  const pubRaw = await crypto.subtle.exportKey('raw', keyPair.publicKey);
  const privJwk = await crypto.subtle.exportKey('jwk', keyPair.privateKey);

  const dhPubKey = bufToBase64(pubRaw);
  storageSet(KEY_DH_PUBKEY, dhPubKey);
  storageSet(KEY_DH_ALGO, dhAlgo);
  storageSet(KEY_DH_LAST_ROTATION, String(Math.floor(Date.now() / 1000)));

  // Re-import private key as non-extractable and store in IndexedDB
  try {
    const nonExtractable = await crypto.subtle.importKey(
      'jwk',
      privJwk,
      dhAlgo === 'X25519' ? 'X25519' : { name: 'ECDH', namedCurve: 'P-256' },
      false,
      ['deriveBits', 'deriveKey'],
    );
    if (previousPrivKey) {
      await setKey(KEY_DH_PREV_PRIV_IDB, previousPrivKey);
    } else {
      await deleteKey(KEY_DH_PREV_PRIV_IDB);
    }
    await setKey(KEY_DH_PRIV_IDB, nonExtractable);
    storageRemove(KEY_DH_PRIVKEY);
  } catch (err) {
    storageRemove(KEY_DH_PRIVKEY);
    console.warn('[mesh] DH key IndexedDB storage unavailable — DM encryption disabled', err);
    throw new Error('IndexedDB required for DH key storage');
  }

  return dhPubKey;
}

export function getDHLastRotation(): number {
  if (typeof window === 'undefined') return 0;
  const raw = storageGet(KEY_DH_LAST_ROTATION);
  const val = raw ? parseInt(raw, 10) : 0;
  return Number.isFinite(val) ? val : 0;
}

export async function ensureDhKeysFresh(
  maxAgeSeconds: number = 7 * 24 * 3600,
): Promise<{ pub: string | null; rotated: boolean }> {
  if (typeof window === 'undefined') return { pub: null, rotated: false };
  const now = Math.floor(Date.now() / 1000);
  const last = getDHLastRotation();
  let pub = getDHPubKey();
  let rotated = false;
  if (!pub || !last || now - last >= maxAgeSeconds) {
    pub = await generateDHKeys();
    rotated = true;
  }
  await ensureDhPrivateKey();
  return { pub: pub || null, rotated };
}

/** Get our DH public key from active storage. */
export function getDHPubKey(): string | null {
  if (typeof window === 'undefined') return null;
  return storageGet(KEY_DH_PUBKEY);
}

export function getDHAlgo(): string {
  if (typeof window === 'undefined') return '';
  return storageGet(KEY_DH_ALGO) || '';
}

async function ensureDhPrivateKey(): Promise<CryptoKey | null> {
  const existing = await getKey(KEY_DH_PRIV_IDB);
  if (existing) return existing;
  if (storageGet(KEY_DH_PRIVKEY)) {
    storageRemove(KEY_DH_PRIVKEY);
    console.warn('[mesh] cleared legacy DH private key fallback from browser storage');
  }
  return null;
}

async function retainedDhPrivateKeys(): Promise<CryptoKey[]> {
  const keys: CryptoKey[] = [];
  const current = await getKey(KEY_DH_PRIV_IDB);
  if (current) {
    keys.push(current);
  }
  const previous = await getKey(KEY_DH_PREV_PRIV_IDB);
  if (previous && previous !== current) {
    keys.push(previous);
  }
  return keys;
}

async function deriveSharedSecretWithPrivateKey(
  theirDHPubBase64: string,
  privateKey: CryptoKey,
): Promise<ArrayBuffer> {
  const theirPubRaw = base64ToBuf(theirDHPubBase64);
  if (privateKey.algorithm.name === 'X25519') {
    const theirPubKey = await crypto.subtle.importKey('raw', theirPubRaw, 'X25519', false, []);
    return crypto.subtle.deriveBits({ name: 'X25519', public: theirPubKey }, privateKey, 256);
  }

  const ecAlgorithm = privateKey.algorithm as EcKeyAlgorithm;
  const theirPubKey = await crypto.subtle.importKey(
    'raw',
    theirPubRaw,
    { name: 'ECDH', namedCurve: ecAlgorithm.namedCurve || 'P-256' },
    false,
    [],
  );
  return crypto.subtle.deriveBits({ name: 'ECDH', public: theirPubKey }, privateKey, 256);
}

/**
 * Derive a shared AES-256-GCM key from our DH private key + their DH public key.
 */
export async function deriveSharedKey(theirDHPubBase64: string): Promise<CryptoKey> {
  const dhAlgo = storageGet(KEY_DH_ALGO) || 'X25519';
  const privKey = await ensureDhPrivateKey();
  if (!privKey) throw new Error('Missing DH private key');
  const theirPubRaw = base64ToBuf(theirDHPubBase64);
  let theirPubKey: CryptoKey;

  if (dhAlgo === 'X25519') {
    theirPubKey = await crypto.subtle.importKey('raw', theirPubRaw, 'X25519', false, []);
    return crypto.subtle.deriveKey(
      { name: 'X25519', public: theirPubKey },
      privKey,
      { name: 'AES-GCM', length: 256 },
      false,
      ['encrypt', 'decrypt'],
    );
  } else {
    theirPubKey = await crypto.subtle.importKey(
      'raw',
      theirPubRaw,
      { name: 'ECDH', namedCurve: 'P-256' },
      false,
      [],
    );
    return crypto.subtle.deriveKey(
      { name: 'ECDH', public: theirPubKey },
      privKey,
      { name: 'AES-GCM', length: 256 },
      false,
      ['encrypt', 'decrypt'],
    );
  }
}

/**
 * Derive a raw shared secret (256-bit) from our DH private key + their DH public key.
 * Used for metadata-hiding tokens (dead-drop) and SAS verification.
 */
export async function deriveSharedSecret(theirDHPubBase64: string): Promise<ArrayBuffer> {
  const dhAlgo = storageGet(KEY_DH_ALGO) || 'X25519';
  const privKey = await ensureDhPrivateKey();
  if (!privKey) throw new Error('Missing DH private key');
  const theirPubRaw = base64ToBuf(theirDHPubBase64);

  let theirPubKey: CryptoKey;

  if (dhAlgo === 'X25519') {
    theirPubKey = await crypto.subtle.importKey('raw', theirPubRaw, 'X25519', false, []);
    return crypto.subtle.deriveBits({ name: 'X25519', public: theirPubKey }, privKey, 256);
  }
  theirPubKey = await crypto.subtle.importKey(
    'raw',
    theirPubRaw,
    { name: 'ECDH', namedCurve: 'P-256' },
    false,
    [],
  );
  return crypto.subtle.deriveBits({ name: 'ECDH', public: theirPubKey }, privKey, 256);
}

async function sha256Bytes(value: string): Promise<ArrayBuffer> {
  return crypto.subtle.digest('SHA-256', utf8ToBuf(value));
}

export async function deriveSenderSealKey(
  theirDHPubBase64: string,
  recipientId: string,
  msgId: string,
): Promise<CryptoKey> {
  const secret = await deriveSharedSecret(theirDHPubBase64);
  const salt = await sha256Bytes(`SB-SEAL-SALT|${recipientId}|${msgId}|${PROTOCOL_VERSION}`);
  const hkdfKey = await crypto.subtle.importKey('raw', secret, 'HKDF', false, ['deriveKey']);
  return crypto.subtle.deriveKey(
    {
      name: 'HKDF',
      hash: 'SHA-256',
      salt,
      info: utf8ToBuf('SB-SENDER-SEAL-V2'),
    },
    hkdfKey,
    { name: 'AES-GCM', length: 256 },
    false,
    ['encrypt', 'decrypt'],
  );
}

export async function deriveSenderSealKeyV3(
  ephemeralPubBase64: string,
  recipientId: string,
  msgId: string,
): Promise<CryptoKey> {
  const secret = await deriveSharedSecret(ephemeralPubBase64);
  const salt = await sha256Bytes(
    `SB-SEAL-SALT|${recipientId}|${msgId}|${PROTOCOL_VERSION}|${ephemeralPubBase64}`,
  );
  const hkdfKey = await crypto.subtle.importKey('raw', secret, 'HKDF', false, ['deriveKey']);
  return crypto.subtle.deriveKey(
    {
      name: 'HKDF',
      hash: 'SHA-256',
      salt,
      info: utf8ToBuf('SB-SENDER-SEAL-V3'),
    },
    hkdfKey,
    { name: 'AES-GCM', length: 256 },
    false,
    ['encrypt', 'decrypt'],
  );
}

async function decryptSenderSealPayloadWithRetainedKeys(
  payload: string,
  ephemeralPubBase64: string,
  recipientId: string,
  msgId: string,
): Promise<string | null> {
  const keys = await retainedDhPrivateKeys();
  for (const privateKey of keys) {
    try {
      const secret = await deriveSharedSecretWithPrivateKey(ephemeralPubBase64, privateKey);
      const salt = await sha256Bytes(
        `SB-SEAL-SALT|${recipientId}|${msgId}|${PROTOCOL_VERSION}|${ephemeralPubBase64}`,
      );
      const hkdfKey = await crypto.subtle.importKey('raw', secret, 'HKDF', false, ['deriveKey']);
      const sealKey = await crypto.subtle.deriveKey(
        {
          name: 'HKDF',
          hash: 'SHA-256',
          salt,
          info: utf8ToBuf('SB-SENDER-SEAL-V3'),
        },
        hkdfKey,
        { name: 'AES-GCM', length: 256 },
        false,
        ['encrypt', 'decrypt'],
      );
      return await decryptDM(payload, sealKey);
    } catch {
      /* try next retained key */
    }
  }
  return null;
}

export async function decryptSenderSealPayloadLocally(
  senderSeal: string,
  candidateDhPub: string,
  recipientId: string,
  msgId: string,
): Promise<string | null> {
  const sealEnvelope = unwrapSenderSealPayload(senderSeal);
  try {
    if (sealEnvelope.version === 'v3') {
      const ephemeralPub = String(sealEnvelope.ephemeralPub || '').trim();
      if (!ephemeralPub) return null;
      return await decryptSenderSealPayloadWithRetainedKeys(
        sealEnvelope.payload,
        ephemeralPub,
        recipientId,
        msgId,
      );
    }
    const sealKey =
      sealEnvelope.version === 'v2'
        ? await deriveSenderSealKey(candidateDhPub, recipientId, msgId)
        : await deriveSharedKey(candidateDhPub);
    return await decryptDM(sealEnvelope.payload, sealKey);
  } catch {
    return null;
  }
}

export function unwrapSenderSealPayload(
  senderSeal: string,
): { version: 'v3' | 'v2' | 'legacy'; payload: string; ephemeralPub?: string } {
  const value = String(senderSeal || '').trim();
  if (value.startsWith('v3:')) {
    const [, ephemeralPub, payload] = value.split(':', 3);
    return { version: 'v3', payload, ephemeralPub };
  }
  if (value.startsWith('v2:')) {
    return { version: 'v2', payload: value.slice(3) };
  }
  return { version: 'legacy', payload: value };
}

/**
 * Encrypt a plaintext message with a shared AES-GCM key.
 * Returns Base64(iv || ciphertext).
 */
export async function encryptDM(plaintext: string, sharedKey: CryptoKey): Promise<string> {
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const encoded = new TextEncoder().encode(plaintext);
  const ciphertext = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, sharedKey, encoded);
  // Concatenate IV + ciphertext
  const combined = new Uint8Array(iv.length + ciphertext.byteLength);
  combined.set(iv, 0);
  combined.set(new Uint8Array(ciphertext), iv.length);
  return bufToBase64(combined.buffer);
}

/**
 * Decrypt a ciphertext blob with a shared AES-GCM key.
 * Expects Base64(iv || ciphertext) as input.
 */
export async function decryptDM(ciphertextB64: string, sharedKey: CryptoKey): Promise<string> {
  const combined = new Uint8Array(base64ToBuf(ciphertextB64));
  const iv = combined.slice(0, 12);
  const ciphertext = combined.slice(12);
  const plainBuf = await crypto.subtle.decrypt({ name: 'AES-GCM', iv }, sharedKey, ciphertext);
  return new TextDecoder().decode(plainBuf);
}

// ─── Contact Management (storage) ──────────────────────────────────────

export interface Contact {
  alias?: string;
  blocked: boolean;
  dhPubKey?: string;
  dhAlgo?: string;
  sharedAlias?: string;
  previousSharedAliases?: string[];
  pendingSharedAlias?: string;
  sharedAliasGraceUntil?: number;
  sharedAliasRotatedAt?: number;
  verify_inband?: boolean;
  verify_registry?: boolean;
  verified?: boolean;
  verify_mismatch?: boolean;
  verified_at?: number;
  remotePrekeyFingerprint?: string;
  remotePrekeyObservedFingerprint?: string;
  remotePrekeyPinnedAt?: number;
  remotePrekeyLastSeenAt?: number;
  remotePrekeySequence?: number;
  remotePrekeySignedAt?: number;
  remotePrekeyMismatch?: boolean;
  witness_count?: number;
  witness_checked_at?: number;
  vouch_count?: number;
  vouch_checked_at?: number;
}

let contactCache: Record<string, Contact> = {};
let contactsHydration: Promise<Record<string, Contact>> | null = null;

function shouldUseWormholeContacts(): boolean {
  return isSecureModeCached();
}

function sanitizeContact(contact: Partial<Contact> | undefined): Contact {
  return {
    alias: String(contact?.alias || ''),
    blocked: Boolean(contact?.blocked),
    dhPubKey: String(contact?.dhPubKey || ''),
    dhAlgo: String(contact?.dhAlgo || ''),
    sharedAlias: String(contact?.sharedAlias || ''),
    previousSharedAliases: Array.isArray(contact?.previousSharedAliases)
      ? contact?.previousSharedAliases.filter(Boolean).map(String).slice(-8)
      : [],
    pendingSharedAlias: String(contact?.pendingSharedAlias || ''),
    sharedAliasGraceUntil: Number(contact?.sharedAliasGraceUntil || 0),
    sharedAliasRotatedAt: Number(contact?.sharedAliasRotatedAt || 0),
    verify_inband: Boolean(contact?.verify_inband),
    verify_registry: Boolean(contact?.verify_registry),
    verified: Boolean(contact?.verified),
    verify_mismatch: Boolean(contact?.verify_mismatch),
    verified_at: Number(contact?.verified_at || 0),
    remotePrekeyFingerprint: String(contact?.remotePrekeyFingerprint || ''),
    remotePrekeyObservedFingerprint: String(contact?.remotePrekeyObservedFingerprint || ''),
    remotePrekeyPinnedAt: Number(contact?.remotePrekeyPinnedAt || 0),
    remotePrekeyLastSeenAt: Number(contact?.remotePrekeyLastSeenAt || 0),
    remotePrekeySequence: Number(contact?.remotePrekeySequence || 0),
    remotePrekeySignedAt: Number(contact?.remotePrekeySignedAt || 0),
    remotePrekeyMismatch: Boolean(contact?.remotePrekeyMismatch),
    witness_count: Number(contact?.witness_count || 0),
    witness_checked_at: Number(contact?.witness_checked_at || 0),
    vouch_count: Number(contact?.vouch_count || 0),
    vouch_checked_at: Number(contact?.vouch_checked_at || 0),
  };
}

function normalizeContactMap(input: Record<string, Contact> | Record<string, unknown>): Record<string, Contact> {
  return Object.fromEntries(
    Object.entries(input || {}).map(([peerId, contact]) => [peerId, sanitizeContact(contact as Partial<Contact>)]),
  );
}

async function persistContactToWormhole(peerId: string, contact: Contact): Promise<void> {
  await controlPlaneJson('/api/wormhole/dm/contact', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      peer_id: peerId,
      contact,
    }),
  });
}

async function deleteContactFromWormhole(peerId: string): Promise<void> {
  await controlPlaneJson(`/api/wormhole/dm/contact/${encodeURIComponent(peerId)}`, {
    method: 'DELETE',
  });
}

export async function hydrateWormholeContacts(force: boolean = false): Promise<Record<string, Contact>> {
  if (!shouldUseWormholeContacts()) {
    if (!force && contactsHydration) {
      return contactsHydration;
    }
    contactsHydration = (async () => {
      if (typeof window === 'undefined') {
        contactCache = {};
        return contactCache;
      }
      const raw = storageGet(KEY_CONTACTS) || '';
      if (!raw) {
        contactCache = {};
        return contactCache;
      }
      try {
        const hydrated = await decryptContactsPayload(raw);
        contactCache = hydrated;
        if (!raw.startsWith(CONTACTS_ENCRYPTED_PREFIX)) {
          void persistStoredContacts(hydrated);
        }
        return contactCache;
      } catch (err) {
        console.warn('[mesh] contact storage unreadable — treating as empty contacts', err);
        contactCache = {};
        return contactCache;
      }
    })();
    return contactsHydration;
  }
  if (!force && contactsHydration) {
    return contactsHydration;
  }
  contactsHydration = controlPlaneJson<{ ok: boolean; contacts: Record<string, unknown> }>(
    '/api/wormhole/dm/contacts',
  )
    .then((data) => {
      contactCache = normalizeContactMap(data.contacts || {});
      return contactCache;
    })
    .catch(() => contactCache);
  return contactsHydration;
}

function getStoredContacts(): Record<string, Contact> {
  if (!shouldUseWormholeContacts() && !contactsHydration && typeof window !== 'undefined') {
    void hydrateWormholeContacts();
  }
  return contactCache;
}

export function getContacts(): Record<string, Contact> {
  if (shouldUseWormholeContacts()) {
    return contactCache;
  }
  return getStoredContacts();
}

async function persistStoredContacts(contacts: Record<string, Contact>): Promise<void> {
  try {
    const encrypted = await encryptContactsPayload(normalizeContactMap(contacts));
    storageSet(KEY_CONTACTS, encrypted);
  } catch (err) {
    console.warn(
      '[mesh] contact storage encryption unavailable — contacts kept in memory only',
      err,
    );
  }
}

function saveContacts(contacts: Record<string, Contact>): void {
  const normalized = normalizeContactMap(contacts);
  contactCache = normalized;
  if (shouldUseWormholeContacts()) {
    return;
  }
  void persistStoredContacts(normalized);
}

export function addContact(agentId: string, dhPubKey: string, alias?: string, dhAlgo?: string): void {
  const contacts = getContacts();
  const next = sanitizeContact({
    alias: alias || contacts[agentId]?.alias,
    blocked: contacts[agentId]?.blocked || false,
    dhPubKey,
    dhAlgo: dhAlgo || contacts[agentId]?.dhAlgo,
    sharedAlias: contacts[agentId]?.sharedAlias,
    previousSharedAliases: contacts[agentId]?.previousSharedAliases,
    pendingSharedAlias: contacts[agentId]?.pendingSharedAlias,
    sharedAliasGraceUntil: contacts[agentId]?.sharedAliasGraceUntil,
    sharedAliasRotatedAt: contacts[agentId]?.sharedAliasRotatedAt,
    verify_inband: contacts[agentId]?.verify_inband,
    verify_registry: contacts[agentId]?.verify_registry,
    verified: contacts[agentId]?.verified,
    verify_mismatch: contacts[agentId]?.verify_mismatch,
    verified_at: contacts[agentId]?.verified_at,
    remotePrekeyFingerprint: contacts[agentId]?.remotePrekeyFingerprint,
    remotePrekeyObservedFingerprint: contacts[agentId]?.remotePrekeyObservedFingerprint,
    remotePrekeyPinnedAt: contacts[agentId]?.remotePrekeyPinnedAt,
    remotePrekeyLastSeenAt: contacts[agentId]?.remotePrekeyLastSeenAt,
    remotePrekeySequence: contacts[agentId]?.remotePrekeySequence,
    remotePrekeySignedAt: contacts[agentId]?.remotePrekeySignedAt,
    remotePrekeyMismatch: contacts[agentId]?.remotePrekeyMismatch,
  });
  contacts[agentId] = next;
  saveContacts(contacts);
  if (shouldUseWormholeContacts()) {
    void persistContactToWormhole(agentId, next);
  }
}

export function updateContact(agentId: string, updates: Partial<Contact>): void {
  const contacts = getContacts();
  const current = contacts[agentId] || sanitizeContact({ blocked: false });
  contacts[agentId] = sanitizeContact({ ...current, ...updates });
  saveContacts(contacts);
  if (shouldUseWormholeContacts()) {
    void persistContactToWormhole(agentId, contacts[agentId]);
  }
}

export function blockContact(agentId: string): void {
  const contacts = getContacts();
  if (contacts[agentId]) {
    contacts[agentId].blocked = true;
  } else {
    contacts[agentId] = sanitizeContact({ blocked: true });
  }
  saveContacts(contacts);
  if (shouldUseWormholeContacts()) {
    void persistContactToWormhole(agentId, sanitizeContact(contacts[agentId]));
  }
}

export function unblockContact(agentId: string): void {
  const contacts = getContacts();
  if (contacts[agentId]) {
    contacts[agentId].blocked = false;
    saveContacts(contacts);
    if (shouldUseWormholeContacts()) {
      void persistContactToWormhole(agentId, sanitizeContact(contacts[agentId]));
    }
  }
}

export function removeContact(agentId: string): void {
  const contacts = getContacts();
  if (!(agentId in contacts)) return;
  delete contacts[agentId];
  saveContacts(contacts);
  if (shouldUseWormholeContacts()) {
    void deleteContactFromWormhole(agentId);
  }
}

export function isBlocked(agentId: string): boolean {
  return getContacts()[agentId]?.blocked || false;
}

export function getDMNotify(): boolean {
  if (typeof window === 'undefined') return true;
  return storageGet(KEY_DM_NOTIFY) !== 'false';
}

export function setDMNotify(on: boolean): void {
  storageSet(KEY_DM_NOTIFY, on ? 'true' : 'false');
}
const NODE_ID_PREFIX = '!sb_';
const NODE_ID_HEX_LEN = 16;
