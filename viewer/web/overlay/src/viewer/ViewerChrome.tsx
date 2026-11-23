'use client';

import React, { useEffect, useState } from 'react';
import { Eye, Info, X, Target, AlertTriangle, Minus, Wrench, MessagesSquare, Coins } from 'lucide-react';
import { VIEWER_LINKS, type ViewerLinkId } from './config';
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
        <button
          type="button"
          onClick={onAbout}
          className="ml-auto flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] font-mono tracking-[0.14em] uppercase text-cyan-300/90 hover:text-cyan-100 hover:bg-cyan-500/10 transition-colors"
        >
          <Info size={11} aria-hidden="true" />
          About
        </button>
      </div>

      {/* Community links: one tile each, opening the project's page on that site. */}
      <nav aria-label="Community links" className="mt-3 grid grid-cols-4 gap-2">
        {VIEWER_LINKS.map((link) => {
          const look = LINK_LOOK[link.id];
          return (
            <a
              key={link.id}
              href={link.href}
              title={link.title}
              aria-label={link.title}
              target="_blank"
              rel="noopener noreferrer"
              className="sb-link-tile group relative flex flex-col items-center gap-1.5 rounded-lg border px-1 pt-2.5 pb-2 transition-all duration-200 hover:-translate-y-0.5"
              style={{ '--tile': look.color } as React.CSSProperties}
            >
              <span className="sb-link-tile-icon grid place-items-center w-8 h-8 rounded-full transition-transform duration-200 group-hover:scale-110">
                {look.icon}
              </span>
              <span className="text-[9.5px] font-mono font-bold tracking-[0.14em] uppercase text-[var(--text-primary)] group-hover:text-white">
                {link.label}
              </span>
            </a>
          );
        })}
      </nav>
      <style>{`
        .sb-link-tile {
          border-color: color-mix(in srgb, var(--tile) 26%, transparent);
          background: linear-gradient(180deg, color-mix(in srgb, var(--tile) 12%, transparent), color-mix(in srgb, var(--tile) 3%, transparent));
        }
        .sb-link-tile:hover, .sb-link-tile:focus-visible {
          border-color: color-mix(in srgb, var(--tile) 70%, transparent);
          box-shadow: 0 0 0 1px color-mix(in srgb, var(--tile) 25%, transparent), 0 6px 18px -8px var(--tile);
          outline: none;
        }
        .sb-link-tile-icon {
          color: var(--tile);
          background: color-mix(in srgb, var(--tile) 16%, transparent);
        }
        @media (prefers-reduced-motion: reduce) {
          .sb-link-tile, .sb-link-tile-icon { transition: none; transform: none !important; }
        }
      `}</style>
    </div>
  );
}

function BrandIcon({ path }: { path: string }) {
  return (
    <svg viewBox="0 0 24 24" width="17" height="17" fill="currentColor" aria-hidden="true">
      <path d={path} />
    </svg>
  );
}

const DISCORD_PATH =
  'M20.317 4.3698a19.7913 19.7913 0 00-4.8851-1.5152.0741.0741 0 00-.0785.0371c-.211.3753-.4447.8648-.6083 1.2495-1.8447-.2762-3.68-.2762-5.4868 0-.1636-.3933-.4058-.8742-.6177-1.2495a.077.077 0 00-.0785-.037 19.7363 19.7363 0 00-4.8852 1.515.0699.0699 0 00-.0321.0277C.5334 9.0458-.319 13.5799.0992 18.0578a.0824.0824 0 00.0312.0561c2.0528 1.5076 4.0413 2.4228 5.9929 3.0294a.0777.0777 0 00.0842-.0276c.4616-.6304.8731-1.2952 1.226-1.9942a.076.076 0 00-.0416-.1057c-.6528-.2476-1.2743-.5495-1.8722-.8923a.077.077 0 01-.0076-.1277c.1258-.0943.2517-.1923.3718-.2914a.0743.0743 0 01.0776-.0105c3.9278 1.7933 8.18 1.7933 12.0614 0a.0739.0739 0 01.0785.0095c.1202.099.246.1981.3728.2924a.077.077 0 01-.0066.1276 12.2986 12.2986 0 01-1.873.8914.0766.0766 0 00-.0407.1067c.3604.698.7719 1.3628 1.225 1.9932a.076.076 0 00.0842.0286c1.961-.6067 3.9495-1.5219 6.0023-3.0294a.077.077 0 00.0313-.0552c.5004-5.177-.8382-9.6739-3.5485-13.6604a.061.061 0 00-.0312-.0286zM8.02 15.3312c-1.1825 0-2.1569-1.0857-2.1569-2.419 0-1.3332.9555-2.4189 2.157-2.4189 1.2108 0 2.1757 1.0952 2.1568 2.419 0 1.3332-.9555 2.4189-2.1569 2.4189zm7.9748 0c-1.1825 0-2.1569-1.0857-2.1569-2.419 0-1.3332.9554-2.4189 2.1569-2.4189 1.2108 0 2.1757 1.0952 2.1568 2.419 0 1.3332-.946 2.4189-2.1568 2.4189Z';
const GITHUB_PATH =
  'M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12';

/** Each tile's accent colour and icon. */
const LINK_LOOK: Record<ViewerLinkId, { color: string; icon: React.ReactNode }> = {
  discord: { color: '#7b88ff', icon: <BrandIcon path={DISCORD_PATH} /> },
  github: { color: '#dbe7f7', icon: <BrandIcon path={GITHUB_PATH} /> },
  discussions: { color: '#45d8ff', icon: <MessagesSquare size={16} aria-hidden="true" /> },
  token: { color: '#2cf5a0', icon: <Coins size={16} aria-hidden="true" /> },
};

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
  { name: 'APRS-IS', what: 'Amateur radio station positions (one region, listen-only)', href: 'https://www.aprs-is.net' },
  { name: 'KiwiSDR / OpenMHZ', what: 'Receiver and scanner locations; you listen on their sites', href: 'http://kiwisdr.com' },
  { name: 'Public traffic agencies', what: 'Road cameras, loaded from each agency directly', href: 'https://github.com/BigBodyCobain/Shadowbroker' },
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
