import { describe, it, expect } from 'vitest';
import {
  parseCoordinateInput,
  boundsForCoordinate,
  sanitizeGeocodeBbox,
  boundsForPlaceRank,
  clampZoom,
} from '@/lib/mapZoom';

describe('parseCoordinateInput', () => {
  it('counts decimals as typed, not as parsed', () => {
    // 78.00 and 78 are the same float but not the same claim.
    expect(parseCoordinateInput('78.00, -119.00')?.decimals).toBe(2);
    expect(parseCoordinateInput('78, -119')?.decimals).toBe(0);
  });

  it('takes the less precise axis so one sloppy field cannot drive framing', () => {
    expect(parseCoordinateInput('78.00, -119')?.decimals).toBe(0);
  });

  it('accepts space separation and a trailing dot', () => {
    expect(parseCoordinateInput('34.05 -118.24')?.decimals).toBe(2);
    expect(parseCoordinateInput('78. -119.')?.decimals).toBe(0);
  });

  it('rejects out-of-range and non-coordinate input', () => {
    expect(parseCoordinateInput('91, 0')).toBeNull();
    expect(parseCoordinateInput('0, 181')).toBeNull();
    expect(parseCoordinateInput('Tokyo')).toBeNull();
  });
});

describe('boundsForCoordinate', () => {
  it('brackets the point by half an uncertainty cell', () => {
    const [w, s, e, n] = boundsForCoordinate(78, -119, 0);
    expect(w).toBeCloseTo(-119.5, 6);
    expect(e).toBeCloseTo(-118.5, 6);
    expect(s).toBeCloseTo(77.5, 6);
    expect(n).toBeCloseTo(78.5, 6);
  });

  it('shrinks by 10x per decimal place', () => {
    const [w, , e] = boundsForCoordinate(34.052341, -118.243607, 6);
    expect(e - w).toBeCloseTo(0.000001, 9);
  });

  it('does not produce latitudes beyond the poles', () => {
    const [, s, , n] = boundsForCoordinate(90, 0, 0);
    expect(n).toBeLessThanOrEqual(90);
    expect(s).toBeGreaterThanOrEqual(-90);
  });
});

