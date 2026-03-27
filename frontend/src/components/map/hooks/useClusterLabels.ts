'use client';

import { useEffect, useRef, useState } from 'react';
import type { MapRef } from 'react-map-gl/maplibre';
import type { MapGeoJSONFeature } from 'maplibre-gl';

export interface ClusterItem {
  lng: number;
  lat: number;
  count: string | number;
  id: number;
}

/**
 * Extracts cluster label positions from a MapLibre clustered source.
 * Queries only rendered cluster features for a given cluster layer to avoid
 * scanning the full clustered source on every update.
 *
 * @param mapRef - React ref to the MapLibre map instance
 * @param layerId - The rendered cluster layer ID to query (e.g. "ships-clusters-layer")
 * @param geoJSON - The GeoJSON data driving the source (null = no clusters)
 */
export function useClusterLabels(
  mapRef: React.RefObject<MapRef | null>,
  layerId: string,
  geoJSON: unknown | null,
): ClusterItem[] {
  const [clusters, setClusters] = useState<ClusterItem[]>([]);
  const handlerRef = useRef<(() => void) | null>(null);
  const rafRef = useRef<number | null>(null);
  const signatureRef = useRef('');

  useEffect(() => {
    const map = mapRef.current?.getMap();
    if (!map || !geoJSON) {
      setClusters([]);
      return;
    }

    // Remove previous handler if it exists
    if (handlerRef.current) {
      map.off('moveend', handlerRef.current);
      map.off('idle', handlerRef.current);
    }

    const runUpdate = () => {
      try {
        if (!map.getLayer(layerId)) {
          setClusters([]);
          signatureRef.current = '';
          return;
        }
        const features = map.queryRenderedFeatures(undefined, {
          layers: [layerId],
        }) as MapGeoJSONFeature[];
        const raw = features
          .filter((f) => f.properties?.cluster)
          .map((f) => {
            const point = f.geometry as GeoJSON.Point;
            return {
              lng: point.coordinates[0],
              lat: point.coordinates[1],
              count: f.properties?.point_count_abbreviated ?? f.properties?.point_count ?? 0,
              id: Number(f.properties?.cluster_id ?? 0),
            };
          });
        const seen = new Set<number>();
        const unique = raw.filter((c) => {
          if (seen.has(c.id)) return false;
          seen.add(c.id);
          return true;
        });
        const signature = unique
          .map((c) => `${c.id}:${c.count}:${c.lng.toFixed(3)}:${c.lat.toFixed(3)}`)
          .join('|');
        if (signature !== signatureRef.current) {
          signatureRef.current = signature;
          setClusters(unique);
        }
      } catch {
        if (signatureRef.current !== '') {
          signatureRef.current = '';
          setClusters([]);
        }
      }
    };
    const scheduleUpdate = () => {
      if (rafRef.current != null) {
        cancelAnimationFrame(rafRef.current);
      }
      rafRef.current = requestAnimationFrame(() => {
        rafRef.current = null;
        runUpdate();
      });
    };
    handlerRef.current = scheduleUpdate;

    map.on('moveend', scheduleUpdate);
    map.on('idle', scheduleUpdate);
    scheduleUpdate();

    return () => {
      map.off('moveend', scheduleUpdate);
      map.off('idle', scheduleUpdate);
      if (rafRef.current != null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
    };
  }, [geoJSON, layerId, mapRef]);

  return clusters;
}
