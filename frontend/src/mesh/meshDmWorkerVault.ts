export type WorkerRatchetState = {
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

export const WORKER_RATCHET_DB = 'sb_mesh_dm_worker';
const WORKER_RATCHET_DB_VERSION = 2;
const WORKER_RATCHET_STATE_STORE = 'ratchet';
const WORKER_RATCHET_META_STORE = 'meta';
const WORKER_RATCHET_STATE_KEY = 'state';
const WORKER_RATCHET_WRAP_KEY_ID = 'ratchet_wrap_key';

function openWorkerRatchetDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const open = indexedDB.open(WORKER_RATCHET_DB, WORKER_RATCHET_DB_VERSION);
    open.onupgradeneeded = () => {
      const db = open.result;
      if (!db.objectStoreNames.contains(WORKER_RATCHET_STATE_STORE)) {
        db.createObjectStore(WORKER_RATCHET_STATE_STORE);
      }
      if (!db.objectStoreNames.contains(WORKER_RATCHET_META_STORE)) {
        db.createObjectStore(WORKER_RATCHET_META_STORE);
      }
    };
    open.onsuccess = () => resolve(open.result);
    open.onerror = () => reject(open.error);
  });
}

function readValue<T>(db: IDBDatabase, storeName: string, key: string): Promise<T | null> {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(storeName, 'readonly');
    const store = tx.objectStore(storeName);
    const req = store.get(key);
    req.onsuccess = () => resolve((req.result as T | undefined) ?? null);
    req.onerror = () => reject(req.error);
    tx.onabort = () => reject(tx.error);
  });
}

function writeValue(db: IDBDatabase, storeName: string, key: string, value: unknown): Promise<void> {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(storeName, 'readwrite');
    tx.objectStore(storeName).put(value, key);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
    tx.onabort = () => reject(tx.error);
  });
}

function deleteValue(db: IDBDatabase, storeName: string, key: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(storeName, 'readwrite');
    tx.objectStore(storeName).delete(key);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
    tx.onabort = () => reject(tx.error);
  });
}

async function getStoredWrapKey(db: IDBDatabase): Promise<CryptoKey | null> {
  return readValue<CryptoKey>(db, WORKER_RATCHET_META_STORE, WORKER_RATCHET_WRAP_KEY_ID);
}

async function getOrCreateWrapKey(db: IDBDatabase): Promise<CryptoKey> {
  const existing = await getStoredWrapKey(db);
  if (existing) return existing;
  const key = await crypto.subtle.generateKey({ name: 'AES-GCM', length: 256 }, false, [
    'encrypt',
    'decrypt',
  ]);
  await writeValue(db, WORKER_RATCHET_META_STORE, WORKER_RATCHET_WRAP_KEY_ID, key);
  return key;
}

async function encryptSerializedState(db: IDBDatabase, serialized: string): Promise<string> {
  const key = await getOrCreateWrapKey(db);
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const encoded = new TextEncoder().encode(serialized);
  const ciphertext = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, encoded);
  const combined = new Uint8Array(iv.length + ciphertext.byteLength);
  combined.set(iv);
  combined.set(new Uint8Array(ciphertext), iv.length);
  return btoa(String.fromCharCode(...combined));
}

async function decryptSerializedState(db: IDBDatabase, encrypted: string): Promise<string> {
  const key = await getStoredWrapKey(db);
  if (!key) {
    throw new Error('worker_ratchet_wrap_key_missing');
  }
  const combined = Uint8Array.from(atob(encrypted), (char) => char.charCodeAt(0));
  const iv = combined.slice(0, 12);
  const ciphertext = combined.slice(12);
  const decrypted = await crypto.subtle.decrypt({ name: 'AES-GCM', iv }, key, ciphertext);
  return new TextDecoder().decode(decrypted);
}

function normalizeStateRecord(
  value: unknown,
): Record<string, WorkerRatchetState> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
  return value as Record<string, WorkerRatchetState>;
}

export async function readWorkerRatchetStates(): Promise<Record<string, WorkerRatchetState>> {
  const db = await openWorkerRatchetDb();
  try {
    const persisted = await readValue<unknown>(db, WORKER_RATCHET_STATE_STORE, WORKER_RATCHET_STATE_KEY);
    if (persisted == null) return {};
    if (typeof persisted === 'string') {
      const decrypted = await decryptSerializedState(db, persisted);
      return normalizeStateRecord(JSON.parse(decrypted));
    }

    const legacy = normalizeStateRecord(persisted);
    if (Object.keys(legacy).length > 0) {
      try {
        const encrypted = await encryptSerializedState(db, JSON.stringify(legacy));
        await writeValue(db, WORKER_RATCHET_STATE_STORE, WORKER_RATCHET_STATE_KEY, encrypted);
      } catch {
        await deleteValue(db, WORKER_RATCHET_STATE_STORE, WORKER_RATCHET_STATE_KEY);
      }
    }
    return legacy;
  } finally {
    db.close();
  }
}

export async function writeWorkerRatchetStates(
  states: Record<string, WorkerRatchetState>,
): Promise<void> {
  const db = await openWorkerRatchetDb();
  try {
    const encrypted = await encryptSerializedState(db, JSON.stringify(states));
    await writeValue(db, WORKER_RATCHET_STATE_STORE, WORKER_RATCHET_STATE_KEY, encrypted);
  } finally {
    db.close();
  }
}

export async function clearWorkerRatchetStates(): Promise<void> {
  await writeWorkerRatchetStates({});
}

export async function deleteWorkerRatchetDatabase(): Promise<void> {
  if (typeof indexedDB === 'undefined') return;
  await new Promise<void>((resolve) => {
    try {
      const req = indexedDB.deleteDatabase(WORKER_RATCHET_DB);
      req.onsuccess = () => resolve();
      req.onerror = () => resolve();
      req.onblocked = () => resolve();
    } catch {
      resolve();
    }
  });
}
