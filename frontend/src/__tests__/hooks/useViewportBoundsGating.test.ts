/**
 * Culling-box gating in useViewportBounds.
 *
 * `mapBounds` is a build dependency of both layer workers in
 * MaplibreViewer, so every new array reference rebuilds ~36 layers and
 * re-uploads them to the GPU. The hook therefore only republishes the padded
 * box when the retained one stops being usable.
 *
 * The invariant that makes the gate safe: whatever `mapBounds` holds must
 * always fully contain the visible viewport, because `inView()` culls against
 * it. An oversized box is harmless (features render that did not need to);
 * an undersized box makes on-screen features disappear.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';

import { useViewportBounds } from '@/components/map/hooks/useViewportBounds';
import { setLiveDataBounds } from '@/lib/liveDataViewport';

type Visible = { west: number; south: number; east: number; north: number };

function makeMapRef(initial: Visible) {
  const visible = { ...initial };
  const map = {
    getBounds: () => ({
      getWest: () => visible.west,
      getSouth: () => visible.south,
      getEast: () => visible.east,
      getNorth: () => visible.north,
    }),
  };
  return {
    ref: { current: { getMap: () => map } } as never,
    setVisible(next: Visible) {
      Object.assign(visible, next);
    },
    get visible(): Visible {
      return { ...visible };
    },
  };
}

/** A viewport centered on (lat, lng) spanning `span` degrees each way. */
function box(lat: number, lng: number, span: number): Visible {
  return {
    west: lng - span / 2,
    south: lat - span / 2,
    east: lng + span / 2,
    north: lat + span / 2,
  };
}

function contains(bounds: [number, number, number, number], v: Visible): boolean {
  return (
    v.west >= bounds[0] && v.south >= bounds[1] && v.east <= bounds[2] && v.north <= bounds[3]
  );
}

