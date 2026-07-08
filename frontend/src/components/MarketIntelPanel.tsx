'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import {
  BarChart3,
  Briefcase,
  ChevronDown,
  ChevronUp,
  Crosshair,
  Database,
  Loader2,
  LockKeyhole,
  MapPin,
  RefreshCw,
  ShieldAlert,
  Target,
  TrendingUp,
} from 'lucide-react';
import { API_BASE } from '@/lib/api';

type LocalPoint = { lat: number; lng: number };

type MarketSignal = {
  id: string;
  kind: 'risk' | 'opportunity' | string;
  category: string;
  market: string;
  objective: string;
  source: string;
  label: string;
  detail: string;
  lat?: number | null;
  lng?: number | null;
  area?: string;
  metrics?: string[];
  evidence_count: number;
  confidence: number;
  impact_rank: number;
  urgency_rank: number;
  score: number;
  grade: 'alpha' | 'strong' | 'watch' | 'low' | string;
  action: string;
};

type HeatRow = {
  category: string;
  count: number;
  score: number;
  risk: number;
  opportunity: number;
};

type SourceRow = {
  source: string;
  category: string;
  count: number;
  max_score: number;
  confidence: number;
};

type MarketIntelResponse = {
  query: {
    market: string;
    objective: string;
    lat?: number | null;
    lng?: number | null;
    radius_km: number;
    generated_at: number;
    fused_local: boolean;
  };
  summary: {
    total: number;
    returned: number;
    opportunities: number;
    risks: number;
    average_confidence: number;
    top_grade: string;
    primary_categories: Record<string, number>;
    primary_sources: Record<string, number>;
  };
  action_queue: MarketSignal[];
  heat: HeatRow[];
  source_matrix: SourceRow[];
  privacy: {
    stored: boolean;
    redacted: number;
    redactions: Record<string, number>;
  };
};

const POINT_STORAGE_KEY = 'sb_local_intel_point';
const MARKET_OPTIONS = [
  { id: 'local_services', label: 'Local services' },
  { id: 'retail_inventory', label: 'Retail / inventory' },
  { id: 'logistics', label: 'Logistics' },
  { id: 'real_estate', label: 'Real estate' },
  { id: 'labor', label: 'Labor' },
  { id: 'custom', label: 'Custom' },
];
const OBJECTIVE_OPTIONS = [
  { id: 'demand', label: 'Demand' },
  { id: 'pricing', label: 'Pricing' },
  { id: 'operations', label: 'Operations' },
  { id: 'expansion', label: 'Expansion' },
];
const RADIUS_OPTIONS = [25, 75, 150, 300];

