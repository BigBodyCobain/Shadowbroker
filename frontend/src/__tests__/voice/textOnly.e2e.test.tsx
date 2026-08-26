/**
 * U6 — text_only E2E (§6 U6 row; acceptance #38/#40 automated).
 *
 * Zero-realtime-model install (provider resolves to local_text): the console
 * is a first-class TEXT MODE surface — the mic button renders its dimmed TXT
 * state and routes pointer activation to the composer instead of mic capture
 * (unbrokered browser speech-to-text APIs are prohibited, §1.4), and typed
 * composer text drives the
 * deterministic loop end-to-end ("fly to Kyiv" → geocode → map_fly_to) with
 * no LLM path anywhere.
 */
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import VoiceMicButton from '@/components/VoiceMicButton';
import VoiceHudPanel from '@/components/VoiceHudPanel';
import { useVoiceAgent } from '@/hooks/useVoiceAgent';
import { voiceController } from '@/lib/voiceController';
import type { ClientToolContext } from '@/lib/clientTools';
import type { VoiceStatusResponse } from '@/lib/voiceTypes';

const LOCAL_TEXT_STATUS: VoiceStatusResponse = {
  ok: true,
  effectiveEnable: true,
  opt_in_state: 'enabled',
  flags: { enableSet: true, acknowledgeSet: true },
  provider: {
    resolved: 'local_text',
    requestedMode: 'auto',
    openaiKeySet: false,
    compatKeySet: false,
    compatBaseUrlSet: true,
  geminiKeySet: false,
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

/** Full console harness — the same wiring page.tsx uses (single mount point). */
function ConsoleHarness({ ctx }: { ctx: ClientToolContext }) {
  const voice = useVoiceAgent(ctx);
  return (
    <>
      <VoiceMicButton />
      {voice.state.panelOpen && (
        <VoiceHudPanel onSubmit={voice.submitText} onClose={voice.closePanel} onRequestBrief={voice.requestBrief} />
      )}
    </>
  );
}

describe('text_only E2E — zero realtime model, composer-only console', () => {
  const ctx: ClientToolContext = {
    flyTo: vi.fn(),
    toggleLayer: vi.fn(() => true),
    applyMapStyle: vi.fn((s) => s),
    setFilter: vi.fn(),
    setSelectedEntity: vi.fn(),
    viewSummary: () => ({ activeLayers: {}, filters: {} }),
  };

  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.includes('/api/voice/status')) {
          return new Response(JSON.stringify(LOCAL_TEXT_STATUS), { status: 200 });
        }
        if (url.includes('/api/geocode/search')) {
          expect(String(url)).toContain('Kyiv');
          return new Response(
            JSON.stringify({ results: [{ label: 'Kyiv, Ukraine', lat: 50.45, lng: 30.52 }] }),
            { status: 200 },
          );
        }
        throw new Error(`unexpected fetch ${url}`);
      }),
    );
  });

  afterEach(() => {
    voiceController.resetForNewSession();
    voiceController.resetTranscript();
    vi.unstubAllGlobals();
    cleanup();
  });

  it('mic routes to the composer (no capture path) and typed text flies the map', async () => {
    render(<ConsoleHarness ctx={ctx} />);

    // Status intake derives idle-but-degraded (local_text ⇒ TXT badge).
    const mic = screen.getByTestId('voice-mic-button').querySelector('button') as HTMLButtonElement;
    await screen.findByTestId('voice-txt-badge');

    // Click activation opens the console and routes to the composer — it
    // never begins a PTT capture (there is no brokered STT path).
    fireEvent.click(mic);
    expect(voiceController.getState().pttHeld).toBe(false);
    expect(voiceController.getState().phase).not.toBe('listening');
    const panel = screen.getByTestId('voice-hud-panel');
    expect(panel).toBeTruthy();

    // Typed text drives the identical deterministic pipeline end-to-end.
    const input = screen.getByRole('textbox') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'fly to Kyiv' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    // Flush the deterministic turn (geocode → map_fly_to → transcript).
    expect(await screen.findByText(/Flying to Kyiv, Ukraine\./)).toBeTruthy();
    expect(ctx.flyTo).toHaveBeenCalledWith(expect.objectContaining({ lat: 50.45, lng: 30.52 }));

    const transcript = screen.getByTestId('voice-transcript');
    // No tool row ever claims OK for a failed action — none failed here, but
    // the transcript must show the operator turn verbatim.
    expect(transcript.textContent).toContain('fly to Kyiv');
  });
});
