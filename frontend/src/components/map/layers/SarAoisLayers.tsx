import { Layer, Source } from 'react-map-gl/maplibre';
import { EMPTY_FC } from '@/components/map/mapConstants';

export function SarAoisLayers() {
  return (
          <Source id="sar-aois" type="geojson" data={EMPTY_FC}>
            <Layer
              id="sar-aois-fill"
              type="fill"
              paint={{
                'fill-color': [
                  'match',
                  ['get', 'category'],
                  'conflict', '#ef4444',
                  'geohazard', '#f97316',
                  'infrastructure', '#06b6d4',
                  'geopolitical', '#a855f7',
                  '#eab308',
                ],
                'fill-opacity': 0.08,
              }}
            />
            <Layer
              id="sar-aois-outline"
              type="line"
              paint={{
                'line-color': [
                  'match',
                  ['get', 'category'],
                  'conflict', '#ef4444',
                  'geohazard', '#f97316',
                  'infrastructure', '#06b6d4',
                  'geopolitical', '#a855f7',
                  '#eab308',
                ],
                'line-width': 1.2,
                'line-opacity': 0.55,
                'line-dasharray': [2, 2],
              }}
            />
            <Layer
              id="sar-aois-label"
              type="symbol"
              minzoom={4}
              layout={{
                'text-field': ['get', 'name'],
                'text-font': ['Noto Sans Regular'],
                'text-size': 10,
                'text-offset': [0, 0.5],
                'text-anchor': 'top',
                'text-allow-overlap': false,
              }}
              paint={{
                'text-color': '#fde68a',
                'text-halo-color': 'rgba(0,0,0,0.9)',
                'text-halo-width': 1,
              }}
            />
          </Source>
        )}
  );
}
