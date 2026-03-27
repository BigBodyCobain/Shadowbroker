/**
 * Double Ratchet for Dead Drop DMs (client-side only).
 *
 * This is a pragmatic, lightweight ratchet using:
 * - X25519 (preferred) or ECDH P-256 (fallback) for DH
 * - HKDF-SHA256 for root key evolution
 * - HMAC-SHA256 for chain/message keys
 * - AES-256-GCM for message encryption
 *
 * Ciphertext format:
 *   "dr2:" + base64(JSON({ h: { v, dh, pn, n, alg }, ct }))
 * where ct is base64(iv || ciphertext)
 */

import { getKey } from '@/mesh/meshKeyStore';

const KEY_SESSION_MODE = 'sb_mesh_session_mode';
const KEY_DH_PUBKEY = 'sb_mesh_dh_pubkey';
const KEY_DH_ALGO = 'sb_mesh_dh_algo';
const KEY_DH_PRIV_IDB = 'sb_mesh_dh_priv';
const KEY_RATCHET = 'sb_mesh_dm_ratchet';
const KEY_RATCHET_TELEMETRY = 'sb_mesh_ratchet_telemetry';
// Ratchet state lives in IndexedDB alongside a non-extractable wrap key so raw
// private state never needs to persist in Web Storage.
const RATCHET_CRYPTO_DB = 'sb_mesh_ratchet_crypto';
const RATCHET_CRYPTO_DB_VERSION = 2;
const RATCHET_CRYPTO_STORE = 'keys';
const RATCHET_STATE_STORE = 'state';
const RATCHET_WRAP_KEY_ID = 'ratchet_wrap_key';
const RATCHET_STATE_ID = 'ratchet_state';

const MAX_SKIP = 32;
const PAD_BUCKET = 1024;
const PAD_STEP = 512;
const PAD_MAX = 4096;
const PAD_MAGIC = 'SBP1';

type RatchetState = {
  algo: string;
  rk: string;
  cks?: string;
  ckr?: string;
  dhSelfPub: string;
  dhSelfPriv: string;
  dhRemote: string;
  ns: number;
  nr: number;
  pn: number;
  skipped?: Record<string, string>;
  updated: number;
};

let stateCache: Record<string, RatchetState> | null = null;
let stateLoadPromise: Promise<Record<string, RatchetState>> | null = null;
const ratchetTelemetry: Record<string, number> = {};

if (typeof window !== 'undefined') {
  try {
    localStorage.removeItem(KEY_RATCHET_TELEMETRY);
    sessionStorage.removeItem(KEY_RATCHET_TELEMETRY);
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

function getStore(): Storage | null {
  if (typeof window === 'undefined') return null;
  try {
    return isSessionMode() ? sessionStorage : localStorage;
  } catch {
    return sessionStorage;
  }
}

function getAlternateStore(store: Storage | null): Storage | null {
  if (typeof window === 'undefined' || !store) return null;
  return store === sessionStorage ? localStorage : sessionStorage;
}

function storageGet(key: string): string | null {
  const store = getStore();
  if (!store) return null;
  const primaryValue = store.getItem(key);
  if (primaryValue !== null) return primaryValue;
  const alternate = getAlternateStore(store);
  if (!alternate) return null;
  const migratedValue = alternate.getItem(key);
  if (migratedValue !== null) {
    store.setItem(key, migratedValue);
    alternate.removeItem(key);
  }
  return migratedValue;
}

function storageSet(key: string, value: string): void {
  const store = getStore();
  if (!store) return;
  store.setItem(key, value);
  const alternate = getAlternateStore(store);
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

function openRatchetCryptoDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const open = indexedDB.open(RATCHET_CRYPTO_DB, RATCHET_CRYPTO_DB_VERSION);
    open.onupgradeneeded = () => {
      const db = open.result;
      if (!db.objectStoreNames.contains(RATCHET_CRYPTO_STORE)) {
        db.createObjectStore(RATCHET_CRYPTO_STORE, { keyPath: 'id' });
      }
      if (!db.objectStoreNames.contains(RATCHET_STATE_STORE)) {
        db.createObjectStore(RATCHET_STATE_STORE);
      }
    };
    open.onsuccess = () => resolve(open.result);
    open.onerror = () => reject(open.error);
  });
}

