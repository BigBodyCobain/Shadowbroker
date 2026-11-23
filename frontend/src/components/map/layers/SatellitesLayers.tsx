import { Layer, Source } from 'react-map-gl/maplibre';
import { EMPTY_FC } from '@/components/map/mapConstants';

export function SatellitesLayers() {
  return (
    <>
        <Source id="satellites" type="geojson" data={EMPTY_FC}>
          {/* Golden halo ring — ISS only */}
          <Layer
            id="satellites-iss-halo"
            type="circle"
            filter={['==', ['get', 'isISS'], true]}
            paint={{
              'circle-radius': ['interpolate', ['linear'], ['zoom'], 0, 10, 3, 14, 6, 18, 10, 24],
              'circle-color': 'transparent',
              'circle-stroke-width': 2,
              'circle-stroke-color': '#ffdd00',
              'circle-stroke-opacity': 0.8,
              'circle-opacity': 0,
            }}
          />
          <Layer
            id="satellites-layer"
            type="symbol"
            layout={{
              'icon-image': ['get', 'iconId'],
              'icon-size': ['interpolate', ['linear'], ['zoom'], 0, 0.4, 3, 0.5, 6, 0.7, 10, 1.0],
              'icon-allow-overlap': true,
            }}
          />
        </Source>
    </>
  );
}
