import { Layer, Source } from 'react-map-gl/maplibre';
import { EMPTY_FC } from '@/components/map/mapConstants';

export function GpsJammingLayers() {
  return (
    <Source id="gps-jamming" type="geojson" data={EMPTY_FC}>
      <Layer
        id="gps-jamming-fill"
        type="fill"
        paint={{
          'fill-color': '#ff0040',
          'fill-opacity': ['get', 'opacity'],
        }}
      />
      <Layer
        id="gps-jamming-outline"
        type="line"
        paint={{
          'line-color': '#ff0040',
          'line-width': 1.5,
          'line-opacity': 0.6,
        }}
      />
      <Layer
        id="gps-jamming-label"
        type="symbol"
        layout={{
          'text-font': ['Noto Sans Bold'],
          'text-field': ['concat', 'GPS JAM ', ['to-string', ['round', ['*', 100, ['get', 'ratio']]]], '%'],
          'text-size': ['interpolate', ['linear'], ['zoom'], 2, 8, 5, 10, 8, 12],
          'text-allow-overlap': false,
          'text-ignore-placement': false,
        }}
        paint={{
          'text-color': '#ff4060',
          'text-halo-color': '#000000',
          'text-halo-width': 1.5,
        }}
      />
    </Source>
  );
}
