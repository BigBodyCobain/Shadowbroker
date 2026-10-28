import { describe, expect, it } from 'vitest';
import { applyDynamicLayerInterp } from '@/components/map/applyDynamicLayerInterp';
import type { DynamicMapLayersResult } from '@/components/map/dynamicMapLayers.worker';
import { MAX_INTERP_SECONDS } from '@/lib/constants';

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

  it('caps dead-reckoning when data is stale (tab hidden overnight)', () => {
    const layer = (): DynamicMapLayersResult => ({
      commercialFlightsGeoJSON: pointLayer(
        { kind: 'flight', baseLat: 40, baseLng: -74, spd: 500, hdg: 90, alt: 35000 },
        [-74, 40],
      ),
      privateFlightsGeoJSON: null,
      privateJetsGeoJSON: null,
      militaryFlightsGeoJSON: null,
      trackedFlightsGeoJSON: null,
      shipsGeoJSON: null,
      meshtasticGeoJSON: null,
      aprsGeoJSON: null,
    });
    const lngAt = (dt: number) => {
      const g = applyDynamicLayerInterp(layer(), dt).commercialFlightsGeoJSON?.features[0].geometry;
      return g && g.type === 'Point' ? g.coordinates[0] : NaN;
    };
    const eightHours = lngAt(8 * 3600);
    // Same position as at the cap: no further drift however stale the data is.
    expect(eightHours).toBeCloseTo(lngAt(MAX_INTERP_SECONDS), 9);
    // 500 kt for 180 s ≈ 25 nm ≈ 0.54° of longitude at 40°N — not thousands of miles.
    expect(eightHours - -74).toBeGreaterThan(0.3);
    expect(eightHours - -74).toBeLessThan(0.7);
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
