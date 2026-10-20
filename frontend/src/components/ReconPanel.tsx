'use client';

import React, { useCallback, useState } from 'react';
import { Loader2, Minus, Plus, Radar, RefreshCw, Search, Shield } from 'lucide-react';
import { API_BASE } from '@/lib/api';
import { useTranslation } from '@/i18n';
import ReconResults from '@/components/ReconResults';

type TabId =
  | 'ip'
  | 'dns'
  | 'whois'
  | 'certs'
  | 'threats'
  | 'bgp'
  | 'sanctions'
  | 'cve'
  | 'mac'
  | 'github'
  | 'leaks'
  | 'sweep';

const TABS: Array<{
  id: TabId;
  label: string;
  param: string;
  path: string;
  optional?: boolean;
}> = [
  { id: 'ip', label: 'IP LOOKUP', param: 'ip', path: 'ip' },
  { id: 'dns', label: 'DNS', param: 'domain', path: 'dns' },
  { id: 'whois', label: 'WHOIS / RDAP', param: 'domain', path: 'whois' },
  { id: 'certs', label: 'CERTS', param: 'domain', path: 'certs' },
  { id: 'threats', label: 'THREATS', param: 'query', path: 'threats', optional: true },
  { id: 'bgp', label: 'BGP / ASN', param: 'query', path: 'bgp' },
  { id: 'sanctions', label: 'OFAC SDN', param: 'query', path: 'sanctions' },
  { id: 'cve', label: 'CVE', param: 'cve', path: 'cve' },
  { id: 'mac', label: 'MAC', param: 'mac', path: 'mac' },
  { id: 'github', label: 'GITHUB', param: 'username', path: 'github' },
  { id: 'leaks', label: 'LEAKS', param: 'email', path: 'leaks' },
  { id: 'sweep', label: 'IP SWEEP', param: 'ip', path: 'sweep' },
];

export default function ReconPanel() {
  const { t } = useTranslation();
  const [isMinimized, setIsMinimized] = useState(true);
  const [activeTab, setActiveTab] = useState<TabId>('ip');
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [results, setResults] = useState<unknown>(null);

  const active = TABS.find((tab) => tab.id === activeTab);

  const runLookup = useCallback(async () => {
    if (!active || loading) return;
    if (!active.optional && !query.trim()) return;

    setLoading(true);
    setError('');
    setResults(null);

    try {
      if (activeTab === 'sweep') {
        const res = await fetch(`${API_BASE}/api/osint/sweep/scan`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ip: query.trim(), cidr: 24 }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || data.error || `HTTP ${res.status}`);
        setResults(data);
      } else {
        const params = new URLSearchParams();
        if (query.trim()) params.set(active.param, query.trim());
        const res = await fetch(`${API_BASE}/api/osint/${active.path}?${params}`);
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || data.error || `HTTP ${res.status}`);
        setResults(data);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Lookup failed');
    } finally {
      setLoading(false);
    }
  }, [active, activeTab, query, loading]);

  return (
    <div className="pointer-events-auto flex-shrink-0 border border-cyan-700/40 bg-black/75 backdrop-blur-sm shadow-[0_0_18px_rgba(34,211,238,0.10)]">
      <div
        className="flex items-center justify-between border-b border-cyan-700/30 bg-cyan-950/20 px-3 py-2.5 cursor-pointer hover:bg-cyan-950/40 transition-colors"
        onClick={() => setIsMinimized((prev) => !prev)}
      >
        <div className="flex items-center gap-2">
          <Radar size={16} className="text-cyan-400" />
          <span className="text-[12px] font-mono font-bold tracking-widest text-cyan-400">
            {t('recon.title').toUpperCase()}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {isMinimized ? (
            <Plus size={16} className="text-cyan-400" />
          ) : (
            <Minus size={16} className="text-cyan-400" />
          )}
        </div>
      </div>

      {!isMinimized && (
        <div className="px-3 py-2 space-y-2">
          <div className="flex items-center gap-1.5 text-[11px] font-mono">
            <select
              value={activeTab}
              onChange={(e) => {
                setActiveTab(e.target.value as TabId);
                setResults(null);
                setError('');
              }}
              className="flex-1 border border-cyan-900/50 bg-black/70 px-2 py-1 text-[11px] font-mono text-cyan-300 tracking-[0.12em] outline-none transition-colors focus:border-cyan-500/60"
            >
              {TABS.map((tab) => (
                <option key={tab.id} value={tab.id}>
                  {tab.label}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={() => {
                setQuery('');
                setResults(null);
                setError('');
              }}
              title="Clear"
              className="text-cyan-600 transition-colors hover:text-cyan-400 p-0.5"
            >
              <RefreshCw size={11} />
            </button>
          </div>

          <div className="flex items-center gap-1">
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && runLookup()}
              placeholder={active?.param || 'query'}
              className="flex-1 border border-cyan-900/50 bg-black/70 px-2 py-1 text-[11px] font-mono text-cyan-300 outline-none transition-colors focus:border-cyan-500/60 placeholder:text-cyan-800"
            />
            <button
              type="button"
              onClick={runLookup}
              disabled={loading}
              className="border border-cyan-600/40 px-2 py-1 text-[10px] font-mono tracking-wider text-cyan-400 transition-colors hover:border-cyan-500/70 disabled:opacity-40 flex items-center gap-1"
            >
              {loading ? <Loader2 size={12} className="animate-spin" /> : <Search size={12} />}
              RUN
            </button>
          </div>

          <div className="flex items-center gap-1.5 text-[10px] font-mono text-cyan-600 tracking-wider">
            <Shield size={10} />
            <span>{t('recon.proxyNote')}</span>
          </div>

          {error && (
            <div className="border border-red-500/30 bg-red-950/20 px-2 py-1.5 text-[11px] font-mono text-red-400">
              {error}
            </div>
          )}

          {results != null && <ReconResults tabId={activeTab} results={results} />}
        </div>
      )}
    </div>
  );
}
