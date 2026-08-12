import { useCallback, useRef, useState } from 'react';
import type { RefObject } from 'react';
import type { MapRef } from 'react-map-gl/maplibre';
import { API_BASE } from '@/lib/api';
import {
  coarsenViewBounds,
  expandBoundsToRadius,
  normalizeViewBounds,
  type ViewBounds,
} from '@/lib/viewportPrivacy';
import { setLiveDataBounds } from '@/lib/liveDataViewport';

const VIEWPORT_POST_DEBOUNCE_MS = 2500;
const VIEWPORT_POST_MIN_INTERVAL_MS = 12000;
const VIEWPORT_CHANGE_EPSILON = 1.5;
export const VIEWPORT_COMMITTED_EVENT = 'shadowbroker:viewport-committed';

// Fraction of the visible span added on every side when padding the culling
// box. 0.2 => the padded box spans 1.4x the visible box on each axis.
const MAP_BOUNDS_PAD = 0.2;

// How far the visible span may shrink, relative to the span of the padded box
// we last committed, before we re-tighten the culling box.
//
// A freshly committed box spans 1.4x the visible box. One zoom level in halves
// the visible span, so the ratio after a single zoom-in step is
// 0.5 / 1.4 ≈ 0.36 — comfortably under this threshold, meaning zooming in
// always re-tightens within one level rather than leaving a world-sized box
// pinned forever. Holding the line at 0.5 also caps how oversized a retained
// box can be: we only keep it while visibleSpan >= 0.5 * committedSpan, i.e.
// the box is never more than ~2x the visible span per axis. Over-inclusion is
// harmless (extra features render); under-inclusion would cull visible
// features, so the gate is deliberately one-sided.
const MAP_BOUNDS_SHRINK_RATIO = 0.5;

// Deliberately NOT VIEWPORT_CHANGE_EPSILON: that is an absolute 1.5-degree
// threshold sized for the backend viewport POST. A city-level viewport spans
// ~0.02 degrees, so an absolute gate of that size would freeze the culling box
// while panning and features would vanish. Everything here is relative to the
// current viewport span.

function boundsChanged(a: ViewBounds | null, b: ViewBounds): boolean {
  if (!a) return true;
  return (
    Math.abs(a.south - b.south) > VIEWPORT_CHANGE_EPSILON ||
    Math.abs(a.west - b.west) > VIEWPORT_CHANGE_EPSILON ||
    Math.abs(a.north - b.north) > VIEWPORT_CHANGE_EPSILON ||
    Math.abs(a.east - b.east) > VIEWPORT_CHANGE_EPSILON
  );
}

type PaddedBounds = [number, number, number, number];

/**
 * Decide whether the culling box has to be replaced.
 *
 * `committed` is the padded box currently held in `mapBounds`; the four
 * `visible*` values are the map's current visible bounds. Returns true when
 * the committed box no longer fully contains the visible viewport (a pan
 * escaped the pad, or a zoom-out grew past it) or when the viewport has
 * shrunk far enough that the committed box is wastefully oversized.
 */
function shouldRecommitBounds(
  committed: PaddedBounds | null,
  visibleWest: number,
  visibleSouth: number,
  visibleEast: number,
  visibleNorth: number,
): boolean {
  if (!committed) return true;
  if (
    !Number.isFinite(visibleWest) ||
    !Number.isFinite(visibleSouth) ||
    !Number.isFinite(visibleEast) ||
    !Number.isFinite(visibleNorth)
  ) {
    // Degenerate camera reading — recommit rather than risk keeping a box that
    // no longer covers what is on screen.
    return true;
  }

  // 1. Containment. Any escape at all invalidates the box: keeping a box that
  //    does not cover the viewport would cull features that are on screen.
  if (
    visibleWest < committed[0] ||
    visibleSouth < committed[1] ||
    visibleEast > committed[2] ||
    visibleNorth > committed[3]
  ) {
    return true;
  }

  // 2. Oversize. The box still contains the viewport, but the viewport has
  //    shrunk enough that we are culling far less than we could.
  const committedLngSpan = committed[2] - committed[0];
  const committedLatSpan = committed[3] - committed[1];
  const visibleLngSpan = visibleEast - visibleWest;
  const visibleLatSpan = visibleNorth - visibleSouth;
  if (committedLngSpan > 0 && visibleLngSpan < committedLngSpan * MAP_BOUNDS_SHRINK_RATIO) {
    return true;
  }
  if (committedLatSpan > 0 && visibleLatSpan < committedLatSpan * MAP_BOUNDS_SHRINK_RATIO) {
    return true;
  }

  return false;
}

