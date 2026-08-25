/**
 * §7.D #26 — grounding composer / freshness dispositions (U5).
 *
 * Golden fixtures assert REAL post-fix dispositions (live/aging), never
 * unknown workarounds — the §2.3 stamps must be visible here (R23).
 */
import { describe, expect, it } from 'vitest';

import {
  DERIVED_LAYER_FRESHNESS_PARENT,
  FINGERPRINT_LAYER_KEYS,
  LAYER_EXPECTED_CADENCE_S,
  NARRATION_LAYER_KEYS,
  ageFromStamp,
  dispositionForLayer,
  newsSentimentBucket,
} from '@/lib/voiceFreshness';
import { composeFreshness } from '@/hooks/useVoiceGrounding';

const NOW = Date.parse('2026-08-25T12:00:00Z');
function stampAge(secondsAgo: number): string {
  return new Date(NOW - secondsAgo * 1000).toISOString();
}

describe('disposition buckets (§2.5: live < 2×C · aging 2–5×C · stale ≥ 5×C)', () => {
  const cadence = 60; // fast-tier layer
  it('boundary: just under 2× cadence is live', () => {
    expect(dispositionForLayer('ships', 2 * cadence - 1)).toBe('live');
  });
  it('boundary: exactly 2× cadence is aging', () => {
    expect(dispositionForLayer('ships', 2 * cadence)).toBe('aging');
  });
  it('boundary: just under 5× cadence is still aging', () => {
    expect(dispositionForLayer('ships', 5 * cadence - 1)).toBe('aging');
  });
  it('boundary: exactly 5× cadence is stale', () => {
    expect(dispositionForLayer('ships', 5 * cadence)).toBe('stale');
  });
  it('slow-tier layers bucket against their own cadence', () => {
    // news C=300 → live < 600 s
    expect(dispositionForLayer('news', 500)).toBe('live');
    expect(dispositionForLayer('news', 700)).toBe('aging');
    expect(dispositionForLayer('news', 1500)).toBe('stale');
  });
  it('negative/non-finite/null ages are unknown, never estimates', () => {
    for (const age of [null, undefined, NaN, -5]) {
      expect(dispositionForLayer('ships', age as number)).toBe('unknown');
    }
  });
});

describe('gps_jamming parent inheritance (sole derived case)', () => {
  it('inherits commercial_flights cadence through DERIVED_LAYER_FRESHNESS_PARENT', () => {
    expect(DERIVED_LAYER_FRESHNESS_PARENT).toEqual({ gps_jamming: 'commercial_flights' });
    // gps_jamging has no own stamp; parent stamp age drives the disposition.
    expect(dispositionForLayer('gps_jamming', 100)).toBe('live');
    expect(dispositionForLayer('gps_jamming', 400)).toBe('stale'); // ≥ 5×60
  });
  it('composeFreshness resolves gps_jamging from the parent stamp', () => {
    const stamps = { commercial_flights: stampAge(30) };
    const { map } = composeFreshness(stamps, NOW);
    expect(map.gps_jamming.disposition).toBe('live');
    expect(map.gps_jamming.age_s).toBe(30);
  });
});

describe('sentiment buckets equal NewsFeed thresholds (±0.05 labels)', () => {
  it.each([
    [-0.05, 'NEGATIVE'],
    [-0.9, 'NEGATIVE'],
    [0.05, 'POSITIVE'],
    [0.42, 'POSITIVE'],
    [0.04, 'NEUTRAL'],
    [-0.04, 'NEUTRAL'],
    [0, 'NEUTRAL'],
    [null, 'NEUTRAL'],
  ])('%s → %s', (sentiment, expected) => {
    expect(newsSentimentBucket(sentiment as number)).toBe(expected);
  });
});

describe('closed key sets (§2.5)', () => {
  it('NARRATION_LAYER_KEYS is the closed 22-key set matching the cadence table', () => {
    expect(NARRATION_LAYER_KEYS.length).toBe(22);
    expect(new Set(NARRATION_LAYER_KEYS)).toEqual(new Set(Object.keys(LAYER_EXPECTED_CADENCE_S)));
  });
  it('all seven fingerprint keys are narration keys with real cadences', () => {
    expect(FINGERPRINT_LAYER_KEYS.length).toBe(7);
    for (const key of FINGERPRINT_LAYER_KEYS) {
      expect(LAYER_EXPECTED_CADENCE_S[key]).toBeGreaterThan(0);
    }
  });
});

describe('post-fix golden fixtures — real dispositions, not unknown', () => {
  it('tracked_flights and correlations narrate honest fresh ages post-U0', () => {
    const stamps = {
      tracked_flights: stampAge(45),
      correlations: stampAge(120),
      ships: stampAge(150),
      news: stampAge(240),
      never_stamped_layer: stampAge(30), // outside narration set but present
    };
    const { rows, map } = composeFreshness(stamps, NOW);
    const byLayer = Object.fromEntries(rows.map((r) => [r.layer, r]));
    expect(byLayer.tracked_flights).toEqual({ layer: 'tracked_flights', disposition: 'live', age_s: 45 });
    expect(byLayer.correlations.disposition).toBe('live');
    expect(byLayer.ships.disposition).toBe('aging'); // 150s = 2.5×60 ∈ [2×60, 5×60)
    expect(map.news.expected_cadence_s).toBe(300);
    // Unknown when no usable timestamp exists — reported exactly as marked.
    expect(byLayer.satellites.disposition).toBe('unknown');
    expect(byLayer.satellites.age_s).toBeNull();
  });

  it('garbage stamps degrade to unknown, never throw', () => {
    const { map } = composeFreshness({ gdelt: 'not-a-timestamp' }, NOW);
    expect(map.gdelt.disposition).toBe('unknown');
    expect(ageFromStamp('not-a-timestamp')).toBeNull();
  });
});
