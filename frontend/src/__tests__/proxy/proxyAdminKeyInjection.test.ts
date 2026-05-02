/**
 * Sprint 1C: Proxy admin-key injection coverage tests.
 *
 * Verifies that the server-side catch-all proxy injects X-Admin-Key on the
 * backend leg for routes guarded by require_local_operator:
 *   - /api/mesh/peers  (Sprint 1C addition)
 *   - /api/tools/*     (Sprint 1C addition)
 *   - /api/wormhole/*  (pre-existing, regression)
 *   - /api/settings/*  (pre-existing, regression)
 *
 * Also verifies that:
 *   - non-sensitive mesh paths (e.g. mesh/events) do NOT receive injected key
 *   - browser-supplied x-admin-key is stripped before forwarding (not trusted)
 *   - no-store cache headers are set on all sensitive paths
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';

import { GET as proxyGet, POST as proxyPost } from '@/app/api/[...path]/route';
import {
  POST as postAdminSession,
} from '@/app/api/admin/session/route';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function extractSessionCookie(setCookie: string): string {
  return setCookie.split(';')[0] || '';
}

/** Mint a valid admin session and return the raw cookie string. */
async function mintSession(adminKey: string): Promise<string> {
  const verifyMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  );
  vi.stubGlobal('fetch', verifyMock);

  const req = new NextRequest('http://localhost/api/admin/session', {
    method: 'POST',
    body: JSON.stringify({ adminKey }),
    headers: { 'Content-Type': 'application/json' },
  });
  const res = await postAdminSession(req);
  return extractSessionCookie(res.headers.get('set-cookie') || '');
}

/** Return the Headers object forwarded to the upstream fetch call. */
function capturedHeaders(fetchMock: ReturnType<typeof vi.fn>): Headers {
  const forwarded = fetchMock.mock.calls[0]?.[1];
  return new Headers((forwarded as RequestInit | undefined)?.headers);
}

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

