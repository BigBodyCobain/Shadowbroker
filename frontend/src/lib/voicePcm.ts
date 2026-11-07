/**
 * voicePcm — pure PCM math for the U8 realtime speech-to-speech client.
 *
 * No DOM, no AudioContext, no WebSocket — importable under vitest and
 * reusable by both the AudioWorklet-feeding path and the playback path.
 * All functions are total: hostile input (NaN, wrong rates) degrades to
 * honest empty output rather than throwing mid-audio.
 *
 * Wire contract (plan §4.3): client→broker binary = raw little-endian PCM16
 * signed mono 24 000 Hz; broker→client audio = the same format. The mic
 * AudioContext runs at the hardware rate — downsampling happens HERE,
 * before emission, so no resampling happens anywhere on the server.
 */

export const WIRE_SAMPLE_RATE = 24000;

/**
 * Linear-interpolation downsample from an arbitrary hardware input rate to
 * the 24 kHz wire rate. `inputRate <= WIRE_SAMPLE_RATE` (e.g. a 16 kHz mic)
 * is passed through unchanged — upsampling mic audio adds nothing.
 */
export function downsampleTo24k(input: Float32Array, inputRate: number): Float32Array {
  if (!input || input.length === 0) return new Float32Array(0);
  const rate = Number(inputRate);
  if (!Number.isFinite(rate) || rate <= 0) return new Float32Array(0);
  if (rate <= WIRE_SAMPLE_RATE) return input;

  const ratio = rate / WIRE_SAMPLE_RATE;
  const outLength = Math.floor(input.length / ratio);
  const out = new Float32Array(outLength);
  for (let i = 0; i < outLength; i++) {
    const src = i * ratio;
    const i0 = Math.floor(src);
    const i1 = Math.min(i0 + 1, input.length - 1);
    const frac = src - i0;
    out[i] = input[i0] * (1 - frac) + input[i1] * frac;
  }
  return out;
}

/** Float32 [-1,1] → little-endian Int16 PCM, clamped (never wraps). */
export function float32ToInt16LE(input: Float32Array): Int16Array {
  const out = new Int16Array(input ? input.length : 0);
  for (let i = 0; i < out.length; i++) {
    const s = input[i];
    const clamped = s > 1 ? 1 : s < -1 ? -1 : Number.isFinite(s) ? s : 0;
    out[i] = Math.round(clamped * 0x7fff);
  }
  return out;
}

/** Int16 PCM (any endianness in memory — we read via DataView-free typed array) → Float32 [-1,1]. */
export function int16ToFloat32(input: Int16Array): Float32Array {
  const out = new Float32Array(input ? input.length : 0);
  for (let i = 0; i < out.length; i++) {
    out[i] = input[i] / 0x8000;
  }
  return out;
}

/** Raw little-endian PCM16 bytes (wire format) → Float32 [-1,1]. */
export function pcm16BytesToFloat32(bytes: ArrayBuffer | Uint8Array): Float32Array {
  const view = bytes instanceof Uint8Array
    ? new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
    : new DataView(bytes);
  const samples = Math.floor(view.byteLength / 2);
  const out = new Float32Array(samples);
  for (let i = 0; i < samples; i++) {
    out[i] = view.getInt16(i * 2, true) / 0x8000;
  }
  return out;
}

/** Float32 [-1,1] → raw little-endian PCM16 bytes (wire format). */
export function float32ToPcm16Bytes(input: Float32Array): ArrayBuffer {
  const int16 = float32ToInt16LE(input);
  const out = new ArrayBuffer(int16.length * 2);
  const view = new DataView(out);
  for (let i = 0; i < int16.length; i++) {
    view.setInt16(i * 2, int16[i], true);
  }
  return out;
}

/** Rough RMS of a Float32 block — used for local speech-activity gating. */
export function rms(input: Float32Array): number {
  if (!input || input.length === 0) return 0;
  let sum = 0;
  for (let i = 0; i < input.length; i++) {
    const s = Number.isFinite(input[i]) ? input[i] : 0;
    sum += s * s;
  }
  return Math.sqrt(sum / input.length);
}

/**
 * Batch wire-emission cadence: accumulate Int16 samples until at least
 * `targetSamples` are held (e.g. 2400 = 100 ms at 24 kHz), then flush one
 * ≤65 536-byte binary frame (§4.3 frame enforcement). Pure accumulator —
 * the client owns the timer.
 */
export class PcmBatcher {
  private buffer: Int16Array = new Int16Array(0);

  constructor(private readonly targetSamples: number = 2400) {
    if (!Number.isFinite(targetSamples) || targetSamples < 1) this.targetSamples = 1;
  }

  push(samples: Int16Array): Int16Array | null {
    if (!samples || samples.length === 0) return null;
    const merged = new Int16Array(this.buffer.length + samples.length);
    merged.set(this.buffer, 0);
    merged.set(samples, this.buffer.length);
    if (merged.length < this.targetSamples) {
      this.buffer = merged;
      return null;
    }
    this.buffer = new Int16Array(0);
    return merged;
  }

  /** Flush whatever is held (end of turn / teardown). */
  drain(): Int16Array | null {
    if (this.buffer.length === 0) return null;
    const out = this.buffer;
    this.buffer = new Int16Array(0);
    return out;
  }

  get held(): number {
    return this.buffer.length;
  }
}