async function getOrCreateWrapKey(): Promise<CryptoKey> {
  const db = await openRatchetCryptoDb();
  try {
    const existing = await new Promise<CryptoKey | null>((resolve, reject) => {
      const tx = db.transaction(RATCHET_CRYPTO_STORE, 'readonly');
      const store = tx.objectStore(RATCHET_CRYPTO_STORE);
      const req = store.get(RATCHET_WRAP_KEY_ID);
      req.onsuccess = () => resolve((req.result?.key as CryptoKey | undefined) || null);
      req.onerror = () => reject(req.error);
    });
    if (existing) return existing;

    const key = await crypto.subtle.generateKey({ name: 'AES-GCM', length: 256 }, false, [
      'encrypt',
      'decrypt',
    ]);
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(RATCHET_CRYPTO_STORE, 'readwrite');
      tx.objectStore(RATCHET_CRYPTO_STORE).put({ id: RATCHET_WRAP_KEY_ID, key });
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error);
    });
    return key;
  } finally {
    db.close();
  }
}

async function encryptRatchetState(plaintext: string): Promise<string> {
  const key = await getOrCreateWrapKey();
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const encoded = new TextEncoder().encode(plaintext);
  const ciphertext = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, encoded);
  const combined = new Uint8Array(iv.length + ciphertext.byteLength);
  combined.set(iv);
  combined.set(new Uint8Array(ciphertext), iv.length);
  return btoa(String.fromCharCode(...combined));
}

async function decryptRatchetState(encrypted: string): Promise<string> {
  const key = await getOrCreateWrapKey();
  const combined = Uint8Array.from(atob(encrypted), (c) => c.charCodeAt(0));
  const iv = combined.slice(0, 12);
  const ciphertext = combined.slice(12);
  const decrypted = await crypto.subtle.decrypt({ name: 'AES-GCM', iv }, key, ciphertext);
  return new TextDecoder().decode(decrypted);
}

async function readPersistedRatchetState(): Promise<string | null> {
  const db = await openRatchetCryptoDb();
  try {
    return await new Promise<string | null>((resolve, reject) => {
      const tx = db.transaction(RATCHET_STATE_STORE, 'readonly');
      const store = tx.objectStore(RATCHET_STATE_STORE);
      const req = store.get(RATCHET_STATE_ID);
      req.onsuccess = () => resolve((req.result as string | undefined) || null);
      req.onerror = () => reject(req.error);
    });
  } finally {
    db.close();
  }
}

async function writePersistedRatchetState(value: string): Promise<void> {
  const db = await openRatchetCryptoDb();
  try {
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(RATCHET_STATE_STORE, 'readwrite');
      tx.objectStore(RATCHET_STATE_STORE).put(value, RATCHET_STATE_ID);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error);
    });
  } finally {
    db.close();
  }
}

function recordTelemetry(event: string): void {
  ratchetTelemetry[event] = (ratchetTelemetry[event] || 0) + 1;
}

function bufToBase64(buf: ArrayBufferLike): string {
  return btoa(String.fromCharCode(...new Uint8Array(buf)));
}

