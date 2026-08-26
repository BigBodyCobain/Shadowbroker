/**
 * voice-pcm-worklet — AudioWorkletProcessor for the U8 realtime voice client.
 *
 * Lives in /public/worklets/ so `audioContext.audioWorklet.addModule()` can
 * fetch it by URL in Next.js. Receives hardware-rate Float32 mic blocks,
 * downsamples to the 24 kHz wire rate, converts to little-endian PCM16, and
 * posts raw ArrayBuffers to the main thread (transferable, zero-copy).
 *
 * The main thread owns batching (PcmBatcher) and the WebSocket; this file
 * stays a dumb format converter so it can never wedge the audio graph.
 *
 * Wire contract (plan §4.3): raw LE PCM16 signed mono 24 000 Hz, no header.
 */

const WIRE_SAMPLE_RATE = 24000;

class VoicePcmProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._inputRate = sampleRate; // global provided by AudioWorkletGlobalScope
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || input.length === 0) return true;
    // Mono downmix: average available channels (mic setups vary).
    const ch0 = input[0];
    if (!ch0 || ch0.length === 0) return true;

    let mono;
    if (input.length === 1) {
      mono = ch0;
    } else {
      mono = new Float32Array(ch0.length);
      const n = input.length;
      for (let i = 0; i < ch0.length; i++) {
        let sum = 0;
        for (let c = 0; c < n; c++) {
          const ch = input[c];
          sum += ch && ch.length > i ? ch[i] : 0;
        }
        mono[i] = sum / n;
      }
    }

    const downsampled = this._downsample(mono);
    const pcm = new Int16Array(downsampled.length);
    for (let i = 0; i < downsampled.length; i++) {
      const s = downsampled[i];
      const clamped = s > 1 ? 1 : s < -1 ? -1 : Number.isFinite(s) ? s : 0;
      pcm[i] = Math.round(clamped * 0x7fff);
    }
    if (pcm.length > 0) {
      this.port.postMessage(pcm.buffer, [pcm.buffer]);
    }
    return true;
  }

  _downsample(input) {
    if (this._inputRate <= WIRE_SAMPLE_RATE) return input;
    const ratio = this._inputRate / WIRE_SAMPLE_RATE;
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
}

registerProcessor('voice-pcm', VoicePcmProcessor);
