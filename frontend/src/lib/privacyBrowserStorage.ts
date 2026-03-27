const PRIVACY_STRICT_KEY = 'sb_privacy_strict';
const PRIVACY_PROFILE_KEY = 'sb_privacy_profile';
const SESSION_MODE_KEY = 'sb_mesh_session_mode';

type BrowserStorageMode = 'local' | 'session';

function browserAvailable(): boolean {
  return typeof window !== 'undefined';
}

function safeGet(store: Storage, key: string): string | null {
  try {
    return store.getItem(key);
  } catch {
    return null;
  }
}

function safeSet(store: Storage, key: string, value: string): void {
  try {
    store.setItem(key, value);
  } catch {
    /* ignore */
  }
}

function safeRemove(store: Storage, key: string): void {
  try {
    store.removeItem(key);
  } catch {
    /* ignore */
  }
}

function readPreference(key: string): string | null {
  if (!browserAvailable()) return null;
  const sessionValue = safeGet(sessionStorage, key);
  if (sessionValue !== null) return sessionValue;
  return safeGet(localStorage, key);
}

function writePreference(key: string, value: string, mode: BrowserStorageMode): void {
  if (!browserAvailable()) return;
  const preferred = mode === 'session' ? sessionStorage : localStorage;
  const alternate = mode === 'session' ? localStorage : sessionStorage;
  safeSet(preferred, key, value);
  safeRemove(alternate, key);
}

export function getSessionModePreference(): boolean {
  return readPreference(SESSION_MODE_KEY) !== 'false';
}

export function setSessionModePreference(enabled: boolean): void {
  writePreference(SESSION_MODE_KEY, enabled ? 'true' : 'false', enabled ? 'session' : 'local');
}

export function getPrivacyStrictPreference(): boolean {
  return readPreference(PRIVACY_STRICT_KEY) === 'true';
}

export function setPrivacyStrictPreference(
  enabled: boolean,
  opts?: { sessionMode?: boolean },
): void {
  const sessionMode = opts?.sessionMode ?? getSessionModePreference();
  writePreference(
    PRIVACY_STRICT_KEY,
    enabled ? 'true' : 'false',
    enabled || sessionMode ? 'session' : 'local',
  );
}

export function getPrivacyProfilePreference(): string {
  return readPreference(PRIVACY_PROFILE_KEY) || 'default';
}

export function setPrivacyProfilePreference(
  profile: string,
  opts?: { sessionMode?: boolean },
): void {
  const normalized = String(profile || 'default') || 'default';
  const sessionMode = opts?.sessionMode ?? getSessionModePreference();
  writePreference(
    PRIVACY_PROFILE_KEY,
    normalized,
    normalized === 'high' || sessionMode ? 'session' : 'local',
  );
}

export function getSensitiveBrowserStorageMode(): BrowserStorageMode {
  if (!browserAvailable()) return 'session';
  const strict = getPrivacyStrictPreference();
  const sessionMode = getSessionModePreference();
  return strict || sessionMode ? 'session' : 'local';
}

function preferredSensitiveStorage(): Storage | null {
  if (!browserAvailable()) return null;
  return getSensitiveBrowserStorageMode() === 'session' ? sessionStorage : localStorage;
}

function alternateStorage(preferred: Storage): Storage | null {
  if (!browserAvailable()) return null;
  return preferred === localStorage ? sessionStorage : localStorage;
}

export function getSensitiveBrowserItem(key: string): string | null {
  const preferred = preferredSensitiveStorage();
  if (!preferred) return null;
  const alternate = alternateStorage(preferred);
  const preferredValue = safeGet(preferred, key);
  if (preferredValue !== null) return preferredValue;
  if (!alternate) return null;
  const alternateValue = safeGet(alternate, key);
  if (alternateValue !== null) {
    safeSet(preferred, key, alternateValue);
    if (alternate !== preferred) {
      safeRemove(alternate, key);
    }
  }
  return alternateValue;
}

export function setSensitiveBrowserItem(key: string, value: string): void {
  const preferred = preferredSensitiveStorage();
  if (!preferred) return;
  const alternate = alternateStorage(preferred);
  safeSet(preferred, key, value);
  if (alternate && alternate !== preferred) {
    safeRemove(alternate, key);
  }
}

export function removeSensitiveBrowserItem(key: string): void {
  if (!browserAvailable()) return;
  safeRemove(localStorage, key);
  safeRemove(sessionStorage, key);
}

export function migrateSensitiveBrowserItems(keys: string[]): void {
  if (!browserAvailable()) return;
  keys.forEach((key) => {
    void getSensitiveBrowserItem(key);
  });
}
