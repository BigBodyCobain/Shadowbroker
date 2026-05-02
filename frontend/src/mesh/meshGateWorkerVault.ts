export type WorkerGateStateMember = {
  persona_id: string;
  node_id: string;
  identity_scope: string;
  group_handle: number;
};

export type WorkerGateStateSnapshot = {
  gate_id: string;
  epoch: number;
  rust_state_blob_b64: string;
  members: WorkerGateStateMember[];
  active_identity_scope: string;
  active_persona_id: string;
  active_node_id: string;
};

export const WORKER_GATE_DB = 'sb_mesh_gate_worker';
const WORKER_GATE_DB_VERSION = 1;
const WORKER_GATE_STATE_STORE = 'gate_state';
const WORKER_GATE_META_STORE = 'meta';
const WORKER_GATE_WRAP_KEY_ID = 'gate_wrap_key';

function openWorkerGateDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const open = indexedDB.open(WORKER_GATE_DB, WORKER_GATE_DB_VERSION);
    open.onupgradeneeded = () => {
      const db = open.result;
      if (!db.objectStoreNames.contains(WORKER_GATE_STATE_STORE)) {
        db.createObjectStore(WORKER_GATE_STATE_STORE);
      }
      if (!db.objectStoreNames.contains(WORKER_GATE_META_STORE)) {
        db.createObjectStore(WORKER_GATE_META_STORE);
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
  return readValue<CryptoKey>(db, WORKER_GATE_META_STORE, WORKER_GATE_WRAP_KEY_ID);
}

async function getOrCreateWrapKey(db: IDBDatabase): Promise<CryptoKey> {
  const existing = await getStoredWrapKey(db);
  if (existing) return existing;
  const key = await crypto.subtle.generateKey({ name: 'AES-GCM', length: 256 }, false, [
    'encrypt',
    'decrypt',
  ]);
  await writeValue(db, WORKER_GATE_META_STORE, WORKER_GATE_WRAP_KEY_ID, key);
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
    throw new Error('worker_gate_wrap_key_missing');
  }
  const combined = Uint8Array.from(atob(encrypted), (char) => char.charCodeAt(0));
  const iv = combined.slice(0, 12);
  const ciphertext = combined.slice(12);
  const decrypted = await crypto.subtle.decrypt({ name: 'AES-GCM', iv }, key, ciphertext);
  return new TextDecoder().decode(decrypted);
}

function normalizeSnapshot(value: unknown): WorkerGateStateSnapshot | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const snapshot = value as WorkerGateStateSnapshot;
  if (!snapshot.gate_id || !snapshot.rust_state_blob_b64) return null;
  return snapshot;
}

export async function readWorkerGateState(gateId: string): Promise<WorkerGateStateSnapshot | null> {
  const db = await openWorkerGateDb();
  try {
    const persisted = await readValue<unknown>(db, WORKER_GATE_STATE_STORE, gateId);
    if (persisted == null) return null;
    if (typeof persisted === 'string') {
      try {
        const decrypted = await decryptSerializedState(db, persisted);
        return normalizeSnapshot(JSON.parse(decrypted));
      } catch {
        await deleteValue(db, WORKER_GATE_STATE_STORE, gateId);
        return null;
      }
    }
    const legacy = normalizeSnapshot(persisted);
    if (legacy) {
      try {
        const encrypted = await encryptSerializedState(db, JSON.stringify(legacy));
        await writeValue(db, WORKER_GATE_STATE_STORE, gateId, encrypted);
      } catch {
        await deleteValue(db, WORKER_GATE_STATE_STORE, gateId);
      }
    }
    return legacy;
  } finally {
    db.close();
  }
}

export async function writeWorkerGateState(snapshot: WorkerGateStateSnapshot): Promise<void> {
  const db = await openWorkerGateDb();
  try {
    const encrypted = await encryptSerializedState(db, JSON.stringify(snapshot));
    await writeValue(db, WORKER_GATE_STATE_STORE, snapshot.gate_id, encrypted);
  } finally {
    db.close();
  }
}

export async function deleteWorkerGateState(gateId: string): Promise<void> {
  const db = await openWorkerGateDb();
  try {
    await deleteValue(db, WORKER_GATE_STATE_STORE, gateId);
  } finally {
    db.close();
  }
}

export async function clearWorkerGateStates(): Promise<void> {
  const db = await openWorkerGateDb();
  try {
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(WORKER_GATE_STATE_STORE, 'readwrite');
      tx.objectStore(WORKER_GATE_STATE_STORE).clear();
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error);
    });
  } finally {
    db.close();
  }
}

export async function probeWorkerGateVaultAvailability(): Promise<{ ok: boolean; reason: string }> {
  if (typeof indexedDB === 'undefined') {
    return { ok: false, reason: 'browser_gate_indexeddb_unavailable' };
  }
  try {
    const db = await openWorkerGateDb();
    db.close();
    return { ok: true, reason: '' };
  } catch {
    return { ok: false, reason: 'browser_gate_storage_unavailable' };
  }
}

export async function deleteWorkerGateDatabase(): Promise<void> {
  if (typeof indexedDB === 'undefined') return;
  await new Promise<void>((resolve) => {
    try {
      const req = indexedDB.deleteDatabase(WORKER_GATE_DB);
      req.onsuccess = () => resolve();
      req.onerror = () => resolve();
      req.onblocked = () => resolve();
    } catch {
      resolve();
    }
  });
}
