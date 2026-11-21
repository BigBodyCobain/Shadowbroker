import { Layer, Source } from 'react-map-gl/maplibre';
import { EMPTY_FC } from '@/components/map/mapConstants';

export function FrontlinesLayer() {
  return (
        <Source id="frontlines" type="geojson" data={EMPTY_FC}>
          <Layer
            id="ukraine-frontline-layer"
            type="fill"
            paint={{
              'fill-color': '#ff0000',
              'fill-opacity': 0.3,
              'fill-outline-color': '#ff5500',
            }}
          />
        </Source>
  );
}
