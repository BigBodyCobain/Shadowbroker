'use client';

import React, { useEffect, useMemo, useState } from 'react';
import { Activity, AlertTriangle, BarChart3, Clock, DatabaseZap, ShieldCheck, Signal } from 'lucide-react';
import BusinessIntelGraph, { IntelGraphLink, IntelGraphNode } from '@/components/BusinessIntelGraph';
import { API_BASE } from '@/lib/api';

interface IntelSignal {
  id: string;
  label: string;
  detail?: string;
  category?: string;
  source?: string;
  score?: number;
  grade?: string;
  action?: string;
}

interface DashboardPayload {
  summary?: {
    total?: number;
    opportunities?: number;
    risks?: number;
    average_confidence?: number;
    top_grade?: string;
  };
  action_queue?: IntelSignal[];
  watchlist?: IntelSignal[];
  heat?: Array<{ category: string; count: number; score: number; risk: number; opportunity: number }>;
  source_matrix?: Array<{ source: string; category: string; count: number; max_score: number; confidence: number }>;
  stale_sources?: string[];
  live_event_count?: number;
  stored_signal_count?: number;
  graph?: { nodes: IntelGraphNode[]; links: IntelGraphLink[] };
}

export default function BusinessIntelTvPage() {
  const [payload, setPayload] = useState<DashboardPayload | null>(null);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/business-intel/dashboard?limit=40`, { cache: 'no-store' });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (!alive) return;
        setPayload(data);
        setUpdatedAt(new Date());
        setError('');
      } catch (err) {
        if (alive) setError(err instanceof Error ? err.message : 'dashboard unavailable');
      }
    };
    void load();
    const id = window.setInterval(load, 30_000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, []);

  const topActions = payload?.action_queue?.slice(0, 8) || [];
  const watchlist = payload?.watchlist?.slice(0, 6) || [];
  const heat = payload?.heat?.slice(0, 8) || [];
  const sources = payload?.source_matrix?.slice(0, 7) || [];
  const summary = payload?.summary || {};
  const graph = payload?.graph || { nodes: [], links: [] };
  const timeLabel = useMemo(() => updatedAt?.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) || '--:--', [updatedAt]);

  return (
    <main className="min-h-screen bg-[#05070b] text-cyan-100 font-mono overflow-hidden">
      <div className="flex h-screen flex-col p-5">
        <header className="mb-4 flex items-center justify-between border-b border-cyan-900/45 pb-3">
          <div>
            <div className="flex items-center gap-3">
              <DatabaseZap size={28} className="text-cyan-300" />
              <h1 className="text-[24px] font-bold tracking-[0.38em] text-cyan-100">SHADOWBROKER BUSINESS INTEL</h1>
            </div>
            <div className="mt-1 text-[11px] tracking-[0.24em] text-cyan-700">
              LOCAL / TAILNET / READ ONLY
            </div>
          </div>
          <div className="flex items-center gap-5">
            <StatusPill icon={ShieldCheck} label="PRIVATE" value="LOCAL" tone="green" />
            <StatusPill icon={Clock} label="UPDATED" value={timeLabel} tone="cyan" />
            <StatusPill icon={Signal} label="LIVE EVENTS" value={payload?.live_event_count || 0} tone="amber" />
          </div>
        </header>

        {error && (
          <div className="mb-3 border border-red-500/45 bg-red-950/35 px-4 py-2 text-[12px] tracking-wider text-red-300">
            BUSINESS INTEL API UNAVAILABLE / {error}
          </div>
        )}

        <section className="grid min-h-0 flex-1 grid-cols-[1.1fr_1.6fr_1fr] gap-4">
          <div className="flex min-h-0 flex-col gap-4">
            <div className="grid grid-cols-2 gap-3">
              <Kpi label="SIGNALS" value={summary.total || 0} />
              <Kpi label="OPPORTUNITIES" value={summary.opportunities || 0} />
              <Kpi label="RISKS" value={summary.risks || 0} />
              <Kpi label="CONFIDENCE" value={`${Math.round((summary.average_confidence || 0) * 100)}%`} />
            </div>

            <Panel title="ACTION QUEUE" icon={Activity} className="min-h-0 flex-1">
              <div className="space-y-2 overflow-y-auto pr-1 styled-scrollbar">
                {topActions.map((item) => (
                  <SignalRow key={item.id} item={item} />
                ))}
                {topActions.length === 0 && <Empty label="Waiting for scored opportunities" />}
              </div>
            </Panel>
          </div>

          <Panel title="OPPORTUNITY GRAPH" icon={BarChart3} className="min-h-0">
            <BusinessIntelGraph nodes={graph.nodes} links={graph.links} height={620} />
          </Panel>

          <div className="flex min-h-0 flex-col gap-4">
            <Panel title="WATCHLIST" icon={AlertTriangle} className="min-h-0 flex-1">
              <div className="space-y-2 overflow-y-auto pr-1 styled-scrollbar">
                {watchlist.map((item) => (
                  <SignalRow key={item.id} item={item} compact />
                ))}
                {watchlist.length === 0 && <Empty label="No strong watch items" />}
              </div>
            </Panel>

            <Panel title="HEAT" icon={Activity}>
              <div className="space-y-2">
                {heat.map((item) => (
                  <div key={item.category}>
                    <div className="mb-1 flex justify-between text-[10px] uppercase tracking-wider">
                      <span className="text-cyan-500">{item.category}</span>
                      <span className="text-amber-300">{Math.round(item.score)}</span>
                    </div>
                    <div className="h-2 bg-cyan-950/70">
                      <div className="h-2 bg-cyan-400/70" style={{ width: `${Math.min(100, Math.max(4, item.score))}%` }} />
                    </div>
                  </div>
                ))}
                {heat.length === 0 && <Empty label="No heat buckets" />}
              </div>
            </Panel>

            <Panel title="SOURCES" icon={Signal}>
              <div className="space-y-1.5">
                {sources.map((item) => (
                  <div key={`${item.source}:${item.category}`} className="flex items-center justify-between border border-cyan-900/30 bg-black/35 px-2 py-1.5">
                    <span className="truncate text-[10px] text-cyan-500">{item.source}</span>
                    <span className="text-[10px] text-cyan-200">{item.count}</span>
                  </div>
                ))}
              </div>
            </Panel>
          </div>
        </section>
      </div>
    </main>
  );
}

function Kpi({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="border border-cyan-800/35 bg-cyan-950/10 px-4 py-3">
      <div className="text-[10px] tracking-[0.24em] text-cyan-700">{label}</div>
      <div className="mt-1 text-[26px] font-bold tracking-wider text-cyan-200">{value}</div>
    </div>
  );
}

function Panel({ title, icon: Icon, children, className = '' }: { title: string; icon: typeof Activity; children: React.ReactNode; className?: string }) {
  return (
    <div className={`flex flex-col overflow-hidden border border-cyan-800/35 bg-black/55 ${className}`}>
      <div className="flex items-center gap-2 border-b border-cyan-900/40 px-3 py-2.5">
        <Icon size={15} className="text-cyan-400" />
        <span className="text-[12px] font-bold tracking-[0.24em] text-cyan-300">{title}</span>
      </div>
      <div className="min-h-0 flex-1 overflow-hidden p-3">{children}</div>
    </div>
  );
}

function SignalRow({ item, compact = false }: { item: IntelSignal; compact?: boolean }) {
  return (
    <div className="border border-cyan-900/35 bg-cyan-950/10 px-3 py-2">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className={`${compact ? 'text-[11px]' : 'text-[12px]'} line-clamp-2 font-bold leading-snug text-cyan-100`}>
            {item.label}
          </div>
          {!compact && <div className="mt-1 line-clamp-2 text-[10px] leading-snug text-cyan-700">{item.action || item.detail}</div>}
        </div>
        <div className="shrink-0 text-right">
          <div className="text-[14px] font-bold text-amber-300">{Math.round(Number(item.score || 0))}</div>
          <div className="text-[9px] uppercase tracking-wider text-cyan-600">{item.grade || item.category}</div>
        </div>
      </div>
    </div>
  );
}

function StatusPill({ icon: Icon, label, value, tone }: { icon: typeof ShieldCheck; label: string; value: string | number; tone: 'green' | 'cyan' | 'amber' }) {
  const color = tone === 'green' ? 'text-emerald-300 border-emerald-700/40 bg-emerald-950/20' : tone === 'amber' ? 'text-amber-300 border-amber-700/40 bg-amber-950/20' : 'text-cyan-300 border-cyan-700/40 bg-cyan-950/20';
  return (
    <div className={`flex items-center gap-2 border px-3 py-2 ${color}`}>
      <Icon size={14} />
      <div>
        <div className="text-[9px] tracking-[0.22em] opacity-70">{label}</div>
        <div className="text-[12px] font-bold tracking-wider">{value}</div>
      </div>
    </div>
  );
}

function Empty({ label }: { label: string }) {
  return <div className="border border-cyan-900/30 bg-black/30 px-3 py-4 text-center text-[11px] tracking-wider text-cyan-700">{label}</div>;
}