describe('sanitizeGeocodeBbox', () => {
  it('accepts an honest city-sized box and converts to [w,s,e,n]', () => {
    // Monaco the country, place_rank 4. The box is padded with territorial
    // water and the point sits on its northern edge, but at 26km across the
    // lopsidedness is too small to matter.
    expect(
      sanitizeGeocodeBbox(
        ['43.5165358', '43.7519173', '7.4090279', '7.5329917'],
        43.7323492,
        7.4276832,
      ),
    ).toEqual([7.4090279, 43.5165358, 7.5329917, 43.7519173]);
  });

  it('accepts a town', () => {
    // Zermatt, place_rank 16.
    expect(
      sanitizeGeocodeBbox(
        ['45.9167499', '46.0643293', '7.5749926', '7.9086793'],
        46.0207133,
        7.7491027,
      ),
    ).not.toBeNull();
  });

  it('keeps the honest box of a country far larger than its rank implies', () => {
    // Canada is rank 4, the same rank as Monaco, and 4600km across. Sizing
    // rules keyed off place_rank threw this away and flew to a 1000km box
    // over the Northwest Territories.
    expect(
      sanitizeGeocodeBbox(
        ['41.6765597', '83.3362128', '-141.0027500', '-52.3237664'],
        61.0666922,
        -107.9917071,
      ),
    ).toEqual([-141.00275, 41.6765597, -52.3237664, 83.3362128]);
  });

  it('keeps the honest box of an oversized state', () => {
    // Texas is rank 8 and 1300km wide; the old cap allowed 1000km.
    expect(
      sanitizeGeocodeBbox(
        ['25.8371638', '36.5007041', '-106.6456461', '-93.5078063'],
        31.2638905,
        -98.5456116,
      ),
    ).not.toBeNull();
  });

  it('rebuilds an antimeridian-degraded box from its latitude axis', () => {
    // Russia: Nominatim returns the whole planet in longitude. MapLibre's
    // adjustAntiMeridian() reads that as a legitimate world box, so we must
    // catch it — but the latitude axis survived and still sizes the country.
    const bounds = sanitizeGeocodeBbox(
      ['41.1850968', '82.0586232', '-180.0000000', '180.0000000'],
      64.6863136,
      97.7453061,
    );
    expect(bounds).not.toBeNull();
    const [west, south, east, north] = bounds!;
    // The latitude axis is real data and survives untouched. Re-deriving it
    // from the result's own point pushes north past 85, where Mercator's
    // stretch alone drags the zoom down to the floor.
    expect([south, north]).toEqual([41.1850968, 82.0586232]);
    expect(east - west).toBeLessThan(180);
    expect(west).toBeLessThan(97.7453061);
    expect(east).toBeGreaterThan(97.7453061);
  });

  it('caps a latitude axis that overseas territories also smeared', () => {
    // The United States reaches 14S at American Samoa and 71N at Point
    // Barrow: 9600km of latitude for a 4500km country. Uncapped, the camera
    // frames a hemisphere.
    const [, south, , north] = sanitizeGeocodeBbox(
      ['-14.7608358', '71.5889534', '-180.0000000', '180.0000000'],
      39.7837304,
      -100.4458825,
    )!;
    expect(north - south).toBeLessThan(50);
    expect(south).toBeLessThan(39.7837304);
    expect(north).toBeGreaterThan(39.7837304);
  });

  it('rejects a box smeared by overseas territories', () => {
    // France: Kerguelen to French Polynesia, 350 deg of longitude. Never
    // quite +/-180, so the dateline check alone would miss it.
    expect(
      sanitizeGeocodeBbox(
        ['-50.2187169', '51.3055721', '-178.3873749', '172.3057152'],
        46.603354,
        1.8883335,
      ),
    ).toBeNull();
  });

  it('rejects an island-chain prefecture', () => {
    // "Tokyo" resolves to Tokyo Metropolis (rank 8), whose bbox reaches
    // 1800km south to the Ogasawara Islands, leaving the city itself 1.4%
    // from the northern edge. The box is roughly square, so an aspect-ratio
    // test does not catch it.
    expect(
      sanitizeGeocodeBbox(
        ['20.2145811', '35.8984245', '135.8536855', '154.2055410'],
        35.6768601,
        139.7638947,
      ),
    ).toBeNull();
  });

  it('rejects a padded node box', () => {
    // Mount Everest is an OSM node; Nominatim pads it to +/-0.00005 deg.
    // Not zero-area, so a degenerate-bounds guard never fires.
    expect(
      sanitizeGeocodeBbox(
        ['27.9880114', '27.9881114', '86.9251600', '86.9252600'],
        27.9880614,
        86.92521,
      ),
    ).toBeNull();
  });

  it('rejects malformed input', () => {
    expect(sanitizeGeocodeBbox(undefined, 0, 0)).toBeNull();
    expect(sanitizeGeocodeBbox(['1', '2'], 0, 0)).toBeNull();
    expect(sanitizeGeocodeBbox(['a', 'b', 'c', 'd'], 0, 0)).toBeNull();
    expect(sanitizeGeocodeBbox(['1', '2', '3', '4'], NaN, 0)).toBeNull();
  });
});

describe('boundsForPlaceRank', () => {
  it('sizes a country far wider than a building', () => {
    const [cw, , ce] = boundsForPlaceRank(48.85, 2.35, 4);
    const [bw, , be] = boundsForPlaceRank(48.85, 2.35, 30);
    expect(ce - cw).toBeGreaterThan((be - bw) * 100);
  });

  it('widens longitude at high latitude to keep the box roughly square', () => {
    const [ew, , ee] = boundsForPlaceRank(0, 0, 16);
    const [aw, , ae] = boundsForPlaceRank(78, 0, 16);
    expect(ae - aw).toBeGreaterThan(ee - ew);
  });

  it('falls back to a city-sized box when rank is unknown', () => {
    expect(boundsForPlaceRank(39.7, -104.9, undefined)).toEqual(
      boundsForPlaceRank(39.7, -104.9, 15),
    );
  });
});

describe('clampZoom', () => {
  it('holds the camera inside the usable range', () => {
    expect(clampZoom(22)).toBe(17);
    expect(clampZoom(0)).toBe(2);
    expect(clampZoom(11.4)).toBe(11.4);
  });
});
