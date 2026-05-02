import { beforeEach, describe, expect, it, vi } from 'vitest';

type StoreRecord = Map<string, unknown>;
type DbRecord = {
  version: number;
  stores: Map<string, StoreRecord>;
};

const databases = new Map<string, DbRecord>();
const deletedDatabases: string[] = [];

function domStringList(record: DbRecord): DOMStringList {
  return {
    contains: (name: string) => record.stores.has(name),
    item: (index: number) => Array.from(record.stores.keys())[index] ?? null,
    get length() {
      return record.stores.size;
    },
  } as DOMStringList;
}

function makeRequest<T>(
  executor: (request: IDBRequest<T>) => void,
  tx?: IDBTransaction,
): IDBRequest<T> {
  const request = {} as IDBRequest<T>;
  queueMicrotask(() => {
    executor(request);
    tx?.oncomplete?.(new Event('complete') as Event);
  });
  return request;
}

function makeObjectStore(record: DbRecord, name: string, tx: IDBTransaction): IDBObjectStore {
  const store = record.stores.get(name);
  if (!store) throw new Error(`missing object store ${name}`);
  return {
    get(key: IDBValidKey) {
      return makeRequest((request) => {
        (request as { result?: unknown }).result = store.get(String(key));
        request.onsuccess?.(new Event('success') as Event);
      }, tx);
    },
    put(value: unknown, key?: IDBValidKey) {
      return makeRequest((request) => {
        store.set(String(key ?? ''), value);
        (request as { result?: unknown }).result = key;
        request.onsuccess?.(new Event('success') as Event);
      }, tx);
    },
    delete(key: IDBValidKey) {
      return makeRequest((request) => {
        store.delete(String(key));
        request.onsuccess?.(new Event('success') as Event);
      }, tx);
    },
    clear() {
      return makeRequest((request) => {
        store.clear();
        request.onsuccess?.(new Event('success') as Event);
      }, tx);
    },
  } as unknown as IDBObjectStore;
}

function makeTransaction(record: DbRecord): IDBTransaction {
  const tx = {
    oncomplete: null,
    onerror: null,
    onabort: null,
    objectStore: (name: string) => makeObjectStore(record, name, tx as unknown as IDBTransaction),
  } as unknown as IDBTransaction;
  return tx;
}

function makeDb(name: string, record: DbRecord): IDBDatabase {
  return {
    name,
    version: record.version,
    objectStoreNames: domStringList(record),
    createObjectStore(storeName: string) {
      if (!record.stores.has(storeName)) {
        record.stores.set(storeName, new Map());
      }
      return {} as IDBObjectStore;
    },
    transaction(_storeName: string | string[]) {
      return makeTransaction(record);
    },
    close() {
      /* noop */
    },
  } as unknown as IDBDatabase;
}

function createFakeIndexedDb() {
  return {
    open(name: string, version?: number) {
      const request = {} as IDBOpenDBRequest;
      queueMicrotask(() => {
        const resolvedVersion = Number(version || 1);
        let record = databases.get(name);
        const upgrading = !record || resolvedVersion > record.version;
        if (!record) {
          record = { version: resolvedVersion, stores: new Map() };
          databases.set(name, record);
        }
        if (upgrading) {
          record.version = resolvedVersion;
          (request as { result?: IDBDatabase }).result = makeDb(name, record);
          request.onupgradeneeded?.(new Event('upgradeneeded') as IDBVersionChangeEvent);
        }
        (request as { result?: IDBDatabase }).result = makeDb(name, record);
        request.onsuccess?.(new Event('success') as Event);
      });
      return request;
    },
    deleteDatabase(name: string) {
      const request = {} as IDBOpenDBRequest;
      queueMicrotask(() => {
        deletedDatabases.push(name);
        databases.delete(name);
        request.onsuccess?.(new Event('success') as Event);
      });
      return request;
    },
  };
}

function ensureStore(name: string, version: number, storeName: string): StoreRecord {
  let record = databases.get(name);
  if (!record) {
    record = { version, stores: new Map() };
    databases.set(name, record);
  }
  record.version = Math.max(record.version, version);
  if (!record.stores.has(storeName)) {
    record.stores.set(storeName, new Map());
  }
  return record.stores.get(storeName)!;
}

function getStoredValue(name: string, storeName: string, key: string): unknown {
  return databases.get(name)?.stores.get(storeName)?.get(key);
}

describe('gate worker vault hardening', () => {
  beforeEach(() => {
    vi.resetModules();
    databases.clear();
    deletedDatabases.length = 0;
    Object.defineProperty(globalThis, 'indexedDB', {
      value: createFakeIndexedDb(),
      configurable: true,
      writable: true,
    });
  });

  it('persists worker gate state as an encrypted blob instead of raw state', async () => {
    const mod = await import('@/mesh/meshGateWorkerVault');
    const sample = {
      gate_id: 'infonet',
      epoch: 7,
      rust_state_blob_b64: 'blob-private',
      members: [
        {
          persona_id: 'persona-a',
          node_id: '!sb_gate',
          identity_scope: 'persona',
          group_handle: 11,
        },
      ],
      active_identity_scope: 'persona',
      active_persona_id: 'persona-a',
      active_node_id: '!sb_gate',
    };

    await mod.writeWorkerGateState(sample);

    const raw = getStoredValue(mod.WORKER_GATE_DB, 'gate_state', 'infonet');
    expect(typeof raw).toBe('string');
    expect(String(raw)).not.toContain('blob-private');
    expect(String(raw)).not.toContain('persona-a');

    const loaded = await mod.readWorkerGateState('infonet');
    expect(loaded).toEqual(sample);
  });

  it('migrates legacy plaintext gate state into encrypted storage on read', async () => {
    const legacyStore = ensureStore('sb_mesh_gate_worker', 1, 'gate_state');
    ensureStore('sb_mesh_gate_worker', 1, 'meta');
    legacyStore.set('infonet', {
      gate_id: 'infonet',
      epoch: 4,
      rust_state_blob_b64: 'legacy-blob',
      members: [],
      active_identity_scope: 'anonymous',
      active_persona_id: '',
      active_node_id: '!sb_legacy',
    });

    const mod = await import('@/mesh/meshGateWorkerVault');
    const loaded = await mod.readWorkerGateState('infonet');
    const raw = getStoredValue(mod.WORKER_GATE_DB, 'gate_state', 'infonet');

    expect(loaded?.rust_state_blob_b64).toBe('legacy-blob');
    expect(typeof raw).toBe('string');
    expect(String(raw)).not.toContain('legacy-blob');
  });

  it('drops stale encrypted gate state when the wrap key is missing so the room can resync cleanly', async () => {
    const gateStore = ensureStore('sb_mesh_gate_worker', 1, 'gate_state');
    gateStore.set('infonet', 'encrypted-state-that-cannot-be-opened');
    ensureStore('sb_mesh_gate_worker', 1, 'meta');

    const mod = await import('@/mesh/meshGateWorkerVault');
    await expect(mod.readWorkerGateState('infonet')).resolves.toBeNull();
    expect(getStoredValue(mod.WORKER_GATE_DB, 'gate_state', 'infonet')).toBeUndefined();
  });

  it('deleteWorkerGateDatabase removes the persisted gate vault', async () => {
    const mod = await import('@/mesh/meshGateWorkerVault');
    await mod.deleteWorkerGateDatabase();
    expect(deletedDatabases).toContain('sb_mesh_gate_worker');
  });
});
