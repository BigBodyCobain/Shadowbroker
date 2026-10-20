'use client';

import React, { useDeferredValue, useState, useMemo, useRef, useEffect } from 'react';
import { Search, Crosshair, Plane, Shield, Star, Ship, X, Database } from 'lucide-react';
import { motion, AnimatePresence } from '@/lib/motion';
import { trackedOperators } from '../lib/trackedData';
import { useDataKeys } from '@/hooks/useDataStore';
import {
  LAYER_PREFERENCES_CHANGED_EVENT,
  loadActiveLayers,
} from '@/lib/layerPreferences';
import type { ActiveLayers } from '@/types/dashboard';
import { useTranslation } from '@/i18n';

interface FindLocateBarProps {
  onLocate: (lat: number, lng: number, entityId: string, entityType: string) => void;
  onFilter?: (filterType: string, filterValue: string) => void;
}

interface SearchResult {
  id: string;
  label: string;
  sublabel: string;
  category: string;
  categoryColor: string;
  lat: number;
  lng: number;
  entityType: string;
  extra?: string;
}

const SEARCH_RESULT_LIMIT = 12;

function isFiniteCoordinate(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function matchesQuery(query: string, ...values: unknown[]): boolean {
  return values.some((value) => {
    if (value === null || value === undefined) return false;
    if (Array.isArray(value)) return value.some((item) => String(item).toLowerCase().includes(query));
    return String(value).toLowerCase().includes(query);
  });
}

const FindLocateBar = React.memo(function FindLocateBar({ onLocate, onFilter }: FindLocateBarProps) {
  const { t } = useTranslation();
  const data = useDataKeys([
    'commercial_flights',
    'private_flights',
    'private_jets',
    'military_flights',
    'tracked_flights',
    'ships',
    'fishing_activity',
    'satellites',
    'trains',
    'military_bases',
    'kiwisdr',
  ] as const);
  const [query, setQuery] = useState('');
  const deferredQuery = useDeferredValue(query.trim().toLowerCase());
  const [isOpen, setIsOpen] = useState(false);
  const [visibleLayers, setVisibleLayers] = useState<ActiveLayers>(loadActiveLayers);
  const inputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Keep search visibility aligned with the DATA LAYERS panel without requiring
  // a heavyweight page-level prop chain. Same-tab saves emit a custom event;
  // the storage listener covers another tab changing the shared preferences.
  useEffect(() => {
    const onPreferenceChange = (event: Event) => {
      const detail = (event as CustomEvent<ActiveLayers>).detail;
      setVisibleLayers(detail ?? loadActiveLayers());
    };
    const onStorage = (event: StorageEvent) => {
      if (event.key === null || event.key.startsWith('sb_')) {
        setVisibleLayers(loadActiveLayers());
      }
    };
    window.addEventListener(LAYER_PREFERENCES_CHANGED_EVENT, onPreferenceChange);
    window.addEventListener('storage', onStorage);
    return () => {
      window.removeEventListener(LAYER_PREFERENCES_CHANGED_EVENT, onPreferenceChange);
      window.removeEventListener('storage', onStorage);
    };
  }, []);

  // Close dropdown when clicking outside
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  // Keep the long-standing flight/ship/database index cheap and ready. Heavy
  // optional layers are matched lazily below only while the user is searching.
  const allEntities = useMemo(() => {
    const results: SearchResult[] = [];

    // Commercial flights
    for (const f of data?.commercial_flights || []) {
      const uid = f.icao24 || f.registration || f.callsign || '';
      results.push({
        id: `flight-${uid}`,
        label: f.callsign || uid,
        sublabel: `${f.model || 'Unknown'} · ${f.airline_code || 'Commercial'}`,
        category: 'COMMERCIAL',
        categoryColor: 'text-cyan-400',
        lat: f.lat,
        lng: f.lng,
        entityType: 'flight',
      });
    }

    // Private flights
    for (const f of [...(data?.private_flights || []), ...(data?.private_jets || [])]) {
      const uid = f.icao24 || f.registration || f.callsign || '';
      const type = f.type === 'private_jet' ? 'private_jet' : 'private_flight';
      results.push({
        id: `${type === 'private_jet' ? 'private-jet' : 'private-flight'}-${uid}`,
        label: f.callsign || f.registration || uid,
        sublabel: `${f.model || 'Unknown'} · Private`,
        category: 'PRIVATE',
        categoryColor: 'text-orange-400',
        lat: f.lat,
        lng: f.lng,
        entityType: type,
      });
    }

    // Military flights
    for (const f of data?.military_flights || []) {
      const uid = f.icao24 || f.registration || f.callsign || '';
      results.push({
        id: `mil-flight-${uid}`,
        label: f.callsign || uid,
        sublabel: `${f.model || 'Unknown'} · ${f.military_type || 'Military'}`,
        category: 'MILITARY',
        categoryColor: 'text-yellow-400',
        lat: f.lat,
        lng: f.lng,
        entityType: 'military_flight',
      });
    }

    // Tracked flights — include tags/owner/name for broad search (first name, last name, etc.)
    for (const f of data?.tracked_flights || []) {
      const uid = f.icao24 || f.registration || f.callsign || '';
      const operator = f.alert_operator || 'Unknown Operator';
      const category = f.alert_category || 'Tracked';
      const type = f.alert_type || f.model || 'Unknown';
      const extras = [f.alert_operator, f.alert_tags, f.owner, f.name, f.callsign, f.registration]
        .filter(Boolean)
        .join(' ');
      results.push({
        id: `tracked-${uid}`,
        label: operator,
        sublabel: `${category} · ${type} (${f.registration || uid})`,
        category: 'TRACKED',
        categoryColor: 'text-pink-400',
        lat: f.lat,
        lng: f.lng,
        entityType: 'tracked_flight',
        extra: extras,
      });
    }

    // Ships
    for (const s of data?.ships || []) {
      results.push({
        id: `ship-${s.mmsi || s.name || ''}`,
        label: s.name || 'UNKNOWN',
        sublabel: `${s.type || 'Vessel'} · ${s.destination || 'Unknown dest'}`,
        category: 'MARITIME',
        categoryColor: 'text-blue-400',
        lat: s.lat,
        lng: s.lng,
        entityType: 'ship',
      });
    }

    // Database Records - Tracked Operators
    for (const op of trackedOperators) {
      results.push({
        id: `tracked-db-${op}`,
        label: op,
        sublabel: `Database Record · Operator`,
        category: 'DATABASE',
        categoryColor: 'text-purple-400',
        lat: 0,
        lng: 0,
        entityType: 'database_operator',
      });
    }

    return results;
  }, [data]);

  // Filter results based on query. Large/optional datasets are scanned only
  // for a real search (2+ chars), only when their layer is visible, and stop
  // as soon as the 12-result UI cap is satisfied. useDeferredValue keeps the
  // input responsive even with tens of thousands of fishing events.
  const filtered = useMemo(() => {
    if (!deferredQuery) return [];
    const q = deferredQuery;
    const results = allEntities
      .filter((e) => {
        const searchable = `${e.label} ${e.sublabel} ${e.id} ${e.extra || ''}`.toLowerCase();
        return searchable.includes(q);
      })
      .slice(0, SEARCH_RESULT_LIMIT);

    if (q.length < 2 || results.length >= SEARCH_RESULT_LIMIT) return results;

    const push = (
      result: SearchResult,
      searchableValues: unknown[],
    ) => {
      if (results.length >= SEARCH_RESULT_LIMIT) return;
      if (!isFiniteCoordinate(result.lat) || !isFiniteCoordinate(result.lng)) return;
      if (matchesQuery(q, ...searchableValues)) results.push(result);
    };

    if (visibleLayers.fishing_activity) {
      for (const event of data?.fishing_activity || []) {
        push(
          {
            id: `fishing-${event.id || event.vessel_id || event.vessel_ssvid || ''}`,
            label: event.vessel_name || event.vessel_ssvid || 'UNKNOWN VESSEL',
            sublabel: `${event.type || 'Fishing activity'} · ${event.vessel_flag || 'Unknown flag'}`,
            category: 'FISHING',
            categoryColor: 'text-teal-400',
            lat: event.lat,
            lng: event.lng,
            entityType: 'fishing_activity',
          },
          [
            event.vessel_name,
            event.vessel_flag,
            event.vessel_id,
            event.vessel_ssvid,
            event.type,
            event.id,
          ],
        );
        if (results.length >= SEARCH_RESULT_LIMIT) break;
      }
    }

    if (visibleLayers.satellites && results.length < SEARCH_RESULT_LIMIT) {
      for (const satellite of data?.satellites || []) {
        push(
          {
            id: `satellite-${satellite.id}`,
            label: satellite.name || String(satellite.id),
            sublabel: `${satellite.mission || satellite.sat_type || 'Satellite'} · ${satellite.country || 'Unknown'}`,
            category: 'SATELLITE',
            categoryColor: 'text-violet-400',
            lat: satellite.lat,
            lng: satellite.lng,
            entityType: 'satellite',
          },
          [satellite.name, satellite.id, satellite.mission, satellite.sat_type, satellite.country],
        );
        if (results.length >= SEARCH_RESULT_LIMIT) break;
      }
    }

    if (visibleLayers.trains && results.length < SEARCH_RESULT_LIMIT) {
      for (const train of data?.trains || []) {
        push(
          {
            id: `train-${train.id || train.number || train.name || ''}`,
            label: train.name || train.number || train.id || 'TRAIN',
            sublabel: `${train.operator || train.source_label || train.source || 'Rail'} · ${train.route || train.status || 'Unknown route'}`,
            category: 'TRAIN',
            categoryColor: 'text-emerald-400',
            lat: train.lat,
            lng: train.lng,
            entityType: 'train',
          },
          [
            train.id,
            train.name,
            train.number,
            train.operator,
            train.country,
            train.route,
            train.status,
            train.source,
            train.source_label,
          ],
        );
        if (results.length >= SEARCH_RESULT_LIMIT) break;
      }
    }

    if (visibleLayers.military_bases && results.length < SEARCH_RESULT_LIMIT) {
      for (const base of data?.military_bases || []) {
        push(
          {
            id: `military-base-${base.name || ''}-${base.country || ''}`,
            label: base.name || 'MILITARY BASE',
            sublabel: `${base.branch || base.operator || 'Military'} · ${base.country || 'Unknown'}`,
            category: 'BASE',
            categoryColor: 'text-red-400',
            lat: base.lat,
            lng: base.lng,
            entityType: 'military_base',
          },
          [base.name, base.country, base.operator, base.branch],
        );
        if (results.length >= SEARCH_RESULT_LIMIT) break;
      }
    }

    if (visibleLayers.kiwisdr && results.length < SEARCH_RESULT_LIMIT) {
      for (const receiver of data?.kiwisdr || []) {
        push(
          {
            id: `kiwisdr-${receiver.name || ''}-${receiver.lat}-${receiver.lon}`,
            label: receiver.name || receiver.location || 'KIWISDR',
            sublabel: `${receiver.location || receiver.bands || 'KiwiSDR'} · ${receiver.users ?? 0}/${receiver.users_max ?? '?'} users`,
            category: 'SDR',
            categoryColor: 'text-green-400',
            lat: receiver.lat,
            lng: receiver.lon,
            entityType: 'kiwisdr',
          },
          [receiver.name, receiver.location, receiver.bands, receiver.antenna, receiver.url],
        );
        if (results.length >= SEARCH_RESULT_LIMIT) break;
      }
    }

    return results;
  }, [deferredQuery, allEntities, data, visibleLayers]);

  const handleSelect = (result: SearchResult) => {
    if (result.entityType === 'database_operator') {
      if (onFilter) onFilter('tracked_owner', result.label);
    } else {
      onLocate(result.lat, result.lng, result.id, result.entityType);
    }
    setQuery('');
    setIsOpen(false);
  };

  const categoryIcons: Record<string, React.ReactNode> = {
    COMMERCIAL: <Plane size={10} className="text-cyan-400" />,
    PRIVATE: <Plane size={10} className="text-orange-400" />,
    MILITARY: <Shield size={10} className="text-yellow-400" />,
    TRACKED: <Star size={10} className="text-pink-400" />,
    MARITIME: <Ship size={10} className="text-blue-400" />,
    FISHING: <Ship size={10} className="text-teal-400" />,
    SATELLITE: <Star size={10} className="text-violet-400" />,
    TRAIN: <Database size={10} className="text-emerald-400" />,
    BASE: <Shield size={10} className="text-red-400" />,
    SDR: <Crosshair size={10} className="text-green-400" />,
    DATABASE: <Database size={10} className="text-purple-400" />,
  };

  return (
    <div ref={containerRef} className="relative w-full pointer-events-auto">
      <div className="flex items-center gap-2 bg-[#0a0a0a]/90 backdrop-blur-sm border border-cyan-900/40 px-3 py-2 focus-within:border-cyan-500/40 transition-colors">
        <Search size={12} className="text-slate-500 flex-shrink-0" />
        <input
          ref={inputRef}
          type="text"
          value={query}
          name="sb-locate-search"
          autoComplete="off"
          data-search-input
          placeholder={t('map.searchPlaceholder')}
          className="flex-1 bg-transparent text-[12px] text-[var(--text-secondary)] font-mono tracking-wider outline-none placeholder:text-slate-500"
          onChange={(e) => {
            setQuery(e.target.value);
            setIsOpen(true);
          }}
          onFocus={() => setIsOpen(true)}
        />
        {query && (
          <button
            onClick={() => {
              setQuery('');
              setIsOpen(false);
            }}
            className="text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
          >
            <X size={10} />
          </button>
        )}
        <Crosshair size={12} className="text-[var(--text-muted)] flex-shrink-0" />
      </div>

      <AnimatePresence>
        {isOpen && filtered.length > 0 && (
          <motion.div
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            className="absolute top-full left-0 right-0 mt-1 bg-[var(--bg-secondary)]/90 backdrop-blur-sm border border-[var(--border-primary)] overflow-hidden z-50 shadow-[0_8px_30px_rgba(0,0,0,0.3)]"
          >
            <div className="max-h-[300px] overflow-y-auto styled-scrollbar">
              {filtered.map((r, idx) => (
                <button
                  key={`${r.id}-${idx}`}
                  onClick={() => handleSelect(r)}
                  className="w-full flex items-center gap-3 px-3 py-2 hover:bg-[var(--hover-accent)] transition-colors text-left border-b border-[var(--border-primary)]/50 last:border-0 group"
                >
                  <div className="flex-shrink-0 w-5 h-5 flex items-center justify-center bg-[var(--bg-secondary)] border border-[var(--border-primary)] group-hover:border-cyan-800">
                    {categoryIcons[r.category]}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-[10px] text-[var(--text-primary)] font-mono tracking-wide truncate">
                      {r.label}
                    </div>
                    <div className="text-[11px] text-[var(--text-muted)] font-mono truncate">
                      {r.sublabel}
                    </div>
                  </div>
                  <span
                    className={`text-[10px] font-bold tracking-widest ${r.categoryColor} flex-shrink-0`}
                  >
                    {r.category}
                  </span>
                </button>
              ))}
            </div>
            <div className="px-3 py-1.5 border-t border-[var(--border-primary)] bg-[var(--bg-primary)]/50 text-[11px] text-[var(--text-muted)] font-mono tracking-widest">
              {filtered.length} RESULT{filtered.length !== 1 ? 'S' : ''} — CLICK TO LOCATE
            </div>
          </motion.div>
        )}
        {isOpen && query.trim() && filtered.length === 0 && (
          <motion.div
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            className="absolute top-full left-0 right-0 mt-1 bg-[var(--bg-secondary)]/90 backdrop-blur-sm border border-[var(--border-primary)] z-50 p-4 text-center"
          >
            <div className="text-[9px] text-[var(--text-muted)] font-mono tracking-widest">
              NO MATCHING ASSETS
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
});

export default FindLocateBar;
