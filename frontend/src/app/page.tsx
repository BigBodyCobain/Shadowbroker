"use client";

import { useEffect, useState, useRef } from "react";
import dynamic from 'next/dynamic';
import { motion } from "framer-motion";
import { ChevronLeft, ChevronRight } from "lucide-react";
import WorldviewLeftPanel from "@/components/WorldviewLeftPanel";

import NewsFeed from "@/components/NewsFeed";
import MarketsPanel from "@/components/MarketsPanel";
import FilterPanel from "@/components/FilterPanel";
import FindLocateBar from "@/components/FindLocateBar";
import TopRightControls from "@/components/TopRightControls";
import RadioInterceptPanel from "@/components/RadioInterceptPanel";
import SettingsPanel from "@/components/SettingsPanel";
import MapLegend from "@/components/MapLegend";
import ScaleBar from "@/components/ScaleBar";
import ErrorBoundary from "@/components/ErrorBoundary";
import { DashboardDataProvider } from "@/lib/DashboardDataContext";
import OnboardingModal, { useOnboarding } from "@/components/OnboardingModal";
import ChangelogModal, { useChangelog } from "@/components/ChangelogModal";
import type { SelectedEntity } from "@/types/dashboard";
import { NOMINATIM_DEBOUNCE_MS } from "@/lib/constants";
import { useDataPolling } from "@/hooks/useDataPolling";
import { useReverseGeocode } from "@/hooks/useReverseGeocode";
import { useRegionDossier } from "@/hooks/useRegionDossier";

// Use dynamic loads for Maplibre to avoid SSR window is not defined errors
const MaplibreViewer = dynamic(() => import('@/components/MaplibreViewer'), { ssr: false });
const STYLE_STORAGE_KEY = "sb_map_style";
const STYLE_OPTIONS = ["DEFAULT", "SATELLITE", "STREETS", "TERRAIN", "LIGHT", "DARK"] as const;
type StyleOption = (typeof STYLE_OPTIONS)[number];

