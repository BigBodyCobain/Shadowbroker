import { afterEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';
import { GET, POST } from '@/app/api/[...path]/route';
import { createAdminSessionToken, clearAdminSessionToken } from '@/lib/server/adminSessionStore';
import { proxy } from '@/proxy';
import { readRequestBody, RequestBodyTooLarge } from '@/lib/server/requestBody';

afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); });

describe('operator request boundary', () => {
  it.each([{}, { origin: 'http://localhost:3000' }])('never grants anonymous callers the server admin key', async (headers) => {
    const upstream = vi.fn().mockResolvedValue(new Response('{}'));
    vi.stubGlobal('fetch', upstream);
    const req = new NextRequest('http://localhost:3000/api/settings/api-keys', { headers });
    await GET(req, { params: Promise.resolve({ path: ['settings', 'api-keys'] }) });
    expect(new Headers(upstream.mock.calls[0][1].headers).has('x-admin-key')).toBe(false);
  });

  it('forwards an authenticated session and explicit CLI credentials', async () => {
    const key = 'audit-synthetic-key';
    vi.stubEnv('ADMIN_KEY', key);
    const token = createAdminSessionToken(key, 60);
    const upstream = vi.fn().mockResolvedValue(new Response('{}'));
    vi.stubGlobal('fetch', upstream);
    try {
      for (const headers of [{ cookie: 'sb_admin_session=' + token }, { 'x-admin-key': key }]) {
        await GET(new NextRequest('http://localhost:3000/api/voice/status', { headers }), {
          params: Promise.resolve({ path: ['voice', 'status'] }),
        });
        expect(new Headers(upstream.mock.calls.at(-1)![1].headers).get('x-admin-key')).toBe(key);
      }
    } finally { clearAdminSessionToken(token); }
  });

  it.each(['/api/voice/models', '/api/voice/opt-in', '/api/admin/session', '/api/settings/api-keys'])('denies hostile-origin requests to %s', (path) => {
    expect(proxy(new NextRequest('http://localhost:3000' + path, {
      headers: { origin: 'https://attacker.example', 'sec-fetch-site': 'cross-site' },
    })).status).toBe(403);
  });

  it('does not trust forwarded hosts or a different scheme', async () => {
    vi.stubGlobal('fetch', vi.fn());
    const req = new NextRequest('http://localhost:3000/api/settings/api-keys', {
      headers: { origin: 'https://localhost:3000', 'x-forwarded-host': 'localhost:3000' },
    });
    expect((await GET(req, { params: Promise.resolve({ path: ['settings', 'api-keys'] }) })).status).toBe(403);
    expect(fetch).not.toHaveBeenCalled();
  });

  it('supports a configured reverse-proxy origin with an authenticated session', async () => {
    vi.stubEnv('SHADOWBROKER_ALLOWED_ORIGINS', 'https://dashboard.example');
    const token = createAdminSessionToken('audit-synthetic-key', 60);
    const upstream = vi.fn().mockResolvedValue(new Response('{}'));
    vi.stubGlobal('fetch', upstream);
    try {
      const result = await GET(new NextRequest('http://frontend:3000/api/voice/status', {
        headers: { origin: 'https://dashboard.example', cookie: 'sb_admin_session=' + token },
      }), { params: Promise.resolve({ path: ['voice', 'status'] }) });
      expect(result.status).toBe(200);
      expect(new Headers(upstream.mock.calls[0][1].headers).get('x-admin-key')).toBe('audit-synthetic-key');
    } finally { clearAdminSessionToken(token); }
  });

  it('limits bytes rather than trusting Content-Length or character count', async () => {
    const req = new Request('http://localhost/api/test', {
      method: 'POST', headers: { 'content-length': '1' }, body: '€€',
    });
    await expect(readRequestBody(req, 5)).rejects.toBeInstanceOf(RequestBodyTooLarge);
  });

  it('rejects a chunked oversized peer request before forwarding', async () => {
    const upstream = vi.fn();
    vi.stubGlobal('fetch', upstream);
    const req = new NextRequest('http://localhost:3000/api/mesh/infonet/peer-push', {
      method: 'POST', body: 'x'.repeat(512 * 1024 + 1),
    });
    expect((await POST(req, { params: Promise.resolve({ path: ['mesh', 'infonet', 'peer-push'] }) })).status).toBe(413);
    expect(upstream).not.toHaveBeenCalled();
  });
});
