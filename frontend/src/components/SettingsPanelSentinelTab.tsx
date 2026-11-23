'use client';

import React, { useEffect, useState } from 'react';
import { Satellite } from 'lucide-react';
import { checkBackendSentinelStatus, migrateLegacySentinelBrowserKeys } from '@/lib/sentinelHub';

function UsageMeter() {
  const [usage, setUsage] = useState({ month: '', tiles: 0, pu: 0 });

  useEffect(() => {
    // Import dynamically to avoid SSR issues
    import('@/lib/sentinelHub').then(({ getSentinelUsage }) => {
      setUsage(getSentinelUsage());
    });
    // Refresh every 10s when tab is active
    const id = setInterval(() => {
      import('@/lib/sentinelHub').then(({ getSentinelUsage }) => {
        setUsage(getSentinelUsage());
      });
    }, 10_000);
    return () => clearInterval(id);
  }, []);

  const maxRequests = 10_000;
  const maxPU = 10_000;
  const pct = Math.min(100, (usage.tiles / maxRequests) * 100);
  const barColor =
    pct < 50 ? 'bg-purple-500' : pct < 80 ? 'bg-yellow-500' : 'bg-red-500';
  const textColor =
    pct < 50 ? 'text-purple-400' : pct < 80 ? 'text-yellow-400' : 'text-red-400';

  return (
    <div className="mt-3 p-3 border border-purple-900/30 bg-purple-950/10">
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-[13px] font-mono text-purple-400 tracking-widest">
          MONTHLY USAGE
        </span>
        <span className="text-[13px] font-mono text-[var(--text-muted)]">
          {usage.month || '—'}
        </span>
      </div>
      {/* Progress bar */}
      <div className="w-full h-1.5 rounded-full bg-[var(--bg-primary)] mb-2">
        <div
          className={`h-full rounded-full ${barColor} transition-all`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="grid grid-cols-3 gap-2">
        <div>
          <div className={`text-[11px] font-mono font-bold ${textColor}`}>
            {usage.tiles.toLocaleString()}
          </div>
          <div className="text-[12px] font-mono text-[var(--text-muted)]">
            / {maxRequests.toLocaleString()} tiles
          </div>
        </div>
        <div>
          <div className={`text-[11px] font-mono font-bold ${textColor}`}>
            {usage.pu.toLocaleString()}
          </div>
          <div className="text-[12px] font-mono text-[var(--text-muted)]">
            / {maxPU.toLocaleString()} PU
          </div>
        </div>
        <div>
          <div className="text-[11px] font-mono font-bold text-[var(--text-secondary)]">
            {Math.round(100 - pct)}%
          </div>
          <div className="text-[12px] font-mono text-[var(--text-muted)]">remaining</div>
        </div>
      </div>
    </div>
  );
}

// Sentinel Hub settings tab (post-#298: credentials live in backend .env / API Keys).
export function SentinelTab({ onGoToApiKeys }: { onGoToApiKeys: () => void }) {
  const [backendConfigured, setBackendConfigured] = useState<boolean | null>(null);
  const [migrationResult, setMigrationResult] = useState<{ cleared: string[] } | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    // One-time legacy browser-key wipe. Idempotent — does nothing on a
    // fresh install. We do NOT silently POST any browser-stored values
    // to the backend; operators who relied on them re-enter once in the
    // API Keys panel. Doing the wipe regardless ensures pre-#298 secrets
    // don't linger in localStorage indefinitely.
    setMigrationResult(migrateLegacySentinelBrowserKeys());

    // Check whether the backend has SENTINEL_CLIENT_ID/SECRET set.
    void checkBackendSentinelStatus().then(setBackendConfigured);
  }, []);

  const refresh = async () => {
    setRefreshing(true);
    try {
      // refreshSentinelStatus() invalidates the module-level cache so the
      // next check actually hits the backend instead of returning the
      // memoized value. Lazy-imported so SSR/tests don't choke.
      const { refreshSentinelStatus } = await import('@/lib/sentinelHub');
      refreshSentinelStatus();
      const ok = await checkBackendSentinelStatus();
      setBackendConfigured(ok);
    } finally {
      setRefreshing(false);
    }
  };

  const statusColor =
    backendConfigured === null
      ? 'text-[var(--text-muted)]'
      : backendConfigured
      ? 'text-green-400'
      : 'text-yellow-400';
  const statusLabel =
    backendConfigured === null
      ? 'CHECKING…'
      : backendConfigured
      ? 'CONFIGURED ON BACKEND'
      : 'NOT CONFIGURED';

  return (
    <div className="flex-1 flex flex-col overflow-y-auto styled-scrollbar">
      {/* Setup Guide */}
      <div className="mx-4 mt-4 p-3 border border-purple-900/30 bg-purple-950/10">
        <div className="flex items-start gap-2">
          <Satellite size={12} className="text-purple-400 mt-0.5 flex-shrink-0" />
          <div className="text-sm text-[var(--text-secondary)] font-mono leading-relaxed space-y-2">
            <p className="text-purple-300 font-bold">COPERNICUS SENTINEL HUB SETUP</p>
            <p className="text-[var(--text-muted)]">
              Sentinel Hub gives you access to ESA satellite imagery (Sentinel-2 true color,
              NDVI vegetation, false color IR, moisture index). Free tier: 10,000 processing
              units/month. Follow each step below:
            </p>
            <div className="space-y-1.5 mt-1">
              <p>
                <span className="text-purple-400 font-bold">STEP 1:</span>{' '}
                Go to{' '}
                <a
                  href="https://dataspace.copernicus.eu"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-purple-400 underline hover:text-purple-300"
                >
                  dataspace.copernicus.eu
                </a>
                {' '}&rarr; click <span className="text-white">Register</span> (top right) &rarr;
                create a free account. Pick <span className="text-white">Public</span> for
                User Category.
              </p>
              <p>
                <span className="text-purple-400 font-bold">STEP 2:</span>{' '}
                Once logged in, go to{' '}
                <a
                  href="https://shapps.dataspace.copernicus.eu/dashboard/"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-purple-400 underline hover:text-purple-300"
                >
                  Sentinel Hub Dashboard
                </a>
                {' '}&rarr; click your <span className="text-white">user icon</span> (top right)
                {' '}&rarr; <span className="text-white">User Settings</span>
                {' '}&rarr; <span className="text-white">OAuth clients</span> tab &rarr;{' '}
                click <span className="text-cyan-400">&quot;+ Create new&quot;</span>.
                Give it any name (e.g. &quot;ShadowBroker&quot;). Copy the{' '}
                <span className="text-white">Client ID</span> and{' '}
                <span className="text-white">Client Secret</span> it shows you.
              </p>
              <p>
                <span className="text-purple-400 font-bold">STEP 3:</span>{' '}
                Paste both values into the <span className="text-cyan-400">API Keys</span> panel
                under <span className="text-white">SENTINEL_CLIENT_ID</span> and{' '}
                <span className="text-white">SENTINEL_CLIENT_SECRET</span>, then hit Save.
                The backend uses them to mint short-lived tokens — your browser never sees
                the secret again.
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Backend status */}
      <div className="mx-4 mt-3 p-3 border border-[var(--border-primary)] bg-[var(--bg-primary)]/30">
        <div className="flex items-center justify-between mb-2">
          <span className="text-[13px] font-mono text-[var(--text-muted)] tracking-widest">
            BACKEND STATUS
          </span>
          <span className={`text-[11px] font-mono font-bold ${statusColor}`}>
            {statusLabel}
          </span>
        </div>
        <p className="text-[13px] text-[var(--text-muted)] font-mono leading-relaxed">
          {backendConfigured === false
            ? 'Sentinel credentials are not yet set in the backend .env. Open the API Keys panel to enter them — the tile overlay and Sentinel-2 Intel Card will work as soon as both fields are saved.'
            : backendConfigured === true
            ? 'Sentinel credentials are configured on the backend. The dashboard fetches tokens automatically; your browser does not handle the secret.'
            : 'Checking backend configuration…'}
        </p>
        <div className="mt-3 flex items-center gap-2">
          <button
            onClick={onGoToApiKeys}
            className="flex-1 px-4 py-2 bg-purple-500/20 border border-purple-500/40 text-purple-400 hover:bg-purple-500/30 transition-colors text-sm font-mono flex items-center justify-center gap-1.5"
          >
            OPEN API KEYS PANEL
          </button>
          <button
            onClick={refresh}
            disabled={refreshing}
            className="px-3 py-2 border border-[var(--border-primary)] text-[var(--text-muted)] hover:text-cyan-400 hover:border-cyan-500/50 transition-all text-sm font-mono disabled:opacity-40"
            title="Re-check backend status"
          >
            {refreshing ? 'CHECKING…' : 'REFRESH'}
          </button>
        </div>
      </div>

      {/* Migration notice (only if we actually cleared anything) */}
      {migrationResult && migrationResult.cleared.length > 0 && (
        <div className="mx-4 mt-3 px-3 py-2 text-sm font-mono text-cyan-400 bg-cyan-950/20 border border-cyan-900/30">
          <p className="font-bold mb-1">LEGACY BROWSER CREDENTIALS CLEARED</p>
          <p className="text-[13px] leading-relaxed text-[var(--text-muted)]">
            Found and removed pre-#298 Sentinel credentials from browser storage
            ({migrationResult.cleared.join(', ')}). Re-enter them in the API Keys panel
            above; they&apos;ll be stored server-side from now on and never sent back to
            the browser.
          </p>
        </div>
      )}

      {/* Footer + Usage Meter */}
      <div className="p-4 border-t border-[var(--border-primary)]/80 mt-auto">
        <UsageMeter />
        <div className="mt-2 p-2 border border-[var(--border-primary)]/40 bg-[var(--bg-primary)]/30">
          <p className="text-[13px] text-[var(--text-muted)] font-mono leading-relaxed">
            Credentials are stored in the backend <span className="text-cyan-400">.env</span>{' '}
            and never sent to the browser. The tile proxy mints short-lived OAuth tokens
            on demand using those values.
          </p>
        </div>
      </div>
    </div>
  );
}
