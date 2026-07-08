'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Activity,
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  Crosshair,
  Loader2,
  MapPin,
  Navigation,
  Plane,
  Radar,
  Radio,
  RefreshCw,
  Satellite,
  Server,
  Ship,
} from 'lucide-react';
import { API_BASE } from '@/lib/api';

type LocalPoint = { lat: number; lng: number };

type LocalIntelItem = {
  id: string;
  category: string;
  kind: string;
  source_key: string;
  label: string;
  detail: string;
  lat: number;
  lng: number;
  distance_km: number;
  severity: 'critical' | 'elevated' | 'watch' | 'normal' | string;
  severity_rank: number;
  score: number;
  timestamp?: string;
  url?: string;
};

type LocalIntelResponse = {
  query: {
    lat: number;
    lng: number;
    radius_km: number;
    generated_at: number;
  };
  summary: {
    total: number;
    returned: number;
    categories: Record<string, number>;
    highest_severity: string;
  };
  watch: LocalIntelItem[];
  items: LocalIntelItem[];
  freshness: Record<string, string>;
};

const STORAGE_KEY = 'sb_local_intel_point';
const RADIUS_OPTIONS = [25, 75, 150, 300];

const CATEGORY_LABELS: Record<string, string> = {
  air: 'AIR',
  maritime: 'SEA',
  hazard: 'WX/HAZ',
  infrastructure: 'INFRA',
  rf: 'RF',
  space: 'ORBIT',
  intel: 'INTEL',
  health: 'BIO',
  mobility: 'RAIL',
};

function categoryIcon(category: string) {
  switch (category) {
    case 'air':
      return Plane;
    case 'maritime':
      return Ship;
    case 'hazard':
      return AlertTriangle;
    case 'infrastructure':
      return Server;
    case 'rf':
      return Radio;
    case 'space':
      return Satellite;
    case 'mobility':
      return Navigation;
    default:
      return Activity;
  }
}

function severityClass(severity: string) {
  switch (severity) {
    case 'critical':
      return 'border-red-500/40 bg-red-950/20 text-red-300';
    case 'elevated':
      return 'border-amber-500/40 bg-amber-950/20 text-amber-300';
    case 'watch':
      return 'border-cyan-500/30 bg-cyan-950/20 text-cyan-300';
    default:
      return 'border-slate-500/30 bg-slate-950/20 text-slate-300';
  }
}

function formatTime(epochSeconds?: number) {
  if (!epochSeconds) return 'not scanned';
  return new Date(epochSeconds * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function formatCoord(value: number) {
  return value.toFixed(4);
}

function readStoredPoint(): LocalPoint | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<LocalPoint>;
    if (typeof parsed.lat !== 'number' || typeof parsed.lng !== 'number') return null;
    if (parsed.lat < -90 || parsed.lat > 90 || parsed.lng < -180 || parsed.lng > 180) return null;
    return { lat: parsed.lat, lng: parsed.lng };
  } catch {
    return null;
  }
}

