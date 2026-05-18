'use client';

import { createContext, useContext, useState, useCallback, type ReactNode } from 'react';
import en from './translations/en.json';
import zhCN from './translations/zh-CN.json';

export type Locale = 'en' | 'zh-CN';

const translations: Record<Locale, Record<string, Record<string, string>>> = { en, 'zh-CN': zhCN };

interface I18nContextValue {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: string) => string;
}

const I18nContext = createContext<I18nContextValue>({
  locale: 'en',
  setLocale: () => {},
  t: (key: string) => key,
});

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

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocale] = useState<Locale>(() => {
    if (typeof window === 'undefined') return 'en';
    const saved = localStorage.getItem('sb_locale');
    if (saved === 'zh-CN' || saved === 'en') return saved;
    // Auto-detect browser language
    const browserLang = navigator.language || '';
    return browserLang.startsWith('zh') ? 'zh-CN' : 'en';
  });

  const handleSetLocale = useCallback((newLocale: Locale) => {
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
