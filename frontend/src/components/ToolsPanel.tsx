'use client';

import React, { useEffect, useRef, useState } from 'react';
import { Wrench, Radar, ScanSearch, Target, AlertTriangle, Brain, Minus } from 'lucide-react';

export type ToolId = 'shodan' | 'recon' | 'scm' | 'cyber' | 'ai';

const TOOLS: { id: ToolId; name: string; Icon: typeof Radar; tint: string }[] = [
  { id: 'shodan', name: 'SHODAN CONNECTOR', Icon: Radar, tint: 'text-green-400' },
  { id: 'recon', name: 'RECON TOOLKIT', Icon: ScanSearch, tint: 'text-cyan-400' },
  { id: 'scm', name: 'SUPPLY CHAIN', Icon: Target, tint: 'text-cyan-400' },
  { id: 'cyber', name: 'CYBER THREATS', Icon: AlertTriangle, tint: 'text-amber-400' },
  { id: 'ai', name: 'AI INTEL', Icon: Brain, tint: 'text-violet-400' },
];

/**
 * One card for the five operator tools. Collapsed it is a single bar of icon tabs; clicking a
 * tab opens that tool below (clicking it again, or the minus, closes it). Every tool stays
 * mounted while hidden so its polling, results and map overlays carry on as before.
 */
export default function ToolsPanel({ panels }: { panels: Record<ToolId, React.ReactNode> }) {
  const [active, setActive] = useState<ToolId | null>(null);
  const current = TOOLS.find((tool) => tool.id === active);
  const rootRef = useRef<HTMLDivElement>(null);
  // on short screens the card sits at the bottom of the scrolling column: bring an opened tool into view
  useEffect(() => {
    if (!active) return;
    const id = window.setTimeout(() => rootRef.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }), 60);
    return () => window.clearTimeout(id);
  }, [active]);

  return (
    <div ref={rootRef} className="sb-panel sb-tools pointer-events-auto shrink-0 overflow-hidden">
      <div
        className={`flex items-center gap-2 px-3 py-2 bg-[rgba(var(--sb-accent-rgb),0.035)] ${active ? 'border-b border-[var(--border-primary)]' : ''}`}
      >
        <Wrench size={15} className="text-cyan-400 shrink-0" />
        <span className="sb-title text-cyan-300">TOOLS</span>
        <div role="tablist" aria-label="Operator tools" className="ml-auto flex items-center gap-1">
          {TOOLS.map(({ id, name, Icon, tint }) => {
            const on = active === id;
            return (
              <button
                key={id}
                type="button"
                role="tab"
                aria-selected={on}
                aria-label={name}
                title={name}
                onClick={() => setActive((prev) => (prev === id ? null : id))}
                className={`grid place-items-center w-8 h-8 rounded-lg border transition-colors ${
                  on
                    ? 'border-[rgba(var(--sb-accent-rgb),0.55)] bg-[rgba(var(--sb-accent-rgb),0.14)]'
                    : 'border-transparent hover:border-[var(--border-primary)] hover:bg-white/5'
                }`}
              >
                <Icon size={15} className={`${tint} ${on ? '' : 'opacity-80'}`} />
              </button>
            );
          })}
        </div>
      </div>

      {current && (
        <div className="flex items-center justify-between px-3 pt-2.5">
          <span className="text-[11px] font-mono font-bold tracking-[0.16em] text-[var(--text-secondary)]">
            {current.name}
          </span>
          <button
            type="button"
            onClick={() => setActive(null)}
            aria-label={`Close ${current.name.toLowerCase()}`}
            title="Close"
            className="text-cyan-400 hover:text-cyan-200 p-0.5 rounded-md transition-colors"
          >
            <Minus size={15} />
          </button>
        </div>
      )}

      {TOOLS.map(({ id }) => (
        <div key={id} role="tabpanel" hidden={active !== id}>
          {panels[id]}
        </div>
      ))}
    </div>
  );
}
