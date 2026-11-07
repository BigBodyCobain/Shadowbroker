/**
 * U8 — VoiceAudioClient state machine over full infrastructure fakes:
 * grant gating, wire framing, phase transitions, barge-in flush, cost
 * frames, verbatim faults, and teardown hygiene (plan §4.3).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  FakeableAudioContext,
  FakeableWebSocket,
  FakeableWorkletNode,
  VoiceAudioClient,
} from '@/lib/voiceAudioClient';
import { float32ToPcm16Bytes } from '@/lib/voicePcm';

// ── fakes ────────────────────────────────────────────────────────────────

class FakeWS implements FakeableWebSocket {
  readyState = 0;
  sent: (string | ArrayBuffer)[] = [];
  closed: { code?: number; reason?: string }[] = [];
  onopen: ((ev?: unknown) => void) | null = null;
  onmessage: ((ev: { data: unknown }) => void) | null = null;
  onclose: ((ev: { code: number; reason: string }) => void) | null = null;
  onerror: ((ev?: unknown) => void) | null = null;
  binaryType?: string;

  constructor(public url: string) {}

  send(data: string | ArrayBuffer) {
    this.sent.push(data);
  }
  close(code?: number, reason?: string) {
    this.closed.push({ code, reason });
  }
  // test drivers
  open() {
    this.readyState = 1;
    this.onopen?.();
  }
  serverText(frame: Record<string, unknown>) {
    this.onmessage?.({ data: JSON.stringify(frame) });
  }
  serverBinary(bytes: ArrayBuffer) {
    this.onmessage?.({ data: bytes });
  }
  serverClose(code = 1000, reason = '') {
    this.readyState = 3;
    this.onclose?.({ code, reason });
  }
}

function fakeContext() {
  const sources: { stopped: boolean; startedAt?: number; buffer?: unknown }[] = [];
  const ctx = {
    sampleRate: 24000,
    currentTime: 10,
    destination: { fake: 'dest' },
    closed: false,
    audioWorklet: { addModule: vi.fn(async () => undefined) },
    createMediaStreamSource: () => ({
      connected: [] as unknown[],
      connect(dest: unknown) {
        this.connected.push(dest);
      },
      disconnect() {},
    }),
    createBuffer: (_ch: number, length: number, rate: number) => ({
      copied: null as Float32Array | null,
      copyToChannel(src: Float32Array) {
        this.copied = src;
      },
      duration: length / rate,
    }),
    createBufferSource: () => {
      const src = {
        stopped: false,
        startedAt: undefined as number | undefined,
        buffer: null as unknown,
        connectedTo: null as unknown,
        connect(dest: unknown) {
          src.connectedTo = dest;
        },
        start(when?: number) {
          src.startedAt = when;
        },
        stop() {
          src.stopped = true;
        },
        onended: null as (() => void) | null,
      };
      sources.push(src);
      return src;
    },
    close: vi.fn(async () => {
      ctx.closed = true;
    }),
    __sources: sources,
  };
  return ctx as unknown as FakeCtx;
}

function fakeWorklet() {
  const node: FakeableWorkletNode = {
    port: { onmessage: null, postMessage: vi.fn() },
    disconnect: vi.fn(),
  };
  return node;
}

function fakeTrack() {
  return { stop: vi.fn() };
}

type FakeCtx = FakeableAudioContext & {
  __sources: { stopped: boolean; startedAt?: number }[];
  closed: boolean;
};

interface Harness {
  client: VoiceAudioClient;
  ws: FakeWS;
  ctx: FakeCtx;
  worklet: FakeableWorkletNode;
  track: ReturnType<typeof fakeTrack>;
  phases: string[];
  frames: Record<string, unknown>[];
  faults: string[];
  grantCalls: [string, RequestInit | undefined][];
}

function harness(status = 201, grantBody?: Record<string, unknown>): Harness {
  const ws = new FakeWS('ws://test');
  const ctx = fakeContext();
  const worklet = fakeWorklet();
  const track = fakeTrack();
  const phases: string[] = [];
  const frames: Record<string, unknown>[] = [];
  const faults: string[] = [];
  const grantCalls: [string, RequestInit | undefined][] = [];

  const grant = grantBody ?? {
    sessionId: 'sess-1',
    token: 'tok-1',
    wsPath: '/api/voice/session/ws',
    resolvedProvider: 'openai_realtime',
  };
  const fetchImpl = vi.fn(async (url: string, init?: RequestInit) => {
    grantCalls.push([url, init]);
    if (status === 201) {
      return new Response(JSON.stringify(grant), { status: 201 });
    }
    // Match the router's real refusal shapes per status.
    const body =
      status === 403
        ? { error: 'opt_in_required', detail: 'opt_in_required', reasons: ['VOICE_AGENT_OUTBOUND_ENABLE is not allow'] }
        : { error: 'unconfigured', detail: 'No usable voice provider configured — set VOICE_OPENAI_API_KEY' };
    void init;
    return new Response(JSON.stringify(body), { status });
  });

  const client = new VoiceAudioClient(
    {
      onPhase: (p) => phases.push(p),
      onFrame: (f) => frames.push(f),
      onFault: (r) => faults.push(r),
    },
    {
      fetchImpl: fetchImpl as unknown as typeof fetch,
      WebSocketImpl: function (url: string) {
        ws.url = url;
        return ws;
      } as unknown as new (url: string) => FakeableWebSocket,
      getUserMediaImpl: async () => ({ getTracks: () => [track] }) as unknown as MediaStream,
      AudioContextImpl: function () {
        return ctx;
      } as unknown as new (o?: { sampleRate: number }) => FakeableAudioContext,
      createWorkletNode: () => worklet,
    },
  );
  return { client, ws, ctx, worklet, track, phases, frames, faults, grantCalls };
}

async function started(h: Harness) {
  const p = h.client.start();
  // Grant fetch is awaited synchronously through microtasks.
  await vi.waitFor(() => expect(h.ws.url).toContain('/api/voice/session/ws'));
  h.ws.open();
  h.ws.serverText({ type: 'ready', sessionId: 'sess-1' });
  await p;
  await vi.waitFor(() => expect(h.client.currentPhase).toBe('listening'));
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn());
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

// ── tests ────────────────────────────────────────────────────────────────

describe('VoiceAudioClient — grant gating', () => {
  it('403 opt-in refusal surfaces the verbatim detail and never opens a socket', async () => {
    const h = harness(403);
    await h.client.start();
    expect(h.faults).toEqual(['opt_in_required']);
    expect(h.client.currentPhase).toBe('idle');
    expect(h.ws.sent).toHaveLength(0);
  });

  it('503 unconfigured surfaces the provider degradation reason', async () => {
    const h = harness(503);
    await h.client.start();
    expect(h.faults[0]).toContain('No usable voice provider configured');
    expect(h.client.currentPhase).toBe('idle');
  });

  it('mints the session with mode:"realtime" and binds token+sessionId in the WS URL', async () => {
    const h = harness();
    await started(h);
    const [, init] = h.grantCalls[0];
    expect(JSON.parse(String(init?.body)).mode).toBe('realtime');
    expect(h.ws.url).toContain('token=tok-1');
    expect(h.ws.url).toContain('sessionId=sess-1');
  });
});

describe('VoiceAudioClient — wire protocol', () => {
  it('ready frame drives listening; binary frames drive speaking', async () => {
    const h = harness();
    await started(h);

    h.ws.serverBinary(float32ToPcm16Bytes(new Float32Array(240).fill(0.5)));
    expect(h.client.currentPhase).toBe('speaking');

    h.ws.serverText({ type: 'response.audio.done' });
    expect(h.client.currentPhase).toBe('listening');
  });

  it('mic capture batches to the 100 ms cadence before sending upstream', async () => {
    const h = harness();
    await started(h);

    const small = new Int16Array(1000).buffer; // < 2400 samples → held
    h.worklet.port.onmessage?.({ data: small });
    expect(h.ws.sent.filter((d) => typeof d !== 'string')).toHaveLength(0);

    h.worklet.port.onmessage?.({ data: new Int16Array(1500).buffer });
    const binary = h.ws.sent.filter((d) => d instanceof ArrayBuffer);
    expect(binary).toHaveLength(1);
    expect((binary[0] as ArrayBuffer).byteLength).toBe((1000 + 1500) * 2);
  });

  it('cost/warn/cap frames forward verbatim; cap also flushes playback', async () => {
    const h = harness();
    await started(h);

    h.ws.serverBinary(float32ToPcm16Bytes(new Float32Array(500).fill(0.3)));
    expect(h.client.currentPhase).toBe('speaking');

    h.ws.serverText({ type: 'cap', totalUsd: 5, reason: 'session cap reached' });
    expect(h.client.currentPhase).toBe('listening'); // flushed
    const cap = h.frames.find((f) => f.type === 'cap');
    expect(cap?.reason).toBe('session cap reached');
  });

  it('upstream errors surface the provider detail verbatim', async () => {
    const h = harness();
    await started(h);

    h.ws.serverText({ type: 'upstream.error', status: 401, detail: 'invalid api key' });
    expect(h.faults).toContain('invalid api key');
  });
});

describe('VoiceAudioClient — barge-in & teardown', () => {
  it('speech_started flushes stale playback (barge-in) and returns to listening', async () => {
    const h = harness();
    await started(h);

    h.ws.serverBinary(float32ToPcm16Bytes(new Float32Array(500).fill(0.4)));
    const playing = h.ctx.__sources.filter((s: { startedAt?: number }) => s.startedAt !== undefined);
    expect(playing.length).toBeGreaterThan(0);

    h.ws.serverText({ type: 'input_audio_buffer.speech_started' });
    expect(h.client.currentPhase).toBe('listening');
    for (const src of playing) {
      expect((src as { stopped: boolean }).stopped).toBe(true);
    }
  });

  it('stop() sends the §4.3 stop frame and tears the graph down cleanly', async () => {
    const h = harness();
    await started(h);

    h.client.stop('ptt_release');
    expect(h.ws.sent.some((d) => d === '{"type":"stop"}')).toBe(true);
    // Teardown suspends at the awaited audioContext.close() — wait it out.
    await vi.waitFor(() => expect(h.client.currentPhase).toBe('idle'));
    expect(h.track.stop).toHaveBeenCalled();
    expect(h.ctx.closed).toBe(true);
    expect(h.worklet.disconnect).toHaveBeenCalled();
    expect(h.ws.closed.length).toBe(1);
    expect(h.frames.some((f) => f.type === 'closed' && f.reason === 'ptt_release')).toBe(true);
  });

  it('abnormal socket close mid-session is a verbatim fault, not silence', async () => {
    const h = harness();
    await started(h);

    h.ws.serverClose(1011, 'relay crashed');
    expect(h.faults).toContain('relay crashed');
    await vi.waitFor(() => expect(h.client.currentPhase).toBe('idle'));
    expect(h.track.stop).toHaveBeenCalled();
  });

  it('worklet load failure degrades honestly with the load error', async () => {
    const h = harness();
    h.ctx.audioWorklet.addModule = vi.fn(async () => {
      throw new Error('404 on worklet url');
    });
    await h.client.start();
    expect(h.faults[0]).toContain('voice worklet failed to load');
    expect(h.faults[0]).toContain('404 on worklet url');
    expect(h.client.currentPhase).toBe('idle');
    // Mic track released even though the socket never opened.
    expect(h.track.stop).toHaveBeenCalled();
  });
});
