'use client';

import React, { useState } from 'react';
import ExternalImage from '@/components/ExternalImage';

export interface Sentinel2Data {
  found: boolean;
  fullres_url?: string;
  thumbnail_url?: string;
  platform?: string;
  datetime?: string;
  cloud_cover?: number;
  fallback?: boolean;
  scenes?: Sentinel2Data[];
}

export interface RegionDossierPanelProps {
  sentinel2: Sentinel2Data;
  lat: number;
  lng: number;
  onClose: () => void;
}

const NAV_BTN: React.CSSProperties = {
  background: 'rgba(34,197,94,0.2)',
  border: '1px solid rgba(34,197,94,0.5)',
  borderRadius: 6,
  color: '#4ade80',
  fontSize: 12,
  fontFamily: 'monospace',
  padding: '6px 14px',
  cursor: 'pointer',
  letterSpacing: '0.1em',
  fontWeight: 'bold',
};

const NAV_BTN_DISABLED: React.CSSProperties = {
  ...NAV_BTN,
  opacity: 0.3,
  cursor: 'default',
};

const ACTION_BTN: React.CSSProperties = {
  background: 'rgba(34,197,94,0.2)',
  border: '1px solid rgba(34,197,94,0.5)',
  borderRadius: 6,
  color: '#4ade80',
  fontSize: 11,
  fontFamily: 'monospace',
  padding: '6px 16px',
  cursor: 'pointer',
  textDecoration: 'none',
  letterSpacing: '0.15em',
  fontWeight: 'bold',
};

