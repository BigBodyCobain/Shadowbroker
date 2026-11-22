import { useEffect, useMemo } from 'react';
import * as maplibregl from 'maplibre-gl';
import { buildUkraineAlertsGeoJSON, buildUkraineAlertLabelsGeoJSON, buildWeatherAlertsGeoJSON, buildWeatherAlertLabelsGeoJSON } from '@/components/map/geoJSONBuilders';
import { buildSentinelTileUrl, hasSentinelCredentials, getSentinelToken, registerSentinelProtocol } from '@/lib/sentinelHub';

export function useMapAlertGeoJson(ctx: any) {
  const { activeLayers, data, sentinelPreset, sentinelDate } = ctx;
  const ukraineAlertsGeoJSON = useMemo(
    () => (activeLayers.ukraine_alerts ? buildUkraineAlertsGeoJSON(data?.ukraine_alerts) : null),
    [activeLayers.ukraine_alerts, data?.ukraine_alerts],
  );
  const ukraineAlertLabelsGeoJSON = useMemo(
    () => (activeLayers.ukraine_alerts ? buildUkraineAlertLabelsGeoJSON(data?.ukraine_alerts) : null),
    [activeLayers.ukraine_alerts, data?.ukraine_alerts],
  );
  const weatherAlertsGeoJSON = useMemo(
    () => (activeLayers.weather_alerts ? buildWeatherAlertsGeoJSON(data?.weather_alerts) : null),
    [activeLayers.weather_alerts, data?.weather_alerts],
  );
  const weatherAlertLabelsGeoJSON = useMemo(
    () => (activeLayers.weather_alerts ? buildWeatherAlertLabelsGeoJSON(data?.weather_alerts) : null),
    [activeLayers.weather_alerts, data?.weather_alerts],
  );
  const sentinelTileUrl = useMemo(() => {
    if (!activeLayers.sentinel_hub) return null;
    if (!hasSentinelCredentials()) return null;
    return buildSentinelTileUrl(sentinelPreset || 'TRUE-COLOR', sentinelDate || '');
  }, [activeLayers.sentinel_hub, sentinelPreset, sentinelDate]);
  useEffect(() => { registerSentinelProtocol(maplibregl); }, []);
  useEffect(() => {
    if (!activeLayers.sentinel_hub) return;
    getSentinelToken().catch((err) => console.warn('Sentinel Hub token error:', err));
  }, [activeLayers.sentinel_hub, sentinelPreset, sentinelDate]);
  return { ukraineAlertsGeoJSON, ukraineAlertLabelsGeoJSON, weatherAlertsGeoJSON, weatherAlertLabelsGeoJSON, sentinelTileUrl };
}
