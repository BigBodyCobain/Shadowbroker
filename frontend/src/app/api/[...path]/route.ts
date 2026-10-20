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
  'content-length',
  'expect',
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

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function isSensitiveProxyPath(pathSegments: string[]): boolean {
  const joined = pathSegments.join('/');
  if (!joined) return false;
  if (pathSegments[0] === 'wormhole') return true;
  if (joined === 'refresh') return true;
  if (joined === 'debug-latest') return true;
  if (joined === 'system/update') return true;
  if (joined === 'layers') return true;
  if (joined === 'ais/feed') return true;
  if (pathSegments[0] === 'ai') return true;
  if (pathSegments[0] === 'sar' && (pathSegments[1] === 'mode-b' || pathSegments[1] === 'aois')) {
    return true;
  }
  if (pathSegments[0] === 'settings') return true;
  if (joined === 'mesh/infonet/ingest') return true;
  if (joined === 'mesh/meshtastic/send') return true;
  // mesh/peers and all tools/* use require_local_operator on the backend and
  // need X-Admin-Key injected on the server-side proxy leg.
  if (pathSegments[0] === 'mesh' && pathSegments[1] === 'peers') return true;
  if (pathSegments[0] === 'tools') return true;
  return false;
}

function normalizeHeaderHost(host: string | null): string {
  return (host || '').trim().replace(/^"|"$/g, '').toLowerCase();
}

function hostnameFromHeaderHost(host: string): string {
  const normalized = normalizeHeaderHost(host);
  if (!normalized) return '';
  try {
    return new URL(`http://${normalized}`).hostname.toLowerCase();
  } catch {
    return normalized.replace(/:\d+$/, '').toLowerCase();
  }
}

function isPrivateIpv4(hostname: string): boolean {
  const parts = hostname.split('.').map((part) => Number(part));
  if (parts.length !== 4 || parts.some((part) => !Number.isInteger(part) || part < 0 || part > 255)) {
    return false;
  }
  const [first, second] = parts;
  return first === 10 || (first === 172 && second >= 16 && second <= 31) || (first === 192 && second === 168);
}

function isInternalProxyHost(host: string): boolean {
  const hostname = hostnameFromHeaderHost(host);
  if (!hostname || hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '::1') {
    return false;
  }
  return (
    !hostname.includes('.') ||
    isPrivateIpv4(hostname) ||
    hostname.endsWith('.internal') ||
    hostname.endsWith('.docker')
  );
}

function forwardedHostCandidates(req: NextRequest): string[] {
  const hosts = new Set<string>();
  const directHost = normalizeHeaderHost(req.headers.get('host'));
  if (directHost) hosts.add(directHost);

  if (!isInternalProxyHost(directHost)) {
    return [...hosts];
  }

  const forwardedHost = req.headers.get('x-forwarded-host');
  if (forwardedHost) {
    for (const value of forwardedHost.split(',')) {
      const host = normalizeHeaderHost(value);
      if (host) hosts.add(host);
    }
  }

  const forwarded = req.headers.get('forwarded');
  if (forwarded) {
    const hostPattern = /(?:^|[;,])\s*host=(?:"([^"]+)"|([^;,]+))/gi;
    let match: RegExpExecArray | null;
    while ((match = hostPattern.exec(forwarded)) !== null) {
      const host = normalizeHeaderHost(match[1] || match[2] || '');
      if (host) hosts.add(host);
    }
  }

  return [...hosts];
}

/**
 * CSRF guard for the server-side admin-key injection (issues #249 / #254).
 *
 * The proxy injects ``process.env.ADMIN_KEY`` into the forwarded
 * X-Admin-Key header for sensitive backend routes. Without an origin
 * check, any cross-origin webpage the operator visits could fire
 * ``fetch('http://localhost:3000/api/wormhole/identity/bootstrap')`` and
 * have that request get the operator's admin key injected for free —
 * full identity-takeover CSRF.
 *
 * We allow injection when ANY of these is true:
 *   - The request carries a valid admin session cookie (already auth'd)
 *   - The Origin header is absent (server-to-server fetch, Tauri/Electron
 *     native shells, curl/cli — none of these are browser-CSRF surfaces)
 *   - The Origin header host matches the request's own Host or, when the
 *     direct Host is an internal service name, a reverse proxy's forwarded
 *     host (genuine same-origin browser fetch from our own dashboard,
 *     including Docker/Traefik deployments where Host is internal)
 *
 * If Origin is present AND doesn't match Host, the caller is a hostile
 * cross-origin webpage. We refuse to inject the admin key. The backend
 * then sees the request without auth and rejects it via
 * require_local_operator — exactly the desired outcome.
 */
