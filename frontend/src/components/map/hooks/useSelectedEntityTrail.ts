import { useEffect } from 'react';
import { API_BASE } from '@/lib/api';
import { findSelectedEntity } from '@/components/map/geoJSONBuilders';
import {
  FLIGHT_SELECTION_TYPES,
  parseTrailPoints,
  flightPayloadHasKnownRoute,
} from '@/components/MaplibreViewer.helpers';
import type { TrailKind } from '@/components/MaplibreViewer.helpers';
import type { Flight, Ship } from '@/types/dashboard';

export function useSelectedEntityTrail({ selectedEntity, data, dynamicRoute, setSelectedTrailPoints }: any) {
  useEffect(() => {
    let cancelled = false;
    const entity = findSelectedEntity(selectedEntity, data);
    if (!selectedEntity || !entity) {
      setSelectedTrailPoints([]);
      return () => { cancelled = true; };
    }

    const isFlight = FLIGHT_SELECTION_TYPES.has(selectedEntity.type);
    const isShip = selectedEntity.type === 'ship';
    if (!isFlight && !isShip) {
      setSelectedTrailPoints([]);
      return () => { cancelled = true; };
    }

    if (isFlight && flightPayloadHasKnownRoute(entity)) {
      setSelectedTrailPoints([]);
      return () => { cancelled = true; };
    }

    const kind: TrailKind = isShip ? 'ship' : 'flight';
    const fallback = parseTrailPoints((entity as Flight | Ship).trail, kind);
    if (fallback.length >= 2) {
      setSelectedTrailPoints(fallback);
    } else {
      setSelectedTrailPoints([]);
    }

    const trailId = String(selectedEntity.id || '').trim();
    if (!trailId) {
      return () => { cancelled = true; };
    }
    if (isShip && !/^\d+$/.test(trailId)) {
      return () => { cancelled = true; };
    }

    const endpoint = isShip
      ? `${API_BASE}/api/trail/ship/${encodeURIComponent(trailId)}`
      : `${API_BASE}/api/trail/flight/${encodeURIComponent(trailId)}`;
    const refreshSelectedTrail = () => {
      fetch(endpoint, { cache: 'no-store' })
        .then((res) => (res.ok ? res.json() : null))
        .then((payload) => {
          if (cancelled || !payload) return;
          const points = parseTrailPoints(payload.trail, kind);
          setSelectedTrailPoints(points.length >= 2 ? points : fallback);
        })
        .catch(() => {
          if (!cancelled) setSelectedTrailPoints(fallback);
        });
    };
    refreshSelectedTrail();
    const trailRefreshTimer = window.setInterval(refreshSelectedTrail, 30000);

    return () => {
      cancelled = true;
      window.clearInterval(trailRefreshTimer);
    };
  }, [selectedEntity, data, dynamicRoute, setSelectedTrailPoints]);
}
