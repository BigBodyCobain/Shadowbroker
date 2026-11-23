import { Layer, Source } from 'react-map-gl/maplibre';
import { EMPTY_FC } from '@/components/map/mapConstants';

export function CrowdThreatLayers() {
  return (
        <Source id="crowdthreat-source" type="geojson" data={EMPTY_FC} cluster={true} clusterMaxZoom={8} clusterRadius={40}>
          <Layer
            id="crowdthreat-clusters"
            type="circle"
            filter={['has', 'point_count']}
            paint={{
              'circle-radius': ['step', ['get', 'point_count'], 14, 10, 18, 50, 24],
              'circle-color': 'rgba(239, 68, 68, 0.7)',
              'circle-stroke-width': 2,
              'circle-stroke-color': '#ef4444' }}
          />
          <Layer
            id="crowdthreat-cluster-count"
            type="symbol"
            filter={['has', 'point_count']}
            layout={{
              'text-field': '{point_count_abbreviated}',
              'text-font': ['Noto Sans Bold'],
              'text-size': 12 }}
            paint={{
              'text-color': '#ffffff' }}
          />
          <Layer
            id="crowdthreat-layer"
            type="symbol"
            filter={['!', ['has', 'point_count']]}
            layout={{
              'icon-image': ['get', 'iconId'],
              'icon-size': ['interpolate', ['linear'], ['zoom'], 2, 0.6, 6, 0.8, 10, 1.0],
              'icon-allow-overlap': true }}
          />
          <Layer
            id="crowdthreat-label"
            type="symbol"
            filter={['!', ['has', 'point_count']]}
            layout={{
              'text-field': ['step', ['zoom'], '', 8, ['get', 'threat_type']],
              'text-font': ['Noto Sans Bold'],
              'text-size': 9,
              'text-offset': [0, 1.6],
              'text-anchor': 'top',
              'text-allow-overlap': false }}
            paint={{
              'text-color': '#fca5a5',
              'text-halo-color': 'rgba(0,0,0,0.9)',
              'text-halo-width': 1 }}
          />
        </Source>
  );
}
