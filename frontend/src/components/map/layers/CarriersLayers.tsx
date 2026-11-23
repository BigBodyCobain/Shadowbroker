import { Layer, Source } from 'react-map-gl/maplibre';
import { EMPTY_FC } from '@/components/map/mapConstants';

export function CarriersLayers({ opacityFilter }: { opacityFilter: any }) {
  return (
        <Source id="carriers" type="geojson" data={EMPTY_FC}>
          <Layer
            id="carriers-layer"
            type="symbol"
            layout={{
              'icon-image': 'svgCarrier',
              'icon-size': 0.8,
              'icon-allow-overlap': true,
              'icon-rotate': ['get', 'rotation'],
              'icon-rotation-alignment': 'map',
            }}
            paint={{ 'icon-opacity': opacityFilter }}
          />
        </Source>
  );
}
