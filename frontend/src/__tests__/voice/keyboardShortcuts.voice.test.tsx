/**
 * §7.D item 34 — keyboard V PTT extension: fires down/up only outside inputs,
 * e.repeat ignored, and undefined voicePtt keeps legacy behavior byte-identical.
 */
import React from 'react';
import { cleanup, fireEvent, render } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useKeyboardShortcuts } from '@/hooks/useKeyboardShortcuts';
import { voiceController } from '@/lib/voiceController';
import type { VoiceStatusResponse } from '@/lib/voiceTypes';

type Actions = Parameters<typeof useKeyboardShortcuts>[0];

function baseActions(overrides: Partial<Actions> = {}): Actions {
  return {
    toggleLeft: vi.fn(),
    toggleRight: vi.fn(),
    toggleMarkets: vi.fn(),
    openSettings: vi.fn(),
    openLegend: vi.fn(),
    openShortcuts: vi.fn(),
    deselectEntity: vi.fn(),
    focusSearch: vi.fn(),
    ...overrides,
  };
}

function Harness({ actions }: { actions: Actions }) {
  useKeyboardShortcuts(actions);
  return <div />;
}

describe('useKeyboardShortcuts voicePtt (V)', () => {
  afterEach(cleanup);

  it('V fires begin on keydown and end on keyup', () => {
    const begin = vi.fn();
    const end = vi.fn();
    render(<Harness actions={baseActions({ voicePtt: { begin, end } })} />);
    fireEvent.keyDown(document, { key: 'v' });
    expect(begin).toHaveBeenCalledTimes(1);
    fireEvent.keyUp(document, { key: 'v' });
    expect(end).toHaveBeenCalledTimes(1);
  });

  it('ignores V while typing in an input', () => {
    const begin = vi.fn();
    const end = vi.fn();
    render(<Harness actions={baseActions({ voicePtt: { begin, end } })} />);
    const input = document.createElement('input');
    document.body.appendChild(input);
    const down = new KeyboardEvent('keydown', { key: 'v', bubbles: true });
    Object.defineProperty(down, 'target', { value: input });
    document.dispatchEvent(down);
    const up = new KeyboardEvent('keyup', { key: 'v', bubbles: true });
    Object.defineProperty(up, 'target', { value: input });
    document.dispatchEvent(up);
    expect(begin).not.toHaveBeenCalled();
    expect(end).not.toHaveBeenCalled();
    input.remove();
  });

  it('ignores e.repeat holds', () => {
    const begin = vi.fn();
    render(<Harness actions={baseActions({ voicePtt: { begin, end: vi.fn() } })} />);
    const repeatEvent = new KeyboardEvent('keydown', { key: 'v', bubbles: true });
    Object.defineProperty(repeatEvent, 'repeat', { value: true });
    document.dispatchEvent(repeatEvent);
    expect(begin).not.toHaveBeenCalled();
  });

  it('window blur force-releases the hold', () => {
    const end = vi.fn();
    render(<Harness actions={baseActions({ voicePtt: { begin: vi.fn(), end } })} />);
    window.dispatchEvent(new Event('blur'));
    expect(end).toHaveBeenCalled();
  });

  it('undefined voicePtt leaves legacy behavior byte-identical (V unbound)', () => {
    const toggleLeft = vi.fn();
    render(<Harness actions={baseActions({ toggleLeft })} />);
    // No crash, no listener errors; L still works.
    fireEvent.keyDown(document, { key: 'l' });
    expect(toggleLeft).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(document, { key: 'v' });
    expect(toggleLeft).toHaveBeenCalledTimes(1);
    fireEvent.keyUp(document, { key: 'v' });
    expect(toggleLeft).toHaveBeenCalledTimes(1);
  });

  it('Ctrl fires begin on keydown and end on keyup', () => {
    const begin = vi.fn();
    const end = vi.fn();
    render(<Harness actions={baseActions({ voicePtt: { begin, end } })} />);
    fireEvent.keyDown(document, { key: 'Control' });
    expect(begin).toHaveBeenCalledTimes(1);
    fireEvent.keyUp(document, { key: 'Control' });
    expect(end).toHaveBeenCalledTimes(1);
  });

  it('Ctrl works while focused in an input (produces no characters)', () => {
    const begin = vi.fn();
    const end = vi.fn();
    render(<Harness actions={baseActions({ voicePtt: { begin, end } })} />);
    const input = document.createElement('input');
    document.body.appendChild(input);
    const down = new KeyboardEvent('keydown', { key: 'Control', bubbles: true });
    Object.defineProperty(down, 'target', { value: input });
    document.dispatchEvent(down);
    expect(begin).toHaveBeenCalledTimes(1);
    const up = new KeyboardEvent('keyup', { key: 'Control', bubbles: true });
    Object.defineProperty(up, 'target', { value: input });
    document.dispatchEvent(up);
    expect(end).toHaveBeenCalledTimes(1);
    input.remove();
  });

  it('a combo while Ctrl is held cancels the hold without transmitting', () => {
    const begin = vi.fn();
    const end = vi.fn();
    render(<Harness actions={baseActions({ voicePtt: { begin, end } })} />);
    fireEvent.keyDown(document, { key: 'Control' });
    expect(begin).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(document, { key: 'c', ctrlKey: true });
    expect(end).toHaveBeenCalledTimes(1);
  });
});

