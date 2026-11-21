import { useMemo } from 'react';
import { buildEarthquakesGeoJSON, buildJammingGeoJSON, buildCorrelationsGeoJSON, buildGtRiskGeoJSON, buildTinygsGeoJSON, buildShodanGeoJSON, buildAIIntelGeoJSON } from '@/components/map/geojsonBuilders';

export function useMapCoreGeoJson(ctx: any) {
  const { activeLayers, data, inView, interpSat, interpTick, shodanResults, aiIntelPins } = ctx;
  const earthquakesGeoJSON = useMemo(
    () => (activeLayers.earthquakes ? buildEarthquakesGeoJSON(data?.earthquakes) : null),
    [activeLayers.earthquakes, data?.earthquakes],
  );
  const jammingGeoJSON = useMemo(
    () => (activeLayers.gps_jamming ? buildJammingGeoJSON(data?.gps_jamming) : null),
    [activeLayers.gps_jamming, data?.gps_jamming],
  );
  const correlationsGeoJSON = useMemo(
    () => {
      if (!activeLayers.correlations && !activeLayers.contradictions) return null;
      const alerts = data?.correlations?.filter((a: any) => {
        if (a.type === 'contradiction') return activeLayers.contradictions;
        return activeLayers.correlations;
      });
      return buildCorrelationsGeoJSON(alerts);
    },
    [activeLayers.correlations, activeLayers.contradictions, data?.correlations],
  );
  const gtRiskGeoJSON = useMemo(
    () => (activeLayers.gt_risk ? buildGtRiskGeoJSON(data?.gt_risk) : null),
    [activeLayers.gt_risk, data?.gt_risk],
  );
  const tinygsGeoJSON = useMemo(
    () => {
      void interpTick;
      return activeLayers.tinygs ? buildTinygsGeoJSON(data?.tinygs_satellites, inView, interpSat) : null;
    },
    [activeLayers.tinygs, data?.tinygs_satellites, inView, interpSat, interpTick],
  );
  const shodanGeoJSON = useMemo(
    () => (activeLayers.shodan_overlay ? buildShodanGeoJSON(shodanResults) : null),
    [activeLayers.shodan_overlay, shodanResults],
  );
  const aiIntelGeoJSON = useMemo(
    () => (activeLayers.ai_intel ? buildAIIntelGeoJSON(aiIntelPins, data) : null),
    [activeLayers.ai_intel, aiIntelPins, data],
  );
  return { earthquakesGeoJSON, jammingGeoJSON, correlationsGeoJSON, gtRiskGeoJSON, tinygsGeoJSON, shodanGeoJSON, aiIntelGeoJSON };
}
