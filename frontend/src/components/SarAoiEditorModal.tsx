'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { X, Radar, Plus, Trash2, MapPin, Crosshair } from 'lucide-react';
import { API_BASE } from '@/lib/api';
import type { SarAoi } from '@/types/dashboard';

interface SarAoiEditorModalProps {
  onClose: () => void;
  /** Enter map drop mode — modal hides, user clicks map to place AOI center. */
  onRequestMapPick: () => void;
  /** Coordinates picked from the map (set by parent after drop-mode click). */
  pickedCoords: { lat: number; lng: number } | null;
  /** Called after the modal consumes pickedCoords so the parent can clear them. */
  onPickConsumed: () => void;
  /** Called after an AOI is created or deleted so MaplibreViewer can refresh. */
  onAoiListChanged?: () => void;
  /** Whether map drop mode is currently active. */
  dropModeActive?: boolean;
}

const AOI_CATEGORIES = [
  { value: 'watchlist', label: 'Watchlist' },
  { value: 'conflict', label: 'Conflict Zone' },
  { value: 'infrastructure', label: 'Infrastructure' },
  { value: 'natural_hazard', label: 'Natural Hazard' },
  { value: 'border', label: 'Border Area' },
  { value: 'maritime', label: 'Maritime' },
];

function slugify(s: string): string {
  return s
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 64);
}

