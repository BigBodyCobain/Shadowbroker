/**
 * voiceAudioClient — U8 realtime speech-to-speech session client (§4.3).
 *
 * Owns one realtime voice session end-to-end:
 *   POST /api/voice/session {mode:"realtime"} → one-time token
 *   → getUserMedia → AudioContext(24 kHz) → /worklets/voice-pcm-worklet.js
 *   → WebSocket /api/voice/session/ws?token&sessionId
 *   → mic PCM16 frames upstream · provider audio downstream → playback.
 *
 * Framework-free and infrastructure-injected (WebSocket / media / audio
 * factories) so vitest can drive the full state machine with fakes.
 * The controller/hook wiring stays in useVoiceAgent — this class never
 * imports voiceController.
 *
 * Barge-in: the upstream text stream is forwarded verbatim by the broker,
 * so `input_audio_buffer.speech_started` (server VAD) is the interruption
 * signal — on it we flush local playback immediately. `{"type":"stop"}`
 * is NOT used for barge-in: §4.3 defines it as relay termination.
 */
import {
  WIRE_SAMPLE_RATE,
  PcmBatcher,
  pcm16BytesToFloat32,
} from './voicePcm';
import { API_BASE } from './api';

export type VoiceAudioPhase = 'idle' | 'connecting' | 'listening' | 'speaking';

/** readyState === 1 — kept as a constant so tests need no global WebSocket. */
const WS_OPEN = 1;

export interface VoiceAudioEvents {
  onPhase?: (phase: VoiceAudioPhase) => void;
  /** Verbatim broker JSON frames (ready/cost/warn/cap/error/closed/watchdog_alert, upstream text). */
  onFrame?: (frame: Record<string, unknown>) => void;
  onFault?: (reason: string) => void;
}

/** Structural subsets the client actually touches — fakes satisfy these. */
export interface FakeableWebSocket {
  binaryType?: string;
  readyState: number;
  send(data: string | ArrayBuffer): void;
  close(code?: number, reason?: string): void;
  onopen: ((ev?: unknown) => void) | null;
  onmessage: ((ev: { data: unknown }) => void) | null;
  onclose: ((ev: { code: number; reason: string }) => void) | null;
  onerror: ((ev?: unknown) => void) | null;
}

export interface FakeableWorkletNode {
  port: { onmessage: ((ev: { data: unknown }) => void) | null; postMessage?(data: unknown): void };
  disconnect(): void;
}

export interface FakeableAudioContext {
  sampleRate: number;
  currentTime: number;
  destination: unknown;
  audioWorklet: { addModule(url: string): Promise<void> };
  createMediaStreamSource(stream: MediaStream): { connect(dest: unknown): void; disconnect(): void };
  createBuffer(channels: number, length: number, sampleRate: number): {
    copyToChannel(source: Float32Array, channel: number): void;
    duration: number;
  };
  createBufferSource(): {
    buffer: unknown;
    connect(dest: unknown): void;
    start(when?: number): void;
    stop(): void;
    onended: (() => void) | null;
  };
  close(): Promise<void>;
}

export interface VoiceAudioDeps {
  fetchImpl?: typeof fetch;
  WebSocketImpl?: new (url: string) => FakeableWebSocket;
  getUserMediaImpl?: () => Promise<MediaStream>;
  AudioContextImpl?: new (options?: { sampleRate: number }) => FakeableAudioContext;
  /** Builds the 'voice-pcm' AudioWorkletNode bound to the context. */
  createWorkletNode?: (ctx: FakeableAudioContext) => FakeableWorkletNode;
  workletUrl?: string;
}

interface SessionGrant {
  sessionId: string;
  token: string;
  wsPath: string;
  modelId?: string;
  resolvedProvider?: string;
}

const WORKLET_URL = '/worklets/voice-pcm-worklet.js';
/** 2400 samples = 100 ms at 24 kHz — inside the §4.3 20–100 ms cadence. */
const BATCH_SAMPLES = 2400;

