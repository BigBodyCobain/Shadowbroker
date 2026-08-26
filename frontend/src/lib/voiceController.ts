/**
 * voiceController — framework-free singleton state machine for the voice
 * console (voice-agent plan §5.2). Ported from the GEV STATUS enum extended
 * with policy states; transitions live only here so they are unit-testable.
 *
 * Carried GEV behaviors:
 *  - disconnect grace: VOICE_DISCONNECT_GRACE_MS (6 s) must elapse before a
 *    transport blip becomes an `error` — short WebRTC drops recover;
 *  - monotonic cost latching: `level` never steps down, and cap closes the
 *    session through the normal stop path into `quota-capped`;
 *  - window blur force-releases a stuck push-to-talk.
 */
import type { VoicePhase, VoiceStatusResponse, VoiceTurn, VoiceUsageEvent } from './voiceTypes';

export const VOICE_DISCONNECT_GRACE_MS = 6000;

export interface VoiceNarration {
  summary: string;
  generatedAt: number;
  /** Verbatim upstream failure reason; null while the last brief is good. */
  error: string | null;
}

/** Freshness-strip row (VoiceHudPanel NARRATE provenance, §5.3). */
export interface FreshnessRow {
  layer: string;
  disposition: 'live' | 'aging' | 'stale' | 'unknown';
  age_s: number | null;
}

export interface VoiceControllerState {
  phase: VoicePhase;
  pttHeld: boolean;
  panelOpen: boolean;
  turns: VoiceTurn[];
  cost: VoiceUsageEvent | null;
  /** Text-only/deterministic mode → corner badge TXT + mic routes to composer. */
  degraded: boolean;
  modelLabel: string;
  /** Verbatim status reasons for the dimmed-state tooltip. */
  reasons: string[];
  /** Incremented to ask the panel composer to take focus (mic routing). */
  composerFocusNonce: number;
  /** Latest NARRATE brief (U5) — hold-last-good on regen failure. */
  narration: VoiceNarration | null;
  narrating: boolean;
  /** Per-layer freshness strip backing the NARRATE block. */
  freshnessRows: FreshnessRow[];
  /** Ambient auto-narration ARM toggle — per-page-session, default OFF. */
  ambientArmed: boolean;
  /** Today's persisted daily-spend view from /api/voice/status (§4.3) —
   *  backs the spend chip in VoiceHudPanel (U6). */
  dailySpend: VoiceStatusResponse['dailySpend'] | null;
  /** Verbatim reason for the current FAULT (upstream close text, budget
   *  refusal detail, transport error) — rendered as-is, never softened. */
  lastFaultReason: string | null;
  /** Resolved provider id from the last status poll (U8): realtime-capable
   *  providers ('openai_realtime'|'compatible_ws') gate PTT audio capture. */
  providerResolved: string | null;
}

/**
 * Legal phase transition matrix. Every transition not listed here is illegal
 * and is ignored by the controller (test #31 walks both sets).
 */
const LEGAL_TRANSITIONS: Record<VoicePhase, ReadonlyArray<VoicePhase>> = {
  'opt-in-required': ['idle', 'lean-unavailable'],
  'lean-unavailable': ['idle', 'opt-in-required'],
  idle: ['connecting', 'listening', 'error', 'quota-capped', 'opt-in-required', 'lean-unavailable'],
  connecting: ['listening', 'thinking', 'idle', 'error', 'quota-capped'],
  listening: ['connecting', 'thinking', 'speaking', 'idle', 'error', 'quota-capped'],
  thinking: ['speaking', 'listening', 'idle', 'error', 'quota-capped'],
  speaking: ['listening', 'thinking', 'idle', 'error', 'quota-capped'],
  error: ['idle', 'connecting', 'opt-in-required', 'lean-unavailable', 'quota-capped'],
  'quota-capped': ['idle'],
};

const INITIAL_STATE: VoiceControllerState = {
  phase: 'opt-in-required',
  pttHeld: false,
  panelOpen: false,
  turns: [],
  cost: null,
  degraded: true,
  modelLabel: '',
  reasons: [],
  composerFocusNonce: 0,
  narration: null,
  narrating: false,
  freshnessRows: [],
  ambientArmed: false,
  dailySpend: null,
  lastFaultReason: null,
  providerResolved: null,
};

const MAX_TURNS = 200;
const NARRATION_ROWS_MAX = 22;
export const ARM_STORAGE_KEY = 'sb_voice_ambient_armed_v1';

let turnSeq = 0;

function canTransition(from: VoicePhase, to: VoicePhase): boolean {
  return from === to || LEGAL_TRANSITIONS[from].includes(to);
}

class VoiceController {
  private state: VoiceControllerState = INITIAL_STATE;
  private listeners = new Set<() => void>();
  private graceTimer: ReturnType<typeof setTimeout> | null = null;
  private blurBound = false;

