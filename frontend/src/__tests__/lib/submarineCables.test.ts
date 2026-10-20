import { sanitizeSubmarineCables } from '@/lib/submarineCables';

describe('sanitizeSubmarineCables', () => {
  it('removes synthetic corridor overlays', () => {
    const out = sanitizeSubmarineCables({
      type: 'FeatureCollection',
      features: [
        {
          type: 'Feature',
          properties: { name: 'SEA-ME-WE Corridor' },
          geometry: {
            type: 'LineString',
            coordinates: [
              [-5, 51],
              [73, 17],
            ],
          },
        },
        {
          type: 'Feature',
          properties: { name: 'FEA' },
          geometry: {
            type: 'LineString',
            coordinates: [
              [32, 30],
              [33, 29],
            ],
          },
        },
      ],
    });
    expect(out.features).toHaveLength(1);
    expect(out.features[0].properties?.name).toBe('FEA');
  });

  it('splits trans-ocean jumps into separate segments', () => {
    const out = sanitizeSubmarineCables({
      type: 'FeatureCollection',
      features: [
        {
          type: 'Feature',
          properties: { name: 'Test Pacific' },
          geometry: {
            type: 'LineString',
            coordinates: [
              [-120, 35],
              [-125, 36],
              [100, 13],
              [101, 12],
            ],
          },
        },
      ],
    });
    const geom = out.features[0].geometry;
    expect(geom?.type).toBe('MultiLineString');
    if (geom?.type === 'MultiLineString') {
      expect(geom.coordinates).toHaveLength(2);
    }
  });
});
