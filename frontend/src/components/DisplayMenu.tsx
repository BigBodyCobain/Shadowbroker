'use client';

import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useTheme, type SensorMode } from '@/lib/ThemeContext';
import type { MapStyle } from '@/lib/layerPreferences';

/** Short code shown as the big mode label in the header (EO = normal electro-optical view). */
export const SENSOR_CODE: Record<SensorMode, string> = { off: 'EO', flir: 'FLIR', nvg: 'NVG', crt: 'CRT' };

const SENSORS: { id: SensorMode; label: string; hint: string; swatch: string }[] = [
  { id: 'off', label: 'EO', hint: 'Standard view', swatch: 'linear-gradient(135deg,#0a1524,#1e9bff)' },
  { id: 'flir', label: 'FLIR', hint: 'Thermal iron-bow, hot pink and orange', swatch: 'linear-gradient(135deg,#1b0626,#ff6aa8 55%,#ffa040)' },
  { id: 'nvg', label: 'NVG', hint: 'Night-vision phosphor green', swatch: 'linear-gradient(135deg,#031a0a,#2fe56e 55%,#b4ffc6)' },
  { id: 'crt', label: 'CRT', hint: 'Lime P1 terminal with scanlines', swatch: 'repeating-linear-gradient(180deg,#010300 0 2px,#7fbf14 2px 3px)' },
];

function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
  dim = false,
}: {
  dim?: boolean;
  label: string;
  value: T;
  options: { id: T; label: string }[];
  onChange: (v: T) => void;
}) {
  return (
    <div className="grid grid-cols-[78px_minmax(0,1fr)] items-center gap-2">
      <span className="text-[10.5px] font-mono tracking-[0.16em] text-[var(--text-muted)]">{label}</span>
      <div className={`sb-seg !m-0 grid grid-cols-2 gap-1 w-full ${dim ? 'opacity-45' : ''}`} role="radiogroup" aria-label={label}>
        {options.map((o) => (
          <button
            key={o.id}
            type="button"
            role="radio"
            aria-checked={value === o.id}
            onClick={() => onChange(o.id)}
            className={`sb-seg-btn px-2 text-[11px] font-mono tracking-[0.08em] transition-colors ${
              value === o.id ? 'is-active text-cyan-200 font-bold' : 'text-[var(--text-muted)] hover:text-cyan-300'
            }`}
          >
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}

export default function DisplayMenu({
  open,
  onClose,
  mapStyle,
  onMapStyleChange,
}: {
  open: boolean;
  onClose: () => void;
  mapStyle?: MapStyle;
  onMapStyleChange?: (style: MapStyle) => void;
}) {
  const { theme, setTheme, hudColor, setHudColor, sensor, setSensor } = useTheme();
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    const onDown = (e: PointerEvent) => {
      const el = ref.current;
      if (el && !el.contains(e.target as Node) && !(e.target as HTMLElement).closest?.('[data-display-toggle]')) onClose();
    };
    window.addEventListener('keydown', onKey);
    window.addEventListener('pointerdown', onDown);
    return () => {
      window.removeEventListener('keydown', onKey);
      window.removeEventListener('pointerdown', onDown);
    };
  }, [open, onClose]);

  // Rendered in a portal at the page level so the left column's scroll clipping can't cut it.
  // Position comes from the VIEW button; divide by the HUD zoom step because a zoomed fixed
  // element multiplies its own left/top.
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null);
  useLayoutEffect(() => {
    if (!open) return;
    const place = () => {
      const btn = document.querySelector('[data-display-toggle]');
      const card = btn?.closest('.sb-header-card') ?? btn;
      if (!card) return;
      const r = card.getBoundingClientRect();
      const w = window.innerWidth;
      const z = w >= 3000 ? 1.5 : w >= 2300 ? 1.2 : 1; // matches the .sb-modal zoom step
      setPos({ left: r.left / z, top: (r.bottom + 8) / z });
    };
    place();
    window.addEventListener('resize', place);
    return () => window.removeEventListener('resize', place);
  }, [open]);

  if (!open || typeof document === 'undefined') return null;

  return createPortal(
    <div
      ref={ref}
      role="dialog"
      aria-label="Display settings"
      style={pos ? { left: pos.left, top: pos.top } : { visibility: 'hidden' }}
      className="sb-panel sb-modal sb-menu-solid fixed z-[9500] w-[296px] p-4 flex flex-col gap-3.5 pointer-events-auto"
    >
      <div className="sb-title text-cyan-300">Display</div>

      <div className="flex flex-col gap-2">
        <span className="text-[10.5px] font-mono tracking-[0.18em] text-[var(--text-muted)]">SENSOR</span>
        <div className="grid grid-cols-2 gap-2" role="radiogroup" aria-label="Sensor mode">
          {SENSORS.map((s) => {
            const on = sensor === s.id;
            return (
              <button
                key={s.id}
                type="button"
                role="radio"
                aria-checked={on}
                title={s.hint}
                onClick={() => setSensor(s.id)}
                className={`sb-sensor-tile text-left rounded-xl border px-2.5 py-2 transition-colors ${
                  on
                    ? 'border-cyan-400/60 bg-cyan-500/10'
                    : 'border-[var(--border-primary)] hover:border-cyan-500/40 bg-[rgba(3,8,18,0.45)]'
                }`}
              >
                <span className="flex items-center gap-2">
                  <span className="w-4 h-4 rounded-[5px] shrink-0 ring-1 ring-white/10" style={{ background: s.swatch }} />
                  <span className={`text-[12px] font-mono font-bold tracking-[0.12em] ${on ? 'text-cyan-200' : 'text-[var(--text-primary)]'}`}>
                    {s.label}
                  </span>
                </span>
                <span className="sb-prose mt-1 block text-[11px] !leading-snug text-[var(--text-muted)]">{s.hint}</span>
              </button>
            );
          })}
        </div>
        <p className="sb-prose text-[11px] !leading-snug text-[var(--text-muted)]">
          Sensor modes tint the map and the interface. Map data keeps a trace of its real colours, and alert severity colours never change.
        </p>
      </div>

      {onMapStyleChange && mapStyle && (
        <Segmented
          label="BASEMAP"
          value={mapStyle}
          options={[
            { id: 'DEFAULT' as MapStyle, label: 'MAP' },
            { id: 'SATELLITE' as MapStyle, label: 'SATELLITE' },
            { id: 'OSM' as MapStyle, label: 'OSM' },
          ]}
          onChange={onMapStyleChange}
        />
      )}
      <Segmented
        label={sensor === 'off' ? 'MAP TONE' : 'TONE (EO)'}
        value={theme}
        dim={sensor !== 'off'}
        options={[
          { id: 'dark', label: 'DARK' },
          { id: 'light', label: 'LIGHT' },
        ]}
        onChange={setTheme}
      />
      <Segmented
        label={sensor === 'off' ? 'HUD' : 'HUD (EO)'}
        value={hudColor}
        dim={sensor !== 'off'}
        options={[
          { id: 'cyan', label: 'CYAN' },
          { id: 'matrix', label: 'MATRIX' },
        ]}
        onChange={setHudColor}
      />
    </div>,
    document.body,
  );
}