const SarAoiEditorModal = React.memo(function SarAoiEditorModal({
  onClose,
  onRequestMapPick,
  pickedCoords,
  onPickConsumed,
  onAoiListChanged,
  dropModeActive,
}: SarAoiEditorModalProps) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => { setMounted(true); }, []);

  // ----- AOI list -----
  const [aois, setAois] = useState<SarAoi[]>([]);
  const [listLoading, setListLoading] = useState(true);

  const fetchAois = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/sar/aois`, { credentials: 'include' });
      if (!res.ok) return;
      const body = await res.json();
      if (Array.isArray(body?.aois)) setAois(body.aois);
    } catch { /* silent */ }
    setListLoading(false);
  }, []);

  useEffect(() => { fetchAois(); }, [fetchAois]);

  // ----- Form state -----
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [centerLat, setCenterLat] = useState('');
  const [centerLon, setCenterLon] = useState('');
  const [radiusKm, setRadiusKm] = useState('25');
  const [category, setCategory] = useState('watchlist');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [showForm, setShowForm] = useState(false);

  // Consume picked coords from map
  useEffect(() => {
    if (pickedCoords) {
      setCenterLat(pickedCoords.lat.toFixed(5));
      setCenterLon(pickedCoords.lng.toFixed(5));
      setShowForm(true);
      onPickConsumed();
    }
  }, [pickedCoords, onPickConsumed]);

  const resetForm = () => {
    setName('');
    setDescription('');
    setCenterLat('');
    setCenterLon('');
    setRadiusKm('25');
    setCategory('watchlist');
    setError('');
  };

  const handleSubmit = async () => {
    const trimName = name.trim();
    if (!trimName) { setError('Name is required'); return; }
    const lat = parseFloat(centerLat);
    const lon = parseFloat(centerLon);
    if (!Number.isFinite(lat) || lat < -90 || lat > 90) { setError('Latitude must be between -90 and 90'); return; }
    if (!Number.isFinite(lon) || lon < -180 || lon > 180) { setError('Longitude must be between -180 and 180'); return; }
    const rad = parseFloat(radiusKm);
    if (!Number.isFinite(rad) || rad < 1 || rad > 500) { setError('Radius must be 1-500 km'); return; }

    setSubmitting(true);
    setError('');
    try {
      const payload = {
        id: slugify(trimName) || `aoi_${Date.now()}`,
        name: trimName,
        description: description.trim(),
        center_lat: lat,
        center_lon: lon,
        radius_km: rad,
        category,
      };
      const res = await fetch(`${API_BASE}/api/sar/aois`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        const d = body?.detail;
        let msg = `HTTP ${res.status}`;
        if (typeof d === 'string') msg = d;
        else if (Array.isArray(d) && d.length > 0) {
          msg = d.map((item: Record<string, unknown>) => {
            if (typeof item === 'string') return item;
            const loc = Array.isArray(item?.loc) ? (item.loc as string[]).slice(1).join('.') : '';
            return loc ? `${loc}: ${item?.msg || 'invalid'}` : (item?.msg as string) || JSON.stringify(item);
          }).join('; ');
        } else if (d && typeof d === 'object') msg = JSON.stringify(d);
        throw new Error(msg);
      }
      resetForm();
      setShowForm(false);
      await fetchAois();
      onAoiListChanged?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to create AOI');
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (aoiId: string) => {
    try {
      const res = await fetch(`${API_BASE}/api/sar/aois/${encodeURIComponent(aoiId)}`, {
        method: 'DELETE',
        credentials: 'include',
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(typeof body?.detail === 'string' ? body.detail : `HTTP ${res.status}`);
      }
      await fetchAois();
      onAoiListChanged?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to delete AOI');
    }
  };

  // If drop mode is active, show a small floating pill instead of full modal
  if (dropModeActive) {
    if (!mounted) return null;
    return createPortal(
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        className="fixed top-6 left-1/2 -translate-x-1/2 z-[9999] px-4 py-2 rounded-lg border border-cyan-500/60 bg-zinc-950/95 text-cyan-100 shadow-[0_0_20px_rgba(0,200,255,0.2)] flex items-center gap-3"
        style={{ direction: 'ltr' }}
      >
        <Crosshair size={16} className="text-cyan-400 animate-pulse" />
        <span className="text-xs font-mono tracking-wide">CLICK THE MAP TO PLACE AOI CENTER</span>
        <button
          type="button"
          onClick={onClose}
          className="ml-2 text-cyan-400 hover:text-cyan-200 text-xs underline"
        >
          Cancel
        </button>
      </motion.div>,
      document.body,
    );
  }

  if (!mounted) return null;

  return createPortal(
    <AnimatePresence>
      <motion.div
        key="aoi-backdrop"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        onMouseDown={(e) => {
          if (e.target === e.currentTarget) {
            (e.currentTarget as HTMLElement).dataset.downOnBackdrop = '1';
          } else {
            (e.currentTarget as HTMLElement).dataset.downOnBackdrop = '';
          }
        }}
        onMouseUp={(e) => {
          const el = e.currentTarget as HTMLElement;
          const wasDown = el.dataset.downOnBackdrop === '1';
          el.dataset.downOnBackdrop = '';
          if (wasDown && e.target === e.currentTarget) onClose();
        }}
        style={{ direction: 'ltr' }}
        className="fixed inset-0 z-[9999] bg-black/80 backdrop-blur-sm flex items-center justify-center p-4"
      >
        <motion.div
          key="aoi-modal"
          initial={{ scale: 0.94, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          exit={{ scale: 0.94, opacity: 0 }}
          transition={{ type: 'spring', damping: 22, stiffness: 260 }}
          onClick={(e) => e.stopPropagation()}
          className="relative w-full max-w-lg max-h-[85vh] overflow-y-auto rounded-lg border border-cyan-500/40 bg-zinc-950/95 text-cyan-100 shadow-[0_0_40px_rgba(0,200,255,0.25)]"
        >
          {/* Header */}
          <div className="sticky top-0 z-10 flex items-center justify-between gap-3 border-b border-cyan-500/30 bg-zinc-950/95 px-5 py-3">
            <div className="flex items-center gap-2">
              <Radar size={18} className="text-cyan-400" />
              <span className="text-sm font-semibold tracking-wide">SAR AREAS OF INTEREST</span>
            </div>
            <button type="button" onClick={onClose} aria-label="Close" className="rounded p-1 text-cyan-300 hover:bg-cyan-500/10">
              <X size={16} />
            </button>
          </div>

          <div className="p-5 space-y-4">
            {/* Error bar */}
            {error && (
              <div className="text-xs text-red-400 bg-red-500/10 border border-red-500/30 rounded px-3 py-2">
                {error}
              </div>
            )}

            {/* AOI List */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold tracking-wide text-cyan-300/80">
                  {listLoading ? 'LOADING...' : `${aois.length} AOI${aois.length !== 1 ? 'S' : ''} DEFINED`}
                </span>
                {!showForm && (
                  <button
                    type="button"
                    onClick={() => setShowForm(true)}
                    className="flex items-center gap-1 text-xs text-cyan-400 hover:text-cyan-200 transition"
                  >
                    <Plus size={12} /> Add AOI
                  </button>
                )}
              </div>

              {aois.length > 0 && (
                <div className="space-y-1 max-h-48 overflow-y-auto styled-scrollbar">
                  {aois.map((aoi) => (
                    <div
                      key={aoi.id}
                      className="flex items-center justify-between gap-2 px-3 py-2 rounded border border-cyan-500/20 bg-cyan-500/5 hover:bg-cyan-500/10 transition group"
                    >
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <MapPin size={12} className="text-cyan-400 flex-shrink-0" />
                          <span className="text-xs font-semibold truncate">{aoi.name}</span>
                          <span className="text-[10px] text-cyan-500/60 bg-cyan-500/10 px-1.5 rounded">
                            {aoi.category}
                          </span>
                        </div>
                        <div className="text-[10px] text-cyan-300/50 mt-0.5 ml-5">
                          {aoi.center[0].toFixed(3)}, {aoi.center[1].toFixed(3)} &middot; {aoi.radius_km} km
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={() => handleDelete(aoi.id)}
                        className="text-red-400/60 hover:text-red-400 opacity-0 group-hover:opacity-100 transition p-1"
                        title="Delete AOI"
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  ))}
                </div>
              )}

              {!listLoading && aois.length === 0 && !showForm && (
                <div className="text-xs text-cyan-300/50 text-center py-4">
                  No AOIs defined yet. Click &quot;Add AOI&quot; to create one.
                </div>
              )}
            </div>

            {/* Add AOI Form */}
            {showForm && (
              <div className="border border-cyan-500/30 rounded-lg p-4 space-y-3 bg-cyan-500/5">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold tracking-wide text-cyan-200">NEW AOI</span>
                  <button
                    type="button"
                    onClick={() => { setShowForm(false); resetForm(); }}
                    className="text-xs text-cyan-400/60 hover:text-cyan-300"
                  >
                    Cancel
                  </button>
                </div>

                {/* Name */}
                <div>
                  <label className="text-[10px] text-cyan-300/70 block mb-1">NAME</label>
                  <input
                    type="text"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="e.g. Crimea Bridge"
                    className="w-full bg-zinc-900 border border-cyan-500/30 rounded px-3 py-1.5 text-xs text-cyan-100 placeholder:text-cyan-500/30 focus:outline-none focus:border-cyan-400/60"
                    autoComplete="off"
                  />
                </div>

                {/* Description */}
                <div>
                  <label className="text-[10px] text-cyan-300/70 block mb-1">DESCRIPTION (optional)</label>
                  <input
                    type="text"
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    placeholder="Brief description"
                    className="w-full bg-zinc-900 border border-cyan-500/30 rounded px-3 py-1.5 text-xs text-cyan-100 placeholder:text-cyan-500/30 focus:outline-none focus:border-cyan-400/60"
                    autoComplete="off"
                  />
                </div>

                {/* Center coordinates + pick button */}
                <div className="flex gap-2 items-end">
                  <div className="flex-1">
                    <label className="text-[10px] text-cyan-300/70 block mb-1">LATITUDE</label>
                    <input
                      type="text"
                      value={centerLat}
                      onChange={(e) => setCenterLat(e.target.value)}
                      placeholder="45.2606"
                      className="w-full bg-zinc-900 border border-cyan-500/30 rounded px-3 py-1.5 text-xs text-cyan-100 placeholder:text-cyan-500/30 focus:outline-none focus:border-cyan-400/60"
                      autoComplete="off"
                    />
                  </div>
                  <div className="flex-1">
                    <label className="text-[10px] text-cyan-300/70 block mb-1">LONGITUDE</label>
                    <input
                      type="text"
                      value={centerLon}
                      onChange={(e) => setCenterLon(e.target.value)}
                      placeholder="36.5106"
                      className="w-full bg-zinc-900 border border-cyan-500/30 rounded px-3 py-1.5 text-xs text-cyan-100 placeholder:text-cyan-500/30 focus:outline-none focus:border-cyan-400/60"
                      autoComplete="off"
                    />
                  </div>
                  <button
                    type="button"
                    onClick={onRequestMapPick}
                    title="Pick from map"
                    className="flex-shrink-0 p-2 rounded border border-cyan-500/40 bg-cyan-500/10 text-cyan-300 hover:bg-cyan-500/20 hover:text-cyan-100 transition"
                  >
                    <Crosshair size={14} />
                  </button>
                </div>

                {/* Radius + Category */}
                <div className="flex gap-2">
                  <div className="w-24">
                    <label className="text-[10px] text-cyan-300/70 block mb-1">RADIUS (km)</label>
                    <input
                      type="text"
                      value={radiusKm}
                      onChange={(e) => setRadiusKm(e.target.value)}
                      placeholder="25"
                      className="w-full bg-zinc-900 border border-cyan-500/30 rounded px-3 py-1.5 text-xs text-cyan-100 placeholder:text-cyan-500/30 focus:outline-none focus:border-cyan-400/60"
                      autoComplete="off"
                    />
                  </div>
                  <div className="flex-1">
                    <label className="text-[10px] text-cyan-300/70 block mb-1">CATEGORY</label>
                    <select
                      value={category}
                      onChange={(e) => setCategory(e.target.value)}
                      className="w-full bg-zinc-900 border border-cyan-500/30 rounded px-3 py-1.5 text-xs text-cyan-100 focus:outline-none focus:border-cyan-400/60"
                    >
                      {AOI_CATEGORIES.map((c) => (
                        <option key={c.value} value={c.value}>{c.label}</option>
                      ))}
                    </select>
                  </div>
                </div>

                {/* Submit */}
                <button
                  type="button"
                  onClick={handleSubmit}
                  disabled={submitting}
                  className="w-full rounded border border-cyan-400/60 bg-cyan-500/15 px-4 py-2 text-xs font-semibold text-cyan-100 hover:bg-cyan-500/25 transition disabled:opacity-50"
                >
                  {submitting ? 'CREATING...' : 'CREATE AOI'}
                </button>
              </div>
            )}
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>,
    document.body,
  );
});

export default SarAoiEditorModal;
