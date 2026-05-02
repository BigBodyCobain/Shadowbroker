import { beforeEach, describe, expect, it, vi } from 'vitest';

const deriveWormholeDeadDropTokens = vi.fn();
const deriveWormholeDeadDropTokenPair = vi.fn();
const isWormholeReady = vi.fn();

vi.mock('@/mesh/wormholeIdentityClient', () => ({
  deriveWormholeDeadDropTokens,
  deriveWormholeDeadDropTokenPair,
  isWormholeReady,
}));

vi.mock('@/mesh/meshIdentity', () => ({
  deriveSharedSecret: vi.fn(),
  getStoredNodeDescriptor: vi.fn(() => ({ nodeId: 'local-node' })),
}));

describe('mesh dead-drop alias hygiene', () => {
  beforeEach(() => {
    deriveWormholeDeadDropTokens.mockReset();
    deriveWormholeDeadDropTokenPair.mockReset();
    isWormholeReady.mockReset();
  });

  it('sends alias refs instead of the stable peer id when mailbox aliases exist', async () => {
    isWormholeReady.mockResolvedValue(true);
    deriveWormholeDeadDropTokens.mockResolvedValue({
      ok: true,
      tokens: [
        { peer_id: 'peer_alpha', peer_ref: 'dmx_alpha', current: 'tok1', previous: 'tok0', epoch: 7 },
      ],
    });

    const { deadDropTokensForContacts } = await import('@/mesh/meshDeadDrop');
    const tokens = await deadDropTokensForContacts(
      {
        peer_alpha: {
          blocked: false,
          dhPubKey: 'dhpub_alpha',
          sharedAlias: 'dmx_alpha',
          previousSharedAliases: ['dmx_prev_alpha'],
        } as any,
      },
      24,
    );

    expect(tokens).toEqual(['tok1', 'tok0']);
    expect(deriveWormholeDeadDropTokens).toHaveBeenCalledWith(
      [
        {
          peer_id: 'peer_alpha',
          peer_dh_pub: 'dhpub_alpha',
          peer_refs: ['dmx_alpha', 'dmx_prev_alpha'],
        },
      ],
      24,
    );
  });

  it('falls back to the stable peer id only when no alias history exists', async () => {
    isWormholeReady.mockResolvedValue(true);
    deriveWormholeDeadDropTokens.mockResolvedValue({
      ok: true,
      tokens: [
        { peer_id: 'peer_bravo', peer_ref: 'peer_bravo', current: 'tok2', previous: 'tok1', epoch: 8 },
      ],
    });

    const { deadDropTokensForContacts } = await import('@/mesh/meshDeadDrop');
    await deadDropTokensForContacts(
      {
        peer_bravo: {
          blocked: false,
          dhPubKey: 'dhpub_bravo',
        } as any,
      },
      24,
    );

    expect(deriveWormholeDeadDropTokens).toHaveBeenCalledWith(
      [
        {
          peer_id: 'peer_bravo',
          peer_dh_pub: 'dhpub_bravo',
          peer_refs: ['peer_bravo'],
        },
      ],
      24,
    );
  });
});
