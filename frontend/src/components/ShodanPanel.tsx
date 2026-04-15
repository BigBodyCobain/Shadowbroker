'use client';

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  Download,
  KeyRound,
  Radar,
  RefreshCw,
  Save,
  Search,
  Server,
  ShieldAlert,
  Upload,
} from 'lucide-react';
import type { SelectedEntity } from '@/types/dashboard';
import type {
  ShodanCountResponse,
  ShodanHost,
  ShodanSearchMatch,
  ShodanStatusResponse,
  ShodanStyleConfig,
  ShodanMarkerShape,
  ShodanMarkerSize,
} from '@/types/shodan';
import { countShodan, fetchShodanStatus, lookupShodanHost, searchShodan } from '@/lib/shodanClient';

type Mode = 'search' | 'count' | 'host';
type ShodanPreset = {
  id: string;
  label: string;
  mode: Mode;
  query: string;
  page: number;
  facets: string;
  hostIp: string;
  style?: ShodanStyleConfig;
};

const SHODAN_PRESETS_KEY = 'sb_shodan_presets_v1';
const SHODAN_STYLE_KEY = 'sb_shodan_style_v1';

const DEFAULT_STYLE: ShodanStyleConfig = { shape: 'circle', color: '#16a34a', size: 'md' };

const SHAPE_OPTIONS: { value: ShodanMarkerShape; label: string; glyph: string }[] = [
  { value: 'circle', label: 'Circle', glyph: '●' },
  { value: 'triangle', label: 'Triangle', glyph: '▲' },
  { value: 'diamond', label: 'Diamond', glyph: '◆' },
  { value: 'square', label: 'Square', glyph: '■' },
];

const SIZE_OPTIONS: { value: ShodanMarkerSize; label: string }[] = [
  { value: 'sm', label: 'SM' },
  { value: 'md', label: 'MD' },
  { value: 'lg', label: 'LG' },
];

const COLOR_SWATCHES = [
  '#16a34a', '#ef4444', '#3b82f6', '#06b6d4',
  '#f97316', '#eab308', '#ec4899', '#e2e8f0',
];

interface Props {
  onOpenSettings: () => void;
  onResultsChange: (results: ShodanSearchMatch[], queryLabel: string) => void;
  onSelectEntity: (entity: SelectedEntity | null) => void;
  onStyleChange: (style: ShodanStyleConfig) => void;
  currentResults: ShodanSearchMatch[];
  isMinimized?: boolean;
  onMinimizedChange?: (minimized: boolean) => void;
  /** When true the settings modal is open — status auto-refreshes on close. */
  settingsOpen?: boolean;
}

function toSelectedEntity(match: ShodanSearchMatch): SelectedEntity {
  return {
    id: match.id,
    type: 'shodan_host',
    name: `${match.ip}${match.port ? `:${match.port}` : ''}`,
    extra: { ...match },
  };
}

function fromHost(host: ShodanHost): ShodanSearchMatch {
  return {
    id: host.id,
    ip: host.ip,
    port: host.ports?.[0] ?? null,
    lat: host.lat,
    lng: host.lng,
    city: host.city,
    region_code: host.region_code,
    country_code: host.country_code,
    country_name: host.country_name,
    location_label: host.location_label,
    asn: host.asn,
    org: host.org,
    isp: host.isp,
    os: host.os,
    product: host.services?.[0]?.product ?? null,
    transport: host.services?.[0]?.transport ?? null,
    timestamp: host.services?.[0]?.timestamp ?? null,
    hostnames: host.hostnames,
    domains: host.domains,
    tags: host.tags,
    vulns: host.vulns,
    data_snippet: host.services?.[0]?.banner_excerpt ?? null,
    attribution: host.attribution,
  };
}

function facetList(raw: string): string[] {
  return raw
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
    .slice(0, 8);
}

