/**
 * Phase 5F-A: CSP nonce plumbing tests.
 *
 * Validates:
 * 1. Document CSP remains hydration-safe for the Next.js runtime
 * 2. CSP is deterministic across repeated requests
 * 3. next.config.ts no longer owns a static CSP header
 * 4. Proxy screens API routes before handlers while static assets stay excluded
 * 5. Google Fonts domains are preserved in CSP
 * 6. Production CSP preserves required directives
 */

import { describe, expect, it } from 'vitest';
import { NextRequest } from 'next/server';

import { proxy, config as proxyConfig } from '@/proxy';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Call proxy with a fake document request and return the response. */
function callProxy(path = '/') {
  const req = new NextRequest(`http://localhost${path}`, { method: 'GET' });
  return proxy(req);
}

/** Extract the CSP header string from a proxy response. */
function getCsp(path = '/'): string {
  return callProxy(path).headers.get('Content-Security-Policy') ?? '';
}

/** Check whether the proxy matcher regex excludes a given path. */
function matcherExcludes(path: string): boolean {
  const pattern = proxyConfig.matcher[0];
  // Next.js wraps the matcher in ^/<pattern>$ for path matching.
  // We replicate the essential check: the negative-lookahead prefix groups.
  const re = new RegExp(`^${pattern}$`);
  // Strip leading '/' because the matcher pattern starts with '/'.
  return !re.test(path);
}

// ---------------------------------------------------------------------------
// 1. Document CSP remains hydration-safe
// ---------------------------------------------------------------------------

describe('hydration-safe CSP header', () => {
  it('CSP header does not put nonce tokens in script-src', () => {
    const csp = getCsp();
    expect(csp).not.toMatch(/'nonce-[A-Za-z0-9+/=]+'/);
  });

  it('script-src keeps the inline compatibility fallback required by Next hydration', () => {
    const csp = getCsp();
    expect(csp).toMatch(/script-src [^;]*'unsafe-inline'/);
  });

  it('proxy still returns a CSP header for document requests', () => {
    const csp = getCsp();
    expect(csp).toContain("default-src 'self'");
    expect(csp).toContain("script-src 'self'");
  });
});

// ---------------------------------------------------------------------------
// 2. CSP is deterministic across repeated requests
// ---------------------------------------------------------------------------

describe('CSP stability', () => {
  it('two sequential requests produce the same document CSP', () => {
    const csp1 = getCsp();
    const csp2 = getCsp();
    expect(csp1).toBe(csp2);
  });

  it('ten requests do not introduce nonce-bearing CSP variants', () => {
    const csps = new Set<string>();
    for (let i = 0; i < 10; i++) {
      const csp = getCsp();
      expect(csp).not.toMatch(/'nonce-[A-Za-z0-9+/=]+'/);
      csps.add(csp);
    }
    expect(csps.size).toBe(1);
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
// 4. Proxy screens APIs while keeping document/static behavior intact
// ---------------------------------------------------------------------------

describe('proxy matcher and privileged API boundary', () => {
  it('includes /api paths so the request-boundary security guard runs', () => {
    expect(matcherExcludes('/api/mesh/events')).toBe(false);
  });

  it('non-sensitive API requests pass through without document CSP', () => {
    expect(getCsp('/api/mesh/events')).toBe('');
  });

  it('rejects hostile cross-origin privileged API requests before route handling', () => {
    const req = new NextRequest('http://localhost/api/settings/tor/reset-identity', {
      method: 'POST',
      headers: {
        host: 'localhost',
        origin: 'https://evil.example',
        'sec-fetch-site': 'cross-site',
      },
    });
    const response = proxy(req);
    expect(response.status).toBe(403);
    expect(response.headers.get('Content-Security-Policy')).toBeNull();
  });

  it('preserves a legitimate reverse-proxy Forwarded host on an internal direct Host', () => {
    const req = new NextRequest('http://frontend:3000/api/settings/api-keys', {
      method: 'GET',
      headers: {
        host: 'frontend:3000',
        origin: 'https://shadowbroker.example',
        forwarded: 'for=172.18.0.1;proto=https;host="shadowbroker.example"',
      },
    });
    expect(proxy(req).status).not.toBe(403);
  });

  it('does not trust spoofed X-Forwarded-Host on a public direct Host', () => {
    const req = new NextRequest('https://shadowbroker.example/api/settings/api-keys', {
      method: 'GET',
      headers: {
        host: 'shadowbroker.example',
        origin: 'https://evil.example',
        'x-forwarded-host': 'evil.example',
      },
    });
    expect(proxy(req).status).toBe(403);
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
// 5. Runtime Google Fonts domains are not required in CSP
// ---------------------------------------------------------------------------

describe('local font CSP', () => {
  it('style-src does not allow https://fonts.googleapis.com', () => {
    const csp = getCsp();
    expect(csp).not.toContain('https://fonts.googleapis.com');
  });

  it('font-src does not allow https://fonts.gstatic.com', () => {
    const csp = getCsp();
    expect(csp).not.toContain('https://fonts.gstatic.com');
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

  it('has script-src with hydration compatibility fallback', () => {
    expect(csp).toMatch(/script-src [^;]*'unsafe-inline'/);
    expect(csp).not.toMatch(/script-src [^;]*'nonce-/);
  });

  it('has style-src with hydration-compatible inline styles only', () => {
    expect(csp).toMatch(/style-src [^;]*'unsafe-inline'/);
    expect(csp).not.toMatch(/style-src [^;]*https:\/\/fonts\.googleapis\.com/);
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
