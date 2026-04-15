import { describe, it, expect } from 'vitest';
import {
  classifyAircraft,
  HELI_TYPES,
  TURBOPROP_TYPES,
  BIZJET_TYPES,
} from '@/utils/aircraftClassification';

describe('classifyAircraft', () => {
  // ─── Helicopter classification ────────────────────────────────────────────

  it('classifies known helicopter types', () => {
    const heliModels = ['R22', 'R44', 'B407', 'S76', 'EC35', 'H145', 'UH60', 'AH64', 'CH47'];
    for (const model of heliModels) {
      expect(classifyAircraft(model)).toBe('heli');
    }
  });

  it('classifies as heli when category hint is "heli"', () => {
    expect(classifyAircraft('UNKNOWN', 'heli')).toBe('heli');
  });

  it('category hint "heli" overrides model-based classification', () => {
    // B738 would normally be airliner, but category says heli
    expect(classifyAircraft('B738', 'heli')).toBe('heli');
  });

  // ─── Business jet classification ──────────────────────────────────────────

  it('classifies known bizjet types', () => {
    const bizjetModels = ['C25A', 'C680', 'CL60', 'GLEX', 'GLF5', 'LJ45', 'FA7X'];
    for (const model of bizjetModels) {
      expect(classifyAircraft(model)).toBe('bizjet');
    }
  });

  // ─── Turboprop classification ─────────────────────────────────────────────

  it('classifies known turboprop types', () => {
    const turbopropModels = ['AT72', 'C208', 'DHC6', 'DH8D', 'PC12', 'TBM9', 'C130'];
    for (const model of turbopropModels) {
      expect(classifyAircraft(model)).toBe('turboprop');
    }
  });

  // ─── Airliner default ────────────────────────────────────────────────────

  it('defaults to airliner for unknown types', () => {
    expect(classifyAircraft('B738')).toBe('airliner');
    expect(classifyAircraft('A320')).toBe('airliner');
    expect(classifyAircraft('B77W')).toBe('airliner');
  });

  it('defaults to airliner for empty model string', () => {
    expect(classifyAircraft('')).toBe('airliner');
  });

  // ─── Case insensitivity ──────────────────────────────────────────────────

  it('handles lowercase model codes', () => {
    expect(classifyAircraft('r22')).toBe('heli');
    expect(classifyAircraft('c25a')).toBe('bizjet');
    expect(classifyAircraft('at72')).toBe('turboprop');
  });

  it('handles mixed case model codes', () => {
    expect(classifyAircraft('Dh8D')).toBe('turboprop');
    expect(classifyAircraft('Glf5')).toBe('bizjet');
  });

  // ─── Priority order ──────────────────────────────────────────────────────

  it('prioritizes heli over bizjet (if type appears in both sets)', () => {
    // heli check comes first in the function
    for (const model of ['B06', 'S92', 'H225']) {
      expect(classifyAircraft(model)).toBe('heli');
    }
  });

  it('prioritizes bizjet over turboprop', () => {
    // PC24 appears in both BIZJET_TYPES and TURBOPROP_TYPES
    // bizjet check comes before turboprop in the function
    if (BIZJET_TYPES.has('PC24') && TURBOPROP_TYPES.has('PC24')) {
      expect(classifyAircraft('PC24')).toBe('bizjet');
    }
  });

  // ─── Set integrity ───────────────────────────────────────────────────────

  it('HELI_TYPES set has expected minimum entries', () => {
    expect(HELI_TYPES.size).toBeGreaterThan(50);
  });

  it('TURBOPROP_TYPES set has expected minimum entries', () => {
    expect(TURBOPROP_TYPES.size).toBeGreaterThan(80);
  });

  it('BIZJET_TYPES set has expected minimum entries', () => {
    expect(BIZJET_TYPES.size).toBeGreaterThan(50);
  });
});
