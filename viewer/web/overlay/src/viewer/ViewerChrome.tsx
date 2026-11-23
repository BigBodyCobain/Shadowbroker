'use client';

import React, { useEffect, useState } from 'react';
import { Eye, Info, X, Target, AlertTriangle, Minus, Wrench, ExternalLink } from 'lucide-react';
import { VIEWER_REPO_URL } from './config';
import { feedAgeMs, feedIsStale, useFeedStatus } from './feedStatus';

function useNow(intervalMs: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs]);
  return now;
}

function ageLabel(ms: number): string {
  const s = Math.max(0, Math.round(ms / 1000));
  if (s < 90) return `${s}s ago`;
  const m = Math.round(s / 60);
  if (m < 90) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 48) return `${h} h ago`;
  return `${Math.round(h / 24)} d ago`;
}

/** Top-right card: says what this page is, and how fresh the data is. */
export function ViewerHeaderCard({ onAbout }: { onAbout: () => void }) {
  const status = useFeedStatus();
  const now = useNow(1000);
  const age = feedAgeMs(status, now);
  const stale = feedIsStale(status, now);

  return (
    <div className="sb-panel flex-shrink-0 px-3.5 py-3 pointer-events-auto">
      <div className="flex items-center gap-2">
        <Eye size={15} className="text-cyan-400 shrink-0" aria-hidden="true" />
        <span className="sb-title text-cyan-300">PUBLIC VIEWER</span>
        <span className="ml-auto text-[10px] font-mono tracking-[0.14em] text-[var(--text-muted)]">LOOK-ONLY</span>
      </div>
      <div className="mt-2 flex items-center gap-2 text-[11px] font-mono tracking-wider">
        <span
          className={`feed-dot ${!status.loaded ? (status.reachable ? 'feed-dot-stale' : 'feed-dot-offline') : stale ? 'feed-dot-stale' : 'feed-dot-healthy'}`}
          aria-hidden="true"
        />
        <span className="text-[var(--text-muted)]" role="status">
          {!status.loaded
            ? status.reachable
              ? 'Loading map data…'
              : 'Data feed unreachable'
            : stale
              ? `Feed paused · last update ${ageLabel(age ?? 0)}`
              : `Live · updated ${ageLabel(age ?? 0)}`}
        </span>
      </div>
      <div className="mt-2.5 flex items-center gap-2">
        <button
          type="button"
          onClick={onAbout}
          className="sb-chip flex items-center gap-1.5 px-3 py-1.5 text-[10.5px] font-mono tracking-[0.14em] uppercase text-cyan-300 hover:text-cyan-100"
        >
          <Info size={12} aria-hidden="true" />
          About &amp; sources
        </button>
        <a
          href={VIEWER_REPO_URL}
          target="_blank"
          rel="noopener noreferrer"
          className="sb-chip flex items-center gap-1.5 px-3 py-1.5 text-[10.5px] font-mono tracking-[0.14em] uppercase text-cyan-300 hover:text-cyan-100"
        >
          <ExternalLink size={12} aria-hidden="true" />
          Run the full app
        </a>
      </div>
    </div>
  );
}

/** Top-center banner shown when the published data stopped updating. */
export function StaleBanner() {
  const status = useFeedStatus();
  const now = useNow(5000);
  if (!status.loaded) {
    if (status.reachable) return null;
    return (
      <div role="status" className="sb-offline-toast absolute top-5 left-1/2 -translate-x-1/2 z-[9000] flex items-center gap-2 px-4 py-2">
        <span className="sb-alert-dot text-[#ff3b5c] shrink-0" aria-hidden="true" />
        <span className="sb-prose text-[12.5px] text-[#ffc2cd]">The data feed can&apos;t be reached right now. Retrying…</span>
      </div>
    );
  }
  if (!feedIsStale(status, now)) return null;
  const age = feedAgeMs(status, now) ?? 0;
  return (
    <div role="status" className="sb-offline-toast absolute top-5 left-1/2 -translate-x-1/2 z-[9000] flex items-center gap-2 px-4 py-2">
      <span className="sb-alert-dot text-[#ffb020] shrink-0" aria-hidden="true" />
      <span className="flex items-baseline gap-x-3 gap-y-0.5 flex-wrap">
        <span className="font-[family-name:var(--font-display)] text-[13px] font-bold tracking-[0.14em] text-[#ffb020] whitespace-nowrap">
          FEED PAUSED
        </span>
        <span className="sb-prose text-[12.5px] text-[#ffe2ad]">
          Positions shown are from {ageLabel(age)}, not live.
        </span>
      </span>
    </div>
  );
}

type ViewerToolId = 'scm' | 'cyber';
const VIEWER_TOOLS: { id: ViewerToolId; name: string; Icon: typeof Target; tint: string }[] = [
  { id: 'scm', name: 'SUPPLY CHAIN', Icon: Target, tint: 'text-cyan-400' },
  { id: 'cyber', name: 'CYBER THREATS', Icon: AlertTriangle, tint: 'text-amber-400' },
];

