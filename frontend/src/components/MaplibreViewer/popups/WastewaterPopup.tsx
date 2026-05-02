'use client';

import React from 'react';
import { Popup } from 'react-map-gl/maplibre';
import type { WastewaterPlant } from '@/types/dashboard';

export interface WastewaterPopupProps {
  plant: WastewaterPlant;
  onClose: () => void;
}

const ACTIVITY_COLORS: Record<string, string> = {
  'very high': 'text-red-400',
  high: 'text-red-400',
  'above normal': 'text-amber-400',
  normal: 'text-green-400',
  'below normal': 'text-blue-400',
  low: 'text-blue-300',
  'not calculated': 'text-gray-500',
};

export function WastewaterPopup({ plant, onClose }: WastewaterPopupProps) {
  const hasAlerts = plant.alert_count > 0;
  const borderColor = hasAlerts ? 'border-red-500/50' : 'border-cyan-500/40';

  return (
    <Popup
      longitude={plant.lng}
      latitude={plant.lat}
      closeButton={false}
      closeOnClick={false}
      onClose={onClose}
      anchor="bottom"
      offset={12}
      maxWidth="320px"
    >
      <div className={`map-popup border ${borderColor}`}>
        {/* Header */}
        <div className="flex justify-between items-start mb-2">
          <div className={`map-popup-title ${hasAlerts ? 'text-red-400' : 'text-cyan-400'}`}>
            {hasAlerts ? '!! PATHOGEN ALERT !!' : 'WASTEWATER MONITOR'}
          </div>
          {plant.alert_count > 0 && (
            <span className="text-[11px] font-mono tracking-widest px-1.5 py-0.5 rounded border bg-red-900/50 border-red-500/40 text-red-300">
              {plant.alert_count} ALERT{plant.alert_count > 1 ? 'S' : ''}
            </span>
          )}
        </div>

        {/* Site info */}
        <div className="map-popup-row text-[#8899aa] mb-1">
          SITE: <span className="text-white">{plant.name || plant.site_name}</span>
        </div>
        {plant.city && (
          <div className="map-popup-row text-[#8899aa] mb-1">
            LOCATION: <span className="text-white">{plant.city}, {plant.state}</span>
          </div>
        )}
        {plant.population && (
          <div className="map-popup-row text-[#8899aa] mb-1">
            POP SERVED: <span className="text-white">{plant.population.toLocaleString()}</span>
          </div>
        )}
        {plant.collection_date && (
          <div className="map-popup-row text-[#8899aa] mb-2">
            SAMPLED: <span className="text-white">{plant.collection_date}</span>
          </div>
        )}

        {/* Pathogen levels */}
        {plant.pathogens && plant.pathogens.length > 0 ? (
          <div className="mt-2 pt-2 border-t border-cyan-500/20">
            <div className="text-[11px] font-mono tracking-widest text-cyan-400/60 mb-1.5">PATHOGEN DETECTIONS</div>
            {plant.pathogens.map((p, i) => (
              <div
                key={i}
                className={`flex justify-between items-center text-[10px] mb-1 p-1 rounded border ${
                  p.alert ? 'bg-red-950/30 border-red-500/20' : 'bg-gray-900/30 border-gray-700/20'
                }`}
              >
                <span className={p.alert ? 'text-red-300 font-semibold' : 'text-gray-300'}>
                  {p.name}
                </span>
                <span className={`font-mono ${ACTIVITY_COLORS[p.activity.toLowerCase()] || 'text-gray-400'}`}>
                  {p.activity.toUpperCase()}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <div className="mt-2 pt-2 border-t border-gray-600/20">
            <div className="text-[9px] text-gray-500 text-center">No recent pathogen data available</div>
          </div>
        )}

        {/* Source attribution */}
        <div className="mt-2 pt-1.5 border-t border-[var(--border-primary)]/10">
          <div className="text-[10px] text-[#667788] text-center leading-tight">
            SOURCE: WastewaterSCAN (Stanford / Emory)
          </div>
        </div>
      </div>
    </Popup>
  );
}
