import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, render, screen } from '@testing-library/react';
import React from 'react';

import OperationalStatus from '@/components/OperationalStatus';

const originalFetch = globalThis.fetch;

afterEach(() => {
  cleanup();
  globalThis.fetch = originalFetch;
  vi.useRealTimers();
});

describe('OperationalStatus', () => {
  it('keeps the current health result when Strict Mode leaves its first probe pending', async () => {
    let requestCount = 0;
    const fetchMock = vi.fn((_input: RequestInfo | URL) => {
      requestCount += 1;
      if (requestCount === 1) {
        return new Promise<Response>(() => undefined);
      }
      return Promise.resolve(
        new Response(JSON.stringify({ status: 'error', sources: { ships: 7 } }), { status: 200 }),
      );
    });
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;

    render(
      <React.StrictMode>
        <OperationalStatus />
      </React.StrictMode>,
    );

    expect(await screen.findByText(/Data service degraded/)).toBeTruthy();
    expect(screen.queryByText(/Data service is unavailable/)).toBeNull();
  });

  it('refreshes the health result every 30 seconds', async () => {
    vi.useFakeTimers();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ status: 'ok', sources: { ships: 7 } }), { status: 200 }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ status: 'error', sources: { ships: 0 } }), { status: 200 }),
      );
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;

    render(<OperationalStatus />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByText(/Data service available/)).toBeTruthy();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(screen.getByText(/Data service degraded/)).toBeTruthy();
  });

  it('makes a stale shared feed explicit', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          status: 'degraded',
          sources: { flights: 12 },
          qazpipe: { available: true, stale: true },
        }),
        { status: 200 },
      ),
    ) as unknown as typeof globalThis.fetch;

    render(<OperationalStatus />);

    expect(await screen.findByText(/Shared data feed stale/)).toBeTruthy();
  });
});
