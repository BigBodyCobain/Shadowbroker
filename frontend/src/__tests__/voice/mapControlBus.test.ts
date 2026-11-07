/**
 * §7.D item 30 — mapControlBus: a dead/unresponsive viewer yields
 * {ok:false} after the timeout (never wedges the caller), and getViewState
 * round-trips through the registered viewer handler.
 */
import { describe, expect, it, vi, afterEach } from 'vitest';

import {
  emitViewState,
  onRequest,
  onViewState,
  send,
  type MapBusResult,
} from '@/lib/mapControlBus';

describe('mapControlBus', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('send without a connected viewer resolves {ok:false} immediately', async () => {
    const result = await send({ type: 'getViewState' });
    expect(result.ok).toBe(false);
    expect(result.error).toBe('map viewer is not connected');
  });

  it('unresponsive viewer resolves {ok:false} within the timeout', async () => {
    const unsub = onRequest(() => new Promise<MapBusResult>(() => undefined));
    try {
      const started = Date.now();
      const result = await send({ type: 'zoom', direction: 'in', amount: 'little' }, 25);
      expect(result.ok).toBe(false);
      expect(result.error).toBe('operator client did not respond');
      expect(Date.now() - started).toBeLessThan(2000);
    } finally {
      unsub();
    }
  });

  it('getViewState round-trips through the viewer handler', async () => {
    const unsub = onRequest((cmd) => {
      if (cmd.type !== 'getViewState') return { ok: false, action: cmd.type, error: 'unexpected' };
      return {
        ok: true,
        action: 'get_view_state',
        view: { center: { lat: 50.45, lng: 30.52 }, zoom: 9 },
      };
    });
    try {
      const result = await send({ type: 'getViewState' });
      expect(result.ok).toBe(true);
      expect(result.view).toEqual({ center: { lat: 50.45, lng: 30.52 }, zoom: 9 });
    } finally {
      unsub();
    }
  });

  it('onViewState subscribes and unsubscribes cleanly', () => {
    const cb = vi.fn();
    const unsub = onViewState(cb);
    emitViewState({ center: { lat: 1, lng: 2 }, zoom: 5 });
    expect(cb).toHaveBeenCalledTimes(1);
    expect(cb).toHaveBeenLastCalledWith({ center: { lat: 1, lng: 2 }, zoom: 5 });
    unsub();
    emitViewState({ center: { lat: 3, lng: 4 }, zoom: 6 });
    expect(cb).toHaveBeenCalledTimes(1);
  });
});
