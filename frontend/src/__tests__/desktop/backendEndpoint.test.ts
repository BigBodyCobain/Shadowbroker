/**
 * Tests for getBackendEndpoint() — the runtime-resolved API endpoint
 * displayed in "Connect" modals for external tool configuration.
 *
 * Verifies:
 * - Returns window.location.origin when window is available
 * - Returns fallback when window is undefined (SSR)
 * - Does NOT hardcode :8000
 */

import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';

describe('getBackendEndpoint', () => {
  const originalWindow = globalThis.window;

  afterEach(() => {
    vi.resetModules();
    // Restore window if we deleted it
    if (!globalThis.window && originalWindow) {
      globalThis.window = originalWindow;
    }
  });

  it('returns window.location.origin in browser context', async () => {
    // Default test environment (jsdom) has window defined
    const { getBackendEndpoint } = await import('@/lib/backendEndpoint');
    const result = getBackendEndpoint();
    expect(result).toBe(window.location.origin);
    expect(result).not.toContain(':8000');
  });

  it('does not hardcode port 8000', async () => {
    const { getBackendEndpoint } = await import('@/lib/backendEndpoint');
    const result = getBackendEndpoint();
    // The result should be derived from window.location, not a hardcoded backend port
    expect(result).not.toMatch(/:8000$/);
  });

  it('returns http://localhost:8000 fallback when window is undefined (SSR)', async () => {
    // Temporarily remove window to simulate SSR
    // @ts-expect-error — intentionally removing window for SSR simulation
    delete globalThis.window;
    const { getBackendEndpoint } = await import('@/lib/backendEndpoint');
    const result = getBackendEndpoint();
    expect(result).toBe('http://localhost:8000');
    // Restore
    globalThis.window = originalWindow;
  });
});
