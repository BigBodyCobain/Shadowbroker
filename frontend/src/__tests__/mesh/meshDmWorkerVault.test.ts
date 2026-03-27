import { beforeEach, describe, expect, it, vi } from 'vitest';

type StoreRecord = Map<string, unknown>;
type DbRecord = {
  version: number;
  stores: Map<string, StoreRecord>;
};

const databases = new Map<string, DbRecord>();
const deletedDatabases: string[] = [];
const workerInstances: FakeWorker[] = [];

vi.mock('@/lib/controlPlane', () => ({
  controlPlaneJson: vi.fn(),
}));

vi.mock('@/mesh/wormholeIdentityClient', () => ({
  ensureWormholeReadyForSecureAction: vi.fn(async () => undefined),
  isWormholeReady: vi.fn(async () => false),
}));

vi.mock('@/mesh/meshIdentity', () => ({
  getDHAlgo: vi.fn(() => 'X25519'),
}));

function makeStorage() {
  const values = new Map<string, string>();
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => void values.set(key, value),
    removeItem: (key: string) => void values.delete(key),
    clear: () => void values.clear(),
    get length() {
      return values.size;
    },
    key: (_i: number) => null as string | null,
  };
}

class FakeWorker {
  onmessage: ((event: MessageEvent<{ id: string; ok: boolean; result?: string }>) => void) | null =
    null;
  terminated = false;

  constructor() {
    workerInstances.push(this);
  }

  postMessage(message: { id: string }) {
    queueMicrotask(() => {
      this.onmessage?.({
        data: { id: message.id, ok: true, result: '' },
      } as MessageEvent<{ id: string; ok: boolean; result?: string }>);
    });
  }

  terminate() {
    this.terminated = true;
  }
}

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
    transaction(storeName: string | string[]) {
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

describe('worker ratchet vault hardening', () => {
  beforeEach(() => {
    vi.resetModules();
    databases.clear();
    deletedDatabases.length = 0;
    workerInstances.length = 0;
    Object.defineProperty(globalThis, 'localStorage', {
      value: makeStorage(),
      configurable: true,
      writable: true,
    });
    Object.defineProperty(globalThis, 'sessionStorage', {
      value: makeStorage(),
      configurable: true,
      writable: true,
    });
    Object.defineProperty(globalThis, 'Worker', {
      value: FakeWorker,
      configurable: true,
      writable: true,
    });
    Object.defineProperty(globalThis, 'indexedDB', {
      value: createFakeIndexedDb(),
      configurable: true,
      writable: true,
    });
  });

  it('persists worker ratchet state as an encrypted blob instead of raw state', async () => {
    const mod = await import('@/mesh/meshDmWorkerVault');
    const sample = {
      alice: {
        algo: 'X25519',
        rk: 'root-key',
        cks: 'send-chain',
        ckr: 'recv-chain',
        dhSelfPub: 'pub',
        dhSelfPriv: 'private-material',
        dhRemote: 'remote',
        ns: 1,
        nr: 2,
        pn: 3,
        skipped: { 'remote:1': 'mk' },
        updated: 123,
      },
    };

    await mod.writeWorkerRatchetStates(sample);

    const raw = getStoredValue(mod.WORKER_RATCHET_DB, 'ratchet', 'state');
    expect(typeof raw).toBe('string');
    expect(String(raw)).not.toContain('dhSelfPriv');
    expect(String(raw)).not.toContain('private-material');

    const loaded = await mod.readWorkerRatchetStates();
    expect(loaded).toEqual(sample);
  });

  it('migrates legacy plaintext worker state into encrypted storage on read', async () => {
    const legacyStore = ensureStore('sb_mesh_dm_worker', 1, 'ratchet');
    legacyStore.set('state', {
      bob: {
        algo: 'X25519',
        rk: 'legacy-rk',
        dhSelfPub: 'legacy-pub',
        dhSelfPriv: 'legacy-private',
        dhRemote: 'legacy-remote',
        ns: 0,
        nr: 0,
        pn: 0,
        updated: 999,
      },
    });

    const mod = await import('@/mesh/meshDmWorkerVault');
    const loaded = await mod.readWorkerRatchetStates();
    const raw = getStoredValue(mod.WORKER_RATCHET_DB, 'ratchet', 'state');

    expect(loaded.bob?.dhSelfPriv).toBe('legacy-private');
    expect(typeof raw).toBe('string');
    expect(String(raw)).not.toContain('legacy-private');
  });

  it('purgeBrowserDmState clears worker persistence and legacy browser copies', async () => {
    localStorage.setItem('sb_mesh_dm_ratchet', 'legacy');
    sessionStorage.setItem('sb_mesh_ratchet_telemetry', '{"seen":1}');
    const mod = await import('@/mesh/meshDmWorkerClient');

    await mod.purgeBrowserDmState();

    expect(localStorage.getItem('sb_mesh_dm_ratchet')).toBeNull();
    expect(sessionStorage.getItem('sb_mesh_ratchet_telemetry')).toBeNull();
    expect(deletedDatabases).toContain('sb_mesh_dm_worker');
    expect(workerInstances[0]?.terminated).toBe(true);
  });
});
