'use client';

import { motion, AnimatePresence } from 'framer-motion';

const shortcuts = [
  { key: 'L', desc: 'Toggle left panel (LAYERS)' },
  { key: 'R', desc: 'Toggle right panel (INTEL)' },
  { key: 'M', desc: 'Toggle markets ticker' },
  { key: 'S', desc: 'Open settings' },
  { key: 'K', desc: 'Open map legend (KEY)' },
  { key: 'F', desc: 'Focus search bar' },
  { key: 'Esc', desc: 'Deselect / close modals' },
  { key: 'Space', desc: 'Toggle this overlay' },
];

export default function KeyboardShortcutsOverlay({
  isOpen,
  onClose,
}: {
  isOpen: boolean;
  onClose: () => void;
}) {
  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          className="fixed inset-0 z-[9500] flex items-center justify-center"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
          onClick={onClose}
        >
          {/* Backdrop */}
          <div className="absolute inset-0 bg-black/80 backdrop-blur-sm" />

          {/* Content */}
          <motion.div
            className="relative z-10 bg-[var(--bg-primary)]/95 border border-[var(--border-secondary)] rounded-sm p-8 max-w-md w-full mx-4 shadow-[0_0_40px_rgba(6,182,212,0.1)]"
            initial={{ scale: 0.9, y: 20 }}
            animate={{ scale: 1, y: 0 }}
            exit={{ scale: 0.9, y: 20 }}
            transition={{ type: 'spring', damping: 25, stiffness: 300 }}
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header */}
            <div className="flex items-center justify-between mb-6">
              <div className="flex items-center gap-3">
                <div className="text-[18px] text-[var(--text-heading)] font-mono font-bold tracking-widest">
                  KEYBOARD SHORTCUTS
                </div>
              </div>
              <button
                onClick={onClose}
                className="text-[var(--text-muted)] hover:text-cyan-400 transition-colors text-lg font-bold"
              >
                ×
              </button>
            </div>

            {/* Divider */}
            <div className="h-px bg-[var(--border-primary)] mb-4" />

            {/* Shortcuts Grid */}
            <div className="flex flex-col gap-2">
              {shortcuts.map(({ key, desc }) => (
                <div
                  key={key}
                  className="flex items-center justify-between py-1.5"
                >
                  <span className="text-[12px] font-mono text-[var(--text-primary)] tracking-wide">
                    {desc}
                  </span>
                  <kbd className="inline-flex items-center justify-center min-w-[32px] px-2 py-1 rounded-sm bg-cyan-950/40 border border-cyan-800/50 text-[11px] font-mono font-bold text-cyan-400 tracking-wider">
                    {key}
                  </kbd>
                </div>
              ))}
            </div>

            {/* Footer */}
            <div className="mt-6 pt-3 border-t border-[var(--border-primary)]">
              <div className="text-[9px] font-mono tracking-[0.25em] text-[var(--text-muted)] text-center uppercase">
                Shortcuts are disabled when typing in inputs
              </div>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