describe('useViewportBounds — mapBounds gating', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true }));
  });

  afterEach(() => {
    setLiveDataBounds(null);
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  // City-scale viewport: ~0.02 degrees across. This is the scale at which an
  // absolute-degree gate (e.g. VIEWPORT_CHANGE_EPSILON = 1.5) would never fire
  // and culling would silently break.
  const CITY_SPAN = 0.02;

  it('commits a padded box on the first update', () => {
    const map = makeMapRef(box(51.5, -0.12, CITY_SPAN));
    const { result } = renderHook(() => useViewportBounds(map.ref, undefined, false));

    act(() => result.current.updateBounds());

    const bounds = result.current.mapBounds;
    expect(contains(bounds, map.visible)).toBe(true);
    // 20% pad on each side => the box spans 1.4x the visible box.
    expect(bounds[2] - bounds[0]).toBeCloseTo(CITY_SPAN * 1.4, 10);
    expect(bounds[3] - bounds[1]).toBeCloseTo(CITY_SPAN * 1.4, 10);
  });

  it('keeps the same reference for a small pan that stays inside the pad', () => {
    const map = makeMapRef(box(51.5, -0.12, CITY_SPAN));
    const { result } = renderHook(() => useViewportBounds(map.ref, undefined, false));

    act(() => result.current.updateBounds());
    const first = result.current.mapBounds;

    // Nudge by 10% of the span — well inside the 20% pad.
    map.setVisible(box(51.5 + CITY_SPAN * 0.1, -0.12 + CITY_SPAN * 0.1, CITY_SPAN));
    act(() => result.current.updateBounds());

    expect(result.current.mapBounds).toBe(first);
    expect(contains(result.current.mapBounds, map.visible)).toBe(true);
  });

  it('is idempotent when called twice for the same camera (onMoveEnd + onIdle)', () => {
    const map = makeMapRef(box(51.5, -0.12, CITY_SPAN));
    const { result } = renderHook(() => useViewportBounds(map.ref, undefined, false));

    act(() => result.current.updateBounds());
    const first = result.current.mapBounds;
    act(() => result.current.updateBounds());

    expect(result.current.mapBounds).toBe(first);
  });

  it('updates when a pan escapes the pad', () => {
    const map = makeMapRef(box(51.5, -0.12, CITY_SPAN));
    const { result } = renderHook(() => useViewportBounds(map.ref, undefined, false));

    act(() => result.current.updateBounds());
    const first = result.current.mapBounds;

    // Pan by 50% of the span — past the 20% pad.
    map.setVisible(box(51.5, -0.12 + CITY_SPAN * 0.5, CITY_SPAN));
    act(() => result.current.updateBounds());

    expect(result.current.mapBounds).not.toBe(first);
    expect(contains(result.current.mapBounds, map.visible)).toBe(true);
  });

  it('updates when zooming out', () => {
    const map = makeMapRef(box(51.5, -0.12, CITY_SPAN));
    const { result } = renderHook(() => useViewportBounds(map.ref, undefined, false));

    act(() => result.current.updateBounds());
    const first = result.current.mapBounds;

    map.setVisible(box(51.5, -0.12, CITY_SPAN * 2));
    act(() => result.current.updateBounds());

    expect(result.current.mapBounds).not.toBe(first);
    expect(contains(result.current.mapBounds, map.visible)).toBe(true);
  });

  it('tightens the box after zooming in', () => {
    const map = makeMapRef(box(51.5, -0.12, 40));
    const { result } = renderHook(() => useViewportBounds(map.ref, undefined, false));

    act(() => result.current.updateBounds());
    const wide = result.current.mapBounds;

    // A single zoom level in (span halves) already trips the shrink gate:
    // 0.5 / 1.4 is below the 0.5 ratio threshold.
    map.setVisible(box(51.5, -0.12, 20));
    act(() => result.current.updateBounds());
    const tighter = result.current.mapBounds;

    expect(tighter).not.toBe(wide);
    expect(tighter[2] - tighter[0]).toBeLessThan(wide[2] - wide[0]);

    // Keep zooming: the box must track down to city scale, not stay world-sized.
    for (let span = 10; span >= CITY_SPAN; span /= 2) {
      map.setVisible(box(51.5, -0.12, span));
      act(() => result.current.updateBounds());
    }
    const bounds = result.current.mapBounds;
    expect(bounds[2] - bounds[0]).toBeLessThan(CITY_SPAN * 4);
    expect(contains(bounds, map.visible)).toBe(true);
  });

  it('never lets the retained box exceed ~2x the visible span', () => {
    const map = makeMapRef(box(0, 0, 8));
    const { result } = renderHook(() => useViewportBounds(map.ref, undefined, false));

    act(() => result.current.updateBounds());

    for (let span = 8; span >= 0.05; span *= 0.9) {
      map.setVisible(box(0, 0, span));
      act(() => result.current.updateBounds());
      const bounds = result.current.mapBounds;
      expect(contains(bounds, map.visible)).toBe(true);
      expect(bounds[2] - bounds[0]).toBeLessThanOrEqual(span * 2 + 1e-9);
      expect(bounds[3] - bounds[1]).toBeLessThanOrEqual(span * 2 + 1e-9);
    }
  });

  it('holds the containment invariant across a long mixed sequence of moves', () => {
    const map = makeMapRef(box(0, 0, 30));
    const { result } = renderHook(() => useViewportBounds(map.ref, undefined, false));
    act(() => result.current.updateBounds());

    // Deterministic pseudo-random walk of pans and zooms.
    let seed = 12345;
    const rand = () => {
      seed = (seed * 1103515245 + 12345) % 2147483648;
      return seed / 2147483648;
    };

    let lat = 0;
    let lng = 0;
    let span = 30;
    let updates = 0;
    let previous = result.current.mapBounds;

    for (let i = 0; i < 400; i += 1) {
      // Pan by up to +/-35% of the span, and jitter the zoom by up to ~1.25x
      // either way, so the sequence contains both gated and ungated moves.
      lat = Math.max(-60, Math.min(60, lat + (rand() - 0.5) * span * 0.7));
      lng = Math.max(-160, Math.min(160, lng + (rand() - 0.5) * span * 0.7));
      span = Math.max(0.01, Math.min(60, span * (0.8 + rand() * 0.45)));

      map.setVisible(box(lat, lng, span));
      act(() => result.current.updateBounds());

      const bounds = result.current.mapBounds;
      // The invariant, checked after every single move.
      expect(contains(bounds, map.visible)).toBe(true);
      if (bounds !== previous) {
        updates += 1;
        previous = bounds;
      }
    }

    // Sanity: the gate is a gate, not a freeze — it both fires and holds.
    expect(updates).toBeGreaterThan(0);
    expect(updates).toBeLessThan(400);
  });

  it('keeps the non-gated side effects running on every call', async () => {
    const { liveDataBoundsKey } = await import('@/lib/liveDataViewport');
    const map = makeMapRef(box(51.5, -0.12, CITY_SPAN));
    const viewBoundsRef: { current: unknown } = { current: null };
    const { result } = renderHook(
      () => useViewportBounds(map.ref, viewBoundsRef as never, false),
    );

    setLiveDataBounds(null);
    act(() => result.current.updateBounds());
    const firstBounds = result.current.mapBounds;
    const firstRef = viewBoundsRef.current;
    expect(firstRef).not.toBeNull();
    expect(liveDataBoundsKey()).not.toBeNull();

    // A pan small enough to be gated out of mapBounds must still refresh
    // viewBoundsRef and the live-data bounds.
    setLiveDataBounds(null);
    map.setVisible(box(51.5 + CITY_SPAN * 0.05, -0.12, CITY_SPAN));
    act(() => result.current.updateBounds());

    expect(result.current.mapBounds).toBe(firstBounds);
    expect(viewBoundsRef.current).not.toBe(firstRef);
    expect(liveDataBoundsKey()).not.toBeNull();
  });
});
