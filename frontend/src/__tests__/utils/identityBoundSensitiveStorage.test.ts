import { beforeEach, describe, expect, it, vi } from 'vitest';

const idbStore = new Map<string, unknown>();

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
  };
}

function bufToBase64(buf: ArrayBuffer): string {
  return btoa(String.fromCharCode(...new Uint8Array(buf)));
}

async function provisionLocalIdentity(): Promise<void> {
  const meshIdentity = await import('@/mesh/meshIdentity');
  localStorage.setItem('sb_mesh_pubkey', 'test-pub');
  localStorage.setItem('sb_mesh_node_id', '!sb_sensitive123456');
  localStorage.setItem('sb_mesh_sovereignty_accepted', 'true');
  const keyPair = (await crypto.subtle.generateKey(
    { name: 'ECDH', namedCurve: 'P-256' },
    false,
    ['deriveKey', 'deriveBits'],
  )) as CryptoKeyPair;
  const publicRaw = await crypto.subtle.exportKey('raw', keyPair.publicKey);
  localStorage.setItem('sb_mesh_dh_pubkey', bufToBase64(publicRaw));
  localStorage.setItem('sb_mesh_dh_algo', 'ECDH');
  idbStore.set('sb_mesh_dh_priv', keyPair.privateKey);
  meshIdentity.getNodeIdentity();
}

describe('identityBoundSensitiveStorage', () => {
  beforeEach(() => {
    vi.resetModules();
    idbStore.clear();
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
  });

  it('stores encrypted values in sensitive storage and keeps them out of localStorage', async () => {
    await provisionLocalIdentity();
    const storage = await import('@/lib/identityBoundSensitiveStorage');

    await storage.persistIdentityBoundSensitiveValue(
      'sb_access_requests:test',
      'SB-ACCESS-REQUESTS-STORAGE-V1',
      [{ sender_id: 'alice', ts: 1 }],
    );

    expect(String(sessionStorage.getItem('sb_access_requests:test') ?? '')).toMatch(/^enc:/);
    expect(localStorage.getItem('sb_access_requests:test')).toBeNull();

    const hydrated = await storage.loadIdentityBoundSensitiveValue(
      'sb_access_requests:test',
      'SB-ACCESS-REQUESTS-STORAGE-V1',
      [],
    );
    expect(hydrated).toEqual([{ sender_id: 'alice', ts: 1 }]);
  });

  it('migrates legacy plaintext sensitive values into encrypted session-backed storage', async () => {
    await provisionLocalIdentity();
    const storage = await import('@/lib/identityBoundSensitiveStorage');

    localStorage.setItem('sb_mesh_muted', JSON.stringify(['alice', 'bob']));

    const hydrated = await storage.loadIdentityBoundSensitiveValue(
      'sb_mesh_muted:!sb_sensitive123456',
      'SB-MUTED-LIST-V1',
      [],
      { legacyKey: 'sb_mesh_muted' },
    );

    expect(hydrated).toEqual(['alice', 'bob']);
    expect(String(sessionStorage.getItem('sb_mesh_muted:!sb_sensitive123456') ?? '')).toMatch(/^enc:/);
    expect(localStorage.getItem('sb_mesh_muted')).toBeNull();
    expect(sessionStorage.getItem('sb_mesh_muted')).toBeNull();
  });
});
