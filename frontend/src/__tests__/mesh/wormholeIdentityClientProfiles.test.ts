import { beforeEach, describe, expect, it, vi } from 'vitest';

const controlPlaneJson = vi.fn();
const getNodeIdentity = vi.fn<
  () => { nodeId: string; publicKey: string; privateKey: string } | null
>(() => null);
const signEvent = vi.fn();
const signMessage = vi.fn();
const signWithStoredKey = vi.fn();
const isSecureModeCached = vi.fn(() => true);
const fetchWormholeSettings = vi.fn(async () => ({ enabled: true }));
const fetchWormholeState = vi.fn(async () => ({ ready: true }));

vi.mock('@/lib/controlPlane', () => ({
  controlPlaneJson,
}));

vi.mock('@/mesh/meshIdentity', () => ({
  cacheWormholeIdentityDescriptor: vi.fn(),
  getNodeIdentity,
  getPublicKeyAlgo: vi.fn(() => 'ed25519'),
  isSecureModeCached,
  purgeBrowserSigningMaterial: vi.fn(async () => {}),
  setSecureModeCached: vi.fn(),
  signEvent,
  signMessage,
  signWithStoredKey,
}));

vi.mock('@/mesh/meshProtocol', () => ({
  PROTOCOL_VERSION: 'sb-test',
}));

vi.mock('@/mesh/wormholeClient', () => ({
  fetchWormholeSettings,
  fetchWormholeState,
}));

describe('wormholeIdentityClient strict profile hints', () => {
  beforeEach(() => {
    vi.resetModules();
    controlPlaneJson.mockReset();
    controlPlaneJson.mockResolvedValue({ ok: true });
    getNodeIdentity.mockReset();
    getNodeIdentity.mockReturnValue(null);
    signEvent.mockReset();
    signMessage.mockReset();
    signWithStoredKey.mockReset();
    isSecureModeCached.mockReset();
    isSecureModeCached.mockReturnValue(true);
    fetchWormholeSettings.mockReset();
    fetchWormholeSettings.mockResolvedValue({ enabled: true });
    fetchWormholeState.mockReset();
    fetchWormholeState.mockResolvedValue({ ready: true });
  });

  it('applies strict gate_operator enforcement to gate persona and compose operations', async () => {
    const mod = await import('@/mesh/wormholeIdentityClient');

    await mod.listWormholeGatePersonas('infonet');
    await mod.createWormholeGatePersona('infonet', 'persona-1');
    await mod.activateWormholeGatePersona('infonet', 'persona-1');
    await mod.clearWormholeGatePersona('infonet');
    await mod.retireWormholeGatePersona('infonet', 'persona-1');
    await mod.composeWormholeGateMessage('infonet', 'hello');

    expect(controlPlaneJson).toHaveBeenNthCalledWith(
      1,
      '/api/wormhole/gate/infonet/personas',
      expect.objectContaining({
        capabilityIntent: 'wormhole_gate_persona',
        sessionProfileHint: 'gate_operator',
        enforceProfileHint: true,
      }),
    );
    for (let i = 2; i <= 5; i += 1) {
      expect(controlPlaneJson).toHaveBeenNthCalledWith(
        i,
        expect.any(String),
        expect.objectContaining({
          capabilityIntent: 'wormhole_gate_persona',
          sessionProfileHint: 'gate_operator',
          enforceProfileHint: true,
        }),
      );
    }
    expect(controlPlaneJson).toHaveBeenNthCalledWith(
      6,
      '/api/wormhole/gate/message/compose',
      expect.objectContaining({
        capabilityIntent: 'wormhole_gate_content',
        sessionProfileHint: 'gate_operator',
        enforceProfileHint: true,
      }),
    );
  });

  it('browser raw signing fails closed instead of falling back to legacy jwk signing', async () => {
    fetchWormholeSettings.mockResolvedValue({ enabled: false });
    fetchWormholeState.mockResolvedValue({ ready: false });
    getNodeIdentity.mockReturnValue({
      nodeId: '!sb_browser',
      publicKey: 'browser-pub',
      privateKey: '',
    });
    signWithStoredKey.mockRejectedValue(new Error('no key'));

    const mod = await import('@/mesh/wormholeIdentityClient');

    await expect(mod.signRawMeshMessage('payload')).rejects.toThrow(
      'browser_signing_key_unavailable',
    );
    expect(signWithStoredKey).toHaveBeenCalledWith('payload');
    expect(signMessage).not.toHaveBeenCalled();
  });

  it('keeps the cached secure boundary when wormhole settings fetch fails', async () => {
    fetchWormholeSettings.mockRejectedValue(new Error('network down'));
    isSecureModeCached.mockReturnValue(true);

    const mod = await import('@/mesh/wormholeIdentityClient');

    await expect(mod.isWormholeSecureRequired()).resolves.toBe(true);
  });
});
