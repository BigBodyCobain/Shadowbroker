// @ts-nocheck
import { Layer, Source } from 'react-map-gl/maplibre';
import { EMPTY_FC } from '@/components/map/mapConstants';

export function PskReporterLayers() {
  return (
        <Source
          id="psk-reporter"
          type="geojson"
          data={EMPTY_FC}
          cluster={true}
          clusterRadius={50}
          clusterMaxZoom={14}
        >
          {/* Pulse ring behind clusters */}
          <Layer
            id="psk-reporter-cluster-pulse"
            type="circle"
            filter={['has', 'point_count']}
            minzoom={4}
            paint={{
              'circle-radius': ['step', ['get', 'point_count'], 20, 10, 26, 50, 32, 200, 40],
              'circle-color': 'rgba(34, 197, 94, 0.08)',
              'circle-stroke-width': 1.5,
              'circle-stroke-color': 'rgba(34, 197, 94, 0.35)',
              'circle-blur': 0.4 }}
          />
          {/* Clusters — count */}
          <Layer
            id="psk-reporter-clusters"
            type="circle"
            filter={['has', 'point_count']}
            minzoom={4}
            paint={{
              'circle-radius': ['step', ['get', 'point_count'], 12, 10, 16, 50, 20, 200, 26],
              'circle-color': 'rgba(34, 197, 94, 0.6)',
              'circle-stroke-width': 1.5,
              'circle-stroke-color': 'rgba(34, 197, 94, 0.9)' }}
          />
          <Layer
            id="psk-reporter-cluster-count"
            type="symbol"
            filter={['has', 'point_count']}
            minzoom={4}
            layout={{
              'text-field': '{point_count_abbreviated}',
              'text-size': 10,
              'text-allow-overlap': true,
              'text-font': ['Noto Sans Bold'] }}
            paint={{
              'text-color': '#ffffff',
              'text-halo-color': '#000000',
              'text-halo-width': 1 }}
          />
          {/* Individual spots — small green dots */}
          <Layer
            id="psk-reporter-pulse"
            type="circle"
            filter={['!', ['has', 'point_count']]}
            minzoom={4}
            paint={{
              'circle-radius': ['interpolate', ['linear'], ['zoom'], 2, 4, 8, 6, 14, 8],
              'circle-color': 'rgba(34, 197, 94, 0.06)',
              'circle-stroke-width': 1,
              'circle-stroke-color': 'rgba(34, 197, 94, 0.3)',
              'circle-blur': 0.5 }}
          />
          <Layer
            id="psk-reporter-layer"
            type="circle"
            filter={['!', ['has', 'point_count']]}
            minzoom={4}
            paint={{
              'circle-radius': ['interpolate', ['linear'], ['zoom'], 2, 2.5, 8, 4, 14, 6],
              'circle-color': '#22c55e',
              'circle-stroke-width': 0.5,
              'circle-stroke-color': 'rgba(34, 197, 94, 0.8)' }}
          />
        </Source>
  );
}
