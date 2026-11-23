import { Layer, Source } from 'react-map-gl/maplibre';
import { EMPTY_FC } from '@/components/map/mapConstants';

export function FlightTrailLayers() {
  return (
    <>
        <Source id="flight-trail" type="geojson" data={EMPTY_FC}>
          <Layer
            id="flight-trail-layer"
            type="line"
            paint={{
              'line-color': ['get', 'color'],
              'line-width': 3,
              'line-opacity': ['coalesce', ['get', 'opacity'], 0.7],
            }}
            layout={{
              'line-cap': 'round',
              'line-join': 'round',
            }}
          />
        </Source>
    </>
  );
}
