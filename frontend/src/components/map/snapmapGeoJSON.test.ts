import { describe, expect, it } from 'vitest';
import { buildSnapmapOsintGeoJSON, SNAPMAP_LEVEL_COLORS } from '@/components/map/geoJSONBuilders';

describe('buildSnapmapOsintGeoJSON', () => {
  it('returns null without zones', () => {
    expect(buildSnapmapOsintGeoJSON(null)).toBeNull();
    expect(buildSnapmapOsintGeoJSON({ zones: [] })).toBeNull();
  });

  it('emits a footprint polygon and a centre point per zone with level colour and A/B/C tag', () => {
    const fc = buildSnapmapOsintGeoJSON({
      zones: [
        { id: 'gva', label: 'Genève', lat: 46.2, lng: 6.14, radius_m: 2000, count_1h: 25, level: 'critical', reliability: 'B' },
        { id: 'bad', label: 'Bad', lat: Number.NaN, lng: 6, radius_m: 1000 },
      ],
    });
    expect(fc?.features).toHaveLength(2);
    const [zone, centre] = fc!.features;
    expect(zone.geometry.type).toBe('Polygon');
    expect(centre.geometry.type).toBe('Point');
    expect(centre.properties?.color).toBe(SNAPMAP_LEVEL_COLORS.critical);
    expect(centre.properties?.tag).toBe('B · 25/h');
    // ring radius ≈ 2 km in latitude
    const ring = (zone.geometry as GeoJSON.Polygon).coordinates[0];
    const maxLat = Math.max(...ring.map((c) => c[1]));
    expect(maxLat - 46.2).toBeCloseTo(2000 / 111_320, 4);
  });
});