export function useViewportBounds(
  mapRef: RefObject<MapRef | null>,
  viewBoundsRef?: { current: ViewBounds | null },
  backendViewportSyncEnabled: boolean = true,
) {
  // Viewport bounds for culling off-screen features [west, south, east, north]
  const [mapBounds, setMapBounds] = useState<[number, number, number, number]>([
    -180, -90, 180, 90,
  ]);

  const debounceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastPostedBoundsRef = useRef<ViewBounds | null>(null);
  const lastPostedAtRef = useRef(0);
  const lastCommittedBoundsRef = useRef<ViewBounds | null>(null);
  // The padded box currently published as `mapBounds`. Kept separate from
  // lastCommittedBoundsRef / lastPostedBoundsRef, which throttle the
  // viewport-committed event and the backend POST on their own schedules.
  const committedMapBoundsRef = useRef<PaddedBounds | null>(null);

  const updateBounds = useCallback(() => {
    const map = mapRef.current?.getMap();
    if (!map) return;
    const b = map.getBounds();
    const visibleWest = b.getWest();
    const visibleSouth = b.getSouth();
    const visibleEast = b.getEast();
    const visibleNorth = b.getNorth();
    const latRange = visibleNorth - visibleSouth;
    const lngRange = visibleEast - visibleWest;

    // `mapBounds` is a dependency of the layer-building workers, so a new
    // array reference rebuilds every static and dynamic layer. Only publish a
    // new box when the retained one stops being usable — see
    // shouldRecommitBounds. The invariant is that whatever sits in
    // `mapBounds` always fully contains the visible viewport.
    if (
      shouldRecommitBounds(
        committedMapBoundsRef.current,
        visibleWest,
        visibleSouth,
        visibleEast,
        visibleNorth,
      )
    ) {
      const next: PaddedBounds = [
        visibleWest - lngRange * MAP_BOUNDS_PAD,
        visibleSouth - latRange * MAP_BOUNDS_PAD,
        visibleEast + lngRange * MAP_BOUNDS_PAD,
        visibleNorth + latRange * MAP_BOUNDS_PAD,
      ];
      committedMapBoundsRef.current = next;
      setMapBounds(next);
    }

    const normalized = normalizeViewBounds({
      south: b.getSouth(),
      west: b.getWest(),
      north: b.getNorth(),
      east: b.getEast(),
    });
    const preloadBounds = coarsenViewBounds(expandBoundsToRadius(normalized));

    if (viewBoundsRef && 'current' in viewBoundsRef) {
      viewBoundsRef.current = preloadBounds;
    }

    if (boundsChanged(lastCommittedBoundsRef.current, preloadBounds)) {
      lastCommittedBoundsRef.current = preloadBounds;
      window.dispatchEvent(new CustomEvent(VIEWPORT_COMMITTED_EVENT));
    }

    // Issue #288: hand the same coarsened/expanded bounds to the live-data
    // poller so heavy collections in /api/live-data/{fast,slow} can be
    // scoped to the visible region. Static reference layers are unaffected
    // — see backend _FAST_BBOX_HEAVY_KEYS / _SLOW_BBOX_HEAVY_KEYS.
    setLiveDataBounds({
      south: preloadBounds.south,
      west: preloadBounds.west,
      north: preloadBounds.north,
      east: preloadBounds.east,
    });

    // Debounce POSTing viewport bounds to backend for dynamic AIS stream filtering
    if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current);
    debounceTimerRef.current = setTimeout(() => {
      if (!backendViewportSyncEnabled) {
        lastPostedBoundsRef.current = null;
        lastPostedAtRef.current = 0;
        return;
      }
      const now = Date.now();
      if (
        !boundsChanged(lastPostedBoundsRef.current, preloadBounds) &&
        now - lastPostedAtRef.current < VIEWPORT_POST_MIN_INTERVAL_MS
      ) {
        return;
      }
      if (now - lastPostedAtRef.current < VIEWPORT_POST_MIN_INTERVAL_MS) {
        return;
      }
      lastPostedBoundsRef.current = preloadBounds;
      lastPostedAtRef.current = now;
      fetch(`${API_BASE}/api/viewport`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          s: preloadBounds.south,
          w: preloadBounds.west,
          n: preloadBounds.north,
          e: preloadBounds.east,
        }),
      }).catch((e) => console.error('Failed to update backend viewport:', e));
    }, VIEWPORT_POST_DEBOUNCE_MS);
  }, [backendViewportSyncEnabled, mapRef, viewBoundsRef]);

  const inView = useCallback(
    (lat: number, lng: number) =>
      lng >= mapBounds[0] && lng <= mapBounds[2] && lat >= mapBounds[1] && lat <= mapBounds[3],
    [mapBounds],
  );

  const scheduleBoundsUpdate = useCallback(() => {
    updateBounds();
  }, [updateBounds]);

  return { mapBounds, inView, updateBounds, scheduleBoundsUpdate };
}