export default function LocalIntelPanel({ onFlyTo }: { onFlyTo?: (lat: number, lng: number) => void }) {
  const [isMinimized, setIsMinimized] = useState(false);
  const [point, setPoint] = useState<LocalPoint | null>(null);
  const [latInput, setLatInput] = useState('');
  const [lngInput, setLngInput] = useState('');
  const [radiusKm, setRadiusKm] = useState(150);
  const [data, setData] = useState<LocalIntelResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [locating, setLocating] = useState(false);
  const [error, setError] = useState('');

  const fetchIntel = useCallback(async (target: LocalPoint, radius: number) => {
    setLoading(true);
    setError('');
    try {
      const params = new URLSearchParams({
        lat: String(target.lat),
        lng: String(target.lng),
        radius_km: String(radius),
        limit: '48',
      });
      const response = await fetch(`${API_BASE}/api/local-intel?${params.toString()}`, { cache: 'no-store' });
      if (!response.ok) {
        const payload = (await response.json().catch(() => ({}))) as { detail?: string };
        throw new Error(payload.detail || `Local intel request failed (${response.status})`);
      }
      const payload = (await response.json()) as LocalIntelResponse;
      setData(payload);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Local intel request failed');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const stored = readStoredPoint();
    if (!stored) return;
    setPoint(stored);
    setLatInput(String(stored.lat));
    setLngInput(String(stored.lng));
  }, []);

  useEffect(() => {
    if (!point) return;
    void fetchIntel(point, radiusKm);
  }, [fetchIntel, point, radiusKm]);

  const categoryEntries = useMemo(() => {
    const entries = Object.entries(data?.summary.categories || {});
    return entries.sort((a, b) => b[1] - a[1]);
  }, [data]);

  const savePoint = useCallback((next: LocalPoint) => {
    setPoint(next);
    setLatInput(String(Number(next.lat.toFixed(6))));
    setLngInput(String(Number(next.lng.toFixed(6))));
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  }, []);

  const applyManualPoint = useCallback(() => {
    const lat = Number(latInput);
    const lng = Number(lngInput);
    if (!Number.isFinite(lat) || !Number.isFinite(lng) || lat < -90 || lat > 90 || lng < -180 || lng > 180) {
      setError('Enter valid latitude and longitude.');
      return;
    }
    savePoint({ lat, lng });
  }, [latInput, lngInput, savePoint]);

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
        savePoint({
          lat: position.coords.latitude,
          lng: position.coords.longitude,
        });
      },
      (geoError) => {
        setLocating(false);
        setError(geoError.message || 'Location permission was not granted.');
      },
      { enableHighAccuracy: false, maximumAge: 300000, timeout: 10000 },
    );
  }, [savePoint]);

  return (
    <motion.section
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex-shrink-0 overflow-hidden border border-cyan-900/40 bg-[#05080c]/95 font-mono text-cyan-100 shadow-[0_0_24px_rgba(8,145,178,0.12)]"
    >
      <button
        type="button"
        onClick={() => setIsMinimized((prev) => !prev)}
        className="flex w-full items-center justify-between border-b border-cyan-900/40 px-3 py-2.5 text-left transition-colors hover:bg-cyan-950/20"
      >
        <span className="flex items-center gap-2">
          <Radar size={15} className="text-cyan-300" />
          <span className="text-[12px] font-bold tracking-[0.22em] text-cyan-300">LOCAL INTEL</span>
        </span>
        <span className="flex items-center gap-2 text-[9px] tracking-[0.18em] text-cyan-700">
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
              <div className="relative mb-3 h-9 border border-cyan-900/30 bg-black/30">
                <div className="absolute left-3 right-3 top-1/2 h-px bg-cyan-900/70" />
                <div className="absolute left-1/2 top-1/2 h-7 w-7 -translate-x-1/2 -translate-y-1/2 rounded-full border border-cyan-500/70" />
                <div className="absolute left-[18%] top-1/2 h-3 w-3 -translate-y-1/2 rounded-full border border-cyan-800" />
                <div className="absolute right-[18%] top-1/2 h-3 w-3 -translate-y-1/2 rounded-full border border-cyan-800" />
                <div className="absolute inset-x-0 top-1 px-2 text-[8px] tracking-[0.24em] text-cyan-700">
                  RANGE RING
                </div>
                <div className="absolute bottom-1 right-2 text-[8px] tracking-[0.18em] text-cyan-600">
                  {radiusKm} KM
                </div>
              </div>

              <div className="grid grid-cols-[1fr_1fr_auto] gap-2">
                <label className="flex flex-col gap-1 text-[8px] tracking-[0.18em] text-cyan-700">
                  LAT
                  <input
                    value={latInput}
                    onChange={(event) => setLatInput(event.target.value)}
                    onBlur={applyManualPoint}
                    className="h-8 border border-cyan-900/50 bg-black/40 px-2 text-[11px] tracking-normal text-cyan-100 outline-none focus:border-cyan-400/60"
                    placeholder="40.7128"
                    inputMode="decimal"
                  />
                </label>
                <label className="flex flex-col gap-1 text-[8px] tracking-[0.18em] text-cyan-700">
                  LNG
                  <input
                    value={lngInput}
                    onChange={(event) => setLngInput(event.target.value)}
                    onBlur={applyManualPoint}
                    className="h-8 border border-cyan-900/50 bg-black/40 px-2 text-[11px] tracking-normal text-cyan-100 outline-none focus:border-cyan-400/60"
                    placeholder="-74.0060"
                    inputMode="decimal"
                  />
                </label>
                <button
                  type="button"
                  onClick={locateBrowser}
                  className="mt-4 flex h-8 w-8 items-center justify-center border border-cyan-800/60 bg-cyan-950/20 text-cyan-300 transition-colors hover:border-cyan-300/70 hover:bg-cyan-900/30"
                  title="Use browser location"
                >
                  {locating ? <Loader2 size={15} className="animate-spin" /> : <Crosshair size={15} />}
                </button>
              </div>

              <div className="mt-3 flex items-center justify-between gap-2">
                <div className="flex gap-1">
                  {RADIUS_OPTIONS.map((radius) => (
                    <button
                      key={radius}
                      type="button"
                      onClick={() => setRadiusKm(radius)}
                      className={`h-7 border px-2 text-[9px] tracking-[0.12em] transition-colors ${
                        radiusKm === radius
                          ? 'border-cyan-300/70 bg-cyan-400/10 text-cyan-200'
                          : 'border-cyan-900/50 bg-black/20 text-cyan-700 hover:text-cyan-300'
                      }`}
                    >
                      {radius}
                    </button>
                  ))}
                </div>
                <button
                  type="button"
                  onClick={() => {
                    if (point) void fetchIntel(point, radiusKm);
                    else applyManualPoint();
                  }}
                  className="flex h-7 items-center gap-1.5 border border-cyan-800/60 bg-black/30 px-2 text-[9px] tracking-[0.14em] text-cyan-300 transition-colors hover:border-cyan-300/70"
                >
                  {loading ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
                  SCAN
                </button>
              </div>

              {point && (
                <div className="mt-3 flex items-center gap-2 border border-cyan-900/30 bg-cyan-950/10 px-2 py-1.5 text-[9px] tracking-[0.12em] text-cyan-600">
                  <MapPin size={12} />
                  {formatCoord(point.lat)}, {formatCoord(point.lng)}
                </div>
              )}

              {error && (
                <div className="mt-3 border border-red-500/30 bg-red-950/20 px-2 py-2 text-[10px] leading-4 text-red-200">
                  {error}
                </div>
              )}

              {!point && !error && (
                <div className="mt-3 border border-cyan-900/30 bg-black/20 px-2 py-2 text-[10px] leading-4 text-cyan-600">
                  Set coordinates or use browser location to scan local signals.
                </div>
              )}

              {data && (
                <>
                  <div className="mt-3 grid grid-cols-3 border border-cyan-900/30 bg-black/30 text-center">
                    <div className="border-r border-cyan-900/30 px-2 py-2">
                      <div className="text-[16px] font-bold text-cyan-200">{data.summary.total}</div>
                      <div className="text-[8px] tracking-[0.18em] text-cyan-700">SIGNALS</div>
                    </div>
                    <div className="border-r border-cyan-900/30 px-2 py-2">
                      <div className="text-[16px] font-bold uppercase text-cyan-200">{data.summary.highest_severity}</div>
                      <div className="text-[8px] tracking-[0.18em] text-cyan-700">PEAK</div>
                    </div>
                    <div className="px-2 py-2">
                      <div className="text-[16px] font-bold text-cyan-200">{categoryEntries.length}</div>
                      <div className="text-[8px] tracking-[0.18em] text-cyan-700">BANDS</div>
                    </div>
                  </div>

                  {categoryEntries.length > 0 && (
                    <div className="mt-3 flex flex-wrap gap-1">
                      {categoryEntries.slice(0, 6).map(([category, count]) => (
                        <span
                          key={category}
                          className="border border-cyan-900/40 bg-cyan-950/10 px-1.5 py-1 text-[8px] tracking-[0.14em] text-cyan-500"
                        >
                          {CATEGORY_LABELS[category] || category.toUpperCase()} {count}
                        </span>
                      ))}
                    </div>
                  )}

                  <div className="mt-3 flex max-h-[360px] flex-col gap-2 overflow-y-auto pr-1 styled-scrollbar">
                    {data.items.length === 0 ? (
                      <div className="border border-cyan-900/30 bg-black/20 px-2 py-3 text-[10px] text-cyan-600">
                        No cached signals inside this radius yet.
                      </div>
                    ) : (
                      data.items.slice(0, 14).map((item) => {
                        const Icon = categoryIcon(item.category);
                        return (
                          <button
                            type="button"
                            key={item.id}
                            onClick={() => onFlyTo?.(item.lat, item.lng)}
                            className="group border border-cyan-900/30 bg-black/25 p-2 text-left transition-colors hover:border-cyan-400/50 hover:bg-cyan-950/20"
                          >
                            <div className="flex items-start gap-2">
                              <div className={`mt-0.5 flex h-7 w-7 flex-shrink-0 items-center justify-center border ${severityClass(item.severity)}`}>
                                <Icon size={14} />
                              </div>
                              <div className="min-w-0 flex-1">
                                <div className="flex items-center justify-between gap-2">
                                  <div className="truncate text-[11px] font-bold tracking-[0.08em] text-cyan-100">
                                    {item.label}
                                  </div>
                                  <div className="flex-shrink-0 text-[9px] text-cyan-500">
                                    {item.distance_km}km
                                  </div>
                                </div>
                                <div className="mt-1 line-clamp-2 text-[10px] leading-4 text-cyan-600">
                                  {item.detail}
                                </div>
                                <div className="mt-1 flex items-center justify-between text-[8px] tracking-[0.14em] text-cyan-800">
                                  <span>{CATEGORY_LABELS[item.category] || item.category.toUpperCase()} / {item.kind.toUpperCase()}</span>
                                  <span>{item.source_key.toUpperCase()}</span>
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
