import { beforeEach, describe, expect, it, vi } from 'vitest';

const hasLocalControlBridge = vi.fn(() => false);
const buildGateAccessHeaders = vi.fn();
const decryptWormholeGateMessage = vi.fn();

vi.mock('@/lib/localControlTransport', () => ({
  hasLocalControlBridge,
}));

vi.mock('@/mesh/gateAccessProof', () => ({
  buildGateAccessHeaders,
}));

vi.mock('@/mesh/wormholeIdentityClient', () => ({
  decryptWormholeGateMessage,
}));

describe('gatePreviewSnapshot cache', () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.resetModules();
    fetchMock.mockReset();
    buildGateAccessHeaders.mockReset();
    decryptWormholeGateMessage.mockReset();
    hasLocalControlBridge.mockReset();
    hasLocalControlBridge.mockReturnValue(false);
    buildGateAccessHeaders.mockResolvedValue({
      'X-Wormhole-Node-Id': '!sb_gate',
      'X-Wormhole-Gate-Proof': 'proof',
      'X-Wormhole-Gate-Ts': '1712345678',
    });
    decryptWormholeGateMessage.mockResolvedValue({
      ok: true,
      plaintext: 'sealed preview',
    });
    vi.stubGlobal('fetch', fetchMock);
  });

  it('coarsens browser/web gate preview fetches through a short cache window', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-04-05T23:30:00.000Z'));
    try {
      fetchMock.mockResolvedValue({
        ok: true,
        json: async () => ({
          messages: [
            {
              event_id: 'evt-1',
              event_type: 'gate_message',
              node_id: '!sb_sender',
              gate: 'infonet',
              epoch: 7,
              ciphertext: 'ct',
              nonce: 'nonce',
              sender_ref: 'sender-ref',
              format: 'mls1',
              gate_envelope: 'env',
              envelope_hash: 'hash',
              timestamp: Math.floor(Date.now() / 1000) - 60,
            },
          ],
        }),
      });

      const mod = await import('@/mesh/gatePreviewSnapshot');

      await expect(mod.fetchGateThreadPreviewSnapshot('infonet')).resolves.toEqual([
        {
          nodeId: '!sb_sender',
          age: '1m ago',
          text: 'sealed preview',
          encrypted: true,
        },
      ]);
      await mod.fetchGateThreadPreviewSnapshot('infonet');

      expect(fetchMock).toHaveBeenCalledTimes(1);
      expect(decryptWormholeGateMessage).toHaveBeenCalledTimes(1);

      vi.advanceTimersByTime(12_001);

      await mod.fetchGateThreadPreviewSnapshot('infonet');
      expect(fetchMock).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it('uses a shorter preview cache window on native runtimes', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-04-05T23:30:00.000Z'));
    try {
      hasLocalControlBridge.mockReturnValue(true);
      fetchMock.mockResolvedValue({
        ok: true,
        json: async () => ({
          messages: [
            {
              event_id: 'evt-1',
              node_id: '!sb_sender',
              message: 'plain preview',
              timestamp: Math.floor(Date.now() / 1000) - 60,
            },
          ],
        }),
      });

      const mod = await import('@/mesh/gatePreviewSnapshot');

      await mod.fetchGateThreadPreviewSnapshot('infonet');
      vi.advanceTimersByTime(4_001);
      await mod.fetchGateThreadPreviewSnapshot('infonet');

      expect(fetchMock).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it('invalidates cached gate previews explicitly', async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          messages: [
            {
              event_id: 'evt-1',
              node_id: '!sb_sender',
              message: 'plain preview',
              timestamp: 1712360000,
            },
          ],
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          messages: [
            {
              event_id: 'evt-2',
              node_id: '!sb_sender',
              message: 'updated preview',
              timestamp: 1712360100,
            },
          ],
        }),
      });

    const mod = await import('@/mesh/gatePreviewSnapshot');

    await expect(mod.fetchGateThreadPreviewSnapshot('infonet')).resolves.toEqual([
      expect.objectContaining({ text: 'plain preview' }),
    ]);
    mod.invalidateGateThreadPreviewSnapshot('infonet');
    await expect(mod.fetchGateThreadPreviewSnapshot('infonet')).resolves.toEqual([
      expect.objectContaining({ text: 'updated preview' }),
    ]);

    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
