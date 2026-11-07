/**
 * voiceSpeech — local TTS output + the honest AUDIO → SYNTH → TEXT ladder
 * (voice-agent plan §2.7 / §1.4 rule 5, U5).
 *
 * Baseline output is `window.speechSynthesis` using ON-DEVICE/system voices
 * only (rate 1.05 / pitch 0.95). If only remote-quality voices are enumerated,
 * the UI discloses and stays silent (TEXT) — we never route narration text to
 * a cloud voice. One shared utterance queue; barge-in ducks playback.
 * Framework-free singleton so the controller and tests can drive it directly.
 */

export type VoiceLadderMode = 'AUDIO' | 'SYNTH' | 'TEXT';

export interface VoiceSpeechState {
  /** Current rung of the honest degradation ladder. */
  mode: VoiceLadderMode;
  /** Verbatim reason when TEXT was forced (no local voices / no synthesis). */
  reason: string | null;
  speaking: boolean;
}

const RATE = 1.05;
const PITCH = 0.95;

class VoiceSpeech {
  private state: VoiceSpeechState = { mode: 'TEXT', reason: 'not probed yet', speaking: false };
  private listeners = new Set<() => void>();
  private queue: string[] = [];
  private current: SpeechSynthesisUtterance | null = null;

  subscribe = (fn: () => void): (() => void) => {
    this.listeners.add(fn);
    return () => {
      this.listeners.delete(fn);
    };
  };

  getState = (): VoiceSpeechState => this.state;

  private set(patch: Partial<VoiceSpeechState>): void {
    this.state = { ...this.state, ...patch };
    for (const fn of this.listeners) fn();
  }

  /** Probe on-device voices once (deferred: Chrome populates voices async). */
  probe(): void {
    if (typeof window === 'undefined' || !('speechSynthesis' in window)) {
      this.set({ mode: 'TEXT', reason: 'speechSynthesis unavailable in this shell' });
      return;
    }
    const pick = (): void => {
      const voices = window.speechSynthesis.getVoices();
      const local = voices.filter((v) => v.localService);
      if (local.length > 0) {
        this.set({ mode: 'SYNTH', reason: null });
      } else if (voices.length > 0) {
        // Remote-quality voices only → disclose and stay silent (§1.4 rule 5).
        this.set({ mode: 'TEXT', reason: 'only remote-quality voices available — staying silent' });
      } else {
        this.set({ mode: 'TEXT', reason: 'no system voices enumerated' });
      }
    };
    pick();
    window.speechSynthesis.onvoiceschanged = () => pick();
  }

  /** Enqueue one narrated sentence. No-op unless the ladder reached SYNTH. */
  say(text: string): void {
    if (this.state.mode !== 'SYNTH') return;
    const trimmed = String(text ?? '').trim();
    if (!trimmed) return;
    this.queue.push(trimmed.slice(0, 600));
    this.drain();
  }

  private drain(): void {
    if (typeof window === 'undefined' || !('speechSynthesis' in window)) return;
    if (this.current) return;
    const next = this.queue.shift();
    if (!next) {
      this.set({ speaking: false });
      return;
    }
    const utterance = new SpeechSynthesisUtterance(next);
    utterance.rate = RATE;
    utterance.pitch = PITCH;
    const local = window.speechSynthesis.getVoices().find((v) => v.localService);
    if (local) utterance.voice = local;
    utterance.onend = () => {
      this.current = null;
      this.drain();
    };
    utterance.onerror = () => {
      this.current = null;
      this.drain();
    };
    this.current = utterance;
    this.set({ speaking: true });
    try {
      window.speechSynthesis.speak(utterance);
    } catch {
      this.current = null;
      this.set({ mode: 'TEXT', reason: 'speechSynthesis.speak failed', speaking: false });
    }
  }

  /** Barge-in: duck playback by flushing the pending queue. */
  duck(): void {
    this.queue = [];
  }

  cancel(): void {
    this.queue = [];
    if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
      try {
        window.speechSynthesis.cancel();
      } catch {
        // never wedge the console on teardown
      }
    }
    this.current = null;
    this.set({ speaking: false });
  }
}

export const voiceSpeech = new VoiceSpeech();
