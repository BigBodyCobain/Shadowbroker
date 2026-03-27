'use client';

import { useEffect, useState, useRef, useCallback, useMemo } from 'react';
import dynamic from 'next/dynamic';
import { motion } from 'framer-motion';
import { ChevronLeft, ChevronRight, ChevronUp, ChevronDown } from 'lucide-react';
import WorldviewLeftPanel from '@/components/WorldviewLeftPanel';

import NewsFeed from '@/components/NewsFeed';
import MarketsPanel from '@/components/MarketsPanel';
import FilterPanel from '@/components/FilterPanel';
import FindLocateBar from '@/components/FindLocateBar';
import TopRightControls from '@/components/TopRightControls';
import PredictionsPanel from '@/components/PredictionsPanel';
import SettingsPanel from '@/components/SettingsPanel';
import MapLegend from '@/components/MapLegend';
import ScaleBar from '@/components/ScaleBar';
import MeshTerminal from '@/components/MeshTerminal';
import MeshChat from '@/components/MeshChat';
import InfonetTerminal from '@/components/InfonetTerminal';
import { leaveWormhole, fetchWormholeState } from '@/mesh/wormholeClient';
import ShodanPanel from '@/components/ShodanPanel';
import GlobalTicker from '@/components/GlobalTicker';
import ErrorBoundary from '@/components/ErrorBoundary';
import OnboardingModal, { useOnboarding } from '@/components/OnboardingModal';
import ChangelogModal, { useChangelog } from '@/components/ChangelogModal';
import type { ActiveLayers, KiwiSDR, Scanner, SelectedEntity } from '@/types/dashboard';
import type { ShodanSearchMatch } from '@/types/shodan';
import { NOMINATIM_DEBOUNCE_MS } from '@/lib/constants';
import { API_BASE } from '@/lib/api';
import { useDataPolling, LAYER_TOGGLE_EVENT } from '@/hooks/useDataPolling';
import { useBackendStatus, useDataKey } from '@/hooks/useDataStore';
import { useReverseGeocode } from '@/hooks/useReverseGeocode';
import { useRegionDossier } from '@/hooks/useRegionDossier';
import {
  requestSecureMeshTerminalLauncherOpen,
  subscribeMeshTerminalOpen,
} from '@/lib/meshTerminalLauncher';
import {
  hasSentinelInfoBeenSeen,
  markSentinelInfoSeen,
  hasSentinelCredentials,
  getSentinelUsage,
} from '@/lib/sentinelHub';

// Use dynamic loads for Maplibre to avoid SSR window is not defined errors
const MaplibreViewer = dynamic(() => import('@/components/MaplibreViewer'), { ssr: false });