/** Production worklet factory — global AudioWorkletNode, guarded for SSR. */
function defaultCreateWorkletNode(ctx: FakeableAudioContext): FakeableWorkletNode {
  const Ctor = (globalThis as {
    AudioWorkletNode?: new (ctx: unknown, name: string, opts?: unknown) => FakeableWorkletNode;
  }).AudioWorkletNode;
  if (!Ctor) throw new Error('AudioWorkletNode unavailable in this context');
  return new Ctor(ctx, 'voice-pcm');
}

export class VoiceAudioClient {
  private deps: VoiceAudioDeps & Required<Pick<VoiceAudioDeps, 'fetchImpl' | 'WebSocketImpl' | 'createWorkletNode'>>;
  private events: VoiceAudioEvents;

  private ws: FakeableWebSocket | null = null;
  private audioContext: FakeableAudioContext | null = null;
  private mediaStream: MediaStream | null = null;
  private workletNode: FakeableWorkletNode | null = null;
  private sourceNode: { connect(dest: unknown): void; disconnect(): void } | null = null;

  private batcher = new PcmBatcher(BATCH_SAMPLES);
  private playbackQueue: { stop(): void; onended: (() => void) | null }[] = [];
  private playbackTime = 0;
  private phase: VoiceAudioPhase = 'idle';
  private sessionId: string | null = null;
  private stopping = false;
  /** Set once per session when speech_started flushes playback (barge-in). */
  private bargedIn = false;

  constructor(events: VoiceAudioEvents = {}, deps: VoiceAudioDeps = {}) {
    this.events = events;
    this.deps = {
      fetchImpl: deps.fetchImpl ?? fetch.bind(globalThis),
      WebSocketImpl: deps.WebSocketImpl ?? (WebSocket as unknown as new (url: string) => FakeableWebSocket),
      getUserMediaImpl: deps.getUserMediaImpl,
      AudioContextImpl: deps.AudioContextImpl,
      createWorkletNode: deps.createWorkletNode ?? defaultCreateWorkletNode,
      workletUrl: deps.workletUrl ?? WORKLET_URL,
    };
  }

  get currentPhase(): VoiceAudioPhase {
    return this.phase;
  }

  get activeSessionId(): string | null {
    return this.sessionId;
  }

  private setPhase(phase: VoiceAudioPhase) {
    if (this.phase === phase) return;
    this.phase = phase;
    this.events.onPhase?.(phase);
  }

