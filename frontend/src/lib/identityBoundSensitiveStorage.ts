import {
  decryptIdentityBoundStoragePayload,
  encryptIdentityBoundStoragePayload,
} from '@/mesh/meshIdentity';
import {
  getSensitiveBrowserItem,
  removeSensitiveBrowserItem,
  setSensitiveBrowserItem,
} from '@/lib/privacyBrowserStorage';

type SensitiveStorageOptions = {
  legacyKey?: string;
};

export async function loadIdentityBoundSensitiveValue<T>(
  storageKey: string,
  wrapInfo: string,
  fallback: T,
  options: SensitiveStorageOptions = {},
): Promise<T> {
  const scopedRaw = getSensitiveBrowserItem(storageKey) || '';
  const legacyKey = String(options.legacyKey || '').trim();
  const legacyRaw = legacyKey ? getSensitiveBrowserItem(legacyKey) || '' : '';
  const raw = scopedRaw || legacyRaw;
  if (!raw) return fallback;

  const value = await decryptIdentityBoundStoragePayload<T>(raw, wrapInfo, fallback);
  if (!raw.trim().startsWith('enc:')) {
    await persistIdentityBoundSensitiveValue(storageKey, wrapInfo, value, options);
  }
  return value;
}

export async function persistIdentityBoundSensitiveValue<T>(
  storageKey: string,
  wrapInfo: string,
  value: T,
  options: SensitiveStorageOptions = {},
): Promise<void> {
  const encrypted = await encryptIdentityBoundStoragePayload(value, wrapInfo);
  setSensitiveBrowserItem(storageKey, encrypted);
  const legacyKey = String(options.legacyKey || '').trim();
  if (legacyKey && legacyKey !== storageKey) {
    removeSensitiveBrowserItem(legacyKey);
  }
}
