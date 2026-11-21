import { Layer, Source } from 'react-map-gl/maplibre';
import { EMPTY_FC } from '@/components/map/mapConstants';

export function VolcanoLayers() {
  return (
    <Source id="volcanoes-source" type="geojson" data={EMPTY_FC}>
      <Layer id="volcanoes-layer" type="symbol" layout={{ 'icon-image': ['get', 'iconId'], 'icon-size': ['interpolate', ['linear'], ['zoom'], 2, 0.4, 6, 0.7, 10, 1.0], 'icon-allow-overlap': true }} />
      <Layer id="volcanoes-label" type="symbol" layout={{ 'text-field': ['step', ['zoom'], '', 6, ['get', 'name']], 'text-font': ['Noto Sans Bold'], 'text-size': 10, 'text-offset': [0, 1.2], 'text-anchor': 'top', 'text-allow-overlap': false }} paint={{ 'text-color': '#f97316', 'text-halo-color': 'rgba(0,0,0,0.9)', 'text-halo-width': 1 }} />
    </Source>
  );
}
