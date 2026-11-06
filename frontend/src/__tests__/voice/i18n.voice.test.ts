/**
 * §7.D item 35 — i18n parity: every voice.* key resolves in en/zh-CN/fr/fa;
 * a missing key in any locale fails CI.
 */
import { describe, expect, it } from 'vitest';

import en from '@/i18n/translations/en.json';
import zhCN from '@/i18n/translations/zh-CN.json';
import fr from '@/i18n/translations/fr.json';
import fa from '@/i18n/translations/fa.json';

type Dict = Record<string, unknown>;

const LOCALES: Array<[string, Dict]> = [
  ['en', en as unknown as Dict],
  ['zh-CN', zhCN as unknown as Dict],
  ['fr', fr as unknown as Dict],
  ['fa', fa as unknown as Dict],
];

function resolve(dict: Dict, path: string): string | undefined {
  let current: unknown = dict;
  for (const part of path.split('.')) {
    if (current && typeof current === 'object' && part in (current as Dict)) {
      current = (current as Dict)[part];
    } else {
      return undefined;
    }
  }
  return typeof current === 'string' ? current : undefined;
}

function leafPaths(obj: Dict, prefix = ''): string[] {
  const paths: string[] = [];
  for (const [key, value] of Object.entries(obj)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (value && typeof value === 'object') paths.push(...leafPaths(value as Dict, path));
    else paths.push(path);
  }
  return paths;
}

const EN_VOICE_KEYS = leafPaths(en.voice as Dict).map((p) => `voice.${p}`);

describe('i18n voice namespace parity', () => {
  it('english defines the full voice key set (9 mic phases + panels + states)', () => {
    expect(EN_VOICE_KEYS.length).toBeGreaterThan(20);
    for (const phase of ['opt-in-required', 'lean-unavailable', 'idle', 'connecting', 'listening', 'thinking', 'speaking', 'error', 'quota-capped']) {
      expect(EN_VOICE_KEYS).toContain(`voice.micAria.${phase}`);
    }
  });

  it('every voice.* key resolves to a real string in all four locales', () => {
    for (const [locale, dict] of LOCALES) {
      for (const key of EN_VOICE_KEYS) {
        const value = resolve(dict, key);
        expect(value, `${key} missing in ${locale}`).toBeDefined();
        expect(value, `${key} empty in ${locale}`).not.toBe('');
        expect(value, `${key} unresolved in ${locale}`).not.toBe(key);
      }
    }
  });
});
