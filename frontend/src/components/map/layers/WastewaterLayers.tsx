import { Layer, Source } from 'react-map-gl/maplibre';
import { EMPTY_FC } from '@/components/map/mapConstants';

export function WastewaterLayers() {
  return (
        <Source id="wastewater-source" type="geojson" data={EMPTY_FC} cluster={true} clusterMaxZoom={10} clusterRadius={35}>
          {/* Cluster glow — faint backdrop behind water drop icon */}
          <Layer
            id="wastewater-cluster-bg"
            type="circle"
            filter={['has', 'point_count']}
            paint={{
              'circle-radius': ['step', ['get', 'point_count'], 12, 10, 14, 50, 18],
              'circle-color': 'rgba(0, 229, 255, 0.10)',
              'circle-stroke-width': 0,
              'circle-stroke-color': 'transparent' }}
          />
          {/* Cluster water drop icon + count */}
          <Layer
            id="wastewater-clusters"
            type="symbol"
            filter={['has', 'point_count']}
            layout={{
              'icon-image': 'ww-cluster',
              'icon-size': ['interpolate', ['linear'], ['zoom'], 0, 1.5, 2, 1.55, 4, 1.57, 6, 1.52, 8, 1.46, 10, 1.4],
              'icon-allow-overlap': true,
              'icon-ignore-placement': true,
              'text-field': '{point_count_abbreviated}',
              'text-font': ['Noto Sans Bold'],
              'text-size': ['interpolate', ['linear'], ['zoom'], 0, 10, 4, 11, 8, 12],
              'text-offset': [0, 0.1],
              'text-allow-overlap': true,
              'text-ignore-placement': true }}
            paint={{
              'icon-opacity': 1,
              'text-color': '#ffffff',
              'text-halo-color': 'rgba(0, 80, 100, 1)',
              'text-halo-width': 2.4 }}
          />
          {/* Individual glow — faint backdrop behind water drop icon */}
          <Layer
            id="wastewater-dot"
            type="circle"
            filter={['!', ['has', 'point_count']]}
            paint={{
              'circle-radius': ['interpolate', ['linear'], ['zoom'], 2, 3, 8, 4, 12, 5, 16, 6],
              'circle-color': ['case', ['>', ['get', 'alert_count'], 0], 'rgba(255, 34, 34, 0.20)', 'rgba(0, 229, 255, 0.20)'],
              'circle-stroke-width': 0.75,
              'circle-stroke-color': ['case', ['>', ['get', 'alert_count'], 0], 'rgba(255, 82, 82, 0.25)', 'rgba(128, 222, 234, 0.25)'] }}
          />
          {/* Individual water drop icon overlay */}
          <Layer
            id="wastewater-layer"
            type="symbol"
            filter={['!', ['has', 'point_count']]}
            layout={{
              'icon-image': ['get', 'icon'],
              'icon-size': ['interpolate', ['linear'], ['zoom'], 1, 0.7, 3, 0.8, 6, 0.95, 10, 1.1, 14, 1.2],
              'icon-allow-overlap': true,
              'icon-ignore-placement': true,
              'text-field': ['step', ['zoom'], '', 7, ['get', 'label']],
              'text-font': ['Noto Sans Bold'],
              'text-size': ['interpolate', ['linear'], ['zoom'], 7, 9, 10, 11],
              'text-offset': [0, 2.0],
              'text-anchor': 'top',
              'text-allow-overlap': false,
              'text-optional': true,
              'text-max-width': 16 }}
            paint={{
              'icon-opacity': 1,
              'text-color': ['case', ['>', ['get', 'alert_count'], 0], '#ff5252', '#80deea'],
              'text-halo-color': 'rgba(0,0,0,0.98)',
              'text-halo-width': 1.25 }}
          />
        </Source>
  );
}
