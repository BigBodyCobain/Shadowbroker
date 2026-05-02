'use client';

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Download,
  Eye,
  EyeOff,
  KeyRound,
  Minus,
  Plus,
  Radar,
  RefreshCw,
  Save,
  Search,
  Server,
  Upload,
} from 'lucide-react';
import { API_BASE } from '@/lib/api';
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
  onOpenSettings: _onOpenSettings,
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
  const [shodanApiKey, setShodanApiKey] = useState('');
  const [showKey, setShowKey] = useState(false);
  const [keySaving, setKeySaving] = useState(false);
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
        className="flex items-center justify-between border-b border-green-700/30 bg-green-950/20 px-3 py-2.5 cursor-pointer hover:bg-green-950/40 transition-colors"
        onClick={() => setIsMinimized((prev) => !prev)}
      >
        <div className="flex items-center gap-2">
          <Radar size={16} className="text-green-400" />
          <span className="text-[12px] font-mono font-bold tracking-widest text-green-400">
            SHODAN
          </span>
          {currentResults.length > 0 && (
            <span className="text-[11px] font-mono px-1.5 py-0.5 bg-green-900/30 border border-green-700/30 text-green-300">
              {currentResults.length.toLocaleString()} MAPPED
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {isMinimized ? (
            <Plus size={16} className="text-green-400" />
          ) : (
            <Minus size={16} className="text-green-400" />
          )}
        </div>
      </div>

      {!isMinimized && (
      <>
      <div className="px-3 py-2">
        <div className="mb-2 flex items-center gap-1.5 text-[11px] font-mono">
          {(['search', 'count', 'host'] as Mode[]).map((item) => (
            <button
              key={item}
              onClick={() => setMode(item)}
              className={`border px-2 py-0.5 tracking-[0.15em] transition-colors ${
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
            title="Refresh Shodan status"
            className="ml-auto text-green-600 transition-colors hover:text-green-400 p-0.5"
          >
            <RefreshCw size={11} />
          </button>
        </div>

        {!status?.configured && (
          <div className="mb-2 border border-green-700/30 bg-green-950/10 px-2.5 py-2">
            <div className="flex items-center gap-1.5 text-[11px] font-mono text-green-300 mb-1.5">
              <KeyRound size={10} />
              <span className="tracking-wider">SHODAN API KEY</span>
              <a
                href="https://account.shodan.io/billing"
                target="_blank"
                rel="noopener noreferrer"
                className="ml-auto text-[9px] text-green-500/60 hover:text-green-400 transition-colors"
              >
                GET KEY →
              </a>
            </div>
            <div className="flex items-center gap-1">
              <input
                type={showKey ? 'text' : 'password'}
                value={shodanApiKey}
                onChange={(e) => setShodanApiKey(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && shodanApiKey.trim()) {
                    setKeySaving(true);
                    fetch(`${API_BASE}/api/settings/api-keys`, {
                      method: 'PUT',
                      headers: { 'Content-Type': 'application/json' },
                      body: JSON.stringify({ env_key: 'SHODAN_API_KEY', value: shodanApiKey.trim() }),
                    })
                      .then(() => refreshStatus())
                      .finally(() => setKeySaving(false));
                  }
                }}
                placeholder="Paste your Shodan API key"
                className="flex-1 border border-green-900/50 bg-black/70 px-2 py-1 text-[11px] font-mono text-green-300 outline-none transition-colors focus:border-green-500/60 placeholder:text-green-800"
              />
              <button
                onClick={() => setShowKey(!showKey)}
                className="p-1 text-green-600 hover:text-green-400 transition-colors"
                title={showKey ? 'Hide key' : 'Show key'}
              >
                {showKey ? <EyeOff size={12} /> : <Eye size={12} />}
              </button>
              <button
                disabled={!shodanApiKey.trim() || keySaving}
                onClick={() => {
                  setKeySaving(true);
                  fetch(`${API_BASE}/api/settings/api-keys`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ env_key: 'SHODAN_API_KEY', value: shodanApiKey.trim() }),
                  })
                    .then(() => refreshStatus())
                    .finally(() => setKeySaving(false));
                }}
                className="border border-green-600/40 px-1.5 py-0.5 text-[10px] font-mono text-green-400 transition-colors hover:border-green-500/70 disabled:opacity-40"
              >
                {keySaving ? '...' : 'SAVE'}
              </button>
            </div>
          </div>
        )}

        <div className="space-y-1.5 text-[12px] font-mono">
          {mode !== 'host' ? (
            <>
              <div className="flex items-center gap-1.5">
                <Search size={11} className="text-green-500 shrink-0" />
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && (mode === 'search' ? void handleSearch() : void handleCount())}
                  placeholder='port:443 org:"Amazon"'
                  className="flex-1 border border-green-900/50 bg-black/70 px-2 py-1 text-green-300 outline-none transition-colors focus:border-green-500/60"
                />
              </div>
              <div className="flex items-center gap-1.5">
                <input
                  value={facets}
                  onChange={(e) => setFacets(e.target.value)}
                  placeholder="country,port,org"
                  className="flex-1 border border-green-900/50 bg-black/70 px-2 py-1 text-green-300 outline-none transition-colors focus:border-green-500/60"
                />
                {mode === 'search' && (
                  <input
                    type="number"
                    min={1}
                    max={2}
                    value={page}
                    onChange={(e) => setPage(Math.max(1, Math.min(2, Number(e.target.value) || 1)))}
                    title="Page number"
                    className="w-12 border border-green-900/50 bg-black/70 px-1.5 py-1 text-center text-green-300 outline-none transition-colors focus:border-green-500/60"
                  />
                )}
              </div>
            </>
          ) : (
            <div className="flex items-center gap-1.5">
              <Server size={11} className="text-green-500 shrink-0" />
              <input
                value={hostIp}
                onChange={(e) => setHostIp(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && void handleHost()}
                placeholder="8.8.8.8"
                className="flex-1 border border-green-900/50 bg-black/70 px-2 py-1 text-green-300 outline-none transition-colors focus:border-green-500/60"
              />
            </div>
          )}
        </div>

        <div className="mt-2 flex items-center gap-1.5 text-[11px] font-mono">
          <button
            onClick={() => mode === 'host' ? void handleHost() : mode === 'count' ? void handleCount() : void handleSearch()}
            disabled={busy || !status?.configured}
            className="flex-1 border border-green-600/40 py-1.5 text-center text-green-400 transition-colors hover:border-green-500/70 hover:bg-green-950/20 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {busy ? '...' : mode === 'host' ? 'LOOKUP' : mode === 'count' ? 'COUNT' : 'SEARCH'}
          </button>
          <button
            onClick={handleClear}
            className="border border-green-900/40 px-2.5 py-1.5 text-green-600 transition-colors hover:border-green-700/60 hover:text-green-400"
          >
            CLEAR
          </button>
        </div>

        {/* ── Marker Style ── */}
        <div className="mt-2 border border-green-900/40 bg-black/60 px-2.5 py-2">
          <div className="mb-1.5 flex items-center justify-between">
            <span className="text-[10px] font-mono tracking-widest text-green-600 uppercase">Style</span>
            <span className="text-[13px] leading-none" style={{ color: styleConfig.color }}>
              {SHAPE_OPTIONS.find((s) => s.value === styleConfig.shape)?.glyph ?? '●'}
            </span>
          </div>
          <div className="flex items-center gap-3">
            {/* Shape */}
            <div className="flex items-center gap-1">
              {SHAPE_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  onClick={() => updateStyle({ shape: opt.value })}
                  className={`flex items-center justify-center w-6 h-6 border text-[11px] transition-colors ${
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
            <div className="w-px h-5 bg-green-900/40" />
            {/* Size */}
            <div className="flex items-center gap-1">
              {SIZE_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  onClick={() => updateStyle({ size: opt.value })}
                  className={`px-1.5 py-0.5 border text-[10px] font-mono transition-colors ${
                    styleConfig.size === opt.value
                      ? 'border-green-500/60 bg-green-950/40 text-green-300'
                      : 'border-green-900/40 text-green-700 hover:border-green-700/60 hover:text-green-400'
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
            <div className="w-px h-5 bg-green-900/40" />
            {/* Color swatches */}
            <div className="flex items-center gap-1 flex-wrap">
              {COLOR_SWATCHES.map((hex) => (
                <button
                  key={hex}
                  onClick={() => { updateStyle({ color: hex }); setCustomHex(''); }}
                  className={`w-4 h-4 border transition-all ${
                    styleConfig.color === hex && !customHex
                      ? 'border-white scale-110'
                      : 'border-green-900/40 hover:border-green-600/60'
                  }`}
                  style={{ backgroundColor: hex }}
                  title={hex}
                />
              ))}
            </div>
          </div>
        </div>

        {/* ── Presets & Data ── */}
        <div className="mt-2 border border-green-900/40 bg-black/60 px-2.5 py-2">
          <div className="mb-1.5 text-[10px] font-mono tracking-widest text-green-600 uppercase">Presets</div>
          <div className="flex items-center gap-1.5 mb-1.5">
            <input
              value={presetLabel}
              onChange={(e) => setPresetLabel(e.target.value)}
              placeholder="label"
              className="flex-1 border border-green-900/50 bg-black/70 px-2 py-1 text-[11px] font-mono text-green-300 outline-none transition-colors focus:border-green-500/60"
            />
            <button onClick={handleSavePreset} title="Save preset" className="border border-green-600/40 p-1 text-green-400 transition-colors hover:border-green-500/70">
              <Save size={11} />
            </button>
            <button onClick={exportPresets} disabled={!presets.length} title="Export presets" className="border border-green-900/40 p-1 text-green-600 transition-colors hover:border-green-700/60 hover:text-green-400 disabled:opacity-40">
              <Download size={11} />
            </button>
            <button onClick={() => presetImportRef.current?.click()} title="Import presets" className="border border-green-900/40 p-1 text-green-600 transition-colors hover:border-green-700/60 hover:text-green-400">
              <Upload size={11} />
            </button>
          </div>
          {presets.length > 0 && (
            <div className="max-h-20 space-y-0.5 overflow-y-auto styled-scrollbar mb-1.5">
              {presets.map((preset) => (
                <div key={preset.id} className="flex items-center justify-between bg-green-950/10 px-2 py-0.5">
                  <button onClick={() => applyPreset(preset)} className="min-w-0 flex-1 truncate text-left text-[11px] font-mono text-green-300 transition-colors hover:text-green-200">
                    {preset.label}
                  </button>
                  <button onClick={() => removePreset(preset.id)} title="Delete preset" className="ml-1.5 text-[10px] font-mono text-green-700/70 transition-colors hover:text-red-300">✕</button>
                </div>
              ))}
            </div>
          )}
          {currentResults.length > 0 && (
            <div className="flex items-center gap-1.5 pt-1.5 border-t border-green-900/30">
              <span className="text-[10px] font-mono text-green-600">Export:</span>
              <button onClick={exportResultsJson} className="text-[10px] font-mono text-green-500 hover:text-green-300 transition-colors">JSON</button>
              <span className="text-green-900">·</span>
              <button onClick={exportResultsCsv} className="text-[10px] font-mono text-green-500 hover:text-green-300 transition-colors">CSV</button>
              <span className="text-green-900">·</span>
              <button onClick={() => resultImportRef.current?.click()} className="text-[10px] font-mono text-green-500 hover:text-green-300 transition-colors">Import</button>
            </div>
          )}
          <input ref={presetImportRef} type="file" accept=".json,application/json" className="hidden" title="Import presets file" onChange={(e) => void importPresets(e)} />
          <input ref={resultImportRef} type="file" accept=".json,application/json" className="hidden" title="Import results file" onChange={(e) => void importResults(e)} />
        </div>

        {/* Status / Errors */}
        <div className="mt-2 px-0.5 text-[11px] font-mono text-green-500/70">
          {resultSummary}
          {status?.warning && <span className="ml-1 text-yellow-500/70">· {status.warning}</span>}
        </div>
        {error && (
          <div className="mt-1.5 flex items-center justify-between border border-red-900/40 bg-red-950/20 px-2 py-1 text-[11px] font-mono text-red-300">
            <span className="truncate">{error}</span>
            {lastAction && (
              <button
                onClick={() => { setError(null); lastAction(); }}
                disabled={busy}
                className="ml-1.5 shrink-0 text-red-400 hover:text-red-200 transition-colors disabled:opacity-40"
              >
                <RefreshCw size={10} />
              </button>
            )}
          </div>
        )}

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
