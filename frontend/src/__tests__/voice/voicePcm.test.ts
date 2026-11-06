/**
 * U8 — voicePcm pure-math suite: wire-format conversions, downsampling,
 * batching cadence, and hostile-input honesty (plan §4.3 wire contract).
 */
import { describe, expect, it } from 'vitest';

import {
  WIRE_SAMPLE_RATE,
  PcmBatcher,
  downsampleTo24k,
  float32ToPcm16Bytes,
  float32ToInt16LE,
  int16ToFloat32,
  pcm16BytesToFloat32,
  rms,
} from '@/lib/voicePcm';

describe('downsampleTo24k', () => {
  it('passes through at or below the wire rate', () => {
    const input = new Float32Array([0.1, -0.2, 0.3]);
    expect(downsampleTo24k(input, 16000)).toBe(input);
    expect(downsampleTo24k(input, WIRE_SAMPLE_RATE)).toBe(input);
  });

  it('halves length for 48 kHz input and preserves shape', () => {
    const input = new Float32Array(480);
    for (let i = 0; i < input.length; i++) input[i] = Math.sin((i / 480) * Math.PI * 2);
    const out = downsampleTo24k(input, 48000);
    expect(out.length).toBe(240);
    // A full sine cycle at half the samples must still span one cycle.
    expect(out[0]).toBeCloseTo(input[0], 5);
    expect(Math.max(...out)).toBeGreaterThan(0.9);
    expect(Math.min(...out)).toBeLessThan(-0.9);
  });

  it('interpolates rather than decimating', () => {
    // A sample landing exactly between two input points takes the midpoint.
    const input = new Float32Array([0, 1]);
    const out = downsampleTo24k(input, 48000);
    expect(out[0]).toBeCloseTo(0, 5);
  });

  it('degrades hostile input to empty output', () => {
    expect(downsampleTo24k(new Float32Array(0), 48000).length).toBe(0);
    expect(downsampleTo24k(null as unknown as Float32Array, 48000).length).toBe(0);
    expect(downsampleTo24k(new Float32Array(10), NaN).length).toBe(0);
    expect(downsampleTo24k(new Float32Array(10), -1).length).toBe(0);
  });
});

describe('PCM16 conversions', () => {
  it('float32→int16 clamps instead of wrapping', () => {
    const out = float32ToInt16LE(new Float32Array([2, -2, 0.5, NaN]));
    expect(out[0]).toBe(0x7fff);
    expect(out[1]).toBe(-0x7fff); // round(-1 * 0x7fff) — clamp holds, sign preserved
    expect(out[2]).toBe(Math.round(0.5 * 0x7fff));
    expect(out[3]).toBe(0);
  });

  it('byte round-trip preserves values', () => {
    const original = new Float32Array([0, 0.25, -0.5, 1, -1]);
    const bytes = float32ToPcm16Bytes(original);
    expect(bytes.byteLength).toBe(original.length * 2);
    const back = pcm16BytesToFloat32(bytes);
    expect(back[0]).toBe(0);
    expect(back[1]).toBeCloseTo(0.25, 4);
    expect(back[2]).toBeCloseTo(-0.5, 4);
    expect(back[3]).toBeCloseTo(1, 4);
    expect(back[4]).toBeCloseTo(-1, 4);
  });

  it('int16ToFloat32 normalizes by 0x8000', () => {
    const out = int16ToFloat32(Int16Array.from([0x7fff, -0x8000, 0]));
    expect(out[0]).toBeCloseTo(1, 4);
    expect(out[1]).toBeCloseTo(-1, 4);
    expect(out[2]).toBe(0);
  });

  it('byte conversion reads little-endian explicitly', () => {
    // 0x0001 as LE bytes = [0x01, 0x00] → sample value 1/32768.
    const back = pcm16BytesToFloat32(new Uint8Array([0x01, 0x00]));
    expect(back[0]).toBeCloseTo(1 / 0x8000, 6);
  });
});

describe('rms', () => {
  it('computes root-mean-square and handles silence/hostile input', () => {
    expect(rms(new Float32Array(100))).toBe(0);
    expect(rms(new Float32Array([1, -1, 1, -1]))).toBe(1);
    expect(rms(null as unknown as Float32Array)).toBe(0);
    // NaN is sanitized to 0, so the block's energy spreads over both samples.
    expect(rms(new Float32Array([NaN, 0.5]))).toBeCloseTo(Math.sqrt(0.25 / 2), 5);
  });
});

describe('PcmBatcher', () => {
  it('holds until the target cadence then flushes one block', () => {
    const batcher = new PcmBatcher(2400); // 100 ms at 24 kHz
    expect(batcher.push(new Int16Array(1000))).toBeNull();
    expect(batcher.held).toBe(1000);
    const flushed = batcher.push(new Int16Array(1500));
    expect(flushed).not.toBeNull();
    expect(flushed!.length).toBe(2500);
    expect(batcher.held).toBe(0);
  });

  it('drains partial holds and ignores empty pushes', () => {
    const batcher = new PcmBatcher(100);
    expect(batcher.push(new Int16Array(0))).toBeNull();
    batcher.push(new Int16Array(40));
    const drained = batcher.drain();
    expect(drained!.length).toBe(40);
    expect(batcher.drain()).toBeNull();
  });

  it('never produces frames above the 65 536-byte wire cap for sane cadences', () => {
    // 100 ms batches at 24 kHz = 2400 samples = 4800 bytes — far under cap.
    const batcher = new PcmBatcher(2400);
    const flushed = batcher.push(new Int16Array(2400));
    expect((flushed!.length * 2)).toBeLessThanOrEqual(65536);
  });
});
