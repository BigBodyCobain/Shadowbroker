import { beforeEach, describe, expect, it, vi } from 'vitest';

function makeStorage() {
  const values = new Map<string, string>();
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => void values.set(key, value),
    removeItem: (key: string) => void values.delete(key),
    clear: () => void values.clear(),
  };
}

describe('privacyBrowserStorage', () => {
  beforeEach(() => {
    vi.resetModules();
    Object.defineProperty(globalThis, 'localStorage', {
      value: makeStorage(),
      configurable: true,
      writable: true,
    });
    Object.defineProperty(globalThis, 'sessionStorage', {
      value: makeStorage(),
      configurable: true,
      writable: true,
    });
  });

  it('stores sensitive items in sessionStorage by default', async () => {
    const mod = await import('@/lib/privacyBrowserStorage');

    mod.setSensitiveBrowserItem('secret-key', 'alpha');

    expect(mod.getSensitiveBrowserStorageMode()).toBe('session');
    expect(sessionStorage.getItem('secret-key')).toBe('alpha');
    expect(localStorage.getItem('secret-key')).toBeNull();
    expect(mod.getSensitiveBrowserItem('secret-key')).toBe('alpha');
  });

  it('stores privacy preferences in session storage when session mode is enabled', async () => {
    const mod = await import('@/lib/privacyBrowserStorage');

    mod.setSessionModePreference(true);
    mod.setPrivacyStrictPreference(true, { sessionMode: true });
    mod.setPrivacyProfilePreference('high', { sessionMode: true });

    expect(mod.getSessionModePreference()).toBe(true);
    expect(mod.getPrivacyStrictPreference()).toBe(true);
    expect(mod.getPrivacyProfilePreference()).toBe('high');
    expect(sessionStorage.getItem('sb_mesh_session_mode')).toBe('true');
    expect(sessionStorage.getItem('sb_privacy_strict')).toBe('true');
    expect(sessionStorage.getItem('sb_privacy_profile')).toBe('high');
    expect(localStorage.getItem('sb_mesh_session_mode')).toBeNull();
    expect(localStorage.getItem('sb_privacy_strict')).toBeNull();
    expect(localStorage.getItem('sb_privacy_profile')).toBeNull();
  });

  it('persists session mode locally only when the user explicitly disables it', async () => {
    const mod = await import('@/lib/privacyBrowserStorage');

    mod.setSessionModePreference(false);

    expect(mod.getSessionModePreference()).toBe(false);
    expect(localStorage.getItem('sb_mesh_session_mode')).toBe('false');
    expect(sessionStorage.getItem('sb_mesh_session_mode')).toBeNull();
  });

  it('stores sensitive items in sessionStorage when privacy strict is enabled', async () => {
    localStorage.setItem('sb_privacy_strict', 'true');
    const mod = await import('@/lib/privacyBrowserStorage');

    mod.setSensitiveBrowserItem('secret-key', 'bravo');

    expect(mod.getSensitiveBrowserStorageMode()).toBe('session');
    expect(sessionStorage.getItem('secret-key')).toBe('bravo');
    expect(localStorage.getItem('secret-key')).toBeNull();
  });

  it('migrates legacy localStorage values into sessionStorage in strict mode', async () => {
    localStorage.setItem('sb_privacy_strict', 'true');
    localStorage.setItem('secret-key', 'charlie');
    const mod = await import('@/lib/privacyBrowserStorage');

    expect(mod.getSensitiveBrowserItem('secret-key')).toBe('charlie');
    expect(sessionStorage.getItem('secret-key')).toBe('charlie');
    expect(localStorage.getItem('secret-key')).toBeNull();
  });
});
