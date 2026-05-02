'use client';

import React from 'react';
import { Popup } from 'react-map-gl/maplibre';
import WikiImage from '@/components/WikiImage';
import type { Satellite, SatManeuverAlert } from '@/types/dashboard';

export interface SatellitePopupProps {
  sat: Satellite;
  maneuverAlert?: SatManeuverAlert;
  onClose: () => void;
}

const MISSION_LABELS: Record<string, string> = {
  military_recon: '🔴 MILITARY RECON',
  military_sar: '🔴 MILITARY SAR',
  military_comms: '🔴 MILITARY COMMS',
  sar: '🔷 SAR IMAGING',
  sigint: '🟠 SIGINT / ELINT',
  navigation: '🔵 NAVIGATION',
  early_warning: '🟣 EARLY WARNING',
  commercial_imaging: '🟢 COMMERCIAL IMAGING',
  space_station: '🏠 SPACE STATION',
  starlink: '🌐 STARLINK',
  constellation: '🌐 CONSTELLATION',
  communication: '📡 COMMUNICATION',
};

export function SatellitePopup({ sat, maneuverAlert, onClose }: SatellitePopupProps) {
  const isISS = sat.mission === 'space_station' && sat.name?.includes('ISS');

  return (
    <Popup
      longitude={sat.lng}
      latitude={sat.lat}
      closeButton={false}
      closeOnClick={false}
      onClose={onClose}
      anchor="bottom"
      offset={isISS ? 20 : 12}
      maxWidth={isISS ? '320px' : '260px'}
    >
      <div className={`map-popup ${isISS ? 'border border-yellow-500/50' : 'border border-cyan-500/30'}`}>
        <div className="flex justify-between items-start">
          <div className={`map-popup-title ${isISS ? 'text-[#ffdd00]' : 'text-[#00c8ff]'}`}>
            🛰️ {sat.name}
          </div>
          {isISS && (
            <span className="text-[11px] font-mono tracking-widest text-yellow-500/80 border border-yellow-500/30 px-1 rounded">LIVE</span>
          )}
        </div>
        <div className="map-popup-row text-[#8899aa]">
          NORAD ID: <span className="text-white">{sat.id}</span>
        </div>
        {sat.sat_type && (
          <div className="map-popup-row">
            Type: <span className="text-[#ffcc00]">{sat.sat_type}</span>
          </div>
        )}
        {sat.country && (
          <div className="map-popup-row">
            Country: <span className="text-white">{sat.country}</span>
          </div>
        )}
        {sat.mission && (
          <div className="map-popup-row font-semibold">
            {MISSION_LABELS[sat.mission] || `⚪ ${sat.mission.toUpperCase()}`}
          </div>
        )}
        <div className="map-popup-row">
          Altitude:{' '}
          <span className="text-[#44ff88]">{sat.alt_km?.toLocaleString()} km</span>
        </div>
        {maneuverAlert && (
          <div className="mt-1.5 p-1.5 rounded bg-red-900/30 border border-red-500/40">
            <div className="text-[11px] font-mono tracking-widest text-red-400 mb-0.5">MANEUVER DETECTED</div>
            {maneuverAlert.reasons.map((r, i) => (
              <div key={i} className="text-[9px] text-red-300/80 font-mono">{r}</div>
            ))}
          </div>
        )}
        {isISS && (
          <div className="map-popup-row text-[#8899aa]">
            Speed: <span className="text-white">{sat.speed_knots ? `${Math.round(sat.speed_knots * 1.852).toLocaleString()} km/h` : '~28,000 km/h'}</span>
          </div>
        )}
        {isISS && (
          <div className="mt-2 pt-2 border-t border-yellow-500/20">
            <div className="text-[11px] font-mono tracking-widest text-yellow-500/60 mb-1.5">NASA EHDC LIVE FEED</div>
            <div className="relative w-full rounded overflow-hidden bg-black/60" style={{ paddingBottom: '56.25%' }}>
              <iframe
                src="https://video.ibm.com/embed/17074538?autoplay=0&html5ui"
                className="absolute inset-0 w-full h-full"
                allow="autoplay"
                allowFullScreen
                style={{ border: 'none' }}
              />
            </div>
            <div className="text-[10px] text-[#8899aa] mt-1 text-center">
              Earth view from ISS external cameras • Dark = nightside pass
            </div>
          </div>
        )}
        {sat.wiki && !isISS && (
          <div className="mt-2 border-t border-[var(--border-primary)]/50 pt-2">
            <WikiImage
              wikiUrl={sat.wiki}
              label={sat.sat_type || sat.name}
              maxH="max-h-28"
              accent="hover:border-cyan-500/50"
            />
          </div>
        )}
        {isISS && sat.wiki && (
          <div className="mt-1.5">
            <a href={sat.wiki} target="_blank" rel="noopener noreferrer"
              className="block text-center px-2 py-1 rounded bg-yellow-900/30 border border-yellow-500/20
                hover:bg-yellow-800/40 hover:border-yellow-400/40 text-yellow-300 text-[9px] font-mono tracking-widest">
              WIKIPEDIA ↗
            </a>
          </div>
        )}
      </div>
    </Popup>
  );
}