/**
 * PTT latch-leak regression (field bug: hold = violet, release stayed violet,
 * next press recovered). Drives real Ctrl keydown/keyup through the hook,
 * wired to the REAL voiceController singleton with the useVoiceAgent client
 * contract mirrored onto a controllable fake audio client.
 */
const ENABLED_REALTIME_STATUS: VoiceStatusResponse = {
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
  costDefaults: { warnUsd: 2, capUsd: 5, dailyBudgetUsd: 'off' },
  dailySpend: { date: '', usdSpent: 0, budgetUsd: 'off', remainingUsd: 'off', ledgerQuarantined: false },
  activeSessions: 0,
  maxConcurrent: 1,
};

describe('Ctrl PTT hold-release invariant (real controller)', () => {
  const stop = vi.fn();
  /** Fake VoiceAudioClient slot — stays 'connecting' unless a test moves it. */
  const clientRef: { current: { currentPhase: string; stop: (r: string) => void } | null } = {
    current: null,
  };

  function wirePtt(): Actions['voicePtt'] {
    return {
      // Mirrors the FIXED useVoiceAgent.beginPtt contract.
      begin: () => {
        const stale = clientRef.current;
        if (stale && stale.currentPhase !== 'idle') stale.stop('ptt_restart');
        clientRef.current = null;
        voiceController.beginPtt();
        clientRef.current = { currentPhase: 'connecting', stop };
      },
      // Mirrors the FIXED useVoiceAgent.endPtt contract: unconditional idle.
      end: () => {
        const client = clientRef.current;
        const hadHold =
          voiceController.getState().pttHeld || (client !== null && client.currentPhase !== 'idle');
        if (client && client.currentPhase !== 'idle') {
          client.stop('ptt_release');
          clientRef.current = null;
        }
        if (!hadHold) return;
        voiceController.endPtt(true);
        const phase = voiceController.getState().phase;
        if (phase !== 'idle' && phase !== 'quota-capped') voiceController.backToIdle();
      },
    };
  }

  beforeEach(() => {
    stop.mockClear();
    voiceController.resetForNewSession();
    voiceController.resetTranscript();
    voiceController.applyStatus(ENABLED_REALTIME_STATUS);
  });

  afterEach(() => {
    voiceController.resetForNewSession();
  });

  it('hold → violet LINK, release → teal idle, every time', () => {
    render(<Harness actions={baseActions({ voicePtt: wirePtt() })} />);
    for (let round = 0; round < 3; round++) {
      fireEvent.keyDown(document, { key: 'Control' });
      expect(voiceController.getState().pttHeld, `round ${round} hold`).toBe(true);
      expect(voiceController.getState().phase, `round ${round} phase`).toBe('connecting');
      fireEvent.keyUp(document, { key: 'Control' });
      expect(voiceController.getState().pttHeld, `round ${round} release pttHeld`).toBe(false);
      expect(voiceController.getState().phase, `round ${round} release phase`).toBe('idle');
    }
  });

  it('begin→(client stuck connecting)→end→begin→end twice: idle after every keyup', () => {
    render(<Harness actions={baseActions({ voicePtt: wirePtt() })} />);
    for (let round = 0; round < 2; round++) {
      fireEvent.keyDown(document, { key: 'Control' }); // begin — client stuck connecting
      expect(clientRef.current?.currentPhase).toBe('connecting');
      expect(stop).not.toHaveBeenCalled(); // fresh session opened, none torn down
      fireEvent.keyUp(document, { key: 'Control' }); // end
      expect(stop).toHaveBeenCalledWith('ptt_release');
      expect(voiceController.getState().pttHeld).toBe(false);
      expect(voiceController.getState().phase).toBe('idle');
      stop.mockClear();
    }
  });

  it('a latched dead hold does not swallow the next Ctrl press', () => {
    render(<Harness actions={baseActions({ voicePtt: wirePtt() })} />);
    fireEvent.keyDown(document, { key: 'Control' });
    fireEvent.keyDown(document, { key: 'c', ctrlKey: true }); // combo cancels via end
    expect(voiceController.getState().pttHeld).toBe(false);
    expect(voiceController.getState().phase).toBe('idle');
    fireEvent.keyUp(document, { key: 'Control' }); // stray keyup after combo
    fireEvent.keyDown(document, { key: 'Control' }); // next press must still work
    expect(voiceController.getState().pttHeld).toBe(true);
    expect(voiceController.getState().phase).toBe('connecting');
    fireEvent.keyUp(document, { key: 'Control' });
    expect(voiceController.getState().pttHeld).toBe(false);
    expect(voiceController.getState().phase).toBe('idle');
  });
});
