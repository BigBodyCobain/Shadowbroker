/** Capture one bounded command locally; transcription is performed by the app backend. */
import { float32ToPcm16Bytes } from './voicePcm';

export const DICTATION_SAMPLE_RATE = 16000;
export const MAX_DICTATION_SECONDS = 30;

export function encodeCommandWav(samples: Float32Array): ArrayBuffer {
  if (samples.length === 0 || samples.length > DICTATION_SAMPLE_RATE * MAX_DICTATION_SECONDS)
    throw new Error('invalid-audio');
  const pcm = float32ToPcm16Bytes(samples);
  const wav = new ArrayBuffer(44 + pcm.byteLength);
  const view = new DataView(wav);
  const label = (offset: number, text: string) => {
    for (let i = 0; i < text.length; i++) view.setUint8(offset + i, text.charCodeAt(i));
  };
  label(0, 'RIFF');
  view.setUint32(4, 36 + pcm.byteLength, true);
  label(8, 'WAVE');
  label(12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, DICTATION_SAMPLE_RATE, true);
  view.setUint32(28, DICTATION_SAMPLE_RATE * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  label(36, 'data');
  view.setUint32(40, pcm.byteLength, true);
  new Uint8Array(wav, 44).set(new Uint8Array(pcm));
  return wav;
}

export function audioBase64(audio: ArrayBuffer): string {
  const bytes = new Uint8Array(audio);
  let binary = '';
  for (let offset = 0; offset < bytes.length; offset += 32768)
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 32768));
  return btoa(binary);
}

export async function startDictation(options: {
  signal: AbortSignal;
  onAudio(audio: ArrayBuffer): Promise<void>;
  onError(code: string): void;
  onEnd(): void;
}): Promise<{ stop(): void; abort(): void }> {
  if (
    typeof MediaRecorder === 'undefined' ||
    typeof OfflineAudioContext === 'undefined' ||
    !navigator.mediaDevices?.getUserMedia
  )
    throw new Error('unsupported');
  if (window.isSecureContext === false) throw new Error('insecure');
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const release = () => {
    for (const track of stream.getTracks()) track.stop();
  };
  if (options.signal.aborted) {
    release();
    throw new Error('cancelled');
  }
  const mimeType = ['audio/webm;codecs=opus', 'audio/mp4', 'audio/ogg;codecs=opus'].find((type) =>
    MediaRecorder.isTypeSupported(type),
  );
  let recorder: MediaRecorder;
  try {
    recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
  } catch (error) {
    release();
    throw error;
  }
  const chunks: Blob[] = [];
  let size = 0;
  let cancelled = false;
  let completed = false;
  const abort = () => {
    cancelled = true;
    if (recorder.state !== 'inactive') recorder.stop();
    release();
  };
  options.signal.addEventListener('abort', abort, { once: true });
  recorder.ondataavailable = (event) => {
    size += event.data.size;
    if (size > 2 * 1024 * 1024) {
      options.onError('invalid-audio');
      abort();
      return;
    }
    if (event.data.size) chunks.push(event.data);
  };
  recorder.onerror = () => {
    options.onError('failed');
    abort();
  };
  recorder.onstop = async () => {
    if (completed) return;
    completed = true;
    clearTimeout(timer);
    release();
    options.signal.removeEventListener('abort', abort);
    try {
      if (!cancelled && !options.signal.aborted) {
        const blob = new Blob(chunks, { type: recorder.mimeType });
        if (!blob.size) throw new Error('no-speech');
        const context = new OfflineAudioContext(
          1,
          DICTATION_SAMPLE_RATE * MAX_DICTATION_SECONDS,
          DICTATION_SAMPLE_RATE,
        );
        const decoded = await context.decodeAudioData(await blob.arrayBuffer());
        const samples = new Float32Array(
          Math.min(decoded.length, DICTATION_SAMPLE_RATE * MAX_DICTATION_SECONDS),
        );
        for (let channel = 0; channel < decoded.numberOfChannels; channel++) {
          const data = decoded.getChannelData(channel);
          for (let i = 0; i < samples.length; i++) samples[i] += data[i] / decoded.numberOfChannels;
        }
        if (!cancelled && !options.signal.aborted) await options.onAudio(encodeCommandWav(samples));
      }
    } catch (error) {
      if (!options.signal.aborted)
        options.onError(error instanceof Error ? error.message : 'failed');
    } finally {
      options.onEnd();
    }
  };
  const timer = setTimeout(() => {
    if (recorder.state !== 'inactive') recorder.stop();
  }, MAX_DICTATION_SECONDS * 1000);
  try {
    recorder.start(250);
  } catch (error) {
    clearTimeout(timer);
    options.signal.removeEventListener('abort', abort);
    release();
    throw error;
  }
  return {
    stop: () => {
      if (recorder.state !== 'inactive') recorder.stop();
    },
    abort,
  };
}
