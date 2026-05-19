import React from 'react';
import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { I18nProvider, LOCALES, useTranslation, type Locale } from '@/i18n';

/**
 * Renders a tiny consumer so we can drive the I18nContext from tests.
 */
function Probe({ keyToRender }: { keyToRender: string }) {
  const { locale, setLocale, t } = useTranslation();
  return (
    <div>
      <span data-testid="locale">{locale}</span>
      <span data-testid="translated">{t(keyToRender)}</span>
      <button onClick={() => setLocale('zh-CN')} data-testid="to-zh">go zh</button>
      <button onClick={() => setLocale('en')} data-testid="to-en">go en</button>
    </div>
  );
}

describe('I18nProvider', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    cleanup();
    localStorage.clear();
  });

  it('exposes a non-empty LOCALES registry with en and zh-CN', () => {
    const codes = LOCALES.map((l) => l.code);
    expect(codes).toContain('en');
    expect(codes).toContain('zh-CN');
    // Native labels — used by the language picker. These must be set
    // so the picker shows the native language name regardless of
    // current UI locale.
    for (const entry of LOCALES) {
      expect(entry.label.length).toBeGreaterThan(0);
    }
  });

  it('defaults to English when no localStorage and English browser', () => {
    Object.defineProperty(navigator, 'language', { value: 'en-US', configurable: true });
    render(
      <I18nProvider>
        <Probe keyToRender="settings.title" />
      </I18nProvider>,
    );
    expect(screen.getByTestId('locale').textContent).toBe('en');
  });

  it('auto-detects zh-CN when browser language starts with "zh"', () => {
    Object.defineProperty(navigator, 'language', { value: 'zh-TW', configurable: true });
    render(
      <I18nProvider>
        <Probe keyToRender="settings.title" />
      </I18nProvider>,
    );
    // "zh-TW" should match the zh prefix and resolve to our zh-CN bundle
    // (we ship only one Chinese variant for now).
    expect(screen.getByTestId('locale').textContent).toBe('zh-CN');
  });

  it('honors a previously saved localStorage choice over auto-detect', () => {
    Object.defineProperty(navigator, 'language', { value: 'zh-CN', configurable: true });
    localStorage.setItem('sb_locale', 'en');
    render(
      <I18nProvider>
        <Probe keyToRender="settings.title" />
      </I18nProvider>,
    );
    expect(screen.getByTestId('locale').textContent).toBe('en');
  });

  it('persists setLocale to localStorage', () => {
    render(
      <I18nProvider>
        <Probe keyToRender="settings.title" />
      </I18nProvider>,
    );

    act(() => {
      screen.getByTestId('to-zh').click();
    });

    expect(screen.getByTestId('locale').textContent).toBe('zh-CN');
    expect(localStorage.getItem('sb_locale')).toBe('zh-CN');
  });

  it('falls back to auto-detect when localStorage holds an unknown locale', () => {
    // Pre-poison localStorage with a value that isn't in LOCALES. The
    // isLocale guard at provider init should ignore it and fall through
    // to navigator.language detection.
    Object.defineProperty(navigator, 'language', { value: 'en-US', configurable: true });
    localStorage.setItem('sb_locale', 'klingon' as unknown as Locale);

    render(
      <I18nProvider>
        <Probe keyToRender="settings.title" />
      </I18nProvider>,
    );

    expect(screen.getByTestId('locale').textContent).toBe('en');
  });

  it('renders a real translated string from the zh-CN bundle', () => {
    Object.defineProperty(navigator, 'language', { value: 'zh-CN', configurable: true });
    render(
      <I18nProvider>
        <Probe keyToRender="settings.title" />
      </I18nProvider>,
    );
    // The zh-CN bundle has settings.title = "设置". If this assertion
    // ever fails after a translation PR, it's a signal that the
    // translation surface was significantly altered.
    expect(screen.getByTestId('translated').textContent).toBe('设置');
  });

  it('falls back to the key when a translation is missing', () => {
    render(
      <I18nProvider>
        <Probe keyToRender="this.key.intentionally.does.not.exist" />
      </I18nProvider>,
    );
    expect(screen.getByTestId('translated').textContent).toBe(
      'this.key.intentionally.does.not.exist',
    );
  });
});
