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
}

export function useKeyboardShortcuts(actions: ShortcutActions) {
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      // Don't fire shortcuts when typing in inputs
      const tag = (e.target as HTMLElement)?.tagName?.toLowerCase();
      if (tag === 'input' || tag === 'textarea' || tag === 'select') return;

      // Don't fire when contentEditable is active
      if ((e.target as HTMLElement)?.isContentEditable) return;

      // Don't fire on modifier key combos (Ctrl+S, etc.)
      if (e.ctrlKey || e.metaKey || e.altKey) return;

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
}
