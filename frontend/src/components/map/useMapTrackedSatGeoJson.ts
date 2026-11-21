import { useMemo } from 'react';
import { buildSatellitesGeoJSON } from '@/components/map/geojsonBuilders';

export function useMapTrackedSatGeoJson(ctx: any) {
  const { data, activeLayers, inView, interpSat, interpTick } = ctx;
  const trackedIcaoSet = useMemo(() => {
    const s = new Set<string>();
    if (data?.tracked_flights) {
      for (const t of data.tracked_flights) {
        if (t.icao24) s.add(t.icao24.toLowerCase());
      }
    }
    return s;
  }, [data?.tracked_flights]);
  const satellitesGeoJSON = useMemo(
    () => {
      void interpTick;
      return activeLayers.satellites ? buildSatellitesGeoJSON(data?.satellites, inView, interpSat) : null;
    },
    [activeLayers.satellites, data?.satellites, inView, interpSat, interpTick],
  );
  return { trackedIcaoSet, satellitesGeoJSON };
}
