'use client';

import { motion, AnimatePresence } from 'framer-motion';
import type { ToastItem } from '@/hooks/useAlertToasts';

function getRiskColor(score: number): string {
  if (score >= 9) return '#ef4444';
  if (score >= 7) return '#f97316';
  if (score >= 4) return '#eab308';
  return '#22d3ee';
}

function getRiskLabel(score: number): string {
  if (score >= 9) return 'CRITICAL';
  if (score >= 7) return 'HIGH';
  return 'ELEVATED';
}

export default function AlertToast({
  toasts,
  onDismiss,
  onFlyTo,
}: {
  toasts: ToastItem[];
  onDismiss: (id: string) => void;
  onFlyTo?: (lat: number, lng: number) => void;
}) {
  return (
    <div className="fixed top-16 right-[440px] z-[9500] flex flex-col gap-2 pointer-events-none max-w-[380px]">
      <AnimatePresence mode="popLayout">
        {toasts.map((toast) => {
          const color = getRiskColor(toast.risk_score);
          const label = getRiskLabel(toast.risk_score);
          return (
            <motion.div
              key={toast.id}
              layout
              initial={{ opacity: 0, x: 100, scale: 0.9 }}
              animate={{ opacity: 1, x: 0, scale: 1 }}
              exit={{ opacity: 0, x: 100, scale: 0.9 }}
              transition={{ type: 'spring', damping: 25, stiffness: 300 }}
              className="pointer-events-auto cursor-pointer"
              onClick={() => {
                if (onFlyTo && toast.lat && toast.lng) {
                  onFlyTo(toast.lat, toast.lng);
                }
                onDismiss(toast.id);
              }}
            >
              <div
                className="relative bg-[rgba(5,5,5,0.96)] backdrop-blur-sm rounded-sm overflow-hidden font-mono"
                style={{
                  borderLeft: `3px solid ${color}`,
                  boxShadow: `0 0 20px ${color}40, 0 4px 12px rgba(0,0,0,0.5)`,
                }}
              >
                {/* Progress bar */}
                <motion.div
                  className="absolute top-0 left-0 h-[2px]"
                  style={{ background: color }}
                  initial={{ width: '100%' }}
                  animate={{ width: '0%' }}
                  transition={{ duration: 5, ease: 'linear' }}
                />

                <div className="p-3 pr-8">
                  {/* Header */}
                  <div className="flex items-center gap-2 mb-1.5">
                    <span
                      className="text-[9px] font-bold tracking-[0.2em] px-1.5 py-0.5 rounded-sm"
                      style={{
                        background: `${color}20`,
                        color: color,
                        border: `1px solid ${color}40`,
                      }}
                    >
                      ⚠ {label}
                    </span>
                    <span className="text-[9px] text-[var(--text-muted)] tracking-wider uppercase">
                      LVL {toast.risk_score}/10
                    </span>
                  </div>

                  {/* Title */}
                  <div
                    className="text-[11px] text-[var(--text-primary)] leading-tight mb-1"
                    style={{ display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}
                  >
                    {toast.title}
                  </div>

                  {/* Source */}
                  <div className="text-[9px] text-[var(--text-muted)] tracking-wider uppercase">
                    {toast.source}
                  </div>
                </div>

                {/* Dismiss button */}
                <button
                  className="absolute top-2 right-2 text-[var(--text-muted)] hover:text-white transition-colors text-xs font-bold"
                  onClick={(e) => {
                    e.stopPropagation();
                    onDismiss(toast.id);
                  }}
                >
                  ×
                </button>
              </div>
            </motion.div>
          );
        })}
      </AnimatePresence>
    </div>
  );
}
