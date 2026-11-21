import { Layer, Source } from 'react-map-gl/maplibre';
import { EMPTY_FC } from '@/components/map/mapConstants';

export function WeatherAlertsLayers() {
  return (
    <>
      <Source id="weather-alerts-source" type="geojson" data={EMPTY_FC}>
        <Layer id="weather-alerts-fill" type="fill" paint={{ 'fill-color': ['get', 'color'], 'fill-opacity': 0.12 }} />
        <Layer id="weather-alerts-outline" type="line" paint={{ 'line-color': ['get', 'color'], 'line-width': 2, 'line-opacity': 0.7, 'line-dasharray': [4, 3] }} />
      </Source>
      <Source id="weather-alert-labels-source" type="geojson" data={EMPTY_FC}>
        <Layer id="weather-alert-icons" type="symbol" layout={{ 'icon-image': ['get', 'iconId'], 'icon-size': 1.1, 'icon-allow-overlap': true, 'icon-anchor': 'bottom', 'text-field': ['get', 'event'], 'text-font': ['Noto Sans Bold'], 'text-size': 11, 'text-offset': [0, 0.4], 'text-anchor': 'top', 'text-allow-overlap': false, 'text-max-width': 14 }} paint={{ 'text-color': ['get', 'color'], 'text-halo-color': '#000000', 'text-halo-width': 1.5 }} />
      </Source>
    </>
  );
}
