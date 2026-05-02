'use client';

import React, { useEffect, useState, useRef } from 'react';
import { Source, Layer, Marker } from 'react-map-gl/maplibre';
import { API_BASE } from '@/lib/api';

interface Props {
  vesselLat: number;
  vesselLng: number;
  destination: string;
}

/**
 * Geocodes a fishing vessel's AIS destination and draws a dashed cyan route line
 * from the vessel to the destination on the map.
 */
export default function FishingDestinationRoute({ vesselLat, vesselLng, destination }: Props) {
  const [destCoords, setDestCoords] = useState<[number, number] | null>(null);
  const [destLabel, setDestLabel] = useState('');
  const prevDest = useRef('');

  useEffect(() => {
    if (!destination) { setDestCoords(null); return; }
    const query = destination.trim();
    if (!query || query === prevDest.current) return;
    prevDest.current = query;

    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${API_BASE}/api/geocode/search?q=${encodeURIComponent(query)}&limit=1`);
        if (!res.ok || cancelled) return;
        const json = await res.json();
        const results = json.results || json;
        if (Array.isArray(results) && results.length > 0 && !cancelled) {
          const r = results[0];
          setDestCoords([r.lng ?? r.lon, r.lat]);
          setDestLabel(r.label || r.display_name || query);
        } else {
          setDestCoords(null);
        }
      } catch {
        setDestCoords(null);
      }
    })();
    return () => { cancelled = true; };
  }, [destination]);

  if (!destCoords) return null;

  const geojson: GeoJSON.FeatureCollection = {
    type: 'FeatureCollection',
    features: [
      {
        type: 'Feature',
        properties: { type: 'fishing-route' },
        geometry: {
          type: 'LineString',
          coordinates: [[vesselLng, vesselLat], destCoords],
        },
      },
      {
        type: 'Feature',
        properties: { type: 'fishing-dest' },
        geometry: {
          type: 'Point',
          coordinates: destCoords,
        },
      },
    ],
  };

  return (
    <>
      <Source id="fishing-dest-route" type="geojson" data={geojson}>
        <Layer
          id="fishing-dest-line"
          type="line"
          filter={['==', ['get', 'type'], 'fishing-route']}
          paint={{
            'line-color': '#0ea5e9',
            'line-width': 2,
            'line-opacity': 0.7,
            'line-dasharray': [6, 4],
          }}
        />
        <Layer
          id="fishing-dest-point"
          type="circle"
          filter={['==', ['get', 'type'], 'fishing-dest']}
          paint={{
            'circle-radius': 6,
            'circle-color': 'rgba(14, 165, 233, 0.3)',
            'circle-stroke-width': 2,
            'circle-stroke-color': '#0ea5e9',
          }}
        />
        <Layer
          id="fishing-dest-label"
          type="symbol"
          filter={['==', ['get', 'type'], 'fishing-dest']}
          layout={{
            'text-field': destLabel,
            'text-font': ['Noto Sans Bold'],
            'text-size': 11,
            'text-offset': [0, 1.4],
            'text-anchor': 'top',
            'text-allow-overlap': true,
          }}
          paint={{
            'text-color': '#0ea5e9',
            'text-halo-color': 'rgba(0,0,0,0.9)',
            'text-halo-width': 1.5,
          }}
        />
      </Source>
    </>
  );
}
