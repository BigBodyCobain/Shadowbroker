'use client';

import React, { useCallback, useEffect, useState } from 'react';
import { API_BASE } from '@/lib/api';

export function SarSettingsTab() {
  const [status, setStatus] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionMsg, setActionMsg] = useState<{ type: 'ok' | 'err'; text: string } | null>(null);
  const [disabling, setDisabling] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [earthdataUser, setEarthdataUser] = useState('');
  const [earthdataToken, setEarthdataToken] = useState('');

  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/sar/status`, { credentials: 'include' });
      if (res.ok) {
        const body = await res.json();
        setStatus(body);
      }
    } catch { /* silent */ }
    setLoading(false);
  }, []);

  useEffect(() => { fetchStatus(); }, [fetchStatus]);

  const products = (status?.products ?? {}) as Record<string, unknown>;
  const tokenSet = Boolean(products.earthdata_token_set);
  const fullyConfigured = Boolean(products.fully_configured);
  const optInEnabled = Boolean(products.enabled);
  const runtimeStoreExists = Boolean(products.runtime_store_exists);
  const catalogEnabled = !!(status?.catalog as Record<string, unknown>)?.enabled;
  const openclawEnabled = !!status?.openclaw_enabled;
  const missing = Array.isArray(products.missing)
    ? (products.missing as string[])
    : [];

  const modeBStatusLabel = (() => {
    if (fullyConfigured) return 'Active — credentials configured';
    if (optInEnabled && !tokenSet) return 'Opt-in on — Earthdata token missing';
    if (tokenSet && !optInEnabled) return 'Token present — enable Mode B below';
    return 'Not configured';
  })();

  const handleEnable = async () => {
    if (earthdataToken.trim().length < 8) {
      setActionMsg({ type: 'err', text: 'Earthdata token looks too short. Paste the full token string.' });
      return;
    }
    setSubmitting(true);
    setActionMsg(null);
    try {
      const res = await fetch(`${API_BASE}/api/sar/mode-b/enable`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          earthdata_user: earthdataUser.trim(),
          earthdata_token: earthdataToken.trim(),
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        let msg = `HTTP ${res.status}`;
        const d = body?.detail;
        if (typeof d === 'string') msg = d;
        else if (Array.isArray(d) && d.length > 0) {
          msg = d.map((item: { msg?: string; loc?: string[] }) => item?.msg || 'invalid').join('; ');
        }
        throw new Error(msg);
      }
      setEarthdataToken('');
      setActionMsg({ type: 'ok', text: 'Mode B enabled. Credentials saved on this node.' });
      await fetchStatus();
    } catch (e) {
      setActionMsg({
        type: 'err',
        text: e instanceof Error ? e.message : 'Failed to save SAR credentials',
      });
    } finally {
      setSubmitting(false);
    }
  };

  const handleDisable = async () => {
    setDisabling(true);
    setActionMsg(null);
    try {
      const res = await fetch(`${API_BASE}/api/sar/mode-b/disable`, {
        method: 'POST',
        credentials: 'include',
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(typeof body?.detail === 'string' ? body.detail : `HTTP ${res.status}`);
      }
      setEarthdataUser('');
      setEarthdataToken('');
      setActionMsg({ type: 'ok', text: 'Mode B disabled. Credentials wiped.' });
      await fetchStatus();
    } catch (e) {
      setActionMsg({
        type: 'err',
        text: e instanceof Error ? e.message : 'Failed to disable Mode B',
      });
    } finally {
      setDisabling(false);
    }
  };

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center p-8">
        <span className="text-xs font-mono text-[var(--text-muted)] animate-pulse">
          Loading SAR status...
        </span>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col overflow-y-auto styled-scrollbar">
      {/* Status Overview */}
      <div className="mx-4 mt-4 p-3 border border-amber-900/30 bg-amber-950/10">
        <div className="flex items-start gap-2">
          <Radar size={12} className="text-amber-400 mt-0.5 flex-shrink-0" />
          <div className="text-sm text-[var(--text-secondary)] font-mono leading-relaxed space-y-2">
            <p className="text-amber-300 font-bold">SAR GROUND-CHANGE STATUS</p>
            <div className="space-y-1.5">
              <div className="flex items-center gap-2">
                <span className={`w-2 h-2 rounded-full ${catalogEnabled ? 'bg-green-400' : 'bg-red-400'}`} />
                <span className="text-[11px]">
                  <span className="text-amber-300 font-bold">Mode A</span> (Catalog):{' '}
                  {catalogEnabled ? 'Active' : 'Disabled'}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <span
                  className={`w-2 h-2 rounded-full ${
                    fullyConfigured ? 'bg-green-400' : optInEnabled || tokenSet ? 'bg-yellow-400' : 'bg-gray-500'
                  }`}
                />
                <span className="text-[11px]">
                  <span className="text-amber-300 font-bold">Mode B</span> (Anomalies):{' '}
                  {modeBStatusLabel}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <span className={`w-2 h-2 rounded-full ${openclawEnabled ? 'bg-green-400' : 'bg-gray-500'}`} />
                <span className="text-[11px]">
                  AI agent SAR integration:{' '}
                  {openclawEnabled ? 'Enabled' : 'Disabled'}
                </span>
              </div>
            </div>
            {missing.length > 0 && !fullyConfigured && (
              <p className="text-[10px] text-amber-200/60 pt-1">
                Still needed: {missing.join(' · ')}
              </p>
            )}
          </div>
        </div>
      </div>

      {/* Mode B credential entry — always visible */}
      <div className="mx-4 mt-3 p-3 border border-amber-900/20 bg-amber-950/5 space-y-3">
        <p className="text-[11px] font-mono text-amber-300 font-bold tracking-wide">
          MODE B — EARTHDATA CREDENTIALS
        </p>
        <p className="text-[11px] font-mono text-[var(--text-muted)] leading-relaxed">
          Free NASA Earthdata Login required for OPERA ground-change products. Paste your user
          token below — stored only on this node
          {runtimeStoreExists ? ' in the runtime credentials file' : ' (created on first save)'}.
        </p>

        <ol className="list-decimal list-inside space-y-1 text-[11px] font-mono text-[var(--text-secondary)]">
          <li>
            Register at{' '}
            <a
              href="https://urs.earthdata.nasa.gov/users/new"
              target="_blank"
              rel="noopener noreferrer"
              className="text-amber-400 underline hover:text-amber-300"
            >
              urs.earthdata.nasa.gov
            </a>
          </li>
          <li>
            Generate a user token from your{' '}
            <a
              href="https://urs.earthdata.nasa.gov/profile"
              target="_blank"
              rel="noopener noreferrer"
              className="text-amber-400 underline hover:text-amber-300"
            >
              Earthdata profile
            </a>
          </li>
        </ol>

        <div className="space-y-2">
          <label htmlFor="sar-settings-earthdata-user" className="block text-[11px] text-amber-200/80">
            Earthdata username (optional)
          </label>
          <input
            id="sar-settings-earthdata-user"
            type="text"
            value={earthdataUser}
            onChange={(e) => setEarthdataUser(e.target.value)}
            placeholder="yourname"
            autoComplete="off"
            className="w-full rounded border border-amber-400/30 bg-zinc-900 px-3 py-2 text-xs text-amber-100 placeholder:text-amber-100/30 focus:border-amber-400/70 focus:outline-none cursor-text"
          />

          <label htmlFor="sar-settings-earthdata-token" className="block text-[11px] text-amber-200/80 mt-2">
            Earthdata user token (required)
          </label>
          <input
            id="sar-settings-earthdata-token"
            type="password"
            value={earthdataToken}
            onChange={(e) => setEarthdataToken(e.target.value)}
            placeholder={tokenSet ? '••••••••  (enter new token to rotate)' : 'eyJ0eXAiOiJKV1QiLCJhbGciOi...'}
            autoComplete="off"
            className="w-full rounded border border-amber-400/30 bg-zinc-900 px-3 py-2 text-xs text-amber-100 placeholder:text-amber-100/30 focus:border-amber-400/70 focus:outline-none font-mono cursor-text"
          />
        </div>

        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => void handleEnable()}
            disabled={submitting || earthdataToken.trim().length < 8}
            className="px-3 py-1.5 text-[10px] font-mono font-bold tracking-wide border border-amber-400/50 text-amber-200 hover:bg-amber-500/10 transition disabled:opacity-50"
          >
            {submitting ? 'SAVING...' : fullyConfigured ? 'UPDATE CREDENTIALS' : 'ENABLE MODE B'}
          </button>
          {(fullyConfigured || optInEnabled || tokenSet) && (
            <button
              type="button"
              onClick={() => void handleDisable()}
              disabled={disabling}
              className="px-3 py-1.5 text-[10px] font-mono font-bold tracking-wide border border-red-500/40 text-red-400 hover:bg-red-500/10 transition disabled:opacity-50"
            >
              {disabling ? 'DISABLING...' : 'REVOKE & DISABLE MODE B'}
            </button>
          )}
        </div>
      </div>

      {/* Action feedback */}
      {actionMsg && (
        <div
          className={`mx-4 mt-3 p-2 text-[11px] font-mono border ${
            actionMsg.type === 'ok'
              ? 'text-green-400 border-green-500/30 bg-green-950/10'
              : 'text-red-400 border-red-500/30 bg-red-950/10'
          }`}
        >
          {actionMsg.text}
        </div>
      )}

      {/* Info blurb */}
      <div className="mx-4 mt-3 mb-4 p-3 border border-[var(--border-primary)]/30">
        <p className="text-[11px] font-mono text-[var(--text-muted)] leading-relaxed">
          SAR (Synthetic Aperture Radar) detects ground changes through cloud cover, at
          night, anywhere on Earth. Mode A is a free Sentinel-1 scene catalog from
          Alaska Satellite Facility. Mode B adds real-time anomaly detection via NASA
          OPERA DISP, DSWx, DIST-ALERT, and Copernicus EGMS — all free with an
          Earthdata account.
        </p>
      </div>
    </div>
  );
}
