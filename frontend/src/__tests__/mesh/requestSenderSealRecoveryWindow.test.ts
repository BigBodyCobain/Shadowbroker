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

function bufToBase64(buf: ArrayBuffer): string {
  return btoa(String.fromCharCode(...new Uint8Array(buf)));
}

async function buildV3SealForRecipient(params: {
  recipientPublicKey: CryptoKey;
  recipientId: string;
  msgId: string;
  plaintext: string;
}) {
  const { encryptDM } = await import('@/mesh/meshIdentity');
  const { PROTOCOL_VERSION } = await import('@/mesh/meshProtocol');
  const ephemeral = (await crypto.subtle.generateKey(
    { name: 'ECDH', namedCurve: 'P-256' },
    true,
    ['deriveBits', 'deriveKey'],
  )) as CryptoKeyPair;
  const ephemeralPubRaw = await crypto.subtle.exportKey('raw', ephemeral.publicKey);
  const ephemeralPub = bufToBase64(ephemeralPubRaw);
  const secret = await crypto.subtle.deriveBits(
    { name: 'ECDH', public: params.recipientPublicKey },
    ephemeral.privateKey,
    256,
  );
  const salt = await crypto.subtle.digest(
    'SHA-256',
    new TextEncoder().encode(
      `SB-SEAL-SALT|${params.recipientId}|${params.msgId}|${PROTOCOL_VERSION}|${ephemeralPub}`,
    ),
  );
  const hkdfKey = await crypto.subtle.importKey('raw', secret, 'HKDF', false, ['deriveKey']);
  const sealKey = await crypto.subtle.deriveKey(
    {
      name: 'HKDF',
      hash: 'SHA-256',
      salt,
      info: new TextEncoder().encode('SB-SENDER-SEAL-V3'),
    },
    hkdfKey,
    { name: 'AES-GCM', length: 256 },
    false,
    ['encrypt', 'decrypt'],
  );
  const ciphertext = await encryptDM(params.plaintext, sealKey);
  return `v3:${ephemeralPub}:${ciphertext}`;
}

describe('request sender seal recovery window', () => {
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

  it('opens a v3 sender seal with the immediately previous retained recipient key', async () => {
    const mod = await import('@/mesh/meshIdentity');
    const previousRecipient = (await crypto.subtle.generateKey(
      { name: 'ECDH', namedCurve: 'P-256' },
      false,
      ['deriveBits', 'deriveKey'],
    )) as CryptoKeyPair;
    const currentRecipient = (await crypto.subtle.generateKey(
      { name: 'ECDH', namedCurve: 'P-256' },
      false,
      ['deriveBits', 'deriveKey'],
    )) as CryptoKeyPair;

    idbStore.set('sb_mesh_dh_priv', currentRecipient.privateKey);
    idbStore.set('sb_mesh_dh_prev_priv', previousRecipient.privateKey);
    localStorage.setItem('sb_mesh_dh_algo', 'ECDH');

    const plaintext = JSON.stringify({ sender_id: 'alice', msg_id: 'msg-rotation' });
    const senderSeal = await buildV3SealForRecipient({
      recipientPublicKey: previousRecipient.publicKey,
      recipientId: '!sb_recipient',
      msgId: 'msg-rotation',
      plaintext,
    });

    await expect(
      mod.decryptSenderSealPayloadLocally(senderSeal, '', '!sb_recipient', 'msg-rotation'),
    ).resolves.toBe(plaintext);
  });

  it('returns null when the prior retained recipient key is unavailable', async () => {
    const mod = await import('@/mesh/meshIdentity');
    const previousRecipient = (await crypto.subtle.generateKey(
      { name: 'ECDH', namedCurve: 'P-256' },
      false,
      ['deriveBits', 'deriveKey'],
    )) as CryptoKeyPair;
    const currentRecipient = (await crypto.subtle.generateKey(
      { name: 'ECDH', namedCurve: 'P-256' },
      false,
      ['deriveBits', 'deriveKey'],
    )) as CryptoKeyPair;

    idbStore.set('sb_mesh_dh_priv', currentRecipient.privateKey);
    localStorage.setItem('sb_mesh_dh_algo', 'ECDH');

    const senderSeal = await buildV3SealForRecipient({
      recipientPublicKey: previousRecipient.publicKey,
      recipientId: '!sb_recipient',
      msgId: 'msg-rotation-miss',
      plaintext: JSON.stringify({ sender_id: 'alice', msg_id: 'msg-rotation-miss' }),
    });

    await expect(
      mod.decryptSenderSealPayloadLocally(senderSeal, '', '!sb_recipient', 'msg-rotation-miss'),
    ).resolves.toBeNull();
  });

  it('retains the current DH private key in the previous-key slot when rotating', async () => {
    const mod = await import('@/mesh/meshIdentity');
    const existing = (await crypto.subtle.generateKey(
      { name: 'ECDH', namedCurve: 'P-256' },
      false,
      ['deriveBits', 'deriveKey'],
    )) as CryptoKeyPair;
    const originalGenerateKey = crypto.subtle.generateKey.bind(crypto.subtle);
    const generateKeySpy = vi
      .spyOn(crypto.subtle, 'generateKey')
      .mockImplementation(((algorithm: AlgorithmIdentifier, extractable: boolean, keyUsages: KeyUsage[]) => {
        if (algorithm === 'X25519') {
          return Promise.reject(new Error('x25519_unavailable_for_test'));
        }
        return originalGenerateKey(algorithm, extractable, keyUsages);
      }) as typeof crypto.subtle.generateKey);

    idbStore.set('sb_mesh_dh_priv', existing.privateKey);
    try {
      await mod.generateDHKeys();

      expect(idbStore.get('sb_mesh_dh_prev_priv')).toBe(existing.privateKey);
      expect(idbStore.get('sb_mesh_dh_priv')).not.toBe(existing.privateKey);
    } finally {
      generateKeySpy.mockRestore();
    }
  });
});
