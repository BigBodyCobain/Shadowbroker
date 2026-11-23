import { Layer, Source } from 'react-map-gl/maplibre';
import { EMPTY_FC } from '@/components/map/mapConstants';

export function UkraineAlertsLayers() {
  return (
    <>
      <Source id="ukraine-alerts-source" type="geojson" data={EMPTY_FC}>
        <Layer id="ukraine-alerts-fill" type="fill" paint={{ 'fill-color': ['get', 'color'], 'fill-opacity': 0.18 }} />
        <Layer id="ukraine-alerts-outline" type="line" paint={{ 'line-color': ['get', 'color'], 'line-width': 2.5, 'line-opacity': 0.8, 'line-dasharray': [6, 3] }} />
      </Source>
      <Source id="ukraine-alert-labels-source" type="geojson" data={EMPTY_FC}>
        <Layer id="ukraine-alert-labels" type="symbol" layout={{ 'text-field': ['concat', ['get', 'alert_label'], '\n', ['get', 'name_en']], 'text-font': ['Noto Sans Bold'], 'text-size': 11, 'text-allow-overlap': false, 'text-max-width': 12 }} paint={{ 'text-color': ['get', 'color'], 'text-halo-color': '#000000', 'text-halo-width': 1.5 }} />
      </Source>
    </>
  );
}
