/**
 * Catch-all proxy route — forwards /api/* requests from the browser to the
 * backend server. BACKEND_URL is a plain server-side env var (not NEXT_PUBLIC_),
 * so it is read at request time from the runtime environment, never baked into
 * the client bundle or the build manifest.
 *
 * Set BACKEND_URL in docker-compose `environment:` (e.g. http://backend:8000)
 * to use Docker internal networking. Defaults to http://127.0.0.1:8000 for
 * local development where both services run on the same host.
 */

import { NextRequest, NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';
import { resolveAdminSessionToken } from '@/lib/server/adminSessionStore';

// Headers that must not be forwarded to the backend.
const STRIP_REQUEST = new Set([
  'connection',
  'keep-alive',
  'proxy-authenticate',
  'proxy-authorization',
  'x-admin-key',
  'te',
  'trailers',
  'transfer-encoding',
  'upgrade',
  'host',
]);

// Headers that must not be forwarded back to the browser.
// content-encoding and content-length are stripped because Node.js fetch()
// automatically decompresses gzip/br responses — forwarding these headers
// would cause ERR_CONTENT_DECODING_FAILED in the browser.
const STRIP_RESPONSE = new Set([
  'connection',
  'keep-alive',
  'proxy-authenticate',
  'proxy-authorization',
  'te',
  'trailers',
  'transfer-encoding',
  'upgrade',
  'content-encoding',
  'content-length',
]);

const ADMIN_COOKIE = 'sb_admin_session';
const NO_STORE_PROXY_HEADERS = {
  'Cache-Control': 'no-store, max-age=0',
  Pragma: 'no-cache',
};

function isSensitiveProxyPath(pathSegments: string[]): boolean {
  const joined = pathSegments.join('/');
  if (!joined) return false;
  if (pathSegments[0] === 'wormhole') return true;
  if (joined === 'refresh') return true;
  if (joined === 'debug-latest') return true;
  if (joined === 'system/update') return true;
  if (pathSegments[0] === 'settings') return true;
  if (joined === 'mesh/infonet/ingest') return true;
  return false;
}

async function proxy(req: NextRequest, pathSegments: string[]): Promise<NextResponse> {
  try {
    const isMesh = pathSegments[0] === 'mesh';
    const meshSegments = pathSegments.slice(1);
    const isSensitiveMeshPath = isMesh && meshSegments[0] === 'dm';
    const isAnonymousMeshWritePath =
      isMesh &&
      !isSensitiveMeshPath &&
      ['POST', 'PUT', 'DELETE'].includes(req.method.toUpperCase()) &&
      (meshSegments.join('/') === 'send' ||
        meshSegments.join('/') === 'vote' ||
        meshSegments.join('/') === 'report' ||
        meshSegments.join('/') === 'gate/create' ||
        (meshSegments[0] === 'gate' && meshSegments[2] === 'message') ||
        meshSegments.join('/') === 'oracle/predict' ||
        meshSegments.join('/') === 'oracle/resolve' ||
        meshSegments.join('/') === 'oracle/stake' ||
        meshSegments.join('/') === 'oracle/resolve-stakes');
    const backendUrl = process.env.BACKEND_URL ?? 'http://127.0.0.1:8000';
    let targetBase = backendUrl;

    if (isMesh) {
      const envEnabled = (process.env.WORMHOLE_ENABLED || '').toLowerCase();
      let wormholeEnabled = ['1', 'true', 'yes'].includes(envEnabled);
      let privacyProfile = (process.env.WORMHOLE_PRIVACY_PROFILE || '').toLowerCase();
      let anonymousMode = ['1', 'true', 'yes'].includes(
        (process.env.WORMHOLE_ANONYMOUS_MODE || '').toLowerCase(),
      );
      let wormholeReady = false;
      let effectiveTransport = '';

      if (!wormholeEnabled || !privacyProfile || !anonymousMode) {
        try {
          const cwd = process.cwd();
          const repoRoot = cwd.endsWith(path.sep + 'frontend') ? path.resolve(cwd, '..') : cwd;
          const wormholeFile = path.join(repoRoot, 'backend', 'data', 'wormhole.json');
          if (fs.existsSync(wormholeFile)) {
            const raw = fs.readFileSync(wormholeFile, 'utf8');
            const data = JSON.parse(raw);
            if (!wormholeEnabled) {
              wormholeEnabled = Boolean(data && data.enabled);
            }
            privacyProfile = privacyProfile || String(data?.privacy_profile || '').toLowerCase();
            if (!anonymousMode) {
              anonymousMode = Boolean(data?.anonymous_mode);
            }
          }
          const wormholeStatusFile = path.join(repoRoot, 'backend', 'data', 'wormhole_status.json');
          if (fs.existsSync(wormholeStatusFile)) {
            const raw = fs.readFileSync(wormholeStatusFile, 'utf8');
            const data = JSON.parse(raw);
            wormholeReady = Boolean(data?.running) && Boolean(data?.ready);
            effectiveTransport = String(data?.transport_active || data?.transport || '').toLowerCase();
          }
        } catch {
          wormholeEnabled = false;
        }
      }

      if (privacyProfile === 'high' && !wormholeEnabled && isSensitiveMeshPath) {
        return new NextResponse(
          JSON.stringify({
            ok: false,
            detail: 'High privacy requires Wormhole. Enable it in Settings and restart.',
          }),
          { status: 428, headers: { 'Content-Type': 'application/json' } },
        );
      }

      if (wormholeEnabled && isSensitiveMeshPath) {
        if (!wormholeReady) {
          return new NextResponse(
            JSON.stringify({
              ok: false,
              detail: 'Wormhole is enabled but not connected yet. Start Wormhole to use secure DM features.',
            }),
            { status: 503, headers: { 'Content-Type': 'application/json' } },
          );
        }
        targetBase = process.env.WORMHOLE_URL ?? 'http://127.0.0.1:8787';
      }

      if (anonymousMode && isAnonymousMeshWritePath) {
        if (!wormholeEnabled) {
          return new NextResponse(
            JSON.stringify({
              ok: false,
              detail: 'Anonymous mode requires Wormhole to be enabled before public posting.',
            }),
            { status: 428, headers: { 'Content-Type': 'application/json' } },
          );
        }
        const hiddenReady = wormholeReady && ['tor', 'i2p', 'mixnet'].includes(effectiveTransport);
        if (!hiddenReady) {
          return new NextResponse(
            JSON.stringify({
              ok: false,
              detail: 'Anonymous mode requires Wormhole hidden transport (Tor/I2P/Mixnet) to be ready.',
            }),
            { status: 428, headers: { 'Content-Type': 'application/json' } },
          );
        }
        targetBase = process.env.WORMHOLE_URL ?? 'http://127.0.0.1:8787';
      }
    }

    const targetUrl = new URL(`/api/${pathSegments.join('/')}`, targetBase);
    targetUrl.search = req.nextUrl.search;

    const forwardHeaders = new Headers();
    req.headers.forEach((value, key) => {
      if (!STRIP_REQUEST.has(key.toLowerCase())) {
        forwardHeaders.set(key, value);
      }
    });
    if (isSensitiveProxyPath(pathSegments)) {
      const cookieToken = req.cookies.get(ADMIN_COOKIE)?.value || '';
      const injectedAdmin = process.env.ADMIN_KEY || resolveAdminSessionToken(cookieToken) || '';
      if (injectedAdmin) {
        forwardHeaders.set('X-Admin-Key', injectedAdmin);
      }
    }

    const isBodyless = req.method === 'GET' || req.method === 'HEAD';
    let upstream: Response;
    const requestInit: RequestInit & { duplex?: 'half' } = {
      method: req.method,
      headers: forwardHeaders,
      cache: 'no-store',
    };
    if (!isBodyless) {
      requestInit.body = req.body;
      // Required for streaming request bodies in Node.js fetch
      requestInit.duplex = 'half';
    }
    try {
      upstream = await fetch(targetUrl.toString(), requestInit);
    } catch {
      return new NextResponse(JSON.stringify({ error: 'Backend unavailable' }), {
        status: 502,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    const responseHeaders = new Headers();
    upstream.headers.forEach((value, key) => {
      if (!STRIP_RESPONSE.has(key.toLowerCase())) {
        responseHeaders.set(key, value);
      }
    });
    if (isSensitiveProxyPath(pathSegments) || isSensitiveMeshPath) {
      Object.entries(NO_STORE_PROXY_HEADERS).forEach(([key, value]) => {
        responseHeaders.set(key, value);
      });
    }

    if (upstream.status === 304) {
      return new NextResponse(null, { status: 304, headers: responseHeaders });
    }

    // Stream the upstream body directly instead of buffering the full response.
    // This reduces TTFB and memory pressure for large payloads (flights, ships).
    return new NextResponse(upstream.body, {
      status: upstream.status,
      headers: responseHeaders,
    });
  } catch (error) {
    console.error('api proxy unexpected error', {
      pathSegments,
      method: req.method,
      error,
    });
    return new NextResponse(
      JSON.stringify({
        error: 'Proxy failed',
        detail: error instanceof Error ? error.message : 'unknown_error',
      }),
      {
        status: 500,
        headers: {
          'Content-Type': 'application/json',
          ...NO_STORE_PROXY_HEADERS,
        },
      },
    );
  }
}

export async function GET(req: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  return proxy(req, (await params).path);
}

export async function POST(req: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  return proxy(req, (await params).path);
}

export async function PUT(req: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  return proxy(req, (await params).path);
}

export async function DELETE(
  req: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  return proxy(req, (await params).path);
}
