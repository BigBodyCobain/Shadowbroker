import { Layer, Source } from 'react-map-gl/maplibre';
import { EMPTY_FC } from '@/components/map/mapConstants';

export function ShodanOverlayLayer({ shodanStyle }: { shodanStyle?: any }) {
  const sc = shodanStyle ?? { shape: 'circle' as const, color: '#16a34a', size: 'md' as const };
  const sizeMap = { sm: [3, 4, 5] as const, md: [4, 6, 8] as const, lg: [6, 9, 12] as const };
  const textSizeMap = { sm: 10, md: 14, lg: 20 };
  const shapeGlyphs: Record<string, string> = { triangle: '▲', diamond: '◆', square: '■' };
  const radii = sizeMap[sc.size] ?? sizeMap.md;
  const isCircle = sc.shape === 'circle';
  const labelOffset = isCircle ? 1.1 : (sc.size === 'lg' ? 1.6 : sc.size === 'sm' ? 0.9 : 1.2);
  return (
    <Source
      id="shodan-overlay"
      type="geojson"
      data={EMPTY_FC}
      cluster={true}
      clusterRadius={42}
      clusterMaxZoom={9}
    >
      <Layer
        id="shodan-clusters"
        type="circle"
        filter={['has', 'point_count']}
        paint={{
          'circle-color': sc.color,
          'circle-radius': ['step', ['get', 'point_count'], 14, 10, 18, 50, 22, 200, 26],
          'circle-opacity': 0.8,
          'circle-stroke-width': 1.5,
          'circle-stroke-color': `${sc.color}66`,
        }}
      />
      <Layer
        id="shodan-cluster-count"
        type="symbol"
        filter={['has', 'point_count']}
        layout={{
          'text-field': '{point_count_abbreviated}',
          'text-font': ['Noto Sans Bold'],
          'text-size': 10,
          'text-allow-overlap': true,
        }}
        paint={{ 'text-color': '#ffffff' }}
      />
      <Layer
        id="shodan-points"
        type="circle"
        filter={['!', ['has', 'point_count']]}
        paint={{
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 2, radii[0], 8, radii[1], 14, radii[2]],
          'circle-color': sc.color,
          'circle-opacity': isCircle ? 0.9 : 0.001,
          'circle-stroke-width': isCircle ? 1 : 0,
          'circle-stroke-color': isCircle ? 'rgba(255,255,255,0.55)' : 'transparent',
        }}
      />
      {!isCircle && (
        <Layer
          id="shodan-points-shape"
          type="symbol"
          filter={['!', ['has', 'point_count']]}
          layout={{
            'text-field': shapeGlyphs[sc.shape] ?? '■',
            'text-size': textSizeMap[sc.size] ?? 14,
            'text-allow-overlap': true,
            'text-ignore-placement': true,
            'text-font': ['Noto Sans Bold'],
          }}
          paint={{ 'text-color': sc.color, 'text-opacity': 0.95 }}
        />
      )}
      <Layer
        id="shodan-labels"
        type="symbol"
        filter={['!', ['has', 'point_count']]}
        minzoom={4}
        layout={{
          'text-field': ['get', 'label'],
          'text-size': 11,
          'text-offset': [0, labelOffset],
          'text-anchor': 'top',
          'text-optional': true,
          'text-font': ['Noto Sans Bold'],
        }}
        paint={{ 'text-color': '#d1fae5', 'text-halo-color': '#000000', 'text-halo-width': 1 }}
      />
    </Source>
  );
}
