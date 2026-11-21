import { Layer, Source } from 'react-map-gl/maplibre';
import { EMPTY_FC } from '@/components/map/mapConstants';

export function TrackedFlightsLayers({ opacityFilter }: { opacityFilter: any }) {
  return (
    <>
        <Source id="tracked-flights" type="geojson" data={EMPTY_FC}>
          {/* Gold halo ring — POTUS aircraft only (Air Force One/Two, Marine One) */}
          <Layer
            id="tracked-flights-halo"
            type="circle"
            filter={[
              'any',
              ['==', ['get', 'iconId'], 'svgPotusPlane'],
              ['==', ['get', 'iconId'], 'svgPotusHeli'],
            ]}
            paint={{
              'circle-radius': ['interpolate', ['linear'], ['zoom'], 5, 18, 8, 22, 12, 40],
              'circle-color': 'transparent',
              'circle-stroke-width': 2,
              'circle-stroke-color': 'gold',
              'circle-stroke-opacity': opacityFilter,
              'circle-opacity': 0,
            }}
          />
          <Layer
            id="tracked-flights-layer"
            type="symbol"
            layout={{
              'icon-image': ['get', 'iconId'],
              'icon-size': [
                'interpolate', ['linear'], ['zoom'],
                5, ['case',
                  ['==', ['get', 'iconId'], 'svgPotusPlane'], 1.3,
                  ['==', ['get', 'iconId'], 'svgPotusHeli'], 1.3,
                  0.8,
                ],
                8, ['case',
                  ['==', ['get', 'iconId'], 'svgPotusPlane'], 1.6,
                  ['==', ['get', 'iconId'], 'svgPotusHeli'], 1.6,
                  1.0,
                ],
                12, ['case',
                  ['==', ['get', 'iconId'], 'svgPotusPlane'], 2.6,
                  ['==', ['get', 'iconId'], 'svgPotusHeli'], 2.6,
                  2.0,
                ],
              ],
              'icon-allow-overlap': true,
              'icon-rotate': ['get', 'rotation'],
              'icon-rotation-alignment': 'map',
            }}
            paint={{ 'icon-opacity': opacityFilter }}
          />
        </Source>
    </>
  );
}
