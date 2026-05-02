'use client';

import React from 'react';
import { Popup } from 'react-map-gl/maplibre';
import { AlertTriangle, Radio, Play } from 'lucide-react';
import { SigintSendForm, MeshtasticChannelFeed } from '@/components/map/panels/SigintPanels';
import type { KiwiSDR, SigintSignal } from '@/types/dashboard';

type GeoExtras = {
  lat?: number;
  lng?: number;
  lon?: number;
  geometry?: { coordinates?: [number, number] };
};

export type SigintData = Partial<SigintSignal> & GeoExtras;

export interface SigintPopupProps {
  data: SigintData;
  lat: number;
  lng: number;
  kiwisdrs: KiwiSDR[];
  setTrackedSdr?: (sdr: {
    lat: number;
    lon: number;
    name: string;
    url?: string;
    users?: number;
    users_max?: number;
    bands?: string;
    antenna?: string;
    location?: string;
  }) => void;
  onClose: () => void;
}

const SOURCE_COLORS: Record<string, string> = {
  aprs: '#ff69b4',
  meshtastic: '#22c55e',
  js8call: '#ff69b4',
};

const SOURCE_LABELS: Record<string, string> = {
  aprs: 'APRS-IS',
  meshtastic: 'MESHTASTIC',
  js8call: 'JS8CALL',
};

