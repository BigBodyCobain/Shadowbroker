'use client';

import React from 'react';
import { Popup } from 'react-map-gl/maplibre';
import WikiImage from '@/components/WikiImage';
import type { MilitaryBase } from '@/types/dashboard';

export interface OracleIntel {
  found: boolean;
  top_headline?: string;
  oracle_score?: number;
  tier?: string;
  avg_sentiment?: number;
  nearby_count?: number;
  market?: { title: string; consensus_pct: number | null } | null;
}

export interface MilitaryBasePopupProps {
  base: MilitaryBase;
  oracleIntel: OracleIntel | null;
  onClose: () => void;
}

const BRANCH_LABELS: Record<string, string> = {
  air_force: 'AIR FORCE',
  navy: 'NAVY',
  marines: 'MARINES',
  army: 'ARMY',
  gsdf: 'GSDF',
  msdf: 'MSDF',
  asdf: 'ASDF',
  missile: 'MISSILE FORCES',
  nuclear: 'NUCLEAR FACILITY',
};

const COLOR_MAP: Record<string, string> = {
  'United States': '#3b82f6',
  'Guam': '#3b82f6',
  'Hawaii': '#3b82f6',
  'BIOT': '#3b82f6',
  'China': '#ef4444',
  'Japan': '#e5e7eb',
  'North Korea': '#92400e',
  'Russia': '#9ca3af',
  'Iran': '#f97316',
  'Taiwan': '#22c55e',
  'Philippines': '#eab308',
  'Australia': '#14b8a6',
  'South Korea': '#a855f7',
  'United Kingdom': '#6366f1',
};

export function MilitaryBasePopup({ base, oracleIntel, onClose }: MilitaryBasePopupProps) {
  const accent = COLOR_MAP[base.country] || '#ec4899';
  const wikiSlug = encodeURIComponent(base.name.replace(/ /g, '_'));
  const wikiUrl = `https://en.wikipedia.org/wiki/${wikiSlug}`;

  return (
    <Popup
      longitude={base.lng}
      latitude={base.lat}
      closeButton={false}
      closeOnClick={false}
      onClose={onClose}
      className="threat-popup"
      maxWidth="340px"
    >
      <div
        className="map-popup bg-[#1a1035] min-w-[220px]"
        style={{ borderColor: `${accent}66`, color: accent }}
      >
        <div className="flex justify-between items-start">
          <div
            className="map-popup-title pb-1 flex-1"
            style={{ color: accent, borderBottom: `1px solid ${accent}33` }}
          >
            {base.name}
          </div>
          <button
            onClick={onClose}
            className="text-[var(--text-secondary)] hover:text-[var(--text-primary)] ml-2 shrink-0"
          >
            ✕
          </button>
        </div>
        <div className="map-popup-row">
          Operator:{' '}
          <a
            href={`https://en.wikipedia.org/wiki/${encodeURIComponent(base.operator.replace(/ /g, '_'))}`}
            target="_blank"
            rel="noopener noreferrer"
            className="text-cyan-400 hover:text-cyan-300 underline"
          >
            {base.operator}
          </a>
        </div>
        <div className="map-popup-row">
          Country: <span className="text-white">{base.country}</span>
        </div>

        {/* Wikipedia image + link — same style as tracked aircraft */}
        <div className="border-b border-[var(--border-primary)] pb-2 mt-2">
          <WikiImage
            wikiUrl={wikiUrl}
            label={base.name}
            maxH="max-h-36"
            accent={`hover:border-[${accent}]`}
          />
        </div>

        <div className="mt-1.5 text-[12px] tracking-wider" style={{ color: `${accent}99` }}>
          MILITARY BASE — {BRANCH_LABELS[base.branch] || base.branch.toUpperCase()}
        </div>

        {oracleIntel?.found && (
          <div className="mt-2 pt-2 border-t border-cyan-500/20">
            <div className="text-[11px] font-mono text-cyan-400 tracking-wider mb-1">
              ORACLE INTEL
            </div>
            <div className="text-[11px] font-mono text-cyan-300/80">
              <span
                className={
                  oracleIntel.tier === 'CRITICAL'
                    ? 'text-red-400'
                    : oracleIntel.tier === 'ELEVATED'
                      ? 'text-yellow-400'
                      : 'text-green-400'
                }
              >
                {oracleIntel.tier}
              </span>
              {' // '}
              <span
                className={
                  oracleIntel.avg_sentiment != null && oracleIntel.avg_sentiment < -0.05
                    ? 'text-red-400'
                    : 'text-gray-400'
                }
              >
                {oracleIntel.avg_sentiment != null
                  ? `${oracleIntel.avg_sentiment > 0 ? '+' : ''}${oracleIntel.avg_sentiment.toFixed(2)} SENT`
                  : ''}
              </span>
              {oracleIntel.market && (
                <span className="text-purple-400">
                  {' '}
                  // {oracleIntel.market.consensus_pct}%
                </span>
              )}
            </div>
            {oracleIntel.top_headline && (
              <div className="text-[10px] text-white/60 mt-0.5 truncate">
                {oracleIntel.top_headline}
              </div>
            )}
          </div>
        )}
      </div>
    </Popup>
  );
}
