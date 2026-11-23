/**
 * Tests for reading radar watch areas from the published coverage list.
 * Run: node --test viewer/web/tests/sarAois.test.ts
 */

import assert from 'node:assert/strict';
import { test } from 'node:test';
import { viewerSarAois } from '../overlay/src/viewer/sarAois.ts';

test('coverage rows become watch areas', () => {
  const areas = viewerSarAois([
    { aoi_id: 'suez-canal', aoi_name: 'Suez Canal', category: 'infrastructure', center_lat: 30.45, center_lon: 32.35, radius_km: 60 },
  ]);
  assert.deepEqual(areas, [
    { id: 'suez-canal', name: 'Suez Canal', center: [30.45, 32.35], radius_km: 60, polygon: null, category: 'infrastructure' },
  ]);
});

test('bad rows are skipped and gaps get safe defaults', () => {
  const areas = viewerSarAois([
    null,
    'x',
    { aoi_id: '', center_lat: 1, center_lon: 2 },
    { aoi_id: 'no-centre' },
    { aoi_id: 'text-centre', center_lat: '1', center_lon: '2' },
    { aoi_id: 'off-planet', center_lat: 95, center_lon: 0 },
    { aoi_id: 'plain', center_lat: 1, center_lon: 2 },
    { aoi_id: 'plain', center_lat: 3, center_lon: 4 },
    { aoi_id: 'huge', center_lat: 5, center_lon: 6, radius_km: 99999 },
  ]);
  assert.deepEqual(areas.map((a) => a.id), ['plain', 'huge']);
  assert.deepEqual(areas[0], { id: 'plain', name: 'plain', center: [1, 2], radius_km: 25, polygon: null, category: 'watchlist' });
  assert.equal(areas[1].radius_km, 500);
});

test('anything that is not a list gives no areas', () => {
  assert.deepEqual(viewerSarAois(undefined), []);
  assert.deepEqual(viewerSarAois({ aoi_id: 'x' }), []);
});
