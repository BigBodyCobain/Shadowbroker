// @ts-nocheck
import { Layer, Source } from 'react-map-gl/maplibre';
import { EMPTY_FC } from '@/components/map/mapConstants';

export function PowerPlantsLayers() {
  return (
            <Source id="power-plants" type="geojson" data={EMPTY_FC} cluster={true} clusterRadius={30} clusterMaxZoom={8}>
                {/* Cluster circles */}
                <Layer
                    id="power-plants-clusters"
                    type="circle"
                    minzoom={4}
                    filter={['has', 'point_count']}
                    paint={{
                        'circle-color': '#92400e',
                        'circle-radius': ['step', ['get', 'point_count'], 12, 10, 16, 50, 20],
                        'circle-opacity': 0.7,
                        'circle-stroke-width': 1,
                        'circle-stroke-color': '#f59e0b' }}
                />
                <Layer
                    id="power-plants-cluster-count"
                    type="symbol"
                    minzoom={4}
                    filter={['has', 'point_count']}
                    layout={{
                        'text-field': '{point_count_abbreviated}',
                        'text-font': ['Noto Sans Bold'],
                        'text-size': 10,
                        'text-allow-overlap': true }}
                    paint={{
                        'text-color': '#fde68a' }}
                />
                {/* Individual power plant icons */}
                <Layer
                    id="power-plants-layer"
                    type="symbol"
                    minzoom={4}
                    filter={['!', ['has', 'point_count']]}
                    layout={{
                        'icon-image': 'power-plant',
                        'icon-size': ['interpolate', ['linear'], ['zoom'], 2, 0.5, 6, 0.7, 10, 1.0],
                        'icon-allow-overlap': true,
                        'text-field': ['step', ['zoom'], '', 6, ['get', 'name']],
                        'text-font': ['Noto Sans Regular'],
                        'text-size': 9,
                        'text-offset': [0, 1.2],
                        'text-anchor': 'top',
                        'text-allow-overlap': false }}
                    paint={{
                        'text-color': '#fbbf24',
                        'text-halo-color': 'rgba(0,0,0,0.9)',
                        'text-halo-width': 1 }}
                />
            </Source>
  );
}
