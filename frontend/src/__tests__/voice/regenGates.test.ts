/**
 * §7.D #27 — ambient regeneration gates (U5): every gate must yield ZERO
 * hud-summary POSTs. The decision is the pure `shouldAttemptRegen` predicate
 * used verbatim by useVoiceGrounding before any fetch is initiated.
 */
import { describe, expect, it } from 'vitest';

import { shouldAttemptRegen } from '@/hooks/useVoiceGrounding';
import { REGEN_DEBOUNCE_MS_FOR_TESTS, REGEN_MIN_INTERVAL_MS } from '@/hooks/useVoiceGrounding';

const BASE = {
  controllerPhase: 'idle',
  ambientArmed: true,
  pollingPaused: false,
  tabHidden: false,
  msSinceLastPost: Number.MAX_SAFE_INTEGER,
  lastHash: 'abc',
  nextHash: 'def',
};

describe('ambient regen gates ⇒ zero POSTs (#27/#41)', () => {
  it('armed + enabled + changed view ⇒ POST allowed', () => {
    expect(shouldAttemptRegen(BASE)).toEqual({ ok: true });
  });

  it('arm-gate: disarmed console never posts (default state)', () => {
    const verdict = shouldAttemptRegen({ ...BASE, ambientArmed: false });
    expect(verdict).toEqual({ ok: false, reason: 'disarmed' });
  });

  it('opt-in gate: policy phases block before any network call', () => {
    for (const phase of ['opt-in-required', 'lean-unavailable']) {
      const verdict = shouldAttemptRegen({ ...BASE, controllerPhase: phase });
      expect(verdict.ok).toBe(false);
    }
  });

  it('Time-Machine pause blocks regeneration', () => {
    expect(shouldAttemptRegen({ ...BASE, pollingPaused: true })).toEqual({
      ok: false,
      reason: 'time_machine_paused',
    });
  });

  it('hidden tab blocks regeneration', () => {
    expect(shouldAttemptRegen({ ...BASE, tabHidden: true })).toEqual({
      ok: false,
      reason: 'tab_hidden',
    });
  });

  it('min-interval: a second ambient post inside the window is suppressed', () => {
    const verdict = shouldAttemptRegen({ ...BASE, msSinceLastPost: REGEN_MIN_INTERVAL_MS - 1 });
    expect(verdict).toEqual({ ok: false, reason: 'min_interval' });
  });

  it('min-interval does not apply to a first-ever post (no lastHash)', () => {
    const verdict = shouldAttemptRegen({ ...BASE, msSinceLastPost: 0, lastHash: '' });
    expect(verdict).toEqual({ ok: true });
  });

  it('fingerprint-hash gate: unchanged view never re-posts', () => {
    const verdict = shouldAttemptRegen({ ...BASE, nextHash: BASE.lastHash });
    expect(verdict).toEqual({ ok: false, reason: 'fingerprint_unchanged' });
  });

  it('debounce constant matches §3.6 (≥2.5 s view-change debounce)', () => {
    expect(REGEN_DEBOUNCE_MS_FOR_TESTS).toBeGreaterThanOrEqual(2500);
  });
});
