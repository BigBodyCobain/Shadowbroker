/**
 * §7.D #28 — cadence-table drift guard (U5, R11).
 *
 * LAYER_EXPECTED_CADENCE_S is a transcription of the backend scheduler
 * (`backend/services/data_fetcher.py::start_scheduler`). This suite re-reads
 * the scheduler source and fails when a job interval changes without the
 * narration table being updated. The fingerprint-stamp mirror assertion below
 * points at backend/tests/test_freshness_stamps.py as the ENFORCEMENT
 * AUTHORITY for genuine stamps — this file only checks the frontend mirror.
 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

import {
  DERIVED_LAYER_FRESHNESS_PARENT,
  FINGERPRINT_LAYER_KEYS,
  LAYER_EXPECTED_CADENCE_S,
} from '@/lib/voiceFreshness';

const BACKEND_ROOT = resolve(__dirname, '..', '..', '..', '..', 'backend');
const SCHEDULER_SOURCE = readFileSync(resolve(BACKEND_ROOT, 'services', 'data_fetcher.py'), 'utf8');

/** Extract the keyword-argument value inside the `add_job(...)` block whose
 *  body contains `id="<jobId>"`. */
function jobIntervalKwarg(source: string, jobId: string): string | null {
  const idAt = source.indexOf(`id="${jobId}"`);
  if (idAt === -1) return null;
  // Scan back to the enclosing add_job call opening.
  const start = source.lastIndexOf('_scheduler.add_job', idAt);
  const block = source.slice(start === -1 ? Math.max(0, idAt - 600) : start, idAt + 200);
  for (const kwarg of ['seconds=', 'minutes=', 'hours=', 'days=']) {
    const matches = [...block.matchAll(new RegExp(`${kwarg}(\\d+)`, 'g'))];
    if (matches.length > 0) return `${kwarg}${matches[matches.length - 1][1]}`;
  }
  return null;
}

describe('cadence table vs transcribed scheduler (drift guard)', () => {
  it('fast tier runs every 60 s → all fast-tier layers declare 60 s', () => {
    expect(jobIntervalKwarg(SCHEDULER_SOURCE, 'fast_tier')).toBe('seconds=60');
    for (const layer of [
      'commercial_flights',
      'private_jets',
      'private_flights',
      'tracked_flights',
      'military_flights',
      'uavs',
      'ships',
      'satellites',
      'sigint',
      'trains',
      'gps_jamming',
    ]) {
      expect(LAYER_EXPECTED_CADENCE_S[layer]).toBe(60);
    }
  });

  it('slow tier runs every 5 min → slow-tier layers declare 300 s', () => {
    expect(jobIntervalKwarg(SCHEDULER_SOURCE, 'slow_tier')).toBe('minutes=5');
    for (const layer of [
      'news',
      'earthquakes',
      'firms_fires',
      'fishing_activity',
      'cyber_threats',
      'malware_threats',
      'correlations',
    ]) {
      expect(LAYER_EXPECTED_CADENCE_S[layer]).toBe(300);
    }
  });

  it('dedicated jobs keep their documented cadences', () => {
    expect(jobIntervalKwarg(SCHEDULER_SOURCE, 'ukraine_alerts')).toBe('minutes=2');
    expect(LAYER_EXPECTED_CADENCE_S.ukraine_alerts).toBe(120);
    expect(jobIntervalKwarg(SCHEDULER_SOURCE, 'weather_alerts')).toBe('minutes=5');
    expect(LAYER_EXPECTED_CADENCE_S.weather_alerts).toBe(300);
    expect(jobIntervalKwarg(SCHEDULER_SOURCE, 'gdelt')).toBe('minutes=30');
    expect(LAYER_EXPECTED_CADENCE_S.gdelt).toBe(1800);
  });

  it('telegram_osint default (max(15, env) minutes) stays 60 min in the table', () => {
    expect(SCHEDULER_SOURCE).toContain('TELEGRAM_OSINT_INTERVAL_MINUTES", "60"');
    expect(LAYER_EXPECTED_CADENCE_S.telegram_osint).toBe(3600);
  });
});

// ---------------------------------------------------------------------------
// Fingerprint-stamp mirror — enforcement authority lives backend-side.
// ---------------------------------------------------------------------------

const STAMPS_TEST_SOURCE = readFileSync(
  resolve(BACKEND_ROOT, 'tests', 'test_freshness_stamps.py'),
  'utf8',
);

describe('fingerprint-stamp mirror (authority: backend/tests/test_freshness_stamps.py)', () => {
  it('frontend derived-parent map mirrors the backend adjacency-guard exemption', () => {
    // The backend guard exempts exactly these keys from in-function stamping;
    // if either side changes, both must change together.
    for (const [layer, parent] of Object.entries(DERIVED_LAYER_FRESHNESS_PARENT)) {
      expect(STAMPS_TEST_SOURCE).toContain(`"${layer}": "${parent}"`);
    }
    expect(Object.keys(DERIVED_LAYER_FRESHNESS_PARENT)).toEqual(['gps_jamming']);
  });

  it('every fingerprint key is expected to carry a REAL version bump post-U0', () => {
    // The backend tier-3 probe proves tracked_flights/correlations stamps feed
    // the delta ring; here we pin that the frontend treats all seven as
    // genuinely stamped (no unknown workarounds baked into dispositions).
    expect([...FINGERPRINT_LAYER_KEYS].sort()).toEqual(
      [
        'commercial_flights',
        'military_flights',
        'tracked_flights',
        'private_jets',
        'ships',
        'uavs',
        'correlations',
      ].sort(),
    );
  });
});
