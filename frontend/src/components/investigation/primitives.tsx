'use client';

// Shared presentational primitives for the Investigation Workspace.
// The most important is ClassificationBadge: it makes the fact/inference
// boundary visually unmistakable, per the product rule that a hypothesis must
// never look like a fact.

import React from 'react';
import type { Classification, Confidence } from '@/types/investigation';
import { CLASSIFICATION_META } from '@/types/investigation';

const CLASS_STYLES: Record<Classification, string> = {
  raw_observation: 'border-cyan-500/50 bg-cyan-950/30 text-cyan-200',
  derived_event: 'border-teal-500/50 bg-teal-950/30 text-teal-200',
  analysis: 'border-amber-500/50 bg-amber-950/30 text-amber-200',
  // Hypotheses get a dashed border — deliberately distinct from any solid fact.
  hypothesis: 'border-dashed border-violet-400/70 bg-violet-950/30 text-violet-200',
};

export function ClassificationBadge({ value }: { value: Classification }) {
  const meta = CLASSIFICATION_META[value] || CLASSIFICATION_META.analysis;
  return (
    <span
      className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${CLASS_STYLES[value]}`}
      title={`${meta.label} — ${meta.kind === 'fact' ? 'factual' : 'interpretation, not confirmed fact'}`}
    >
      {meta.kind === 'inference' && <span aria-hidden>◇</span>}
      {meta.short}
    </span>
  );
}

const SEVERITY_STYLES: Record<string, string> = {
  info: 'border-slate-500/40 bg-slate-800/40 text-slate-300',
  low: 'border-sky-500/40 bg-sky-950/30 text-sky-300',
  medium: 'border-amber-500/40 bg-amber-950/30 text-amber-300',
  high: 'border-orange-500/50 bg-orange-950/30 text-orange-300',
  critical: 'border-red-500/60 bg-red-950/40 text-red-300',
};

export function SeverityPill({ value }: { value: string }) {
  const cls = SEVERITY_STYLES[value] || SEVERITY_STYLES.info;
  return (
    <span className={`rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${cls}`}>
      {value}
    </span>
  );
}

const STATUS_STYLES: Record<string, string> = {
  open: 'text-cyan-300 border-cyan-500/40',
  active: 'text-emerald-300 border-emerald-500/40',
  on_hold: 'text-amber-300 border-amber-500/40',
  closed: 'text-slate-400 border-slate-500/40',
  archived: 'text-slate-500 border-slate-600/40',
};

export function StatusPill({ value }: { value: string }) {
  const cls = STATUS_STYLES[value] || STATUS_STYLES.open;
  return (
    <span className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${cls}`}>
      {value.replace('_', ' ')}
    </span>
  );
}

function bandColor(label: string): string {
  switch (label) {
    case 'very high':
      return 'bg-emerald-500';
    case 'high':
      return 'bg-teal-500';
    case 'moderate':
      return 'bg-amber-500';
    case 'low':
      return 'bg-orange-500';
    case 'very low':
      return 'bg-red-500';
    default:
      return 'bg-slate-500';
  }
}

// Explainable confidence: numeric bar OR a clearly-labelled qualitative chip,
// with expandable supporting / contradicting factors. Never invents precision.
export function ConfidenceMeter({ confidence, defaultOpen = false }: { confidence: Confidence; defaultOpen?: boolean }) {
  const [open, setOpen] = React.useState(defaultOpen);
  const hasFactors =
    (confidence.supporting?.length || 0) + (confidence.contradicting?.length || 0) > 0;

  return (
    <div className="rounded border border-cyan-500/20 bg-black/40 p-2">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[10px] uppercase tracking-wider text-cyan-500">Confidence</span>
        {confidence.qualitative || confidence.percent == null ? (
          <span className="rounded border border-slate-500/40 bg-slate-800/40 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-slate-300">
            Qualitative: {confidence.label}
          </span>
        ) : (
          <span className="font-mono text-sm font-bold text-cyan-200">{confidence.percent}%</span>
        )}
      </div>
      {!confidence.qualitative && confidence.percent != null && (
        <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-slate-800">
          <div
            className={`h-full rounded-full ${bandColor(confidence.label)}`}
            style={{ width: `${confidence.percent}%` }}
          />
        </div>
      )}
      {confidence.rationale && (
        <p className="mt-1.5 text-[11px] leading-snug text-slate-400">{confidence.rationale}</p>
      )}
      {hasFactors && (
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="mt-1 text-[10px] uppercase tracking-wider text-cyan-500 hover:text-cyan-300"
        >
          {open ? '▾ Hide evidence' : '▸ Show supporting / contradicting'}
        </button>
      )}
      {open && hasFactors && (
        <div className="mt-1.5 space-y-1">
          {confidence.supporting?.map((f, i) => (
            <div key={`s${i}`} className="flex items-start gap-1 text-[11px] text-emerald-300">
              <span aria-hidden>+</span>
              <span>
                {f.label}
                {f.note ? <span className="text-slate-500"> · {f.note}</span> : null}
              </span>
            </div>
          ))}
          {confidence.contradicting?.map((f, i) => (
            <div key={`c${i}`} className="flex items-start gap-1 text-[11px] text-red-300">
              <span aria-hidden>−</span>
              <span>
                {f.label}
                {f.note ? <span className="text-slate-500"> · {f.note}</span> : null}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function Section({
  title,
  action,
  children,
}: {
  title: string;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="mb-4">
      <div className="mb-2 flex items-center justify-between border-b border-cyan-500/20 pb-1">
        <h3 className="text-xs font-semibold uppercase tracking-widest text-cyan-400">{title}</h3>
        {action}
      </div>
      {children}
    </section>
  );
}

export function EmptyState({ label }: { label: string }) {
  return (
    <div className="rounded border border-dashed border-slate-700 bg-black/30 p-4 text-center text-xs text-slate-500">
      {label}
    </div>
  );
}

export function LoadingState({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 p-6 text-xs text-cyan-400">
      <span className="h-2 w-2 animate-pulse rounded-full bg-cyan-400" aria-hidden />
      {label}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div
      role="alert"
      className="rounded border border-red-500/40 bg-red-950/30 p-3 text-xs text-red-300"
    >
      <p>{message}</p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-2 rounded border border-red-500/50 px-2 py-1 text-[11px] uppercase tracking-wide hover:bg-red-900/40"
        >
          Retry
        </button>
      )}
    </div>
  );
}

export function fmtTime(ts: string | null | undefined): string {
  if (!ts) return '—';
  try {
    const d = new Date(ts);
    if (isNaN(d.getTime())) return ts;
    return d.toISOString().replace('T', ' ').replace('Z', 'Z');
  } catch {
    return ts;
  }
}