/* ── LOCATE BAR ── coordinate / place-name search above bottom status bar ── */
function LocateBar({ onLocate }: { onLocate: (lat: number, lng: number) => void }) {
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState('');
  const [results, setResults] = useState<{ label: string; lat: number; lng: number }[]>([]);
  const [loading, setLoading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => { if (open) inputRef.current?.focus(); }, [open]);

  // Parse raw coordinate input: "31.8, 34.8" or "31.8 34.8" or "-12.3, 45.6"
  const parseCoords = (s: string): { lat: number; lng: number } | null => {
    const m = s.trim().match(/^([+-]?\d+\.?\d*)[,\s]+([+-]?\d+\.?\d*)$/);
    if (!m) return null;
    const lat = parseFloat(m[1]), lng = parseFloat(m[2]);
    if (lat >= -90 && lat <= 90 && lng >= -180 && lng <= 180) return { lat, lng };
    return null;
  };

  const handleSearch = async (q: string) => {
    setValue(q);
    // Check for raw coordinates first
    const coords = parseCoords(q);
    if (coords) {
      setResults([{ label: `${coords.lat.toFixed(4)}, ${coords.lng.toFixed(4)}`, ...coords }]);
      return;
    }
    // Geocode with Nominatim (debounced)
    if (timerRef.current) clearTimeout(timerRef.current);
    if (q.trim().length < 2) { setResults([]); return; }
    timerRef.current = setTimeout(async () => {
      setLoading(true);
      try {
        const res = await fetch(`https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(q)}&format=json&limit=5`, {
          headers: { 'Accept-Language': 'en' },
        });
        const data = await res.json();
        setResults(data.map((r: { display_name: string; lat: string; lon: string }) => ({ label: r.display_name, lat: parseFloat(r.lat), lng: parseFloat(r.lon) })));
      } catch { setResults([]); }
      setLoading(false);
    }, NOMINATIM_DEBOUNCE_MS);
  };

  const handleSelect = (r: { lat: number; lng: number }) => {
    onLocate(r.lat, r.lng);
    setOpen(false);
    setValue('');
    setResults([]);
  };

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="flex items-center gap-1.5 bg-[var(--bg-primary)]/60 backdrop-blur-md border border-[var(--border-primary)] rounded-lg px-3 py-1.5 text-[9px] font-mono tracking-[0.15em] text-[var(--text-muted)] hover:text-cyan-400 hover:border-cyan-800 transition-colors"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>
        LOCATE
      </button>
    );
  }

  return (
    <div className="relative w-[420px]">
      <div className="flex items-center gap-2 bg-[var(--bg-primary)]/80 backdrop-blur-md border border-cyan-800/60 rounded-lg px-3 py-2 shadow-[0_0_20px_rgba(0,255,255,0.1)]">
        <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-cyan-500 flex-shrink-0"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>
        <input
          ref={inputRef}
          value={value}
          onChange={(e) => handleSearch(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Escape') { setOpen(false); setValue(''); setResults([]); } if (e.key === 'Enter' && results.length > 0) handleSelect(results[0]); }}
          placeholder="Enter coordinates (31.8, 34.8) or place name..."
          className="flex-1 bg-transparent text-[10px] text-[var(--text-primary)] font-mono tracking-wider outline-none placeholder:text-[var(--text-muted)]"
        />
        {loading && <div className="w-3 h-3 border border-cyan-500 border-t-transparent rounded-full animate-spin" />}
        <button onClick={() => { setOpen(false); setValue(''); setResults([]); }} className="text-[var(--text-muted)] hover:text-[var(--text-primary)]">
          <svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>
        </button>
      </div>
      {results.length > 0 && (
        <div className="absolute bottom-full left-0 right-0 mb-1 bg-[var(--bg-secondary)]/95 backdrop-blur-md border border-[var(--border-primary)] rounded-lg overflow-hidden shadow-[0_-8px_30px_rgba(0,0,0,0.4)] max-h-[200px] overflow-y-auto styled-scrollbar">
          {results.map((r, i) => (
            <button key={i} onClick={() => handleSelect(r)} className="w-full text-left px-3 py-2 hover:bg-cyan-950/40 transition-colors border-b border-[var(--border-primary)]/50 last:border-0 flex items-center gap-2">
              <svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-cyan-500 flex-shrink-0"><path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z"/><circle cx="12" cy="10" r="3"/></svg>
              <span className="text-[9px] text-[var(--text-secondary)] font-mono truncate">{r.label}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default function Dashboard() {
  const { data, dataVersion, backendStatus } = useDataPolling();
  const { mouseCoords, locationLabel, handleMouseCoords } = useReverseGeocode();
  const [selectedEntity, setSelectedEntity] = useState<SelectedEntity | null>(null);
  const [trackedSdr, setTrackedSdr] = useState<any>(null);
  const { regionDossier, regionDossierLoading, handleMapRightClick } = useRegionDossier(selectedEntity, setSelectedEntity);

  const [uiVisible, setUiVisible] = useState(true);
  const [leftOpen, setLeftOpen] = useState(true);
  const [rightOpen, setRightOpen] = useState(true);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [legendOpen, setLegendOpen] = useState(false);
  const [mapView, setMapView] = useState({ zoom: 2, latitude: 20 });
  const [measureMode, setMeasureMode] = useState(false);
  const [measurePoints, setMeasurePoints] = useState<{ lat: number; lng: number }[]>([]);

  const [activeLayers, setActiveLayers] = useState({
    flights: true,
    private: true,
    jets: true,
    military: true,
    tracked: true,
    satellites: true,
    ships_military: true,
    ships_cargo: true,
    ships_civilian: false,
    ships_passenger: true,
    ships_tracked_yachts: true,
    earthquakes: true,
    cctv: false,
    ukraine_frontline: true,
    global_incidents: true,
    day_night: true,
    gps_jamming: true,
    gibs_imagery: false,
    highres_satellite: false,
    kiwisdr: false,
    firms: false,
    internet_outages: false,
    datacenters: false,
    military_bases: false,
    power_plants: false,
  });

  // NASA GIBS satellite imagery state
  const [gibsDate, setGibsDate] = useState<string>(() => {
    const d = new Date();
    d.setDate(d.getDate() - 1);
    return d.toISOString().slice(0, 10);
  });
  const [gibsOpacity, setGibsOpacity] = useState(0.6);

  const [effects, setEffects] = useState({
    bloom: true,
  });

  const [activeStyle, setActiveStyle] = useState<StyleOption>(() => {
    if (typeof window === "undefined") return "DEFAULT";
    const saved = window.localStorage.getItem(STYLE_STORAGE_KEY);
    return (saved && (STYLE_OPTIONS as readonly string[]).includes(saved)) ? (saved as StyleOption) : "DEFAULT";
  });
  const [styleMenuOpen, setStyleMenuOpen] = useState(false);
  const styleMenuRef = useRef<HTMLDivElement | null>(null);

  const selectStyle = (style: StyleOption) => {
    setActiveStyle(style);
    setStyleMenuOpen(false);
  };

  useEffect(() => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(STYLE_STORAGE_KEY, activeStyle);
    }
    // Auto-toggle High-Res Satellite layer with SATELLITE style
    setActiveLayers((l) => (l.highres_satellite === (activeStyle === "SATELLITE")
      ? l
      : { ...l, highres_satellite: activeStyle === "SATELLITE" }
    ));
  }, [activeStyle]);

  useEffect(() => {
    if (!styleMenuOpen) return;
    const onDocClick = (ev: MouseEvent) => {
      if (!styleMenuRef.current?.contains(ev.target as Node)) setStyleMenuOpen(false);
    };
    const onEsc = (ev: KeyboardEvent) => {
      if (ev.key === "Escape") setStyleMenuOpen(false);
    };
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onEsc);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onEsc);
    };
  }, [styleMenuOpen]);

  const [activeFilters, setActiveFilters] = useState<Record<string, string[]>>({});
  const [flyToLocation, setFlyToLocation] = useState<{ lat: number, lng: number, ts: number } | null>(null);

  // Eavesdrop Mode State
  const [isEavesdropping, setIsEavesdropping] = useState(false);
  const [eavesdropLocation, setEavesdropLocation] = useState<{ lat: number, lng: number } | null>(null);
  const [cameraCenter, setCameraCenter] = useState<{ lat: number, lng: number } | null>(null);

  // Onboarding & connection status
  const { showOnboarding, setShowOnboarding } = useOnboarding();
  const { showChangelog, setShowChangelog } = useChangelog();

  return (
    <DashboardDataProvider data={data} selectedEntity={selectedEntity} setSelectedEntity={setSelectedEntity}>
    <main className="fixed inset-0 w-full h-full bg-[var(--bg-primary)] overflow-hidden font-sans">

      {/* MAPLIBRE WEBGL OVERLAY */}
      <ErrorBoundary name="Map">
        <MaplibreViewer
          data={data}
          activeLayers={activeLayers}
          activeFilters={activeFilters}
          effects={{ ...effects, bloom: effects.bloom && activeStyle !== 'DEFAULT', style: activeStyle }}
          onEntityClick={setSelectedEntity}
          selectedEntity={selectedEntity}
          flyToLocation={flyToLocation}
          gibsDate={gibsDate}
          gibsOpacity={gibsOpacity}
          isEavesdropping={isEavesdropping}
          onEavesdropClick={setEavesdropLocation}
          onCameraMove={setCameraCenter}
          onMouseCoords={handleMouseCoords}
          onRightClick={handleMapRightClick}
          regionDossier={regionDossier}
          regionDossierLoading={regionDossierLoading}
          onViewStateChange={setMapView}
          measureMode={measureMode}
          onMeasureClick={(pt: { lat: number; lng: number }) => {
            setMeasurePoints(prev => prev.length >= 3 ? prev : [...prev, pt]);
          }}
          measurePoints={measurePoints}
          trackedSdr={trackedSdr}
          setTrackedSdr={setTrackedSdr}
        />
      </ErrorBoundary>

      {uiVisible && (
        <>
          {/* WORLDVIEW HEADER */}
          <motion.div
            initial={{ opacity: 0, y: -20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 1 }}
            className="absolute top-6 left-6 z-[200] pointer-events-none flex items-center gap-4 hud-zone"
          >
            <div className="w-8 h-8 flex items-center justify-center">
              {/* Target Reticle Icon */}
              <div className="w-6 h-6 rounded-full border border-cyan-500 relative flex items-center justify-center">
                <div className="w-4 h-4 rounded-full bg-cyan-500/30"></div>
                <div className="absolute top-[-2px] bottom-[-2px] w-[1px] bg-cyan-500"></div>
                <div className="absolute left-[-2px] right-[-2px] h-[1px] bg-cyan-500"></div>
              </div>
            </div>
            <div className="flex flex-col">
              <h1 className="text-2xl font-bold tracking-[0.4em] text-[var(--text-primary)] flex items-center gap-3" style={{ fontFamily: 'monospace' }}>
                S H A D O W <span className="text-cyan-400">B R O K E R</span>
              </h1>
              <span className="text-[9px] text-[var(--text-muted)] font-mono tracking-[0.3em] mt-1 ml-1">GLOBAL THREAT INTERCEPT</span>
            </div>
          </motion.div>

          {/* SYSTEM METRICS TOP LEFT */}
          <div className="absolute top-2 left-6 text-[8px] font-mono tracking-widest text-cyan-500/50 z-[200] pointer-events-none hud-zone">
            OPTIC VIS:113  SRC:180  DENS:1.42  0.8ms
          </div>

          {/* SYSTEM METRICS TOP RIGHT */}
          <div className="absolute top-2 right-6 text-[9px] flex flex-col items-end font-mono tracking-widest text-[var(--text-muted)] z-[200] pointer-events-none hud-zone">
            <div>RTX</div>
            <div>VSR</div>
          </div>

          {/* LEFT HUD CONTAINER — slides off left edge when hidden */}
          <motion.div
            className="absolute left-6 top-24 bottom-6 w-80 flex flex-col gap-6 z-[200] pointer-events-none hud-zone"
            animate={{ x: leftOpen ? 0 : -360 }}
            transition={{ type: 'spring', damping: 30, stiffness: 250 }}
          >
            {/* LEFT PANEL - DATA LAYERS */}
            <ErrorBoundary name="WorldviewLeftPanel">
              <WorldviewLeftPanel data={data} activeLayers={activeLayers} setActiveLayers={setActiveLayers} onSettingsClick={() => setSettingsOpen(true)} onLegendClick={() => setLegendOpen(true)} gibsDate={gibsDate} setGibsDate={setGibsDate} gibsOpacity={gibsOpacity} setGibsOpacity={setGibsOpacity} onEntityClick={setSelectedEntity} onFlyTo={(lat, lng) => setFlyToLocation({ lat, lng, ts: Date.now() })} trackedSdr={trackedSdr} setTrackedSdr={setTrackedSdr} />
            </ErrorBoundary>
          </motion.div>

          {/* LEFT SIDEBAR TOGGLE TAB */}
          <motion.div
            className="absolute left-0 top-1/2 -translate-y-1/2 z-[201] pointer-events-auto hud-zone"
            animate={{ x: leftOpen ? 344 : 0 }}
            transition={{ type: 'spring', damping: 30, stiffness: 250 }}
          >
            <button
              onClick={() => setLeftOpen(!leftOpen)}
              className="flex flex-col items-center gap-1.5 py-5 px-1.5 bg-cyan-400 border border-cyan-400 border-l-0 rounded-r-md text-black hover:bg-cyan-300 hover:border-cyan-300 transition-colors shadow-[2px_0_12px_rgba(0,0,0,0.4)]"
            >
              {leftOpen ? <ChevronLeft size={10} /> : <ChevronRight size={10} />}
              <span className="text-[7px] font-mono tracking-[0.2em] font-bold text-black" style={{ writingMode: 'vertical-rl', transform: 'rotate(180deg)' }}>LAYERS</span>
            </button>
          </motion.div>

          {/* RIGHT SIDEBAR TOGGLE TAB */}
          <motion.div
            className="absolute right-0 top-1/2 -translate-y-1/2 z-[201] pointer-events-auto hud-zone"
            animate={{ x: rightOpen ? -344 : 0 }}
            transition={{ type: 'spring', damping: 30, stiffness: 250 }}
          >
            <button
              onClick={() => setRightOpen(!rightOpen)}
              className="flex flex-col items-center gap-1.5 py-5 px-1.5 bg-cyan-400 border border-cyan-400 border-r-0 rounded-l-md text-black hover:bg-cyan-300 hover:border-cyan-300 transition-colors shadow-[-2px_0_12px_rgba(0,0,0,0.4)]"
            >
              {rightOpen ? <ChevronRight size={10} /> : <ChevronLeft size={10} />}
              <span className="text-[7px] font-mono tracking-[0.2em] font-bold text-black" style={{ writingMode: 'vertical-rl' }}>INTEL</span>
            </button>
          </motion.div>

          {/* RIGHT HUD CONTAINER — slides off right edge when hidden */}
          <motion.div
            className="absolute right-6 top-24 bottom-6 w-80 flex flex-col gap-4 z-[200] pointer-events-auto overflow-y-auto styled-scrollbar pr-2 hud-zone"
            animate={{ x: rightOpen ? 0 : 360 }}
            transition={{ type: 'spring', damping: 30, stiffness: 250 }}
          >
            <TopRightControls />

            {/* FIND / LOCATE */}
            <div className="flex-shrink-0">
              <FindLocateBar
                data={data}
                onLocate={(lat, lng, entityId, entityType) => {
                  setFlyToLocation({ lat, lng, ts: Date.now() });
                }}
                onFilter={(filterKey, value) => {
                  setActiveFilters(prev => {
                    const current = prev[filterKey] || [];
                    if (!current.includes(value)) {
                      return { ...prev, [filterKey]: [...current, value] };
                    }
                    return prev;
                  });
                }}
              />
            </div>

            {/* TOP RIGHT - MARKETS */}
            <div className="flex-shrink-0">
              <ErrorBoundary name="MarketsPanel">
                <MarketsPanel data={data} />
              </ErrorBoundary>
            </div>

            {/* SIGINT & RADIO INTERCEPTS */}
            <div className="flex-shrink-0">
              <ErrorBoundary name="RadioInterceptPanel">
                <RadioInterceptPanel
                  data={data}
                  isEavesdropping={isEavesdropping}
                  setIsEavesdropping={setIsEavesdropping}
                  eavesdropLocation={eavesdropLocation}
                  cameraCenter={cameraCenter}
                  selectedEntity={selectedEntity}
                />
              </ErrorBoundary>
            </div>

            {/* DATA FILTERS */}
            <div className="flex-shrink-0">
              <ErrorBoundary name="FilterPanel">
                <FilterPanel data={data} activeFilters={activeFilters} setActiveFilters={setActiveFilters} />
              </ErrorBoundary>
            </div>

            {/* BOTTOM RIGHT - NEWS FEED (fills remaining space) */}
            <div className="flex-1 min-h-0 flex flex-col">
              <ErrorBoundary name="NewsFeed">
                <NewsFeed data={data} selectedEntity={selectedEntity} regionDossier={regionDossier} regionDossierLoading={regionDossierLoading} />
              </ErrorBoundary>
            </div>
          </motion.div>

          {/* BOTTOM CENTER COORDINATE / LOCATION BAR — hidden when Sentinel-2 imagery overlay is open */}
          {!(selectedEntity?.type === 'region_dossier' && regionDossier?.sentinel2) && <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 1, duration: 1 }}
            className="absolute bottom-6 left-1/2 -translate-x-1/2 z-[200] pointer-events-auto flex flex-col items-center gap-2 hud-zone"
          >
            {/* LOCATE BAR — search by coordinates or place name */}
            <LocateBar onLocate={(lat, lng) => setFlyToLocation({ lat, lng, ts: Date.now() })} />

            <div
              className="bg-[var(--bg-primary)]/60 backdrop-blur-md border border-[var(--border-primary)] rounded-xl px-6 py-2.5 flex items-center gap-6 shadow-[0_4px_30px_rgba(0,0,0,0.2)] border-b-2 border-b-cyan-900"
            >
              {/* Coordinates */}
              <div className="flex flex-col items-center min-w-[120px]">
                <div className="text-[8px] text-[var(--text-muted)] font-mono tracking-[0.2em]">COORDINATES</div>
                <div className="text-[11px] text-cyan-400 font-mono font-bold tracking-wide">
                  {mouseCoords ? `${mouseCoords.lat.toFixed(4)}, ${mouseCoords.lng.toFixed(4)}` : '0.0000, 0.0000'}
                </div>
              </div>

              {/* Divider */}
              <div className="w-px h-8 bg-[var(--border-primary)]" />

              {/* Location name */}
              <div className="flex flex-col items-center min-w-[180px] max-w-[320px]">
                <div className="text-[8px] text-[var(--text-muted)] font-mono tracking-[0.2em]">LOCATION</div>
                <div className="text-[10px] text-[var(--text-secondary)] font-mono truncate max-w-[320px]">
                  {locationLabel || 'Hover over map...'}
                </div>
              </div>

              {/* Divider */}
              <div className="w-px h-8 bg-[var(--border-primary)]" />

              {/* Style preset (dropdown) */}
              <div ref={styleMenuRef} className="relative">
                {styleMenuOpen && (
                  <div className="absolute bottom-full mb-2 left-1/2 -translate-x-1/2 min-w-[130px] rounded-lg border border-cyan-900/60 bg-[var(--bg-secondary)]/95 backdrop-blur-md shadow-[0_8px_30px_rgba(0,0,0,0.45)] overflow-hidden z-[220]">
                    {STYLE_OPTIONS.map((style) => (
                      <button
                        key={style}
                        onClick={() => selectStyle(style)}
                        className={`w-full px-3 py-2 text-left text-[10px] font-mono tracking-wider transition-colors ${activeStyle === style ? "text-cyan-300 bg-cyan-950/40" : "text-[var(--text-secondary)] hover:bg-cyan-950/25 hover:text-cyan-300"}`}
                      >
                        {style}
                      </button>
                    ))}
                  </div>
                )}
                <button className="flex flex-col items-center cursor-pointer" onClick={() => setStyleMenuOpen((v) => !v)}>
                  <div className="text-[8px] text-[var(--text-muted)] font-mono tracking-[0.2em]">STYLE</div>
                  <div className="text-[11px] text-cyan-400 font-mono font-bold">{activeStyle}</div>
                </button>
              </div>

              {/* Divider */}
              <div className="w-px h-8 bg-[var(--border-primary)]" />

              {/* Space Weather */}
              <div className="flex flex-col items-center" title={`Kp Index: ${data?.space_weather?.kp_index ?? 'N/A'}`}>
                <div className="text-[8px] text-[var(--text-muted)] font-mono tracking-[0.2em]">SOLAR</div>
                <div className={`text-[11px] font-mono font-bold ${
                  (data?.space_weather?.kp_index ?? 0) >= 5 ? 'text-red-400' :
                  (data?.space_weather?.kp_index ?? 0) >= 4 ? 'text-yellow-400' :
                  'text-green-400'
                }`}>
                  {data?.space_weather?.kp_text || 'N/A'}
                </div>
              </div>
            </div>
          </motion.div>}
        </>
      )}

      {/* RESTORE UI BUTTON (If Hidden) */}
      {!uiVisible && (
        <button
          onClick={() => setUiVisible(true)}
          className="absolute bottom-6 right-6 z-[200] bg-[var(--bg-primary)]/60 backdrop-blur-md border border-[var(--border-primary)] rounded px-4 py-2 text-[10px] font-mono tracking-widest text-cyan-500 hover:text-cyan-300 hover:border-cyan-800 transition-colors pointer-events-auto"
        >
          RESTORE UI
        </button>
      )}

      {/* DYNAMIC SCALE BAR */}
      <div className="absolute bottom-[5.5rem] left-[26rem] z-[201] pointer-events-auto">
        <ScaleBar
          zoom={mapView.zoom}
          latitude={mapView.latitude}
          measureMode={measureMode}
          measurePoints={measurePoints}
          onToggleMeasure={() => {
            setMeasureMode(m => !m);
            if (measureMode) setMeasurePoints([]);
          }}
          onClearMeasure={() => setMeasurePoints([])}
        />
      </div>

      {/* STATIC CRT VIGNETTE */}
      <div className="absolute inset-0 pointer-events-none z-[2]"
        style={{
          background: 'radial-gradient(circle, transparent 40%, rgba(0,0,0,0.8) 100%)'
        }}
      />

      {/* SCANLINES OVERLAY */}
      <div className="absolute inset-0 pointer-events-none z-[3] opacity-5 bg-[linear-gradient(rgba(255,255,255,0.1)_1px,transparent_1px)]" style={{ backgroundSize: '100% 4px' }}></div>

      {/* SETTINGS PANEL */}
      <ErrorBoundary name="SettingsPanel">
        <SettingsPanel isOpen={settingsOpen} onClose={() => setSettingsOpen(false)} />
      </ErrorBoundary>

      {/* MAP LEGEND */}
      <ErrorBoundary name="MapLegend">
        <MapLegend isOpen={legendOpen} onClose={() => setLegendOpen(false)} />
      </ErrorBoundary>

      {/* ONBOARDING MODAL */}
      {showOnboarding && (
        <OnboardingModal
          onClose={() => setShowOnboarding(false)}
          onOpenSettings={() => { setShowOnboarding(false); setSettingsOpen(true); }}
        />
      )}

      {/* v0.4 CHANGELOG MODAL — shows once per version after onboarding */}
      {!showOnboarding && showChangelog && (
        <ChangelogModal onClose={() => setShowChangelog(false)} />
      )}

      {/* BACKEND DISCONNECTED BANNER */}
      {backendStatus === 'disconnected' && (
        <div className="absolute top-0 left-0 right-0 z-[9000] flex items-center justify-center py-2 bg-red-950/90 border-b border-red-500/40 backdrop-blur-sm">
          <span className="text-[10px] font-mono tracking-widest text-red-400">
            BACKEND OFFLINE — Cannot reach backend server. Check that the backend container is running and BACKEND_URL is correct.
          </span>
        </div>
      )}

    </main>
    </DashboardDataProvider>
  );
}
