// @ts-nocheck
/**
 * Issue #298 (tg12): Sentinel credentials must no longer live in browser
 * storage, and the proxy calls must not forward them in request bodies.
 * These tests pin both invariants on ``lib/sentinelHub``:
 *
 *  1. ``migrateLegacySentinelBrowserKeys()`` clears the legacy keys
 *     idempotently and reports what it cleared.
 *  2. ``fetchSentinelTile()`` and ``getSentinelToken()`` POST WITHOUT
 *     ``client_id`` or ``client_secret`` in the body — the backend
 *     resolves credentials from its ``.env``. A future refactor that
 *     accidentally re-introduces browser-storage reads (e.g. by
 *     restoring ``getSentinelCredentials()`` and forwarding it) gets a
 *     loud test failure here rather than a silent privacy regression.
 *  3. ``checkBackendSentinelStatus()`` queries ``/api/settings/api-keys``
 *     and returns true only when both Sentinel keys report ``is_set``.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  migrateLegacySentinelBrowserKeys,
  fetchSentinelTile,
  getSentinelToken,
  checkBackendSentinelStatus,
  refreshSentinelStatus,
} from '@/lib/sentinelHub';

const originalFetch = globalThis.fetch;

describe('lib/sentinelHub — issue #298 server-side credentials', () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
    refreshSentinelStatus();
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    window.localStorage.clear();
    window.sessionStorage.clear();
    refreshSentinelStatus();
  });

  describe('migrateLegacySentinelBrowserKeys', () => {
    it('clears legacy localStorage keys and reports what it cleared', () => {
      window.localStorage.setItem('sb_sentinel_client_id', 'sh-leaked-id');
      window.localStorage.setItem('sb_sentinel_client_secret', 'leaked-secret');
      window.localStorage.setItem('sb_sentinel_instance_id', 'leaked-instance');

      const result = migrateLegacySentinelBrowserKeys();

      expect(window.localStorage.getItem('sb_sentinel_client_id')).toBeNull();
      expect(window.localStorage.getItem('sb_sentinel_client_secret')).toBeNull();
      expect(window.localStorage.getItem('sb_sentinel_instance_id')).toBeNull();
      expect(result.cleared.sort()).toEqual([
        'sb_sentinel_client_id',
        'sb_sentinel_client_secret',
        'sb_sentinel_instance_id',
      ].sort());
    });

    it('clears sessionStorage too (privacy-strict mode used to put them there)', () => {
      window.sessionStorage.setItem('sb_sentinel_client_id', 'sh-session-id');
      window.sessionStorage.setItem('sb_sentinel_client_secret', 'session-secret');

      const result = migrateLegacySentinelBrowserKeys();

      expect(window.sessionStorage.getItem('sb_sentinel_client_id')).toBeNull();
      expect(window.sessionStorage.getItem('sb_sentinel_client_secret')).toBeNull();
      expect(result.cleared).toContain('sb_sentinel_client_id');
      expect(result.cleared).toContain('sb_sentinel_client_secret');
    });

    it('is idempotent — calling it on a clean store reports nothing cleared', () => {
      const result = migrateLegacySentinelBrowserKeys();
      expect(result.cleared).toEqual([]);
    });
  });

  describe('proxy requests no longer forward credentials', () => {
    it('fetchSentinelTile POSTs without client_id/client_secret in the body', async () => {
      // Plant credentials in browser storage to prove they would NOT be
      // picked up even if present. Pre-#298, this would have been read
      // from localStorage and posted in the body.
      window.localStorage.setItem('sb_sentinel_client_id', 'sh-leaked-id');
      window.localStorage.setItem('sb_sentinel_client_secret', 'leaked-secret');

      const fetchMock = vi.fn(async () => new Response(new ArrayBuffer(0), { status: 200 }));
      globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;

      await fetchSentinelTile(6, 30, 20, 'TRUE-COLOR', '2026-01-01');

      expect(fetchMock).toHaveBeenCalledTimes(1);
      const [, init] = fetchMock.mock.calls[0] as [unknown, RequestInit];
      const body = JSON.parse(String(init.body));
      expect(body).not.toHaveProperty('client_id');
      expect(body).not.toHaveProperty('client_secret');
      // Sanity: the legitimate fields are still there.
      expect(body).toMatchObject({ preset: 'TRUE-COLOR', date: '2026-01-01', z: 6, x: 30, y: 20 });
    });

    it('getSentinelToken POSTs with an empty form body (backend uses env)', async () => {
      window.localStorage.setItem('sb_sentinel_client_id', 'sh-leaked-id');
      window.localStorage.setItem('sb_sentinel_client_secret', 'leaked-secret');

      const fetchMock = vi.fn(async () =>
        new Response(JSON.stringify({ access_token: 'stub', expires_in: 300 }), { status: 200 }),
      );
      globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;

      const token = await getSentinelToken();

      expect(token).toBe('stub');
      expect(fetchMock).toHaveBeenCalledTimes(1);
      const [, init] = fetchMock.mock.calls[0] as [unknown, RequestInit];
      const body = String(init.body);
      // Body is a URLSearchParams stringification. We assert that the
      // leaked credential never appears in it.
      expect(body).not.toContain('sh-leaked-id');
      expect(body).not.toContain('leaked-secret');
    });
  });

  describe('checkBackendSentinelStatus', () => {
    it('returns true when both Sentinel keys report is_set on /api/settings/api-keys', async () => {
      const fetchMock = vi.fn(async (input: unknown) => {
        const url = String(input);
        if (url.endsWith('/api/settings/api-keys')) {
          return new Response(
            JSON.stringify([
              { id: 'sentinel_client_id', env_key: 'SENTINEL_CLIENT_ID', is_set: true },
              { id: 'sentinel_client_secret', env_key: 'SENTINEL_CLIENT_SECRET', is_set: true },
              { id: 'opensky_client_id', env_key: 'OPENSKY_CLIENT_ID', is_set: false },
            ]),
            { status: 200 },
          );
        }
        return new Response('not found', { status: 404 });
      });
      globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;

      const configured = await checkBackendSentinelStatus();
      expect(configured).toBe(true);
    });

    it('returns false when only one of the two keys is set', async () => {
      const fetchMock = vi.fn(async () =>
        new Response(
          JSON.stringify([
            { id: 'sentinel_client_id', env_key: 'SENTINEL_CLIENT_ID', is_set: true },
            { id: 'sentinel_client_secret', env_key: 'SENTINEL_CLIENT_SECRET', is_set: false },
          ]),
          { status: 200 },
        ),
      );
      globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;

      const configured = await checkBackendSentinelStatus();
      expect(configured).toBe(false);
    });

    it('fails safely (false) when the backend errors', async () => {
      const fetchMock = vi.fn(async () => { throw new Error('network down'); });
      globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;

      const configured = await checkBackendSentinelStatus();
      expect(configured).toBe(false);
    });
  });
});