function stableStringify(value: unknown): string {
  if (value === null || typeof value !== 'object') {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map((v) => stableStringify(v)).join(',')}]`;
  }
  const obj = value as Record<string, unknown>;
  const keys = Object.keys(obj).sort();
  const entries = keys.map((k) => `${JSON.stringify(k)}:${stableStringify(obj[k])}`);
  return `{${entries.join(',')}}`;
}

function base64ToBuf(b64: string): ArrayBuffer {
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes.buffer;
}

function utf8ToBuf(text: string): ArrayBuffer {
  return new TextEncoder().encode(text).buffer;
}

function ensureArrayBuf(value?: string): ArrayBuffer {
  if (!value) return new Uint8Array(32).buffer;
  return base64ToBuf(value);
}

async function loadAllStates(): Promise<Record<string, RatchetState>> {
  if (stateCache) return stateCache;
  if (stateLoadPromise) return stateLoadPromise;
  stateLoadPromise = (async () => {
    if (typeof window === 'undefined') {
      stateCache = {};
      return stateCache;
    }
    try {
      const persisted = await readPersistedRatchetState();
      if (persisted) {
        const decrypted = await decryptRatchetState(persisted);
        stateCache = JSON.parse(decrypted) as Record<string, RatchetState>;
        return stateCache;
      }
      const legacy = storageGet(KEY_RATCHET) || '';
      if (!legacy) {
        stateCache = {};
        return stateCache;
      }
      try {
        stateCache = JSON.parse(legacy) as Record<string, RatchetState>;
      } catch {
        const decrypted = await decryptRatchetState(legacy);
        stateCache = JSON.parse(decrypted) as Record<string, RatchetState>;
      }
      await saveAllStates(stateCache || {});
      storageRemove(KEY_RATCHET);
      return stateCache || {};
    } catch {
      stateCache = {};
      return stateCache;
    }
  })();
  return stateLoadPromise;
}

async function saveAllStates(states: Record<string, RatchetState>): Promise<void> {
  stateCache = states;
  stateLoadPromise = Promise.resolve(states);
  try {
    const encrypted = await encryptRatchetState(JSON.stringify(states));
    await writePersistedRatchetState(encrypted);
    storageRemove(KEY_RATCHET);
  } catch (err) {
    console.warn('[mesh] ratchet encryption unavailable — state kept in memory only, not persisted', err);
  }
}

async function getState(peerId: string): Promise<RatchetState | null> {
  const all = await loadAllStates();
  return all[peerId] || null;
}

async function setState(peerId: string, state: RatchetState): Promise<void> {
  const all = await loadAllStates();
  all[peerId] = state;
  await saveAllStates(all);
}

function getLongTermDhAlgo(): string {
  return storageGet(KEY_DH_ALGO) || 'X25519';
}

function getLongTermDhPub(): string {
  return storageGet(KEY_DH_PUBKEY) || '';
}

async function generateRatchetKeyPair(algoHint?: string): Promise<{ pub: string; priv: string; algo: string }> {
  let keyPair: CryptoKeyPair;
  let algo = (algoHint || '').toUpperCase();
  try {
    keyPair = (await crypto.subtle.generateKey('X25519', true, ['deriveBits'])) as CryptoKeyPair;
    algo = 'X25519';
  } catch {
    keyPair = (await crypto.subtle.generateKey({ name: 'ECDH', namedCurve: 'P-256' }, true, [
      'deriveBits',
    ])) as CryptoKeyPair;
    algo = 'ECDH';
  }
  const pubRaw = await crypto.subtle.exportKey('raw', keyPair.publicKey);
  const privJwk = await crypto.subtle.exportKey('jwk', keyPair.privateKey);
  return { pub: bufToBase64(pubRaw), priv: JSON.stringify(privJwk), algo };
}

async function deriveDhSecret(
  algo: string,
  privJwkStr: string,
  theirPubB64: string,
): Promise<ArrayBuffer> {
  const algoNorm = (algo || '').toUpperCase();
  const privJwk = JSON.parse(privJwkStr || '{}');
  const theirPubRaw = base64ToBuf(theirPubB64);
  if (algoNorm === 'X25519') {
    const privKey = await crypto.subtle.importKey('jwk', privJwk, 'X25519', false, ['deriveBits']);
    const pubKey = await crypto.subtle.importKey('raw', theirPubRaw, 'X25519', false, []);
    return crypto.subtle.deriveBits({ name: 'X25519', public: pubKey }, privKey, 256);
  }
  const privKey = await crypto.subtle.importKey(
    'jwk',
    privJwk,
    { name: 'ECDH', namedCurve: 'P-256' },
    false,
    ['deriveBits'],
  );
  const pubKey = await crypto.subtle.importKey(
    'raw',
    theirPubRaw,
    { name: 'ECDH', namedCurve: 'P-256' },
    false,
    [],
  );
  return crypto.subtle.deriveBits({ name: 'ECDH', public: pubKey }, privKey, 256);
}

async function deriveDhSecretWithKey(
  algo: string,
  privKey: CryptoKey,
  theirPubB64: string,
): Promise<ArrayBuffer> {
  const algoNorm = (algo || '').toUpperCase();
  const theirPubRaw = base64ToBuf(theirPubB64);
  if (algoNorm === 'X25519') {
    const pubKey = await crypto.subtle.importKey('raw', theirPubRaw, 'X25519', false, []);
    return crypto.subtle.deriveBits({ name: 'X25519', public: pubKey }, privKey, 256);
  }
  const pubKey = await crypto.subtle.importKey(
    'raw',
    theirPubRaw,
    { name: 'ECDH', namedCurve: 'P-256' },
    false,
    [],
  );
  return crypto.subtle.deriveBits({ name: 'ECDH', public: pubKey }, privKey, 256);
}

async function getLongTermDhPrivateKey(): Promise<CryptoKey> {
  const key = await getKey(KEY_DH_PRIV_IDB);
  if (!key) {
    throw new Error('DM encryption unavailable: missing long-term DH private key');
  }
  return key as CryptoKey;
}

async function hkdf(ikm: ArrayBuffer, salt: ArrayBuffer, info: string, length: number): Promise<Uint8Array> {
  const key = await crypto.subtle.importKey('raw', ikm, 'HKDF', false, ['deriveBits']);
  const bits = await crypto.subtle.deriveBits(
    { name: 'HKDF', hash: 'SHA-256', salt, info: utf8ToBuf(info) },
    key,
    length * 8,
  );
  return new Uint8Array(bits);
}

async function kdfRK(rk: ArrayBuffer, dhOut: ArrayBuffer): Promise<{ rk: Uint8Array; ck: Uint8Array }> {
  const salt = rk && rk.byteLength ? rk : new Uint8Array(32).buffer;
  const out = await hkdf(dhOut, salt, 'SB-DR-RK', 64);
  return { rk: out.slice(0, 32), ck: out.slice(32, 64) };
}

async function hmacSha256(keyBytes: ArrayBufferLike, data: Uint8Array): Promise<Uint8Array> {
  const key = await crypto.subtle.importKey('raw', keyBytes as ArrayBuffer, { name: 'HMAC', hash: 'SHA-256' }, false, [
    'sign',
  ]);
  const sig = await crypto.subtle.sign('HMAC', key, data as BufferSource);
  return new Uint8Array(sig);
}

async function kdfCK(ck: ArrayBuffer): Promise<{ ck: Uint8Array; mk: Uint8Array }> {
  const mk = await hmacSha256(ck, new Uint8Array([1]));
  const next = await hmacSha256(ck, new Uint8Array([2]));
  return { ck: next, mk };
}

function buildPaddedPayload(plaintext: string): Uint8Array {
  const data = new TextEncoder().encode(plaintext);
  const len = data.length;
  let target = PAD_BUCKET;
  if (len + 6 > target) {
    target = Math.ceil((len + 6) / PAD_STEP) * PAD_STEP;
  }
  if (target > PAD_MAX) {
    target = Math.ceil((len + 6) / PAD_STEP) * PAD_STEP;
  }
  const out = new Uint8Array(target);
  out.set(new TextEncoder().encode(PAD_MAGIC), 0);
  out[4] = (len >> 8) & 0xff;
  out[5] = len & 0xff;
  out.set(data, 6);
  if (target > len + 6) {
    crypto.getRandomValues(out.subarray(6 + len));
  }
  return out;
}

function unpadPayload(data: Uint8Array): string {
  if (data.length < 6) {
    return new TextDecoder().decode(data);
  }
  const magic = new TextDecoder().decode(data.slice(0, 4));
  if (magic !== PAD_MAGIC) {
    return new TextDecoder().decode(data);
  }
  const len = (data[4] << 8) + data[5];
  if (len <= 0 || 6 + len > data.length) {
    return new TextDecoder().decode(data);
  }
  return new TextDecoder().decode(data.slice(6, 6 + len));
}

function headerAad(header: Record<string, unknown>): Uint8Array {
  return new TextEncoder().encode(stableStringify(header));
}

async function aesGcmEncrypt(
  mk: ArrayBufferLike,
  plaintext: string,
  aad?: Uint8Array,
): Promise<string> {
  const key = await crypto.subtle.importKey('raw', mk as ArrayBuffer, { name: 'AES-GCM' }, false, ['encrypt']);
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const encoded = buildPaddedPayload(plaintext);
  const ciphertext = await crypto.subtle.encrypt(
    { name: 'AES-GCM', iv, additionalData: aad as BufferSource | undefined },
    key,
    encoded as BufferSource,
  );
  const combined = new Uint8Array(iv.length + ciphertext.byteLength);
  combined.set(iv, 0);
  combined.set(new Uint8Array(ciphertext), iv.length);
  return bufToBase64(combined.buffer);
}

async function aesGcmDecrypt(
  mk: ArrayBufferLike,
  ciphertextB64: string,
  aad?: Uint8Array,
): Promise<string> {
  const key = await crypto.subtle.importKey('raw', mk as ArrayBuffer, { name: 'AES-GCM' }, false, ['decrypt']);
  const combined = new Uint8Array(base64ToBuf(ciphertextB64));
  const iv = combined.slice(0, 12);
  const ciphertext = combined.slice(12);
  const plainBuf = await crypto.subtle.decrypt(
    { name: 'AES-GCM', iv, additionalData: aad as BufferSource | undefined },
    key,
    ciphertext as BufferSource,
  );
  return unpadPayload(new Uint8Array(plainBuf));
}

async function initSenderState(peerId: string, theirDhPub: string): Promise<RatchetState> {
  const { pub, priv, algo } = await generateRatchetKeyPair(getLongTermDhAlgo());
  const dhOut = await deriveDhSecret(algo, priv, theirDhPub);
  const { rk, ck } = await kdfRK(new Uint8Array(32).buffer, dhOut);
  return {
    algo,
    rk: bufToBase64(rk.buffer),
    cks: bufToBase64(ck.buffer),
    ckr: undefined,
    dhSelfPub: pub,
    dhSelfPriv: priv,
    dhRemote: theirDhPub,
    ns: 0,
    nr: 0,
    pn: 0,
    skipped: {},
    updated: Date.now(),
  };
}

async function initReceiverState(peerId: string, senderDhPub: string, algoHint?: string): Promise<RatchetState> {
  const algo = algoHint || getLongTermDhAlgo();
  const ourPriv = await getLongTermDhPrivateKey();
  const dhOut = await deriveDhSecretWithKey(algo, ourPriv, senderDhPub);
  const { rk, ck } = await kdfRK(new Uint8Array(32).buffer, dhOut);
  const { pub, priv } = await generateRatchetKeyPair(algo);
  return {
    algo,
    rk: bufToBase64(rk.buffer),
    cks: undefined,
    ckr: bufToBase64(ck.buffer),
    dhSelfPub: pub,
    dhSelfPriv: priv,
    dhRemote: senderDhPub,
    ns: 0,
    nr: 0,
    pn: 0,
    skipped: {},
    updated: Date.now(),
  };
}

async function ensureSendChain(state: RatchetState): Promise<RatchetState> {
  if (state.cks) return state;
  const rkBytes = ensureArrayBuf(state.rk);
  const dhOut = await deriveDhSecret(state.algo, state.dhSelfPriv, state.dhRemote);
  const { rk, ck } = await kdfRK(rkBytes, dhOut);
  state.rk = bufToBase64(rk.buffer);
  state.cks = bufToBase64(ck.buffer);
  state.updated = Date.now();
  return state;
}

async function skipMessageKeys(state: RatchetState, until: number): Promise<void> {
  if (!state.ckr) return;
  const skipped = state.skipped || {};
  while (state.nr < until) {
    const { ck, mk } = await kdfCK(base64ToBuf(state.ckr));
    const keyId = `${state.dhRemote}:${state.nr}`;
    if (Object.keys(skipped).length < MAX_SKIP) {
      skipped[keyId] = bufToBase64(mk.buffer);
    } else {
      recordTelemetry('ratchet_skip_overflow');
    }
    state.ckr = bufToBase64(ck.buffer);
    state.nr += 1;
  }
  state.skipped = skipped;
}

async function dhRatchet(state: RatchetState, remoteDh: string, pn: number): Promise<RatchetState> {
  // Skip remaining keys in old chain
  await skipMessageKeys(state, pn);
  state.pn = state.ns;
  state.ns = 0;
  state.nr = 0;
  state.dhRemote = remoteDh;

  // Step 1: new receiving chain
  const rkBytes = ensureArrayBuf(state.rk);
  const dhOut1 = await deriveDhSecret(state.algo, state.dhSelfPriv, state.dhRemote);
  const out1 = await kdfRK(rkBytes, dhOut1);
  state.rk = bufToBase64(out1.rk.buffer);
  state.ckr = bufToBase64(out1.ck.buffer);

  // Step 2: new sending chain with a fresh DH key
  const fresh = await generateRatchetKeyPair(state.algo);
  state.dhSelfPub = fresh.pub;
  state.dhSelfPriv = fresh.priv;
  const dhOut2 = await deriveDhSecret(state.algo, state.dhSelfPriv, state.dhRemote);
  const out2 = await kdfRK(ensureArrayBuf(state.rk), dhOut2);
  state.rk = bufToBase64(out2.rk.buffer);
  state.cks = bufToBase64(out2.ck.buffer);
  state.updated = Date.now();
  return state;
}

export async function ratchetEncryptDM(
  peerId: string,
  theirDhPub: string,
  plaintext: string,
): Promise<string> {
  let state = await getState(peerId);
  if (!state) {
    state = await initSenderState(peerId, theirDhPub);
  }
  state = await ensureSendChain(state);
  const { ck, mk } = await kdfCK(base64ToBuf(state.cks!));
  const n = state.ns;
  state.ns += 1;
  state.cks = bufToBase64(ck.buffer);
  const header = { v: 2, dh: state.dhSelfPub, pn: state.pn, n, alg: state.algo };
  const aad = headerAad(header);
  const ct = await aesGcmEncrypt(mk.buffer, plaintext, aad);
  const payload = { h: header, ct };
  const wrapped = bufToBase64(utf8ToBuf(JSON.stringify(payload)));
  state.updated = Date.now();
  await setState(peerId, state);
  return `dr2:${wrapped}`;
}

export async function ratchetDecryptDM(peerId: string, ciphertext: string): Promise<string> {
  if (!ciphertext.startsWith('dr2:')) {
    throw new Error('legacy');
  }
  const raw = ciphertext.slice(4);
  const payload = JSON.parse(new TextDecoder().decode(base64ToBuf(raw)));
  const header = payload.h || {};
  const ct = String(payload.ct || '');
  const remoteDh = String(header.dh || '');
  const pn = Number(header.pn || 0);
  const n = Number(header.n || 0);
  const alg = String(header.alg || getLongTermDhAlgo());

  let state = await getState(peerId);
  if (!state) {
    state = await initReceiverState(peerId, remoteDh, alg);
  }

  if (remoteDh && remoteDh !== state.dhRemote) {
    state = await dhRatchet(state, remoteDh, pn);
  }

  const skipped = state.skipped || {};
  const skipKey = `${remoteDh}:${n}`;
  if (skipped[skipKey]) {
    const mk = base64ToBuf(skipped[skipKey]);
    delete skipped[skipKey];
    state.skipped = skipped;
    await setState(peerId, state);
    return aesGcmDecrypt(mk, ct, headerAad(header));
  }

  await skipMessageKeys(state, n);
  if (!state.ckr) throw new Error('no_receive_chain');
  const { ck, mk } = await kdfCK(base64ToBuf(state.ckr));
  state.ckr = bufToBase64(ck.buffer);
  state.nr += 1;
  state.updated = Date.now();
  await setState(peerId, state);
  return aesGcmDecrypt(mk.buffer, ct, headerAad(header));
}

export function ratchetHasState(peerId: string): boolean {
  if (!stateCache) {
    void loadAllStates();
  }
  return Boolean(stateCache?.[peerId]);
}

export function ratchetReset(peerId: string): void {
  void (async () => {
    const all = await loadAllStates();
    if (all[peerId]) {
      delete all[peerId];
      await saveAllStates(all);
    }
  })();
}

export function ratchetResetAll(): void {
  stateCache = {};
  stateLoadPromise = Promise.resolve(stateCache);
  void saveAllStates({});
}

export function getLongTermDhPublicKey(): string {
  return getLongTermDhPub();
}
