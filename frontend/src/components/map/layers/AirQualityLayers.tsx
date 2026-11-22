// @ts-nocheck
import { Layer, Source } from 'react-map-gl/maplibre';
import { EMPTY_FC } from '@/components/map/mapConstants';

export function AirQualityLayers() {
  return (
    <Source id="air-quality-source" type="geojson" data={EMPTY_FC} cluster={true} clusterMaxZoom={8} clusterRadius={40}>
      <Layer id="air-quality-clusters" type="circle" filter={['has', 'point_count']} paint={{ 'circle-radius': ['step', ['get', 'point_count'], 12, 10, 16, 50, 20], 'circle-color': '#94a3b8', 'circle-opacity': 0.6 }} />
      <Layer id="air-quality-layer" type="circle" filter={['!', ['has', 'point_count']]} paint={{ 'circle-radius': ['interpolate', ['linear'], ['zoom'], 2, 3, 6, 5, 10, 8], 'circle-color': ['get', 'color'], 'circle-opacity': 0.75, 'circle-stroke-width': 1, 'circle-stroke-color': '#000' }} />
    </Source>
  );
}
