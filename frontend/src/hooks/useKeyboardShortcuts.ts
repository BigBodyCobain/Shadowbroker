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

  // Voice PTT: guarded keydown+keyup pair on V (§5.4). e.repeat ignored;
  // window blur force-releases a stuck hold. Keydown-only legacy builds
  // (no voicePtt action) are untouched.
  const voicePtt = actions.voicePtt;
  useEffect(() => {
    if (!voicePtt) return;
    const isVoiceKey = (e: KeyboardEvent) => shortcutTargetGuarded(e) && e.key.toLowerCase() === 'v';
    const handleKeyUp = (e: KeyboardEvent) => {
      if (!isVoiceKey(e)) return;
      e.preventDefault();
      voicePtt.end();
    };
    const handleBlur = () => {
      voicePtt.end();
    };
    document.addEventListener('keyup', handleKeyUp);
    window.addEventListener('blur', handleBlur);
    return () => {
      document.removeEventListener('keyup', handleKeyUp);
      window.removeEventListener('blur', handleBlur);
    };
  }, [voicePtt]);
}
