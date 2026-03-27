'use client';

import React, { useEffect } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { X, Minus } from 'lucide-react';
import InfonetShell from './InfonetShell';

interface InfonetTerminalProps {
  isOpen: boolean;
  onClose: () => void;
  onOpenLiveGate?: (gate: string) => void;
}

export default function InfonetTerminal({ isOpen, onClose, onOpenLiveGate }: InfonetTerminalProps) {
  /* Close on Escape */
  useEffect(() => {
    if (!isOpen) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [isOpen, onClose]);

  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
          className="fixed inset-0 z-[400] flex items-center justify-center bg-black/60 backdrop-blur-[2px]"
        >
          {/* Window container */}
          <motion.div
            initial={{ scale: 0.95, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0.95, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="relative flex flex-col w-[95vw] h-[90vh] max-w-[1400px] max-h-[900px] bg-[#0a0a0a] border border-cyan-900/40 shadow-[0_0_60px_rgba(6,182,212,0.08)] crt infonet-font"
          >
            {/* Title bar */}
            <div className="flex items-center justify-between px-4 py-2 border-b border-gray-800/60 bg-[#080808] shrink-0 select-none">
              <div className="flex items-center gap-2">
                <div className="w-2 h-2 rounded-full bg-cyan-500/60 shadow-[0_0_6px_rgba(6,182,212,0.4)]" />
                <span className="text-sm tracking-[0.3em] text-gray-500 uppercase">
                  Infonet Sovereign Shell v0.1.1
                </span>
              </div>
              <div className="flex items-center gap-1">
                <button
                  onClick={onClose}
                  className="p-1 text-gray-600 hover:text-gray-300 transition-colors"
                  title="Minimize"
                >
                  <Minus size={14} />
                </button>
                <button
                  onClick={onClose}
                  className="p-1 text-gray-600 hover:text-red-400 transition-colors"
                  title="Close (Esc)"
                >
                  <X size={14} />
                </button>
              </div>
            </div>

            {/* Shell content — fills remaining space, scrolls internally */}
            <div className="flex-1 overflow-hidden">
              <InfonetShell isOpen={isOpen} onClose={onClose} onOpenLiveGate={onOpenLiveGate} />
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