  /**
   * Open the full chain: grant → mic → worklet → WS. Resolves once the
   * socket is open; the broker's `ready` frame drives `listening` after.
   */
  async start(tier: 'standard' | 'mini' = 'standard'): Promise<void> {
    if (this.phase !== 'idle') throw new Error('voice audio session already active');
    this.stopping = false;
    this.bargedIn = false;
    this.setPhase('connecting');

    let grant: SessionGrant;
    try {
      const res = await this.deps.fetchImpl(`${API_BASE}/api/voice/session`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ tier, mode: 'realtime' }),
      });
      if (!res.ok) {
        const body = (await res.json().catch(() => ({}))) as Record<string, unknown>;
        const detail =
          typeof body.detail === 'string'
            ? body.detail
            : typeof body.error === 'string'
              ? body.error
              : Array.isArray(body.reasons) && body.reasons.length
                ? String(body.reasons[0])
                : `HTTP ${res.status}`;
        throw new Error(detail);
      }
      grant = (await res.json()) as SessionGrant;
    } catch (err) {
      this.fail(err);
      return;
    }
    this.sessionId = grant.sessionId;
    // Released before the chain finished opening — tear down, never open.
    if (this.stopping) {
      await this.teardown('ptt_release');
      return;
    }

    try {
      await this.openAudioGraph();
      if (this.stopping) {
        await this.teardown('ptt_release');
        return;
      }
      this.openSocket(grant);
    } catch (err) {
      this.fail(err);
    }
  }

  /** Operator released PTT: stop capture, close the relay, tear down. */
  stop(reason: string = 'ptt_release'): void {
    if (this.phase === 'idle') return;
    this.stopping = true;
    if (this.ws && this.ws.readyState === WS_OPEN) {
      // §4.3: stop = relay termination (the honest end-of-turn signal).
      try {
        this.ws.send(JSON.stringify({ type: 'stop' }));
      } catch {
        /* socket already dying — teardown below handles it */
      }
    }
    void this.teardown(reason);
  }

  /** Barge-in: drop scheduled/stale playback so the operator isn't talked over. */
  flushPlayback(): void {
    for (const src of this.playbackQueue) {
      try {
        src.stop();
      } catch {
        /* already finished */
      }
    }
    this.playbackQueue = [];
    this.playbackTime = 0;
    if (this.phase === 'speaking') this.setPhase('listening');
  }

  // ── audio graph ────────────────────────────────────────────────────────

  private async openAudioGraph(): Promise<void> {
    if (!this.deps.getUserMediaImpl) {
      throw new Error('microphone capture unavailable in this context');
    }
    if (!this.deps.AudioContextImpl) throw new Error('Web Audio unavailable in this context');

    this.mediaStream = await this.deps.getUserMediaImpl();
    this.audioContext = new this.deps.AudioContextImpl({ sampleRate: WIRE_SAMPLE_RATE });
    try {
      await this.audioContext.audioWorklet.addModule(this.deps.workletUrl!);
    } catch (err) {
      throw new Error(
        `voice worklet failed to load: ${err instanceof Error ? err.message : String(err)}`,
      );
    }
    this.sourceNode = this.audioContext.createMediaStreamSource(this.mediaStream);
    this.workletNode = this.deps.createWorkletNode(this.audioContext);
    this.workletNode.port.onmessage = (ev: { data: unknown }) => {
      if (!(ev.data instanceof ArrayBuffer)) return;
      const queued = this.batcher.push(new Int16Array(ev.data));
      if (queued && this.ws && this.ws.readyState === WS_OPEN) {
        // Int16Array buffer IS the little-endian PCM16 wire frame.
        this.ws.send(queued.buffer as ArrayBuffer);
      }
    };
    this.sourceNode.connect(this.workletNode);
    // Do NOT connect the worklet to destination — mic must never echo.
  }

  private openSocket(grant: SessionGrant): void {
    const base = API_BASE.replace(/^http/, 'ws');
    const url = `${base}${grant.wsPath}?token=${encodeURIComponent(grant.token)}&sessionId=${encodeURIComponent(grant.sessionId)}`;
    const ws = new this.deps.WebSocketImpl(url);
    ws.binaryType = 'arraybuffer';
    this.ws = ws;

    ws.onopen = () => {
      if (this.stopping) {
        // Released while the handshake was in flight — do not go live.
        try {
          ws.close();
        } catch { /* already closing */ }
        return;
      }
      // Flush anything the worklet captured before the socket opened.
      const held = this.batcher.drain();
      if (held && ws.readyState === WS_OPEN) ws.send(held.buffer as ArrayBuffer);
    };

    ws.onmessage = (ev: { data: unknown }) => this.handleMessage(ev.data);

    ws.onclose = (ev: { code: number; reason: string }) => {
      const reason = ev.reason || `closed ${ev.code}`;
      if (!this.stopping) this.fail(new Error(reason));
      else void this.teardown(reason);
    };

    ws.onerror = () => {
      if (!this.stopping) this.fail(new Error('voice relay socket error'));
    };
  }

  private handleMessage(data: unknown): void {
    // Broker→client audio: raw PCM16 wire frames → playback.
    if (data instanceof ArrayBuffer) {
      this.enqueuePlayback(pcm16BytesToFloat32(data));
      return;
    }

    let frame: Record<string, unknown>;
    try {
      frame = JSON.parse(String(data)) as Record<string, unknown>;
    } catch {
      return; // broker never sends non-JSON text; ignore defensively
    }

    const type = String(frame.type ?? '');

    if (type === 'ready') {
      this.setPhase('listening');
      this.events.onFrame?.(frame);
      return;
    }
    if (type === 'cost' || type === 'warn' || type === 'cap' || type === 'watchdog_alert') {
      if (type === 'cap') this.flushPlayback();
      this.events.onFrame?.(frame);
      return;
    }
    if (type === 'error' || type === 'upstream.error' || type === 'closed') {
      const detail =
        typeof frame.detail === 'string'
          ? frame.detail
          : typeof frame.reason === 'string'
            ? frame.reason
            : typeof frame.code === 'string'
              ? frame.code
              : type;
      // Verbatim honesty: surface the provider's own words.
      if (!this.stopping) this.events.onFault?.(detail);
      return;
    }

    // Verbatim upstream stream: watch for the server-VAD barge-in signal.
    if (type === 'input_audio_buffer.speech_started') {
      if (!this.bargedIn && this.phase === 'speaking') {
        this.bargedIn = true;
        this.flushPlayback();
      }
      if (this.phase === 'speaking') this.setPhase('listening');
      this.events.onFrame?.(frame);
      return;
    }
    if (type === 'response.audio.done' || type === 'response.done') {
      this.setPhase('listening');
      this.events.onFrame?.(frame);
      return;
    }
    // Provider text/tool events: forwarded for the panel + picker visibility.
    if (type.startsWith('response.audio')) {
      this.setPhase('speaking');
    }
    this.events.onFrame?.(frame);
  }

  // ── playback ───────────────────────────────────────────────────────────

  private enqueuePlayback(samples: Float32Array): void {
    if (this.audioContext && samples.length > 0) {
      const buffer = this.audioContext.createBuffer(1, samples.length, WIRE_SAMPLE_RATE);
      buffer.copyToChannel(samples, 0);
      const src = this.audioContext.createBufferSource();
      src.buffer = buffer;
      src.connect(this.audioContext.destination);
      const now = this.audioContext.currentTime;
      if (this.playbackTime < now) this.playbackTime = now;
      src.start(this.playbackTime);
      this.playbackTime += buffer.duration;
      this.playbackQueue.push(src);
      src.onended = () => {
        this.playbackQueue = this.playbackQueue.filter((s) => s !== src);
        if (this.playbackQueue.length === 0 && this.phase === 'speaking') {
          this.setPhase('listening');
        }
      };
      this.setPhase('speaking');
    }
  }

  // ── teardown ───────────────────────────────────────────────────────────

  private fail(err: unknown): void {
    const reason = err instanceof Error && err.message ? err.message : String(err);
    this.events.onFault?.(reason);
    void this.teardown(reason);
  }

  private async teardown(reason: string): Promise<void> {
    this.flushPlayback();
    this.batcher.drain();
    if (this.workletNode) {
      this.workletNode.port.onmessage = null;
      try {
        this.workletNode.disconnect();
      } catch { /* already torn down */ }
      this.workletNode = null;
    }
    if (this.sourceNode) {
      try {
        this.sourceNode.disconnect();
      } catch { /* already torn down */ }
      this.sourceNode = null;
    }
    if (this.mediaStream) {
      this.mediaStream.getTracks().forEach((t) => t.stop());
      this.mediaStream = null;
    }
    if (this.audioContext) {
      try {
        await this.audioContext.close();
      } catch { /* already closed */ }
      this.audioContext = null;
    }
    if (this.ws) {
      this.ws.onclose = null;
      this.ws.onerror = null;
      this.ws.onmessage = null;
      try {
        this.ws.close();
      } catch { /* already closed */ }
      this.ws = null;
    }
    this.sessionId = null;
    this.setPhase('idle');
    if (reason) this.events.onFrame?.({ type: 'closed', reason });
  }
}
