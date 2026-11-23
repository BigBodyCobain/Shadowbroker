import { Layer, Source } from 'react-map-gl/maplibre';
import { EMPTY_FC } from '@/components/map/mapConstants';

export function TrainsLayers() {
  return (
        <Source id="trains" type="geojson" data={EMPTY_FC}>
          <Layer
            id="trains-layer"
            type="symbol"
            layout={{
              'icon-image': ['get', 'iconId'],
              'icon-size': ['interpolate', ['linear'], ['zoom'], 0, 0.3, 4, 0.5, 8, 0.8, 12, 1.0],
              'icon-allow-overlap': true,
            }}
          />
        </Source>
  );
}
