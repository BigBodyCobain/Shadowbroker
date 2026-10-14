/**
 * useVoiceAgent — React binding for the voice console (voice-agent plan §5.6).
 *
 * Subscribes to the framework-free `voiceController` singleton via
 * useSyncExternalStore (same pattern as useDataStore), polls GET /api/voice/
 * status at a rate under its 10/min limiter, and drives the deterministic
 * zero-model loop (§3.7) from typed composer text. U8: when the provider is
 * realtime-capable, each PTT hold opens a VoiceAudioClient session — mic
 * PCM16 → broker relay → provider audio playback — with barge-in flush on
 * the server-VAD speech_started signal.
 */
import { useCallback, useEffect, useRef, useSyncExternalStore } from 'react';
import { API_BASE } from '@/lib/api';
import { voiceController, type VoiceControllerState } from '@/lib/voiceController';
import { runDeterministicTurn } from '@/lib/voiceDeterministic';
import { voiceSpeech } from '@/lib/voiceSpeech';
import { VoiceAudioClient, type VoiceAudioPhase } from '@/lib/voiceAudioClient';
import { useVoiceGrounding } from '@/hooks/useVoiceGrounding';
import type { ClientToolContext } from '@/lib/clientTools';
import type { VoiceStatusResponse } from '@/lib/voiceTypes';

export type VoiceAgentBindings = ClientToolContext & {
  /** §2.6 selectedEntity regen trigger (U6): the page-local selection rides
   *  the widened page→hook bindings; only its identity is read. */
  selectedEntity?: { id: string | number; type: string } | null;
};

export interface UseVoiceAgentResult {
  state: VoiceControllerState;
  submitText: (text: string) => Promise<void>;
  beginPtt: () => void;
  endPtt: () => void;
  cancelActive: () => void;
  openPanel: () => void;
  closePanel: () => void;
  /** Manual "BRIEF NOW" — explicit operator request bypassing only the ARM
   *  switch (§2.6); surfaced for the VoiceHudPanel affordance (U6). */
  requestBrief: () => void;
}

const STATUS_POLL_MS = 60000;

/** Providers that speak the §4.3 realtime wire protocol (binary PCM16 relay). */
export function isRealtimeProvider(resolved: string | null | undefined): boolean {
  return resolved === 'openai_realtime' || resolved === 'compatible_ws' || resolved === 'gemini_live';
}

/** Broker cost snapshot → controller applyCost shape (defensive mapping). */
function costFromFrame(frame: Record<string, unknown>, level: 'ok' | 'warn' | 'cap') {
  const snap = (frame.snapshot ?? frame) as Record<string, unknown>;
  const total = Number(snap.totalUsd ?? snap.total_usd ?? 0);
  const display = typeof snap.display === 'string' ? snap.display : `~$${total.toFixed(2)}`;
  voiceController.applyCost({ total_usd: total, display, level, note: null });
}

