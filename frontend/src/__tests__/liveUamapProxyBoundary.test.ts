import { describe, expect, it } from 'vitest';
import type { NextRequest } from 'next/server';

import { proxy } from '@/proxy';

function request(path: string, headers: Record<string, string>): NextRequest {
  return {
    nextUrl: { pathname: path },
    headers: new Headers(headers),
  } as unknown as NextRequest;
}

describe('LiveUAMap privileged proxy boundary', () => {
  it('rejects a cross-site browser opt-in request', async () => {
    const response = proxy(
      request('/api/liveuamap/scraper-opt-in', {
        host: 'localhost:3000',
        origin: 'https://evil.example',
        'sec-fetch-site': 'cross-site',
      }),
    );

    expect(response.status).toBe(403);
    await expect(response.json()).resolves.toEqual({
      detail: 'Cross-origin privileged request denied',
    });
  });

  it('allows the same-origin dashboard request without adding page CSP', () => {
    const response = proxy(
      request('/api/liveuamap/scraper-opt-in', {
        host: 'localhost:3000',
        origin: 'http://localhost:3000',
        'sec-fetch-site': 'same-origin',
      }),
    );

    expect(response.status).toBe(200);
    expect(response.headers.get('content-security-policy')).toBeNull();
  });

  it('also protects the provider status endpoint from cross-site browser reads', () => {
    const response = proxy(
      request('/api/liveuamap/scraper-status', {
        host: 'localhost:3000',
        'sec-fetch-site': 'cross-site',
      }),
    );

    expect(response.status).toBe(403);
  });
});
