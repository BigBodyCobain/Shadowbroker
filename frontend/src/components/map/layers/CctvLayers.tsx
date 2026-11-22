import { Layer, Source } from 'react-map-gl/maplibre';
import { EMPTY_FC } from '@/components/map/mapConstants';

export function CctvLayers() {
  return (
        <Source
          id="cctv"
          type="geojson"
          data={EMPTY_FC}
          cluster={true}
          clusterRadius={50}
          clusterMaxZoom={14}
        >
          {/* Cluster circles — white, sized by count */}
          <Layer
            id="cctv-clusters"
            type="circle"
            filter={['has', 'point_count']}
            paint={{
              'circle-color': '#ffffff',
              'circle-radius': ['step', ['get', 'point_count'], 14, 10, 18, 50, 24, 200, 30],
              'circle-opacity': 0.8,
              'circle-stroke-width': 2,
              'circle-stroke-color': '#a0a0a0' }}
          />
          {/* Cluster count labels */}
          <Layer
            id="cctv-cluster-count"
            type="symbol"
            filter={['has', 'point_count']}
            layout={{
              'text-font': ['Noto Sans Bold'],
              'text-field': '{point_count_abbreviated}',
              'text-size': 12,
              'text-allow-overlap': true }}
            paint={{
              'text-color': '#000000',
              'text-halo-color': '#ffffff',
              'text-halo-width': 1 }}
          />
          {/* Individual camera dots */}
          <Layer
            id="cctv-layer"
            type="circle"
            filter={['!', ['has', 'point_count']]}
            paint={{
              'circle-color': '#ffffff',
              'circle-radius': ['interpolate', ['linear'], ['zoom'], 2, 2, 8, 4, 14, 6],
              'circle-opacity': 0.9,
              'circle-stroke-width': 1,
              'circle-stroke-color': '#a0a0a0' }}
          />
        </Source>
  );
}
