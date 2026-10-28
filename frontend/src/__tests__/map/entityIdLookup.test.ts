/**
 * Regression: clicking an AIS vessel showed no popup or side panel.
 *
 * The dynamic worker labels ships with shipFeatureId(), which stringifies the
 * MMSI, but the backend sends MMSIs as numbers. Lookups compared them with
 * `===`, so `234881054 === "234881054"` matched nothing and the UI stayed empty.
 */
import { describe, expect, it } from 'vitest';
import { sameEntityId, shipFeatureId } from '@/components/map/featureIds';
import { findSelectedEntity } from '@/components/map/geoJSONBuilders';
import type { DashboardData, Ship } from '@/types/dashboard';

describe('sameEntityId', () => {
  it('matches numeric records against stringified feature ids', () => {
    expect(sameEntityId(234881054, '234881054')).toBe(true);
    expect(sameEntityId('234881054', 234881054)).toBe(true);
  });

  it('does not match different, missing, or empty ids', () => {
    expect(sameEntityId(1, '2')).toBe(false);
    expect(sameEntityId(undefined, 'undefined')).toBe(false);
    expect(sameEntityId(null, 'null')).toBe(false);
    expect(sameEntityId('', '')).toBe(false);
  });
});

describe('findSelectedEntity for ships', () => {
  it('finds a vessel whose numeric MMSI was stringified for its map feature', () => {
    const ship = { name: 'OCEANICA', lat: 1, lng: 2, type: 'cargo', mmsi: 710033650 } as unknown as Ship;
    const data = { ships: [ship] } as unknown as DashboardData;
    const featureId = shipFeatureId(ship);

    expect(typeof featureId).toBe('string');
    expect(findSelectedEntity({ type: 'ship', id: featureId }, data)).toBe(ship);
  });
});
