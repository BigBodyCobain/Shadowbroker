import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

describe('layer backend reconciliation', () => {
  beforeEach(() => {
    vi.resetModules();
    localStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it('replays saved operator toggles when a restarted backend is back at defaults', async () => {
    const prefs = await import('@/lib/layerPreferences');
    const desired = {
      ...prefs.getDefaultActiveLayers(),
      cctv: true,
      datacenters: true,
      power_plants: true,
    };
    prefs.saveActiveLayers(desired);

    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ layers: prefs.getDefaultActiveLayers(), overrides: {} }),
      })
      .mockResolvedValueOnce({ ok: true });
    vi.stubGlobal('fetch', fetchMock);

    await expect(prefs.reconcileActiveLayersWithBackend()).resolves.toBe('synced');
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[1]?.[1]?.method).toBe('POST');
    const posted = JSON.parse(String(fetchMock.mock.calls[1]?.[1]?.body));
    expect(posted.layers.cctv).toBe(true);
    expect(posted.layers.datacenters).toBe(true);
    expect(posted.layers.power_plants).toBe(true);
  });

  it('does not fight a non-default backend state after a healthy connection', async () => {
    const prefs = await import('@/lib/layerPreferences');
    const desired = { ...prefs.getDefaultActiveLayers(), cctv: true };
    prefs.saveActiveLayers(desired);
    const otherClientState = { ...desired, datacenters: true };

    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ layers: desired, overrides: {} }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ layers: otherClientState, overrides: {} }),
      });
    vi.stubGlobal('fetch', fetchMock);

    await expect(prefs.reconcileActiveLayersWithBackend()).resolves.toBe('noop');
    await expect(prefs.reconcileActiveLayersWithBackend()).resolves.toBe('noop');
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls.every((call) => call[1]?.method !== 'POST')).toBe(true);
  });

  it('retries saved state after an observed backend outage', async () => {
    const prefs = await import('@/lib/layerPreferences');
    const desired = { ...prefs.getDefaultActiveLayers(), cctv: true };
    prefs.saveActiveLayers(desired);

    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new Error('backend restarting'))
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ layers: prefs.getDefaultActiveLayers(), overrides: {} }),
      })
      .mockResolvedValueOnce({ ok: true });
    vi.stubGlobal('fetch', fetchMock);

    await expect(prefs.reconcileActiveLayersWithBackend()).resolves.toBe('offline');
    await expect(prefs.reconcileActiveLayersWithBackend()).resolves.toBe('synced');
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(fetchMock.mock.calls[2]?.[1]?.method).toBe('POST');
  });
});
