import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { VIEWPORT_COMMITTED_EVENT } from '@/components/map/hooks/useViewportBounds';
import { setLiveDataBounds } from '@/lib/liveDataViewport';

describe('viewport fast refetch wiring', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    setLiveDataBounds({ south: 10, west: 20, north: 12, east: 22 });
  });

  afterEach(() => {
    setLiveDataBounds(null);
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('VIEWPORT_COMMITTED_EVENT is a stable custom event name', () => {
    expect(VIEWPORT_COMMITTED_EVENT).toBe('shadowbroker:viewport-committed');
    const handler = vi.fn();
    window.addEventListener(VIEWPORT_COMMITTED_EVENT, handler);
    window.dispatchEvent(new CustomEvent(VIEWPORT_COMMITTED_EVENT));
    expect(handler).toHaveBeenCalledTimes(1);
    window.removeEventListener(VIEWPORT_COMMITTED_EVENT, handler);
  });

  it('liveDataBoundsKey changes when the operator pans to a new region', async () => {
    const { liveDataBoundsKey } = await import('@/lib/liveDataViewport');
    const before = liveDataBoundsKey();
    setLiveDataBounds({ south: 20, west: -130, north: 55, east: -60 });
    const after = liveDataBoundsKey();
    expect(before).not.toBe(after);
    expect(after).toBe('20,-130,55,-60');
  });
});
