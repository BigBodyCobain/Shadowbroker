/**
 * voiceFreshness — single source of layer freshness cadences for NARRATE
 * grounding (voice-agent plan §2.5 / U5).
 *
 * Cadences are transcribed from backend/services/data_fetcher.py
 * (`start_scheduler`: fast tier 60 s, slow tier 300 s, dedicated jobs) and are
 * guarded against scheduler drift by
 * frontend/src/__tests__/voice/freshnessTable.test.ts (#28).
 *
 * Dispositions compute against BACKEND SCHEDULER CADENCES (source refresh),
 * never frontend poll tiers (delivery); delivery lag ≤15 s is absorbed by the
 * 2× bucket width. Buckets: live < 2×C · aging 2–5×C · stale ≥ 5×C ·
 * unknown = no usable timestamp.
 */

// ── Expected cadences (seconds) ─────────────────────────────────────────────

export const LAYER_EXPECTED_CADENCE_S: Readonly<Record<string, number>> = Object.freeze({
  // fast tier — 60 s (update_fast_data; fetch_flights stamps ONLY
  // commercial_flights/private_jets/private_flights before the tracked merge;
  // fetch_military_flights stamps military_flights,uavs; tracked_flights has
  // its own post-U0 stamps at flights.py/military.py final writes).
  commercial_flights: 60,
  private_jets: 60,
  private_flights: 60,
  tracked_flights: 60, // REAL post-fix (U0 stamps)
  military_flights: 60,
  uavs: 60,
  ships: 60,
  satellites: 60,
  sigint: 60,
  trains: 60,
  gps_jamming: 60, // derived inside fetch_flights; parent-routed below
  // dedicated jobs
  ukraine_alerts: 120, // every 2 min (time-critical)
  weather_alerts: 300, // every 5 min
  gdelt: 1800, // every 30 min
  telegram_osint: 3600, // max(15, env) minutes, default 60
  // slow tier — 300 s (update_slow_data) + post-tier correlation engine
  news: 300,
  earthquakes: 300,
  firms_fires: 300, // slow-tier stamped layer (fetch_firms_fires)
  fishing_activity: 300,
  cyber_threats: 300,
  malware_threats: 300,
  correlations: 300, // REAL post-fix (stamp adjacent to the _data_lock write)
});

/**
 * Layers whose freshness disposition is inherited from a parent instead of
 * being stamped. Mirrored by backend/tests/test_freshness_stamps.py — keep
 * both sides in sync.
 */
export const DERIVED_LAYER_FRESHNESS_PARENT: Readonly<Record<string, string>> = Object.freeze({
  gps_jamming: 'commercial_flights',
});

/** The seven fingerprint layers whose version bumps trigger regeneration;
 * post-U0 all seven receive genuine stamps (§2.5). */
export const FINGERPRINT_LAYER_KEYS: readonly string[] = Object.freeze([
  'commercial_flights',
  'military_flights',
  'tracked_flights',
  'private_jets',
  'ships',
  'uavs',
  'correlations',
]);

/** Closed narration key set (§2.5): only these layers appear in freshness
 * dispositions and trigger diffs. */
export const NARRATION_LAYER_KEYS: readonly string[] = Object.freeze(
  Object.keys(LAYER_EXPECTED_CADENCE_S),
);

/**
 * Layer → fetch-health task bridge. `tracked_flights` maps to BOTH flight
 * tasks (R20): narration reports whichever shows ok:false; both healthy ⇒
 * silent. `correlations` derives from other layers' data (engine runs inside
 * update_slow_data), so it owns no dedicated task.
 */
export const LAYER_TO_HEALTH_TASK: Readonly<Record<string, readonly string[]>> = Object.freeze({
  commercial_flights: ['fetch_flights'],
  private_jets: ['fetch_flights'],
  private_flights: ['fetch_flights'],
  tracked_flights: ['fetch_flights', 'fetch_military_flights'],
  gps_jamming: ['fetch_flights'],
  military_flights: ['fetch_military_flights'],
  uavs: ['fetch_military_flights'],
  ships: ['fetch_ships'],
  satellites: ['fetch_satellites'],
  sigint: ['fetch_sigint'],
  trains: ['fetch_trains'],
  news: ['fetch_news'],
  earthquakes: ['fetch_earthquakes'],
  firms_fires: ['fetch_firms_fires'],
  fishing_activity: ['fetch_fishing_activity'],
  cyber_threats: ['fetch_cyber_threats'],
  malware_threats: ['fetch_malware_threats'],
  gdelt: ['fetch_gdelt'],
  telegram_osint: ['fetch_telegram_osint'],
  ukraine_alerts: ['fetch_ukraine_air_raid_alerts'],
  weather_alerts: ['fetch_weather_alerts'],
  correlations: [], // engine-derived from slow-tier snapshots; no own task
});

// ── Disposition buckets ─────────────────────────────────────────────────────

export type FreshnessDisposition = 'live' | 'aging' | 'stale' | 'unknown';

/** Bucket an age against a layer's expected cadence (§2.5):
 *  live < 2×C · aging 2–5×C · stale ≥ 5×C · unknown = no usable age.
 *  Derived layers inherit their parent's cadence (sole case: gps_jamming). */
export function dispositionForLayer(
  layer: string,
  age_s: number | null | undefined,
): FreshnessDisposition {
  if (age_s == null || !Number.isFinite(age_s) || age_s < 0) return 'unknown';
  let cadence: number | undefined = LAYER_EXPECTED_CADENCE_S[layer];
  if (cadence == null) {
    const parent = DERIVED_LAYER_FRESHNESS_PARENT[layer];
    cadence = parent ? LAYER_EXPECTED_CADENCE_S[parent] : undefined;
  }
  if (!cadence || !Number.isFinite(cadence) || cadence <= 0) return 'unknown';
  if (age_s < 2 * cadence) return 'live';
  if (age_s < 5 * cadence) return 'aging';
  return 'stale';
}

/** Age in seconds of a source_timestamps ISO stamp relative to now. */
export function ageFromStamp(stamp: string | undefined | null, now = Date.now()): number | null {
  if (!stamp) return null;
  const ms = Date.parse(stamp);
  if (!Number.isFinite(ms)) return null;
  return Math.max(0, Math.round((now - ms) / 1000));
}

// ── News sentiment buckets (must equal NewsFeed.tsx thresholds) ────────────

export type SentimentBucket = 'NEGATIVE' | 'POSITIVE' | 'NEUTRAL';

/** NewsFeed.tsx label buckets: ≤ −0.05 NEGATIVE · ≥ +0.05 POSITIVE · else NEUTRAL. */
export function newsSentimentBucket(sentiment: number | null | undefined): SentimentBucket {
  if (sentiment == null || !Number.isFinite(sentiment)) return 'NEUTRAL';
  if (sentiment <= -0.05) return 'NEGATIVE';
  if (sentiment >= 0.05) return 'POSITIVE';
  return 'NEUTRAL';
}
