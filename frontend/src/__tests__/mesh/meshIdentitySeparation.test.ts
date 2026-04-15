import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/controlPlane', () => ({
  controlPlaneJson: vi.fn(),
}));

vi.mock('@/mesh/meshKeyStore', () => ({
  getKey: vi.fn().mockResolvedValue(null),
  setKey: vi.fn().mockResolvedValue(undefined),
  deleteKey: vi.fn().mockResolvedValue(undefined),
}));

describe('mesh identity storage separation', () => {
  beforeEach(() => {
    vi.resetModules();
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

  it('keeps public browser identity separate from Wormhole descriptor cache', async () => {
    const mod = await import('@/mesh/meshIdentity');

    mod.cachePublicIdentity({
      nodeId: '!sb_public',
      publicKey: 'public-key',
      publicKeyAlgo: 'Ed25519',
    });
    mod.cacheWormholeIdentityDescriptor({
      nodeId: '!sb_wormhole',
      publicKey: 'wormhole-key',
      publicKeyAlgo: 'Ed25519',
    });

    expect(mod.getStoredNodeDescriptor()).toEqual({
      nodeId: '!sb_public',
      publicKey: 'public-key',
      publicKeyAlgo: 'Ed25519',
    });
    expect(mod.getWormholeIdentityDescriptor()).toEqual({
      nodeId: '!sb_wormhole',
      publicKey: 'wormhole-key',
      publicKeyAlgo: 'Ed25519',
    });
  });

  it('clears browser public identity and Wormhole descriptor cache together on full reset', async () => {
    const mod = await import('@/mesh/meshIdentity');

    mod.cachePublicIdentity({
      nodeId: '!sb_public',
      publicKey: 'public-key',
      publicKeyAlgo: 'Ed25519',
    });
    mod.cacheWormholeIdentityDescriptor({
      nodeId: '!sb_wormhole',
      publicKey: 'wormhole-key',
      publicKeyAlgo: 'Ed25519',
    });

    await mod.clearBrowserIdentityState();

    expect(mod.getStoredNodeDescriptor()).toBeNull();
    expect(mod.getWormholeIdentityDescriptor()).toBeNull();
  });

  it('migrates legacy browser and Wormhole node ids to the current format', async () => {
    const mod = await import('@/mesh/meshIdentity');
    const publicKey = 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=';
    const currentNodeId = await mod.deriveNodeIdFromPublicKey(publicKey);

    mod.cachePublicIdentity({
      nodeId: '!sb_deadbeef',
      publicKey,
      publicKeyAlgo: 'Ed25519',
    });
    mod.cacheWormholeIdentityDescriptor({
      nodeId: '!sb_deadbeef',
      publicKey,
      publicKeyAlgo: 'Ed25519',
    });

    await mod.migrateLegacyNodeIds();

    expect(mod.getStoredNodeDescriptor()).toEqual({
      nodeId: currentNodeId,
      publicKey,
      publicKeyAlgo: 'Ed25519',
    });
    expect(mod.getWormholeIdentityDescriptor()).toEqual({
      nodeId: currentNodeId,
      publicKey,
      publicKeyAlgo: 'Ed25519',
    });
  });
});
