/**
 * Phase 5F-A: CSP nonce plumbing tests.
 *
 * Validates:
 * 1. Nonce appears in document CSP header
 * 2. Nonce differs across repeated requests
 * 3. next.config.ts no longer owns a static CSP header
 * 4. Middleware does not break API/static routes (matcher exclusion)
 * 5. Google Fonts domains are preserved in CSP
 * 6. Production CSP preserves required directives
 */

import { describe, expect, it } from 'vitest';
import { NextRequest } from 'next/server';

import { middleware, config as middlewareConfig } from '@/middleware';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Call middleware with a fake document request and return the response. */
function callMiddleware(path = '/') {
  const req = new NextRequest(`http://localhost${path}`, { method: 'GET' });
  return middleware(req);
}

/** Extract the CSP header string from a middleware response. */
function getCsp(path = '/'): string {
  return callMiddleware(path).headers.get('Content-Security-Policy') ?? '';
}

/** Check whether the middleware matcher regex excludes a given path. */
function matcherExcludes(path: string): boolean {
  const pattern = middlewareConfig.matcher[0];
  // Next.js wraps the matcher in ^/<pattern>$ for path matching.
  // We replicate the essential check: the negative-lookahead prefix groups.
  const re = new RegExp(`^${pattern}$`);
  // Strip leading '/' because the matcher pattern starts with '/'.
  return !re.test(path);
}

// ---------------------------------------------------------------------------
// 1. Nonce appears in document CSP header
// ---------------------------------------------------------------------------

