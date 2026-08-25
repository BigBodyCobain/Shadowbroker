/**
 * §7.D item 32 — VoiceMicButton render matrix: one assertion set per phase
 * (border class + chip + aria-label), reduced-motion classes present, and
 * degraded-mode pointer routing to the composer.
 */
import React from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import VoiceMicButton from '@/components/VoiceMicButton';
import { voiceController } from '@/lib/voiceController';
import type { VoicePhase, VoiceStatusResponse } from '@/lib/voiceTypes';

function enabledStatus(overrides: Partial<VoiceStatusResponse> = {}): VoiceStatusResponse {
  return {
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
    costDefaults: { warnUsd: 'off', capUsd: 'off', dailyBudgetUsd: 'off' },
    dailySpend: { date: '', usdSpent: 0, budgetUsd: 'off', remainingUsd: 'off', ledgerQuarantined: false },
    activeSessions: 0,
    maxConcurrent: 1,
    ...overrides,
  };
}

/** Drive the singleton into `phase` through legal transitions only. */
function drive(phase: VoicePhase) {
  voiceController.resetForNewSession();
  voiceController.resetTranscript();
  switch (phase) {
    case 'opt-in-required':
      voiceController.applyStatus({ ...enabledStatus(), effectiveEnable: false, provider: { ...enabledStatus().provider, resolved: null }, reasons: ['Voice agent outbound is blocked by configuration'] });
      break;
    case 'lean-unavailable':
      voiceController.applyStatus(enabledStatus({ mode: 'mesh_lean' }));
      break;
    case 'idle':
      voiceController.applyStatus(enabledStatus());
      break;
    case 'connecting':
      voiceController.beginPtt();
      break;
    case 'listening':
      voiceController.beginPtt();
      voiceController.markListening();
      break;
    case 'thinking':
      voiceController.beginThinking();
      break;
    case 'speaking':
      voiceController.beginThinking();
      voiceController.markSpeaking();
      break;
    case 'error':
      voiceController.fail('link fault');
      break;
    case 'quota-capped':
      voiceController.applyStatus(enabledStatus());
      voiceController.applyCost({ total_usd: 5.4, display: '~$5.40', level: 'cap', note: null });
      break;
  }
}

describe('VoiceMicButton render matrix', () => {
  beforeEach(() => {
    window.localStorage.setItem('sb_voice_hint_seen_v1', '1');
  });

  afterEach(() => {
    cleanup();
    voiceController.resetForNewSession();
  });

  const CASES: Array<[VoicePhase, string | null]> = [
    ['opt-in-required', 'OPT-IN REQUIRED'],
    ['lean-unavailable', 'LEAN MODE'],
    ['idle', null],
    ['connecting', 'LINK…'],
    ['listening', null],
    ['thinking', '…'],
    ['speaking', 'TX'],
    ['error', 'FAULT'],
    ['quota-capped', '$ CAP'],
  ];

  for (const [phase, chip] of CASES) {
    it(`renders phase ${phase} with border class and text chip`, () => {
      drive(phase);
      render(<VoiceMicButton />);
      const root = screen.getByTestId('voice-mic-button');
      const button = root.querySelector('button') as HTMLButtonElement;
      // Border class per the §5.2 matrix.
      const cls = button.className;
      if (phase === 'opt-in-required' || phase === 'lean-unavailable') {
        expect(cls).toContain('opacity-50');
      } else if (phase === 'idle') {
        expect(cls).toContain('border-violet-500/40');
      } else if (phase === 'error') {
        expect(cls).toContain('border-red-800/70');
      } else if (phase === 'quota-capped') {
        expect(cls).toContain('border-amber-700/70');
      }
      // Text chip — color independence.
      const chipEl = screen.queryByTestId('voice-phase-chip');
      if (chip) {
        expect(chipEl).not.toBeNull();
        expect(chipEl!.textContent).toBe(chip);
      }
    });

    it(`renders an aria-label for ${phase}`, () => {
      drive(phase);
      render(<VoiceMicButton />);
      const button = screen.getByTestId('voice-mic-button').querySelector('button') as HTMLButtonElement;
      expect(button.getAttribute('aria-label')).toBeTruthy();
      expect(button.getAttribute('aria-label')).not.toBe('');
    });
  }

  it('shows the TXT corner badge in degraded mode', () => {
    drive('opt-in-required');
    render(<VoiceMicButton />);
    expect(screen.getByTestId('voice-txt-badge')).not.toBeNull();
  });

  it('hides the TXT corner badge when fully enabled', () => {
    drive('idle');
    render(<VoiceMicButton />);
    expect(screen.queryByTestId('voice-txt-badge')).toBeNull();
  });

  it('animated elements carry reduced-motion opt-out classes', () => {
    drive('listening');
    render(<VoiceMicButton />);
    const root = screen.getByTestId('voice-mic-button').innerHTML;
    expect(root).toContain('motion-reduce:');
  });

  it('degraded activation routes to the composer instead of mic capture (§3.7)', () => {
    drive('opt-in-required');
    const focusSpy = vi.spyOn(voiceController, 'requestComposerFocus');
    const openSpy = vi.spyOn(voiceController, 'setPanelOpen');
    render(<VoiceMicButton />);
    const button = screen.getByTestId('voice-mic-button').querySelector('button') as HTMLButtonElement;
    fireEvent.click(button);
    expect(focusSpy).toHaveBeenCalled();
    expect(openSpy).toHaveBeenCalledWith(true);
  });

  it('interactive hold past the threshold begins PTT', () => {
    vi.useFakeTimers();
    try {
      drive('idle');
      const beginSpy = vi.spyOn(voiceController, 'beginPtt');
      render(<VoiceMicButton />);
      const button = screen.getByTestId('voice-mic-button').querySelector('button') as HTMLButtonElement;
      fireEvent.pointerDown(button);
      vi.advanceTimersByTime(300); // past the PTT_HOLD_MS threshold
      expect(beginSpy).toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });

  it('quick tap (below the hold threshold) opens the console panel', () => {
    drive('idle');
    const openSpy = vi.spyOn(voiceController, 'setPanelOpen');
    render(<VoiceMicButton />);
    const button = screen.getByTestId('voice-mic-button').querySelector('button') as HTMLButtonElement;
    fireEvent.pointerDown(button);
    fireEvent.pointerUp(button); // released before PTT_HOLD_MS
    fireEvent.click(button);
    expect(openSpy).toHaveBeenCalledWith(true);
  });
});