export function useVoiceAgent(bindings: VoiceAgentBindings): UseVoiceAgentResult {
  const state = useSyncExternalStore(voiceController.subscribe, voiceController.getState, voiceController.getState);

  // U5 NARRATE grounding composer — ambient briefs, ARM gating, freshness
  // strip state (flows through voiceController into VoiceHudPanel). U6 makes
  // its requestBrief surface user-reachable ("BRIEF NOW") and feeds it the
  // page-local selectedEntity for the §2.6 regen trigger.
  const grounding = useVoiceGrounding(bindings);
  const groundingRef = useRef(grounding);
  groundingRef.current = grounding;

  // Keep the latest page bindings without resubscribing effects per render.
  const bindingsRef = useRef(bindings);
  bindingsRef.current = bindings;

  // U8 realtime speech-to-speech: one audio session per PTT hold. The client
  // is controller-free (testable); this hook is its single wiring point.
  const audioClientRef = useRef<VoiceAudioClient | null>(null);
  const textRequestRef = useRef<AbortController | null>(null);
  useEffect(() => () => textRequestRef.current?.abort(), []);

  const realtimeActive = isRealtimeProvider(state.providerResolved);

  const beginPtt = useCallback(() => {
    // A fresh keydown always wins: any previous client is torn down and its
    // ref cleared BEFORE the new hold opens — a stale ref in any phase must
    // never block or swallow a new session.
    const stale = audioClientRef.current;
    if (stale && stale.currentPhase !== 'idle') stale.stop('ptt_restart');
    audioClientRef.current = null;
    voiceController.beginPtt();
    if (!realtimeActive) return;
    // Barge-in path: a fresh hold while the agent is speaking starts a new
    // session; the client flushes stale playback on speech_started/cap.
    const client = new VoiceAudioClient({
      onPhase: (phase: VoiceAudioPhase) => {
        if (phase === 'listening') voiceController.markListening();
        else if (phase === 'speaking') voiceController.markSpeaking();
        // An async teardown reaching idle must never yank an ACTIVE hold out
        // of its phase — only settle the console when nothing is held.
        else if (phase === 'idle' && !voiceController.getState().pttHeld) voiceController.backToIdle();
      },
      onFault: (reason) => voiceController.fail(reason),
      onFrame: (frame) => {
        const type = String(frame.type ?? '');
        if (type === 'cost') costFromFrame(frame, 'ok');
        else if (type === 'warn') costFromFrame(frame, 'warn');
        else if (type === 'cap') {
          costFromFrame(frame, 'cap');
          voiceController.applyCost({
            total_usd: Number((frame.snapshot as Record<string, unknown>)?.totalUsd ?? 0),
            display: `$${String(frame.totalUsd ?? '')} CAP`,
            level: 'cap',
            note: typeof frame.reason === 'string' ? frame.reason : null,
          });
        }
      },
    });
    audioClientRef.current = client;
    void client.start().then(() => {
      // Clear only if this client is still the live one — a newer hold may
      // have replaced it while start() was settling.
      if (client.currentPhase === 'idle' && audioClientRef.current === client) {
        audioClientRef.current = null;
      }
    });
  }, [realtimeActive]);

  const endPtt = useCallback(() => {
    const client = audioClientRef.current;
    const hadHold =
      voiceController.getState().pttHeld || (client !== null && client.currentPhase !== 'idle');
    if (client && client.currentPhase !== 'idle') {
      // §4.3 stop frame = honest relay termination; teardown returns to idle.
      client.stop('ptt_release');
      audioClientRef.current = null;
    }
    // Invariant: after a real hold's release the console ALWAYS lands at
    // idle within this call — endPtt(force) clears pttHeld even when the
    // client branch already ran (the leak that turned PTT into a toggle),
    // and any residual session phase falls back to idle. quota-capped stays
    // terminal by design ("until explicit reset"). Stray keyups/blurs with
    // no hold and no client change nothing.
    if (!hadHold) return;
    voiceController.endPtt(true);
    const phase = voiceController.getState().phase;
    if (phase !== 'idle' && phase !== 'quota-capped') voiceController.backToIdle();
  }, []);

  useEffect(() => {
    let cancelled = false;
    const refresh = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/voice/status`);
        if (!res.ok) return;
        const json = (await res.json()) as VoiceStatusResponse;
        if (!cancelled && json?.ok) voiceController.applyStatus(json);
      } catch {
        // Status never wedges the console — the button keeps its last honest
        // phase (fresh installs stay dimmed opt-in-required until reachable).
      }
    };
    void refresh();
    const id = setInterval(refresh, STATUS_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  const submitText = useCallback(async (text: string) => {
    const trimmed = String(text ?? '').trim();
    if (!trimmed || textRequestRef.current) return;
    const request = new AbortController();
    textRequestRef.current = request;
    voiceController.beginThinking();
    voiceController.pushTurn({ role: 'operator', kind: 'text', text: trimmed.slice(0, 500) });
    try {
      const outcome = await runDeterministicTurn(trimmed, bindingsRef.current, request.signal, () => groundingRef.current.composeSnapshot());
      if (request.signal.aborted) return;
      for (const step of outcome.steps) {
        voiceController.pushTurn({
          role: 'agent',
          kind: 'tool',
          text: step.tool ?? 'tool',
          ...(step.tool
            ? {
                tool: {
                  name: step.tool,
                  args_summary: step.argsSummary,
                  ok: step.ok,
                  detail: step.detail,
                },
              }
            : {}),
        });
      }
      voiceController.pushTurn({ role: 'agent', kind: 'text', text: outcome.reply });
      if (voiceController.getState().readReplies) {
        voiceSpeech.probe();
        voiceSpeech.say(outcome.reply);
      }
    } catch (err) {
      if (request.signal.aborted) return;
      // Verbatim honesty: render the real error string, never a fabricated success.
      voiceController.pushTurn({
        role: 'agent',
        kind: 'text',
        text: err instanceof Error && err.message ? err.message : 'console loop failed',
      });
    } finally {
      if (textRequestRef.current === request) {
        textRequestRef.current = null;
        const latest = voiceController.getState();
        if (!latest.pttHeld && latest.phase === 'thinking') voiceController.backToIdle();
      }
    }
  }, []);

  const cancelActive = useCallback(() => {
    textRequestRef.current?.abort();
    textRequestRef.current = null;
    // Esc cancels an open mic or aborts a thinking turn — an active audio
    // session is terminated the same honest way as a PTT release.
    const client = audioClientRef.current;
    if (client && client.currentPhase !== 'idle') {
      client.stop('operator_cancel');
      audioClientRef.current = null;
    }
    voiceController.escape();
  }, []);
  const openPanel = useCallback(() => voiceController.setPanelOpen(true), []);
  const closePanel = useCallback(() => voiceController.setPanelOpen(false), []);

  return { state, submitText, beginPtt, endPtt, cancelActive, openPanel, closePanel, requestBrief: grounding.requestBrief };
}
