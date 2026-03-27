import { beforeEach, describe, expect, it, vi } from 'vitest';

// Track what gets stored in IndexedDB
const idbStore = new Map<string, unknown>();
const deletedDatabases: string[] = [];

vi.mock('@/lib/controlPlane', () => ({
  controlPlaneJson: vi.fn(),
}));

vi.mock('@/mesh/meshKeyStore', () => ({
  getKey: vi.fn(async (id: string) => idbStore.get(id) ?? null),
  setKey: vi.fn(async (id: string, key: unknown) => {
    idbStore.set(id, key);
  }),
  deleteKey: vi.fn(async (id: string) => {
    idbStore.delete(id);
  }),
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

describe('signing key storage hardening', () => {
  beforeEach(() => {
    vi.resetModules();
    idbStore.clear();
    deletedDatabases.length = 0;
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
    Object.defineProperty(globalThis, 'indexedDB', {
      value: {
        deleteDatabase: vi.fn((name: string) => {
          deletedDatabases.push(name);
          const request = {} as IDBOpenDBRequest;
          queueMicrotask(() => {
            request.onsuccess?.(new Event('success') as Event);
          });
          return request;
        }),
      },
      configurable: true,
      writable: true,
    });
  });

  it('getNodeIdentity returns identity even when privateKey is empty (post-migration)', async () => {
    const mod = await import('@/mesh/meshIdentity');

    // Simulate a state where the signing key has already been migrated:
    // publicKey and nodeId exist, but privateKey does not.
    localStorage.setItem('sb_mesh_pubkey', 'test-pub');
    localStorage.setItem('sb_mesh_node_id', '!sb_abcd1234abcd1234');
    localStorage.setItem('sb_mesh_sovereignty_accepted', 'true');
    // No sb_mesh_privkey — simulates post-migration state

    const identity = mod.getNodeIdentity();
    expect(identity).not.toBeNull();
    expect(identity!.publicKey).toBe('test-pub');
    expect(identity!.nodeId).toBe('!sb_abcd1234abcd1234');
    expect(identity!.privateKey).toBe('');
  });

  it('getNodeIdentity triggers eager migration and does not expose legacy privateKey', async () => {
    const mod = await import('@/mesh/meshIdentity');

    localStorage.setItem('sb_mesh_pubkey', 'test-pub');
    localStorage.setItem('sb_mesh_node_id', '!sb_abcd1234abcd1234');
    localStorage.setItem('sb_mesh_privkey', '{"fake":"jwk"}');
    localStorage.setItem('sb_mesh_sovereignty_accepted', 'true');

    const identity = mod.getNodeIdentity();
    expect(identity).not.toBeNull();
    expect(identity!.privateKey).toBe('');

    // The eager migration fires asynchronously (void ensureSigningPrivateKey()).
    // In this test environment crypto.subtle.importKey will fail on the fake JWK,
    // but the extractable browser copy should still be scrubbed.
    await new Promise((r) => setTimeout(r, 10));
    expect(localStorage.getItem('sb_mesh_privkey')).toBeNull();
    expect(identity!.publicKey).toBe('test-pub');
  });

  it('purgeBrowserSigningMaterial clears IndexedDB signing key', async () => {
    const { deleteKey } = await import('@/mesh/meshKeyStore');
    const mod = await import('@/mesh/meshIdentity');

    idbStore.set('sb_mesh_sign_priv', 'mock-crypto-key');
    localStorage.setItem('sb_mesh_privkey', '{"fake":"jwk"}');
    localStorage.setItem('sb_mesh_sequence', '42');

    await mod.purgeBrowserSigningMaterial();

    expect(deleteKey).toHaveBeenCalledWith('sb_mesh_sign_priv');
    expect(localStorage.getItem('sb_mesh_privkey')).toBeNull();
    expect(localStorage.getItem('sb_mesh_sequence')).toBeNull();
  });

  it('clearBrowserIdentityState clears both DH and signing keys from IndexedDB', async () => {
    const { deleteKey } = await import('@/mesh/meshKeyStore');
    const mod = await import('@/mesh/meshIdentity');

    localStorage.setItem('sb_mesh_pubkey', 'test-pub');
    localStorage.setItem('sb_mesh_node_id', '!sb_test');
    localStorage.setItem('sb_mesh_privkey', '{"fake":"jwk"}');
    localStorage.setItem('sb_mesh_session_mode', 'true');
    localStorage.setItem('sb_mesh_sovereignty_accepted', 'true');
    localStorage.setItem('sb_dm_bundle_fingerprint', 'bundle-fp');
    sessionStorage.setItem('sb_wormhole_desc_node_id', '!sb_gate');
    sessionStorage.setItem('sb_mesh_dm_ratchet', 'encrypted');
    sessionStorage.setItem('sb_mesh_ratchet_telemetry', '{"seen":1}');

    await mod.clearBrowserIdentityState();

    expect(deleteKey).toHaveBeenCalledWith('sb_mesh_dh_priv');
    expect(deleteKey).toHaveBeenCalledWith('sb_mesh_sign_priv');
    expect(localStorage.getItem('sb_mesh_pubkey')).toBeNull();
    expect(localStorage.getItem('sb_mesh_privkey')).toBeNull();
    expect(localStorage.getItem('sb_dm_bundle_fingerprint')).toBeNull();
    expect(sessionStorage.getItem('sb_wormhole_desc_node_id')).toBeNull();
    expect(sessionStorage.getItem('sb_mesh_dm_ratchet')).toBeNull();
    expect(sessionStorage.getItem('sb_mesh_ratchet_telemetry')).toBeNull();
    expect(deletedDatabases).toContain('sb_mesh_ratchet_crypto');
  });

  it('generateDHKeys fails closed when non-extractable DH key storage is unavailable', async () => {
    const { setKey } = await import('@/mesh/meshKeyStore');
    vi.mocked(setKey).mockRejectedValueOnce(new Error('idb unavailable'));
    const mod = await import('@/mesh/meshIdentity');

    await expect(mod.generateDHKeys()).rejects.toThrow('IndexedDB required for DH key storage');
    expect(localStorage.getItem('sb_mesh_dh_privkey')).toBeNull();
    expect(sessionStorage.getItem('sb_mesh_dh_privkey')).toBeNull();
  });

  it('signWithStoredKey is exported and throws when no key available', async () => {
    const mod = await import('@/mesh/meshIdentity');
    // No key in IndexedDB or localStorage
    await expect(mod.signWithStoredKey('test message')).rejects.toThrow(
      'No signing key available',
    );
  });

  it('signEvent fails closed when only public identity metadata exists', async () => {
    const mod = await import('@/mesh/meshIdentity');

    sessionStorage.setItem('sb_mesh_pubkey', 'test-pub');
    sessionStorage.setItem('sb_mesh_node_id', '!sb_abcd1234abcd1234');
    sessionStorage.setItem('sb_mesh_sovereignty_accepted', 'true');
    sessionStorage.setItem('sb_mesh_algo', 'Ed25519');

    await expect(
      mod.signEvent('message', '!sb_abcd1234abcd1234', 1, { message: 'hello' }),
    ).rejects.toThrow('No signing key available');
  });
});
