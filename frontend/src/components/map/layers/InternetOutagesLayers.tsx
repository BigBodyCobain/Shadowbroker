import { Layer, Source } from 'react-map-gl/maplibre';
import { EMPTY_FC } from '@/components/map/mapConstants';

export function InternetOutagesLayers() {
  return (
        <Source id="internet-outages" type="geojson" data={EMPTY_FC}>
          {/* Outer ring */}
          <Layer
            id="internet-outages-pulse"
            type="circle"
            paint={{
              'circle-radius': [
                'interpolate',
                ['linear'],
                ['get', 'severity'],
                0,
                14,
                50,
                18,
                80,
                22,
              ],
              'circle-color': 'rgba(180, 180, 180, 0.1)',
              'circle-stroke-width': 1.5,
              'circle-stroke-color': 'rgba(180, 180, 180, 0.35)',
            }}
          />
          {/* Inner solid circle — all grey, size conveys severity */}
          <Layer
            id="internet-outages-layer"
            type="circle"
            paint={{
              'circle-radius': [
                'interpolate',
                ['linear'],
                ['get', 'severity'],
                0,
                6,
                50,
                9,
                80,
                12,
              ],
              'circle-color': '#888888',
              'circle-stroke-width': 2,
              'circle-stroke-color': 'rgba(0, 0, 0, 0.6)',
              'circle-opacity': 0.9,
            }}
          />
          {/* Severity % inside circle */}
          <Layer
            id="internet-outages-pct"
            type="symbol"
            layout={{
              'text-field': [
                'case',
                ['>', ['get', 'severity'], 0],
                ['concat', ['to-string', ['get', 'severity']], '%'],
                '!',
              ],
              'text-size': 9,
              'text-font': ['Noto Sans Bold'],
              'text-allow-overlap': true,
              'text-ignore-placement': true,
            }}
            paint={{
              'text-color': '#ffffff',
              'text-halo-color': 'rgba(0,0,0,0.8)',
              'text-halo-width': 1,
            }}
          />
          {/* Region name label below — grey */}
          <Layer
            id="internet-outages-label"
            type="symbol"
            layout={{
              'text-field': ['get', 'region'],
              'text-size': 10,
              'text-font': ['Noto Sans Bold'],
              'text-offset': [0, 1.8],
              'text-anchor': 'top',
              'text-allow-overlap': false,
            }}
            paint={{
              'text-color': '#aaaaaa',
              'text-halo-color': 'rgba(0,0,0,0.9)',
              'text-halo-width': 1.5,
            }}
          />
        </Source>

        {/* Data Center positions */}
        <Source
          id="datacenters"
          type="geojson"
          data={EMPTY_FC}
          cluster={true}
          clusterRadius={30}
          clusterMaxZoom={8}
        >
          {/* Cluster circles */}
          <Layer
            id="datacenters-clusters"
            type="circle"
            filter={['has', 'point_count']}
            paint={{
              'circle-color': '#7c3aed',
              'circle-radius': ['step', ['get', 'point_count'], 12, 10, 16, 50, 20],
              'circle-opacity': 0.7,
              'circle-stroke-width': 1,
              'circle-stroke-color': '#a78bfa',
            }}
          />
          <Layer
            id="datacenters-cluster-count"
            type="symbol"
            filter={['has', 'point_count']}
            layout={{
              'text-field': '{point_count_abbreviated}',
              'text-font': ['Noto Sans Bold'],
              'text-size': 10,
              'text-allow-overlap': true,
            }}
            paint={{
              'text-color': '#e9d5ff',
            }}
          />
          {/* Individual DC icons */}
          <Layer
            id="datacenters-layer"
            type="symbol"
            filter={['!', ['has', 'point_count']]}
            layout={{
              'icon-image': 'datacenter',
              'icon-size': ['interpolate', ['linear'], ['zoom'], 2, 0.5, 6, 0.7, 10, 1.0],
              'icon-allow-overlap': true,
              'text-field': ['step', ['zoom'], '', 6, ['get', 'name']],
              'text-font': ['Noto Sans Regular'],
              'text-size': 9,
              'text-offset': [0, 1.2],
              'text-anchor': 'top',
              'text-allow-overlap': false,
            }}
            paint={{
              'text-color': '#c4b5fd',
              'text-halo-color': 'rgba(0,0,0,0.9)',
              'text-halo-width': 1,
            }}
          />
        </Source>
  );
}
