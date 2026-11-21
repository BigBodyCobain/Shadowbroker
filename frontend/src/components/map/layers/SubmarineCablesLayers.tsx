import { Layer, Source } from 'react-map-gl/maplibre';
import { EMPTY_FC } from '@/components/map/mapConstants';

export function SubmarineCablesLayers() {
  return (
        <Source id="submarine-cables-source" type="geojson" data={EMPTY_FC}>
          <Layer
            id="submarine-cables-layer"
            type="line"
            paint={{
              'line-color': '#eab308',
              'line-width': ['interpolate', ['linear'], ['zoom'], 2, 0.5, 6, 1.2, 10, 2],
              'line-opacity': 0.75,
            }}
          />
        </Source>
  );
}
