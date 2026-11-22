// @ts-nocheck
import { Layer, Source } from 'react-map-gl/maplibre';
import { EMPTY_FC } from '@/components/map/mapConstants';
import { GpsJammingLayers } from './GpsJammingLayers';
import { GtRiskLayers } from './GtRiskLayers';
import { CorrelationLayers } from './CorrelationLayers';

export function EarthquakesLayers() {
  return (
    <>
      <Source
        id="earthquakes"
        type="geojson"
        data={EMPTY_FC}
        cluster={true}
        clusterMaxZoom={10}
        clusterRadius={60}
      >
        {/* Earthquake cluster circles */}
        <Layer
          id="eq-clusters-layer"
          type="circle"
          filter={['has', 'point_count']}
          paint={{
            'circle-color': 'rgba(255, 170, 0, 0.85)',
            'circle-radius': ['step', ['get', 'point_count'], 12, 5, 16, 10, 20, 20, 24],
            'circle-stroke-width': 2,
            'circle-stroke-color': 'rgba(255, 200, 0, 1.0)' }}
        />
        {/* Individual (unclustered) earthquake icons */}
        <Layer
          id="earthquakes-layer"
          type="symbol"
          filter={['!', ['has', 'point_count']]}
          layout={{
            'icon-image': 'icon-threat',
            'icon-size': 0.5,
            'icon-allow-overlap': true }}
          paint={{ 'icon-opacity': 1.0 }}
        />
      </Source>

      {/* GPS Jamming Zones — red translucent grid squares */}
      <GpsJammingLayers />

      {/* Strategic Risk Heatmap — Bayesian posterior scores */}
      <GtRiskLayers />

      <CorrelationLayers />
    </>
  );
}