  subscribe = (fn: () => void): (() => void) => {
    this.listeners.add(fn);
    this.bindBlurGuard();
    return () => {
      this.listeners.delete(fn);
    };
  };

  getState = (): VoiceControllerState => this.state;

  private set(patch: Partial<VoiceControllerState>): void {
    this.state = { ...this.state, ...patch };
    for (const fn of this.listeners) fn();
  }

  private setPhase(phase: VoicePhase): boolean {
    if (!canTransition(this.state.phase, phase)) return false;
    if (phase === 'error' || phase === 'idle') this.clearGrace();
    this.set({ phase });
    return true;
  }

  /** Exposed for tests / callers that need the legality predicate. */
  canGo(phase: VoicePhase): boolean {
    return canTransition(this.state.phase, phase);
  }

  // ── Status intake ────────────────────────────────────────────────────────

  /** Derive policy phases exclusively from the server's status response. */
  applyStatus(status: VoiceStatusResponse): void {
    this.set({
      reasons: Array.isArray(status.reasons) ? status.reasons.slice(0, 4) : [],
      // Text-only providers (local chat endpoints and Anthropic's Claude —
      // which has no realtime speech API) keep the console in degraded
      // text mode: TXT badge, mic routes to the composer, no audio session.
      degraded:
        !status.effectiveEnable ||
        status.provider.resolved === null ||
        status.provider.resolved === 'local_text' ||
        status.provider.resolved === 'anthropic_text',
      providerResolved: status.provider.resolved ?? null,
      modelLabel:
        status.mode === 'mesh_lean'
          ? ''
          : status.provider.resolved
            ? String(status.provider.resolved)
            : '',
      dailySpend: status.dailySpend ?? null,
    });
    if (this.state.phase === 'quota-capped') return; // terminal until explicit reset
    if (status.mode === 'mesh_lean') {
      this.setPhase('lean-unavailable');
      return;
    }
    if (!status.effectiveEnable) {
      this.setPhase('opt-in-required');
      return;
    }
    // Enabled: leave any policy state.
    if (
      this.state.phase === 'opt-in-required' ||
      this.state.phase === 'lean-unavailable' ||
      this.state.phase === 'error'
    ) {
      this.setPhase('idle');
    }
  }

  // ── Push-to-talk ────────────────────────────────────────────────────────

  beginPtt(): void {
    // A dead hold can leave pttHeld latched while the UI shows LINK
    // (connecting) — e.g. a release path that stopped only the audio client.
    // A fresh keydown must never be swallowed: recover the stale latch and
    // let the new hold proceed. Healthy holds (listening/speaking) still
    // early-return so an active hold is not double-begun.
    if (this.state.pttHeld) {
      if (this.state.phase !== 'connecting') return;
      this.set({ pttHeld: false });
    }
    if (
      this.state.phase === 'opt-in-required' ||
      this.state.phase === 'lean-unavailable' ||
      this.state.phase === 'quota-capped'
    ) {
      return;
    }
    // Barge-in: holding V while speaking ducks playback and starts the next turn.
    this.clearGrace();
    this.set({ pttHeld: true });
    if (this.state.phase !== 'listening') {
      if (this.canGo('connecting')) this.set({ phase: 'connecting' });
    }
  }

  endPtt(force = false): void {
    if (!this.state.pttHeld && !force) return;
    this.set({ pttHeld: false });
    if (this.state.phase === 'connecting' || this.state.phase === 'listening') {
      // U4 deterministic/text mode has no capture pipeline yet — release back
      // to idle honestly instead of pretending a turn was captured.
      this.setPhase('idle');
    }
  }

  /** Escape cancels open mic or aborts a thinking turn (recorded honestly). */
  escape(): void {
    if (this.state.pttHeld) this.endPtt(true);
    else if (this.state.phase === 'thinking') this.setPhase('idle');
  }

  // ── Turn lifecycle ──────────────────────────────────────────────────────

  beginThinking(): boolean {
    return this.setPhase('thinking');
  }

  markListening(): boolean {
    return this.setPhase('listening');
  }

  markSpeaking(): boolean {
    return this.setPhase('speaking');
  }

  backToIdle(): boolean {
    return this.setPhase('idle');
  }

  fail(message: string): void {
    const reason = String(message ?? '').trim();
    if (reason) this.set({ lastFaultReason: reason.slice(0, 300) });
    const wasSet = this.setPhase('error');
    if (wasSet || this.state.phase === 'error') {
      this.pushTurn({
        id: `t${++turnSeq}`,
        role: 'agent',
        kind: 'text',
        text: reason || 'link fault',
        ts: Date.now(),
      });
    }
  }

