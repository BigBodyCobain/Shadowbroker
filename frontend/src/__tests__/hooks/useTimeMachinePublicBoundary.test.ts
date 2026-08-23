import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, renderHook, waitFor } from '@testing-library/react';

import { useTimeMachine } from '@/hooks/useTimeMachine';

const originalFetch = globalThis.fetch;

afterEach(() => {
  cleanup();
  globalThis.fetch = originalFetch;
});

describe('useTimeMachine public boundary', () => {
  it('does not request archived snapshot metadata when auto-refresh is disabled', async () => {
    const fetchMock = vi.fn();
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;

    renderHook(() => useTimeMachine({ autoRefresh: false }));
    await Promise.resolve();

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('loads the hourly index only for an enabled operator surface', async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ hours: [] }), { status: 200 }),
    );
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;

    renderHook(() => useTimeMachine({ autoRefresh: true }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith('/api/ai/timemachine/hourly-index');
    });
  });
});
