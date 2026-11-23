import { Layer, Source } from 'react-map-gl/maplibre';
import { EMPTY_FC } from '@/components/map/mapConstants';

export function MilitaryBasesLayers() {
  return (
        <Source id="military-bases" type="geojson" data={EMPTY_FC}>
          <Layer
            id="military-bases-layer"
            type="symbol"
            layout={{
              'icon-image': ['get', 'iconId'],
              'icon-size': ['interpolate', ['linear'], ['zoom'], 2, 0.5, 6, 0.8, 10, 1.0],
              'icon-allow-overlap': true,
            }}
          />
          <Layer
            id="military-bases-label"
            type="symbol"
            layout={{
              'text-field': ['step', ['zoom'], '', 5, ['get', 'name']],
              'text-font': ['Noto Sans Bold'],
              'text-size': 10,
              'text-offset': [0, 1.4],
              'text-anchor': 'top',
              'text-allow-overlap': false,
            }}
            paint={{
              'text-color': ['get', 'color'],
              'text-halo-color': 'rgba(0,0,0,0.9)',
              'text-halo-width': 1,
            }}
          />
        </Source>
  );
}
