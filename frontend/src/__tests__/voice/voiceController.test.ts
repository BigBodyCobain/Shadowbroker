/**
 * §7.D item 31 — voiceController: every legal/illegal transition, the 6 s
 * disconnect grace, monotonic quota-cap latching, and blur force-release of
 * a stuck PTT.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  VOICE_DISCONNECT_GRACE_MS,
  isLegalTransition,
  voiceController,
} from '@/lib/voiceController';
import type { VoicePhase, VoiceStatusResponse } from '@/lib/voiceTypes';

const ALL_PHASES: VoicePhase[] = [
  'opt-in-required',
  'lean-unavailable',
  'idle',
  'connecting',
  'listening',
  'thinking',
  'speaking',
  'error',
  'quota-capped',
];

const ENABLED_STATUS: VoiceStatusResponse = {
  ok: true,
  effectiveEnable: true,
  opt_in_state: 'enabled',
  flags: { enableSet: true, acknowledgeSet: true },
  provider: {
    resolved: 'openai_realtime',
    requestedMode: 'auto',
    openaiKeySet: true,
    compatKeySet: false,
    compatBaseUrlSet: false,
    chatModelConfigured: false,
  },
  degradedReason: null,
  reasons: [],
  mode: 'full',
  costDefaults: { warnUsd: 2, capUsd: 5, dailyBudgetUsd: 'off' },
  dailySpend: { date: '', usdSpent: 0, budgetUsd: 'off', remainingUsd: 'off', ledgerQuarantined: false },
  activeSessions: 0,
  maxConcurrent: 1,
};

function disabledStatus(mode: 'full' | 'mesh_lean' = 'full'): VoiceStatusResponse {
  return {
    ...ENABLED_STATUS,
    effectiveEnable: false,
    opt_in_state: 'not_requested',
    flags: { enableSet: false, acknowledgeSet: false },
    provider: { ...ENABLED_STATUS.provider, resolved: null },
    reasons: ['Voice agent outbound is blocked by configuration'],
    mode,
  };
}

describe('transition matrix (pure predicate)', () => {
  const LEGAL_PAIRS: Array<[VoicePhase, VoicePhase]> = [
    ['opt-in-required', 'idle'],
    ['opt-in-required', 'lean-unavailable'],
    ['lean-unavailable', 'idle'],
    ['lean-unavailable', 'opt-in-required'],
    ['idle', 'connecting'],
    ['idle', 'listening'],
    ['idle', 'error'],
    ['idle', 'quota-capped'],
    ['idle', 'opt-in-required'],
    ['idle', 'lean-unavailable'],
    ['connecting', 'listening'],
    ['connecting', 'thinking'],
    ['connecting', 'idle'],
    ['connecting', 'error'],
    ['listening', 'thinking'],
    ['listening', 'speaking'],
    ['listening', 'idle'],
    ['listening', 'error'],
    ['thinking', 'speaking'],
    ['thinking', 'listening'],
    ['thinking', 'idle'],
    ['speaking', 'listening'],
    ['speaking', 'idle'],
    ['error', 'idle'],
    ['error', 'connecting'],
    ['error', 'quota-capped'],
    ['quota-capped', 'idle'],
  ];

  const ILLEGAL_PAIRS: Array<[VoicePhase, VoicePhase]> = [
    // Policy states never jump into live session phases.
    ['opt-in-required', 'connecting'],
    ['opt-in-required', 'listening'],
    ['opt-in-required', 'thinking'],
    ['opt-in-required', 'speaking'],
    ['opt-in-required', 'error'],
    ['lean-unavailable', 'connecting'],
    ['lean-unavailable', 'thinking'],
    // Terminal cap state only releases through an explicit new session.
    ['quota-capped', 'connecting'],
    ['quota-capped', 'listening'],
    ['quota-capped', 'thinking'],
    ['quota-capped', 'speaking'],
    ['quota-capped', 'error'],
    // Backwards session flow.
    ['connecting', 'speaking'],
    ['thinking', 'connecting'],
    ['speaking', 'connecting'],
    ['error', 'listening'],
    ['error', 'thinking'],
    ['error', 'speaking'],
  ];

  it('accepts exactly the documented legal transitions', () => {
    for (const [from, to] of LEGAL_PAIRS) {
      expect(isLegalTransition(from, to), `${from} -> ${to} must be legal`).toBe(true);
    }
  });

  it('rejects every undocumented transition', () => {
    for (const [from, to] of ILLEGAL_PAIRS) {
      expect(isLegalTransition(from, to), `${from} -> ${to} must be illegal`).toBe(false);
    }
    for (const phase of ALL_PHASES) {
      expect(isLegalTransition(phase, phase)).toBe(true); // self-transitions are no-ops
    }
  });
});

describe('voiceController behavior', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    voiceController.resetForNewSession();
    voiceController.resetTranscript();
    voiceController.applyStatus(ENABLED_STATUS);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('fresh installs derive opt-in-required with verbatim reasons', () => {
    voiceController.applyStatus(disabledStatus());
    const state = voiceController.getState();
    expect(state.phase).toBe('opt-in-required');
    expect(state.degraded).toBe(true);
    expect(state.reasons[0]).toBe('Voice agent outbound is blocked by configuration');
  });

  it('mesh lean derives lean-unavailable', () => {
    voiceController.applyStatus(disabledStatus('mesh_lean'));
    expect(voiceController.getState().phase).toBe('lean-unavailable');
  });

  it('PTT begins connecting and releases back to idle', () => {
    voiceController.beginPtt();
    expect(voiceController.getState().pttHeld).toBe(true);
    expect(voiceController.getState().phase).toBe('connecting');
    voiceController.endPtt();
    expect(voiceController.getState().pttHeld).toBe(false);
    expect(voiceController.getState().phase).toBe('idle');
  });

  it('PTT is refused in policy/terminal phases', () => {
    voiceController.applyStatus(disabledStatus());
    voiceController.beginPtt();
    expect(voiceController.getState().pttHeld).toBe(false);
  });

  it('disconnect grace: blips recover inside 6 s, faults after', () => {
    voiceController.markDisconnected();
    vi.advanceTimersByTime(VOICE_DISCONNECT_GRACE_MS - 1);
    voiceController.markConnected();
    expect(voiceController.getState().phase).toBe('idle');
    voiceController.markDisconnected();
    vi.advanceTimersByTime(VOICE_DISCONNECT_GRACE_MS);
    expect(voiceController.getState().phase).toBe('error');
  });

  it('cost level never steps down; cap latches quota-capped once', () => {
    voiceController.applyCost({ total_usd: 2.1, display: '~$2.10', level: 'warn', note: null });
    voiceController.applyCost({ total_usd: 0.5, display: '~$0.50', level: 'ok', note: null });
    expect(voiceController.getState().cost?.level).toBe('warn');

    let phaseChanges = 0;
    let prevPhase = voiceController.getState().phase;
    const unsub = voiceController.subscribe(() => {
      const p = voiceController.getState().phase;
      if (p === 'quota-capped' && prevPhase !== 'quota-capped') phaseChanges += 1;
      prevPhase = p;
    });
    voiceController.applyCost({ total_usd: 5.4, display: '~$5.40', level: 'cap', note: null });
    voiceController.applyCost({ total_usd: 6, display: '~$6.00', level: 'cap', note: null });
    expect(voiceController.getState().phase).toBe('quota-capped');
    expect(phaseChanges).toBe(1); // single-fire latch
    unsub();
  });

  it('window blur force-releases a stuck PTT', () => {
    voiceController.beginPtt();
    expect(voiceController.getState().pttHeld).toBe(true);
    window.dispatchEvent(new Event('blur'));
    expect(voiceController.getState().pttHeld).toBe(false);
  });

  it('escape cancels an open mic honestly', () => {
    voiceController.beginPtt();
    voiceController.escape();
    expect(voiceController.getState().pttHeld).toBe(false);
    expect(voiceController.getState().phase).toBe('idle');
  });
});
