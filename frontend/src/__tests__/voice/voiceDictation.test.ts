import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  audioBase64,
  DICTATION_SAMPLE_RATE,
  encodeCommandWav,
  MAX_DICTATION_SECONDS,
  startDictation,
} from '@/lib/voiceDictation';

describe('backend-mediated command audio', () => {
  it('encodes bounded mono PCM WAV for local and cloud transcription APIs', () => {
    const audio = encodeCommandWav(new Float32Array([0, 1, -1, Number.NaN]));
    const header = new DataView(audio);
    expect(new TextDecoder().decode(audio.slice(0, 4))).toBe('RIFF');
    expect(header.getUint16(22, true)).toBe(1);
    expect(header.getUint32(24, true)).toBe(DICTATION_SAMPLE_RATE);
    expect(header.getUint16(34, true)).toBe(16);
    expect(header.getUint32(40, true)).toBe(8);
    expect(header.getInt16(46, true)).toBe(32767);
    expect(header.getInt16(48, true)).toBe(-32767);
    expect(header.getInt16(50, true)).toBe(0);
    expect(atob(audioBase64(audio)).length).toBe(audio.byteLength);
  });
  it('rejects empty audio and records longer than the server limit', () => {
    expect(() => encodeCommandWav(new Float32Array())).toThrow('invalid-audio');
    expect(() =>
      encodeCommandWav(new Float32Array(DICTATION_SAMPLE_RATE * MAX_DICTATION_SECONDS + 1)),
    ).toThrow('invalid-audio');
  });
});

describe('microphone cancellation', () => {
  afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });
  it('releases a late microphone permission grant after cancellation without uploading', async () => {
    const stop = vi.fn();
    let grant!: (stream: MediaStream) => void;
    const permission = new Promise<MediaStream>((resolve) => { grant = resolve; });
    vi.stubGlobal('MediaRecorder', class {});
    vi.stubGlobal('OfflineAudioContext', class {});
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: () => permission } });
    const controller = new AbortController();
    const onAudio = vi.fn();
    const started = startDictation({ signal: controller.signal, onAudio, onError: vi.fn(), onEnd: vi.fn() });
    controller.abort();
    grant({ getTracks: () => [{ stop }] } as unknown as MediaStream);
    await expect(started).rejects.toThrow('cancelled');
    expect(stop).toHaveBeenCalledOnce();
    expect(onAudio).not.toHaveBeenCalled();
  });
  it('stops active recording and releases the microphone without transcribing on abort', async () => {
    const stop = vi.fn();
    class Recorder {
      static isTypeSupported() { return true; }
      state = 'inactive';
      onstop?: () => void;
      start() { this.state = 'recording'; }
      stop() { this.state = 'inactive'; this.onstop?.(); }
    }
    vi.stubGlobal('MediaRecorder', Recorder);
    vi.stubGlobal('OfflineAudioContext', class {});
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: async () => ({ getTracks: () => [{ stop }] }) } });
    const controller = new AbortController();
    const onAudio = vi.fn();
    const onEnd = vi.fn();
    await startDictation({ signal: controller.signal, onAudio, onError: vi.fn(), onEnd });
    controller.abort();
    expect(stop).toHaveBeenCalled();
    expect(onEnd).toHaveBeenCalledOnce();
    expect(onAudio).not.toHaveBeenCalled();
  });
});
