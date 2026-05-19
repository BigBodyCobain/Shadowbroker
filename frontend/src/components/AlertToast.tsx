'use client';

import { useEffect, useState } from 'react';
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

// Internal component to handle individual toast lifecycle (timer & pause on hover)
function ToastCard({
  toast,
  onDismiss,
  onFlyTo,
}: {
  toast: ToastItem;
  onDismiss: (id: string) => void;
  onFlyTo?: (lat: number, lng: number) => void;
}) {
  const [isPaused, setIsPaused] = useState(false);
  const color = getRiskColor(toast.risk_score);
  const label = getRiskLabel(toast.risk_score);

  useEffect(() => {
    if (isPaused) return;

    const timer = setTimeout(() => {
      onDismiss(toast.id);
    }, 5000); // 5 seconds duration

    return () => clearTimeout(timer);
  }, [isPaused, toast.id, onDismiss]);

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: -20, scale: 0.95 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, scale: 0.9, transition: { duration: 0.2 } }}
      onMouseEnter={() => setIsPaused(true)}
      onMouseLeave={() => setIsPaused(false)}
      className="pointer-events-auto relative overflow-hidden rounded-lg border bg-slate-900/95 p-4 shadow-lg backdrop-blur-sm transition-colors duration-200"
      style={{ borderColor: `${color}40` }}
    >
      <div className="flex flex-col gap-1.5">
        <div className="flex items-center justify-between gap-2">
          <span 
            className="rounded px-1.5 py-0.5 text-xs font-black tracking-wider text-slate-950"
            style={{ backgroundColor: color }}
          >
            {label}
          </span>
          <div className="flex items-center gap-1">
            {onFlyTo && toast.lat && toast.lng && (
              <button
                onClick={() => onFlyTo(toast.lat!, toast.lng!)}
                className="rounded p-1 text-slate-400 hover:bg-slate-800 hover:text-slate-200 transition-colors"
                title="Locate on map"
              >
                📍
              </button>
            )}
            <button
              onClick={() => onDismiss(toast.id)}
              className="rounded p-1 text-slate-400 hover:bg-slate-800 hover:text-slate-200 transition-colors"
            >
              ✕
            </button>
          </div>
        </div>
        
        {toast.message && (
          <p className="text-sm font-medium text-slate-200">{toast.message}</p>
        )}
      </div>

      {/* Animated Progress Bar Visual Feature */}
      <motion.div
        initial={{ scaleX: 1 }}
        animate={{ scaleX: isPaused ? undefined : 0 }}
        transition={{ duration: 5, ease: 'linear' }}
        className="absolute bottom-0 left-0 h-1 w-full origin-left"
        style={{ backgroundColor: color }}
      />
    </motion.div>
  );
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
    <div className="fixed top-16 right-[440px] z-[9500] flex flex-col gap-2 pointer-events-none max-w-[380px] w-full">
      <AnimatePresence mode="popLayout">
        {toasts.map((toast) => (
          <ToastCard
            key={toast.id}
            toast={toast}
            onDismiss={onDismiss}
            onFlyTo={onFlyTo}
          />
        ))}
      </AnimatePresence>
    </div>
  );
}
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
