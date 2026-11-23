import { Layer, Source } from 'react-map-gl/maplibre';
import { EMPTY_FC } from '@/components/map/mapConstants';

export function PredictivePathLayers() {
  return (
    <>
        <Source id="predictive-path" type="geojson" data={EMPTY_FC}>
          <Layer
            id="predictive-path-layer"
            type="line"
            filter={['==', ['get', 'type'], 'predictive-line']}
            paint={{
              'line-color': '#22d3ee',
              'line-width': 1.5,
              'line-opacity': 0.4,
              'line-dasharray': [4, 4],
            }}
          />
          <Layer
            id="predictive-endpoint"
            type="circle"
            filter={['==', ['get', 'type'], 'predictive-endpoint']}
            paint={{
              'circle-radius': 4,
              'circle-color': 'transparent',
              'circle-stroke-width': 1.5,
              'circle-stroke-color': '#22d3ee',
              'circle-stroke-opacity': 0.4,
              'circle-opacity': 0,
            }}
          />
        </Source>
    </>
  );
}
