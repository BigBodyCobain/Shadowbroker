import { describe, expect, it } from 'vitest';

import {
  buildBoundsQuery,
  coarsenViewBounds,
  expandBoundsToRadius,
} from '@/lib/viewportPrivacy';

describe('viewport privacy helper', () => {
  it('coarsens narrow bounds outward without clipping the original view', () => {
    const original = {
      south: 33.612,
      west: -84.452,
      north: 33.781,
      east: -84.211,
    };

    const coarse = coarsenViewBounds(original);

    expect(coarse.south).toBeLessThanOrEqual(original.south);
    expect(coarse.west).toBeLessThanOrEqual(original.west);
    expect(coarse.north).toBeGreaterThanOrEqual(original.north);
    expect(coarse.east).toBeGreaterThanOrEqual(original.east);
    expect(coarse.south).toBe(33.6);
    expect(coarse.west).toBe(-84.5);
    expect(coarse.north).toBe(33.8);
    expect(coarse.east).toBe(-84.2);
  });

  it('canonicalizes the bounds query so nearby pans in the same coarse cell dedupe', () => {
    const a = buildBoundsQuery({
      south: 47.6011,
      west: -122.3484,
      north: 47.6902,
      east: -122.2012,
    });
    const b = buildBoundsQuery({
      south: 47.6039,
      west: -122.3441,
      north: 47.6883,
      east: -122.2051,
    });

    expect(a).toBe('?s=47.60&w=-122.35&n=47.70&e=-122.20');
    expect(b).toBe(a);
  });

  it('expands bounds to a fixed preload radius around the current view center', () => {
    const original = {
      south: 39.55,
      west: -105.25,
      north: 39.95,
      east: -104.75,
    };

    const expanded = expandBoundsToRadius(original, 3000);

    expect(expanded.south).toBeLessThanOrEqual(original.south);
    expect(expanded.west).toBeLessThanOrEqual(original.west);
    expect(expanded.north).toBeGreaterThanOrEqual(original.north);
    expect(expanded.east).toBeGreaterThanOrEqual(original.east);
    expect(expanded.north - expanded.south).toBeGreaterThan(80);
    expect(expanded.east - expanded.west).toBeGreaterThan(90);
  });
});
