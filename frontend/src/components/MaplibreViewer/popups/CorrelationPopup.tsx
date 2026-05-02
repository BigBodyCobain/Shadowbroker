'use client';

import React, { useState } from 'react';
import { Popup } from 'react-map-gl/maplibre';
import { Trash2 } from 'lucide-react';
import { API_BASE } from '@/lib/api';
import type { CorrelationAlert } from '@/types/dashboard';

export interface CorrelationPopupProps {
  alert: CorrelationAlert;
  onClose: () => void;
}

const TYPE_LABELS: Record<string, { label: string; color: string; border: string }> = {
  contradiction: { label: 'POSSIBLE CONTRADICTION', color: 'text-amber-400', border: 'border-amber-500/50' },
  rf_anomaly: { label: 'RF ANOMALY', color: 'text-gray-400', border: 'border-gray-500/50' },
  military_buildup: { label: 'MILITARY BUILDUP', color: 'text-red-400', border: 'border-red-500/50' },
  infra_cascade: { label: 'INFRASTRUCTURE CASCADE', color: 'text-blue-400', border: 'border-blue-500/50' },
  analysis_zone: { label: 'OPENCLAW ANALYSIS', color: 'text-cyan-400', border: 'border-cyan-500/50' },
};

const CATEGORY_LABELS: Record<string, { label: string; color: string }> = {
  contradiction: { label: 'CONTRADICTION', color: 'text-amber-400' },
  analysis: { label: 'ANALYSIS', color: 'text-cyan-400' },
  warning: { label: 'WARNING', color: 'text-red-400' },
  observation: { label: 'OBSERVATION', color: 'text-blue-400' },
  hypothesis: { label: 'HYPOTHESIS', color: 'text-purple-400' },
};

const CONTEXT_COLORS: Record<string, string> = {
  STRONG: 'text-red-400',
  MODERATE: 'text-amber-400',
  WEAK: 'text-yellow-300',
  DETECTION_GAP: 'text-gray-400',
};

const SEVERITY_BADGES: Record<string, { bg: string; text: string }> = {
  high: { bg: 'bg-red-900/50 border-red-500/40', text: 'text-red-300' },
  medium: { bg: 'bg-amber-900/50 border-amber-500/40', text: 'text-amber-300' },
  low: { bg: 'bg-gray-800/50 border-gray-500/40', text: 'text-gray-300' },
};

