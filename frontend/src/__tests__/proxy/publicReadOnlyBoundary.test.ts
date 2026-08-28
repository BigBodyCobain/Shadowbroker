import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';

import { GET as proxyGet, POST as proxyPost } from '@/app/api/[...path]/route';

describe('public read-only API boundary', () => {
  const originalPublicReadOnly = process.env.NEXT_PUBLIC_PUBLIC_READ_ONLY;

  beforeEach(() => {
    process.env.NEXT_PUBLIC_PUBLIC_READ_ONLY = 'false';
    vi.restoreAllMocks();
  });

  afterEach(() => {
    process.env.NEXT_PUBLIC_PUBLIC_READ_ONLY = originalPublicReadOnly;
    vi.restoreAllMocks();
  });

  it.each([
    ['GET', ['sar', 'aois']],
    ['GET', ['sar', 'status']],
    ['GET', ['ai', 'pins', 'geojson']],
    ['POST', ['viewport']],
    ['POST', ['mesh', 'vote']],
  ] as const)('rejects public %s /api/%s before forwarding', async (method, path) => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    const req = new NextRequest(`https://shadow.qdev.run/api/${path.join('/')}`, {
      method,
      headers: { host: 'shadow.qdev.run' },
    });

    const response = method === 'GET'
      ? await proxyGet(req, { params: Promise.resolve({ path: [...path] }) })
      : await proxyPost(req, { params: Promise.resolve({ path: [...path] }) });

    expect(response.status).toBe(403);
    expect(response.headers.get('cache-control')).toContain('no-store');
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('uses the trusted forwarded public host when the direct host is internal', async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    const req = new NextRequest('http://frontend:3000/api/sar/aois', {
      headers: {
        host: 'frontend:3000',
        'x-forwarded-host': 'shadow.qdev.run',
      },
    });

    const response = await proxyGet(req, { params: Promise.resolve({ path: ['sar', 'aois'] }) });

    expect(response.status).toBe(403);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('keeps the local operator host available to the backend', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response('{"ok":true}', { status: 200, headers: { 'Content-Type': 'application/json' } }),
    );
    vi.stubGlobal('fetch', fetchMock);
    const req = new NextRequest('http://localhost:3000/api/sar/aois', {
      headers: { host: 'localhost:3000' },
    });

    const response = await proxyGet(req, { params: Promise.resolve({ path: ['sar', 'aois'] }) });

    expect(response.status).toBe(200);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
