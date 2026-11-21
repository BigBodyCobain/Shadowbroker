import { Layer, Source } from 'react-map-gl/maplibre';
import { EMPTY_FC } from '@/components/map/mapConstants';

export function LiveuamapLayers() {
  return (
        <Source id="liveuamap" type="geojson" data={EMPTY_FC}>
          <Layer
            id="liveuamap-layer"
            type="symbol"
            minzoom={4}
            layout={{
              'icon-image': ['get', 'iconId'],
              'icon-size': 0.8,
              'icon-allow-overlap': true,
            }}
          />
        </Source>
  );
}
