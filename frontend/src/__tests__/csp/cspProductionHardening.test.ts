/**
 * Phase 5F-B: Production script-src nonce hardening tests.
 *
 * Validates:
 * 1. Production CSP preserves hydration-safe script execution with a compatibility
 *    inline fallback required by the Next.js production runtime
 * 2. Dev CSP retains 'unsafe-inline' and 'unsafe-eval'
 * 3. Unchanged directives (style-src, font-src, worker-src, etc.) intact
 * 4. API security-boundary matching and static route exclusions remain intact
 * 5. isDev is evaluated per-request (not cached at module load)
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';

import { proxy, config as proxyConfig } from '@/proxy';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function callProxy(path = '/') {
  const req = new NextRequest(`http://localhost${path}`, { method: 'GET' });
  return proxy(req);
}

function getCsp(path = '/'): string {
  return callProxy(path).headers.get('Content-Security-Policy') ?? '';
}

/** Extract a single CSP directive by name. */
function getDirective(name: string, csp?: string): string {
  const full = csp ?? getCsp();
  const re = new RegExp(`${name}\\s+([^;]+)`);
  return re.exec(full)?.[1]?.trim() ?? '';
}

function matcherExcludes(path: string): boolean {
  const pattern = proxyConfig.matcher[0];
  const re = new RegExp(`^${pattern}$`);
  return !re.test(path);
}

// ---------------------------------------------------------------------------
// 1. Production CSP stays hardened without blocking Next hydration
// ---------------------------------------------------------------------------

describe('production script-src hardening', () => {
  beforeEach(() => {
    vi.stubEnv('NODE_ENV', 'production');
  });
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('production script-src contains unsafe-inline compatibility fallback', () => {
    const scriptSrc = getDirective('script-src');
    expect(scriptSrc).toContain("'unsafe-inline'");
  });

  it('production script-src does NOT contain unsafe-eval', () => {
    const scriptSrc = getDirective('script-src');
    expect(scriptSrc).not.toContain("'unsafe-eval'");
  });

  it('production script-src does not contain nonce until all Next inline scripts are wired', () => {
    const scriptSrc = getDirective('script-src');
    expect(scriptSrc).not.toMatch(/'nonce-[A-Za-z0-9+/=]+'/);
  });

  it('production script-src contains self and blob:', () => {
    const scriptSrc = getDirective('script-src');
    expect(scriptSrc).toContain("'self'");
    expect(scriptSrc).toContain('blob:');
  });

  it('production connect-src uses restricted set', () => {
    const connectSrc = getDirective('connect-src');
    expect(connectSrc).not.toContain('http://127.0.0.1:8000');
    expect(connectSrc).not.toContain('http://127.0.0.1:8787');
    expect(connectSrc).toContain("'self'");
    expect(connectSrc).toContain('wss:');
    expect(connectSrc).toContain('https:');
  });
});

// ---------------------------------------------------------------------------
// 2. Dev CSP retains required dev allowances
// ---------------------------------------------------------------------------

describe('dev script-src allowances', () => {
  beforeEach(() => {
    vi.stubEnv('NODE_ENV', 'development');
  });
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('dev script-src contains unsafe-inline', () => {
    const scriptSrc = getDirective('script-src');
    expect(scriptSrc).toContain("'unsafe-inline'");
  });

  it('dev script-src contains unsafe-eval', () => {
    const scriptSrc = getDirective('script-src');
    expect(scriptSrc).toContain("'unsafe-eval'");
  });

  it('dev script-src also omits nonce to match production hydration behavior', () => {
    const scriptSrc = getDirective('script-src');
    expect(scriptSrc).not.toMatch(/'nonce-[A-Za-z0-9+/=]+'/);
  });

  it('dev connect-src includes localhost backends', () => {
    const connectSrc = getDirective('connect-src');
    expect(connectSrc).toContain('http://127.0.0.1:8000');
    expect(connectSrc).toContain('http://127.0.0.1:8787');
  });
});

// ---------------------------------------------------------------------------
// 3. Unchanged directives remain intact across both modes
// ---------------------------------------------------------------------------

describe('unchanged directives in production', () => {
  beforeEach(() => {
    vi.stubEnv('NODE_ENV', 'production');
  });
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('style-src preserves unsafe-inline without runtime Google Fonts', () => {
    const styleSrc = getDirective('style-src');
    expect(styleSrc).toContain("'unsafe-inline'");
    expect(styleSrc).not.toContain('https://fonts.googleapis.com');
  });

  it('font-src preserves self and data without runtime Google Fonts', () => {
    const fontSrc = getDirective('font-src');
    expect(fontSrc).toContain("'self'");
    expect(fontSrc).toContain('data:');
    expect(fontSrc).not.toContain('https://fonts.gstatic.com');
  });

  it('worker-src self blob:', () => {
    expect(getCsp()).toContain("worker-src 'self' blob:");
  });

  it('child-src self blob:', () => {
    expect(getCsp()).toContain("child-src 'self' blob:");
  });

  it('img-src self data: blob: https:', () => {
    expect(getCsp()).toContain("img-src 'self' data: blob: https:");
  });

  it('object-src none', () => {
    expect(getCsp()).toContain("object-src 'none'");
  });

  it('frame-ancestors none', () => {
    expect(getCsp()).toContain("frame-ancestors 'none'");
  });

  it('base-uri self', () => {
    expect(getCsp()).toContain("base-uri 'self'");
  });

  it('form-action self', () => {
    expect(getCsp()).toContain("form-action 'self'");
  });

  it('default-src self', () => {
    expect(getCsp()).toContain("default-src 'self'");
  });
});

// ---------------------------------------------------------------------------
// 4. API security boundary / static route exclusions remain intact
// ---------------------------------------------------------------------------

describe('matcher security boundary and exclusions', () => {
  it('includes /api paths so privileged requests can be screened', () => {
    expect(matcherExcludes('/api/mesh/events')).toBe(false);
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

  it('includes document paths', () => {
    expect(matcherExcludes('/')).toBe(false);
    expect(matcherExcludes('/dashboard')).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// 5. isDev evaluated per-request (not cached at module load)
// ---------------------------------------------------------------------------

describe('per-request environment evaluation', () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('switching NODE_ENV between calls changes script-src', () => {
    vi.stubEnv('NODE_ENV', 'production');
    const prodScriptSrc = getDirective('script-src');
    expect(prodScriptSrc).toContain("'unsafe-inline'");
    expect(prodScriptSrc).not.toContain("'unsafe-eval'");

    vi.stubEnv('NODE_ENV', 'development');
    const devScriptSrc = getDirective('script-src');
    expect(devScriptSrc).toContain("'unsafe-inline'");
    expect(devScriptSrc).toContain("'unsafe-eval'");
  });
});
