const DB_NAME = 'sb_mesh_keystore';
const DB_VERSION = 1;
const STORE_KEYS = 'keys';

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE_KEYS)) {
        db.createObjectStore(STORE_KEYS);
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function withStore<T>(
  mode: IDBTransactionMode,
  handler: (store: IDBObjectStore) => IDBRequest,
): Promise<T> {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_KEYS, mode);
    const store = tx.objectStore(STORE_KEYS);
    const req = handler(store);
    req.onsuccess = () => resolve(req.result as T);
    req.onerror = () => reject(req.error);
    tx.oncomplete = () => db.close();
    tx.onerror = () => {
      db.close();
      reject(tx.error);
    };
  });
}

export async function setKey(id: string, key: CryptoKey): Promise<void> {
  await withStore<void>('readwrite', (store) => store.put(key, id));
}

export async function getKey(id: string): Promise<CryptoKey | null> {
  try {
    const result = await withStore<CryptoKey | undefined>('readonly', (store) => store.get(id));
    return result || null;
  } catch {
    return null;
  }
}

export async function deleteKey(id: string): Promise<void> {
  try {
    await withStore<void>('readwrite', (store) => store.delete(id));
  } catch {
    /* ignore */
  }
}
