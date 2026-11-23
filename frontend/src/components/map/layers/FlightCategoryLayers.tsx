import { Layer, Source } from 'react-map-gl/maplibre';
import { EMPTY_FC } from '@/components/map/mapConstants';

const CATEGORIES = ['commercial-flights', 'private-flights', 'private-jets', 'military-flights'] as const;

export function FlightCategoryLayers({ opacityFilter }: { opacityFilter: any }) {
  return (
    <>
      {CATEGORIES.map((id) => (
        <Source key={id} id={id} type="geojson" data={EMPTY_FC}>
          <Layer
            id={`${id}-layer`}
            type="symbol"
            layout={{
              'icon-image': ['get', 'iconId'],
              'icon-size': ['interpolate', ['linear'], ['zoom'], 5, 0.8, 8, 1.0, 12, 2.0],
              'icon-allow-overlap': true,
              'icon-rotate': ['get', 'rotation'],
              'icon-rotation-alignment': 'map',
            }}
            paint={{ 'icon-opacity': opacityFilter }}
          />
        </Source>
      ))}
    </>
  );
}