function computePosAge(d: SigintData): string | null {
  const ts = d.position_updated_at || d.timestamp;
  if (!ts) return null;
  try {
    const then = new Date(ts).getTime();
    const diffMs = Date.now() - then;
    if (diffMs < 0 || isNaN(diffMs)) return null;
    const mins = Math.floor(diffMs / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    const days = Math.floor(hrs / 24);
    return `${days}d ago`;
  } catch {
    return null;
  }
}

function findNearestSdr(
  src: string,
  lat: number,
  lng: number,
  sdrs: KiwiSDR[],
): KiwiSDR | null {
  if (src === 'meshtastic') return null;
  if (!sdrs || !sdrs.length) return null;
  let best: KiwiSDR | null = null;
  let bestDist = Infinity;
  for (const sdr of sdrs) {
    const slat = sdr.lat;
    const slng = sdr.lon;
    if (slat == null || slng == null || !sdr.url) continue;
    const dist = Math.sqrt((lat - slat) ** 2 + (lng - slng) ** 2);
    if (dist < bestDist) {
      bestDist = dist;
      best = sdr;
    }
  }
  return best;
}

export function SigintPopup({ data: d, lat, lng, kiwisdrs, setTrackedSdr, onClose }: SigintPopupProps) {
  const src = d.source || 'unknown';
  const isEmergency = d.emergency === true;
  const color = isEmergency ? '#ef4444' : SOURCE_COLORS[src] || '#94a3b8';
  const stationType = d.station_type || 'Station';
  const status = d.status || d.comment || '';
  const isApiNode = d.from_api === true;
  const posAge = computePosAge(d);
  const nearestSdr = findNearestSdr(src, lat, lng, kiwisdrs);

  return (
    <Popup
      longitude={lng}
      latitude={lat}
      closeButton={false}
      closeOnClick={false}
      onClose={onClose}
      anchor="bottom"
      offset={12}
    >
      <div
        className="map-popup"
        style={{ borderWidth: 1, borderStyle: 'solid', borderColor: `${color}66` }}
      >
        <div className="flex justify-between items-start mb-1">
          <div className="map-popup-title" style={{ color }}>
            {isEmergency && (
              <AlertTriangle
                size={12}
                className="inline mr-1 animate-pulse"
                style={{ color: '#ef4444' }}
              />
            )}
            {(d.callsign || 'UNKNOWN').toUpperCase()}
          </div>
          <button
            onClick={onClose}
            className="text-[var(--text-secondary)] hover:text-[var(--text-primary)] ml-2"
          >
            ✕
          </button>
        </div>
        <div
          className="map-popup-subtitle border-b pb-1 flex items-center gap-1.5 flex-wrap"
          style={{ color: `${color}99`, borderColor: `${color}30` }}
        >
          <Radio size={10} />
          <span
            className="font-mono text-[12px] px-1.5 py-0.5 rounded"
            style={{ backgroundColor: `${color}20`, color }}
          >
            {SOURCE_LABELS[src] || src.toUpperCase()}
          </span>
          <span className="text-[var(--text-muted)]">{stationType}</span>
          {isEmergency && (
            <span className="font-mono text-[11px] px-1.5 py-0.5 rounded bg-red-900/60 text-red-400 animate-pulse tracking-wider">
              EMERGENCY
            </span>
          )}
          {src === 'meshtastic' && d.channel && (
            <span className="font-mono text-[11px] px-1.5 py-0.5 rounded bg-green-900/50 text-green-300 border border-green-500/30">
              {d.channel}
            </span>
          )}
          {src === 'meshtastic' && d.region && (
            <span className="font-mono text-[11px] px-1.5 py-0.5 rounded bg-slate-800/60 text-slate-300 border border-slate-500/30">
              {d.region}
            </span>
          )}
          {isApiNode && (
            <span className="font-mono text-[11px] px-1.5 py-0.5 rounded bg-blue-900/40 text-blue-300 border border-blue-500/30">
              MAP API
            </span>
          )}
        </div>

        {/* Long name + hardware (API nodes) */}
        {src === 'meshtastic' && (d.long_name || d.hardware) && (
          <div className="map-popup-row mt-0.5 flex items-center gap-1.5 flex-wrap">
            {d.long_name && <span className="text-[13px] text-white">{d.long_name}</span>}
            {d.hardware && (
              <span className="text-[11px] text-slate-400">({d.hardware})</span>
            )}
            {d.role && d.role !== 'CLIENT' && (
              <span className="font-mono text-[11px] px-1 py-0.5 rounded bg-amber-900/40 text-amber-300 border border-amber-500/30">
                {d.role}
              </span>
            )}
          </div>
        )}

        {/* Position age */}
        {posAge && (
          <div className="map-popup-row mt-0.5">
            <span className="text-[12px] text-[var(--text-muted)]">
              Last heard: <span className="text-slate-300">{posAge}</span>
            </span>
          </div>
        )}

        {/* Status */}
        {status && (
          <div className="map-popup-row mt-1">
            <span
              className={`text-[13px] ${isEmergency ? 'text-red-300 font-bold' : 'text-white'}`}
            >
              {status}
            </span>
          </div>
        )}

        {/* Key telemetry */}
        <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 mt-1">
          {d.frequency && (
            <div className="map-popup-row">
              Freq: <span className="text-cyan-400">{d.frequency}</span>
            </div>
          )}
          {(d.altitude_ft ?? 0) > 0 && (
            <div className="map-popup-row">
              Alt:{' '}
              <span className="text-white">
                {Number(d.altitude_ft).toLocaleString()} ft
              </span>
            </div>
          )}
          {(d.speed_knots ?? 0) > 0 && (
            <div className="map-popup-row">
              Speed:{' '}
              <span className="text-white">
                {d.speed_knots} kts / {d.course || 0}°
              </span>
            </div>
          )}
          {(d.power_watts ?? 0) > 0 && (
            <div className="map-popup-row">
              TX Power: <span className="text-amber-400">{d.power_watts}W</span>
            </div>
          )}
          {(d.battery_v ?? 0) > 0 && (
            <div className="map-popup-row">
              Battery: <span className="text-white">{d.battery_v}V</span>
            </div>
          )}
          {!d.battery_v && d.battery_level != null && d.battery_level <= 100 && (
            <div className="map-popup-row">
              Battery: <span className="text-white">{d.battery_level}%</span>
            </div>
          )}
          {d.snr != null && (
            <div className="map-popup-row">
              SNR: <span className="text-white">{d.snr} dB</span>
            </div>
          )}
        </div>

        {/* Action buttons: Tune In via nearest KiwiSDR */}
        <div className="flex items-center gap-2 mt-2 pt-1.5 border-t border-[var(--border-primary)]/30">
          {nearestSdr?.url && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                if (setTrackedSdr) {
                  setTrackedSdr({
                    lat: nearestSdr.lat,
                    lon: nearestSdr.lon,
                    name: nearestSdr.name,
                    url: nearestSdr.url,
                    users: nearestSdr.users,
                    users_max: nearestSdr.users_max,
                    bands: nearestSdr.bands,
                    antenna: nearestSdr.antenna,
                    location: nearestSdr.location,
                  });
                }
                onClose();
              }}
              className="flex-1 text-center px-2 py-1.5 rounded bg-cyan-950/40 border border-cyan-500/30 hover:bg-cyan-900/60 hover:border-cyan-400 text-cyan-400 text-[12px] font-mono tracking-widest transition-colors flex justify-center items-center gap-1.5"
              title={`Listen via ${nearestSdr.name}`}
            >
              <Play size={10} className="fill-cyan-400/20" /> TUNE IN
            </button>
          )}
          <span className="text-[#666] text-[12px]">
            {Number(lat).toFixed(4)}, {Number(lng).toFixed(4)}
          </span>
        </div>
        {nearestSdr && (
          <div className="text-[11px] text-[#555] mt-0.5">
            via {nearestSdr.name} ({nearestSdr.location || 'SDR'})
          </div>
        )}

        {/* Meshtastic channel feed */}
        {src === 'meshtastic' && d.region && (
          <MeshtasticChannelFeed region={d.region} channel={d.channel || 'LongFast'} />
        )}

        {/* Send Message */}
        {src === 'meshtastic' && (
          <SigintSendForm
            destination={
              typeof d.callsign === 'string' && /^![0-9a-f]{8}$/i.test(d.callsign)
                ? d.callsign
                : d.channel || 'LongFast'
            }
            source={src}
            region={d.region}
            channel={d.channel || 'LongFast'}
          />
        )}
        {src === 'aprs' && (
          <div className="mt-2 pt-1.5 border-t border-[var(--border-primary)]/30 text-[11px] text-[#555] italic">
            APRS is receive-only — transmitting requires a ham radio license
          </div>
        )}
      </div>
    </Popup>
  );
}
