import { beforeEach, describe, expect, it, vi } from 'vitest';

const controlPlaneJson = vi.fn();
const idbStore = new Map<string, unknown>();

vi.mock('@/lib/controlPlane', () => ({
  controlPlaneJson,
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

async function flushStoragePersistence(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
  await new Promise((resolve) => setTimeout(resolve, 0));
}

async function waitForEncryptedContacts(): Promise<string | null> {
  for (let i = 0; i < 20; i += 1) {
    await flushStoragePersistence();
    const stored =
      sessionStorage.getItem('sb_mesh_contacts') || localStorage.getItem('sb_mesh_contacts');
    if (typeof stored === 'string' && stored.startsWith('enc:')) {
      return stored;
    }
  }
  return sessionStorage.getItem('sb_mesh_contacts') || localStorage.getItem('sb_mesh_contacts');
}

function bufToBase64(buf: ArrayBuffer): string {
  return btoa(String.fromCharCode(...new Uint8Array(buf)));
}

describe('meshIdentity contact storage hardening', () => {
  beforeEach(() => {
    vi.resetModules();
    controlPlaneJson.mockReset();
    idbStore.clear();
    const makeStorage = () => {
      const values = new Map<string, string>();
      return {
        getItem: (key: string) => values.get(key) ?? null,
        setItem: (key: string, value: string) => void values.set(key, value),
        removeItem: (key: string) => void values.delete(key),
        clear: () => void values.clear(),
      };
    };
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

  async function provisionLocalIdentity(mod: typeof import('@/mesh/meshIdentity')) {
    localStorage.setItem('sb_mesh_pubkey', 'test-pub');
    localStorage.setItem('sb_mesh_node_id', '!sb_contacts123456');
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
  }

  it('hydrates secure-mode contacts from Wormhole and avoids localStorage persistence', async () => {
    controlPlaneJson
      .mockResolvedValueOnce({
        ok: true,
        contacts: {
          alice: { blocked: false, dhPubKey: 'dh_a', sharedAlias: 'alias_a' },
        },
      })
      .mockResolvedValueOnce({
        ok: true,
        peer_id: 'alice',
        contact: { blocked: false, dhPubKey: 'dh_a2', sharedAlias: 'alias_a' },
      });

    const mod = await import('@/mesh/meshIdentity');
    mod.setSecureModeCached(true);

    const contacts = await mod.hydrateWormholeContacts(true);
    expect(contacts.alice.dhPubKey).toBe('dh_a');

    mod.addContact('alice', 'dh_a2');
    await Promise.resolve();

    expect(localStorage.getItem('sb_mesh_contacts')).toBeNull();
    expect(mod.getContacts().alice.dhPubKey).toBe('dh_a2');
    expect(controlPlaneJson).toHaveBeenLastCalledWith('/api/wormhole/dm/contact', expect.any(Object));
  });

  it('stores local contacts as encrypted ciphertext and hydrates them back', async () => {
    const mod = await import('@/mesh/meshIdentity');
    await provisionLocalIdentity(mod);

    mod.addContact('alice', 'dh_a', 'Alice', 'X25519');
    mod.updateContact('alice', {
      remotePrekeyFingerprint: 'fp-1',
      remotePrekeyObservedFingerprint: 'fp-1',
      remotePrekeyPinnedAt: 111,
      remotePrekeyLastSeenAt: 222,
      remotePrekeySequence: 3,
      remotePrekeySignedAt: 444,
      remotePrekeyMismatch: false,
    });
    const stored = await waitForEncryptedContacts();
    expect(String(stored ?? '')).toMatch(/^enc:/);
    expect(String(stored ?? '')).not.toContain('"alice"');
    expect(String(stored ?? '')).not.toContain('"dh_a"');

    const hydrated = await mod.hydrateWormholeContacts(true);
    expect(hydrated.alice.dhPubKey).toBe('dh_a');
    expect(hydrated.alice.alias).toBe('Alice');
    expect(hydrated.alice.remotePrekeyFingerprint).toBe('fp-1');
    expect(hydrated.alice.remotePrekeyObservedFingerprint).toBe('fp-1');
    expect(hydrated.alice.remotePrekeyPinnedAt).toBe(111);
    expect(hydrated.alice.remotePrekeyLastSeenAt).toBe(222);
    expect(hydrated.alice.remotePrekeySequence).toBe(3);
    expect(hydrated.alice.remotePrekeySignedAt).toBe(444);
    expect(hydrated.alice.remotePrekeyMismatch).toBe(false);
  });

  it('migrates legacy plaintext contacts to encrypted storage on first hydrate', async () => {
    const mod = await import('@/mesh/meshIdentity');
    await provisionLocalIdentity(mod);

    localStorage.setItem(
      'sb_mesh_contacts',
      JSON.stringify({ alice: { blocked: false, dhPubKey: 'legacy_dh', alias: 'Legacy Alice' } }),
    );

    const hydrated = await mod.hydrateWormholeContacts(true);
    expect(hydrated.alice.dhPubKey).toBe('legacy_dh');
    expect(hydrated.alice.alias).toBe('Legacy Alice');

    const stored = await waitForEncryptedContacts();
    expect(String(stored ?? '')).toMatch(/^enc:/);
    expect(String(stored ?? '')).not.toContain('legacy_dh');
  });

  it('encrypts identity-bound browser payloads under distinct info domains', async () => {
    const mod = await import('@/mesh/meshIdentity');
    await provisionLocalIdentity(mod);

    const accessCipher = await mod.encryptIdentityBoundStoragePayload(
      [{ sender_id: 'alice', timestamp: 1 }],
      'SB-ACCESS-REQUESTS-STORAGE-V1',
    );
    expect(accessCipher).toMatch(/^enc:/);
    expect(accessCipher).not.toContain('alice');

    const decrypted = await mod.decryptIdentityBoundStoragePayload(
      accessCipher,
      'SB-ACCESS-REQUESTS-STORAGE-V1',
      [],
    );
    expect(decrypted).toEqual([{ sender_id: 'alice', timestamp: 1 }]);

    await expect(
      mod.decryptIdentityBoundStoragePayload(
        accessCipher,
        'SB-PENDING-CONTACTS-STORAGE-V1',
        [],
      ),
    ).rejects.toThrow();
  });

  it('treats unreadable encrypted contacts as empty and warns instead of crashing', async () => {
    const mod = await import('@/mesh/meshIdentity');
    await provisionLocalIdentity(mod);

    localStorage.setItem('sb_mesh_contacts', 'enc:not-valid-ciphertext');
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});

    const hydrated = await mod.hydrateWormholeContacts(true);

    expect(hydrated).toEqual({});
    expect(warn).toHaveBeenCalledWith(
      '[mesh] contact storage unreadable — treating as empty contacts',
      expect.anything(),
    );
    warn.mockRestore();
  });

  it('purges browser-persisted contact graph when secure mode boundary is applied', async () => {
    const mod = await import('@/mesh/meshIdentity');
    localStorage.setItem(
      'sb_mesh_contacts',
      JSON.stringify({ bob: { blocked: false, sharedAlias: 'peer-b' } }),
    );

    mod.purgeBrowserContactGraph();

    expect(localStorage.getItem('sb_mesh_contacts')).toBeNull();
    expect(mod.getContacts()).toEqual({});
  });

  it('rotates the mailbox-claim secret when identity state is cleared', async () => {
    const { mailboxClaimToken } = await import('@/mesh/meshMailbox');
    const mod = await import('@/mesh/meshIdentity');
    await provisionLocalIdentity(mod);

    const first = await mailboxClaimToken('requests', '!sb_contacts123456');
    const second = await mailboxClaimToken('requests', '!sb_contacts123456');
    expect(second).toBe(first);

    await mod.clearBrowserIdentityState();

    localStorage.setItem('sb_mesh_pubkey', 'test-pub');
    localStorage.setItem('sb_mesh_node_id', '!sb_contacts123456');
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

    const rotated = await mailboxClaimToken('requests', '!sb_contacts123456');
    expect(rotated).not.toBe(first);
  });
});
