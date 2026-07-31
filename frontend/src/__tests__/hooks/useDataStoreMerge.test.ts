import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import {
  arrayFingerprint,
  mergeData,
  useDataKey,
  valuesEquivalent,
} from '@/hooks/useDataStore';

afterEach(() => {
  cleanup();
});

describe('arrayFingerprint', () => {
  it('encodes length and id/lat/lng samples', () => {
    const a = [
      { icao: 'ABC123', lat: 40.1234, lng: -74.5678 },
      { icao: 'DEF456', lat: 41.0, lng: -73.0 },
    ];
    expect(arrayFingerprint(a)).toBe('2|ABC123:4012:-7457|DEF456:4100:-7300');
  });

  it('falls back through id/mmsi/hex/callsign/name', () => {
    expect(arrayFingerprint([{ mmsi: '123', lat: 1.006, lng: 2.004 }])).toBe(
      '1|123:101:200',
    );
    expect(arrayFingerprint([{ hex: 'A1', lat: null, lng: null }])).toBe('1|A1::');
  });
});

describe('valuesEquivalent', () => {
  it('returns true for identical references and empty arrays', () => {
    const arr: unknown[] = [];
    expect(valuesEquivalent(arr, arr)).toBe(true);
    expect(valuesEquivalent([], [])).toBe(true);
    expect(valuesEquivalent(null, null)).toBe(true);
    expect(valuesEquivalent(undefined, null)).toBe(false);
  });

  it('treats flight arrays with same ids/positions as equivalent', () => {
    const prev = [{ icao: 'N1', lat: 10.001, lng: 20.002 }];
    const next = [{ icao: 'N1', lat: 10.004, lng: 20.002 }]; // rounds to same *100
    expect(valuesEquivalent(prev, next)).toBe(true);
  });

  it('detects position changes beyond rounding', () => {
    const prev = [{ icao: 'N1', lat: 10.0, lng: 20.0 }];
    const next = [{ icao: 'N1', lat: 10.02, lng: 20.0 }];
    expect(valuesEquivalent(prev, next)).toBe(false);
  });

  it('shallow-compares plain objects', () => {
    expect(valuesEquivalent({ a: 1, b: 2 }, { a: 1, b: 2 })).toBe(true);
    expect(valuesEquivalent({ a: 1 }, { a: 1, b: 2 })).toBe(false);
    expect(valuesEquivalent({ a: 1 }, { a: 2 })).toBe(false);
  });

  it('returns false for different lengths', () => {
    expect(valuesEquivalent([{ id: 1 }], [{ id: 1 }, { id: 2 }])).toBe(false);
  });

  it('does not fingerprint non-geo arrays (news etc. still notify)', () => {
    const prev = [{ id: 'a', title: 'Old headline' }];
    const next = [{ id: 'a', title: 'New headline' }];
    expect(valuesEquivalent(prev, next)).toBe(false);
  });
});

describe('mergeData stable references', () => {
  it('keeps the previous array reference when content fingerprint matches', () => {
    const first = [{ icao: 'KEEP', lat: 51.5, lng: -0.12 }];
    act(() => {
      mergeData({ commercial_flights: first });
    });

    const { result } = renderHook(() => useDataKey('commercial_flights'));
    expect(result.current).toBe(first);

    act(() => {
      mergeData({
        commercial_flights: [{ icao: 'KEEP', lat: 51.5, lng: -0.12 }],
      });
    });
    expect(result.current).toBe(first);
  });

  it('replaces the reference when a tracked position moves', () => {
    const first = [{ icao: 'MOVE', lat: 1.0, lng: 2.0 }];
    act(() => {
      mergeData({ ships: first });
    });

    const { result } = renderHook(() => useDataKey('ships'));
    expect(result.current).toBe(first);

    const second = [{ icao: 'MOVE', lat: 1.5, lng: 2.0 }];
    act(() => {
      mergeData({ ships: second });
    });
    expect(result.current).toBe(second);
    expect(result.current).not.toBe(first);
  });

  it('does not notify for shallow-equivalent objects', () => {
    const threat = { score: 3, level: 'ELEVATED' as const, color: '#f90', drivers: [] as string[] };
    act(() => {
      mergeData({ threat_level: threat });
    });
    const { result } = renderHook(() => useDataKey('threat_level'));
    expect(result.current).toBe(threat);

    act(() => {
      mergeData({
        threat_level: { score: 3, level: 'ELEVATED', color: '#f90', drivers: threat.drivers },
      });
    });
    expect(result.current).toBe(threat);
  });
});