/* ── LOCATE BAR ── coordinate / place-name search above bottom status bar ── */
function LocateBar({ onLocate, onOpenChange }: { onLocate: (lat: number, lng: number) => void; onOpenChange?: (open: boolean) => void }) {
  const [open, setOpen] = useState(false);

  useEffect(() => { onOpenChange?.(open); }, [open]);
  const [value, setValue] = useState('');
  const [results, setResults] = useState<{ label: string; lat: number; lng: number }[]>([]);
  const [loading, setLoading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const searchAbortRef = useRef<AbortController | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  // Close when clicking outside
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
        setValue('');
        setResults([]);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  // Parse raw coordinate input: "31.8, 34.8" or "31.8 34.8" or "-12.3, 45.6"
  const parseCoords = (s: string): { lat: number; lng: number } | null => {
    const m = s.trim().match(/^([+-]?\d+\.?\d*)[,\s]+([+-]?\d+\.?\d*)$/);
    if (!m) return null;
    const lat = parseFloat(m[1]),
      lng = parseFloat(m[2]);
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
    if (searchAbortRef.current) searchAbortRef.current.abort();
    if (q.trim().length < 2) {
      setResults([]);
      return;
    }
    timerRef.current = setTimeout(async () => {
      setLoading(true);
      searchAbortRef.current = new AbortController();
      const signal = searchAbortRef.current.signal;
      try {
        // Try backend proxy first (has caching + rate-limit compliance)
        const res = await fetch(
          `${API_BASE}/api/geocode/search?q=${encodeURIComponent(q)}&limit=5`,
          { signal },
        );
        if (res.ok) {
          const data = await res.json();
          const mapped = (data?.results || []).map(
            (r: { label: string; lat: number; lng: number }) => ({
              label: r.label,
              lat: r.lat,
              lng: r.lng,
            }),
          );
          setResults(mapped);
        } else {
          // Backend proxy returned an error — fall back to direct Nominatim
          console.warn(`[Locate] Proxy returned HTTP ${res.status}, falling back to Nominatim`);
          const directRes = await fetch(
            `https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(q)}&format=json&limit=5`,
            { headers: { 'Accept-Language': 'en' }, signal },
          );
          const data = await directRes.json();
          setResults(
            data.map((r: { display_name: string; lat: string; lon: string }) => ({
              label: r.display_name,
              lat: parseFloat(r.lat),
              lng: parseFloat(r.lon),
            })),
          );
        }
      } catch (err) {
        if ((err as Error)?.name !== 'AbortError') {
          // Proxy completely failed — try direct Nominatim as last resort
          try {
            const directRes = await fetch(
              `https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(q)}&format=json&limit=5`,
              { headers: { 'Accept-Language': 'en' } },
            );
            const data = await directRes.json();
            setResults(
              data.map((r: { display_name: string; lat: string; lon: string }) => ({
                label: r.display_name,
                lat: parseFloat(r.lat),
                lng: parseFloat(r.lon),
              })),
            );
          } catch {
            setResults([]);
          }
        } else {
          setResults([]);
        }
      } finally {
        setLoading(false);
      }
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
        className="flex items-center gap-2 bg-[var(--bg-primary)]/80 border border-[var(--border-primary)] px-5 py-2 text-[11px] font-mono tracking-[0.15em] text-[var(--text-muted)] hover:text-cyan-400 hover:border-cyan-800 transition-colors"
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="13"
          height="13"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <circle cx="11" cy="11" r="8" />
          <path d="m21 21-4.3-4.3" />
        </svg>
        LOCATE
      </button>
    );
  }

  return (
    <div ref={containerRef} className="relative w-[520px]">
      <div className="flex items-center gap-2 bg-[var(--bg-primary)] border border-cyan-800/60 px-4 py-2.5 shadow-[0_0_20px_rgba(0,255,255,0.1)]">
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className="text-cyan-500 flex-shrink-0"
        >
          <circle cx="11" cy="11" r="8" />
          <path d="m21 21-4.3-4.3" />
        </svg>
        <input
          ref={inputRef}
          value={value}
          onChange={(e) => handleSearch(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Escape') {
              setOpen(false);
              setValue('');
              setResults([]);
            }
            if (e.key === 'Enter' && results.length > 0) handleSelect(results[0]);
          }}
          placeholder="Enter coordinates (31.8, 34.8) or place name..."
          className="flex-1 bg-transparent text-[12px] text-[var(--text-primary)] font-mono tracking-wider outline-none placeholder:text-[var(--text-muted)]"
        />
        {loading && (
          <div className="w-3 h-3 border border-cyan-500 border-t-transparent rounded-full animate-spin" />
        )}
        <button
          onClick={() => {
            setOpen(false);
            setValue('');
            setResults([]);
          }}
          className="text-[var(--text-muted)] hover:text-[var(--text-primary)]"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="10"
            height="10"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M18 6 6 18" />
            <path d="m6 6 12 12" />
          </svg>
        </button>
      </div>
      {results.length > 0 && (
        <div className="absolute bottom-full left-0 right-0 mb-1 bg-[var(--bg-secondary)] border border-[var(--border-primary)] overflow-hidden shadow-[0_-8px_30px_rgba(0,0,0,0.4)] max-h-[200px] overflow-y-auto styled-scrollbar">
          {results.map((r, i) => (
            <button
              key={i}
              onClick={() => handleSelect(r)}
              className="w-full text-left px-3 py-2 hover:bg-cyan-950/40 transition-colors border-b border-[var(--border-primary)]/50 last:border-0 flex items-center gap-2"
            >
              <svg
                xmlns="http://www.w3.org/2000/svg"
                width="10"
                height="10"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                className="text-cyan-500 flex-shrink-0"
              >
                <path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z" />
                <circle cx="12" cy="10" r="3" />
              </svg>
              <span className="text-[11px] text-[var(--text-secondary)] font-mono truncate">
                {r.label}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default function Dashboard() {
  const viewBoundsRef = useRef<{ south: number; west: number; north: number; east: number } | null>(null);
  const { mouseCoords, locationLabel, handleMouseCoords } = useReverseGeocode();
  const [selectedEntity, setSelectedEntity] = useState<SelectedEntity | null>(null);
  const [trackedSdr, setTrackedSdr] = useState<KiwiSDR | null>(null);
  const [trackedScanner, setTrackedScanner] = useState<Scanner | null>(null);
  const { regionDossier, regionDossierLoading, handleMapRightClick } = useRegionDossier(
    selectedEntity,
    setSelectedEntity,
  );

  const [uiVisible, setUiVisible] = useState(true);
  const [leftOpen, setLeftOpen] = useState(true);
  const [rightOpen, setRightOpen] = useState(true);
  const [tickerOpen, setTickerOpen] = useState(true);

  // Persist UI panel states
  useEffect(() => {
    const l = localStorage.getItem('sb_left_open');
    const r = localStorage.getItem('sb_right_open');
    const t = localStorage.getItem('sb_ticker_open');
    if (l !== null) setLeftOpen(l === 'true');
    if (r !== null) setRightOpen(r === 'true');
    if (t !== null) setTickerOpen(t === 'true');
  }, []);

  useEffect(() => {
    localStorage.setItem('sb_left_open', leftOpen.toString());
  }, [leftOpen]);

  useEffect(() => {
    localStorage.setItem('sb_right_open', rightOpen.toString());
  }, [rightOpen]);

  useEffect(() => {
    localStorage.setItem('sb_ticker_open', tickerOpen.toString());
  }, [tickerOpen]);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [legendOpen, setLegendOpen] = useState(false);
  const [terminalOpen, setTerminalOpen] = useState(false);
  const [terminalLaunchToken, setTerminalLaunchToken] = useState(0);
  const [infonetOpen, setInfonetOpen] = useState(false);
  const [meshChatLaunchRequest, setMeshChatLaunchRequest] = useState<{
    tab: 'infonet' | 'meshtastic' | 'dms';
    gate?: string;
    nonce: number;
  } | null>(null);
  const [dmCount, setDmCount] = useState(0);
  const [mapView, setMapView] = useState({ zoom: 2, latitude: 20 });
  const [locateBarOpen, setLocateBarOpen] = useState(false);
  const [measureMode, setMeasureMode] = useState(false);
  const [measurePoints, setMeasurePoints] = useState<{ lat: number; lng: number }[]>([]);

  const openMeshTerminal = useCallback(() => {
    setTerminalOpen(true);
    setTerminalLaunchToken((prev) => prev + 1);
  }, []);

  const openInfonet = useCallback(() => {
    setInfonetOpen(true);
  }, []);

  const openSecureTerminalLauncher = useCallback(() => {
    requestSecureMeshTerminalLauncherOpen('dashboard');
  }, []);

  useEffect(() => subscribeMeshTerminalOpen(openInfonet), [openInfonet]);

  const toggleInfonet = useCallback(() => {
    setInfonetOpen(prev => !prev);
  }, []);

  const [activeLayers, setActiveLayers] = useState<ActiveLayers>({
    // Aircraft — all ON
    flights: true,
    private: true,
    jets: true,
    military: true,
    tracked: true,
    gps_jamming: true,
    // Maritime — all ON
    ships_military: true,
    ships_cargo: true,
    ships_civilian: true,
    ships_passenger: true,
    ships_tracked_yachts: true,
    fishing_activity: true,
    // Space — only satellites
    satellites: true,
    gibs_imagery: false,
    highres_satellite: false,
    sentinel_hub: false,
    viirs_nightlights: false,
    // Hazards — no fire, rest ON
    earthquakes: true,
    firms: false,
    ukraine_alerts: true,
    weather_alerts: true,
    volcanoes: true,
    air_quality: true,
    // Infrastructure — military bases + internet outages only
    cctv: false,
    datacenters: false,
    internet_outages: true,
    power_plants: false,
    military_bases: true,
    trains: false,
    // SIGINT — all ON except HF digital spots
    kiwisdr: true,
    psk_reporter: false,
    satnogs: true,
    tinygs: true,
    scanners: true,
    sigint_meshtastic: true,
    sigint_aprs: true,
    // Overlays
    ukraine_frontline: true,
    global_incidents: true,
    day_night: true,
    correlations: true,
    // Shodan
    shodan_overlay: false,
  });
  const [shodanResults, setShodanResults] = useState<ShodanSearchMatch[]>([]);
  const [, setShodanQueryLabel] = useState('');
  const [shodanStyle, setShodanStyle] = useState<import('@/types/shodan').ShodanStyleConfig>({ shape: 'circle', color: '#16a34a', size: 'md' });
  useDataPolling();
  const backendStatus = useBackendStatus();
  const spaceWeather = useDataKey('space_weather');

  // Notify backend of layer toggles so it can skip disabled fetchers / stop streams.
  // After the POST completes, dispatch a custom event so useDataPolling immediately
  // refetches slow-tier data — this makes toggled layers (power plants, GDELT, etc.)
  // appear instantly instead of waiting up to 120 seconds.
  const layersTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const initialLayerSyncRef = useRef(false);
  useEffect(() => {
    const syncLayers = (triggerRefetch: boolean) =>
      fetch(`${API_BASE}/api/layers`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ layers: activeLayers }),
      }).then(() => {
        if (triggerRefetch) {
          window.dispatchEvent(new Event(LAYER_TOGGLE_EVENT));
        }
      }).catch((e) => console.error('Failed to update backend layers:', e));

    if (layersTimerRef.current) clearTimeout(layersTimerRef.current);
    if (!initialLayerSyncRef.current) {
      initialLayerSyncRef.current = true;
      void syncLayers(false);
    } else {
      layersTimerRef.current = setTimeout(() => {
        void syncLayers(true);
      }, 250);
    }
    return () => {
      if (layersTimerRef.current) clearTimeout(layersTimerRef.current);
    };
  }, [activeLayers]);

  // Left panel accordion state
  const [leftDataMinimized, setLeftDataMinimized] = useState(false);
  const [leftMeshExpanded, setLeftMeshExpanded] = useState(true);
  const [leftShodanMinimized, setLeftShodanMinimized] = useState(true);

  const launchMeshChatTab = useCallback((tab: 'infonet' | 'meshtastic' | 'dms', gate?: string) => {
    setLeftOpen(true);
    setLeftMeshExpanded(true);
    setMeshChatLaunchRequest({ tab, gate, nonce: Date.now() });
  }, []);

  const openLiveGateFromShell = useCallback((gate: string) => {
    setInfonetOpen(false);
    launchMeshChatTab('infonet', gate);
  }, [launchMeshChatTab]);

  // Right panel: which panel is "focused" (expanded). null = none focused, all normal.
  const [rightFocusedPanel, setRightFocusedPanel] = useState<string | null>(null);

  // Auto-expand Data Layers when user starts tracking an SDR/Scanner
  useEffect(() => {
    if (trackedSdr || trackedScanner) {
      setLeftDataMinimized(false);
      setLeftOpen(true);
    }
  }, [trackedSdr, trackedScanner]);

  // NASA GIBS satellite imagery state
  const [gibsDate, setGibsDate] = useState<string>(() => {
    const d = new Date();
    d.setDate(d.getDate() - 1);
    return d.toISOString().slice(0, 10);
  });
  const [gibsOpacity, setGibsOpacity] = useState(0.6);

  // Sentinel Hub satellite imagery state (user-provided Copernicus CDSE credentials)
  const [sentinelDate, setSentinelDate] = useState<string>(() => {
    const d = new Date();
    d.setDate(d.getDate() - 5); // Sentinel-2 has ~5-day revisit
    return d.toISOString().slice(0, 10);
  });
  const [sentinelOpacity, setSentinelOpacity] = useState(0.6);
  const [sentinelPreset, setSentinelPreset] = useState('TRUE-COLOR');
  const [showSentinelInfo, setShowSentinelInfo] = useState(false);
  const prevSentinelRef = useRef(false);

  // Show info modal the first time sentinel_hub is toggled on
  useEffect(() => {
    if (activeLayers.sentinel_hub && !prevSentinelRef.current) {
      if (!hasSentinelInfoBeenSeen()) {
        setShowSentinelInfo(true);
        markSentinelInfoSeen();
      }
      if (!hasSentinelCredentials()) {
        // No creds — open settings instead
        setSettingsOpen(true);
      }
    }
    prevSentinelRef.current = activeLayers.sentinel_hub;
  }, [activeLayers.sentinel_hub]);

  const [effects] = useState({
    bloom: true,
  });

  const [activeStyle, setActiveStyle] = useState('DEFAULT');

  const memoizedEffects = useMemo(
    () => ({ ...effects, bloom: effects.bloom && activeStyle !== 'DEFAULT', style: activeStyle }),
    [effects, activeStyle],
  );

  const handleFlyTo = useCallback(
    (lat: number, lng: number) => setFlyToLocation({ lat, lng, ts: Date.now() }),
    [],
  );

  const handleMeasureClick = useCallback(
    (pt: { lat: number; lng: number }) => {
      setMeasurePoints((prev) => (prev.length >= 3 ? prev : [...prev, pt]));
    },
    [],
  );

  const stylesList = ['DEFAULT', 'SATELLITE'];

  const cycleStyle = () => {
    setActiveStyle((prev) => {
      const idx = stylesList.indexOf(prev);
      const next = stylesList[(idx + 1) % stylesList.length];
      // Auto-toggle High-Res Satellite layer with SATELLITE style
      setActiveLayers((l) => ({ ...l, highres_satellite: next === 'SATELLITE' }));
      return next;
    });
  };

  const [activeFilters, setActiveFilters] = useState<Record<string, string[]>>({});
  const [flyToLocation, setFlyToLocation] = useState<{
    lat: number;
    lng: number;
    ts: number;
  } | null>(null);

  // Eavesdrop Mode State
  const [isEavesdropping] = useState(false);
  const [, setEavesdropLocation] = useState<{ lat: number; lng: number } | null>(null);
  const [, setCameraCenter] = useState<{ lat: number; lng: number } | null>(null);

  // Onboarding & connection status
  const { showOnboarding, setShowOnboarding } = useOnboarding();
  const { showChangelog, setShowChangelog } = useChangelog();

  return (
    <>
      <main className="fixed inset-0 w-full h-full bg-[var(--bg-primary)] overflow-hidden font-sans">
        {/* MAPLIBRE WEBGL OVERLAY */}
        <ErrorBoundary name="Map">
          <MaplibreViewer
            activeLayers={activeLayers}
            activeFilters={activeFilters}
            effects={memoizedEffects}
            onEntityClick={setSelectedEntity}
            selectedEntity={selectedEntity}
            flyToLocation={flyToLocation}
            gibsDate={gibsDate}
            gibsOpacity={gibsOpacity}
            sentinelDate={sentinelDate}
            sentinelOpacity={sentinelOpacity}
            sentinelPreset={sentinelPreset}
            isEavesdropping={isEavesdropping}
            onEavesdropClick={setEavesdropLocation}
            onCameraMove={setCameraCenter}
            onMouseCoords={handleMouseCoords}
            onRightClick={handleMapRightClick}
            regionDossier={regionDossier}
            regionDossierLoading={regionDossierLoading}
            onViewStateChange={setMapView}
            measureMode={measureMode}
            onMeasureClick={handleMeasureClick}
            measurePoints={measurePoints}
            viewBoundsRef={viewBoundsRef}
            trackedSdr={trackedSdr}
            setTrackedSdr={setTrackedSdr}
            trackedScanner={trackedScanner}
            setTrackedScanner={setTrackedScanner}
            shodanResults={shodanResults}
            shodanStyle={shodanStyle}
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
                <h1
                  className="text-2xl font-bold tracking-[0.4em] text-[var(--text-primary)] flex items-center gap-3 text-glow"
                  style={{ fontFamily: 'var(--font-roboto-mono), monospace' }}
                >
                  S H A D O W <span className="text-cyan-400">B R O K E R</span>
                </h1>
                <span className="text-[9px] text-[var(--text-muted)] font-mono tracking-[0.3em] mt-1 ml-1">
                  GLOBAL THREAT INTERCEPT
                </span>
              </div>
            </motion.div>

            {/* SYSTEM METRICS TOP LEFT */}
            <div className="absolute top-2 left-6 text-[8px] font-mono tracking-widest text-cyan-500/50 z-[200] pointer-events-none hud-zone">
              OPTIC VIS:113 SRC:180 DENS:1.42 0.8ms
            </div>

            {/* SYSTEM METRICS TOP RIGHT */}
            <div className="absolute top-2 right-6 text-[9px] flex flex-col items-end font-mono tracking-widest text-[var(--text-muted)] z-[200] pointer-events-none hud-zone">
              <div>RTX</div>
              <div>VSR</div>
            </div>

            {/* LEFT HUD CONTAINER — mirrors right side: one scroll container, scrollbar on LEFT edge */}
            <motion.div
              className="absolute left-6 top-24 bottom-9 w-80 flex flex-col gap-3 z-[200] pointer-events-auto overflow-y-auto styled-scrollbar pl-2 pr-2 hud-zone"
              style={{ direction: 'rtl' }}
              animate={{ x: leftOpen ? 0 : -360 }}
              transition={{ type: 'spring', damping: 30, stiffness: 250 }}
            >
              {/* 1. DATA LAYERS (Top) */}
              <div className="contents" style={{ direction: 'ltr' }}>
                <ErrorBoundary name="WorldviewLeftPanel">
                  <WorldviewLeftPanel
                    activeLayers={activeLayers}
                    setActiveLayers={setActiveLayers}
                    shodanResultCount={shodanResults.length}
                    onSettingsClick={() => setSettingsOpen(true)}
                    onLegendClick={() => setLegendOpen(true)}
                    gibsDate={gibsDate}
                    setGibsDate={setGibsDate}
                    gibsOpacity={gibsOpacity}
                    setGibsOpacity={setGibsOpacity}
                    sentinelDate={sentinelDate}
                    setSentinelDate={setSentinelDate}
                    sentinelOpacity={sentinelOpacity}
                    setSentinelOpacity={setSentinelOpacity}
                    sentinelPreset={sentinelPreset}
                    setSentinelPreset={setSentinelPreset}
                    onEntityClick={setSelectedEntity}
                    onFlyTo={handleFlyTo}
                    trackedSdr={trackedSdr}
                    setTrackedSdr={setTrackedSdr}
                    trackedScanner={trackedScanner}
                    setTrackedScanner={setTrackedScanner}
                    isMinimized={leftDataMinimized}
                    onMinimizedChange={setLeftDataMinimized}
                  />
                </ErrorBoundary>
              </div>

              {/* 2. MESH CHAT (Middle) */}
              <div className="contents" style={{ direction: 'ltr' }}>
                <MeshChat
                  onFlyTo={handleFlyTo}
                  expanded={leftMeshExpanded}
                  onExpandedChange={setLeftMeshExpanded}
                  onSettingsClick={() => setSettingsOpen(true)}
                  onTerminalToggle={openSecureTerminalLauncher}
                  launchRequest={meshChatLaunchRequest}
                />
              </div>

              {/* 3. SHODAN CONNECTOR (Bottom) */}
              <div className="contents" style={{ direction: 'ltr' }}>
                <ShodanPanel
                  currentResults={shodanResults}
                  onOpenSettings={() => setSettingsOpen(true)}
                  settingsOpen={settingsOpen}
                  onResultsChange={(results, queryLabel) => {
                    setShodanResults(results);
                    setShodanQueryLabel(queryLabel);
                    setActiveLayers((prev) => ({ ...prev, shodan_overlay: results.length > 0 }));
                  }}
                  onSelectEntity={setSelectedEntity}
                  onStyleChange={setShodanStyle}
                  isMinimized={leftShodanMinimized}
                  onMinimizedChange={setLeftShodanMinimized}
                />
              </div>
            </motion.div>

            {/* LEFT SIDEBAR TOGGLE TAB — aligns with Data Layers section */}
            <motion.div
              className="absolute left-0 top-[12.5rem] z-[201] pointer-events-auto hud-zone"
              animate={{ x: leftOpen ? 344 : 0 }}
              transition={{ type: 'spring', damping: 30, stiffness: 250 }}
            >
              <button
                onClick={() => setLeftOpen(!leftOpen)}
                className="flex flex-col items-center gap-1.5 py-5 px-1.5 bg-cyan-950/40 border border-cyan-800/50 border-l-0 rounded-r text-cyan-700 hover:text-cyan-400 hover:bg-cyan-950/60 hover:border-cyan-500/40 transition-colors"
              >
                {leftOpen ? <ChevronLeft size={10} /> : <ChevronRight size={10} />}
                <span
                  className="text-[7px] font-mono tracking-[0.2em] font-bold"
                  style={{ writingMode: 'vertical-rl', transform: 'rotate(180deg)' }}
                >
                  LAYERS
                </span>
              </button>
            </motion.div>

            {/* RIGHT SIDEBAR TOGGLE TAB — aligns with Oracle Predictions section */}
            <motion.div
              className="absolute right-0 top-[12.5rem] z-[201] pointer-events-auto hud-zone"
              animate={{ x: rightOpen ? -344 : 0 }}
              transition={{ type: 'spring', damping: 30, stiffness: 250 }}
            >
              <button
                onClick={() => setRightOpen(!rightOpen)}
                className="flex flex-col items-center gap-1.5 py-5 px-1.5 bg-cyan-950/40 border border-cyan-800/50 border-r-0 rounded-l text-cyan-700 hover:text-cyan-400 hover:bg-cyan-950/60 hover:border-cyan-500/40 transition-colors"
              >
                {rightOpen ? <ChevronRight size={10} /> : <ChevronLeft size={10} />}
                <span
                  className="text-[7px] font-mono tracking-[0.2em] font-bold"
                  style={{ writingMode: 'vertical-rl' }}
                >
                  INTEL
                </span>
              </button>
            </motion.div>

            {/* RIGHT HUD CONTAINER — slides off right edge when hidden */}
            <motion.div
              className="absolute right-6 top-24 bottom-9 w-80 flex flex-col gap-4 z-[200] pointer-events-auto overflow-y-auto styled-scrollbar pr-2 pl-2 hud-zone"
              animate={{ x: rightOpen ? 0 : 360 }}
              transition={{ type: 'spring', damping: 30, stiffness: 250 }}
            >
              <TopRightControls
                onTerminalToggle={openInfonet}
                onInfonetToggle={toggleInfonet}
                onSettingsClick={() => setSettingsOpen(true)}
                onMeshChatNavigate={launchMeshChatTab}
                dmCount={dmCount}
              />

              {/* FIND / LOCATE */}
              <div className="flex-shrink-0">
              <FindLocateBar
                onLocate={(lat, lng, _entityId, _entityType) => {
                  setFlyToLocation({ lat, lng, ts: Date.now() });
                }}
                onFilter={(filterKey, value) => {
                    setActiveFilters((prev) => {
                      const current = prev[filterKey] || [];
                      if (!current.includes(value)) {
                        return { ...prev, [filterKey]: [...current, value] };
                      }
                      return prev;
                    });
                  }}
                />
              </div>

              {/* GLOBAL TICKER REPLACES MARKETS PANEL - RENDERED OUTSIDE THIS DIV */}

              {/* ORACLE PREDICTIONS */}
              <div className={`flex-shrink-0 ${rightFocusedPanel && rightFocusedPanel !== 'predictions' ? 'hidden' : ''}`}>
                <ErrorBoundary name="PredictionsPanel">
                  <PredictionsPanel />
                </ErrorBoundary>
              </div>

              {/* DATA FILTERS */}
              <div className={`flex-shrink-0 ${rightFocusedPanel && rightFocusedPanel !== 'filters' ? 'hidden' : ''}`}>
                <ErrorBoundary name="FilterPanel">
                  <FilterPanel
                    activeFilters={activeFilters}
                    setActiveFilters={setActiveFilters}
                  />
                </ErrorBoundary>
              </div>

              {/* BOTTOM RIGHT - NEWS FEED (fills remaining space) */}
              <div className={`flex-1 min-h-0 flex flex-col ${rightFocusedPanel ? 'hidden' : ''}`}>
                <ErrorBoundary name="NewsFeed">
                  <NewsFeed
                    selectedEntity={selectedEntity}
                    regionDossier={regionDossier}
                    regionDossierLoading={regionDossierLoading}
                    onArticleClick={(idx, lat, lng) => {
                      if (lat !== undefined && lng !== undefined) {
                        setFlyToLocation({ lat, lng, ts: Date.now() });
                      }
                    }}
                  />
                </ErrorBoundary>
              </div>
            </motion.div>

            {/* BOTTOM CENTER COORDINATE / LOCATION BAR — hidden when fullscreen overlays are open */}
            {!(selectedEntity?.type === 'region_dossier' && regionDossier?.sentinel2) && selectedEntity?.type !== 'cctv' && selectedEntity?.type !== 'news' && (
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 1, duration: 1 }}
                className="absolute bottom-9 left-1/2 -translate-x-1/2 z-[200] pointer-events-auto flex flex-col items-center gap-2 hud-zone"
              >
                {/* LOCATE BAR — search by coordinates or place name */}
                <LocateBar
                  onLocate={(lat, lng) => setFlyToLocation({ lat, lng, ts: Date.now() })}
                  onOpenChange={setLocateBarOpen}
                />

                <div
                  className="bg-[#0a0a0a]/90 border border-cyan-900/40 px-5 py-1.5 flex items-center gap-5 border-b-2 border-b-cyan-800 cursor-pointer backdrop-blur-sm"
                  onClick={cycleStyle}
                >
                  {/* Coordinates */}
                  <div className="flex flex-col items-center min-w-[120px]">
                    <div className="text-[8px] text-[var(--text-muted)] font-mono tracking-[0.2em]">
                      COORDINATES
                    </div>
                    <div className="text-[11px] text-cyan-400 font-mono font-bold tracking-wide">
                      {mouseCoords
                        ? `${mouseCoords.lat.toFixed(4)}, ${mouseCoords.lng.toFixed(4)}`
                        : '0.0000, 0.0000'}
                    </div>
                  </div>

                  {/* Divider */}
                  <div className="w-px h-6 bg-[var(--border-primary)]" />

                  {/* Location name */}
                  <div className="flex flex-col items-center min-w-[160px] max-w-[280px]">
                    <div className="text-[8px] text-[var(--text-muted)] font-mono tracking-[0.2em]">
                      LOCATION
                    </div>
                    <div className="text-[10px] text-[var(--text-secondary)] font-mono truncate max-w-[280px]">
                      {locationLabel || 'Hover over map...'}
                    </div>
                  </div>

                  {/* Divider */}
                  <div className="w-px h-6 bg-[var(--border-primary)]" />

                  {/* Style preset (compact) */}
                  <div className="flex flex-col items-center">
                    <div className="text-[8px] text-[var(--text-muted)] font-mono tracking-[0.2em]">
                      STYLE
                    </div>
                    <div className="text-[11px] text-cyan-400 font-mono font-bold">
                      {activeStyle}
                    </div>
                  </div>

                  {/* Divider */}
                  <div className="w-px h-6 bg-[var(--border-primary)]" />

                  {/* Space Weather */}
                  {(() => {
                    const sw = spaceWeather as { kp_index?: number; kp_text?: string } | undefined;
                    return (
                      <div
                        className="flex flex-col items-center"
                        title={`Kp Index: ${sw?.kp_index ?? 'N/A'}`}
                      >
                        <div className="text-[8px] text-[var(--text-muted)] font-mono tracking-[0.2em]">
                          SOLAR
                        </div>
                        <div
                          className={`text-[11px] font-mono font-bold ${
                            (sw?.kp_index ?? 0) >= 5
                              ? 'text-red-400'
                              : (sw?.kp_index ?? 0) >= 4
                                ? 'text-yellow-400'
                                : 'text-green-400'
                          }`}
                        >
                          {sw?.kp_text || 'N/A'}
                        </div>
                      </div>
                    );
                  })()}
                </div>
              </motion.div>
            )}
          </>
        )}

        {/* RESTORE UI BUTTON (If Hidden) */}
        {!uiVisible && (
          <button
            onClick={() => setUiVisible(true)}
            className="absolute bottom-9 right-6 z-[200] bg-[var(--bg-primary)]/80 border border-[var(--border-primary)] px-4 py-2 text-[10px] font-mono tracking-widest text-cyan-500 hover:text-cyan-300 hover:border-cyan-800 transition-colors pointer-events-auto"
          >
            RESTORE UI
          </button>
        )}

        {/* DYNAMIC SCALE BAR — hidden when fullscreen overlays or locate bar are open */}
        {!(selectedEntity?.type === 'region_dossier' && regionDossier?.sentinel2) && selectedEntity?.type !== 'cctv' && selectedEntity?.type !== 'news' && !locateBarOpen && (
        <div className="absolute bottom-[7rem] left-[23rem] z-[201] pointer-events-auto">
          <ScaleBar
            zoom={mapView.zoom}
            latitude={mapView.latitude}
            measureMode={measureMode}
            measurePoints={measurePoints}
            onToggleMeasure={() => {
              setMeasureMode((m) => !m);
              if (measureMode) setMeasurePoints([]);
            }}
            onClearMeasure={() => setMeasurePoints([])}
          />
        </div>
        )}

        {/* STATIC CRT VIGNETTE */}
        <div
          className="absolute inset-0 pointer-events-none z-[2]"
          style={{
            background: 'radial-gradient(circle, transparent 40%, rgba(0,0,0,0.8) 100%)',
          }}
        />

        {/* SCANLINES OVERLAY */}
        <div
          className="absolute inset-0 pointer-events-none z-[3] opacity-[0.08] bg-[linear-gradient(rgba(255,255,255,0.1)_1px,transparent_1px)]"
          style={{ backgroundSize: '100% 4px' }}
        ></div>

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
            onOpenSettings={() => {
              setShowOnboarding(false);
              setSettingsOpen(true);
            }}
          />
        )}

        {/* v0.4 CHANGELOG MODAL — shows once per version after onboarding */}
        {!showOnboarding && showChangelog && (
          <ChangelogModal onClose={() => setShowChangelog(false)} />
        )}

        {/* SENTINEL HUB — first-time info modal */}
        {showSentinelInfo && (
          <div className="fixed inset-0 z-[10000] flex items-center justify-center">
            <div
              className="absolute inset-0 bg-black/90"
              onClick={() => setShowSentinelInfo(false)}
            />
            <div className="relative z-[10001] w-[520px] max-h-[80vh] bg-[var(--bg-secondary)] border border-purple-500/30 shadow-2xl shadow-purple-900/20 overflow-y-auto styled-scrollbar">
              <div className="p-6 space-y-4">
                <div className="flex items-center justify-between">
                  <h2 className="text-lg font-bold tracking-wider text-purple-300 font-mono">
                    SENTINEL HUB IMAGERY
                  </h2>
                  <button
                    onClick={() => setShowSentinelInfo(false)}
                    className="text-[var(--text-muted)] hover:text-white transition-colors text-xl leading-none"
                  >
                    &times;
                  </button>
                </div>

                <p className="text-[11px] text-[var(--text-secondary)] font-mono leading-relaxed">
                  You now have access to ESA Sentinel-2 satellite imagery directly on the map.
                  This uses the Copernicus Data Space Ecosystem with your own credentials.
                </p>

                <div className="space-y-2">
                  <h3 className="text-[10px] font-mono text-purple-400 tracking-widest">AVAILABLE LAYERS</h3>
                  <div className="grid grid-cols-2 gap-2">
                    {[
                      { name: 'True Color', desc: 'Natural RGB — see terrain, cities, water' },
                      { name: 'False Color IR', desc: 'Near-infrared — vegetation in red' },
                      { name: 'NDVI', desc: 'Vegetation health index (green = healthy)' },
                      { name: 'Moisture Index', desc: 'Soil & vegetation moisture levels' },
                    ].map((l) => (
                      <div key={l.name} className="p-2 border border-purple-900/30 bg-purple-950/10">
                        <div className="text-[10px] font-mono text-white">{l.name}</div>
                        <div className="text-[9px] text-[var(--text-muted)]">{l.desc}</div>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="space-y-2">
                  <h3 className="text-[10px] font-mono text-purple-400 tracking-widest">USAGE LIMITS (FREE TIER)</h3>
                  <div className="p-3 border border-[var(--border-primary)] bg-[var(--bg-primary)]/40 space-y-1.5">
                    <div className="flex justify-between text-[10px] font-mono">
                      <span className="text-[var(--text-muted)]">Monthly budget</span>
                      <span className="text-purple-300">10,000 requests</span>
                    </div>
                    <div className="flex justify-between text-[10px] font-mono">
                      <span className="text-[var(--text-muted)]">Cost per tile</span>
                      <span className="text-purple-300">0.25 PU (256&times;256px)</span>
                    </div>
                    <div className="flex justify-between text-[10px] font-mono">
                      <span className="text-[var(--text-muted)]">~Viewport loads/month</span>
                      <span className="text-purple-300">~500 (20 tiles each)</span>
                    </div>
                    <div className="flex justify-between text-[10px] font-mono">
                      <span className="text-[var(--text-muted)]">Empty tiles</span>
                      <span className="text-green-400">FREE (no data = no charge)</span>
                    </div>
                  </div>
                </div>

                <div className="space-y-2">
                  <h3 className="text-[10px] font-mono text-purple-400 tracking-widest">HOW IT WORKS</h3>
                  <ul className="text-[10px] text-[var(--text-secondary)] font-mono leading-relaxed space-y-1 list-disc list-inside">
                    <li>Sentinel-2 revisits every ~5 days — not every location has data every day</li>
                    <li>The date slider picks the end of a time window; zoomed out uses wider windows</li>
                    <li>Black patches = no satellite pass on that date range (normal)</li>
                    <li>Best results at zoom 8-14 — closer = sharper imagery (10m resolution)</li>
                    <li>Cloud filter auto-skips tiles with {'>'} 30% cloud cover</li>
                  </ul>
                </div>

                <button
                  onClick={() => setShowSentinelInfo(false)}
                  className="w-full py-2.5 bg-purple-500/20 border border-purple-500/40 text-purple-300 hover:bg-purple-500/30 transition-colors text-[11px] font-mono tracking-wider"
                >
                  GOT IT
                </button>
              </div>
            </div>
          </div>
        )}

        {/* MESH TERMINAL */}
        <MeshTerminal
          isOpen={terminalOpen}
          launchToken={terminalLaunchToken}
          onClose={() => setTerminalOpen(false)}
          onDmCount={setDmCount}
          onSettingsClick={() => setSettingsOpen(true)}
        />

        {/* INFONET TERMINAL */}
        <InfonetTerminal
          isOpen={infonetOpen}
          onClose={() => {
            setInfonetOpen(false);
            // Shut down Wormhole when the terminal closes so it doesn't stay running
            fetchWormholeState(false)
              .then((s) => {
                if (s?.ready || s?.running) return leaveWormhole();
              })
              .catch(() => {});
          }}
          onOpenLiveGate={openLiveGateFromShell}
        />

        {/* BACKEND DISCONNECTED BANNER */}
        {backendStatus === 'disconnected' && (
          <div className="absolute top-0 left-0 right-0 z-[9000] flex items-center justify-center py-2 bg-red-950/90 border-b border-red-500/40 backdrop-blur-sm">
            <span className="text-[10px] font-mono tracking-widest text-red-400">
              BACKEND OFFLINE — Cannot reach backend server. Check that the backend container is
              running and BACKEND_URL is correct.
            </span>
          </div>
        )}
        {/* BOTTOM TICKER TOGGLE TAB — moved to right to avoid Shodan overlap */}
        <motion.div
           className={`absolute bottom-0 right-[22rem] z-[8001] pointer-events-auto hud-zone transition-opacity duration-300 ${tickerOpen ? 'opacity-100' : 'opacity-40 hover:opacity-100'}`}
           animate={{ y: tickerOpen ? -28 : 0 }}
           transition={{ type: 'spring', damping: 30, stiffness: 250 }}
        >
          <button
            onClick={() => setTickerOpen(!tickerOpen)}
            className="flex items-center gap-2 px-3 py-1 bg-cyan-950/40 border border-cyan-800/50 border-b-0 rounded-t text-cyan-700 hover:text-cyan-400 hover:bg-cyan-950/60 hover:border-cyan-500/40 transition-colors"
          >
            <div className="text-[7.5px] font-mono tracking-[0.25em] font-bold uppercase">
              MARKETS
            </div>
            {tickerOpen ? <ChevronDown size={10} /> : <ChevronUp size={10} />}
          </button>
        </motion.div>

        {/* GLOBAL MARKETS TICKER (BOTTOM ANCHOR) */}
        <motion.div
          className="absolute bottom-0 left-0 right-0 z-[8000] h-7"
          animate={{ y: tickerOpen ? 0 : 28 }}
          transition={{ type: 'spring', damping: 30, stiffness: 250 }}
        >
          <ErrorBoundary name="GlobalTicker">
            <GlobalTicker />
          </ErrorBoundary>
        </motion.div>

      </main>
    </>
  );
}