function readStoredPoint(): LocalPoint | null {
  try {
    const raw = localStorage.getItem(POINT_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<LocalPoint>;
    if (typeof parsed.lat !== 'number' || typeof parsed.lng !== 'number') return null;
    if (parsed.lat < -90 || parsed.lat > 90 || parsed.lng < -180 || parsed.lng > 180) return null;
    return { lat: parsed.lat, lng: parsed.lng };
  } catch {
    return null;
  }
}

function gradeClass(grade: string, kind: string) {
  if (kind === 'risk' && (grade === 'alpha' || grade === 'strong')) {
    return 'border-red-500/45 bg-red-950/20 text-red-200';
  }
  switch (grade) {
    case 'alpha':
      return 'border-emerald-400/50 bg-emerald-950/20 text-emerald-200';
    case 'strong':
      return 'border-amber-400/50 bg-amber-950/20 text-amber-200';
    case 'watch':
      return 'border-cyan-500/35 bg-cyan-950/20 text-cyan-200';
    default:
      return 'border-slate-600/40 bg-slate-950/25 text-slate-300';
  }
}

function categoryIcon(category: string) {
  switch (category) {
    case 'risk':
    case 'mobility':
      return ShieldAlert;
    case 'pricing':
      return BarChart3;
    case 'competitor':
      return Target;
    case 'supply':
      return Database;
    default:
      return TrendingUp;
  }
}

function formatPercent(value: number) {
  return `${Math.round((Number.isFinite(value) ? value : 0) * 100)}%`;
}

function formatTime(epochSeconds?: number) {
  if (!epochSeconds) return 'not scored';
  return new Date(epochSeconds * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

export default function MarketIntelPanel({ onFlyTo }: { onFlyTo?: (lat: number, lng: number) => void }) {
  const [isMinimized, setIsMinimized] = useState(false);
  const [market, setMarket] = useState('local_services');
  const [objective, setObjective] = useState('demand');
  const [sourceLabel, setSourceLabel] = useState('authorized_notes');
  const [brief, setBrief] = useState('');
  const [radiusKm, setRadiusKm] = useState(150);
  const [fuseLocal, setFuseLocal] = useState(true);
  const [point, setPoint] = useState<LocalPoint | null>(null);
  const [locating, setLocating] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [data, setData] = useState<MarketIntelResponse | null>(null);

  useEffect(() => {
    const stored = readStoredPoint();
    if (stored) setPoint(stored);
  }, []);

  const dominantHeat = useMemo(() => data?.heat.slice(0, 7) || [], [data]);
  const queue = data?.action_queue || [];

  const scanMarket = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const response = await fetch(`${API_BASE}/api/market-intel`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        cache: 'no-store',
        body: JSON.stringify({
          text: brief,
          market,
          objective,
          source_label: sourceLabel,
          lat: point?.lat,
          lng: point?.lng,
          radius_km: radiusKm,
          fuse_local: fuseLocal,
          limit: 36,
        }),
      });
      if (!response.ok) {
        const payload = (await response.json().catch(() => ({}))) as { detail?: string };
        throw new Error(payload.detail || `Market intel request failed (${response.status})`);
      }
      setData((await response.json()) as MarketIntelResponse);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Market intel request failed');
    } finally {
      setLoading(false);
    }
  }, [brief, fuseLocal, market, objective, point?.lat, point?.lng, radiusKm, sourceLabel]);

  const locateBrowser = useCallback(() => {
    if (!navigator.geolocation) {
      setError('Browser location is not available.');
      return;
    }
    setLocating(true);
    setError('');
    navigator.geolocation.getCurrentPosition(
      (position) => {
        setLocating(false);
        const next = { lat: position.coords.latitude, lng: position.coords.longitude };
        setPoint(next);
        localStorage.setItem(POINT_STORAGE_KEY, JSON.stringify(next));
      },
      (geoError) => {
        setLocating(false);
        setError(geoError.message || 'Location permission was not granted.');
      },
      { enableHighAccuracy: false, maximumAge: 300000, timeout: 10000 },
    );
  }, []);

  return (
    <motion.section
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex-shrink-0 overflow-hidden border border-emerald-900/35 bg-[#050806]/95 font-mono text-emerald-100 shadow-[0_0_24px_rgba(16,185,129,0.10)]"
    >
      <button
        type="button"
        onClick={() => setIsMinimized((prev) => !prev)}
        className="flex w-full items-center justify-between border-b border-emerald-900/35 px-3 py-2.5 text-left transition-colors hover:bg-emerald-950/20"
      >
        <span className="flex items-center gap-2">
          <Briefcase size={15} className="text-emerald-300" />
          <span className="text-[12px] font-bold tracking-[0.22em] text-emerald-300">MARKET INTEL</span>
        </span>
        <span className="flex items-center gap-2 text-[9px] tracking-[0.18em] text-emerald-700">
          {data ? formatTime(data.query.generated_at) : 'STANDBY'}
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
              <div className="mb-3 grid grid-cols-7 gap-1">
                {(dominantHeat.length ? dominantHeat : Array.from({ length: 7 }, (_, index) => ({ category: `idle-${index}`, score: 0, count: 0, risk: 0, opportunity: 0 }))).map((row, index) => {
                  const height = dominantHeat.length ? Math.max(20, Math.min(100, row.score)) : 20 + index * 4;
                  const tone = row.risk > row.opportunity ? 'bg-red-400/70' : row.category === 'pricing' ? 'bg-amber-300/70' : 'bg-emerald-300/70';
                  return (
                    <div key={`${row.category}-${index}`} className="flex h-12 items-end border border-emerald-900/25 bg-black/30 px-1">
                      <div className={`w-full ${tone}`} style={{ height: `${height}%` }} title={row.category} />
                    </div>
                  );
                })}
              </div>

              <div className="grid grid-cols-2 gap-2">
                <label className="flex flex-col gap-1 text-[8px] tracking-[0.18em] text-emerald-700">
                  MARKET
                  <select
                    value={market}
                    onChange={(event) => setMarket(event.target.value)}
                    className="h-8 border border-emerald-900/50 bg-black/45 px-2 text-[11px] tracking-normal text-emerald-100 outline-none focus:border-emerald-400/60"
                  >
                    {MARKET_OPTIONS.map((option) => (
                      <option key={option.id} value={option.id}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="flex flex-col gap-1 text-[8px] tracking-[0.18em] text-emerald-700">
                  OBJECTIVE
                  <select
                    value={objective}
                    onChange={(event) => setObjective(event.target.value)}
                    className="h-8 border border-emerald-900/50 bg-black/45 px-2 text-[11px] tracking-normal text-emerald-100 outline-none focus:border-emerald-400/60"
                  >
                    {OBJECTIVE_OPTIONS.map((option) => (
                      <option key={option.id} value={option.id}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
              </div>

              <div className="mt-2 grid grid-cols-[1fr_auto] gap-2">
                <label className="flex flex-col gap-1 text-[8px] tracking-[0.18em] text-emerald-700">
                  SOURCE
                  <input
                    value={sourceLabel}
                    onChange={(event) => setSourceLabel(event.target.value)}
                    className="h-8 border border-emerald-900/50 bg-black/45 px-2 text-[11px] tracking-normal text-emerald-100 outline-none focus:border-emerald-400/60"
                    maxLength={40}
                  />
                </label>
                <button
                  type="button"
                  onClick={locateBrowser}
                  className="mt-4 flex h-8 w-8 items-center justify-center border border-emerald-800/60 bg-emerald-950/20 text-emerald-300 transition-colors hover:border-emerald-300/70 hover:bg-emerald-900/30"
                  title="Use browser location"
                >
                  {locating ? <Loader2 size={15} className="animate-spin" /> : <Crosshair size={15} />}
                </button>
              </div>

              <textarea
                value={brief}
                onChange={(event) => setBrief(event.target.value)}
                className="mt-3 h-28 w-full resize-none border border-emerald-900/50 bg-black/45 p-2 text-[11px] leading-4 text-emerald-100 outline-none placeholder:text-emerald-900 focus:border-emerald-400/60"
                placeholder="Authorized notes, exports, CSV rows, or observed marketplace signals..."
                maxLength={24000}
              />

              <div className="mt-2 flex items-center justify-between gap-2">
                <div className="flex gap-1">
                  {RADIUS_OPTIONS.map((radius) => (
                    <button
                      key={radius}
                      type="button"
                      onClick={() => setRadiusKm(radius)}
                      className={`h-7 border px-2 text-[9px] tracking-[0.12em] transition-colors ${
                        radiusKm === radius
                          ? 'border-emerald-300/70 bg-emerald-400/10 text-emerald-200'
                          : 'border-emerald-900/50 bg-black/20 text-emerald-700 hover:text-emerald-300'
                      }`}
                    >
                      {radius}
                    </button>
                  ))}
                </div>
                <label className="flex h-7 items-center gap-1.5 border border-emerald-900/50 bg-black/20 px-2 text-[9px] tracking-[0.12em] text-emerald-600">
                  <input
                    type="checkbox"
                    checked={fuseLocal}
                    onChange={(event) => setFuseLocal(event.target.checked)}
                    className="h-3 w-3 accent-emerald-400"
                  />
                  LOCAL
                </label>
                <button
                  type="button"
                  onClick={() => void scanMarket()}
                  className="flex h-7 items-center gap-1.5 border border-emerald-700/60 bg-black/35 px-2 text-[9px] tracking-[0.14em] text-emerald-300 transition-colors hover:border-emerald-300/70"
                >
                  {loading ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
                  SCORE
                </button>
              </div>

              <div className="mt-3 grid grid-cols-[1fr_auto] gap-2">
                <div className="flex items-center gap-2 border border-emerald-900/30 bg-emerald-950/10 px-2 py-1.5 text-[9px] tracking-[0.12em] text-emerald-600">
                  <MapPin size={12} />
                  {point ? `${point.lat.toFixed(4)}, ${point.lng.toFixed(4)}` : 'NO GEO ANCHOR'}
                </div>
                <div className="flex items-center gap-2 border border-emerald-900/30 bg-black/25 px-2 py-1.5 text-[9px] tracking-[0.12em] text-emerald-600">
                  <LockKeyhole size={12} />
                  {data ? `${data.privacy.redacted} REDACTED` : 'MEMORY ONLY'}
                </div>
              </div>

              {error && (
                <div className="mt-3 border border-red-500/30 bg-red-950/20 px-2 py-2 text-[10px] leading-4 text-red-200">
                  {error}
                </div>
              )}

              {data && (
                <>
                  <div className="mt-3 grid grid-cols-4 border border-emerald-900/30 bg-black/30 text-center">
                    <div className="border-r border-emerald-900/30 px-2 py-2">
                      <div className="text-[15px] font-bold text-emerald-200">{data.summary.opportunities}</div>
                      <div className="text-[8px] tracking-[0.16em] text-emerald-700">OPPS</div>
                    </div>
                    <div className="border-r border-emerald-900/30 px-2 py-2">
                      <div className="text-[15px] font-bold text-red-200">{data.summary.risks}</div>
                      <div className="text-[8px] tracking-[0.16em] text-emerald-700">RISKS</div>
                    </div>
                    <div className="border-r border-emerald-900/30 px-2 py-2">
                      <div className="text-[15px] font-bold uppercase text-emerald-200">{data.summary.top_grade}</div>
                      <div className="text-[8px] tracking-[0.16em] text-emerald-700">PEAK</div>
                    </div>
                    <div className="px-2 py-2">
                      <div className="text-[15px] font-bold text-emerald-200">{formatPercent(data.summary.average_confidence)}</div>
                      <div className="text-[8px] tracking-[0.16em] text-emerald-700">CONF</div>
                    </div>
                  </div>

                  {data.source_matrix.length > 0 && (
                    <div className="mt-3 grid grid-cols-2 gap-1">
                      {data.source_matrix.slice(0, 4).map((row) => (
                        <div
                          key={`${row.source}-${row.category}`}
                          className="border border-emerald-900/30 bg-black/25 px-2 py-1.5"
                        >
                          <div className="truncate text-[9px] tracking-[0.12em] text-emerald-400">{row.source.toUpperCase()}</div>
                          <div className="mt-0.5 flex justify-between text-[8px] tracking-[0.12em] text-emerald-700">
                            <span>{row.category.toUpperCase()}</span>
                            <span>{row.count} / {formatPercent(row.confidence)}</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}

                  <div className="mt-3 flex max-h-[390px] flex-col gap-2 overflow-y-auto pr-1 styled-scrollbar">
                    {queue.length === 0 ? (
                      <div className="border border-emerald-900/30 bg-black/20 px-2 py-3 text-[10px] text-emerald-600">
                        No market signals scored in this pass.
                      </div>
                    ) : (
                      queue.slice(0, 14).map((item) => {
                        const Icon = categoryIcon(item.category);
                        const hasPoint = typeof item.lat === 'number' && typeof item.lng === 'number';
                        return (
                          <button
                            type="button"
                            key={item.id}
                            onClick={() => {
                              if (hasPoint) onFlyTo?.(item.lat as number, item.lng as number);
                            }}
                            className="group border border-emerald-900/30 bg-black/25 p-2 text-left transition-colors hover:border-emerald-400/50 hover:bg-emerald-950/20"
                          >
                            <div className="flex items-start gap-2">
                              <div className={`mt-0.5 flex h-7 w-7 flex-shrink-0 items-center justify-center border ${gradeClass(item.grade, item.kind)}`}>
                                <Icon size={14} />
                              </div>
                              <div className="min-w-0 flex-1">
                                <div className="flex items-center justify-between gap-2">
                                  <div className="truncate text-[11px] font-bold tracking-[0.08em] text-emerald-100">
                                    {item.label}
                                  </div>
                                  <div className="flex-shrink-0 text-[9px] uppercase text-emerald-500">
                                    {item.grade}
                                  </div>
                                </div>
                                <div className="mt-1 line-clamp-2 text-[10px] leading-4 text-emerald-600">
                                  {item.detail}
                                </div>
                                <div className="mt-1 border-l border-emerald-800/40 pl-2 text-[9px] leading-4 text-emerald-400">
                                  {item.action}
                                </div>
                                <div className="mt-1 flex items-center justify-between text-[8px] tracking-[0.14em] text-emerald-800">
                                  <span>{item.category.toUpperCase()} / {item.kind.toUpperCase()}</span>
                                  <span>{formatPercent(item.confidence)} / {item.source.toUpperCase()}</span>
                                </div>
                              </div>
                            </div>
                          </button>
                        );
                      })
                    )}
                  </div>
                </>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.section>
  );
}
