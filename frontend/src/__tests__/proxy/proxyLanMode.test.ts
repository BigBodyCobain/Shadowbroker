/**
 * LAN mode: the proxy must not hand the server-side ADMIN_KEY to browsers that
 * have not signed in, because other devices on the network can reach it and
 * X-Forwarded-For cannot tell them apart from the local browser.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';

import { GET as proxyGet } from '@/app/api/[...path]/route';
import { POST as postAdminSession } from '@/app/api/admin/session/route';

const ADMIN_KEY = 'a-valid-admin-key-that-is-at-least-32chars!!';

function upstreamOk() {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  );
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function forwardedAdminKey(fetchMock: ReturnType<typeof vi.fn>): string | null {
  const init = fetchMock.mock.calls[0]?.[1] as RequestInit | undefined;
  return new Headers(init?.headers).get('X-Admin-Key');
}

async function dashboardGet(cookie = '') {
  const req = new NextRequest('http://192.168.1.20:3000/api/wormhole/dm/contacts', {
    method: 'GET',
    headers: {
      origin: 'http://192.168.1.20:3000',
      host: '192.168.1.20:3000',
      // A LAN device can claim to be local; the proxy must not care.
      'x-forwarded-for': '127.0.0.1',
      ...(cookie ? { cookie } : {}),
    },
  });
  return proxyGet(req, { params: Promise.resolve({ path: ['wormhole', 'dm', 'contacts'] }) });
}

describe('proxy LAN mode', () => {
  const saved = {
    admin: process.env.ADMIN_KEY,
    lan: process.env.SHADOWBROKER_LAN_MODE,
    backend: process.env.BACKEND_URL,
  };

  beforeEach(() => {
    process.env.ADMIN_KEY = ADMIN_KEY;
    process.env.BACKEND_URL = 'http://127.0.0.1:8000';
    vi.restoreAllMocks();
  });

  afterEach(() => {
    process.env.ADMIN_KEY = saved.admin;
    process.env.SHADOWBROKER_LAN_MODE = saved.lan;
    process.env.BACKEND_URL = saved.backend;
    vi.restoreAllMocks();
  });

  it('injects the env admin key for same-origin requests outside LAN mode', async () => {
    delete process.env.SHADOWBROKER_LAN_MODE;
    const fetchMock = upstreamOk();
    await dashboardGet();
    expect(forwardedAdminKey(fetchMock)).toBe(ADMIN_KEY);
  });

  it('withholds the env admin key from browsers that have not signed in', async () => {
    process.env.SHADOWBROKER_LAN_MODE = '1';
    const fetchMock = upstreamOk();
    await dashboardGet();
    expect(forwardedAdminKey(fetchMock)).toBeNull();
  });

  it('still forwards the key for a signed-in admin session', async () => {
    process.env.SHADOWBROKER_LAN_MODE = '1';
    upstreamOk();
    const login = await postAdminSession(
      new NextRequest('http://192.168.1.20:3000/api/admin/session', {
        method: 'POST',
        body: JSON.stringify({ adminKey: ADMIN_KEY }),
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    const cookie = (login.headers.get('set-cookie') || '').split(';')[0];
    expect(cookie).toContain('sb_admin_session=');

    const fetchMock = upstreamOk();
    await dashboardGet(cookie);
    expect(forwardedAdminKey(fetchMock)).toBe(ADMIN_KEY);
  });

  it('rejects a wrong admin key at sign-in', async () => {
    upstreamOk();
    const login = await postAdminSession(
      new NextRequest('http://192.168.1.20:3000/api/admin/session', {
        method: 'POST',
        body: JSON.stringify({ adminKey: `${ADMIN_KEY.slice(0, -1)}?` }),
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    expect(login.status).toBeGreaterThanOrEqual(400);
    expect(login.headers.get('set-cookie') || '').not.toContain('sb_admin_session=s');
  });
});
