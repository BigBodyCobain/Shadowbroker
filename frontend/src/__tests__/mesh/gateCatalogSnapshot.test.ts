import { beforeEach, describe, expect, it, vi } from 'vitest';

const hasLocalControlBridge = vi.fn(() => false);

vi.mock('@/lib/localControlTransport', () => ({
  hasLocalControlBridge,
}));

describe('gateCatalogSnapshot cache', () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.resetModules();
    fetchMock.mockReset();
    hasLocalControlBridge.mockReset();
    hasLocalControlBridge.mockReturnValue(false);
    vi.stubGlobal('fetch', fetchMock);
  });

  it('coarsens browser/web gate catalog reads through a short shared cache window', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-04-05T23:10:00.000Z'));
    try {
      fetchMock.mockResolvedValue({
        ok: true,
        json: async () => ({
          gates: [{ gate_id: 'infonet', display_name: 'Infonet Commons' }],
        }),
      });

      const mod = await import('@/mesh/gateCatalogSnapshot');

      await expect(mod.fetchGateCatalogSnapshot()).resolves.toEqual([
        { gate_id: 'infonet', display_name: 'Infonet Commons' },
      ]);
      await expect(mod.fetchGateCatalogSnapshot()).resolves.toEqual([
        { gate_id: 'infonet', display_name: 'Infonet Commons' },
      ]);

      expect(fetchMock).toHaveBeenCalledTimes(1);

      vi.advanceTimersByTime(18_001);

      await mod.fetchGateCatalogSnapshot();
      expect(fetchMock).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it('uses a shorter cache window for native gate catalog/detail snapshots', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-04-05T23:10:00.000Z'));
    try {
      hasLocalControlBridge.mockReturnValue(true);
      fetchMock
        .mockResolvedValueOnce({
          ok: true,
          json: async () => ({
            gates: [{ gate_id: 'finance', display_name: 'Finance' }],
          }),
        })
        .mockResolvedValueOnce({
          ok: true,
          json: async () => ({
            gates: [{ gate_id: 'finance', display_name: 'Finance' }],
          }),
        })
        .mockResolvedValueOnce({
          ok: true,
          json: async () => ({
            gate_id: 'finance',
            display_name: 'Finance',
          }),
        })
        .mockResolvedValueOnce({
          ok: true,
          json: async () => ({
            gate_id: 'finance',
            display_name: 'Finance',
          }),
        });

      const mod = await import('@/mesh/gateCatalogSnapshot');

      await mod.fetchGateCatalogSnapshot();
      vi.advanceTimersByTime(6_001);
      await mod.fetchGateCatalogSnapshot();

      await mod.fetchGateDetailSnapshot('finance');
      vi.advanceTimersByTime(5_001);
      await mod.fetchGateDetailSnapshot('finance');

      expect(fetchMock).toHaveBeenCalledTimes(4);
    } finally {
      vi.useRealTimers();
    }
  });

  it('invalidates cached gate detail snapshots explicitly', async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          gate_id: 'infonet',
          display_name: 'Infonet Commons',
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          gate_id: 'infonet',
          display_name: 'Infonet Commons v2',
        }),
      });

    const mod = await import('@/mesh/gateCatalogSnapshot');

    await expect(mod.fetchGateDetailSnapshot('infonet')).resolves.toEqual(
      expect.objectContaining({
        gate_id: 'infonet',
        display_name: 'Infonet Commons',
      }),
    );
    mod.invalidateGateDetailSnapshot('infonet');
    await expect(mod.fetchGateDetailSnapshot('infonet')).resolves.toEqual(
      expect.objectContaining({
        gate_id: 'infonet',
        display_name: 'Infonet Commons v2',
      }),
    );

    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
