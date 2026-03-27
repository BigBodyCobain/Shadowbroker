'use client';

import { useState, useMemo, useRef, useCallback, useEffect } from 'react';
import { motion } from 'framer-motion';
import { Search, X, Check, GripHorizontal } from 'lucide-react';

interface FilterField {
  key: string;
  label: string;
  options: string[];
  optionLabels?: Record<string, string>;
}

interface AdvancedFilterModalProps {
  title: string;
  icon: React.ReactNode;
  accentColor: string; // CSS color string e.g. '#00bcd4'
  accentColorName: string; // tailwind name e.g. 'cyan'
  fields: FilterField[];
  activeFilters: Record<string, string[]>;
  onApply: (filters: Record<string, string[]>) => void;
  onClose: () => void;
}

export default function AdvancedFilterModal({
  title,
  icon,
  accentColor: _accentColor,
  accentColorName,
  fields,
  activeFilters,
  onApply,
  onClose,
}: AdvancedFilterModalProps) {
  // Local draft state — only committed on Apply
  const [draft, setDraft] = useState<Record<string, Set<string>>>(() => {
    const init: Record<string, Set<string>> = {};
    for (const field of fields) {
      init[field.key] = new Set(activeFilters[field.key] || []);
    }
    return init;
  });

  const [searchTerms, setSearchTerms] = useState<Record<string, string>>(() => {
    const init: Record<string, string> = {};
    for (const field of fields) init[field.key] = '';
    return init;
  });

  const [activeTab, setActiveTab] = useState(fields[0]?.key || '');

  // Dragging state
  const [position, setPosition] = useState({ x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState(false);
  const dragStartRef = useRef({ x: 0, y: 0, posX: 0, posY: 0 });
  const modalRef = useRef<HTMLDivElement>(null);

  // Center on mount, clamped so it doesn't overlap the bottom status bar (~48px)
  useEffect(() => {
    if (modalRef.current) {
      const rect = modalRef.current.getBoundingClientRect();
      const pad = 52; // status bar + small gap
      const maxY = window.innerHeight - rect.height - pad;
      setPosition({
        x: Math.max(0, (window.innerWidth - rect.width) / 2),
        y: Math.max(0, Math.min((window.innerHeight - rect.height) / 2, maxY)),
      });
    }
  }, []);

  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      setIsDragging(true);
      dragStartRef.current = { x: e.clientX, y: e.clientY, posX: position.x, posY: position.y };
    },
    [position],
  );

  useEffect(() => {
    if (!isDragging) return;
    const handleMove = (e: MouseEvent) => {
      const dx = e.clientX - dragStartRef.current.x;
      const dy = e.clientY - dragStartRef.current.y;
      const newX = dragStartRef.current.posX + dx;
      const newY = dragStartRef.current.posY + dy;
      // Clamp so modal can't be dragged below the bottom status bar
      const maxY = window.innerHeight - 120; // keep at least 120px visible
      setPosition({
        x: Math.max(-200, newX),
        y: Math.max(0, Math.min(newY, maxY)),
      });
    };
    const handleUp = () => setIsDragging(false);
    window.addEventListener('mousemove', handleMove);
    window.addEventListener('mouseup', handleUp);
    return () => {
      window.removeEventListener('mousemove', handleMove);
      window.removeEventListener('mouseup', handleUp);
    };
  }, [isDragging]);

  const toggleItem = (fieldKey: string, value: string) => {
    setDraft((prev) => {
      const next = { ...prev };
      const s = new Set(prev[fieldKey]);
      if (s.has(value)) s.delete(value);
      else s.add(value);
      next[fieldKey] = s;
      return next;
    });
  };

  const removeChip = (fieldKey: string, value: string) => {
    setDraft((prev) => {
      const next = { ...prev };
      const s = new Set(prev[fieldKey]);
      s.delete(value);
      next[fieldKey] = s;
      return next;
    });
  };

  const clearField = (fieldKey: string) => {
    setDraft((prev) => ({ ...prev, [fieldKey]: new Set<string>() }));
  };

  const clearAll = () => {
    const cleared: Record<string, Set<string>> = {};
    for (const f of fields) cleared[f.key] = new Set<string>();
    setDraft(cleared);
  };

  const handleApply = () => {
    const result: Record<string, string[]> = {};
    for (const [key, set] of Object.entries(draft)) {
      if (set.size > 0) result[key] = Array.from(set);
    }
    onApply(result);
    onClose();
  };

  const totalSelected = Object.values(draft).reduce((acc, s) => acc + s.size, 0);

  const activeField = fields.find((f) => f.key === activeTab);
  const filteredOptions = useMemo(() => {
    if (!activeField) return [];
    const term = (searchTerms[activeTab] || '').toLowerCase();
    const opts = activeField.options;
    if (!term) return opts;
    return opts.filter((o) => {
      const displayLabel = activeField.optionLabels?.[o] || o;
      return displayLabel.toLowerCase().includes(term);
    });
  }, [activeField, activeTab, searchTerms]);

  // Tailwind color map for dynamic classes
  const colorMap: Record<
    string,
    { text: string; bg: string; bgHover: string; border: string; ring: string }
  > = {
    cyan: {
      text: 'text-cyan-400',
      bg: 'bg-cyan-500/10',
      bgHover: 'hover:bg-cyan-500/15',
      border: 'border-cyan-500/30',
      ring: 'ring-cyan-500/50',
    },
    orange: {
      text: 'text-orange-400',
      bg: 'bg-orange-500/10',
      bgHover: 'hover:bg-orange-500/15',
      border: 'border-orange-500/30',
      ring: 'ring-orange-500/50',
    },
    yellow: {
      text: 'text-yellow-400',
      bg: 'bg-yellow-500/10',
      bgHover: 'hover:bg-yellow-500/15',
      border: 'border-yellow-500/30',
      ring: 'ring-yellow-500/50',
    },
    pink: {
      text: 'text-pink-400',
      bg: 'bg-pink-500/10',
      bgHover: 'hover:bg-pink-500/15',
      border: 'border-pink-500/30',
      ring: 'ring-pink-500/50',
    },
    blue: {
      text: 'text-blue-400',
      bg: 'bg-blue-500/10',
      bgHover: 'hover:bg-blue-500/15',
      border: 'border-blue-500/30',
      ring: 'ring-blue-500/50',
    },
  };
  const c = colorMap[accentColorName] || colorMap.cyan;

  return (
    <div
      className="fixed inset-0 z-[9999] pointer-events-auto"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/40 backdrop-blur-[2px]" />

      {/* Modal */}
      <div
        ref={modalRef}
        className="absolute"
        style={{
          left: position.x,
          top: position.y,
          width: 480,
          userSelect: isDragging ? 'none' : 'auto',
        }}
      >
        <motion.div
          initial={{ opacity: 0, scale: 0.92 }}
          animate={{ opacity: 1, scale: 1 }}
          exit={{ opacity: 0, scale: 0.92 }}
          transition={{ duration: 0.2 }}
          className={`bg-[var(--bg-secondary)]/95 backdrop-blur-sm border ${c.border} shadow-[0_8px_60px_rgba(0,0,0,0.3)] flex flex-col font-mono overflow-hidden`}
          style={{ maxHeight: 'calc(100vh - 80px)' }}
        >
          {/* ── Title Bar (Draggable) ── */}
          <div
            className="flex items-center justify-between px-4 py-3 cursor-grab active:cursor-grabbing border-b border-[var(--border-primary)]/60 select-none flex-shrink-0"
            onMouseDown={handleMouseDown}
          >
            <div className="flex items-center gap-2.5">
              <GripHorizontal size={14} className="text-[var(--text-muted)]" />
              {icon}
              <span className={`text-[11px] ${c.text} tracking-[0.25em] font-semibold`}>
                {title}
              </span>
              {totalSelected > 0 && (
                <span className={`text-[9px] ${c.bg} ${c.text} px-1.5 py-0.5 rounded-sm`}>
                  {totalSelected} SELECTED
                </span>
              )}
            </div>
            <button
              onClick={onClose}
              className="text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors p-1 hover:bg-[var(--bg-tertiary)]"
            >
              <X size={14} />
            </button>
          </div>

          {/* ── Tab Bar (for multi-field categories) ── */}
          {fields.length > 1 && (
            <div className="flex border-b border-[var(--border-primary)]/40 px-3 pt-2 gap-1 flex-shrink-0">
              {fields.map((field) => {
                const isActive = activeTab === field.key;
                const count = draft[field.key]?.size || 0;
                return (
                  <button
                    key={field.key}
                    onClick={() => setActiveTab(field.key)}
                    className={`px-3 py-1.5 text-[9px] tracking-widest rounded-t transition-colors relative ${
                      isActive
                        ? `${c.bg} ${c.text} border border-b-0 ${c.border}`
                        : 'text-gray-500 hover:text-gray-300 border border-transparent'
                    }`}
                  >
                    {field.label}
                    {count > 0 && (
                      <span className={`ml-1.5 text-[8px] ${c.text} bg-black/40 px-1`}>
                        {count}
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          )}

          {/* ── Selected Chips ── */}
          {activeField && draft[activeTab]?.size > 0 && (
            <div className="px-4 pt-3 pb-1 flex flex-wrap gap-1.5 flex-shrink-0 max-h-20 overflow-y-auto styled-scrollbar">
              {Array.from(draft[activeTab]).map((val) => {
                const displayVal = activeField.optionLabels?.[val] || val;
                return (
                  <span
                    key={val}
                    className={`inline-flex items-center gap-1 text-[9px] ${c.bg} ${c.text} border ${c.border} rounded-full px-2 py-0.5 group`}
                  >
                    {displayVal.length > 28 ? displayVal.slice(0, 28) + '…' : displayVal}
                    <button
                      onClick={() => removeChip(activeTab, val)}
                      className="opacity-50 group-hover:opacity-100 transition-opacity"
                    >
                      <X size={8} />
                    </button>
                  </span>
                );
              })}
              <button
                onClick={() => clearField(activeTab)}
                className="text-[8px] text-red-400/70 hover:text-red-300 tracking-widest ml-1"
              >
                CLEAR
              </button>
            </div>
          )}

          {/* ── Search Bar ── */}
          <div className="px-4 pt-3 pb-2 flex-shrink-0">
            <div className="relative">
              <Search
                size={12}
                className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-600"
              />
              <input
                type="text"
                value={searchTerms[activeTab] || ''}
                onChange={(e) =>
                  setSearchTerms((prev) => ({ ...prev, [activeTab]: e.target.value }))
                }
                placeholder={`Search ${activeField?.label.toLowerCase() || ''}...`}
                className={`w-full bg-[var(--bg-primary)]/50 border border-[var(--border-primary)]/70 text-[11px] text-[var(--text-secondary)] pl-8 pr-8 py-2 font-mono tracking-wide focus:outline-none focus:${c.border} focus:ring-1 ${c.ring} placeholder-[var(--text-muted)] transition-all`}
                autoFocus
              />
              {searchTerms[activeTab] && (
                <button
                  onClick={() => setSearchTerms((prev) => ({ ...prev, [activeTab]: '' }))}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-600 hover:text-gray-300"
                >
                  <X size={12} />
                </button>
              )}
            </div>
            <div className="flex justify-between mt-1.5">
              <span className="text-[8px] text-[var(--text-muted)] tracking-widest">
                {filteredOptions.length} AVAILABLE
              </span>
              <span className="text-[8px] text-[var(--text-muted)] tracking-widest">
                {draft[activeTab]?.size || 0} SELECTED
              </span>
            </div>
          </div>

          {/* ── Scrollable Checkbox List ── */}
          <div
            className="flex-1 min-h-0 overflow-y-auto px-2 pb-2 styled-scrollbar"
            style={{ maxHeight: '35vh' }}
          >
            {filteredOptions.length === 0 ? (
              <div className="text-center py-8 text-[var(--text-muted)] text-[10px] tracking-widest">
                NO MATCHING RESULTS
              </div>
            ) : (
              <div className="flex flex-col gap-px">
                {filteredOptions.map((option) => {
                  const isChecked = draft[activeTab]?.has(option);
                  return (
                    <button
                      key={option}
                      onClick={() => toggleItem(activeTab, option)}
                      className={`flex items-center gap-2.5 px-3 py-1.5 text-left transition-all group ${
                        isChecked
                          ? `${c.bg} ${c.text}`
                          : `text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)]/50 hover:text-[var(--text-primary)]`
                      }`}
                    >
                      {/* Checkbox */}
                      <div
                        className={`w-3.5 h-3.5 rounded-[3px] border flex items-center justify-center flex-shrink-0 transition-all ${
                          isChecked
                            ? `${c.border} ${c.bg}`
                            : 'border-[var(--border-primary)] group-hover:border-[var(--border-secondary)]'
                        }`}
                      >
                        {isChecked && <Check size={9} strokeWidth={3} />}
                      </div>
                      <span className="text-[10px] tracking-wide truncate">
                        {activeField?.optionLabels?.[option] || option}
                      </span>
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          {/* ── Footer ── */}
          <div className="flex items-center justify-between px-4 py-3 border-t border-[var(--border-primary)]/60 flex-shrink-0">
            <button
              onClick={clearAll}
              className="text-[9px] text-red-400/70 hover:text-red-300 tracking-widest transition-colors"
            >
              CLEAR ALL
            </button>
            <div className="flex gap-2">
              <button
                onClick={onClose}
                className="text-[9px] text-[var(--text-muted)] hover:text-[var(--text-secondary)] tracking-widest border border-[var(--border-primary)] px-4 py-1.5 hover:bg-[var(--bg-tertiary)]/50 transition-all"
              >
                CANCEL
              </button>
              <button
                onClick={handleApply}
                className={`text-[9px] ${c.text} tracking-widest border ${c.border} px-4 py-1.5 ${c.bg} ${c.bgHover} transition-all font-semibold`}
              >
                APPLY{totalSelected > 0 ? ` (${totalSelected})` : ''}
              </button>
            </div>
          </div>
        </motion.div>
      </div>
    </div>
  );
}
