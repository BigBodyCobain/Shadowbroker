/**
 * Regression coverage for the auth-bypass chain audited by @tg12 in
 * issues #249, #254, and #255.
 *
 * #249 / #254 — Cross-origin webpages must not have the operator's
 * server-side ADMIN_KEY injected into their forwarded requests. The
 * proxy enforces a CSRF guard by checking the Origin header against
 * the request's own Host header. Same-origin (the dashboard itself),
 * Tauri/native shells (no Origin), and authenticated session cookies
 * are all allowed; cross-origin browser fetches with a foreign Origin
 * are rejected.
 *
 * #255 — Admin session minting must require ADMIN_KEY to be configured
 * AND the supplied key to match exactly. The previous implementation
 * round-tripped to a public backend endpoint (/api/settings/privacy-
 * profile) which always returns 200, so any key value would mint a
 * full admin session when ADMIN_KEY was unset on the server.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';

import { GET as proxyGet, POST as proxyPost } from '@/app/api/[...path]/route';
import { POST as postAdminSession } from '@/app/api/admin/session/route';


function capturedHeaders(fetchMock: ReturnType<typeof vi.fn>): Headers {
  const forwarded = fetchMock.mock.calls[0]?.[1];
  return new Headers((forwarded as RequestInit | undefined)?.headers);
}


describe('proxy CSRF guard on admin-key injection (#249/#254)', () => {
  const ADMIN_KEY = 'env-side-admin-key-32-chars-min!!!!!';
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

  it('cross-origin GET to a sensitive route does NOT inject X-Admin-Key', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } }),
    );
    vi.stubGlobal('fetch', fetchMock);

    // Hostile-webpage CSRF: Origin is a different site than Host.
    const req = new NextRequest('http://localhost:3000/api/wormhole/identity', {
      method: 'GET',
      headers: {
        host: 'localhost:3000',
        origin: 'http://evil.example',
      },
    });
    await proxyGet(req, {
      params: Promise.resolve({ path: ['wormhole', 'identity'] }),
    });

    expect(capturedHeaders(fetchMock).get('X-Admin-Key')).toBeNull();
  });

  it('cross-origin POST to a sensitive route does NOT inject X-Admin-Key', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const req = new NextRequest('http://localhost:3000/api/wormhole/identity/bootstrap', {
      method: 'POST',
      body: '{}',
      headers: {
        host: 'localhost:3000',
        origin: 'http://attacker.example',
        'content-type': 'application/json',
      },
    });
    await proxyPost(req, {
      params: Promise.resolve({ path: ['wormhole', 'identity', 'bootstrap'] }),
    });

    expect(capturedHeaders(fetchMock).get('X-Admin-Key')).toBeNull();
  });

  it('same-origin request (Origin matches Host) DOES inject X-Admin-Key', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const req = new NextRequest('http://localhost:3000/api/wormhole/identity', {
      method: 'GET',
      headers: {
        host: 'localhost:3000',
        origin: 'http://localhost:3000',
      },
    });
    await proxyGet(req, {
      params: Promise.resolve({ path: ['wormhole', 'identity'] }),
    });

    expect(capturedHeaders(fetchMock).get('X-Admin-Key')).toBe(ADMIN_KEY);
  });

  it('same-origin request behind a reverse proxy uses X-Forwarded-Host for injection', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const req = new NextRequest('http://frontend:3000/api/settings/api-keys', {
      method: 'GET',
      headers: {
        host: 'frontend:3000',
        origin: 'https://shadowbroker.example',
        'x-forwarded-host': 'shadowbroker.example',
      },
    });
    await proxyGet(req, {
      params: Promise.resolve({ path: ['settings', 'api-keys'] }),
    });

    expect(capturedHeaders(fetchMock).get('X-Admin-Key')).toBe(ADMIN_KEY);
  });

  it('same-origin request behind a Docker bridge proxy can use a private Host with X-Forwarded-Host', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const req = new NextRequest('http://172.18.0.3:3000/api/settings/api-keys', {
      method: 'GET',
      headers: {
        host: '172.18.0.3:3000',
        origin: 'https://shadowbroker.example',
        'x-forwarded-host': 'shadowbroker.example',
      },
    });
    await proxyGet(req, {
      params: Promise.resolve({ path: ['settings', 'api-keys'] }),
    });

    expect(capturedHeaders(fetchMock).get('X-Admin-Key')).toBe(ADMIN_KEY);
  });

  it('same-origin request behind a reverse proxy uses Forwarded host for injection', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const req = new NextRequest('http://frontend:3000/api/tools/shodan/status', {
      method: 'GET',
      headers: {
        host: 'frontend:3000',
        origin: 'https://shadowbroker.example',
        forwarded: 'for=172.18.0.1;proto=https;host="shadowbroker.example"',
      },
    });
    await proxyGet(req, {
      params: Promise.resolve({ path: ['tools', 'shodan', 'status'] }),
    });

    expect(capturedHeaders(fetchMock).get('X-Admin-Key')).toBe(ADMIN_KEY);
  });

  it('cross-origin request cannot spoof same-origin with X-Forwarded-Host on a public Host', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const req = new NextRequest('https://shadowbroker.example/api/settings/api-keys', {
      method: 'GET',
      headers: {
        host: 'shadowbroker.example',
        origin: 'https://evil.example',
        'x-forwarded-host': 'evil.example',
      },
    });
    await proxyGet(req, {
      params: Promise.resolve({ path: ['settings', 'api-keys'] }),
    });

    expect(capturedHeaders(fetchMock).get('X-Admin-Key')).toBeNull();
  });

  it('cross-origin request cannot spoof same-origin with X-Forwarded-Host on localhost', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const req = new NextRequest('http://localhost:3000/api/settings/api-keys', {
      method: 'GET',
      headers: {
        host: 'localhost:3000',
        origin: 'https://evil.example',
        'x-forwarded-host': 'evil.example',
      },
    });
    await proxyGet(req, {
      params: Promise.resolve({ path: ['settings', 'api-keys'] }),
    });

    expect(capturedHeaders(fetchMock).get('X-Admin-Key')).toBeNull();
  });

  it('no Origin header (native shell, server-to-server, curl) DOES inject X-Admin-Key', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const req = new NextRequest('http://localhost:3000/api/settings/wormhole', {
      method: 'GET',
      headers: {
        host: 'localhost:3000',
        // no Origin
      },
    });
    await proxyGet(req, {
      params: Promise.resolve({ path: ['settings', 'wormhole'] }),
    });

    expect(capturedHeaders(fetchMock).get('X-Admin-Key')).toBe(ADMIN_KEY);
  });

  it('GET /api/refresh without Origin does NOT receive env ADMIN_KEY fallback', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response('{}', { status: 403, headers: { 'Content-Type': 'application/json' } }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const req = new NextRequest('http://localhost:3000/api/refresh', {
      method: 'GET',
      headers: {
        host: 'localhost:3000',
        // no Origin
      },
    });
    await proxyGet(req, {
      params: Promise.resolve({ path: ['refresh'] }),
    });

    expect(capturedHeaders(fetchMock).get('X-Admin-Key')).toBeNull();
  });

  it('GET /api/refresh with same-origin Origin still receives env ADMIN_KEY fallback', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const req = new NextRequest('http://localhost:3000/api/refresh', {
      method: 'GET',
      headers: {
        host: 'localhost:3000',
        origin: 'http://localhost:3000',
      },
    });
    await proxyGet(req, {
      params: Promise.resolve({ path: ['refresh'] }),
    });

    expect(capturedHeaders(fetchMock).get('X-Admin-Key')).toBe(ADMIN_KEY);
  });

  it('cross-origin request with a valid session cookie STILL injects (cookie auth wins)', async () => {
    // Mint a session first (against the real handler).
    const mintReq = new NextRequest('http://localhost:3000/api/admin/session', {
      method: 'POST',
      body: JSON.stringify({ adminKey: ADMIN_KEY }),
      headers: {
        host: 'localhost:3000',
        'content-type': 'application/json',
      },
    });
    const mintRes = await postAdminSession(mintReq);
    const cookieHeader = mintRes.headers.get('set-cookie') || '';
    const cookie = cookieHeader.split(';')[0];

    const fetchMock = vi.fn().mockResolvedValue(
      new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } }),
    );
    vi.stubGlobal('fetch', fetchMock);

    // Now hit a sensitive route from a foreign Origin but WITH the cookie.
    // Since the cookie itself is SameSite=strict, a real cross-origin
    // browser fetch wouldn't carry it — but if the operator deliberately
    // forwards their session (e.g. CLI tool), it should work.
    const req = new NextRequest('http://localhost:3000/api/wormhole/identity', {
      method: 'GET',
      headers: {
        host: 'localhost:3000',
        origin: 'http://evil.example',
        cookie,
      },
    });
    await proxyGet(req, {
      params: Promise.resolve({ path: ['wormhole', 'identity'] }),
    });

    expect(capturedHeaders(fetchMock).get('X-Admin-Key')).toBe(ADMIN_KEY);
  });

  it('malformed Origin header is treated as not-same-origin (conservative)', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const req = new NextRequest('http://localhost:3000/api/wormhole/identity', {
      method: 'GET',
      headers: {
        host: 'localhost:3000',
        origin: 'not-a-real-origin',
      },
    });
    await proxyGet(req, {
      params: Promise.resolve({ path: ['wormhole', 'identity'] }),
    });

    expect(capturedHeaders(fetchMock).get('X-Admin-Key')).toBeNull();
  });

  it('cross-origin to a non-sensitive route is unaffected (no injection either way)', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } }),
    );
    vi.stubGlobal('fetch', fetchMock);

    // /api/health is not sensitive — no admin-key injection happens at all.
    const req = new NextRequest('http://localhost:3000/api/health', {
      method: 'GET',
      headers: {
        host: 'localhost:3000',
        origin: 'http://evil.example',
      },
    });
    await proxyGet(req, {
      params: Promise.resolve({ path: ['health'] }),
    });

    expect(capturedHeaders(fetchMock).get('X-Admin-Key')).toBeNull();
  });
});


describe('admin session minting refuses arbitrary keys when ADMIN_KEY unset (#255)', () => {
  const originalAdminKey = process.env.ADMIN_KEY;
  const originalBackendUrl = process.env.BACKEND_URL;

  beforeEach(() => {
    delete process.env.ADMIN_KEY;
    process.env.BACKEND_URL = 'http://127.0.0.1:8000';
    vi.restoreAllMocks();
  });

  afterEach(() => {
    process.env.ADMIN_KEY = originalAdminKey;
    process.env.BACKEND_URL = originalBackendUrl;
    vi.restoreAllMocks();
  });

  it('refuses to mint a session when ADMIN_KEY is unset on the server', async () => {
    // Even if the (previously-relied-on) public endpoint returned 200,
    // the new logic must not accept the key — it does local validation only.
    const fetchMock = vi.fn().mockResolvedValue(
      new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const req = new NextRequest('http://localhost:3000/api/admin/session', {
      method: 'POST',
      body: JSON.stringify({ adminKey: 'literally-anything-an-attacker-sends' }),
      headers: { 'content-type': 'application/json' },
    });
    const res = await postAdminSession(req);

    expect(res.status).toBe(403);
    const body = await res.json();
    expect(body.ok).toBe(false);
    expect(String(body.detail)).toMatch(/no admin key configured/i);

    // No session cookie should have been set
    expect(res.headers.get('set-cookie')).toBeNull();

    // The buggy round-trip to the public endpoint must no longer happen
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('refuses an empty key with 400 (Missing admin key)', async () => {
    const req = new NextRequest('http://localhost:3000/api/admin/session', {
      method: 'POST',
      body: JSON.stringify({ adminKey: '' }),
      headers: { 'content-type': 'application/json' },
    });
    const res = await postAdminSession(req);
    expect(res.status).toBe(400);
  });
});


describe('admin session minting still works when ADMIN_KEY is set (#255 regression)', () => {
  const ADMIN_KEY = 'configured-admin-key-32-chars-min!!!!';
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

  it('mints a session when the supplied key matches the configured ADMIN_KEY', async () => {
    const req = new NextRequest('http://localhost:3000/api/admin/session', {
      method: 'POST',
      body: JSON.stringify({ adminKey: ADMIN_KEY }),
      headers: { 'content-type': 'application/json' },
    });
    const res = await postAdminSession(req);

    expect(res.status).toBe(200);
    expect(res.headers.get('set-cookie')).toBeTruthy();
  });

  it('rejects a non-matching key with 403', async () => {
    const req = new NextRequest('http://localhost:3000/api/admin/session', {
      method: 'POST',
      body: JSON.stringify({ adminKey: 'wrong-key-attempted-by-attacker' }),
      headers: { 'content-type': 'application/json' },
    });
    const res = await postAdminSession(req);

    expect(res.status).toBe(403);
    expect(res.headers.get('set-cookie')).toBeNull();
  });

  it('does NOT round-trip to a backend endpoint for verification (local-only validation)', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const req = new NextRequest('http://localhost:3000/api/admin/session', {
      method: 'POST',
      body: JSON.stringify({ adminKey: ADMIN_KEY }),
      headers: { 'content-type': 'application/json' },
    });
    await postAdminSession(req);

    // The previous implementation did a fetch to verify against the
    // backend; the fix removes that round-trip because the backend
    // endpoint it called was public anyway. Local string-compare suffices.
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
