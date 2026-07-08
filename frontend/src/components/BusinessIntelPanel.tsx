'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { BarChart3, BrainCircuit, Loader2, Minus, Network, Plus, RefreshCw, ShieldCheck, Zap } from 'lucide-react';
import { API_BASE } from '@/lib/api';
import BusinessIntelGraph, { IntelGraphLink, IntelGraphNode } from '@/components/BusinessIntelGraph';

interface IntelSignal {
  id: string;
  label: string;
  detail: string;
  category: string;
  source: string;
  score: number;
  grade: string;
  confidence: number;
  action: string;
  lat?: number | null;
  lng?: number | null;
}

interface BusinessIntelPayload {
  summary?: {
    total?: number;
    returned?: number;
    opportunities?: number;
    risks?: number;
    average_confidence?: number;
    top_grade?: string;
    primary_categories?: Record<string, number>;
    primary_sources?: Record<string, number>;
  };
  action_queue?: IntelSignal[];
  watchlist?: IntelSignal[];
  heat?: Array<{ category: string; count: number; score: number; risk: number; opportunity: number }>;
  source_matrix?: Array<{ source: string; category: string; count: number; max_score: number; confidence: number }>;
  privacy?: { stored?: boolean; redacted?: number; redactions?: Record<string, number>; guidance?: string };
  graph?: { nodes: IntelGraphNode[]; links: IntelGraphLink[] };
  stored_signal_count?: number;
  live_event_count?: number;
}

interface Props {
  onFlyTo?: (lat: number, lng: number) => void;
}

const MARKETS = ['local_services', 'resale', 'real_estate', 'logistics', 'contracting'];
const OBJECTIVES = ['demand', 'pricing', 'operations', 'expansion'];

