import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import React from 'react';

import OperationalStatus from '@/components/OperationalStatus';

const originalFetch = globalThis.fetch;

afterEach(() => {
  cleanup();
  globalThis.fetch = originalFetch;
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
});