function isSameOriginOrNonBrowser(req: NextRequest): boolean {
  const origin = req.headers.get('origin');
  if (!origin) {
    // No Origin header = server-to-server / native shell / older browser
    // doing a same-origin GET. CSRF requires the attacker to control a
    // page running in a browser, which always sends Origin on the
    // dangerous methods. Treat missing Origin as not-CSRF.
    return true;
  }
  try {
    const originUrl = new URL(origin);
    const originHost = normalizeHeaderHost(originUrl.host);
    if (!originHost) return false;
    return forwardedHostCandidates(req).includes(originHost);
  } catch {
    // Malformed Origin header — be conservative.
    return false;
  }
}

function canUseEnvAdminKey(req: NextRequest, pathSegments: string[]): boolean {
  const joined = pathSegments.join('/');
  const origin = req.headers.get('origin');

  // /api/refresh is a state-changing GET. A browser can trigger a no-Origin
  // GET through ambient mechanisms such as image/script navigation, so do not
  // give that shape the server-side ADMIN_KEY fallback. Valid admin-session
  // cookies are still handled separately below.
  if (joined === 'refresh' && req.method.toUpperCase() === 'GET' && !origin) {
    return false;
  }

  return isSameOriginOrNonBrowser(req);
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
      (meshSegments.join('/') === 'vote' ||
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
      // Issues #249 / #254: gate the server-side admin-key injection on
      // either a valid admin session cookie OR a same-origin request.
      // Cross-origin webpages must not silently inherit the operator's
      // ADMIN_KEY just by being open in the same browser.
      const cookieToken = req.cookies.get(ADMIN_COOKIE)?.value || '';
      const sessionAdminKey = resolveAdminSessionToken(cookieToken) || '';
      const allowEnvKeyInjection = canUseEnvAdminKey(req, pathSegments);
      let injectedAdmin = '';
      if (sessionAdminKey) {
        // Authenticated session always works — Origin doesn't matter
        // because the cookie itself is same-site / strict.
        injectedAdmin = sessionAdminKey;
      } else if (allowEnvKeyInjection && process.env.ADMIN_KEY) {
        // Fall back to the server-side ADMIN_KEY only for legitimate
        // callers (same-origin dashboard, Tauri shell, server-to-server).
        injectedAdmin = process.env.ADMIN_KEY;
      }
      if (injectedAdmin) {
        forwardHeaders.set('X-Admin-Key', injectedAdmin);
      }
    }

    const isBodyless = req.method === 'GET' || req.method === 'HEAD';
    let upstream: Response | null = null;
    const requestInit: RequestInit & { duplex?: 'half' } = {
      method: req.method,
      headers: forwardHeaders,
      cache: 'no-store',
    };
    if (!isBodyless) {
      const body = await req.text();
      if (body.length > 0) {
        requestInit.body = body;
      }
    }
    const maxAttempts = isBodyless ? 18 : 1;
    let fetchError: unknown = null;
    for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
      try {
        upstream = await fetch(targetUrl.toString(), requestInit);
        fetchError = null;
        break;
      } catch (error) {
        fetchError = error;
        if (attempt >= maxAttempts) {
          console.error('api proxy upstream fetch failed', {
            method: req.method,
            target: targetUrl.toString(),
            error,
          });
        }
        if (attempt >= maxAttempts) break;
        await sleep(250);
      }
    }
    if (!upstream) {
      return new NextResponse(JSON.stringify({ error: 'Backend unavailable' }), {
        status: 502,
        headers: {
          'Content-Type': 'application/json',
          'X-Proxy-Error': fetchError instanceof Error ? fetchError.name : 'fetch_failed',
        },
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
