/**
 * P5C: Jittered DM poll scheduling.
 *
 * Removes exact fixed-interval DM polling cadence to reduce timing
 * fingerprinting. Privacy profile controls jitter width: high-privacy
 * mode uses a wider band so recurring polls are less distinguishable
 * from random network noise.
 *
 * Also provides bounded catch-up scheduling for `has_more` backlog
 * recovery — short jittered delays, capped to avoid burst-drain.
 */

import { getPrivacyProfilePreference } from './privacyBrowserStorage';

/** Jitter multiplier ranges keyed by privacy profile. */
const JITTER_BANDS: Record<string, { min: number; max: number }> = {
  default: { min: 0.8, max: 1.4 },
  high: { min: 0.5, max: 2.0 },
};

/** Catch-up delay ranges (ms) for has_more backlog recovery. */
const CATCHUP_BANDS: Record<string, { min: number; max: number }> = {
  default: { min: 2_000, max: 5_000 },
  high: { min: 3_000, max: 8_000 },
};

/** Maximum consecutive catch-up polls before falling back to normal cadence. */
export const MAX_CATCHUP_POLLS = 3;

/**
 * Return a jittered delay (ms) for normal recurring DM poll/count activity.
 *
 * @param baseMs - The nominal interval (e.g. 12_000 or 15_000).
 * @param opts.profile - Override privacy profile (default: read from browser storage).
 * @param opts.random - Override random source (default: Math.random); useful for tests.
 */
export function jitteredPollDelay(
  baseMs: number,
  opts?: { profile?: string; random?: number },
): number {
  const profile = opts?.profile ?? getPrivacyProfilePreference();
  const band = JITTER_BANDS[profile] || JITTER_BANDS.default;
  const r = opts?.random ?? Math.random();
  const factor = band.min + r * (band.max - band.min);
  return Math.round(baseMs * factor);
}

/**
 * Return a jittered catch-up delay (ms) for bounded has_more follow-up.
 *
 * @param opts.profile - Override privacy profile.
 * @param opts.random - Override random source.
 */
export function catchUpDelay(
  opts?: { profile?: string; random?: number },
): number {
  const profile = opts?.profile ?? getPrivacyProfilePreference();
  const band = CATCHUP_BANDS[profile] || CATCHUP_BANDS.default;
  const r = opts?.random ?? Math.random();
  return Math.round(band.min + r * (band.max - band.min));
}

export type TickClassification = {
  delay: number;
  refreshCount: boolean;
  newBudget: number;
};

/**
 * Classify the next tick: determine delay, whether to refresh count,
 * and the updated catch-up budget.
 *
 * Catch-up ticks (has_more + budget remaining) use a shorter delay and
 * skip the count endpoint to avoid accelerating coarse-count cadence.
 * Normal ticks refresh both messages and count.
 */
export function classifyTick(
  hasMore: boolean,
  catchUpBudget: number,
  baseMs: number,
  opts?: { profile?: string; random?: number },
): TickClassification {
  if (hasMore && catchUpBudget > 0) {
    return {
      delay: catchUpDelay(opts),
      refreshCount: false,
      newBudget: catchUpBudget - 1,
    };
  }
  return {
    delay: jitteredPollDelay(baseMs, opts),
    refreshCount: true,
    newBudget: MAX_CATCHUP_POLLS,
  };
}
