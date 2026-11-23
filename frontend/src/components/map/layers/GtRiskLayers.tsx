import { Layer, Source } from 'react-map-gl/maplibre';
import { EMPTY_FC } from '@/components/map/mapConstants';

export function GtRiskLayers() {
  return (
    <Source id="gt-risk-source" type="geojson" data={EMPTY_FC}>
      <Layer
        id="gt-risk-heatmap"
        type="circle"
        minzoom={2}
        paint={{
          'circle-radius': [
            'interpolate',
            ['linear'],
            ['zoom'],
            2,
            ['+', 6, ['*', 14, ['get', 'risk']]],
            6,
            ['+', 10, ['*', 28, ['get', 'risk']]],
            10,
            ['+', 14, ['*', 40, ['get', 'risk']]],
          ],
          'circle-color': [
            'interpolate',
            ['linear'],
            ['get', 'risk'],
            0.15,
            '#22c55e',
            0.35,
            '#84cc16',
            0.5,
            '#eab308',
            0.65,
            '#f97316',
            0.8,
            '#ef4444',
          ],
          'circle-opacity': [
            'interpolate',
            ['linear'],
            ['get', 'risk'],
            0.15,
            0.22,
            0.8,
            0.72,
          ],
          'circle-stroke-width': 1,
          'circle-stroke-color': '#fbbf24',
          'circle-stroke-opacity': 0.35,
        }}
      />
    </Source>
  );
}
