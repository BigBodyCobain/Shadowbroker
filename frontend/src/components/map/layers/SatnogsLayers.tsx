// @ts-nocheck
import { Layer, Source } from 'react-map-gl/maplibre';
import { EMPTY_FC } from '@/components/map/mapConstants';

export function SatnogsLayers() {
  return (
        <Source
          id="satnogs"
          type="geojson"
          data={EMPTY_FC}
          cluster={true}
          clusterRadius={50}
          clusterMaxZoom={14}
        >
          <Layer
            id="satnogs-cluster-pulse"
            type="circle"
            filter={['has', 'point_count']}
            paint={{
              'circle-radius': ['step', ['get', 'point_count'], 20, 10, 26, 50, 32, 200, 40],
              'circle-color': 'rgba(20, 184, 166, 0.08)',
              'circle-stroke-width': 1.5,
              'circle-stroke-color': 'rgba(20, 184, 166, 0.35)',
              'circle-blur': 0.4 }}
          />
          <Layer
            id="satnogs-clusters"
            type="symbol"
            filter={['has', 'point_count']}
            layout={{
              'icon-image': 'svgSatDish',
              'icon-size': 0.9,
              'icon-allow-overlap': true,
              'text-field': '{point_count_abbreviated}',
              'text-size': 10,
              'text-offset': [0, 1.4],
              'text-allow-overlap': true,
              'text-font': ['Noto Sans Bold'] }}
            paint={{
              'text-color': '#14b8a6',
              'text-halo-color': '#000000',
              'text-halo-width': 1.5 }}
          />
          <Layer
            id="satnogs-pulse"
            type="circle"
            filter={['!', ['has', 'point_count']]}
            paint={{
              'circle-radius': ['interpolate', ['linear'], ['zoom'], 2, 6, 8, 10, 14, 14],
              'circle-color': 'rgba(20, 184, 166, 0.06)',
              'circle-stroke-width': 1,
              'circle-stroke-color': 'rgba(20, 184, 166, 0.3)',
              'circle-blur': 0.5 }}
          />
          <Layer
            id="satnogs-layer"
            type="symbol"
            filter={['!', ['has', 'point_count']]}
            layout={{
              'icon-image': 'svgSatDish',
              'icon-size': ['interpolate', ['linear'], ['zoom'], 2, 0.5, 8, 0.8, 14, 1.0],
              'icon-allow-overlap': true }}
          />
        </Source>
  );
}
