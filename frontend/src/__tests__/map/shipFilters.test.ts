import { describe, expect, it } from 'vitest';
import { filterShipsByActiveFilters } from '@/components/map/shipFilters';

const nimitz = { name: 'USS Nimitz (CVN-68)', type: 'carrier' as const };
const eclipse = { name: 'ECLIPSE', type: 'yacht' as const };
const frigate = { name: 'HMS Diamond', type: 'military_vessel' as const };
const ships = [nimitz, eclipse, frigate];

describe('filterShipsByActiveFilters', () => {
  it('returns the same array when no ship filter is set', () => {
    expect(filterShipsByActiveFilters(ships, undefined)).toBe(ships);
    expect(filterShipsByActiveFilters(ships, { ship_type: [] })).toBe(ships);
    expect(filterShipsByActiveFilters(ships, { commercial_airline: ['UAL'] })).toBe(ships);
  });

  it('keeps carriers only when their own type is selected', () => {
    expect(filterShipsByActiveFilters(ships, { ship_type: ['yacht'] })).toEqual([eclipse]);
    expect(filterShipsByActiveFilters(ships, { ship_type: ['military_vessel'] })).toEqual([frigate]);
    expect(filterShipsByActiveFilters(ships, { ship_type: ['carrier', 'yacht'] })).toEqual([
      nimitz,
      eclipse,
    ]);
  });

  it('combines name and type filters', () => {
    expect(
      filterShipsByActiveFilters(ships, { ship_name: ['ECLIPSE'], ship_type: ['carrier'] }),
    ).toEqual([]);
    expect(filterShipsByActiveFilters(ships, { ship_name: ['USS Nimitz (CVN-68)'] })).toEqual([
      nimitz,
    ]);
  });

  it('handles a missing ship array', () => {
    expect(filterShipsByActiveFilters(undefined, { ship_type: ['yacht'] })).toEqual([]);
  });
});
