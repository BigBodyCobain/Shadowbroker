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

const VIEWPORT_POST_DEBOUNCE_MS = 2500;
const VIEWPORT_POST_MIN_INTERVAL_MS = 12000;
const VIEWPORT_CHANGE_EPSILON = 1.5;
export const VIEWPORT_COMMITTED_EVENT = 'shadowbroker:viewport-committed';

function boundsChanged(a: ViewBounds | null, b: ViewBounds): boolean {
  if (!a) return true;
  return (
    Math.abs(a.south - b.south) > VIEWPORT_CHANGE_EPSILON ||
    Math.abs(a.west - b.west) > VIEWPORT_CHANGE_EPSILON ||
    Math.abs(a.north - b.north) > VIEWPORT_CHANGE_EPSILON ||
    Math.abs(a.east - b.east) > VIEWPORT_CHANGE_EPSILON
  );
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

  const updateBounds = useCallback(() => {
    const map = mapRef.current?.getMap();
    if (!map) return;
    const b = map.getBounds();
    const latRange = b.getNorth() - b.getSouth();
    const lngRange = b.getEast() - b.getWest();
    const buf = 0.2; // 20% buffer
    setMapBounds([
      b.getWest() - lngRange * buf,
      b.getSouth() - latRange * buf,
      b.getEast() + lngRange * buf,
      b.getNorth() + latRange * buf,
    ]);

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
