import { describe, expect, it } from 'vitest';
import { shipsWithIcons, trackedFlightsWithIcons } from '@/components/map/labelSubjects';
import { shipFeatureId, trackedFlightFeatureId } from '@/components/map/featureIds';
import type { Ship, TrackedFlight } from '@/types/dashboard';

function collection(ids: Array<string | number>): GeoJSON.FeatureCollection {
  return {
    type: 'FeatureCollection',
    features: ids.map((id) => ({
      type: 'Feature',
      properties: { id },
      geometry: { type: 'Point', coordinates: [0, 0] },
    })),
  };
}

function flight(overrides: Partial<TrackedFlight>): TrackedFlight {
  return { type: 'tracked_flight', lat: 40, lng: -74, ...overrides } as TrackedFlight;
}

function ship(overrides: Partial<Ship>): Ship {
  return { type: 'yacht', lat: 40, lng: -74, ...overrides } as Ship;
}

describe('trackedFlightsWithIcons', () => {
  const spielberg = flight({ icao24: 'a1b2c3', callsign: 'N700KS', alert_category: 'Celebrity' });
  const quest = flight({ icao24: 'd4e5f6', callsign: 'LBQ500', alert_category: 'Business' });

  it('keeps only flights whose icao24 has a feature in the filtered layer', () => {
    expect(trackedFlightsWithIcons([spielberg, quest], collection(['a1b2c3']))).toEqual([spielberg]);
  });

  it('matches features by the same id rule the worker uses', () => {
    const noIcao = flight({ callsign: 'ZZZ1' });
    const nothing = flight({});
    // Worker-side ids, including the positional fallback for an unidentifiable row.
    const ids = [spielberg, noIcao, nothing].map((f, i) => trackedFlightFeatureId(f, `tracked-${i}`));
    expect(ids).toEqual(['a1b2c3', 'ZZZ1', 'tracked-2']);
    // Only rows with a real identifier can be matched back for labelling.
    expect(trackedFlightsWithIcons([spielberg, noIcao, nothing], collection(ids))).toEqual([
      spielberg,
      noIcao,
    ]);
  });

  it('returns nothing when the layer has no GeoJSON', () => {
    expect(trackedFlightsWithIcons([spielberg], null)).toEqual([]);
    expect(trackedFlightsWithIcons(undefined, collection(['a1b2c3']))).toEqual([]);
  });
});

describe('shipsWithIcons', () => {
  const eclipse = ship({ mmsi: 123456789, name: 'ECLIPSE', yacht_alert: true });
  const tanker = ship({ mmsi: 987654321, name: 'TANKER', type: 'tanker' });

  it('matches numeric mmsi against the string feature id', () => {
    expect(shipsWithIcons([eclipse, tanker], collection([123456789]))).toEqual([eclipse]);
  });

  it('matches features by the same id rule the worker uses', () => {
    const unnamed = ship({ name: 'NO MMSI' });
    const ids = [eclipse, unnamed].map((s, i) => shipFeatureId(s, `ship-${i}`));
    expect(ids).toEqual(['123456789', 'NO MMSI']);
    expect(shipsWithIcons([eclipse, unnamed], collection(ids))).toEqual([eclipse, unnamed]);
  });

  it('returns nothing when the layer has no GeoJSON', () => {
    expect(shipsWithIcons([eclipse], null)).toEqual([]);
  });
});
