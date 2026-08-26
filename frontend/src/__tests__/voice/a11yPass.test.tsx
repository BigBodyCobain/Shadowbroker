/**
 * §6 U7 — reduced-motion / RTL hardening pass.
 *
 * Reduced-motion: the animated phase indicators (waveform, spinner, TX
 * equalizer) must carry Tailwind `motion-reduce:` guards — asserted
 * structurally here because jsdom cannot emulate the media query.
 * RTL: the app sets `document.documentElement.dir = 'rtl'` for fa/ar
 * locales (i18n/index.tsx:121); both voice surfaces must render intact
 * with their key affordances present — no component may assume LTR to
 * function.
 */
import React from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import VoiceMicButton from '@/components/VoiceMicButton';
import VoiceHudPanel from '@/components/VoiceHudPanel';
import { voiceController } from '@/lib/voiceController';
import type { VoiceStatusResponse } from '@/lib/voiceTypes';

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
      geminiKeySet: false,
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

describe('voice a11y pass (U7)', () => {
  beforeEach(() => {
    window.localStorage.setItem('sb_voice_hint_seen_v1', '1');
    voiceController.resetForNewSession();
    voiceController.resetTranscript();
  });

  afterEach(() => {
    cleanup();
    document.documentElement.dir = '';
  });

  it('animated indicators carry motion-reduce guards', () => {
    voiceController.applyStatus(enabledStatus());
    voiceController.backToIdle();
    voiceController.beginPtt();
    voiceController.markListening();

    const { container } = render(<VoiceMicButton />);
    const waveform = container.querySelector('[data-testid="voice-waveform"]');
    expect(waveform).not.toBeNull();
    // The container hides entirely under reduced motion; each animated bar
    // freezes instead of pulsing.
    expect(waveform!.className).toContain('motion-reduce:hidden');
    container.querySelectorAll('.animate-pulse').forEach((bar) => {
      expect(bar.className).toContain('motion-reduce:animate-none');
    });
  });

  it('thinking spinner freezes under reduced motion', () => {
    voiceController.applyStatus(enabledStatus());
    voiceController.backToIdle();
    // idle→thinking is illegal (LEGAL_TRANSITIONS); the real path is
    // idle → listening → thinking.
    voiceController.markListening();
    voiceController.beginThinking();
    const { container } = render(<VoiceMicButton />);
    const spinner = container.querySelector('.animate-spin');
    expect(spinner).not.toBeNull();
    expect(spinner!.className).toContain('motion-reduce:animate-none');
  });

  it('VoiceMicButton renders intact under RTL', () => {
    document.documentElement.dir = 'rtl';
    voiceController.applyStatus(enabledStatus());
    voiceController.backToIdle();

    render(<VoiceMicButton />);
    expect(screen.getByTestId('voice-mic-button')).not.toBeNull();
    // Phase chip + accessible label survive direction flip.
    expect(screen.getByLabelText(/voice/i)).not.toBeNull();
  });

  it('degraded TXT badge renders under RTL', () => {
    document.documentElement.dir = 'rtl';
    voiceController.applyStatus(
      enabledStatus({ provider: { ...enabledStatus().provider, resolved: null }, degradedReason: 'no model' }),
    );
    voiceController.backToIdle();

    render(<VoiceMicButton />);
    expect(screen.getByTestId('voice-txt-badge')).not.toBeNull();
  });

  it('VoiceHudPanel renders intact under RTL', () => {
    document.documentElement.dir = 'rtl';
    voiceController.applyStatus(enabledStatus());
    voiceController.pushTurn({ role: 'agent', kind: 'text', text: 'Brief ready.' });

    render(<VoiceHudPanel onSubmit={vi.fn()} onClose={vi.fn()} />);
    expect(screen.getByRole('textbox')).not.toBeNull();
    expect(screen.getByText('Brief ready.')).not.toBeNull();
  });
});
