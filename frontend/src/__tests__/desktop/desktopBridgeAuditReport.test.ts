import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  getDesktopNativeControlAuditReport,
  installDesktopControlBridge,
} from '@/lib/desktopBridge';

describe('desktopBridge native audit access', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('returns the runtime audit report when available', () => {
    Object.defineProperty(globalThis, 'window', {
      value: {},
      configurable: true,
      writable: true,
    });

    installDesktopControlBridge({
      invokeLocalControl: vi.fn(),
      getNativeControlAuditReport: vi.fn(() => ({
        totalEvents: 2,
        totalRecorded: 2,
        recent: [],
        byOutcome: { allowed: 2 },
      })),
    });

    expect(getDesktopNativeControlAuditReport(5)).toEqual(
      expect.objectContaining({
        totalEvents: 2,
        totalRecorded: 2,
        byOutcome: { allowed: 2 },
      }),
    );
  });

  it('returns null when no runtime audit report is exposed', () => {
    Object.defineProperty(globalThis, 'window', {
      value: {},
      configurable: true,
      writable: true,
    });

    installDesktopControlBridge({
      invokeLocalControl: vi.fn(),
    });

    expect(getDesktopNativeControlAuditReport(5)).toBeNull();
  });
});
