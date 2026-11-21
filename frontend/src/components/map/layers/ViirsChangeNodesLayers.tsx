import { Layer, Source } from 'react-map-gl/maplibre';
import { EMPTY_FC } from '@/components/map/mapConstants';

export function ViirsChangeNodesLayers() {
  return (
            <Source id="viirs-change-nodes" type="geojson" data={EMPTY_FC}>
                <Layer
                    id="viirs-change-nodes-layer"
                    type="circle"
                    paint={{
                        'circle-radius': ['interpolate', ['linear'], ['zoom'], 2, 4, 6, 8, 10, 12],
                        'circle-color': ['get', 'color'],
                        'circle-opacity': 0.85,
                        'circle-stroke-width': 1,
                        'circle-stroke-color': 'rgba(255,255,255,0.4)',
                    }}
                />
            </Source>
        )}
  );
}
