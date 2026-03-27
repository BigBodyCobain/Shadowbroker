import { useEffect, useRef } from 'react';
import type { MapRef } from 'react-map-gl/maplibre';
import type { GeoJSONSource } from 'maplibre-gl';
import { EMPTY_FC } from '@/components/map/mapConstants';

// Imperatively push GeoJSON data to a MapLibre source, bypassing React reconciliation.
// This is critical for high-volume layers (flights, ships, satellites, fires) where
// React's prop diffing on thousands of coordinate arrays causes memory pressure.
export function useImperativeSource(
  map: MapRef | null,
  sourceId: string,
  geojson: GeoJSON.FeatureCollection | null,
  debounceMs = 0,
) {
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const prevRef = useRef<GeoJSON.FeatureCollection | null>(null);

  useEffect(() => {
    if (!map) return;

    let cancelled = false;
    const data = geojson || EMPTY_FC;
    const rawMap = map.getMap();

    const push = () => {
      if (cancelled) return true;
      const src = rawMap.getSource(sourceId) as GeoJSONSource | undefined;
      if (src && typeof src.setData === 'function') {
        src.setData(data);
        return true;
      }
      return false;
    };

    const pushWhenReady = () => {
      let attemptsRemaining = 20;

      const tryPush = () => {
        if (cancelled) return;
        if (push()) return;
        if (attemptsRemaining <= 0) return;
        attemptsRemaining -= 1;
        if (retryTimerRef.current) clearTimeout(retryTimerRef.current);
        retryTimerRef.current = setTimeout(tryPush, 100);
      };

      tryPush();
    };

    const schedulePush = () => {
      if (cancelled) return;
      if (debounceMs > 0) {
        if (timerRef.current) clearTimeout(timerRef.current);
        timerRef.current = setTimeout(pushWhenReady, debounceMs);
        return;
      }
      pushWhenReady();
    };

    const handleStyleData = () => {
      pushWhenReady();
    };

    rawMap.on('styledata', handleStyleData);

    // Skip redundant writes for unchanged references, but keep the styledata
    // listener active so sources repopulate after style reloads.
    if (geojson !== prevRef.current) {
      prevRef.current = geojson;
      schedulePush();
    }

    return () => {
      cancelled = true;
      rawMap.off('styledata', handleStyleData);
      if (timerRef.current) clearTimeout(timerRef.current);
      if (retryTimerRef.current) clearTimeout(retryTimerRef.current);
    };
  }, [map, sourceId, geojson, debounceMs]);
}
