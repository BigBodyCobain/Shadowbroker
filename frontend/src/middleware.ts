/**
 * Phase 5F-A: CSP nonce plumbing middleware.
 *
 * Generates a per-request cryptographic nonce and emits a dynamic
 * Content-Security-Policy header for document (page) responses.
 * API routes, static assets, and image optimization paths are excluded.
 */

import { NextRequest, NextResponse } from 'next/server';

function buildCsp(nonce: string): string {
  const isDev = process.env.NODE_ENV !== 'production';
  const directives = [
    "default-src 'self'",
    isDev
      ? `script-src 'self' 'unsafe-inline' 'unsafe-eval' 'nonce-${nonce}' blob:`
      : `script-src 'self' 'nonce-${nonce}' blob:`,
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "img-src 'self' data: blob: https:",
    isDev
      ? "connect-src 'self' ws: wss: http://127.0.0.1:8000 http://127.0.0.1:8787 https:"
      : "connect-src 'self' ws: wss: https:",
    "font-src 'self' data: https://fonts.gstatic.com",
    "object-src 'none'",
    "worker-src 'self' blob:",
    "child-src 'self' blob:",
    "frame-src 'self' https://video.ibm.com https://ustream.tv https://www.ustream.tv",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
  ];
  return directives.join('; ');
}

export function middleware(request: NextRequest) {
  const nonce = Buffer.from(crypto.randomUUID()).toString('base64');

  // Forward nonce to server components via request header.
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set('x-nonce', nonce);

  const response = NextResponse.next({
    request: { headers: requestHeaders },
  });

  response.headers.set('Content-Security-Policy', buildCsp(nonce));

  return response;
}

export const config = {
  matcher: [
    /*
     * Match all document/page paths.  Exclude:
     *   - /api/*           (API routes — handled by route handlers)
     *   - /_next/static/*  (static assets)
     *   - /_next/image/*   (image optimization)
     *   - /favicon.ico     (browser icon)
     */
    '/((?!api|_next/static|_next/image|favicon.ico).*)',
  ],
};
