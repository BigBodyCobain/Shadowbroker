import { describe, it, expect } from 'vitest';
import { spreadAlertItems } from '@/utils/alertSpread';

describe('spreadAlertItems', () => {
  const makeAlert = (title: string, lat: number, lng: number, cluster_count = 1) => ({
    title,
    coords: [lat, lng],
    cluster_count,
    alert_level: 3,
  });

  it('returns empty array for empty input', () => {
    expect(spreadAlertItems([], 4, new Set())).toEqual([]);
  });

  it('throws on null input (caller must null-check)', () => {
    expect(() => spreadAlertItems(null as any, 4, new Set())).toThrow();
  });

  it('filters out items without coords', () => {
    const items = [{ title: 'No coords', alert_level: 1 }, makeAlert('Has coords', 40, -74)];
    const result = spreadAlertItems(items, 4, new Set());
    expect(result.length).toBe(1);
    expect(result[0].title).toBe('Has coords');
  });

  it('filters dismissed alerts by alertKey', () => {
    const items = [makeAlert('Fire in NYC', 40.7, -74.0), makeAlert('Floods in LA', 34.0, -118.2)];
    const dismissed = new Set(['Fire in NYC|40.7,-74']);
    const result = spreadAlertItems(items, 4, dismissed);
    expect(result.length).toBe(1);
    expect(result[0].title).toBe('Floods in LA');
  });

  it('preserves originalIdx for popup selection', () => {
    const items = [
      { title: 'Skip me', alert_level: 1 }, // no coords
      makeAlert('Alert A', 10, 20),
      makeAlert('Alert B', 30, 40),
    ];
    const result = spreadAlertItems(items, 4, new Set());
    expect(result[0].originalIdx).toBe(1);
    expect(result[1].originalIdx).toBe(2);
  });

  it('adds alertKey and showLine properties', () => {
    const items = [makeAlert('Test Alert', 51.5, -0.1)];
    const result = spreadAlertItems(items, 4, new Set());
    expect(result[0]).toHaveProperty('alertKey');
    expect(result[0]).toHaveProperty('showLine');
    expect(result[0].alertKey).toContain('Test Alert');
  });

  it('spreads overlapping alerts apart (offsets are non-zero for stacked items)', () => {
    // Place 5 alerts at the exact same location — they should be spread apart
    const items = Array.from({ length: 5 }, (_, i) => makeAlert(`Alert ${i}`, 40.0, -74.0));
    const result = spreadAlertItems(items, 8, new Set()); // zoom 8 = close enough to overlap
    const hasNonZeroOffset = result.some(
      (r: any) => Math.abs(r.offsetX) > 1 || Math.abs(r.offsetY) > 1,
    );
    expect(hasNonZeroOffset).toBe(true);
  });
});
