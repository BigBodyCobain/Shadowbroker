import { Layer, Source } from 'react-map-gl/maplibre';
import { EMPTY_FC } from '@/components/map/mapConstants';

export function SarAnomaliesLayers() {
  return (
          <Source id="sar-anomalies" type="geojson" data={EMPTY_FC}>
            <Layer
              id="sar-anomalies-halo"
              type="circle"
              paint={{
                'circle-radius': [
                  'interpolate', ['linear'], ['zoom'],
                  2, 6, 6, 10, 10, 16,
                ],
                'circle-color': ['get', 'color'],
                'circle-opacity': 0.2,
                'circle-blur': 0.6,
              }}
            />
            <Layer
              id="sar-anomalies-layer"
              type="circle"
              paint={{
                'circle-radius': [
                  'interpolate', ['linear'], ['zoom'],
                  2, 3, 6, 5, 10, 8,
                ],
                'circle-color': ['get', 'color'],
                'circle-opacity': 0.9,
                'circle-stroke-width': 1.5,
                'circle-stroke-color': '#000',
              }}
            />
            <Layer
              id="sar-anomalies-label"
              type="symbol"
              minzoom={7}
              layout={{
                'text-field': ['get', 'title'],
                'text-font': ['Noto Sans Regular'],
                'text-size': 10,
                'text-offset': [0, 1.2],
                'text-anchor': 'top',
                'text-allow-overlap': false,
                'text-max-width': 12,
              }}
              paint={{
                'text-color': '#fef3c7',
                'text-halo-color': 'rgba(0,0,0,0.9)',
                'text-halo-width': 1,
              }}
            />
          </Source>
  );
}
