'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import {
  Building2,
  ChevronDown,
  ChevronUp,
  Fence,
  Hammer,
  Home,
  Loader2,
  MapPin,
  RefreshCw,
  ShieldCheck,
  Waves,
} from 'lucide-react';
import { API_BASE } from '@/lib/api';

type PermitSource = {
  id: string;
  name: string;
  category: string;
  access_method: string;
  enabled: boolean;
  jurisdiction_id: string;
  jurisdiction_name: string;
  lead_categories: string[];
  attribution: string;
  terms_reviewed: boolean;
  commercial_use: string;
};

type PermitRecord = {
  id: string;
  source_id: string;
  source_name: string;
  jurisdiction_id: string;
  jurisdiction_name: string;
  label: string;
  permit_number: string;
  permit_type: string;
  status: string;
  address: string;
  description: string;
  contractor: string;
  parcel_id: string;
  issued_at: string;
  accepted_at: string;
  finaled_at: string;
  valuation: number | null;
  lat: number | null;
  lng: number | null;
  lead_category: string;
  score: number;
  lead_categories: string[];
  attribution: string;
};

type PreviewPayload = {
  summary: {
    selected_sources: number;
    queried_sources: number;
    returned: number;
    errors: number;
    elapsed_ms: number;
  };
  sources: Array<{
    id: string;
    name: string;
    jurisdiction_id: string;
    count: number;
    access_method: string;
    attribution: string;
  }>;
  records: PermitRecord[];
  errors: Array<{ source_id: string; detail: string }>;
};

const DEFAULT_SOURCE = 'cb-residential-swimming-pool-permits';

function categoryIcon(category: string) {
  switch (category) {
    case 'pool':
      return Waves;
    case 'fence':
      return Fence;
    case 'new_home':
      return Home;
    case 'hardscape':
    case 'sitework':
    case 'remodel_addition':
      return Hammer;
    default:
      return Building2;
  }
}

function compactCategory(value: string) {
  return value.replace(/_/g, ' ').toUpperCase();
}

function formatDate(value: string) {
  if (!value) return '';
  const asNumber = Number(value);
  const date = Number.isFinite(asNumber) && asNumber > 100000000000
    ? new Date(asNumber)
    : new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' });
}

function scoreClass(score: number) {
  if (score >= 90) return 'border-emerald-300/60 bg-emerald-400/10 text-emerald-100';
  if (score >= 80) return 'border-amber-300/55 bg-amber-400/10 text-amber-100';
  return 'border-cyan-500/35 bg-cyan-950/20 text-cyan-100';
}

