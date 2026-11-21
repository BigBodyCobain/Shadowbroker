import { Layer, Source } from 'react-map-gl/maplibre';
import { EMPTY_FC } from '@/components/map/mapConstants';

export function ActiveRouteLayers() {
  return (
    <>
        <Source id="active-route" type="geojson" data={EMPTY_FC}>
          <Layer
            id="active-route-layer"
            type="line"
            filter={['in', ['get', 'type'], ['literal', ['route-origin', 'route-dest']]]}
            paint={{
              'line-color': [
                'match',
                ['get', 'type'],
                'route-origin',
                '#38bdf8',
                'route-dest',
                '#fcd34d',
                '#ffffff',
              ],
              'line-width': 2,
              'line-dasharray': [2, 2],
              'line-opacity': 0.8,
            }}
          />
          {/* Airport dots at origin/destination */}
          <Layer
            id="airport-dots"
            type="circle"
            filter={['==', ['get', 'type'], 'airport']}
            paint={{
              'circle-radius': 5,
              'circle-color': [
                'match',
                ['get', 'role'],
                'DEP',
                '#38bdf8',
                'ARR',
                '#fcd34d',
                '#ffffff',
              ],
              'circle-stroke-color': '#000',
              'circle-stroke-width': 1.5,
              'circle-opacity': 0.9,
            }}
          />
          {/* IATA code labels at airports */}
          <Layer
            id="airport-labels"
            type="symbol"
            filter={['==', ['get', 'type'], 'airport']}
            layout={{
              'text-field': ['get', 'code'],
              'text-font': ['Noto Sans Bold'],
              'text-size': 11,
              'text-offset': [0, -1.4],
              'text-anchor': 'bottom',
              'text-allow-overlap': true,
            }}
            paint={{
              'text-color': [
                'match',
                ['get', 'role'],
                'DEP',
                '#38bdf8',
                'ARR',
                '#fcd34d',
                '#ffffff',
              ],
              'text-halo-color': '#000',
              'text-halo-width': 1.5,
            }}
          />
        </Source>
    </>
  );
}