describe('proxy admin-key injection coverage', () => {
  const ADMIN_KEY = 'a-valid-admin-key-that-is-at-least-32chars!!';
  const originalAdminKey = process.env.ADMIN_KEY;
  const originalBackendUrl = process.env.BACKEND_URL;

  beforeEach(() => {
    process.env.ADMIN_KEY = ADMIN_KEY;
    process.env.BACKEND_URL = 'http://127.0.0.1:8000';
    vi.restoreAllMocks();
  });

  afterEach(() => {
    process.env.ADMIN_KEY = originalAdminKey;
    process.env.BACKEND_URL = originalBackendUrl;
    vi.restoreAllMocks();
  });

  // -------------------------------------------------------------------------
  // Sprint 1C: mesh/peers
  // -------------------------------------------------------------------------

  it('GET /api/mesh/peers with valid session injects X-Admin-Key', async () => {
    const cookie = await mintSession(ADMIN_KEY);

    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ peers: [] }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const req = new NextRequest('http://localhost/api/mesh/peers', {
      method: 'GET',
      headers: { cookie },
    });
    const res = await proxyGet(req, {
      params: Promise.resolve({ path: ['mesh', 'peers'] }),
    });

    expect(res.status).toBe(200);
    expect(capturedHeaders(fetchMock).get('X-Admin-Key')).toBe(ADMIN_KEY);
  });

  it('POST /api/mesh/peers with valid session injects X-Admin-Key', async () => {
    const cookie = await mintSession(ADMIN_KEY);

    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const req = new NextRequest('http://localhost/api/mesh/peers', {
      method: 'POST',
      body: JSON.stringify({ url: 'http://peer.example.com:8000' }),
      headers: { cookie, 'Content-Type': 'application/json' },
    });
    const res = await proxyPost(req, {
      params: Promise.resolve({ path: ['mesh', 'peers'] }),
    });

    expect(res.status).toBe(200);
    expect(capturedHeaders(fetchMock).get('X-Admin-Key')).toBe(ADMIN_KEY);
  });

  it('GET /api/mesh/peers applies no-store cache headers', async () => {
    const cookie = await mintSession(ADMIN_KEY);

    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ peers: [] }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const req = new NextRequest('http://localhost/api/mesh/peers', {
      method: 'GET',
      headers: { cookie },
    });
    const res = await proxyGet(req, {
      params: Promise.resolve({ path: ['mesh', 'peers'] }),
    });

    expect(res.headers.get('cache-control')).toContain('no-store');
  });

  // -------------------------------------------------------------------------
  // Sprint 1C: tools/*
  // -------------------------------------------------------------------------

  it('POST /api/tools/shodan/search with valid session injects X-Admin-Key', async () => {
    const cookie = await mintSession(ADMIN_KEY);

    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ results: [] }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const req = new NextRequest('http://localhost/api/tools/shodan/search', {
      method: 'POST',
      body: JSON.stringify({ query: 'port:22' }),
      headers: { cookie, 'Content-Type': 'application/json' },
    });
    const res = await proxyPost(req, {
      params: Promise.resolve({ path: ['tools', 'shodan', 'search'] }),
    });

    expect(res.status).toBe(200);
    expect(capturedHeaders(fetchMock).get('X-Admin-Key')).toBe(ADMIN_KEY);
  });

  it('GET /api/tools/uw/status with valid session injects X-Admin-Key', async () => {
    const cookie = await mintSession(ADMIN_KEY);

    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ configured: true }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const req = new NextRequest('http://localhost/api/tools/uw/status', {
      method: 'GET',
      headers: { cookie },
    });
    const res = await proxyGet(req, {
      params: Promise.resolve({ path: ['tools', 'uw', 'status'] }),
    });

    expect(res.status).toBe(200);
    expect(capturedHeaders(fetchMock).get('X-Admin-Key')).toBe(ADMIN_KEY);
  });

  it('GET /api/tools/shodan/status applies no-store cache headers', async () => {
    const cookie = await mintSession(ADMIN_KEY);

    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ configured: true }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const req = new NextRequest('http://localhost/api/tools/shodan/status', {
      method: 'GET',
      headers: { cookie },
    });
    const res = await proxyGet(req, {
      params: Promise.resolve({ path: ['tools', 'shodan', 'status'] }),
    });

    expect(res.headers.get('cache-control')).toContain('no-store');
  });

  // -------------------------------------------------------------------------
  // Regression: wormhole/* and settings/* unchanged
  // -------------------------------------------------------------------------

  it('GET /api/wormhole/identity with valid session still injects X-Admin-Key', async () => {
    const cookie = await mintSession(ADMIN_KEY);

    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ identity: null }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const req = new NextRequest('http://localhost/api/wormhole/identity', {
      method: 'GET',
      headers: { cookie },
    });
    const res = await proxyGet(req, {
      params: Promise.resolve({ path: ['wormhole', 'identity'] }),
    });

    expect(res.status).toBe(200);
    expect(capturedHeaders(fetchMock).get('X-Admin-Key')).toBe(ADMIN_KEY);
  });

  it('GET /api/settings/node with valid session still injects X-Admin-Key', async () => {
    const cookie = await mintSession(ADMIN_KEY);

    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ node: {} }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const req = new NextRequest('http://localhost/api/settings/node', {
      method: 'GET',
      headers: { cookie },
    });
    const res = await proxyGet(req, {
      params: Promise.resolve({ path: ['settings', 'node'] }),
    });

    expect(res.status).toBe(200);
    expect(capturedHeaders(fetchMock).get('X-Admin-Key')).toBe(ADMIN_KEY);
  });

  // -------------------------------------------------------------------------
  // Non-sensitive mesh paths must NOT receive injected admin key
  // -------------------------------------------------------------------------

  it('GET /api/mesh/events does NOT inject X-Admin-Key', async () => {
    const cookie = await mintSession(ADMIN_KEY);

    const fetchMock = vi.fn().mockResolvedValue(
      new Response('data: {}\n\n', {
        status: 200,
        headers: { 'Content-Type': 'text/event-stream' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const req = new NextRequest('http://localhost/api/mesh/events', {
      method: 'GET',
      headers: { cookie },
    });
    await proxyGet(req, {
      params: Promise.resolve({ path: ['mesh', 'events'] }),
    });

    expect(capturedHeaders(fetchMock).get('X-Admin-Key')).toBeNull();
  });

  it('GET /api/mesh/infonet/feed does NOT inject X-Admin-Key', async () => {
    const cookie = await mintSession(ADMIN_KEY);

    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ items: [] }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const req = new NextRequest('http://localhost/api/mesh/infonet/feed', {
      method: 'GET',
      headers: { cookie },
    });
    await proxyGet(req, {
      params: Promise.resolve({ path: ['mesh', 'infonet', 'feed'] }),
    });

    expect(capturedHeaders(fetchMock).get('X-Admin-Key')).toBeNull();
  });

  // -------------------------------------------------------------------------
  // Browser-supplied x-admin-key is stripped on all paths
  // -------------------------------------------------------------------------

  it('browser-supplied x-admin-key is stripped on mesh/peers path', async () => {
    process.env.ADMIN_KEY = '';

    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ peers: [] }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const req = new NextRequest('http://localhost/api/mesh/peers', {
      method: 'GET',
      headers: { 'x-admin-key': 'browser-injected-key' },
    });
    await proxyGet(req, {
      params: Promise.resolve({ path: ['mesh', 'peers'] }),
    });

    expect(capturedHeaders(fetchMock).get('X-Admin-Key')).toBeNull();
  });

  it('browser-supplied x-admin-key is stripped on tools path', async () => {
    process.env.ADMIN_KEY = '';

    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ configured: false }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const req = new NextRequest('http://localhost/api/tools/shodan/status', {
      method: 'GET',
      headers: { 'x-admin-key': 'browser-injected-key' },
    });
    await proxyGet(req, {
      params: Promise.resolve({ path: ['tools', 'shodan', 'status'] }),
    });

    expect(capturedHeaders(fetchMock).get('X-Admin-Key')).toBeNull();
  });
});