/** The two read-only tools. The owner tools (Shodan, Recon, AI) are not in the viewer. */
export function ViewerToolsPanel({ panels }: { panels: Record<ViewerToolId, React.ReactNode> }) {
  const [active, setActive] = useState<ViewerToolId | null>(null);
  const current = VIEWER_TOOLS.find((tool) => tool.id === active);
  return (
    <div className="sb-panel sb-tools pointer-events-auto shrink-0 overflow-hidden">
      <div
        className={`flex items-center gap-2 px-3 py-2 bg-[rgba(var(--sb-accent-rgb),0.035)] ${active ? 'border-b border-[var(--border-primary)]' : ''}`}
      >
        <Wrench size={15} className="text-cyan-400 shrink-0" />
        <span className="sb-title text-cyan-300">REFERENCE</span>
        <div role="tablist" aria-label="Reference lists" className="ml-auto flex items-center gap-1">
          {VIEWER_TOOLS.map(({ id, name, Icon, tint }) => {
            const on = active === id;
            return (
              <button
                key={id}
                type="button"
                role="tab"
                aria-selected={on}
                aria-label={name}
                title={name}
                onClick={() => setActive((prev) => (prev === id ? null : id))}
                className={`grid place-items-center w-8 h-8 rounded-lg border transition-colors ${
                  on
                    ? 'border-[rgba(var(--sb-accent-rgb),0.55)] bg-[rgba(var(--sb-accent-rgb),0.14)]'
                    : 'border-transparent hover:border-[var(--border-primary)] hover:bg-white/5'
                }`}
              >
                <Icon size={15} className={`${tint} ${on ? '' : 'opacity-80'}`} />
              </button>
            );
          })}
        </div>
      </div>
      {current && (
        <div className="flex items-center justify-between px-3 pt-2.5">
          <span className="text-[11px] font-mono font-bold tracking-[0.16em] text-[var(--text-secondary)]">
            {current.name}
          </span>
          <button
            type="button"
            onClick={() => setActive(null)}
            aria-label={`Close ${current.name.toLowerCase()}`}
            title="Close"
            className="text-cyan-400 hover:text-cyan-200 p-0.5 rounded-md transition-colors"
          >
            <Minus size={15} />
          </button>
        </div>
      )}
      {VIEWER_TOOLS.map(({ id }) => (
        <div key={id} className={active === id ? '' : 'hidden'}>
          {panels[id]}
        </div>
      ))}
    </div>
  );
}

const SOURCES: { name: string; what: string; href: string }[] = [
  { name: 'adsb.lol', what: 'Aircraft positions (ODbL)', href: 'https://adsb.lol' },
  { name: 'OpenSky Network', what: 'Aircraft positions', href: 'https://opensky-network.org' },
  { name: 'AISStream', what: 'Ship positions', href: 'https://aisstream.io' },
  { name: 'CelesTrak', what: 'Satellite orbits', href: 'https://celestrak.org' },
  { name: 'USGS', what: 'Earthquakes', href: 'https://earthquake.usgs.gov' },
  { name: 'NASA FIRMS / GIBS', what: 'Fires and satellite imagery', href: 'https://earthdata.nasa.gov' },
  { name: 'GDELT Project', what: 'Global incidents', href: 'https://www.gdeltproject.org' },
  { name: 'Meshtastic map (Liam Cottle)', what: 'Public mesh node positions', href: 'https://meshtastic.liamcottle.net' },
  { name: 'OpenFreeMap / OpenMapTiles / OpenStreetMap', what: 'Basemap', href: 'https://openfreemap.org' },
  { name: 'Esri World Imagery', what: 'Satellite basemap', href: 'https://www.esri.com' },
  { name: 'Wikipedia', what: 'Summaries (CC BY-SA)', href: 'https://www.wikipedia.org' },
];

/** What this page is, what it cannot do, and where the data comes from. */
export function AboutModal({ onClose }: { onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-[9500] flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
      role="dialog"
      aria-modal="true"
      aria-label="About the public viewer"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="sb-panel w-full max-w-[640px] max-h-[86vh] overflow-y-auto styled-scrollbar px-6 py-5 pointer-events-auto">
        <div className="flex items-start gap-3">
          <h2 className="sb-title text-cyan-300 text-[15px]">ABOUT THE PUBLIC VIEWER</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="ml-auto text-cyan-400 hover:text-cyan-200 p-1 rounded-md transition-colors"
          >
            <X size={16} />
          </button>
        </div>
        <div className="sb-prose mt-3 space-y-3 text-[13px] leading-relaxed text-[var(--text-primary)]">
          <p>
            This is a look-only window onto ShadowBroker. It shows a copy of public map data that refreshes a few
            times a minute. You can pan, zoom, filter and switch layers; those choices stay in your browser.
          </p>
          <p>
            Nothing here can send a message, post, change a setting or start a scan. This page has no connection to
            the machine that gathers the data: it only downloads finished data files.
          </p>
          <p>
            The full app adds radio and mesh tools, AI analysis, imagery lookups and your own data sources. It is
            free and open source, and runs on your own computer.
          </p>
        </div>
        <h3 className="mt-5 text-[11px] font-mono font-bold tracking-[0.16em] text-[var(--text-secondary)]">
          DATA SOURCES
        </h3>
        <ul className="mt-2 grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1.5 text-[12px]">
          {SOURCES.map((s) => (
            <li key={s.name} className="flex flex-col">
              <a href={s.href} target="_blank" rel="noopener noreferrer" className="text-cyan-300 hover:text-cyan-100">
                {s.name}
              </a>
              <span className="text-[var(--text-muted)]">{s.what}</span>
            </li>
          ))}
        </ul>
        <p className="mt-4 text-[11.5px] text-[var(--text-muted)]">
          Positions come from public broadcasts and open datasets and may be late, incomplete or wrong. Not for
          navigation or safety decisions.
        </p>
      </div>
    </div>
  );
}
