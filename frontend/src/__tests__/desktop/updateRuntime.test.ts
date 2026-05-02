import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  classifyUpdateRuntime,
  getDesktopUpdateContext,
  getPreferredManualUpdateUrl,
  getUpdateAction,
  pickDesktopInstallerUrl,
  type GitHubLatestRelease,
} from '@/lib/updateRuntime';

const RELEASE: GitHubLatestRelease = {
  html_url: 'https://github.com/BigBodyCobain/Shadowbroker/releases/tag/v0.9.7',
  assets: [
    { name: 'ShadowBroker_0.9.7_x64_en-US.msi', browser_download_url: 'https://example.test/windows.msi' },
    { name: 'ShadowBroker_0.9.7_x64-setup.exe', browser_download_url: 'https://example.test/windows-setup.exe' },
    { name: 'ShadowBroker_0.9.7_aarch64.dmg', browser_download_url: 'https://example.test/macos.dmg' },
    { name: 'ShadowBroker_0.9.7_amd64.AppImage', browser_download_url: 'https://example.test/linux.AppImage' },
  ],
};

describe('updateRuntime', () => {
  afterEach(() => {
    delete (window as Record<string, unknown>).__TAURI__;
  });

  describe('getDesktopUpdateContext', () => {
    it('returns null when Tauri is not present', async () => {
      expect(await getDesktopUpdateContext()).toBeNull();
    });

    it('invokes desktop_update_context when Tauri is present', async () => {
      const invoke = vi.fn().mockResolvedValue({
        mode: 'packaged',
        platform: 'windows',
        is_packaged_build: true,
        backend_mode: 'managed',
        owns_local_backend: true,
      });
      (window as Record<string, unknown>).__TAURI__ = { core: { invoke } };

      const result = await getDesktopUpdateContext();

      expect(invoke).toHaveBeenCalledWith('desktop_update_context');
      expect(result).toEqual({
        mode: 'packaged',
        platform: 'windows',
        is_packaged_build: true,
        backend_mode: 'managed',
        owns_local_backend: true,
      });
    });
  });

  describe('runtime classification', () => {
    it('classifies browser mode when no desktop context exists', () => {
      expect(classifyUpdateRuntime(null)).toBe('browser');
      expect(getUpdateAction('browser')).toBe('auto_apply');
    });

    it('classifies desktop dev mode as auto-apply', () => {
      expect(
        classifyUpdateRuntime({
          mode: 'dev',
          platform: 'windows',
          is_packaged_build: false,
        }),
      ).toBe('desktop_dev');
      expect(getUpdateAction('desktop_dev')).toBe('auto_apply');
    });

    it('classifies packaged desktop mode as manual-download', () => {
      expect(
        classifyUpdateRuntime({
          mode: 'packaged',
          platform: 'windows',
          is_packaged_build: true,
        }),
      ).toBe('desktop_packaged');
      expect(getUpdateAction('desktop_packaged')).toBe('manual_download');
    });
  });

  describe('installer asset selection', () => {
    it('prefers msi installers on windows', () => {
      expect(pickDesktopInstallerUrl(RELEASE, 'windows')).toBe('https://example.test/windows.msi');
    });

    it('prefers dmg installers on macos', () => {
      expect(pickDesktopInstallerUrl(RELEASE, 'macos')).toBe('https://example.test/macos.dmg');
    });

    it('prefers appimage installers on linux', () => {
      expect(pickDesktopInstallerUrl(RELEASE, 'linux')).toBe('https://example.test/linux.AppImage');
    });

    it('falls back to the release page when no platform asset matches', () => {
      expect(getPreferredManualUpdateUrl(RELEASE, 'desktop_packaged', 'unknown')).toBe(
        RELEASE.html_url,
      );
    });

    it('uses release page for non-packaged runtimes', () => {
      expect(getPreferredManualUpdateUrl(RELEASE, 'browser', 'windows')).toBe(RELEASE.html_url);
    });
  });
});
