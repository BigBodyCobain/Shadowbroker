import { Layer, Source } from 'react-map-gl/maplibre';
import { EMPTY_FC } from '@/components/map/mapConstants';

export function DayNightLayers({ theme }: { theme: 'light' | 'dark' | string }) {
  return (
    <>
      <Source id="night-overlay" type="geojson" data={EMPTY_FC}>
        <Layer
          id="night-overlay-layer"
          type="fill"
          paint={{
            'fill-color': theme === 'light' ? '#1d3a66' : '#0a0e1a',
            'fill-opacity': theme === 'light' ? 0.08 : 0.35,
            'fill-antialias': true,
          }}
        />
      </Source>
      <Source id="night-twilight" type="geojson" data={EMPTY_FC}>
        <Layer
          id="night-twilight-layer"
          type="line"
          paint={{
            'line-color': theme === 'light' ? '#1d3a66' : '#0a0e1a',
            'line-width': ['interpolate', ['linear'], ['zoom'], 1, 180, 4, 320, 7, 460],
            'line-blur': ['interpolate', ['linear'], ['zoom'], 1, 180, 4, 320, 7, 460],
            'line-opacity': theme === 'light' ? 0.08 : 0.34,
          }}
        />
      </Source>
    </>
  );
}
