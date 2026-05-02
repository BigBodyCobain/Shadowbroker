'use client';

import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import type { WatchlistEntry } from '@/hooks/useWatchlist';
import { Eye, X, Trash2, ChevronUp, ChevronDown, Crosshair } from 'lucide-react';

function getTypeIcon(type: string) {
  switch (type) {
    case 'flight': return '✈';
    case 'ship': return '🚢';
    case 'news': return '📰';
    case 'satellite': return '🛰';
    default: return '📍';
  }
}

function getTypeColor(type: string) {
  switch (type) {
    case 'flight': return '#22d3ee';
    case 'ship': return '#3b82f6';
    case 'news': return '#f97316';
    case 'satellite': return '#a855f7';
    default: return '#6b7280';
  }
}

export default function WatchlistWidget({
  items,
  onRemove,
  onClear,
  onFlyTo,
}: {
  items: WatchlistEntry[];
  onRemove: (id: string) => void;
  onClear: () => void;
  onFlyTo?: (lat: number, lng: number) => void;
}) {
  const [expanded, setExpanded] = useState(false);

  if (items.length === 0) return null;

  return (
    <div className="absolute bottom-[6.5rem] left-6 z-[200] pointer-events-auto hud-zone">
      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ opacity: 0, y: 10, height: 0 }}
            animate={{ opacity: 1, y: 0, height: 'auto' }}
            exit={{ opacity: 0, y: 10, height: 0 }}
            transition={{ type: 'spring', damping: 25, stiffness: 300 }}
            className="mb-1 bg-[var(--bg-panel)] border border-[var(--border-primary)] rounded-sm overflow-hidden backdrop-blur-sm"
            style={{
              width: '260px',
              maxHeight: '300px',
              boxShadow: '0 0 20px rgba(6, 182, 212, 0.08)',
            }}
          >
            {/* Header */}
            <div className="flex items-center justify-between px-3 py-2 border-b border-[var(--border-primary)]">
              <span className="text-[10px] font-mono tracking-[0.2em] text-[var(--text-heading)] font-bold">
                WATCHLIST
              </span>
              <button
                onClick={onClear}
                className="text-[var(--text-muted)] hover:text-red-400 transition-colors"
                title="Clear all"
              >
                <Trash2 size={12} />
              </button>
            </div>

            {/* Items */}
            <div className="overflow-y-auto styled-scrollbar" style={{ maxHeight: '240px' }}>
              {items.map((item) => (
                <div
                  key={item.id}
                  className="flex items-center gap-2 px-3 py-2 hover:bg-[var(--hover-accent)] transition-colors border-b border-[var(--border-primary)]/30 cursor-pointer group"
                  onClick={() => onFlyTo?.(item.lat, item.lng)}
                >
                  {/* Type icon */}
                  <span className="text-sm flex-shrink-0">{getTypeIcon(item.type)}</span>

                  {/* Info */}
                  <div className="flex-1 min-w-0">
                    <div
                      className="text-[11px] font-mono truncate"
                      style={{ color: getTypeColor(item.type) }}
                    >
                      {item.name}
                    </div>
                    <div className="text-[9px] font-mono text-[var(--text-muted)] tracking-wider uppercase">
                      {item.type}
                      {item.altitude != null && ` · ${Math.round(item.altitude).toLocaleString()} ft`}
                      {item.speed != null && ` · ${Math.round(item.speed)} kts`}
                      {item.risk_score != null && ` · LVL ${item.risk_score}`}
                    </div>
                  </div>

                  {/* Fly-to button */}
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onFlyTo?.(item.lat, item.lng);
                    }}
                    className="text-[var(--text-muted)] hover:text-cyan-400 transition-colors opacity-0 group-hover:opacity-100 flex-shrink-0"
                    title="Fly to"
                  >
                    <Crosshair size={12} />
                  </button>

                  {/* Remove button */}
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onRemove(item.id);
                    }}
                    className="text-[var(--text-muted)] hover:text-red-400 transition-colors opacity-0 group-hover:opacity-100 flex-shrink-0"
                    title="Remove"
                  >
                    <X size={12} />
                  </button>
                </div>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Collapsed badge */}
      <button
        onClick={() => setExpanded((p) => !p)}
        className="flex items-center gap-2 px-3 py-1.5 bg-[var(--bg-panel)] border border-[var(--border-primary)] rounded-sm hover:border-cyan-500/40 transition-colors"
        style={{ boxShadow: '0 0 12px rgba(6, 182, 212, 0.06)' }}
      >
        <Eye size={13} className="text-cyan-400" />
        <span className="text-[10px] font-mono tracking-[0.15em] text-[var(--text-heading)] font-bold">
          {items.length} TRACKED
        </span>
        {expanded ? (
          <ChevronDown size={12} className="text-[var(--text-muted)]" />
        ) : (
          <ChevronUp size={12} className="text-[var(--text-muted)]" />
        )}
      </button>
    </div>
  );
}
