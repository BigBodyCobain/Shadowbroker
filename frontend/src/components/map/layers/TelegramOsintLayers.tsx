import { Layer, Source } from 'react-map-gl/maplibre';
import { EMPTY_FC } from '@/components/map/mapConstants';

export function TelegramOsintLayers() {
  return (
        <Source id="telegram-osint-source" type="geojson" data={EMPTY_FC}>
          <Layer
            id="telegram-osint-layer"
            type="circle"
            minzoom={2}
            paint={{
              'circle-radius': [
                'interpolate',
                ['linear'],
                ['zoom'],
                4,
                ['case', ['>', ['get', 'post_count'], 1], 14, 11],
                8,
                ['case', ['>', ['get', 'post_count'], 1], 20, 16],
                12,
                ['case', ['>', ['get', 'post_count'], 1], 26, 22],
              ],
              'circle-color': '#ef4444',
              'circle-stroke-width': 1,
              'circle-stroke-color': '#fca5a5',
              // Keep a visible MapLibre fallback while the HTML pins are
              // temporarily suppressed during map interaction.
              'circle-opacity': 0.65,
            }}
          />
        </Source>
  );
}
