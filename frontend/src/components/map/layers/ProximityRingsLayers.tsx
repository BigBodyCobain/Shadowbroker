import { Layer, Source } from 'react-map-gl/maplibre';
import { EMPTY_FC } from '@/components/map/mapConstants';

export function ProximityRingsLayers() {
  return (
    <>
        <Source id="proximity-rings" type="geojson" data={EMPTY_FC}>
          <Layer
            id="proximity-rings-layer"
            type="line"
            paint={{
              'line-color': 'rgba(34, 211, 238, 0.15)',
              'line-width': 1,
              'line-dasharray': [6, 4],
            }}
          />
          <Layer
            id="proximity-rings-labels"
            type="symbol"
            layout={{
              'symbol-placement': 'line',
              'text-field': ['get', 'label'],
              'text-size': 10,
              'text-font': ['Noto Sans Regular'],
              'text-offset': [0, -0.8],
            }}
            paint={{
              'text-color': 'rgba(34, 211, 238, 0.35)',
              'text-halo-color': '#000',
              'text-halo-width': 1,
            }}
          />
        </Source>
    </>
  );
}