export function CorrelationPopup({ alert, onClose }: CorrelationPopupProps) {
  const meta = TYPE_LABELS[alert.type] || TYPE_LABELS.contradiction;
  const sevBadge = SEVERITY_BADGES[alert.severity] || SEVERITY_BADGES.low;
  const isContradiction = alert.type === 'contradiction';
  const isAnalysisZone = alert.type === 'analysis_zone';
  const [deleting, setDeleting] = useState(false);

  const handleDelete = async () => {
    if (!alert.id) return;
    setDeleting(true);
    try {
      await fetch(`${API_BASE}/api/ai/analysis-zones/${encodeURIComponent(alert.id)}`, {
        method: 'DELETE',
        credentials: 'include',
      });
      onClose();
    } catch {
      setDeleting(false);
    }
  };

  return (
    <Popup
      longitude={alert.lng}
      latitude={alert.lat}
      closeButton={false}
      closeOnClick={false}
      onClose={onClose}
      anchor="bottom"
      offset={12}
      maxWidth="360px"
    >
      <div className={`map-popup border ${meta.border}`}>
        {/* Header */}
        <div className="flex justify-between items-start mb-2">
          <div>
            {isAnalysisZone ? (
              <>
                <div className={`map-popup-title ${meta.color}`}>
                  {alert.title || 'OPENCLAW ANALYSIS'}
                </div>
                {alert.category && (
                  <div className="text-[11px] font-mono tracking-widest mt-0.5">
                    <span className={CATEGORY_LABELS[alert.category]?.color || 'text-cyan-400'}>
                      {CATEGORY_LABELS[alert.category]?.label || alert.category.toUpperCase()}
                    </span>
                  </div>
                )}
              </>
            ) : (
              <div className={`map-popup-title ${meta.color}`}>
                !! {meta.label} !!
              </div>
            )}
          </div>
          <div className="flex items-center gap-1.5">
            <span className={`text-[11px] font-mono tracking-widest px-1.5 py-0.5 rounded border ${sevBadge.bg} ${sevBadge.text}`}>
              {isAnalysisZone ? alert.severity?.toUpperCase() : `ALERT LVL ${alert.score}`}
            </span>
            {isAnalysisZone && alert.id && (
              <button
                type="button"
                onClick={handleDelete}
                disabled={deleting}
                className="p-1 text-red-400/60 hover:text-red-400 hover:bg-red-500/10 rounded transition disabled:opacity-50"
                title="Delete this analysis zone"
              >
                <Trash2 size={12} />
              </button>
            )}
          </div>
        </div>

        {/* ── Analysis Zone: Agent report body ── */}
        {isAnalysisZone && alert.body && (
          <div className="mt-2 pt-2 border-t border-cyan-500/20">
            <div className="text-[11px] font-mono tracking-widest text-cyan-500/60 mb-1.5">AGENT ASSESSMENT</div>
            <div className="text-[10px] text-cyan-100/90 leading-relaxed whitespace-pre-wrap">
              {alert.body}
            </div>
          </div>
        )}

        {/* Analysis Zone: Evidence/drivers */}
        {isAnalysisZone && alert.drivers && alert.drivers.length > 0 && (
          <div className="mt-2 pt-2 border-t border-cyan-500/15">
            <div className="text-[11px] font-mono tracking-widest text-cyan-500/50 mb-1.5">KEY INDICATORS</div>
            {alert.drivers.map((driver, i) => (
              <div key={i} className="text-[10px] text-cyan-200/70 mb-0.5 flex items-start gap-1">
                <span className="text-cyan-500">{i + 1}.</span> {driver}
              </div>
            ))}
          </div>
        )}

        {/* Analysis Zone: Source attribution */}
        {isAnalysisZone && (
          <div className="mt-2 pt-1.5 border-t border-cyan-500/10">
            <div className="text-[10px] text-cyan-500/40 text-center">
              Placed by OpenClaw agent — click trash icon to remove
            </div>
          </div>
        )}

        {/* ── Legacy contradiction sections (kept for existing correlation types) ── */}

        {/* Context rating for contradictions */}
        {isContradiction && alert.context && (
          <div className="map-popup-row mb-1">
            <span className="text-[#8899aa]">CONFIDENCE: </span>
            <span className={`font-bold ${CONTEXT_COLORS[alert.context] || 'text-white'}`}>{alert.context}</span>
          </div>
        )}

        {!isAnalysisZone && alert.location_name && (
          <div className="map-popup-row text-[#8899aa] mb-2">
            REGION: <span className="text-white">{alert.location_name}</span>
          </div>
        )}

        {/* Section 1: The Statement/Claim */}
        {isContradiction && alert.headlines && alert.headlines.length > 0 && (
          <div className="mt-2 pt-2 border-t border-amber-500/20">
            <div className="text-[11px] font-mono tracking-widest text-amber-500/60 mb-1.5">OFFICIAL STATEMENT</div>
            {alert.headlines.map((headline, i) => (
              <div key={i} className="text-[10px] text-amber-200/90 leading-relaxed mb-1">
                &ldquo;{headline}&rdquo;
              </div>
            ))}
          </div>
        )}

        {/* Section 2: Contradicting Telemetry */}
        {isContradiction && alert.nearby_outages && alert.nearby_outages.length > 0 && (
          <div className="mt-2 pt-2 border-t border-red-500/20">
            <div className="text-[11px] font-mono tracking-widest text-red-400/60 mb-1.5">CONTRADICTING TELEMETRY</div>
            {alert.nearby_outages.map((outage, i) => (
              <div key={i} className="flex justify-between items-center text-[10px] mb-1 p-1 rounded bg-red-950/30 border border-red-500/20">
                <div>
                  <span className="text-red-300 font-semibold">{outage.region || 'Unknown Region'}</span>
                  <span className="text-[#8899aa] ml-1">({outage.distance_km}km away)</span>
                </div>
                <span className="text-red-400 font-bold">{outage.severity}% outage</span>
              </div>
            ))}
          </div>
        )}

        {/* Section 3: Market Signals */}
        {isContradiction && alert.related_markets && alert.related_markets.length > 0 && (
          <div className="mt-2 pt-2 border-t border-purple-500/20">
            <div className="text-[11px] font-mono tracking-widest text-purple-400/60 mb-1.5">PREDICTION MARKET SIGNALS</div>
            {alert.related_markets.map((market, i) => (
              <div key={i} className="text-[10px] mb-1 p-1 rounded bg-purple-950/30 border border-purple-500/20">
                <div className="text-purple-300">{market.title}</div>
                <div className="text-purple-400 font-bold mt-0.5">{(market.probability * 100).toFixed(0)}% probability</div>
              </div>
            ))}
          </div>
        )}

        {/* Section 4: All Drivers (non-contradiction, non-analysis types) */}
        {!isContradiction && !isAnalysisZone && alert.drivers && alert.drivers.length > 0 && (
          <div className="mt-2 pt-2 border-t border-[var(--border-primary)]/30">
            <div className="text-[11px] font-mono tracking-widest text-[var(--text-muted)] mb-1.5">CORRELATED INDICATORS</div>
            {alert.drivers.map((driver, i) => (
              <div key={i} className="text-[10px] text-[var(--text-primary)] mb-0.5 flex items-start gap-1">
                <span className={meta.color}>+</span> {driver}
              </div>
            ))}
          </div>
        )}

        {/* Drivers summary for contradictions */}
        {isContradiction && alert.drivers && alert.drivers.length > 0 && (
          <div className="mt-2 pt-2 border-t border-[var(--border-primary)]/30">
            <div className="text-[11px] font-mono tracking-widest text-[var(--text-muted)] mb-1.5">EVIDENCE CHAIN</div>
            {alert.drivers.map((driver, i) => (
              <div key={i} className="text-[10px] text-[var(--text-primary)]/80 mb-0.5 flex items-start gap-1">
                <span className="text-amber-500">{i + 1}.</span> {driver}
              </div>
            ))}
          </div>
        )}

        {/* Section 5: Alternative Explanations */}
        {isContradiction && alert.alternatives && alert.alternatives.length > 0 && (
          <div className="mt-2 pt-2 border-t border-[var(--border-primary)]/20">
            <div className="text-[11px] font-mono tracking-widest text-[var(--text-muted)] mb-1.5">ALTERNATIVE EXPLANATIONS</div>
            {alert.alternatives.map((alt, i) => (
              <div key={i} className="text-[9px] text-[#8899aa] mb-0.5 flex items-start gap-1">
                <span className="text-gray-500">-</span> {alt}
              </div>
            ))}
          </div>
        )}

        {/* Disclaimer */}
        {isContradiction && (
          <div className="mt-2 pt-1.5 border-t border-[var(--border-primary)]/10">
            <div className="text-[10px] text-[#667788] text-center leading-tight">
              HYPOTHESIS GENERATOR — NOT A VERDICT. This is a signal for further investigation.
            </div>
          </div>
        )}
      </div>
    </Popup>
  );
}
