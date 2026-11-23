import { Layer, Source } from 'react-map-gl/maplibre';
import { EMPTY_FC } from '@/components/map/mapConstants';

export function KiwiSdrLayers() {
  return (
        <Source
          id="kiwisdr"
          type="geojson"
          data={EMPTY_FC}
          cluster={true}
          clusterRadius={50}
          clusterMaxZoom={14}
        >
          {/* Pulse ring behind clusters */}
          <Layer
            id="kiwisdr-cluster-pulse"
            type="circle"
            filter={['has', 'point_count']}
            paint={{
              'circle-radius': ['step', ['get', 'point_count'], 20, 10, 26, 50, 32, 200, 40],
              'circle-color': 'rgba(245, 158, 11, 0.08)',
              'circle-stroke-width': 1.5,
              'circle-stroke-color': 'rgba(245, 158, 11, 0.35)',
              'circle-blur': 0.4 }}
          />
          {/* Clusters — tower icon with count */}
          <Layer
            id="kiwisdr-clusters"
            type="symbol"
            filter={['has', 'point_count']}
            layout={{
              'icon-image': 'svgRadioTower',
              'icon-size': 0.9,
              'icon-allow-overlap': true,
              'text-field': '{point_count_abbreviated}',
              'text-size': 10,
              'text-offset': [0, 1.4],
              'text-allow-overlap': true,
              'text-font': ['Noto Sans Bold'] }}
            paint={{
              'text-color': '#f59e0b',
              'text-halo-color': '#000000',
              'text-halo-width': 1.5 }}
          />
          {/* Pulse ring behind individual towers */}
          <Layer
            id="kiwisdr-pulse"
            type="circle"
            filter={['!', ['has', 'point_count']]}
            paint={{
              'circle-radius': ['interpolate', ['linear'], ['zoom'], 2, 6, 8, 10, 14, 14],
              'circle-color': 'rgba(245, 158, 11, 0.06)',
              'circle-stroke-width': 1,
              'circle-stroke-color': 'rgba(245, 158, 11, 0.3)',
              'circle-blur': 0.5 }}
          />
          {/* Individual tower icons */}
          <Layer
            id="kiwisdr-layer"
            type="symbol"
            filter={['!', ['has', 'point_count']]}
            layout={{
              'icon-image': 'svgRadioTower',
              'icon-size': ['interpolate', ['linear'], ['zoom'], 2, 0.5, 8, 0.8, 14, 1.0],
              'icon-allow-overlap': true }}
          />
        </Source>
  );
}
