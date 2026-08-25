/**
 * useVoiceAgent — React binding for the voice console (voice-agent plan §5.6).
 *
 * Subscribes to the framework-free `voiceController` singleton via
 * useSyncExternalStore (same pattern as useDataStore), polls GET /api/voice/
 * status at a rate under its 10/min limiter, and drives the deterministic
 * zero-model loop (§3.7) from typed composer text. Realtime session lifecycle
 * and tool-frame correlation over the voice WebSocket land with U5/U8; this
 * hook is their single wiring point.
 */
import { useCallback, useEffect, useRef, useSyncExternalStore } from 'react';
import { API_BASE } from '@/lib/api';
import { voiceController, type VoiceControllerState } from '@/lib/voiceController';
import { runDeterministicTurn } from '@/lib/voiceDeterministic';
import { useVoiceGrounding } from '@/hooks/useVoiceGrounding';
import type { ClientToolContext } from '@/lib/clientTools';
import type { VoiceStatusResponse } from '@/lib/voiceTypes';

export type VoiceAgentBindings = ClientToolContext;

export interface UseVoiceAgentResult {
  state: VoiceControllerState;
  submitText: (text: string) => Promise<void>;
  beginPtt: () => void;
  endPtt: () => void;
  cancelActive: () => void;
  openPanel: () => void;
  closePanel: () => void;
}

const STATUS_POLL_MS = 60000;

export function useVoiceAgent(bindings: VoiceAgentBindings): UseVoiceAgentResult {
  const state = useSyncExternalStore(voiceController.subscribe, voiceController.getState);

  // U5 NARRATE grounding composer — ambient briefs, ARM gating, freshness
  // strip state (flows through voiceController into VoiceHudPanel). Its
  // requestBrief surface becomes user-reachable with U6's interrogation UX.
  useVoiceGrounding(bindings);

  // Keep the latest page bindings without resubscribing effects per render.
  const bindingsRef = useRef(bindings);
  bindingsRef.current = bindings;

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
    if (!trimmed) return;
    voiceController.pushTurn({ role: 'operator', kind: 'text', text: trimmed.slice(0, 500) });
    try {
      const outcome = await runDeterministicTurn(trimmed, bindingsRef.current);
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
    } catch (err) {
      // Verbatim honesty: render the real error string, never a fabricated success.
      voiceController.pushTurn({
        role: 'agent',
        kind: 'text',
        text: err instanceof Error && err.message ? err.message : 'console loop failed',
      });
    }
  }, []);

  const beginPtt = useCallback(() => voiceController.beginPtt(), []);
  const endPtt = useCallback(() => voiceController.endPtt(), []);
  const cancelActive = useCallback(() => voiceController.escape(), []);
  const openPanel = useCallback(() => voiceController.setPanelOpen(true), []);
  const closePanel = useCallback(() => voiceController.setPanelOpen(false), []);

  return { state, submitText, beginPtt, endPtt, cancelActive, openPanel, closePanel };
}