function downloadText(filename: string, content: string, mime = 'application/json') {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function buildCsv(rows: ShodanSearchMatch[]): string {
  const headers = [
    'source',
    'attribution',
    'ip',
    'port',
    'country_code',
    'location_label',
    'org',
    'asn',
    'product',
    'transport',
    'timestamp',
  ];
  const esc = (value: unknown) => `"${String(value ?? '').replaceAll('"', '""')}"`;
  return [
    headers.join(','),
    ...rows.map((row) =>
      [
        'Shodan',
        row.attribution || 'Data from Shodan',
        row.ip,
        row.port ?? '',
        row.country_code ?? '',
        row.location_label ?? '',
        row.org ?? '',
        row.asn ?? '',
        row.product ?? '',
        row.transport ?? '',
        row.timestamp ?? '',
      ]
        .map(esc)
        .join(','),
    ),
  ].join('\n');
}

export default function ShodanPanel({
  onOpenSettings,
  onResultsChange,
  onSelectEntity,
  onStyleChange,
  currentResults,
  isMinimized: isMinimizedProp,
  onMinimizedChange,
  settingsOpen,
}: Props) {
  const [internalMinimized, setInternalMinimized] = useState(true);
  const isMinimized = isMinimizedProp !== undefined ? isMinimizedProp : internalMinimized;
  const setIsMinimized = (val: boolean | ((prev: boolean) => boolean)) => {
    const newVal = typeof val === 'function' ? val(isMinimized) : val;
    setInternalMinimized(newVal);
    onMinimizedChange?.(newVal);
  };
  const [mode, setMode] = useState<Mode>('search');
  const [status, setStatus] = useState<ShodanStatusResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState('port:443');
  const [page, setPage] = useState(1);
  const [facets, setFacets] = useState('country,port,org');
  const [hostIp, setHostIp] = useState('');
  const [presetLabel, setPresetLabel] = useState('');
  const [presets, setPresets] = useState<ShodanPreset[]>([]);
  const [countSummary, setCountSummary] = useState<ShodanCountResponse | null>(null);
  const [hostSummary, setHostSummary] = useState<ShodanHost | null>(null);
  const [styleConfig, setStyleConfig] = useState<ShodanStyleConfig>(DEFAULT_STYLE);
  const [customHex, setCustomHex] = useState('');
  const [lastAction, setLastAction] = useState<(() => void) | null>(null);
  const [unmappedCount, setUnmappedCount] = useState(0);
  const prevSettingsOpen = useRef(settingsOpen);
  const presetImportRef = useRef<HTMLInputElement | null>(null);
  const resultImportRef = useRef<HTMLInputElement | null>(null);

  const refreshStatus = useCallback(async () => {
    try {
      const next = await fetchShodanStatus();
      setStatus(next);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load Shodan status');
    }
  }, []);

  useEffect(() => {
    void refreshStatus();
  }, [refreshStatus]);

  // Auto-refresh status when settings modal closes (key may have changed)
  useEffect(() => {
    if (prevSettingsOpen.current && !settingsOpen) {
      void refreshStatus();
    }
    prevSettingsOpen.current = settingsOpen;
  }, [settingsOpen, refreshStatus]);

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(SHODAN_PRESETS_KEY);
      if (!raw) return;
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) {
        setPresets(parsed);
      }
    } catch {
      // ignore bad local preset state
    }
  }, []);

  useEffect(() => {
    window.localStorage.setItem(SHODAN_PRESETS_KEY, JSON.stringify(presets));
  }, [presets]);

  // Load persisted style config
  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(SHODAN_STYLE_KEY);
      if (!raw) return;
      const parsed = JSON.parse(raw) as ShodanStyleConfig;
      if (parsed && parsed.shape && parsed.color && parsed.size) {
        setStyleConfig(parsed);
        // Defer parent update to avoid setState-during-render
        queueMicrotask(() => onStyleChange(parsed));
      }
    } catch { /* ignore */ }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const updateStyle = useCallback((patch: Partial<ShodanStyleConfig>) => {
    setStyleConfig((prev) => {
      const next = { ...prev, ...patch };
      window.localStorage.setItem(SHODAN_STYLE_KEY, JSON.stringify(next));
      // Defer parent update out of the setState updater
      queueMicrotask(() => onStyleChange(next));
      return next;
    });
  }, [onStyleChange]);

  const handleSearch = useCallback(async () => {
    setBusy(true);
    setError(null);
    setLastAction(() => () => void handleSearch());
    try {
      const resp = await searchShodan(query, page, facetList(facets));
      const mapped = resp.matches.filter((match) => match.lat != null && match.lng != null);
      setUnmappedCount(resp.matches.length - mapped.length);
      onResultsChange(mapped, resp.query);
      setCountSummary({
        ok: true,
        source: resp.source,
        attribution: resp.attribution,
        query: resp.query,
        total: resp.total,
        facets: resp.facets,
        note: resp.note,
      });
      setHostSummary(null);
      setLastAction(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Shodan search failed');
    } finally {
      setBusy(false);
    }
  }, [facets, onResultsChange, page, query]);

  const handleCount = useCallback(async () => {
    setBusy(true);
    setError(null);
    setLastAction(() => () => void handleCount());
    try {
      const resp = await countShodan(query, facetList(facets));
      setCountSummary(resp);
      setHostSummary(null);
      setLastAction(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Shodan count failed');
    } finally {
      setBusy(false);
    }
  }, [facets, query]);

  const handleHost = useCallback(async () => {
    setBusy(true);
    setError(null);
    setLastAction(() => () => void handleHost());
    try {
      const resp = await lookupShodanHost(hostIp);
      setHostSummary(resp.host);
      setCountSummary(null);
      const mapped = fromHost(resp.host);
      onResultsChange(
        resp.host.lat != null && resp.host.lng != null ? [mapped] : [],
        `HOST ${resp.host.ip}`,
      );
      onSelectEntity({
        id: mapped.id,
        type: 'shodan_host',
        name: `${mapped.ip}${mapped.port ? `:${mapped.port}` : ''}`,
        extra: { ...resp.host, ...mapped },
      });
      setLastAction(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Shodan host lookup failed');
    } finally {
      setBusy(false);
    }
  }, [hostIp, onResultsChange, onSelectEntity]);

  const handleClear = useCallback(() => {
    onResultsChange([], '');
    onSelectEntity(null);
    setCountSummary(null);
    setHostSummary(null);
    setError(null);
    setLastAction(null);
    setUnmappedCount(0);
  }, [onResultsChange, onSelectEntity]);

  const handleSavePreset = useCallback(() => {
    const label =
      presetLabel.trim() ||
      (mode === 'host' ? hostIp.trim() || 'Host Lookup' : query.trim() || 'Shodan Query');
    const preset: ShodanPreset = {
      id: `preset-${Date.now()}`,
      label,
      mode,
      query,
      page,
      facets,
      hostIp,
      style: { ...styleConfig },
    };
    setPresets((prev) => [preset, ...prev].slice(0, 16));
    setPresetLabel('');
  }, [facets, hostIp, mode, page, presetLabel, query, styleConfig]);

  const applyPreset = useCallback((preset: ShodanPreset) => {
    setMode(preset.mode);
    setQuery(preset.query);
    setPage(preset.page);
    setFacets(preset.facets);
    setHostIp(preset.hostIp);
    if (preset.style) {
      updateStyle(preset.style);
    }
  }, [updateStyle]);

  const removePreset = useCallback((id: string) => {
    setPresets((prev) => prev.filter((preset) => preset.id !== id));
  }, []);

  const exportPresets = useCallback(() => {
    downloadText(
      `shadowbroker-shodan-presets-${new Date().toISOString().slice(0, 10)}.json`,
      JSON.stringify({ source: 'ShadowBroker', type: 'shodan-presets', presets }, null, 2),
    );
  }, [presets]);

  const importPresets = useCallback(
    async (event: React.ChangeEvent<HTMLInputElement>) => {
      const file = event.target.files?.[0];
      if (!file) return;
      try {
        const text = await file.text();
        const parsed = JSON.parse(text) as { presets?: ShodanPreset[] };
        const incoming = Array.isArray(parsed?.presets) ? parsed.presets : [];
        const sanitized = incoming
          .filter((preset) => preset && typeof preset.label === 'string')
          .map((preset) => ({
            id: preset.id || `preset-${Date.now()}-${Math.random()}`,
            label: String(preset.label || 'Imported Preset'),
            mode: (preset.mode === 'host' || preset.mode === 'count' ? preset.mode : 'search') as Mode,
            query: String(preset.query || ''),
            page: Math.max(1, Math.min(2, Number(preset.page) || 1)),
            facets: String(preset.facets || ''),
            hostIp: String(preset.hostIp || ''),
          }));
        setPresets((prev) => [...sanitized, ...prev].slice(0, 16));
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to import Shodan presets');
      } finally {
        event.target.value = '';
      }
    },
    [],
  );

  const exportResultsJson = useCallback(() => {
    if (!currentResults.length) return;
    downloadText(
      `shadowbroker-shodan-results-${new Date().toISOString().replace(/[:.]/g, '-')}.json`,
      JSON.stringify(
        {
          source: 'Shodan',
          attribution: 'Data from Shodan',
          exported_at: new Date().toISOString(),
          results: currentResults,
        },
        null,
        2,
      ),
    );
  }, [currentResults]);

  const exportResultsCsv = useCallback(() => {
    if (!currentResults.length) return;
    downloadText(
      `shadowbroker-shodan-results-${new Date().toISOString().replace(/[:.]/g, '-')}.csv`,
      buildCsv(currentResults),
      'text/csv',
    );
  }, [currentResults]);

  const importResults = useCallback(
    async (event: React.ChangeEvent<HTMLInputElement>) => {
      const file = event.target.files?.[0];
      if (!file) return;
      try {
        const text = await file.text();
        const parsed = JSON.parse(text) as { results?: ShodanSearchMatch[]; attribution?: string };
        const incoming = Array.isArray(parsed?.results) ? parsed.results : [];
        const sanitized = incoming
          .filter((row) => row && typeof row.ip === 'string')
          .map((row) => ({
            ...row,
            id: String(row.id || `shodan-import-${row.ip}-${row.port || 'na'}`),
            ip: String(row.ip),
            port: row.port == null ? null : Number(row.port),
            lat: row.lat == null ? null : Number(row.lat),
            lng: row.lng == null ? null : Number(row.lng),
            hostnames: Array.isArray(row.hostnames) ? row.hostnames.map(String) : [],
            domains: Array.isArray(row.domains) ? row.domains.map(String) : [],
            tags: Array.isArray(row.tags) ? row.tags.map(String) : [],
            vulns: Array.isArray(row.vulns) ? row.vulns.map(String) : [],
            attribution: String(row.attribution || parsed?.attribution || 'Data from Shodan'),
          }))
          .filter((row) => row.lat != null && row.lng != null);
        onResultsChange(sanitized, 'IMPORTED RESULTS');
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to import Shodan results');
      } finally {
        event.target.value = '';
      }
    },
    [onResultsChange],
  );

  const resultSummary = useMemo(() => {
    if (hostSummary) {
      return `${hostSummary.ip} · ${hostSummary.location_label || 'unmapped'} · ${hostSummary.ports.length} ports`;
    }
    if (countSummary) {
      const unmappedNote = unmappedCount > 0 ? ` · ${unmappedCount} without coordinates` : '';
      return `${countSummary.total.toLocaleString()} matching hosts${unmappedNote}`;
    }
    if (currentResults.length) {
      const unmappedNote = unmappedCount > 0 ? ` · ${unmappedCount} without coordinates` : '';
      return `${currentResults.length.toLocaleString()} mapped results${unmappedNote}`;
    }
    return 'No local Shodan overlay loaded';
  }, [countSummary, currentResults.length, hostSummary, unmappedCount]);

  return (
    <div className="pointer-events-auto flex-shrink-0 border border-green-700/40 bg-black/75 backdrop-blur-sm shadow-[0_0_18px_rgba(34,197,94,0.12)]">
      <div
        className="flex items-center justify-between border-b border-green-700/30 bg-green-950/20 px-3 py-2 cursor-pointer"
        onClick={() => setIsMinimized((prev) => !prev)}
      >
        <div className="flex items-center gap-2">
          <Radar size={13} className="text-green-400" />
          <span className="text-[12px] font-mono font-bold tracking-[0.25em] text-green-400">
            SHODAN CONNECTOR
          </span>
        </div>
        <div className="flex items-center gap-2 text-[12px] font-mono">
          <span className="border border-green-700/40 px-1.5 py-0.5 text-green-300">
            {currentResults.length.toLocaleString()} MAP
          </span>
          <span className="border border-green-700/40 px-1.5 py-0.5 text-green-500/80">
            LOCAL
          </span>
          {isMinimized ? (
            <ChevronUp size={12} className="text-green-500" />
          ) : (
            <ChevronDown size={12} className="text-green-500" />
          )}
        </div>
      </div>

      {!isMinimized && (
      <>
      <div className="border-b border-green-900/40 bg-green-950/10 px-3 py-2 text-sm font-mono leading-relaxed text-green-200/90">
        <div className="flex items-start gap-2">
          <AlertTriangle size={12} className="mt-0.5 text-green-400" />
          <div>
            <div className="font-bold tracking-wider text-green-400">PAID API / OPERATOR-SUPPLIED KEY</div>
            <div>
              Data from Shodan is fetched with the local <span className="text-green-400">SHODAN_API_KEY</span>,
              rendered as a temporary overlay, and remains the operator&apos;s responsibility.
            </div>
          </div>
        </div>
      </div>

      <div className="px-3 py-2">
        <div className="mb-2 flex items-center gap-2 text-[13px] font-mono">
          {(['search', 'count', 'host'] as Mode[]).map((item) => (
            <button
              key={item}
              onClick={() => setMode(item)}
              className={`border px-2 py-1 tracking-[0.2em] transition-colors ${
                mode === item
                  ? 'border-green-500/50 bg-green-950/30 text-green-300'
                  : 'border-green-900/40 text-green-600 hover:border-green-700/60 hover:text-green-400'
              }`}
            >
              {item.toUpperCase()}
            </button>
          ))}
          <button
            onClick={refreshStatus}
            className="ml-auto border border-green-900/40 px-2 py-1 text-green-600 transition-colors hover:border-green-700/60 hover:text-green-400"
          >
            STATUS
          </button>
        </div>

        {!status?.configured && (
          <div className="mb-3 border border-yellow-700/30 bg-yellow-950/10 px-3 py-2 text-sm font-mono text-yellow-300">
            <div className="mb-2 flex items-center gap-2 font-bold tracking-wide">
              <KeyRound size={12} /> SHODAN_API_KEY REQUIRED
            </div>
            <button
              onClick={onOpenSettings}
              className="border border-green-600/40 px-2 py-1 text-green-400 transition-colors hover:border-green-500/70"
            >
              OPEN SETTINGS
            </button>
          </div>
        )}

        <div className="space-y-2 text-sm font-mono">
          {mode !== 'host' ? (
            <>
              <div className="flex items-center gap-2">
                <Search size={12} className="text-green-500" />
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder={'query (e.g. port:443 org:"Amazon")'}
                  className="flex-1 border border-green-900/50 bg-black/70 px-2 py-1.5 text-green-300 outline-none transition-colors focus:border-green-500/60"
                />
              </div>
              <div className="flex items-center gap-2">
                <input
                  value={facets}
                  onChange={(e) => setFacets(e.target.value)}
                  placeholder="facets (country,port,org)"
                  className="flex-1 border border-green-900/50 bg-black/70 px-2 py-1.5 text-green-300 outline-none transition-colors focus:border-green-500/60"
                />
                {mode === 'search' && (
                  <input
                    type="number"
                    min={1}
                    max={2}
                    value={page}
                    onChange={(e) => setPage(Math.max(1, Math.min(2, Number(e.target.value) || 1)))}
                    className="w-16 border border-green-900/50 bg-black/70 px-2 py-1.5 text-green-300 outline-none transition-colors focus:border-green-500/60"
                  />
                )}
              </div>
            </>
          ) : (
            <div className="flex items-center gap-2">
              <Server size={12} className="text-green-500" />
              <input
                value={hostIp}
                onChange={(e) => setHostIp(e.target.value)}
                placeholder="host IP (e.g. 8.8.8.8)"
                className="flex-1 border border-green-900/50 bg-black/70 px-2 py-1.5 text-green-300 outline-none transition-colors focus:border-green-500/60"
              />
            </div>
          )}
        </div>

        <div className="mt-3 flex items-center gap-2 text-[13px] font-mono">
          {mode === 'search' && (
            <button
              onClick={() => void handleSearch()}
              disabled={busy || !status?.configured}
              className="border border-green-600/40 px-2.5 py-1.5 text-green-400 transition-colors hover:border-green-500/70 disabled:cursor-not-allowed disabled:opacity-40"
            >
              SEARCH / MAP
            </button>
          )}
          {mode === 'count' && (
            <button
              onClick={() => void handleCount()}
              disabled={busy || !status?.configured}
              className="border border-green-600/40 px-2.5 py-1.5 text-green-400 transition-colors hover:border-green-500/70 disabled:cursor-not-allowed disabled:opacity-40"
            >
              COUNT / FACETS
            </button>
          )}
          {mode === 'host' && (
            <button
              onClick={() => void handleHost()}
              disabled={busy || !status?.configured}
              className="border border-green-600/40 px-2.5 py-1.5 text-green-400 transition-colors hover:border-green-500/70 disabled:cursor-not-allowed disabled:opacity-40"
            >
              LOOKUP / MAP
            </button>
          )}
          <button
            onClick={handleClear}
            className="border border-green-900/40 px-2.5 py-1.5 text-green-600 transition-colors hover:border-green-700/60 hover:text-green-400"
          >
            CLEAR
          </button>
        </div>

        {/* ── Marker Style Configurator ── */}
        <div className="mt-3 border border-green-900/40 bg-black/80 px-3 py-2">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-[13px] font-mono tracking-[0.22em] text-green-500">MARKER STYLE</span>
            <span className="text-[14px] leading-none" style={{ color: styleConfig.color }}>
              {SHAPE_OPTIONS.find((s) => s.value === styleConfig.shape)?.glyph ?? '●'}
            </span>
          </div>

          {/* Shape */}
          <div className="mb-2">
            <div className="mb-1 text-[12px] font-mono tracking-widest text-green-600">SHAPE</div>
            <div className="flex items-center gap-1.5">
              {SHAPE_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  onClick={() => updateStyle({ shape: opt.value })}
                  className={`flex items-center justify-center w-8 h-7 border text-[13px] transition-colors ${
                    styleConfig.shape === opt.value
                      ? 'border-green-500/60 bg-green-950/40 text-green-300'
                      : 'border-green-900/40 text-green-700 hover:border-green-700/60 hover:text-green-400'
                  }`}
                  title={opt.label}
                >
                  {opt.glyph}
                </button>
              ))}
            </div>
          </div>

          {/* Color */}
          <div className="mb-2">
            <div className="mb-1 text-[12px] font-mono tracking-widest text-green-600">COLOR</div>
            <div className="flex items-center gap-1.5 flex-wrap">
              {COLOR_SWATCHES.map((hex) => (
                <button
                  key={hex}
                  onClick={() => { updateStyle({ color: hex }); setCustomHex(''); }}
                  className={`w-5 h-5 border transition-all ${
                    styleConfig.color === hex && !customHex
                      ? 'border-white scale-110'
                      : 'border-green-900/40 hover:border-green-600/60'
                  }`}
                  style={{ backgroundColor: hex }}
                  title={hex}
                />
              ))}
              <input
                value={customHex}
                onChange={(e) => {
                  const v = e.target.value;
                  setCustomHex(v);
                  if (/^#[0-9a-fA-F]{6}$/.test(v)) {
                    updateStyle({ color: v });
                  }
                }}
                placeholder="#hex"
                maxLength={7}
                className="w-16 border border-green-900/50 bg-black/70 px-1.5 py-0.5 text-[13px] font-mono text-green-300 outline-none focus:border-green-500/60"
              />
            </div>
          </div>

          {/* Size */}
          <div>
            <div className="mb-1 text-[12px] font-mono tracking-widest text-green-600">SIZE</div>
            <div className="flex items-center gap-1.5">
              {SIZE_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  onClick={() => updateStyle({ size: opt.value })}
                  className={`px-2.5 py-1 border text-[13px] font-mono tracking-wider transition-colors ${
                    styleConfig.size === opt.value
                      ? 'border-green-500/60 bg-green-950/40 text-green-300'
                      : 'border-green-900/40 text-green-700 hover:border-green-700/60 hover:text-green-400'
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="mt-3 border border-green-900/40 bg-black/80 px-3 py-2">
          <div className="mb-2 text-[13px] font-mono tracking-[0.22em] text-green-500">PRESETS / EXPORT</div>
          <div className="mb-2 flex items-center gap-2">
            <input
              value={presetLabel}
              onChange={(e) => setPresetLabel(e.target.value)}
              placeholder="preset label"
              className="flex-1 border border-green-900/50 bg-black/70 px-2 py-1.5 text-sm text-green-300 outline-none transition-colors focus:border-green-500/60"
            />
            <button
              onClick={handleSavePreset}
              className="border border-green-600/40 px-2 py-1.5 text-[13px] font-mono text-green-400 transition-colors hover:border-green-500/70"
            >
              <span className="inline-flex items-center gap-1">
                <Save size={10} /> SAVE
              </span>
            </button>
          </div>
          <div className="flex flex-wrap gap-2 text-[13px] font-mono">
            <button
              onClick={exportPresets}
              disabled={!presets.length}
              className="border border-green-900/40 px-2 py-1.5 text-green-600 transition-colors hover:border-green-700/60 hover:text-green-400 disabled:opacity-40"
            >
              <span className="inline-flex items-center gap-1">
                <Download size={10} /> EXPORT PRESETS
              </span>
            </button>
            <button
              onClick={() => presetImportRef.current?.click()}
              className="border border-green-900/40 px-2 py-1.5 text-green-600 transition-colors hover:border-green-700/60 hover:text-green-400"
            >
              <span className="inline-flex items-center gap-1">
                <Upload size={10} /> IMPORT PRESETS
              </span>
            </button>
            <button
              onClick={exportResultsJson}
              disabled={!currentResults.length}
              className="border border-green-900/40 px-2 py-1.5 text-green-600 transition-colors hover:border-green-700/60 hover:text-green-400 disabled:opacity-40"
            >
              <span className="inline-flex items-center gap-1">
                <Download size={10} /> RESULTS JSON
              </span>
            </button>
            <button
              onClick={exportResultsCsv}
              disabled={!currentResults.length}
              className="border border-green-900/40 px-2 py-1.5 text-green-600 transition-colors hover:border-green-700/60 hover:text-green-400 disabled:opacity-40"
            >
              <span className="inline-flex items-center gap-1">
                <Download size={10} /> RESULTS CSV
              </span>
            </button>
            <button
              onClick={() => resultImportRef.current?.click()}
              className="border border-green-900/40 px-2 py-1.5 text-green-600 transition-colors hover:border-green-700/60 hover:text-green-400"
            >
              <span className="inline-flex items-center gap-1">
                <Upload size={10} /> IMPORT RESULTS
              </span>
            </button>
            <input
              ref={presetImportRef}
              type="file"
              accept=".json,application/json"
              className="hidden"
              onChange={(e) => void importPresets(e)}
            />
            <input
              ref={resultImportRef}
              type="file"
              accept=".json,application/json"
              className="hidden"
              onChange={(e) => void importResults(e)}
            />
          </div>
          {presets.length > 0 && (
            <div className="mt-3 max-h-32 space-y-1 overflow-y-auto styled-scrollbar">
              {presets.map((preset) => (
                <div
                  key={preset.id}
                  className="flex items-center justify-between border border-green-950/40 bg-green-950/10 px-2 py-1.5"
                >
                  <button
                    onClick={() => applyPreset(preset)}
                    className="min-w-0 flex-1 truncate text-left text-sm font-mono text-green-300 transition-colors hover:text-green-200"
                  >
                    {preset.label}
                  </button>
                  <button
                    onClick={() => removePreset(preset.id)}
                    className="ml-2 text-[13px] font-mono text-green-700/70 transition-colors hover:text-red-300"
                  >
                    DELETE
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="mt-3 border border-green-900/40 bg-black/80 px-3 py-2 text-sm font-mono">
          <div className="mb-1 flex items-center gap-2 text-green-500">
            <ShieldAlert size={12} />
            <span className="tracking-[0.25em]">SESSION STATUS</span>
          </div>
          <div className="text-green-300/90">{resultSummary}</div>
          {status?.warning && <div className="mt-1 text-green-500/80">{status.warning}</div>}
          {error && (
            <div className="mt-2 flex items-center justify-between border border-red-900/40 bg-red-950/20 px-2 py-1.5 text-red-300">
              <span>{error}</span>
              {lastAction && (
                <button
                  onClick={() => { setError(null); lastAction(); }}
                  disabled={busy}
                  className="ml-2 inline-flex shrink-0 items-center gap-1 border border-red-700/40 px-1.5 py-0.5 text-[13px] font-mono text-red-300 transition-colors hover:border-red-500/60 hover:text-red-200 disabled:opacity-40"
                >
                  <RefreshCw size={9} /> RETRY
                </button>
              )}
            </div>
          )}
        </div>

        {countSummary && (
          <div className="mt-3 max-h-40 space-y-2 overflow-y-auto border border-green-900/40 bg-black/80 p-3 styled-scrollbar">
            <div className="text-[13px] font-mono tracking-[0.22em] text-green-500">FACETS</div>
            {Object.entries(countSummary.facets).length === 0 ? (
              <div className="text-sm font-mono text-green-300/80">No facet buckets returned.</div>
            ) : (
              Object.entries(countSummary.facets).map(([name, buckets]) => (
                <div key={name}>
                  <div className="mb-1 text-[13px] font-mono text-green-400">{name.toUpperCase()}</div>
                  <div className="space-y-1">
                    {buckets.map((bucket) => (
                      <div key={`${name}-${bucket.value}`} className="flex items-center justify-between text-sm font-mono text-green-300/90">
                        <span className="truncate pr-3">{bucket.value || 'UNKNOWN'}</span>
                        <span>{bucket.count.toLocaleString()}</span>
                      </div>
                    ))}
                  </div>
                </div>
              ))
            )}
          </div>
        )}

        {hostSummary && (
          <div className="mt-3 max-h-40 overflow-y-auto border border-green-900/40 bg-black/80 p-3 styled-scrollbar text-sm font-mono">
            <div className="mb-2 flex items-center justify-between text-green-400">
              <span>{hostSummary.ip}</span>
              <span>{hostSummary.location_label || 'UNMAPPED'}</span>
            </div>
            <div className="grid grid-cols-2 gap-2 text-green-300/90">
              <span>ORG</span>
              <span className="text-right">{hostSummary.org || 'UNKNOWN'}</span>
              <span>ASN</span>
              <span className="text-right">{hostSummary.asn || 'UNKNOWN'}</span>
              <span>ISP</span>
              <span className="text-right">{hostSummary.isp || 'UNKNOWN'}</span>
              <span>PORTS</span>
              <span className="text-right">{hostSummary.ports.slice(0, 8).join(', ') || 'NONE'}</span>
            </div>
          </div>
        )}

        {currentResults.length > 0 && (
          <div className="mt-3 max-h-44 overflow-y-auto border border-green-900/40 bg-black/80 p-2 styled-scrollbar">
            <div className="mb-2 flex items-center justify-between text-[13px] font-mono text-green-500">
              <span className="tracking-[0.22em]">MAPPED HOSTS</span>
              <span>{currentResults.length.toLocaleString()}</span>
            </div>
            <div className="space-y-1.5">
              {currentResults.slice(0, 12).map((match) => (
                <button
                  key={match.id}
                  onClick={() => onSelectEntity(toSelectedEntity(match))}
                  className="flex w-full items-center justify-between border border-green-950/40 bg-green-950/10 px-2 py-1.5 text-left transition-colors hover:border-green-700/60 hover:bg-green-950/20"
                >
                  <div className="min-w-0">
                    <div className="truncate text-sm font-mono text-green-300">
                      {match.ip}
                      {match.port ? `:${match.port}` : ''}
                    </div>
                    <div className="truncate text-[13px] font-mono text-green-600">
                      {match.location_label || match.org || 'UNMAPPED'}
                    </div>
                  </div>
                  <div className="ml-3 shrink-0 text-[12px] font-mono text-green-500">
                    {match.product || match.transport || 'HOST'}
                  </div>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
      </>
      )}
    </div>
  );
}
