import { Layer, Source } from 'react-map-gl/maplibre';
import { EMPTY_FC } from '@/components/map/mapConstants';

export function FirmsFireLayers() {
  return (
    <Source
      id="firms-fires"
      type="geojson"
      data={EMPTY_FC}
      cluster={true}
      clusterRadius={40}
      clusterMaxZoom={10}
    >
      <Layer
        id="firms-clusters"
        type="symbol"
        filter={['has', 'point_count']}
        layout={{
          'icon-image': [
            'step',
            ['get', 'point_count'],
            'fire-cluster-sm',
            10,
            'fire-cluster-md',
            50,
            'fire-cluster-lg',
            200,
            'fire-cluster-xl',
          ],
          'icon-size': ['step', ['get', 'point_count'], 1.0, 10, 1.1, 50, 1.2, 200, 1.3],
          'icon-allow-overlap': true,
          'icon-ignore-placement': true,
          'text-field': '{point_count_abbreviated}',
          'text-font': ['Noto Sans Bold'],
          'text-size': ['step', ['get', 'point_count'], 9, 10, 10, 50, 11, 200, 12],
          'text-offset': [0, 0.15],
          'text-allow-overlap': true,
        }}
        paint={{
          'text-color': '#ffffff',
          'text-halo-color': 'rgba(0,0,0,0.8)',
          'text-halo-width': 1.2,
        }}
      />
      <Layer
        id="firms-viirs-layer"
        type="symbol"
        filter={['!', ['has', 'point_count']]}
        layout={{
          'icon-image': ['get', 'iconId'],
          'icon-size': ['interpolate', ['linear'], ['zoom'], 2, 0.4, 5, 0.6, 8, 0.8, 12, 1.0],
          'icon-allow-overlap': true,
          'icon-ignore-placement': true,
        }}
      />
    </Source>
  );
}
