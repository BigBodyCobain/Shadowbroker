/**
 * U8 judge regression — the PTT realtime gate must accept EVERY provider
 * that resolves to the §4.3 binary relay. 1fb3ecf added gemini_live
 * server-side but never widened this gate, so a resolved Gemini Live
 * provider left PTT dead end-to-end from the UI.
 */
import { describe, expect, it } from 'vitest';

import { isRealtimeProvider } from '@/hooks/useVoiceAgent';

describe('useVoiceAgent realtime provider gate', () => {
  it('opens audio sessions for all three realtime providers', () => {
    expect(isRealtimeProvider('openai_realtime')).toBe(true);
    expect(isRealtimeProvider('compatible_ws')).toBe(true);
    expect(isRealtimeProvider('gemini_live')).toBe(true);
  });

  it('stays closed for text-only and unresolved providers', () => {
    expect(isRealtimeProvider('local_text')).toBe(false);
    expect(isRealtimeProvider(null)).toBe(false);
    expect(isRealtimeProvider(undefined)).toBe(false);
    expect(isRealtimeProvider('')).toBe(false);
    expect(isRealtimeProvider('unknown_provider')).toBe(false);
  });
});
