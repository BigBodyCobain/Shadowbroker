import { describe, it, expect } from 'vitest';
import { computeNightPolygon } from '@/utils/solarTerminator';

/** Extract polygon ring from result (type-narrowing helper) */
function getRing(result: GeoJSON.FeatureCollection): number[][] {
  const geom = result.features[0].geometry;
  if (geom.type !== 'Polygon') throw new Error('Expected Polygon geometry');
  return geom.coordinates[0];
}

describe('computeNightPolygon', () => {
  // ─── Structure validation ────────────────────────────────────────────────

  it('returns a valid GeoJSON FeatureCollection', () => {
    const result = computeNightPolygon();
    expect(result.type).toBe('FeatureCollection');
    expect(result.features).toHaveLength(1);
    expect(result.features[0].type).toBe('Feature');
    expect(result.features[0].geometry.type).toBe('Polygon');
  });

  it('polygon has at least 360 vertices (one per degree of longitude)', () => {
    const ring = getRing(computeNightPolygon());
    // 361 terminator points + 2 closing corners + 1 ring-close = ≥364
    expect(ring.length).toBeGreaterThanOrEqual(364);
  });

  it('polygon ring is closed (first and last points match)', () => {
    const ring = getRing(computeNightPolygon());
    expect(ring[ring.length - 1]).toEqual(ring[0]);
  });

  // ─── Coordinate bounds ───────────────────────────────────────────────────

  it('all coordinates are within valid lat/lng bounds', () => {
    const ring = getRing(computeNightPolygon());
    for (const [lng, lat] of ring) {
      expect(lng).toBeGreaterThanOrEqual(-180);
      expect(lng).toBeLessThanOrEqual(180);
      expect(lat).toBeGreaterThanOrEqual(-85);
      expect(lat).toBeLessThanOrEqual(85);
    }
  });

  // ─── Deterministic for same input ────────────────────────────────────────

  it('returns identical result for the same date', () => {
    const date = new Date('2024-06-21T12:00:00Z');
    const result1 = computeNightPolygon(date);
    const result2 = computeNightPolygon(date);
    expect(result1).toEqual(result2);
  });

  // ─── Seasonal behavior ──────────────────────────────────────────────────

  it('equinox produces roughly symmetric polygon', () => {
    const equinox = new Date('2024-03-20T12:00:00Z');
    const ring = getRing(computeNightPolygon(equinox));
    const lats = ring.map(([, lat]: number[]) => lat);
    const maxLat = Math.max(...lats);
    const minLat = Math.min(...lats);
    expect(maxLat).toBeGreaterThan(50);
    expect(minLat).toBeLessThan(-50);
  });

  it('summer solstice shifts night polygon southward', () => {
    const summer = new Date('2024-06-21T00:00:00Z');
    const ring = getRing(computeNightPolygon(summer));
    const terminatorLats = ring
      .filter(([lng]: number[]) => lng >= -180 && lng <= 180)
      .slice(0, 361)
      .map(([, lat]: number[]) => lat);
    const avgLat =
      terminatorLats.reduce((a: number, b: number) => a + b, 0) / terminatorLats.length;
    expect(avgLat).toBeLessThan(15);
  });

  // ─── Different times produce different results ──────────────────────────

  it('produces different polygons for different times of day', () => {
    const morning = new Date('2024-06-21T06:00:00Z');
    const evening = new Date('2024-06-21T18:00:00Z');
    const ringM = getRing(computeNightPolygon(morning));
    const ringE = getRing(computeNightPolygon(evening));
    expect(ringM[0]).not.toEqual(ringE[0]);
  });
});