export default function BusinessIntelPanel({ onFlyTo }: Props) {
  const [isMinimized, setIsMinimized] = useState(true);
  const [graphOpen, setGraphOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [scoring, setScoring] = useState(false);
  const [payload, setPayload] = useState<BusinessIntelPayload | null>(null);
  const [notes, setNotes] = useState('');
  const [sourceLabel, setSourceLabel] = useState('authorized_notes');
  const [market, setMarket] = useState('local_services');
  const [objective, setObjective] = useState('demand');

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ market, objective, limit: '30' });
      const res = await fetch(`${API_BASE}/api/business-intel/dashboard?${params}`);
      if (res.ok) setPayload(await res.json());
    } finally {
      setLoading(false);
    }
  }, [market, objective]);

  useEffect(() => {
    if (!isMinimized) void refresh();
  }, [isMinimized, refresh]);

  const scoreNotes = useCallback(async () => {
    if (!notes.trim()) return;
    setScoring(true);
    try {
      const res = await fetch(`${API_BASE}/api/business-intel/score`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text: notes,
          source_label: sourceLabel,
          market,
          objective,
          persist: true,
          fuse_local: true,
          limit: 40,
        }),
      });
      if (res.ok) {
        setPayload(await res.json());
        setNotes('');
      }
    } finally {
      setScoring(false);
    }
  }, [market, notes, objective, sourceLabel]);

  const topSignals = payload?.action_queue?.slice(0, 5) || [];
  const heat = payload?.heat?.slice(0, 6) || [];
  const summary = payload?.summary;
  const graph = payload?.graph;
  const redactions = payload?.privacy?.redacted || 0;

  const categoryText = useMemo(() => {
    const categories = summary?.primary_categories || {};
    return Object.entries(categories)
      .slice(0, 3)
      .map(([key, value]) => `${key}:${value}`)
      .join(' / ');
  }, [summary]);

  return (
    <>
      <div className="flex-shrink-0 border border-emerald-700/35 bg-black/78 backdrop-blur-sm shadow-[0_0_18px_rgba(16,185,129,0.10)]">
        <div
          className="flex items-center justify-between border-b border-emerald-700/25 bg-emerald-950/15 px-3 py-2.5 cursor-pointer hover:bg-emerald-950/30 transition-colors"
          onClick={() => setIsMinimized((prev) => !prev)}
        >
          <div className="flex min-w-0 items-center gap-2">
            <BrainCircuit size={16} className="shrink-0 text-emerald-400" />
            <span className="truncate text-[12px] font-mono font-bold tracking-widest text-emerald-400">
              BUSINESS INTEL
            </span>
            {summary?.top_grade && summary.top_grade !== 'none' && (
              <span className="shrink-0 border border-amber-600/35 bg-amber-950/20 px-1.5 py-0.5 text-[9px] font-mono tracking-wider text-amber-300">
                {summary.top_grade.toUpperCase()}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={(event) => {
                event.stopPropagation();
                void refresh();
              }}
              className="text-emerald-600 hover:text-emerald-300"
              title="Refresh business intel"
            >
              <RefreshCw size={11} className={loading ? 'animate-spin' : ''} />
            </button>
            {isMinimized ? <Plus size={16} className="text-emerald-400" /> : <Minus size={16} className="text-emerald-400" />}
          </div>
        </div>

        {!isMinimized && (
          <div className="space-y-3 px-3 py-3">
            <div className="grid grid-cols-3 gap-1.5">
              <Metric label="TOTAL" value={summary?.total || 0} />
              <Metric label="OPPS" value={summary?.opportunities || 0} />
              <Metric label="RISK" value={summary?.risks || 0} />
            </div>

            <div className="grid grid-cols-2 gap-1.5">
              <select
                value={market}
                onChange={(event) => setMarket(event.target.value)}
                className="bg-black/60 border border-emerald-800/40 px-2 py-1.5 text-[10px] font-mono text-emerald-200 outline-none"
                title="Market"
              >
                {MARKETS.map((item) => <option key={item} value={item}>{item}</option>)}
              </select>
              <select
                value={objective}
                onChange={(event) => setObjective(event.target.value)}
                className="bg-black/60 border border-emerald-800/40 px-2 py-1.5 text-[10px] font-mono text-emerald-200 outline-none"
                title="Objective"
              >
                {OBJECTIVES.map((item) => <option key={item} value={item}>{item}</option>)}
              </select>
            </div>

            <div className="space-y-1.5">
              <input
                value={sourceLabel}
                onChange={(event) => setSourceLabel(event.target.value)}
                className="w-full bg-black/60 border border-emerald-800/40 px-2 py-1.5 text-[10px] font-mono text-emerald-200 outline-none placeholder:text-emerald-900"
                placeholder="source label"
              />
              <textarea
                value={notes}
                onChange={(event) => setNotes(event.target.value)}
                className="h-24 w-full resize-none bg-black/60 border border-emerald-800/40 px-2 py-2 text-[11px] font-mono leading-relaxed text-emerald-100 outline-none placeholder:text-emerald-900"
                placeholder="Paste authorized notes, CSV rows, observed marketplace signals..."
              />
              <div className="flex gap-1.5">
                <button
                  type="button"
                  onClick={scoreNotes}
                  disabled={scoring || !notes.trim()}
                  className="flex flex-1 items-center justify-center gap-1.5 border border-emerald-600/45 bg-emerald-600/20 px-2 py-1.5 text-[11px] font-mono font-bold tracking-wider text-emerald-300 hover:bg-emerald-600/35 disabled:opacity-40"
                >
                  {scoring ? <Loader2 size={12} className="animate-spin" /> : <Zap size={12} />}
                  SCORE
                </button>
                <button
                  type="button"
                  onClick={() => setGraphOpen(true)}
                  disabled={!graph?.nodes?.length}
                  className="flex items-center justify-center gap-1.5 border border-cyan-600/45 bg-cyan-600/15 px-3 py-1.5 text-[11px] font-mono font-bold tracking-wider text-cyan-300 hover:bg-cyan-600/25 disabled:opacity-40"
                >
                  <Network size={12} />
                  GRAPH
                </button>
              </div>
            </div>

            <div className="flex items-center justify-between border border-emerald-900/25 bg-emerald-950/10 px-2 py-1.5 text-[10px] font-mono">
              <span className="flex items-center gap-1.5 text-emerald-500">
                <ShieldCheck size={11} />
                MEMORY ONLY
              </span>
              <span className="text-amber-300">{redactions} REDACTED</span>
              <span className="text-emerald-700">{payload?.stored_signal_count || 0} STORED</span>
            </div>

            {categoryText && (
              <div className="truncate text-[10px] font-mono tracking-wider text-emerald-700">
                {categoryText}
              </div>
            )}

            {heat.length > 0 && (
              <div className="grid grid-cols-6 gap-1">
                {heat.map((item) => (
                  <div key={item.category} className="flex h-12 flex-col justify-end border border-emerald-900/30 bg-black/40 px-1 py-1" title={item.category}>
                    <div className="bg-emerald-400/70" style={{ height: `${Math.max(12, Math.min(100, item.score))}%` }} />
                  </div>
                ))}
              </div>
            )}

            <div className="space-y-1.5">
              {topSignals.map((item) => (
                <button
                  type="button"
                  key={item.id}
                  onClick={() => {
                    if (typeof item.lat === 'number' && typeof item.lng === 'number') onFlyTo?.(item.lat, item.lng);
                  }}
                  className="block w-full border border-emerald-900/35 bg-black/45 px-2 py-1.5 text-left hover:border-emerald-600/45 hover:bg-emerald-950/15"
                >
                  <div className="flex items-start justify-between gap-2">
                    <span className="line-clamp-2 text-[11px] font-mono font-bold leading-snug text-emerald-200">{item.label}</span>
                    <span className="shrink-0 text-[10px] font-mono text-amber-300">{Math.round(item.score)}</span>
                  </div>
                  <div className="mt-0.5 truncate text-[10px] font-mono text-emerald-700">{item.action}</div>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      {graphOpen && graph?.nodes?.length && (
        <div className="fixed inset-6 z-[9500] flex flex-col border border-cyan-700/40 bg-black/92 p-4 shadow-[0_0_40px_rgba(34,211,238,0.20)] backdrop-blur-md">
          <div className="mb-3 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <BarChart3 size={18} className="text-cyan-400" />
              <span className="text-[13px] font-mono font-bold tracking-widest text-cyan-300">BUSINESS INTEL GRAPH</span>
            </div>
            <button
              type="button"
              onClick={() => setGraphOpen(false)}
              className="text-cyan-600 hover:text-cyan-300"
            >
              CLOSE
            </button>
          </div>
          <div className="min-h-0 flex-1">
            <BusinessIntelGraph
              nodes={graph.nodes}
              links={graph.links}
              height={Math.max(420, window.innerHeight - 180)}
              onNodeSelect={(node) => {
                const lat = Number(node.properties?.lat);
                const lng = Number(node.properties?.lng);
                if (Number.isFinite(lat) && Number.isFinite(lng)) onFlyTo?.(lat, lng);
              }}
            />
          </div>
        </div>
      )}
    </>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="border border-emerald-900/30 bg-black/45 px-2 py-1.5">
      <div className="text-[9px] font-mono tracking-[0.2em] text-emerald-700">{label}</div>
      <div className="text-[15px] font-mono font-bold text-emerald-300">{value}</div>
    </div>
  );
}