export default function LocalPermitsPanel({ onFlyTo }: { onFlyTo?: (lat: number, lng: number) => void }) {
  const [isMinimized, setIsMinimized] = useState(false);
  const [sources, setSources] = useState<PermitSource[]>([]);
  const [sourceId, setSourceId] = useState(DEFAULT_SOURCE);
  const [loadingSources, setLoadingSources] = useState(false);
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [error, setError] = useState('');
  const [data, setData] = useState<PreviewPayload | null>(null);

  const selectedSource = useMemo(
    () => sources.find((source) => source.id === sourceId),
    [sourceId, sources],
  );

  const leadCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const record of data?.records || []) {
      counts.set(record.lead_category, (counts.get(record.lead_category) || 0) + 1);
    }
    return [...counts.entries()].slice(0, 4);
  }, [data?.records]);

  const loadSources = useCallback(async () => {
    setLoadingSources(true);
    setError('');
    try {
      const response = await fetch(`${API_BASE}/api/local-permits/sources?enabled_only=true`, { cache: 'no-store' });
      if (!response.ok) {
        const payload = (await response.json().catch(() => ({}))) as { detail?: string };
        throw new Error(payload.detail || `Permit source load failed (${response.status})`);
      }
      const payload = (await response.json()) as { sources?: PermitSource[] };
      const nextSources = (payload.sources || []).filter((source) => source.category === 'permits' || source.category === 'permits_delta');
      setSources(nextSources);
      if (nextSources.length && !nextSources.some((source) => source.id === sourceId)) {
        setSourceId(nextSources[0].id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Permit source load failed');
    } finally {
      setLoadingSources(false);
    }
  }, [sourceId]);

  const loadPreview = useCallback(async () => {
    if (!sourceId) return;
    setLoadingPreview(true);
    setError('');
    try {
      const params = new URLSearchParams({ source_id: sourceId, limit: '18' });
      const response = await fetch(`${API_BASE}/api/local-permits/preview?${params}`, { cache: 'no-store' });
      if (!response.ok) {
        const payload = (await response.json().catch(() => ({}))) as { detail?: string };
        throw new Error(payload.detail || `Permit preview failed (${response.status})`);
      }
      setData((await response.json()) as PreviewPayload);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Permit preview failed');
    } finally {
      setLoadingPreview(false);
    }
  }, [sourceId]);

  useEffect(() => {
    if (!isMinimized) void loadSources();
  }, [isMinimized, loadSources]);

  useEffect(() => {
    if (!isMinimized && sourceId) void loadPreview();
  }, [isMinimized, loadPreview, sourceId]);

  return (
    <motion.section
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex-shrink-0 overflow-hidden border border-cyan-900/35 bg-[#040809]/95 font-mono text-cyan-100 shadow-[0_0_24px_rgba(34,211,238,0.10)]"
    >
      <button
        type="button"
        onClick={() => setIsMinimized((prev) => !prev)}
        className="flex w-full items-center justify-between border-b border-cyan-900/35 px-3 py-2.5 text-left transition-colors hover:bg-cyan-950/20"
      >
        <span className="flex min-w-0 items-center gap-2">
          <Building2 size={15} className="flex-shrink-0 text-cyan-300" />
          <span className="text-[12px] font-bold tracking-[0.22em] text-cyan-300">LOCAL PERMITS</span>
        </span>
        <span className="flex items-center gap-2 text-[9px] tracking-[0.18em] text-cyan-700">
          {data ? `${data.summary.returned} LEADS` : 'LIVE'}
          {isMinimized ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
        </span>
      </button>

      <AnimatePresence initial={false}>
        {!isMinimized && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden"
          >
            <div className="p-3">
              <div className="grid grid-cols-[1fr_auto] gap-2">
                <label className="flex flex-col gap-1 text-[8px] tracking-[0.18em] text-cyan-700">
                  SOURCE
                  <select
                    value={sourceId}
                    onChange={(event) => setSourceId(event.target.value)}
                    className="h-8 min-w-0 border border-cyan-900/50 bg-black/45 px-2 text-[11px] tracking-normal text-cyan-100 outline-none focus:border-cyan-400/60"
                    disabled={loadingSources || sources.length === 0}
                  >
                    {sources.length === 0 ? (
                      <option value={sourceId}>Loading sources</option>
                    ) : (
                      sources.map((source) => (
                        <option key={source.id} value={source.id}>
                          {source.name}
                        </option>
                      ))
                    )}
                  </select>
                </label>
                <button
                  type="button"
                  onClick={() => void loadPreview()}
                  className="mt-4 flex h-8 w-8 items-center justify-center border border-cyan-800/60 bg-cyan-950/20 text-cyan-300 transition-colors hover:border-cyan-300/70 hover:bg-cyan-900/30 disabled:opacity-40"
                  title="Refresh permit leads"
                  disabled={loadingPreview || !sourceId}
                >
                  {loadingPreview ? <Loader2 size={15} className="animate-spin" /> : <RefreshCw size={15} />}
                </button>
              </div>

              <div className="mt-2 grid grid-cols-4 border border-cyan-900/30 bg-black/30 text-center">
                <div className="border-r border-cyan-900/30 px-2 py-2">
                  <div className="text-[15px] font-bold text-cyan-100">{data?.summary.returned || 0}</div>
                  <div className="text-[8px] tracking-[0.16em] text-cyan-700">LEADS</div>
                </div>
                <div className="border-r border-cyan-900/30 px-2 py-2">
                  <div className="text-[15px] font-bold text-cyan-100">{data?.summary.queried_sources || 0}</div>
                  <div className="text-[8px] tracking-[0.16em] text-cyan-700">FEEDS</div>
                </div>
                <div className="border-r border-cyan-900/30 px-2 py-2">
                  <div className="text-[15px] font-bold text-amber-100">{data?.summary.errors || 0}</div>
                  <div className="text-[8px] tracking-[0.16em] text-cyan-700">ERR</div>
                </div>
                <div className="px-2 py-2">
                  <div className="text-[15px] font-bold text-cyan-100">{data?.summary.elapsed_ms || 0}</div>
                  <div className="text-[8px] tracking-[0.16em] text-cyan-700">MS</div>
                </div>
              </div>

              {selectedSource && (
                <div className="mt-2 grid grid-cols-[1fr_auto] gap-2">
                  <div className="min-w-0 border border-cyan-900/30 bg-cyan-950/10 px-2 py-1.5">
                    <div className="truncate text-[9px] tracking-[0.14em] text-cyan-500">
                      {selectedSource.jurisdiction_name.toUpperCase()}
                    </div>
                    <div className="mt-0.5 truncate text-[8px] tracking-[0.12em] text-cyan-800">
                      {selectedSource.attribution}
                    </div>
                  </div>
                  <div className="flex items-center gap-1.5 border border-cyan-900/30 bg-black/25 px-2 text-[8px] tracking-[0.12em] text-cyan-600">
                    <ShieldCheck size={12} />
                    {selectedSource.commercial_use.toUpperCase() || 'CHECK'}
                  </div>
                </div>
              )}

              {leadCounts.length > 0 && (
                <div className="mt-2 grid grid-cols-4 gap-1">
                  {leadCounts.map(([category, count]) => (
                    <div key={category} className="border border-cyan-900/30 bg-black/25 px-2 py-1.5">
                      <div className="truncate text-[8px] tracking-[0.12em] text-cyan-600">{compactCategory(category)}</div>
                      <div className="mt-0.5 text-[13px] font-bold text-cyan-200">{count}</div>
                    </div>
                  ))}
                </div>
              )}

              {error && (
                <div className="mt-3 border border-red-500/30 bg-red-950/20 px-2 py-2 text-[10px] leading-4 text-red-200">
                  {error}
                </div>
              )}

              <div className="mt-3 flex max-h-[390px] flex-col gap-2 overflow-y-auto pr-1 styled-scrollbar">
                {!data && (
                  <div className="border border-cyan-900/30 bg-black/20 px-2 py-3 text-[10px] text-cyan-700">
                    {loadingPreview ? 'Loading local permit leads...' : 'No permit preview loaded.'}
                  </div>
                )}

                {data?.records.length === 0 && (
                  <div className="border border-cyan-900/30 bg-black/20 px-2 py-3 text-[10px] text-cyan-700">
                    No records returned from this source.
                  </div>
                )}

                {data?.records.map((record) => {
                  const Icon = categoryIcon(record.lead_category);
                  const hasPoint = typeof record.lat === 'number' && typeof record.lng === 'number';
                  const dateLabel = formatDate(record.issued_at || record.accepted_at || record.finaled_at);
                  return (
                    <button
                      type="button"
                      key={record.id}
                      onClick={() => {
                        if (hasPoint) onFlyTo?.(record.lat as number, record.lng as number);
                      }}
                      className="group border border-cyan-900/30 bg-black/25 p-2 text-left transition-colors hover:border-cyan-400/50 hover:bg-cyan-950/20"
                    >
                      <div className="flex items-start gap-2">
                        <div className={`mt-0.5 flex h-8 w-8 flex-shrink-0 items-center justify-center border ${scoreClass(record.score)}`}>
                          <Icon size={15} />
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="flex items-start justify-between gap-2">
                            <div className="min-w-0">
                              <div className="truncate text-[11px] font-bold tracking-[0.08em] text-cyan-100">
                                {record.address || record.permit_number || record.label}
                              </div>
                              <div className="mt-0.5 truncate text-[9px] tracking-[0.12em] text-cyan-600">
                                {record.permit_number || record.status || record.jurisdiction_name}
                              </div>
                            </div>
                            <div className="flex-shrink-0 text-right">
                              <div className="text-[12px] font-bold text-amber-200">{record.score}</div>
                              <div className="text-[8px] tracking-[0.12em] text-cyan-800">SCORE</div>
                            </div>
                          </div>
                          <div className="mt-1 line-clamp-2 text-[10px] leading-4 text-cyan-500">
                            {record.description || record.permit_type || compactCategory(record.lead_category)}
                          </div>
                          <div className="mt-1 flex items-center justify-between gap-2 text-[8px] tracking-[0.14em] text-cyan-800">
                            <span className="truncate">{compactCategory(record.lead_category)} / {(record.status || 'UNKNOWN').toUpperCase()}</span>
                            <span className="flex flex-shrink-0 items-center gap-1">
                              {hasPoint && <MapPin size={10} />}
                              {dateLabel || record.jurisdiction_name}
                            </span>
                          </div>
                        </div>
                      </div>
                    </button>
                  );
                })}
              </div>

              {data?.errors.length ? (
                <div className="mt-3 border border-amber-500/30 bg-amber-950/15 px-2 py-2 text-[9px] leading-4 text-amber-200">
                  {data.errors.slice(0, 2).map((item) => `${item.source_id}: ${item.detail}`).join(' / ')}
                </div>
              ) : null}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.section>
  );
}