export function RegionDossierPanel({ sentinel2: s2, lat, lng, onClose }: RegionDossierPanelProps) {
  const scenes = s2.scenes?.length ? s2.scenes : [s2];
  const [idx, setIdx] = useState(0);
  const scene = scenes[idx] || s2;
  const imgUrl = scene.fullres_url || scene.thumbnail_url;
  const hasMultiple = scenes.length > 1;

  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        zIndex: 9999,
        background: 'rgba(0,0,0,0.85)',
        backdropFilter: 'blur(8px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '80px 40px 80px 40px',
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      onKeyDown={(e: React.KeyboardEvent<HTMLDivElement>) => {
        if (e.key === 'Escape') onClose();
        if (hasMultiple && e.key === 'ArrowLeft' && idx > 0) setIdx(idx - 1);
        if (hasMultiple && e.key === 'ArrowRight' && idx < scenes.length - 1) setIdx(idx + 1);
      }}
      tabIndex={-1}
      ref={(el) => el?.focus()}
    >
      <div
        style={{
          background: 'rgba(0,0,0,0.95)',
          border: '1px solid rgba(34,197,94,0.5)',
          borderRadius: 12,
          overflow: 'hidden',
          maxWidth: 'calc(100vw - 120px)',
          maxHeight: 'calc(100vh - 160px)',
          display: 'flex',
          flexDirection: 'column',
          boxShadow: '0 0 60px rgba(34,197,94,0.3)',
        }}
      >
        {/* Header bar */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '10px 16px',
            background: 'rgba(20,83,45,0.4)',
            borderBottom: '1px solid rgba(34,197,94,0.3)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div
              style={{
                width: 6,
                height: 6,
                borderRadius: '50%',
                background: '#4ade80',
                animation: 'pulse 2s infinite',
              }}
            />
            <span
              style={{
                fontSize: 12,
                color: '#4ade80',
                fontFamily: 'monospace',
                letterSpacing: '0.2em',
                fontWeight: 'bold',
              }}
            >
              SENTINEL-2 IMAGERY
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span
              style={{
                fontSize: 11,
                color: 'rgba(134,239,172,0.6)',
                fontFamily: 'monospace',
              }}
            >
              {lat.toFixed(4)}, {lng.toFixed(4)}
            </span>
            <button
              onClick={onClose}
              style={{
                background: 'rgba(239,68,68,0.2)',
                border: '1px solid rgba(239,68,68,0.4)',
                borderRadius: 6,
                color: '#ef4444',
                fontSize: 11,
                fontFamily: 'monospace',
                padding: '4px 10px',
                cursor: 'pointer',
                letterSpacing: '0.1em',
              }}
            >
              ✕ CLOSE
            </button>
          </div>
        </div>

        {scene.found ? (
          <>
            {/* Metadata row with scene navigation */}
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '8px 16px',
                fontSize: 12,
                fontFamily: 'monospace',
                borderBottom: '1px solid rgba(20,83,45,0.4)',
              }}
            >
              <span style={{ color: '#86efac' }}>{scene.platform}</span>

              {hasMultiple ? (
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <button
                    onClick={() => idx > 0 && setIdx(idx - 1)}
                    disabled={idx === 0}
                    style={idx === 0 ? NAV_BTN_DISABLED : NAV_BTN}
                  >
                    ← PREV
                  </button>
                  <span style={{ color: '#4ade80', fontWeight: 'bold', minWidth: 120, textAlign: 'center' }}>
                    {scene.datetime?.slice(0, 10) || 'UNKNOWN DATE'}
                  </span>
                  <button
                    onClick={() => idx < scenes.length - 1 && setIdx(idx + 1)}
                    disabled={idx === scenes.length - 1}
                    style={idx === scenes.length - 1 ? NAV_BTN_DISABLED : NAV_BTN}
                  >
                    NEXT →
                  </button>
                  <span style={{ color: 'rgba(134,239,172,0.5)', fontSize: 10 }}>
                    {idx + 1}/{scenes.length}
                  </span>
                </div>
              ) : (
                <span style={{ color: '#4ade80', fontWeight: 'bold' }}>
                  {scene.datetime?.slice(0, 10) ||
                    (scene.fallback ? 'DATE UNAVAILABLE' : 'UNKNOWN DATE')}
                </span>
              )}

              <span style={{ color: '#86efac' }}>
                {scene.cloud_cover != null
                  ? `${scene.cloud_cover?.toFixed(0)}% cloud`
                  : scene.fallback
                    ? 'fallback imagery'
                    : 'cloud unknown'}
              </span>
            </div>

            {/* Image */}
            {imgUrl ? (
              <div
                style={{
                  flex: 1,
                  overflow: 'auto',
                  display: 'flex',
                  justifyContent: 'center',
                  alignItems: 'center',
                  minHeight: 400,
                }}
              >
                <ExternalImage
                  src={imgUrl}
                  alt="Sentinel-2 scene"
                  width={1024}
                  height={1024}
                  style={{
                    maxWidth: '100%',
                    maxHeight: 'calc(100vh - 260px)',
                    objectFit: 'contain',
                    display: 'block',
                  }}
                />
              </div>
            ) : (
              <div
                style={{
                  padding: '40px 16px',
                  fontSize: 12,
                  color: 'rgba(134,239,172,0.5)',
                  fontFamily: 'monospace',
                  textAlign: 'center',
                }}
              >
                Scene found — no preview available
              </div>
            )}

            {/* Action buttons */}
            {imgUrl && (
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: 12,
                  padding: '10px 16px',
                  background: 'rgba(20,83,45,0.3)',
                  borderTop: '1px solid rgba(34,197,94,0.2)',
                }}
              >
                <a
                  href={imgUrl}
                  download={`sentinel2_${lat.toFixed(4)}_${lng.toFixed(4)}_${scene.datetime?.slice(0, 10) || 'unknown'}.jpg`}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={ACTION_BTN}
                >
                  ⬇ DOWNLOAD
                </a>
                <button
                  onClick={async () => {
                    try {
                      const resp = await fetch(imgUrl);
                      const blob = await resp.blob();
                      await navigator.clipboard.write([
                        new ClipboardItem({ [blob.type]: blob }),
                      ]);
                    } catch {
                      await navigator.clipboard.writeText(imgUrl);
                    }
                  }}
                  style={{ ...ACTION_BTN, background: 'rgba(34,197,94,0.15)', borderColor: 'rgba(34,197,94,0.4)' }}
                >
                  📋 COPY
                </button>
                <a
                  href={imgUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{ ...ACTION_BTN, color: '#10b981', background: 'rgba(16,185,129,0.15)', borderColor: 'rgba(16,185,129,0.4)' }}
                >
                  ↗ OPEN FULL RES
                </a>
              </div>
            )}
          </>
        ) : (
          <div
            style={{
              padding: '40px 16px',
              fontSize: 12,
              color: 'rgba(134,239,172,0.5)',
              fontFamily: 'monospace',
              textAlign: 'center',
            }}
          >
            No clear imagery in last 30 days
          </div>
        )}
      </div>
    </div>
  );
}
