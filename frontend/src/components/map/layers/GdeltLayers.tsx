import { Layer, Source } from 'react-map-gl/maplibre';
import { EMPTY_FC } from '@/components/map/mapConstants';

export function GdeltLayers() {
  return (
        <Source id="gdelt" type="geojson" data={EMPTY_FC}>
          <Layer
            id="gdelt-layer"
            type="circle"
            minzoom={4}
            paint={{
              'circle-radius': 5,
              'circle-color': '#ff8c00',
              'circle-stroke-color': '#ff0000',
              'circle-stroke-width': 1,
              'circle-opacity': 0.7,
            }}
          />
        </Source>
  );
}
