/**
 * Phase 5F-A: CSP nonce plumbing and privileged-request CSRF boundary.
 *
 * The API guard runs before route handlers so a browser request rejected as
 * cross-origin can never be forwarded through the trusted frontend container
 * to a backend local-operator route.
 */

import { NextRequest, NextResponse } from 'next/server';

function buildCsp(nonce: string, strictScripts = false): string {
  const isDev = process.env.NODE_ENV !== 'production';
  const scriptSrc = isDev
    ? "script-src 'self' 'unsafe-inline' 'unsafe-eval' blob:"
    : strictScripts
      ? `script-src 'self' 'nonce-${nonce}' blob:`
      : "script-src 'self' 'unsafe-inline' blob:";
  const directives = [
    "default-src 'self'",
    scriptSrc,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob: https:",
    isDev
      ? "connect-src 'self' ws: wss: http://127.0.0.1:8000 http://127.0.0.1:8787 https:"
      : "connect-src 'self' ws: wss: https:",
    "font-src 'self' data:",
    "object-src 'none'",
    "worker-src 'self' blob:",
    "child-src 'self' blob:",
    "frame-src 'self' https://video.ibm.com https://ustream.tv https://www.ustream.tv https://t.me",
    "media-src 'self' blob:",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
  ];
  return directives.join('; ');
}

function isPrivilegedApiPath(pathname: string): boolean {
  const path = pathname.replace(/\/+$/, '');
  return (
    path === '/api/refresh' ||
    path === '/api/debug-latest' ||
    path === '/api/system/update' ||
    path === '/api/layers' ||
    path === '/api/ais/feed' ||
    path === '/api/mesh/infonet/ingest' ||
    path === '/api/mesh/meshtastic/send' ||
    path.startsWith('/api/wormhole/') ||
    path.startsWith('/api/settings/') ||
    path.startsWith('/api/ai/') ||
    path === '/api/ai' ||
    path.startsWith('/api/tools/') ||
    path === '/api/tools' ||
    path.startsWith('/api/mesh/peers') ||
    path.startsWith('/api/agent-shell/') ||
    path === '/api/agent-shell' ||
    path === '/api/sar/mode-b' ||
    path.startsWith('/api/sar/mode-b/') ||
    path === '/api/sar/aois' ||
    path.startsWith('/api/sar/aois/')
  );
}

function normalizedHost(value: string | null): string {
  return (value || '').split(',')[0].trim().replace(/^"|"$/g, '').toLowerCase();
}

function isSameOriginOrNonBrowser(request: NextRequest): boolean {
  const fetchSite = (request.headers.get('sec-fetch-site') || '').trim().toLowerCase();
  const origin = (request.headers.get('origin') || '').trim();

  // Modern browsers label ambient cross-site requests even when a particular
  // request shape omits Origin (for example navigations/resource loads).
  if (fetchSite === 'cross-site' || fetchSite === 'same-site') return false;

  if (!origin) {
    // CLI/native/server-to-server callers do not send Sec-Fetch-Site. Normal
    // dashboard browser calls are same-origin. Both remain frictionless.
    return !fetchSite || fetchSite === 'same-origin';
  }

  let originHost = '';
  try {
    originHost = new URL(origin).host.toLowerCase();
  } catch {
    return false;
  }
  if (!originHost) return false;

  const candidates = new Set<string>();
  const directHost = normalizedHost(request.headers.get('host'));
  if (directHost) candidates.add(directHost);
  const forwardedHost = request.headers.get('x-forwarded-host');
  if (forwardedHost) {
    for (const value of forwardedHost.split(',')) {
      const host = normalizedHost(value);
      if (host) candidates.add(host);
    }
  }
  return candidates.has(originHost);
}

export function proxy(request: NextRequest) {
  if (isPrivilegedApiPath(request.nextUrl.pathname) && !isSameOriginOrNonBrowser(request)) {
    return NextResponse.json(
      { detail: 'Cross-origin privileged request denied' },
      {
        status: 403,
        headers: {
          'Cache-Control': 'no-store, max-age=0',
          Pragma: 'no-cache',
        },
      },
    );
  }

  // API requests only need the security boundary above. CSP applies to page
  // responses, not JSON/API traffic.
  if (request.nextUrl.pathname.startsWith('/api/')) {
    return NextResponse.next();
  }

  const nonce = Buffer.from(crypto.randomUUID()).toString('base64');

  // Forward a nonce for staged CSP support. Strict script-src is opt-in until
  // every Next inline bootstrap script is verified with the nonce in production.
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set('x-nonce', nonce);

  const response = NextResponse.next({
    request: { headers: requestHeaders },
  });

  const strictCsp = process.env.SHADOWBROKER_STRICT_CSP === '1';
  response.headers.set('Content-Security-Policy', buildCsp(nonce, strictCsp));
  if (!strictCsp && process.env.NODE_ENV === 'production') {
    response.headers.set('Content-Security-Policy-Report-Only', buildCsp(nonce, true));
  }

  return response;
}

export const config = {
  matcher: [
    /*
     * Match pages AND API routes so privileged browser traffic is screened
     * before the catch-all API proxy can forward it. Exclude only static/image
     * assets and the favicon.
     */
    '/((?!_next/static|_next/image|favicon.ico).*)',
  ],
};
