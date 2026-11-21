import { Layer, Source } from 'react-map-gl/maplibre';
import { EMPTY_FC } from '@/components/map/mapConstants';

export function UavsLayers({ opacityFilter }: { opacityFilter: any }) {
  return (
    <>
        <Source id="uavs" type="geojson" data={EMPTY_FC}>
          <Layer
            id="uav-layer"
            type="symbol"
            layout={{
              'icon-image': ['get', 'iconId'],
              'icon-size': ['interpolate', ['linear'], ['zoom'], 5, 0.8, 8, 1.0, 12, 2.0],
              'icon-allow-overlap': true,
              'icon-rotate': ['get', 'rotation'],
              'icon-rotation-alignment': 'map',
            }}
            paint={{ 'icon-opacity': opacityFilter }}
          />
        </Source>
    </>
  );
}
