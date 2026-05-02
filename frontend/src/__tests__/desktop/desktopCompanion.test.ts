/**
 * Tests for the desktop companion mode helper (desktopCompanion.ts).
 *
 * Validates runtime detection, Tauri invoke delegation, and browser-mode
 * fallback behavior without requiring a live Tauri runtime.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  isNativeDesktop,
  companionStatus,
  companionEnable,
  companionDisable,
  companionOpenBrowser,
} from '@/lib/desktopCompanion';

const MOCK_STATUS = {
  enabled: false,
  url: null,
  warning: 'Browser companion mode is less secure than the native desktop window.',
};

const MOCK_ENABLED = {
  enabled: true,
  url: 'http://127.0.0.1:3000',
  warning: 'Browser companion mode is less secure than the native desktop window.',
};

describe('desktopCompanion', () => {
  afterEach(() => {
    // Clean up __TAURI__ mock
    delete (window as Record<string, unknown>).__TAURI__;
  });

  // -------------------------------------------------------------------------
  // Runtime detection
  // -------------------------------------------------------------------------

  describe('isNativeDesktop', () => {
    it('returns false when __TAURI__ is not present', () => {
      expect(isNativeDesktop()).toBe(false);
    });

    it('returns false when __TAURI__.core.invoke is missing', () => {
      (window as Record<string, unknown>).__TAURI__ = { core: {} };
      expect(isNativeDesktop()).toBe(false);
    });

    it('returns true when __TAURI__.core.invoke is available', () => {
      (window as Record<string, unknown>).__TAURI__ = { core: { invoke: vi.fn() } };
      expect(isNativeDesktop()).toBe(true);
    });
  });

  // -------------------------------------------------------------------------
  // Browser-mode fallback (all commands return null)
  // -------------------------------------------------------------------------

  describe('browser mode (no Tauri)', () => {
    it('companionStatus returns null', async () => {
      expect(await companionStatus()).toBeNull();
    });

    it('companionEnable returns null', async () => {
      expect(await companionEnable()).toBeNull();
    });

    it('companionDisable returns null', async () => {
      expect(await companionDisable()).toBeNull();
    });

    it('companionOpenBrowser returns null', async () => {
      expect(await companionOpenBrowser()).toBeNull();
    });
  });

  // -------------------------------------------------------------------------
  // Desktop mode (mocked Tauri invoke)
  // -------------------------------------------------------------------------

  describe('desktop mode (Tauri present)', () => {
    let mockInvoke: ReturnType<typeof vi.fn>;

    beforeEach(() => {
      mockInvoke = vi.fn();
      (window as Record<string, unknown>).__TAURI__ = { core: { invoke: mockInvoke } };
    });

    it('companionStatus invokes companion_status', async () => {
      mockInvoke.mockResolvedValue(MOCK_STATUS);
      const result = await companionStatus();
      expect(mockInvoke).toHaveBeenCalledWith('companion_status');
      expect(result).toEqual(MOCK_STATUS);
    });

    it('companionEnable invokes companion_enable', async () => {
      mockInvoke.mockResolvedValue(MOCK_ENABLED);
      const result = await companionEnable();
      expect(mockInvoke).toHaveBeenCalledWith('companion_enable');
      expect(result).toEqual(MOCK_ENABLED);
    });

    it('companionDisable invokes companion_disable', async () => {
      mockInvoke.mockResolvedValue(MOCK_STATUS);
      const result = await companionDisable();
      expect(mockInvoke).toHaveBeenCalledWith('companion_disable');
      expect(result).toEqual(MOCK_STATUS);
    });

    it('companionOpenBrowser invokes companion_open_browser', async () => {
      mockInvoke.mockResolvedValue(MOCK_ENABLED);
      const result = await companionOpenBrowser();
      expect(mockInvoke).toHaveBeenCalledWith('companion_open_browser');
      expect(result).toEqual(MOCK_ENABLED);
    });

    it('propagates Tauri invoke errors', async () => {
      mockInvoke.mockRejectedValue(new Error('companion_not_enabled'));
      await expect(companionOpenBrowser()).rejects.toThrow('companion_not_enabled');
    });
  });

  // -------------------------------------------------------------------------
  // Status shape
  // -------------------------------------------------------------------------

  describe('CompanionStatus shape', () => {
    it('disabled status has null url', () => {
      expect(MOCK_STATUS.enabled).toBe(false);
      expect(MOCK_STATUS.url).toBeNull();
      expect(MOCK_STATUS.warning).toBeTruthy();
    });

    it('enabled status has a url', () => {
      expect(MOCK_ENABLED.enabled).toBe(true);
      expect(MOCK_ENABLED.url).toBe('http://127.0.0.1:3000');
    });
  });
});
