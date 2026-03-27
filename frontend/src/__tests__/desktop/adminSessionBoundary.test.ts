import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';

import { GET as proxyGet } from '@/app/api/[...path]/route';
import {
  DELETE as deleteAdminSession,
  GET as getAdminSession,
  POST as postAdminSession,
} from '@/app/api/admin/session/route';

function extractSessionCookie(setCookie: string): string {
  return setCookie.split(';')[0] || '';
}

describe('admin/session boundary hardening', () => {
  const originalAdminKey = process.env.ADMIN_KEY;
  const originalBackendUrl = process.env.BACKEND_URL;

  beforeEach(() => {
    process.env.ADMIN_KEY = 'top-secret';
    process.env.BACKEND_URL = 'http://127.0.0.1:8000';
    vi.restoreAllMocks();
  });

  afterEach(() => {
    process.env.ADMIN_KEY = originalAdminKey;
    process.env.BACKEND_URL = originalBackendUrl;
    vi.restoreAllMocks();
  });

  it('rejects invalid admin keys before minting a session', async () => {
    const req = new NextRequest('http://localhost/api/admin/session', {
      method: 'POST',
      body: JSON.stringify({ adminKey: 'wrong-key' }),
      headers: { 'Content-Type': 'application/json' },
    });

    const res = await postAdminSession(req);
    const body = await res.json();

    expect(res.status).toBe(403);
    expect(body.ok).toBe(false);
    expect(body.detail).toBe('Invalid admin key');
    expect(res.headers.get('set-cookie')).toBeNull();
  });

  it('accepts a verified admin key and reports the minted session as present', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const req = new NextRequest('http://localhost/api/admin/session', {
      method: 'POST',
      body: JSON.stringify({ adminKey: 'top-secret' }),
      headers: { 'Content-Type': 'application/json' },
    });

    const res = await postAdminSession(req);
    const cookie = extractSessionCookie(res.headers.get('set-cookie') || '');

    expect(res.status).toBe(200);
    expect(cookie).toContain('sb_admin_session=');
    expect(res.headers.get('cache-control')).toContain('no-store');
    expect(fetchMock).toHaveBeenCalledTimes(1);

    const getReq = new NextRequest('http://localhost/api/admin/session', {
      method: 'GET',
      headers: { cookie },
    });
    const getRes = await getAdminSession(getReq);
    const getBody = await getRes.json();

    expect(getBody.ok).toBe(true);
    expect(getBody.hasSession).toBe(true);
    expect(getRes.headers.get('cache-control')).toContain('no-store');

    const deleteReq = new NextRequest('http://localhost/api/admin/session', {
      method: 'DELETE',
      headers: { cookie },
    });
    const deleteRes = await deleteAdminSession(deleteReq);
    expect(deleteRes.status).toBe(200);
    expect(deleteRes.headers.get('cache-control')).toContain('no-store');
  });

  it('invalidates the previous admin session token when a new one is minted', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const firstReq = new NextRequest('http://localhost/api/admin/session', {
      method: 'POST',
      body: JSON.stringify({ adminKey: 'top-secret' }),
      headers: { 'Content-Type': 'application/json' },
    });
    const firstRes = await postAdminSession(firstReq);
    const firstCookie = extractSessionCookie(firstRes.headers.get('set-cookie') || '');

    const secondReq = new NextRequest('http://localhost/api/admin/session', {
      method: 'POST',
      body: JSON.stringify({ adminKey: 'top-secret' }),
      headers: {
        'Content-Type': 'application/json',
        cookie: firstCookie,
      },
    });
    const secondRes = await postAdminSession(secondReq);
    const secondCookie = extractSessionCookie(secondRes.headers.get('set-cookie') || '');

    expect(secondCookie).toContain('sb_admin_session=');
    expect(secondCookie).not.toBe(firstCookie);

    const oldSessionCheck = await getAdminSession(
      new NextRequest('http://localhost/api/admin/session', {
        method: 'GET',
        headers: { cookie: firstCookie },
      }),
    );
    const oldBody = await oldSessionCheck.json();
    expect(oldBody.hasSession).toBe(false);

    const newSessionCheck = await getAdminSession(
      new NextRequest('http://localhost/api/admin/session', {
        method: 'GET',
        headers: { cookie: secondCookie },
      }),
    );
    const newBody = await newSessionCheck.json();
    expect(newBody.hasSession).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('rejects session minting when frontend admin key is set but backend has no configured admin key', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Forbidden — admin key not configured' }), {
        status: 403,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const req = new NextRequest('http://localhost/api/admin/session', {
      method: 'POST',
      body: JSON.stringify({ adminKey: 'top-secret' }),
      headers: { 'Content-Type': 'application/json' },
    });

    const res = await postAdminSession(req);
    const body = await res.json();

    expect(res.status).toBe(403);
    expect(body.ok).toBe(false);
    expect(body.detail).toBe('Forbidden — admin key not configured');
    expect(res.headers.get('set-cookie')).toBeNull();
  });

  it('does not forward raw x-admin-key headers through the sensitive proxy path', async () => {
    process.env.ADMIN_KEY = '';
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const req = new NextRequest('http://localhost/api/settings/api-keys', {
      method: 'GET',
      headers: { 'x-admin-key': 'browser-supplied-key' },
    });

    const res = await proxyGet(req, { params: Promise.resolve({ path: ['settings', 'api-keys'] }) });
    const body = await res.json();

    expect(res.status).toBe(200);
    expect(body.ok).toBe(true);
    expect(res.headers.get('cache-control')).toContain('no-store');

    const forwarded = fetchMock.mock.calls[0]?.[1];
    const forwardedHeaders = new Headers((forwarded as RequestInit | undefined)?.headers);
    expect(forwardedHeaders.get('X-Admin-Key')).toBeNull();
  });

  it('forwards the minted admin session to sensitive proxy paths and preserves upstream errors', async () => {
    const verifyMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', verifyMock);

    const sessionReq = new NextRequest('http://localhost/api/admin/session', {
      method: 'POST',
      body: JSON.stringify({ adminKey: 'top-secret' }),
      headers: { 'Content-Type': 'application/json' },
    });
    const sessionRes = await postAdminSession(sessionReq);
    const cookie = extractSessionCookie(sessionRes.headers.get('set-cookie') || '');

    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Forbidden upstream' }), {
        status: 403,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const req = new NextRequest('http://localhost/api/wormhole/identity', {
      method: 'GET',
      headers: { cookie },
    });

    const res = await proxyGet(req, { params: Promise.resolve({ path: ['wormhole', 'identity'] }) });
    const body = await res.json();

    expect(res.status).toBe(403);
    expect(body.detail).toBe('Forbidden upstream');
    expect(res.headers.get('cache-control')).toContain('no-store');

    const forwarded = fetchMock.mock.calls[0]?.[1];
    const forwardedHeaders = new Headers((forwarded as RequestInit | undefined)?.headers);
    expect(forwardedHeaders.get('X-Admin-Key')).toBe('top-secret');
  });
});
