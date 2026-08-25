/**
 * U6 — §2.6 selectedEntity regen trigger (carried over from U5's handoff):
 * selection is page-local React state, so the widened page→hook bindings
 * carry it into useVoiceGrounding; a selection change re-arms the SAME gated
 * pipeline and rides the snapshot (`selection`) so the fingerprint changes.
 *
 * Asserts the §2.6/#41 contract end-to-end at the hook level: every gate runs
 * BEFORE any network call — disarmed ⇒ zero hud-summary POSTs — and a real
 * selection change posts exactly once per change once armed.
 */
import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  REGEN_DEBOUNCE_MS_FOR_TESTS,
  REGEN_MIN_INTERVAL_MS,
  useVoiceGrounding,
  resetHealthCacheForTests,
} from '@/hooks/useVoiceGrounding';
import { voiceController } from '@/lib/voiceController';
import type { ClientToolContext } from '@/lib/clientTools';
import type { VoiceAgentBindings } from '@/hooks/useVoiceAgent';
import type { VoiceStatusResponse } from '@/lib/voiceTypes';

vi.mock('@/lib/mapControlBus', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/mapControlBus')>();
  return {
    ...actual,
    send: vi.fn(async () => ({ ok: true, view: { zoom: 6 } })),
    onViewState: vi.fn(() => () => {}),
  };
});

const ENABLED_STATUS: VoiceStatusResponse = {
  ok: true,
  effectiveEnable: true,
  opt_in_state: 'enabled',
  flags: { enableSet: true, acknowledgeSet: true },
  provider: {
    resolved: 'local_text',
    requestedMode: 'auto',
    openaiKeySet: false,
    compatKeySet: false,
    compatBaseUrlSet: false,
    chatModelConfigured: true,
  },
  degradedReason: null,
  reasons: [],
  mode: 'full',
  costDefaults: { warnUsd: 'off', capUsd: 'off', dailyBudgetUsd: 'off' },
  dailySpend: { date: '', usdSpent: 0, budgetUsd: 'off', remainingUsd: 'off', ledgerQuarantined: false },
  activeSessions: 0,
  maxConcurrent: 1,
};

function makeBindings(selectedEntity: { id: string; type: string } | null): VoiceAgentBindings {
  return {
    flyTo: vi.fn(),
    toggleLayer: vi.fn(() => true),
    applyMapStyle: vi.fn((s) => s),
    setFilter: vi.fn(),
    setSelectedEntity: vi.fn(),
    viewSummary: () => ({ activeLayers: {}, filters: {} }),
    selectedEntity,
  } as unknown as ClientToolContext & VoiceAgentBindings;
}

describe('selectedEntity regen trigger (§2.6, U6)', () => {
  let hudPosts: number;

  beforeEach(() => {
    hudPosts = 0;
    vi.useFakeTimers();
    try {
      sessionStorage.clear();
    } catch {
      /* ignore */
    }
    voiceController.resetForNewSession();
    voiceController.resetTranscript();
    voiceController.applyStatus(ENABLED_STATUS);
    resetHealthCacheForTests();
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes('/api/voice/hud-summary')) {
          hudPosts += 1;
          return new Response(JSON.stringify({ ok: true, summary: `brief #${hudPosts}`, mode: 'full' }), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          });
        }
        if (url.includes('/api/ai/channel/command')) {
          return new Response(JSON.stringify({ data: {} }), { status: 200 });
        }
        throw new Error(`unexpected fetch ${url}`);
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
    cleanup();
  });

  it('disarmed ⇒ zero hud-summary POSTs even when the selection changes (#41)', async () => {
    const { rerender } = renderHook((props: VoiceAgentBindings) => useVoiceGrounding(props), {
      initialProps: makeBindings(null),
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(REGEN_DEBOUNCE_MS_FOR_TESTS + 500);
    });
    expect(hudPosts).toBe(0);

    rerender(makeBindings({ id: 'ae1f23', type: 'tracked_flights' }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(REGEN_DEBOUNCE_MS_FOR_TESTS + 500);
    });
    expect(hudPosts).toBe(0); // arm-gate blocks BEFORE any fetch
  });

  it('selection change re-arms regen once armed; each distinct selection posts once', async () => {
    const { rerender } = renderHook((props: VoiceAgentBindings) => useVoiceGrounding(props), {
      initialProps: makeBindings(null),
    });
    // Flush the mount-time schedule while disarmed.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(REGEN_DEBOUNCE_MS_FOR_TESTS + 500);
    });
    expect(hudPosts).toBe(0);

    voiceController.setAmbientArmed(true);
    rerender(makeBindings({ id: 'ae1f23', type: 'tracked_flights' }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(REGEN_DEBOUNCE_MS_FOR_TESTS + 500);
    });
    expect(hudPosts).toBe(1);

    // Same selection again ⇒ identical fingerprint + min-interval ⇒ no post.
    rerender(makeBindings({ id: 'ae1f23', type: 'tracked_flights' }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(REGEN_DEBOUNCE_MS_FOR_TESTS + 500);
    });
    expect(hudPosts).toBe(1);

    // A different selection changes the snapshot fingerprint; past the
    // min-interval it regenerates exactly once more.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(REGEN_MIN_INTERVAL_MS);
    });
    rerender(makeBindings({ id: '24b7ce', type: 'private_jets' }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(REGEN_DEBOUNCE_MS_FOR_TESTS + 500);
    });
    expect(hudPosts).toBe(2);
  });
});
