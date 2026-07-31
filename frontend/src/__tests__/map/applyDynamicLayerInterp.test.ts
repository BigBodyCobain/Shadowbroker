import { describe, expect, it } from 'vitest';
import { applyDynamicLayerInterp } from '@/components/map/applyDynamicLayerInterp';
import type { DynamicMapLayersResult } from '@/components/map/dynamicMapLayers.worker';

function pointLayer(
  props: Record<string, unknown>,
  coordinates: [number, number],
): GeoJSON.FeatureCollection {
  return {
    type: 'FeatureCollection',
    features: [
      {
        type: 'Feature',
        properties: props,
        geometry: { type: 'Point', coordinates },
      },
    ],
  };
}

describe('applyDynamicLayerInterp', () => {
  it('leaves layers unchanged when dtSeconds is 0', () => {
    const layers: DynamicMapLayersResult = {
      commercialFlightsGeoJSON: pointLayer(
        { kind: 'flight', baseLat: 40, baseLng: -74, spd: 400, hdg: 90, alt: 30000 },
        [-74, 40],
      ),
      privateFlightsGeoJSON: null,
      privateJetsGeoJSON: null,
      militaryFlightsGeoJSON: null,
      trackedFlightsGeoJSON: null,
      shipsGeoJSON: null,
      meshtasticGeoJSON: null,
      aprsGeoJSON: null,
    };
    expect(applyDynamicLayerInterp(layers, 0)).toBe(layers);
  });

  it('dead-reckons flight coordinates between polls', () => {
    const layers: DynamicMapLayersResult = {
      commercialFlightsGeoJSON: pointLayer(
        { kind: 'flight', baseLat: 40, baseLng: -74, spd: 400, hdg: 90, alt: 30000 },
        [-74, 40],
      ),
      privateFlightsGeoJSON: null,
      privateJetsGeoJSON: null,
      militaryFlightsGeoJSON: null,
      trackedFlightsGeoJSON: null,
      shipsGeoJSON: null,
      meshtasticGeoJSON: null,
      aprsGeoJSON: null,
    };
    const next = applyDynamicLayerInterp(layers, 30);
    const coords = next.commercialFlightsGeoJSON?.features[0].geometry;
    expect(coords && coords.type === 'Point' ? coords.coordinates[0] : null).not.toBe(-74);
    expect(coords && coords.type === 'Point' ? coords.coordinates[1] : null).toBeCloseTo(40, 1);
  });

  it('does not move grounded flights', () => {
    const layers: DynamicMapLayersResult = {
      commercialFlightsGeoJSON: pointLayer(
        { kind: 'flight', baseLat: 40, baseLng: -74, spd: 20, hdg: 90, alt: 50 },
        [-74, 40],
      ),
      privateFlightsGeoJSON: null,
      privateJetsGeoJSON: null,
      militaryFlightsGeoJSON: null,
      trackedFlightsGeoJSON: null,
      shipsGeoJSON: null,
      meshtasticGeoJSON: null,
      aprsGeoJSON: null,
    };
    const next = applyDynamicLayerInterp(layers, 30);
    expect(next.commercialFlightsGeoJSON).toBe(layers.commercialFlightsGeoJSON);
  });
});
