'use client';

import { createContext, useContext, useState, useCallback, type ReactNode } from 'react';
import en from './translations/en.json';
import zhCN from './translations/zh-CN.json';
import fr from './translations/fr.json';

export type Locale = 'en' | 'zh-CN' | 'fr';

/**
 * Registry of available locales for the UI language toggle.
 *
 * `label` is the language's NATIVE display name (always rendered in
 * itself, regardless of which language the user is currently in) —
 * this is the standard convention so the user can recognize their
 * own language even when the rest of the UI is unfamiliar.
 *
 * When adding a new locale:
 *   1. Add the translation JSON under translations/
 *   2. Import it above and add to `translations` below
 *   3. Add an entry here
 *   4. Extend the `Locale` type
 *   5. Read CONTRIBUTING.md — translations must be technically faithful
 *      to the English source. Politically loaded substitutions or
 *      framing aligned with state propaganda from ANY country will
 *      be rejected.
 */
export const LOCALES: ReadonlyArray<{ code: Locale; label: string }> = [
  { code: 'en', label: 'English' },
  { code: 'zh-CN', label: '中文 (简体)' },
  { code: 'fr', label: 'Français' },
];

const translations: Record<Locale, Record<string, Record<string, string>>> = { en, 'zh-CN': zhCN, fr };

function isLocale(value: unknown): value is Locale {
  return typeof value === 'string' && LOCALES.some((entry) => entry.code === value);
}

function resolve(obj: Record<string, unknown>, path: string): string {
  const parts = path.split('.');
  let current: unknown = obj;
  for (const part of parts) {
    if (current && typeof current === 'object' && part in (current as Record<string, unknown>)) {
      current = (current as Record<string, unknown>)[part];
    } else {
      return path; // fallback to key
    }
  }
  return typeof current === 'string' ? current : path;
}

interface I18nContextValue {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: string) => string;
}

/**
 * Default context value when useTranslation() is called outside an
 * I18nProvider. Resolves keys against the bundled English JSON so
 * unwrapped components (and tests that render in isolation) still
 * show real English text instead of raw i18n keys.
 *
 * Without this fallback, every test that renders a translated component
 * would need to wrap it in <I18nProvider> — a real maintenance burden,
 * and a footgun because tests would silently start matching "key.path"
 * strings instead of failing loud.
 *
 * This does not hide bugs: if a key is missing from en.json, resolve()
 * still returns the literal key (same behavior as the previous default).
 */
const I18nContext = createContext<I18nContextValue>({
  locale: 'en',
  setLocale: () => {},
  t: (key: string) => resolve(en as unknown as Record<string, unknown>, key),
});

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocale] = useState<Locale>(() => {
    if (typeof window === 'undefined') return 'en';
    const saved = localStorage.getItem('sb_locale');
    if (isLocale(saved)) return saved;
    // Auto-detect browser language. Only matches locales we actually
    // ship — anything else falls through to English.
    const browserLang = (navigator.language || '').toLowerCase();
    const match = LOCALES.find((entry) =>
      entry.code !== 'en' && browserLang.startsWith(entry.code.toLowerCase().split('-')[0]),
    );
    return match ? match.code : 'en';
  });

  const handleSetLocale = useCallback((newLocale: Locale) => {
    if (!isLocale(newLocale)) return;
    setLocale(newLocale);
    if (typeof window !== 'undefined') {
      localStorage.setItem('sb_locale', newLocale);
    }
  }, []);

  const t = useCallback(
    (key: string): string => {
      const dict = translations[locale] ?? translations.en;
      const value = resolve(dict as unknown as Record<string, unknown>, key);
      return value;
    },
    [locale],
  );

  return (
    <I18nContext.Provider value={{ locale, setLocale: handleSetLocale, t }}>
      {children}
    </I18nContext.Provider>
  );
}

export function useTranslation() {
  return useContext(I18nContext);
}

export { I18nContext };
