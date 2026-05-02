'use client';

import React, { useState, useCallback, useRef } from 'react';
import { AlertTriangle, Play, Pause } from 'lucide-react';
import HlsVideo, { type HlsVideoHandle } from '@/components/HlsVideo';

export interface CctvFullscreenModalProps {
  url: string;
  mediaType: string;
  isVideo: boolean;
  cameraName: string;
  sourceAgency: string;
  cameraId: string;
  onClose: () => void;
}

export function CctvFullscreenModal({
  url,
  mediaType,
  isVideo,
  cameraName,
  sourceAgency,
  cameraId,
  onClose,
}: CctvFullscreenModalProps) {
  const [paused, setPaused] = useState(false);
  const [mediaError, setMediaError] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);
  const hlsRef = useRef<HlsVideoHandle>(null);

  const togglePlay = useCallback(() => {
    if (mediaType === 'hls') {
      if (hlsRef.current?.paused) hlsRef.current.play();
      else hlsRef.current?.pause();
      setPaused(!hlsRef.current?.paused);
    } else if (videoRef.current) {
      if (videoRef.current.paused) videoRef.current.play();
      else videoRef.current.pause();
      setPaused(videoRef.current.paused);
    }
  }, [mediaType]);

  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        zIndex: 9999,
        background: 'rgba(0,0,0,0.88)',
        backdropFilter: 'blur(8px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '60px 20px 80px 20px',
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      onKeyDown={(e: React.KeyboardEvent<HTMLDivElement>) => {
        if (e.key === 'Escape') onClose();
      }}
      tabIndex={-1}
      ref={(el) => el?.focus()}
    >
      <div
        style={{
          background: 'rgba(0,0,0,0.95)',
          border: '1px solid rgba(8,145,178,0.5)',
          borderRadius: 12,
          overflow: 'hidden',
          maxWidth: 'calc(100vw - 40px)',
          maxHeight: 'calc(100vh - 80px)',
          width: 900,
          display: 'flex',
          flexDirection: 'column',
          boxShadow: '0 0 60px rgba(8,145,178,0.25), inset 0 0 30px rgba(0,0,0,0.5)',
        }}
      >
        {/* Header */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '10px 16px',
            background: 'rgba(8,51,68,0.4)',
            borderBottom: '1px solid rgba(8,145,178,0.3)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <AlertTriangle size={12} style={{ color: '#ef4444' }} />
            <span
              style={{
                fontSize: 11,
                color: '#22d3ee',
                fontFamily: 'monospace',
                letterSpacing: '0.2em',
                fontWeight: 'bold',
              }}
            >
              OPTIC INTERCEPT
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span
              style={{
                fontSize: 10,
                color: 'rgba(8,145,178,0.6)',
                fontFamily: 'monospace',
              }}
            >
              ID: {cameraId}
            </span>
            <button
              onClick={onClose}
              style={{
                background: 'rgba(239,68,68,0.2)',
                border: '1px solid rgba(239,68,68,0.4)',
                borderRadius: 6,
                color: '#ef4444',
                fontSize: 10,
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

        {/* Metadata row */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '8px 16px',
            fontSize: 10,
            fontFamily: 'monospace',
            borderBottom: '1px solid rgba(8,51,68,0.5)',
          }}
        >
          <span style={{ color: '#22d3ee', letterSpacing: '0.15em' }}>{sourceAgency}</span>
          <span style={{ color: '#ef4444', letterSpacing: '0.1em', fontWeight: 'bold' }}>
            REC // {new Date().toLocaleTimeString('en-GB', { hour12: false })}
          </span>
          <span
            style={{
              color: 'rgba(8,145,178,0.7)',
              letterSpacing: '0.1em',
              background: 'rgba(8,145,178,0.1)',
              border: '1px solid rgba(8,145,178,0.2)',
              borderRadius: 4,
              padding: '2px 8px',
            }}
          >
            {mediaType.toUpperCase()}
          </span>
        </div>

        {/* Media area */}
        <div
          style={{
            flex: 1,
            position: 'relative',
            background: '#000',
            display: 'flex',
            justifyContent: 'center',
            alignItems: 'center',
            minHeight: 400,
            overflow: 'hidden',
          }}
        >
          {url ? (
            <>
              {mediaType === 'video' && !mediaError && (
                <video
                  ref={videoRef}
                  src={url}
                  autoPlay
                  loop
                  muted
                  playsInline
                  onError={() => setMediaError(true)}
                  style={{
                    maxWidth: '100%',
                    maxHeight: 'calc(100vh - 260px)',
                    objectFit: 'contain',
                    filter: 'contrast(1.25) saturate(0.5)',
                  }}
                />
              )}
              {mediaType === 'hls' && !mediaError && (
                <HlsVideo
                  ref={hlsRef}
                  url={url}
                  onError={() => setMediaError(true)}
                  className=""
                />
              )}
              {mediaType === 'mjpeg' && (
                <img
                  src={url}
                  alt="MJPEG Feed"
                  style={{
                    maxWidth: '100%',
                    maxHeight: 'calc(100vh - 260px)',
                    objectFit: 'contain',
                    filter: 'contrast(1.25) saturate(0.5)',
                  }}
                  onError={(e) => {
                    (e.target as HTMLImageElement).style.display = 'none';
                  }}
                />
              )}
              {(mediaType === 'image' || mediaType === 'satellite') && (
                <img
                  src={url}
                  alt="CCTV Feed"
                  style={{
                    maxWidth: '100%',
                    maxHeight: 'calc(100vh - 260px)',
                    objectFit: 'contain',
                    filter: 'contrast(1.25) saturate(0.5)',
                  }}
                  onError={(e) => {
                    const target = e.target as HTMLImageElement;
                    target.style.display = 'none';
                  }}
                />
              )}

              {/* Media error fallback */}
              {mediaError && (
                <div style={{ fontSize: 11, color: 'rgba(239,68,68,0.7)', fontFamily: 'monospace', letterSpacing: '0.15em', textAlign: 'center', padding: 40 }}>
                  FEED UNAVAILABLE<br />
                  <span style={{ fontSize: 9, color: 'rgba(148,163,184,0.5)' }}>stream failed to load — source may be offline</span>
                </div>
              )}

              {/* REC overlay */}
              <div
                style={{
                  position: 'absolute',
                  top: 12,
                  left: 14,
                  fontSize: 9,
                  color: '#22d3ee',
                  background: 'rgba(0,0,0,0.6)',
                  padding: '2px 6px',
                  fontFamily: 'monospace',
                  letterSpacing: '0.1em',
                  borderRadius: 2,
                }}
              >
                REC // 00:00:00:00
              </div>

              {/* Play/Pause overlay for video streams */}
              {isVideo && (
                <button
                  onClick={togglePlay}
                  style={{
                    position: 'absolute',
                    bottom: 14,
                    right: 14,
                    width: 40,
                    height: 40,
                    borderRadius: '50%',
                    background: 'rgba(0,0,0,0.7)',
                    border: '1px solid rgba(8,145,178,0.5)',
                    color: '#22d3ee',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    cursor: 'pointer',
                    transition: 'all 0.2s',
                  }}
                  onMouseEnter={(e) => {
                    (e.target as HTMLElement).style.background = 'rgba(8,51,68,0.8)';
                  }}
                  onMouseLeave={(e) => {
                    (e.target as HTMLElement).style.background = 'rgba(0,0,0,0.7)';
                  }}
                >
                  {paused ? <Play size={18} /> : <Pause size={18} />}
                </button>
              )}
            </>
          ) : (
            <div
              style={{
                fontSize: 12,
                color: 'rgba(8,145,178,0.4)',
                fontFamily: 'monospace',
                letterSpacing: '0.2em',
              }}
            >
              NO SIGNAL
            </div>
          )}
        </div>

        {/* Location bar */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '10px 16px',
            background: 'rgba(8,51,68,0.3)',
            borderTop: '1px solid rgba(8,145,178,0.2)',
          }}
        >
          <span
            style={{
              fontSize: 10,
              color: '#22d3ee',
              fontFamily: 'monospace',
              letterSpacing: '0.15em',
              fontWeight: 'bold',
            }}
          >
            {cameraName}
          </span>
          <div style={{ display: 'flex', gap: 10 }}>
            {url && (
              <>
                <a
                  href={url}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{
                    background: 'rgba(8,145,178,0.2)',
                    border: '1px solid rgba(8,145,178,0.5)',
                    borderRadius: 6,
                    color: '#22d3ee',
                    fontSize: 10,
                    fontFamily: 'monospace',
                    padding: '5px 14px',
                    cursor: 'pointer',
                    textDecoration: 'none',
                    letterSpacing: '0.15em',
                    fontWeight: 'bold',
                  }}
                >
                  OPEN SOURCE ↗
                </a>
                <button
                  onClick={async () => {
                    try {
                      await navigator.clipboard.writeText(url);
                    } catch { /* ignore */ }
                  }}
                  style={{
                    background: 'rgba(8,145,178,0.15)',
                    border: '1px solid rgba(8,145,178,0.4)',
                    borderRadius: 6,
                    color: '#22d3ee',
                    fontSize: 10,
                    fontFamily: 'monospace',
                    padding: '5px 14px',
                    cursor: 'pointer',
                    letterSpacing: '0.15em',
                    fontWeight: 'bold',
                  }}
                >
                  COPY URL
                </button>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
