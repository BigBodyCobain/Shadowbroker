import { Layer, Source } from 'react-map-gl/maplibre';
import { EMPTY_FC } from '@/components/map/mapConstants';

export function TinyGSLayers() {
  return (
    <>
      <Source id="tinygs" type="geojson" data={EMPTY_FC}>
          <Layer
            id="tinygs-layer"
            type="symbol"
            layout={{
              'icon-image': 'svgLoRaSat',
              'icon-size': 0.8,
              'icon-allow-overlap': true,
              'text-field': ['get', 'name'],
              'text-font': ['Noto Sans Regular'],
              'text-size': 10,
              'text-offset': [0, 1.4],
              'text-optional': true }}
            paint={{
              'text-color': '#c084fc',
              'text-halo-color': '#000000',
              'text-halo-width': 1.5 }}
          />
        </Source>

        {/* Police Scanners (OpenMHZ) — red scanner icons with clusters */}
        <Source
          id="scanners"
          type="geojson"
          data={EMPTY_FC}
          cluster={true}
          clusterRadius={50}
          clusterMaxZoom={14}
        >
          {/* Pulse ring behind clusters */}
          <Layer
            id="scanner-cluster-pulse"
            type="circle"
            filter={['has', 'point_count']}
            paint={{
              'circle-radius': ['step', ['get', 'point_count'], 20, 10, 26, 50, 32, 200, 40],
              'circle-color': 'rgba(220, 38, 38, 0.08)',
              'circle-stroke-width': 1.5,
              'circle-stroke-color': 'rgba(220, 38, 38, 0.35)',
              'circle-blur': 0.4 }}
          />
          {/* Cluster icons + count */}
          <Layer
            id="scanner-clusters"
            type="symbol"
            filter={['has', 'point_count']}
            layout={{
              'icon-image': 'svgScannerTower',
              'icon-size': 0.9,
              'icon-allow-overlap': true,
              'text-field': '{point_count_abbreviated}',
              'text-size': 10,
              'text-offset': [0, 1.4],
              'text-allow-overlap': true,
              'text-font': ['Noto Sans Bold'] }}
            paint={{
              'text-color': '#dc2626',
              'text-halo-color': '#000000',
              'text-halo-width': 1.5 }}
          />
          {/* Pulse ring behind individual scanners */}
          <Layer
            id="scanner-pulse"
            type="circle"
            filter={['!', ['has', 'point_count']]}
            paint={{
              'circle-radius': ['interpolate', ['linear'], ['zoom'], 2, 6, 8, 10, 14, 14],
              'circle-color': 'rgba(220, 38, 38, 0.06)',
              'circle-stroke-width': 1,
              'circle-stroke-color': 'rgba(220, 38, 38, 0.3)',
              'circle-blur': 0.5 }}
          />
          {/* Individual scanner icons */}
          <Layer
            id="scanner-layer"
            type="symbol"
            filter={['!', ['has', 'point_count']]}
            layout={{
              'icon-image': 'svgScannerTower',
              'icon-size': ['interpolate', ['linear'], ['zoom'], 2, 0.5, 8, 0.8, 14, 1.0],
              'icon-allow-overlap': true }}
          />
      </Source>
    </>
  );
}
