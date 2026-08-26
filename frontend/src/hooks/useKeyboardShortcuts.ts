/**
 * useKeyboardShortcuts — global keyboard shortcut handler for ShadowBroker.
 *
 * Registers document-level keydown listener with guards for inputs/textareas.
 * Returns nothing — side-effect only hook.
 */
import { useEffect, useCallback } from 'react';

interface ShortcutActions {
  toggleLeft: () => void;
  toggleRight: () => void;
  toggleMarkets: () => void;
  openSettings: () => void;
  openLegend: () => void;
  openShortcuts: () => void;
  deselectEntity: () => void;
  focusSearch: () => void;
  /** Optional voice push-to-talk channel — hold V (§5.4). Undefined = legacy
   *  behavior byte-identical to pre-voice builds (V is unbound). */
  voicePtt?: { begin: () => void; end: () => void };
}

function shortcutTargetGuarded(e: KeyboardEvent): boolean {
  // Don't fire shortcuts when typing in inputs
  const tag = (e.target as HTMLElement)?.tagName?.toLowerCase();
  if (tag === 'input' || tag === 'textarea' || tag === 'select') return false;

  // Don't fire when contentEditable is active
  if ((e.target as HTMLElement)?.isContentEditable) return false;

  // Don't fire on modifier key combos (Ctrl+S, etc.)
  if (e.ctrlKey || e.metaKey || e.altKey) return false;
  return true;
}

export function useKeyboardShortcuts(actions: ShortcutActions) {
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (!shortcutTargetGuarded(e)) return;

      // Voice PTT intercepts V before the switch (guarded, repeat ignored).
      if (actions.voicePtt && e.key.toLowerCase() === 'v') {
        if (e.repeat) return;
        e.preventDefault();
        actions.voicePtt.begin();
        return;
      }

      switch (e.key.toLowerCase()) {
        case 'l':
          e.preventDefault();
          actions.toggleLeft();
          break;

        case 'r':
          e.preventDefault();
          actions.toggleRight();
          break;

        case 'm':
          e.preventDefault();
          actions.toggleMarkets();
          break;

        case 's':
          e.preventDefault();
          actions.openSettings();
          break;

        case 'k':
          e.preventDefault();
          actions.openLegend();
          break;

        case ' ': // Space bar
          e.preventDefault();
          actions.openShortcuts();
          break;

        case 'escape':
          e.preventDefault();
          actions.deselectEntity();
          break;

        case 'f':
          e.preventDefault();
          actions.focusSearch();
          break;
      }
    },
    [actions],
  );

  useEffect(() => {
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [handleKeyDown]);

  // Voice PTT: hold Ctrl (works everywhere — Ctrl produces no characters, so
  // it never leaks keystrokes into the composer). Any other key pressed while
  // Ctrl is held cancels the hold (Ctrl+C/V/X are clipboard combos, not
  // speech). V remains the shortcut OUTSIDE text fields (guarded above):
  // keydown begins via the intercept, keyup ends here. Window blur
  // force-releases a stuck hold.
  const voicePtt = actions.voicePtt;
  useEffect(() => {
    if (!voicePtt) return;
    let ctrlHeld = false;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Control' && !e.repeat && !e.shiftKey && !e.altKey && !e.metaKey) {
        if (ctrlHeld) return;
        ctrlHeld = true;
        voicePtt.begin();
        return;
      }
      if (ctrlHeld && e.key !== 'Control') {
        // Combo (Ctrl+C, Ctrl+V, …) — release without transmitting.
        ctrlHeld = false;
        voicePtt.end();
      }
    };
    const handleKeyUp = (e: KeyboardEvent) => {
      if (e.key === 'Control' && ctrlHeld) {
        ctrlHeld = false;
        voicePtt.end();
        return;
      }
      // V keyup ends the hold started by the V keydown intercept (outside
      // inputs only — the intercept's guard already scoped it).
      if (e.key.toLowerCase() === 'v' && shortcutTargetGuarded(e)) {
        voicePtt.end();
      }
    };
    const handleBlur = () => {
      ctrlHeld = false;
      voicePtt.end();
    };
    document.addEventListener('keydown', handleKeyDown);
    document.addEventListener('keyup', handleKeyUp);
    window.addEventListener('blur', handleBlur);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      document.removeEventListener('keyup', handleKeyUp);
      window.removeEventListener('blur', handleBlur);
    };
  }, [voicePtt]);
}