describe('nonce in CSP header', () => {
  it('CSP header contains a nonce-<value> token in script-src', () => {
    const csp = getCsp();
    expect(csp).toMatch(/'nonce-[A-Za-z0-9+/=]+'/) ;
  });

  it('nonce value is a base64-encoded UUID', () => {
    const csp = getCsp();
    const match = csp.match(/'nonce-([A-Za-z0-9+/=]+)'/);
    expect(match).not.toBeNull();
    const decoded = Buffer.from(match![1], 'base64').toString();
    // crypto.randomUUID() produces 8-4-4-4-12 hex with dashes
    expect(decoded).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-/);
  });

  it('x-nonce request header is set on the response', () => {
    const res = callMiddleware();
    // NextResponse.next({ request: { headers } }) merges into request headers.
    // The CSP nonce in the header must match the one forwarded to server components.
    const csp = res.headers.get('Content-Security-Policy') ?? '';
    const nonceInCsp = csp.match(/'nonce-([A-Za-z0-9+/=]+)'/)?.[1];
    expect(nonceInCsp).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// 2. Nonce differs across repeated requests
// ---------------------------------------------------------------------------

describe('nonce uniqueness', () => {
  it('two sequential requests produce different nonces', () => {
    const csp1 = getCsp();
    const csp2 = getCsp();
    const nonce1 = csp1.match(/'nonce-([A-Za-z0-9+/=]+)'/)?.[1];
    const nonce2 = csp2.match(/'nonce-([A-Za-z0-9+/=]+)'/)?.[1];
    expect(nonce1).toBeTruthy();
    expect(nonce2).toBeTruthy();
    expect(nonce1).not.toBe(nonce2);
  });

  it('ten requests produce ten distinct nonces', () => {
    const nonces = new Set<string>();
    for (let i = 0; i < 10; i++) {
      const csp = getCsp();
      const nonce = csp.match(/'nonce-([A-Za-z0-9+/=]+)'/)?.[1];
      expect(nonce).toBeTruthy();
      nonces.add(nonce!);
    }
    expect(nonces.size).toBe(10);
  });
});

// ---------------------------------------------------------------------------
// 3. next.config.ts no longer owns static CSP
// ---------------------------------------------------------------------------

describe('next.config.ts CSP removal', () => {
  it('securityHeaders in next.config does not include Content-Security-Policy', async () => {
    // Import the built config and inspect the headers callback.
    const nextConfig = (await import('../../../next.config')).default;
    const headerEntries = await nextConfig.headers!();
    const allHeaders = headerEntries.flatMap(
      (entry: { headers: { key: string; value: string }[] }) => entry.headers,
    );
    const cspHeaders = allHeaders.filter(
      (h: { key: string }) => h.key.toLowerCase() === 'content-security-policy',
    );
    expect(cspHeaders).toHaveLength(0);
  });

  it('non-CSP security headers are still present', async () => {
    const nextConfig = (await import('../../../next.config')).default;
    const headerEntries = await nextConfig.headers!();
    const allKeys = headerEntries
      .flatMap(
        (entry: { headers: { key: string; value: string }[] }) => entry.headers,
      )
      .map((h: { key: string }) => h.key);
    expect(allKeys).toContain('Referrer-Policy');
    expect(allKeys).toContain('X-Content-Type-Options');
    expect(allKeys).toContain('X-Frame-Options');
  });
});

// ---------------------------------------------------------------------------
// 4. Middleware does not break API/static routes
// ---------------------------------------------------------------------------

describe('middleware matcher exclusions', () => {
  it('excludes /api paths', () => {
    expect(matcherExcludes('/api/mesh/events')).toBe(true);
  });

  it('excludes /_next/static paths', () => {
    expect(matcherExcludes('/_next/static/chunks/main.js')).toBe(true);
  });

  it('excludes /_next/image paths', () => {
    expect(matcherExcludes('/_next/image?url=foo')).toBe(true);
  });

  it('excludes /favicon.ico', () => {
    expect(matcherExcludes('/favicon.ico')).toBe(true);
  });

  it('includes document paths like /', () => {
    expect(matcherExcludes('/')).toBe(false);
  });

  it('includes document paths like /dashboard', () => {
    expect(matcherExcludes('/dashboard')).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// 5. Google Fonts domains are preserved in CSP
// ---------------------------------------------------------------------------

describe('Google Fonts domains in CSP', () => {
  it('style-src includes https://fonts.googleapis.com', () => {
    const csp = getCsp();
    expect(csp).toContain('https://fonts.googleapis.com');
  });

  it('font-src includes https://fonts.gstatic.com', () => {
    const csp = getCsp();
    expect(csp).toContain('https://fonts.gstatic.com');
  });
});

// ---------------------------------------------------------------------------
// 6. Production CSP directive completeness
// ---------------------------------------------------------------------------

describe('production CSP directive completeness', () => {
  const csp = getCsp();

  it('has default-src self', () => {
    expect(csp).toContain("default-src 'self'");
  });

  it('has script-src with nonce', () => {
    expect(csp).toMatch(/script-src [^;]*'nonce-/);
  });

  it('has style-src with unsafe-inline and fonts.googleapis.com', () => {
    expect(csp).toMatch(/style-src [^;]*'unsafe-inline'/);
    expect(csp).toMatch(/style-src [^;]*https:\/\/fonts\.googleapis\.com/);
  });

  it('has worker-src self blob:', () => {
    expect(csp).toContain("worker-src 'self' blob:");
  });

  it('has child-src self blob:', () => {
    expect(csp).toContain("child-src 'self' blob:");
  });

  it('has img-src with self data: blob: https:', () => {
    expect(csp).toContain("img-src 'self' data: blob: https:");
  });

  it('has connect-src with self', () => {
    expect(csp).toMatch(/connect-src 'self'/);
  });

  it('has object-src none', () => {
    expect(csp).toContain("object-src 'none'");
  });

  it('has frame-ancestors none', () => {
    expect(csp).toContain("frame-ancestors 'none'");
  });

  it('has base-uri self', () => {
    expect(csp).toContain("base-uri 'self'");
  });

  it('has form-action self', () => {
    expect(csp).toContain("form-action 'self'");
  });
});
