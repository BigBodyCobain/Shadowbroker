import { beforeEach, describe, expect, it, vi } from 'vitest';

const hasLocalControlBridge = vi.fn(() => false);
const buildGateAccessHeaders = vi.fn();

vi.mock('@/lib/localControlTransport', () => ({
  hasLocalControlBridge,
}));

vi.mock('@/mesh/gateAccessProof', () => ({
  buildGateAccessHeaders,
}));

describe('gateMessageSnapshot cache', () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.resetModules();
    fetchMock.mockReset();
    buildGateAccessHeaders.mockReset();
    hasLocalControlBridge.mockReset();
    hasLocalControlBridge.mockReturnValue(false);
    buildGateAccessHeaders.mockResolvedValue({
      'X-Wormhole-Node-Id': '!sb_gate',
      'X-Wormhole-Gate-Proof': 'proof',
      'X-Wormhole-Gate-Ts': '1712345678',
    });
    vi.stubGlobal('fetch', fetchMock);
  });

  it('coarsens browser/web gate message reads through a short shared cache window', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-04-05T23:45:00.000Z'));
    try {
      fetchMock.mockResolvedValue({
        ok: true,
        json: async () => ({
          messages: [{ event_id: 'evt-1', gate: 'infonet', timestamp: 1712360000 }],
        }),
      });

      const mod = await import('@/mesh/gateMessageSnapshot');

      await expect(mod.fetchGateMessageSnapshot('infonet', 20)).resolves.toEqual([
        expect.objectContaining({ event_id: 'evt-1', gate: 'infonet' }),
      ]);
      await mod.fetchGateMessageSnapshot('infonet', 20);

      expect(fetchMock).toHaveBeenCalledTimes(1);

      vi.advanceTimersByTime(10_001);

      await mod.fetchGateMessageSnapshot('infonet', 20);
      expect(fetchMock).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it('reuses a larger cached limit for smaller reads without another fetch', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({
        messages: Array.from({ length: 8 }, (_, index) => ({
          event_id: `evt-${index + 1}`,
          gate: 'finance',
          timestamp: 1712360000 + index,
        })),
      }),
    });

    const mod = await import('@/mesh/gateMessageSnapshot');

    await expect(mod.fetchGateMessageSnapshot('finance', 8)).resolves.toHaveLength(8);
    await expect(mod.fetchGateMessageSnapshot('finance', 4)).resolves.toHaveLength(4);

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('uses session-stream proof reuse for stream-owned snapshot refreshes', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({
        messages: [{ event_id: 'evt-1', gate: 'finance', timestamp: 1712360000 }],
        cursor: 1,
      }),
    });

    const mod = await import('@/mesh/gateMessageSnapshot');

    await expect(
      mod.fetchGateMessageSnapshotState('finance', 20, { proofMode: 'session_stream' }),
    ).resolves.toEqual({
      messages: [expect.objectContaining({ event_id: 'evt-1', gate: 'finance' })],
      cursor: 1,
    });

    expect(buildGateAccessHeaders).toHaveBeenCalledWith('finance', { mode: 'session_stream' });
  });

  it('reuses a larger in-flight snapshot fetch for a smaller concurrent read', async () => {
    let releaseFetch:
      | ((value: {
          ok: true;
          json: () => Promise<{
            messages: Array<{ event_id: string; gate: string; timestamp: number }>;
            cursor: number;
          }>;
        }) => void)
      | null = null;
    fetchMock.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          releaseFetch = resolve as typeof releaseFetch;
        }),
    );

    const mod = await import('@/mesh/gateMessageSnapshot');

    const larger = mod.fetchGateMessageSnapshotState('infonet', 40);
    const smaller = mod.fetchGateMessageSnapshotState('infonet', 20);

    await Promise.resolve();
    await Promise.resolve();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0]?.[0] || '')).toContain('/api/mesh/infonet/messages?gate=infonet&limit=40');

    releaseFetch?.({
      ok: true,
      json: async () => ({
        messages: Array.from({ length: 3 }, (_, index) => ({
          event_id: `evt-${index + 1}`,
          gate: 'infonet',
          timestamp: 1712360000 + index,
        })),
        cursor: 3,
      }),
    });

    await expect(larger).resolves.toEqual({
      messages: [
        expect.objectContaining({ event_id: 'evt-1', gate: 'infonet' }),
        expect.objectContaining({ event_id: 'evt-2', gate: 'infonet' }),
        expect.objectContaining({ event_id: 'evt-3', gate: 'infonet' }),
      ],
      cursor: 3,
    });
    await expect(smaller).resolves.toEqual({
      messages: [
        expect.objectContaining({ event_id: 'evt-1', gate: 'infonet' }),
        expect.objectContaining({ event_id: 'evt-2', gate: 'infonet' }),
        expect.objectContaining({ event_id: 'evt-3', gate: 'infonet' }),
      ],
      cursor: 3,
    });
  });

  it('uses a shorter native cache window and supports explicit invalidation', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-04-05T23:45:00.000Z'));
    try {
      hasLocalControlBridge.mockReturnValue(true);
      fetchMock
        .mockResolvedValueOnce({
          ok: true,
          json: async () => ({
            messages: [{ event_id: 'evt-1', gate: 'ops', timestamp: 1712360000 }],
          }),
        })
        .mockResolvedValueOnce({
          ok: true,
          json: async () => ({
            messages: [{ event_id: 'evt-2', gate: 'ops', timestamp: 1712360010 }],
          }),
        })
        .mockResolvedValueOnce({
          ok: true,
          json: async () => ({
            messages: [{ event_id: 'evt-3', gate: 'ops', timestamp: 1712360020 }],
          }),
        });

      const mod = await import('@/mesh/gateMessageSnapshot');

      await expect(mod.fetchGateMessageSnapshot('ops', 6)).resolves.toEqual([
        expect.objectContaining({ event_id: 'evt-1' }),
      ]);
      vi.advanceTimersByTime(3_001);
      await expect(mod.fetchGateMessageSnapshot('ops', 6)).resolves.toEqual([
        expect.objectContaining({ event_id: 'evt-2' }),
      ]);

      mod.invalidateGateMessageSnapshot('ops');
      await expect(mod.fetchGateMessageSnapshot('ops', 6)).resolves.toEqual([
        expect.objectContaining({ event_id: 'evt-3' }),
      ]);

      expect(fetchMock).toHaveBeenCalledTimes(3);
    } finally {
      vi.useRealTimers();
    }
  });

  it('tracks cursors and waits for gate changes without re-reading the ordinary route', async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          messages: [{ event_id: 'evt-1', gate: 'infonet', timestamp: 1712360000 }],
          cursor: 1,
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          messages: [
            { event_id: 'evt-2', gate: 'infonet', timestamp: 1712360010 },
            { event_id: 'evt-1', gate: 'infonet', timestamp: 1712360000 },
          ],
          cursor: 2,
          changed: true,
        }),
      });

    const mod = await import('@/mesh/gateMessageSnapshot');

    await expect(mod.fetchGateMessageSnapshotState('infonet', 20)).resolves.toEqual({
      messages: [expect.objectContaining({ event_id: 'evt-1', gate: 'infonet' })],
      cursor: 1,
    });
    await expect(mod.waitForGateMessageSnapshot('infonet', 1, 20, { timeoutMs: 18_000 })).resolves.toEqual({
      messages: [
        expect.objectContaining({ event_id: 'evt-2', gate: 'infonet' }),
        expect.objectContaining({ event_id: 'evt-1', gate: 'infonet' }),
      ],
      cursor: 2,
      changed: true,
    });
    expect(mod.getGateMessageSnapshotCursor('infonet')).toBe(2);
    expect(fetchMock.mock.calls[1]?.[0]).toContain('/api/mesh/infonet/messages/wait?gate=infonet&after=1');
  });

  it('coalesces concurrent gate wait requests for the same gate cursor', async () => {
    let releaseWait:
      | ((value: { ok: true; json: () => Promise<{ messages: Array<{ event_id: string; gate: string; timestamp: number }>; cursor: number; changed: boolean }> }) => void)
      | null = null;
    fetchMock.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          releaseWait = resolve as typeof releaseWait;
        }),
    );

    const mod = await import('@/mesh/gateMessageSnapshot');

    const first = mod.waitForGateMessageSnapshot('infonet', 4, 20, { timeoutMs: 18_000 });
    const second = mod.waitForGateMessageSnapshot('infonet', 4, 20, { timeoutMs: 24_000 });

    await Promise.resolve();
    await Promise.resolve();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0]?.[0] || '')).toContain('/api/mesh/infonet/messages/wait?gate=infonet&after=4');

    releaseWait?.({
      ok: true,
      json: async () => ({
        messages: [{ event_id: 'evt-5', gate: 'infonet', timestamp: 1712360050 }],
        cursor: 5,
        changed: true,
      }),
    });

    await expect(first).resolves.toEqual({
      messages: [expect.objectContaining({ event_id: 'evt-5', gate: 'infonet' })],
      cursor: 5,
      changed: true,
    });
    await expect(second).resolves.toEqual({
      messages: [expect.objectContaining({ event_id: 'evt-5', gate: 'infonet' })],
      cursor: 5,
      changed: true,
    });
  });

  it('reuses a larger in-flight gate wait for a smaller concurrent consumer', async () => {
    let releaseWait:
      | ((value: {
          ok: true;
          json: () => Promise<{
            messages: Array<{ event_id: string; gate: string; timestamp: number }>;
            cursor: number;
            changed: boolean;
          }>;
        }) => void)
      | null = null;
    fetchMock.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          releaseWait = resolve as typeof releaseWait;
        }),
    );

    const mod = await import('@/mesh/gateMessageSnapshot');

    const larger = mod.waitForGateMessageSnapshot('infonet', 4, 40, { timeoutMs: 18_000 });
    const smaller = mod.waitForGateMessageSnapshot('infonet', 4, 20, { timeoutMs: 24_000 });

    await Promise.resolve();
    await Promise.resolve();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0]?.[0] || '')).toContain('/api/mesh/infonet/messages/wait?gate=infonet&after=4&limit=40');

    releaseWait?.({
      ok: true,
      json: async () => ({
        messages: [
          { event_id: 'evt-8', gate: 'infonet', timestamp: 1712360080 },
          { event_id: 'evt-7', gate: 'infonet', timestamp: 1712360070 },
        ],
        cursor: 8,
        changed: true,
      }),
    });

    await expect(larger).resolves.toEqual({
      messages: [
        expect.objectContaining({ event_id: 'evt-8', gate: 'infonet' }),
        expect.objectContaining({ event_id: 'evt-7', gate: 'infonet' }),
      ],
      cursor: 8,
      changed: true,
    });
    await expect(smaller).resolves.toEqual({
      messages: [
        expect.objectContaining({ event_id: 'evt-8', gate: 'infonet' }),
        expect.objectContaining({ event_id: 'evt-7', gate: 'infonet' }),
      ],
      cursor: 8,
      changed: true,
    });
  });
});
