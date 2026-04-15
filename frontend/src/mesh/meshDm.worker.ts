/// <reference lib="webworker" />

import {
  readWorkerRatchetStates,
  writeWorkerRatchetStates,
  type WorkerRatchetState as RatchetState,
} from './meshDmWorkerVault';

const MAX_SKIP = 32;
const PAD_BUCKET = 1024;
const PAD_STEP = 512;
const PAD_MAX = 4096;
const PAD_MAGIC = 'SBP1';

const KEYSTORE_DB = 'sb_mesh_keystore';
const KEYSTORE_STORE = 'keys';
const KEY_DH_PRIV_IDB = 'sb_mesh_dh_priv';

let stateCache: Record<string, RatchetState> | null = null;
let stateLoadPromise: Promise<Record<string, RatchetState>> | null = null;
let lastOp: Promise<void> = Promise.resolve();

type WorkerRequest = {
  id: string;
  action: 'encrypt' | 'decrypt' | 'reset';
  peerId?: string;
  peerDhPub?: string;
  plaintext?: string;
  ciphertext?: string;
  dhAlgo?: string;
};

function bufToBase64(buf: ArrayBufferLike): string {
  return btoa(String.fromCharCode(...new Uint8Array(buf)));
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

function ensureArrayBuf(value?: string): ArrayBuffer {
  if (!value) return new Uint8Array(32).buffer;
  return base64ToBuf(value);
}

function headerAad(header: Record<string, unknown>): Uint8Array {
  return new TextEncoder().encode(stableStringify(header));
}

function buildPaddedPayload(plaintext: string): Uint8Array {
  const data = new TextEncoder().encode(plaintext);
  const len = data.length;
  let target = PAD_BUCKET;
  if (len + 6 > target) {
    target = Math.ceil((len + 6) / PAD_STEP) * PAD_STEP;
  }
  if (target > PAD_MAX) {
    const raw = new Uint8Array(len);
    raw.set(data, 0);
    return raw;
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

function openDb(name: string, store: string): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(name, 1);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(store)) {
        db.createObjectStore(store);
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function loadAllStates(): Promise<Record<string, RatchetState>> {
  if (stateCache) return stateCache;
  if (!stateLoadPromise) {
    stateLoadPromise = (async () => {
      try {
        stateCache = (await readWorkerRatchetStates()) || {};
        return stateCache;
      } catch {
        stateCache = {};
        return stateCache;
      }
    })();
  }
  return stateLoadPromise;
}

async function saveAllStates(states: Record<string, RatchetState>): Promise<void> {
  stateCache = states;
  stateLoadPromise = Promise.resolve(states);
  try {
    await writeWorkerRatchetStates(states);
  } catch (err) {
    console.warn('[mesh] worker ratchet vault unavailable — state kept in memory only, not persisted', err);
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

async function clearState(peerId?: string): Promise<void> {
  if (!peerId) {
    await saveAllStates({});
    return;
  }
  const all = await loadAllStates();
  if (all[peerId]) {
    delete all[peerId];
    await saveAllStates(all);
  }
}

async function getLongTermDhPrivKey(): Promise<CryptoKey | null> {
  try {
    const db = await openDb(KEYSTORE_DB, KEYSTORE_STORE);
    const tx = db.transaction(KEYSTORE_STORE, 'readonly');
    const store = tx.objectStore(KEYSTORE_STORE);
    const req = store.get(KEY_DH_PRIV_IDB);
    const key = await new Promise<CryptoKey | null>((resolve) => {
      req.onsuccess = () => resolve((req.result as CryptoKey) || null);
      req.onerror = () => resolve(null);
    });
    db.close();
    return key;
  } catch {
    return null;
  }
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

async function skipMessageKeys(state: RatchetState, until: number): Promise<void> {
  if (!state.ckr) return;
  const skipped = state.skipped || {};
  while (state.nr < until) {
    const { ck, mk } = await kdfCK(base64ToBuf(state.ckr));
    const keyId = `${state.dhRemote}:${state.nr}`;
    if (Object.keys(skipped).length < MAX_SKIP) {
      skipped[keyId] = bufToBase64(mk.buffer);
    }
    state.ckr = bufToBase64(ck.buffer);
    state.nr += 1;
  }
  state.skipped = skipped;
}

async function dhRatchet(state: RatchetState, remoteDh: string, pn: number): Promise<RatchetState> {
  await skipMessageKeys(state, pn);
  state.pn = state.ns;
  state.ns = 0;
  state.nr = 0;
  state.dhRemote = remoteDh;

  const rkBytes = ensureArrayBuf(state.rk);
  const dhOut1 = await deriveDhSecret(state.algo, state.dhSelfPriv, state.dhRemote);
  const out1 = await kdfRK(rkBytes, dhOut1);
  state.rk = bufToBase64(out1.rk.buffer);
  state.ckr = bufToBase64(out1.ck.buffer);

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

async function initSenderState(peerId: string, theirDhPub: string, algoHint: string): Promise<RatchetState> {
  const { pub, priv, algo } = await generateRatchetKeyPair(algoHint);
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

async function initReceiverState(
  peerId: string,
  senderDhPub: string,
  algoHint: string,
): Promise<RatchetState> {
  const algo = (algoHint || '').toUpperCase() === 'ECDH' ? 'ECDH' : 'X25519';
  const longTermKey = await getLongTermDhPrivKey();
  if (!longTermKey) {
    throw new Error('missing_long_term_key');
  }
  const dhOut = await deriveDhSecretWithKey(algo, longTermKey, senderDhPub);
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

async function ratchetEncrypt(peerId: string, theirDhPub: string, plaintext: string, algoHint: string): Promise<string> {
  let state = await getState(peerId);
  if (!state) {
    state = await initSenderState(peerId, theirDhPub, algoHint);
  }
  state = await ensureSendChain(state);
  const { ck, mk } = await kdfCK(base64ToBuf(state.cks!));
  const n = state.ns;
  state.ns += 1;
  state.cks = bufToBase64(ck.buffer);
  const header = { v: 2, dh: state.dhSelfPub, pn: state.pn, n, alg: state.algo };
  const ct = await aesGcmEncrypt(mk.buffer, plaintext, headerAad(header));
  const payload = { h: header, ct };
  const wrapped = bufToBase64(utf8ToBuf(JSON.stringify(payload)));
  state.updated = Date.now();
  await setState(peerId, state);
  return `dr2:${wrapped}`;
}

async function ratchetDecrypt(peerId: string, ciphertext: string, algoHint: string): Promise<string> {
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
  const alg = String(header.alg || algoHint || 'X25519');

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

function handleMessage(event: MessageEvent) {
  const data = event.data as WorkerRequest;
  const { id, action } = data || {};
  if (!id || !action) return;
  lastOp = lastOp.then(async () => {
    try {
      if (action === 'encrypt') {
        const result = await ratchetEncrypt(
          String(data.peerId || ''),
          String(data.peerDhPub || ''),
          String(data.plaintext || ''),
          String(data.dhAlgo || 'X25519'),
        );
        postMessage({ id, ok: true, result });
        return;
      }
      if (action === 'decrypt') {
        const result = await ratchetDecrypt(
          String(data.peerId || ''),
          String(data.ciphertext || ''),
          String(data.dhAlgo || 'X25519'),
        );
        postMessage({ id, ok: true, result });
        return;
      }
      if (action === 'reset') {
        const peerId = String(data.peerId || '');
        await clearState(peerId || undefined);
        postMessage({ id, ok: true, result: '' });
        return;
      }
      postMessage({ id, ok: false, error: 'unsupported_action' });
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : String((err as { message?: string })?.message || err);
      postMessage({ id, ok: false, error: message || 'worker_error' });
    }
  });
}

self.onmessage = handleMessage;
