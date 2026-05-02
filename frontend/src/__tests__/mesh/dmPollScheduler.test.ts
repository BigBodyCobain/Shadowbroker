import { beforeEach, describe, expect, it, vi } from 'vitest';

function makeStorage() {
  const values = new Map<string, string>();
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => void values.set(key, value),
    removeItem: (key: string) => void values.delete(key),
    clear: () => void values.clear(),
  };
}

describe('dmPollScheduler', () => {
  beforeEach(() => {
    vi.resetModules();
    Object.defineProperty(globalThis, 'localStorage', {
      value: makeStorage(),
      configurable: true,
      writable: true,
    });
    Object.defineProperty(globalThis, 'sessionStorage', {
      value: makeStorage(),
      configurable: true,
      writable: true,
    });
  });

  describe('jitteredPollDelay', () => {
    it('returns a value within the default jitter band', async () => {
      const { jitteredPollDelay } = await import('@/lib/dmPollScheduler');
      const base = 12_000;
      // r=0 → factor=0.8 → 9600; r=1 → factor=1.4 → 16800
      expect(jitteredPollDelay(base, { profile: 'default', random: 0 })).toBe(9600);
      expect(jitteredPollDelay(base, { profile: 'default', random: 1 })).toBe(16800);
    });

    it('high-privacy band is wider than default', async () => {
      const { jitteredPollDelay } = await import('@/lib/dmPollScheduler');
      const base = 12_000;
      const defaultMin = jitteredPollDelay(base, { profile: 'default', random: 0 });
      const defaultMax = jitteredPollDelay(base, { profile: 'default', random: 1 });
      const highMin = jitteredPollDelay(base, { profile: 'high', random: 0 });
      const highMax = jitteredPollDelay(base, { profile: 'high', random: 1 });

      const defaultRange = defaultMax - defaultMin;
      const highRange = highMax - highMin;
      expect(highRange).toBeGreaterThan(defaultRange);
    });

    it('never returns the exact base interval across random inputs', async () => {
      const { jitteredPollDelay } = await import('@/lib/dmPollScheduler');
      const base = 12_000;
      const samples = Array.from({ length: 100 }, (_, i) =>
        jitteredPollDelay(base, { profile: 'default', random: i / 100 }),
      );
      // At most one value could accidentally equal base; the set should be diverse
      const unique = new Set(samples);
      expect(unique.size).toBeGreaterThan(50);
      // The exact base value corresponds to r ≈ 0.333...; verify it's the only one
      const exactBaseCount = samples.filter((v) => v === base).length;
      expect(exactBaseCount).toBeLessThanOrEqual(1);
    });

    it('reads privacy profile from browser storage when no override', async () => {
      sessionStorage.setItem('sb_privacy_profile', 'high');
      const { jitteredPollDelay } = await import('@/lib/dmPollScheduler');
      const base = 10_000;
      // r=0 with high profile → factor=0.5 → 5000
      expect(jitteredPollDelay(base, { random: 0 })).toBe(5000);
    });

    it('returns positive value for any base and profile', async () => {
      const { jitteredPollDelay } = await import('@/lib/dmPollScheduler');
      for (const profile of ['default', 'high', 'unknown']) {
        for (const r of [0, 0.25, 0.5, 0.75, 1]) {
          const delay = jitteredPollDelay(15_000, { profile, random: r });
          expect(delay).toBeGreaterThan(0);
        }
      }
    });
  });

  describe('catchUpDelay', () => {
    it('returns a value within the default catch-up band', async () => {
      const { catchUpDelay } = await import('@/lib/dmPollScheduler');
      // default: min=2000, max=5000
      expect(catchUpDelay({ profile: 'default', random: 0 })).toBe(2000);
      expect(catchUpDelay({ profile: 'default', random: 1 })).toBe(5000);
    });

    it('high-privacy catch-up delay is longer than default', async () => {
      const { catchUpDelay } = await import('@/lib/dmPollScheduler');
      const defaultMid = catchUpDelay({ profile: 'default', random: 0.5 });
      const highMid = catchUpDelay({ profile: 'high', random: 0.5 });
      expect(highMid).toBeGreaterThan(defaultMid);
    });

    it('catch-up delay is always shorter than normal poll delay', async () => {
      const { jitteredPollDelay, catchUpDelay } = await import('@/lib/dmPollScheduler');
      // Worst-case catch-up (r=1, high) vs best-case normal poll (r=0, default, base=12000)
      const maxCatchUp = catchUpDelay({ profile: 'high', random: 1 });
      const minNormal = jitteredPollDelay(12_000, { profile: 'default', random: 0 });
      expect(maxCatchUp).toBeLessThan(minNormal);
    });

    it('catch-up delay is never zero', async () => {
      const { catchUpDelay } = await import('@/lib/dmPollScheduler');
      for (const profile of ['default', 'high']) {
        const delay = catchUpDelay({ profile, random: 0 });
        expect(delay).toBeGreaterThan(0);
      }
    });
  });

  describe('MAX_CATCHUP_POLLS', () => {
    it('is a small positive integer bounding catch-up bursts', async () => {
      const { MAX_CATCHUP_POLLS } = await import('@/lib/dmPollScheduler');
      expect(MAX_CATCHUP_POLLS).toBeGreaterThanOrEqual(1);
      expect(MAX_CATCHUP_POLLS).toBeLessThanOrEqual(5);
    });
  });

  describe('classifyTick', () => {
    it('catch-up tick skips count refresh', async () => {
      const { classifyTick } = await import('@/lib/dmPollScheduler');
      const result = classifyTick(true, 3, 12_000, { profile: 'default', random: 0.5 });
      expect(result.refreshCount).toBe(false);
      expect(result.newBudget).toBe(2);
    });

    it('normal tick includes count refresh', async () => {
      const { classifyTick } = await import('@/lib/dmPollScheduler');
      const result = classifyTick(false, 3, 12_000, { profile: 'default', random: 0.5 });
      expect(result.refreshCount).toBe(true);
    });

    it('budget exhaustion falls back to normal with count', async () => {
      const { classifyTick } = await import('@/lib/dmPollScheduler');
      // has_more=true but budget=0 → normal tick
      const result = classifyTick(true, 0, 12_000, { profile: 'default', random: 0.5 });
      expect(result.refreshCount).toBe(true);
    });

    it('budget resets after fallback to normal', async () => {
      const { classifyTick, MAX_CATCHUP_POLLS } = await import('@/lib/dmPollScheduler');
      const result = classifyTick(false, 1, 12_000, { profile: 'default', random: 0.5 });
      expect(result.newBudget).toBe(MAX_CATCHUP_POLLS);
    });

    it('catch-up delay is used during catch-up ticks', async () => {
      const { classifyTick, catchUpDelay } = await import('@/lib/dmPollScheduler');
      const opts = { profile: 'default' as const, random: 0.5 };
      const result = classifyTick(true, 2, 12_000, opts);
      expect(result.delay).toBe(catchUpDelay(opts));
    });

    it('normal delay is used during normal ticks', async () => {
      const { classifyTick, jitteredPollDelay } = await import('@/lib/dmPollScheduler');
      const opts = { profile: 'default' as const, random: 0.5 };
      const result = classifyTick(false, 3, 12_000, opts);
      expect(result.delay).toBe(jitteredPollDelay(12_000, opts));
    });
  });

  describe('scheduling contract', () => {
    it('simulated poll loop uses classifyTick for cadence and count decisions', async () => {
      const { classifyTick, catchUpDelay, jitteredPollDelay, MAX_CATCHUP_POLLS } =
        await import('@/lib/dmPollScheduler');

      const ticks: Array<{ delay: number; refreshCount: boolean }> = [];
      let budget = MAX_CATCHUP_POLLS;
      const hasMoreSequence = [true, true, true, true, false, false, true, false];
      const opts = { profile: 'default' as const, random: 0.5 };

      for (const hasMore of hasMoreSequence) {
        const result = classifyTick(hasMore, budget, 12_000, opts);
        budget = result.newBudget;
        ticks.push({ delay: result.delay, refreshCount: result.refreshCount });
      }

      const catchUpValue = catchUpDelay(opts);
      const normalValue = jitteredPollDelay(12_000, opts);

      // First MAX_CATCHUP_POLLS catch-up ticks: short delay, no count
      for (let i = 0; i < MAX_CATCHUP_POLLS; i++) {
        expect(ticks[i].delay).toBe(catchUpValue);
        expect(ticks[i].refreshCount).toBe(false);
      }
      // 4th has_more exceeds budget → normal with count
      expect(ticks[MAX_CATCHUP_POLLS].delay).toBe(normalValue);
      expect(ticks[MAX_CATCHUP_POLLS].refreshCount).toBe(true);
      // Non-has_more ticks: normal with count
      expect(ticks[4].delay).toBe(normalValue);
      expect(ticks[4].refreshCount).toBe(true);
      expect(ticks[5].delay).toBe(normalValue);
      expect(ticks[5].refreshCount).toBe(true);
    });

    it('count is never refreshed during catch-up across a full backlog drain', async () => {
      const { classifyTick, MAX_CATCHUP_POLLS } = await import('@/lib/dmPollScheduler');

      let budget = MAX_CATCHUP_POLLS;
      const countRefreshes: boolean[] = [];

      // Simulate: has_more for exactly budget ticks, then two normal ticks
      const hasMoreSequence = [
        ...Array(MAX_CATCHUP_POLLS).fill(true),
        false,
        false,
      ];
      for (const hasMore of hasMoreSequence) {
        const result = classifyTick(hasMore, budget, 12_000, { profile: 'default', random: 0.5 });
        budget = result.newBudget;
        countRefreshes.push(result.refreshCount);
      }

      // Catch-up ticks should not refresh count
      for (let i = 0; i < MAX_CATCHUP_POLLS; i++) {
        expect(countRefreshes[i]).toBe(false);
      }
      // Normal ticks after catch-up do refresh count
      expect(countRefreshes[MAX_CATCHUP_POLLS]).toBe(true);
      expect(countRefreshes[MAX_CATCHUP_POLLS + 1]).toBe(true);
    });

    it('no fixed cadence is reintroduced by classifyTick', async () => {
      const { classifyTick } = await import('@/lib/dmPollScheduler');
      const delays = new Set<number>();
      for (let r = 0; r < 20; r++) {
        const result = classifyTick(false, 3, 12_000, { profile: 'default', random: r / 20 });
        delays.add(result.delay);
      }
      // All 20 random inputs should produce diverse delays, not a fixed value
      expect(delays.size).toBeGreaterThan(10);
    });
  });
});