  /** Transport lost — start the disconnect grace window. The verbatim
   *  close/error reason becomes the FAULT text if the blip does not recover. */
  markDisconnected(reason?: string): void {
    this.clearGrace();
    if (reason && String(reason).trim()) this.set({ lastFaultReason: String(reason).trim().slice(0, 300) });
    if (this.state.phase === 'quota-capped' || this.state.phase === 'error') return;
    this.graceTimer = setTimeout(() => {
      this.graceTimer = null;
      this.setPhase('error');
      const fault = this.state.lastFaultReason;
      if (fault) {
        this.pushTurn({ id: `t${++turnSeq}`, role: 'agent', kind: 'text', text: fault, ts: Date.now() });
      }
    }, VOICE_DISCONNECT_GRACE_MS);
  }

  /** Transport recovered inside the grace window (or a new session started). */
  markConnected(): void {
    this.clearGrace();
    this.set({ lastFaultReason: null });
    if (this.state.phase === 'error') this.setPhase('idle');
  }

  private clearGrace(): void {
    if (this.graceTimer) {
      clearTimeout(this.graceTimer);
      this.graceTimer = null;
    }
  }

  // ── Cost latch (monotonic) ──────────────────────────────────────────────

  applyCost(event: Pick<VoiceUsageEvent, 'total_usd' | 'display' | 'level' | 'note'> & Partial<Pick<VoiceUsageEvent, 'incomplete' | 'estimated' | 'ratesRecognized'>>): void {
    const prev = this.state.cost;
    // Level never steps down.
    const rank = { ok: 0, warn: 1, cap: 2 } as const;
    const level = prev && rank[event.level] < rank[prev.level] ? prev.level : event.level;
    const next: VoiceUsageEvent = { ...event, level };
    this.set({ cost: next });
    if (level === 'cap') {
      this.clearGrace();
      this.endPtt(true);
      if (this.state.phase !== 'quota-capped') this.setPhase('quota-capped');
    }
  }

  /** Explicit new session after a cap — the only way out of quota-capped. */
  resetForNewSession(): void {
    this.clearGrace();
    this.set({ cost: null, pttHeld: false, lastFaultReason: null });
    if (this.state.phase === 'quota-capped' || this.state.phase === 'error') this.setPhase('idle');
  }

  // ── Transcript & panel ──────────────────────────────────────────────────

  pushTurn(turn: Omit<VoiceTurn, 'id' | 'ts'> & { id?: string; ts?: number }): VoiceTurn {
    const full: VoiceTurn = {
      id: turn.id ?? `t${++turnSeq}`,
      ts: turn.ts ?? Date.now(),
      role: turn.role,
      kind: turn.kind,
      text: turn.text,
      ...(turn.tool ? { tool: turn.tool } : {}),
    };
    const turns = [...this.state.turns, full];
    this.set({ turns: turns.length > MAX_TURNS ? turns.slice(turns.length - MAX_TURNS) : turns });
    return full;
  }

  setPanelOpen(open: boolean): void {
    this.set({ panelOpen: open });
  }

  // ── NARRATE / grounding (U5) ─────────────────────────────────────────────

  setNarration(narration: VoiceNarration | null): void {
    this.set({ narration, narrating: false });
  }

  setNarrating(narrating: boolean): void {
    if (this.state.narrating === narrating) return;
    this.set({ narrating });
  }

  setFreshnessRows(rows: FreshnessRow[]): void {
    this.set({ freshnessRows: rows.slice(0, NARRATION_ROWS_MAX) });
  }

  /** Ambient ARM is a per-page-session switch persisted in sessionStorage
   *  (default OFF — disarmed ⇒ zero hud-summary calls, §2.6/#41). */
  setAmbientArmed(armed: boolean): void {
    try {
      if (typeof sessionStorage !== 'undefined') {
        if (armed) sessionStorage.setItem(ARM_STORAGE_KEY, '1');
        else sessionStorage.removeItem(ARM_STORAGE_KEY);
      }
    } catch {
      // storage unavailable (privacy mode) — session-only state still applies
    }
    this.set({ ambientArmed: armed });
  }

  /** Restore the ARM toggle from sessionStorage at mount time. */
  loadAmbientArm(): void {
    let armed = false;
    try {
      armed = typeof sessionStorage !== 'undefined' && sessionStorage.getItem(ARM_STORAGE_KEY) === '1';
    } catch {
      armed = false;
    }
    this.set({ ambientArmed: armed });
  }

  requestComposerFocus(): void {
    this.set({ composerFocusNonce: this.state.composerFocusNonce + 1 });
  }

  resetTranscript(): void {
    this.set({ turns: [] });
  }

  // ── Blur guard ──────────────────────────────────────────────────────────

  private bindBlurGuard(): void {
    if (this.blurBound || typeof window === 'undefined') return;
    this.blurBound = true;
    window.addEventListener('blur', () => {
      // Force-release a stuck PTT when the window loses focus.
      if (this.state.pttHeld) this.endPtt(true);
    });
  }
}

export const voiceController = new VoiceController();

/** Pure transition-legality helper (test surface for the full matrix). */
export function isLegalTransition(from: VoicePhase, to: VoicePhase): boolean {
  return canTransition(from, to);
}
