'use client';

import React, { useEffect, useState } from 'react';
import { motion, AnimatePresence } from '@/lib/motion';
import { Database, Clock, X } from 'lucide-react';

const CURRENT_VERSION = '0.9.83';
const STORAGE_KEY = `shadowbroker_startup_warmup_notice_v${CURRENT_VERSION}`;

interface StartupWarmupModalProps {
  onClose: () => void;
}

export default function StartupWarmupModal({ onClose }: StartupWarmupModalProps) {
  const handleDismiss = () => {
    localStorage.setItem(STORAGE_KEY, 'true');
    onClose();
  };

  return (
    <AnimatePresence>
      <motion.div
        key="warmup-backdrop"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 bg-black/80 backdrop-blur-sm z-[10000]"
        onClick={handleDismiss}
      />
      <motion.div
        key="warmup-modal"
        initial={{ opacity: 0, scale: 0.92, y: 18 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.92, y: 18 }}
        transition={{ type: 'spring', damping: 25, stiffness: 300 }}
        className="fixed inset-0 z-[10001] flex items-center justify-center pointer-events-none"
      >
        <div
          className="w-[520px] max-w-[calc(100vw-32px)] bg-[var(--bg-secondary)]/98 border border-cyan-900/50 pointer-events-auto overflow-hidden"
          onClick={(e) => e.stopPropagation()}
        >
          <div className="p-5 border-b border-[var(--border-primary)]/80 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 bg-cyan-500/10 border border-cyan-500/30 flex items-center justify-center">
                <Database size={18} className="text-cyan-400" />
              </div>
              <div>
                <h2 className="text-sm font-bold tracking-[0.2em] text-[var(--text-primary)] font-mono">
                  STARTUP CACHE
                </h2>
                <span className="text-[13px] text-[var(--text-muted)] font-mono tracking-widest">
                  FIRST RUN WARMUP
                </span>
              </div>
            </div>
            <button
              onClick={handleDismiss}
              className="w-8 h-8 border border-[var(--border-primary)] hover:border-red-500/50 flex items-center justify-center text-[var(--text-muted)] hover:text-red-400 transition-all hover:bg-red-950/20"
            >
              <X size={14} />
            </button>
          </div>

          <div className="p-5 space-y-4">
            <div className="bg-cyan-950/20 border border-cyan-500/20 p-4">
              <div className="flex items-start gap-3">
                <Clock size={15} className="text-cyan-400 mt-0.5 flex-shrink-0" />
                <div className="space-y-2">
                  <p className="text-[11px] text-cyan-300 font-mono font-bold tracking-widest">
                    MASS DATA SYNTHESIS
                  </p>
                  <p className="text-sm text-[var(--text-secondary)] font-mono leading-relaxed">
                    The first launch builds local caches for flights, ships, satellites, CCTV, fires,
                    and threat intelligence. Cached launches paint the map much faster; a brand-new
                    install can take a few minutes while upstream feeds are synthesized.
                  </p>
                </div>
              </div>
            </div>

            <button
              onClick={handleDismiss}
              className="w-full py-3 border border-cyan-500/40 text-cyan-300 hover:text-cyan-100 hover:border-cyan-400/70 hover:bg-cyan-950/30 transition-all font-mono text-[12px] tracking-[0.18em] font-bold"
            >
              CONTINUE
            </button>
          </div>
        </div>
      </motion.div>
    </AnimatePresence>
  );
}

export function useStartupWarmupNotice() {
  const [showWarmupNotice, setShowWarmupNotice] = useState(false);

  useEffect(() => {
    try {
      setShowWarmupNotice(localStorage.getItem(STORAGE_KEY) !== 'true');
    } catch {
      setShowWarmupNotice(false);
    }
  }, []);

  return { showWarmupNotice, setShowWarmupNotice };
}
