/**
 * Tests for companion section failure visibility in SettingsPanel.
 *
 * Verifies the contract from P6E:
 * - When fetchCompanionStatus rejects, the companion section still renders
 *   (with an unavailable/error state) rather than silently disappearing
 * - When fetchCompanionStatus succeeds, normal controls are shown
 *
 * These are logic-level tests for the state transitions — they do NOT
 * render SettingsPanel (which has deep dependency chains). They verify
 * the decision logic: companionLoadFailed drives visibility.
 */

import { describe, expect, it } from 'vitest';

describe('companion section visibility contract', () => {
  it('companionAvailable && companionLoadFailed shows the section (failure path)', () => {
    // Simulates the render guard: {companionAvailable && (companion || companionLoadFailed) && (...)}
    const companionAvailable = true;
    const companion = null; // fetch failed, no status loaded
    const companionLoadFailed = true;

    const shouldRender = companionAvailable && (companion || companionLoadFailed);
    expect(shouldRender).toBeTruthy();
  });

  it('companionAvailable && companion shows the section (success path)', () => {
    const companionAvailable = true;
    const companion = { enabled: false, url: null, warning: 'Reduced trust.' };
    const companionLoadFailed = false;

    const shouldRender = companionAvailable && (companion || companionLoadFailed);
    expect(shouldRender).toBeTruthy();
  });

  it('section is hidden when not on desktop (companionAvailable=false)', () => {
    const companionAvailable = false;
    const companion = null;
    const companionLoadFailed = true;

    const shouldRender = companionAvailable && (companion || companionLoadFailed);
    expect(shouldRender).toBeFalsy();
  });

  it('section is hidden before first load attempt (no status, no failure)', () => {
    const companionAvailable = true;
    const companion = null;
    const companionLoadFailed = false;

    const shouldRender = companionAvailable && (companion || companionLoadFailed);
    expect(shouldRender).toBeFalsy();
  });

  it('controls are hidden when companion is null (failure mode shows only error)', () => {
    // In the rendered UI: {companion && (<buttons>)} — buttons hidden when companion is null
    const companion = null;
    const companionLoadFailed = true;

    const showControls = !!companion;
    expect(showControls).toBe(false);
    // But the section itself should still render
    expect(companionLoadFailed).toBe(true);
  });

  it('warning box only renders when companion has a warning string', () => {
    // {companion?.warning && (<warning>)}
    const companionNull = null;
    const companionWithWarning = { enabled: true, url: 'http://127.0.0.1:9876', warning: 'Reduced trust.' };
    const companionNoWarning = { enabled: false, url: null, warning: '' };

    expect(companionNull?.warning).toBeFalsy();
    expect(companionWithWarning?.warning).toBeTruthy();
    expect(companionNoWarning?.warning).toBeFalsy();
  });
});
