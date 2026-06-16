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
import TimelinePanel from '@/components/TimelinePanel';
import SettingsPanel from '@/components/SettingsPanel';
import MapLegend from '@/components/MapLegend';
import ScaleBar from '@/components/ScaleBar';
import MeshTerminal from '@/components/MeshTerminal';
import MeshChat from '@/components/MeshChat';
import InfonetTerminal from '@/components/InfonetTerminal';
import { endInfonetTerminalSession } from '@/lib/infonetTerminalSession';
import ShodanPanel from '@/components/ShodanPanel';
import ReconPanel from '@/components/ReconPanel';
import ScmPanel from '@/components/ScmPanel';
import EntityGraphPanel from '@/components/EntityGraphPanel';
import { isEntityGraphEligible } from '@/lib/entityGraph';
import AIIntelPanel from '@/components/AIIntelPanel';
import GlobalTicker from '@/components/GlobalTicker';
import ErrorBoundary from '@/components/ErrorBoundary';
import OnboardingModal, { useOnboarding } from '@/components/OnboardingModal';
import ChangelogModal, { useChangelog } from '@/components/ChangelogModal';
import StartupWarmupModal, { useStartupWarmupNotice } from '@/components/StartupWarmupModal';
import type { ActiveLayers, KiwiSDR, Scanner, SelectedEntity } from '@/types/dashboard';
import type { ShodanSearchMatch } from '@/types/shodan';
import { API_BASE } from '@/lib/api';
import { useDataPolling, LAYER_TOGGLE_EVENT } from '@/hooks/useDataPolling';
import { useBackendStatus, useDataKey, useDataKeys } from '@/hooks/useDataStore';
import { useReverseGeocode } from '@/hooks/useReverseGeocode';
import { useRegionDossier } from '@/hooks/useRegionDossier';
import { useGtDossier } from '@/hooks/useGtDossier';
import { useAgentActions } from '@/hooks/useAgentActions';
import { useFeedHealth } from '@/hooks/useFeedHealth';
import { useKeyboardShortcuts } from '@/hooks/useKeyboardShortcuts';
import KeyboardShortcutsOverlay from '@/components/KeyboardShortcutsOverlay';
import AlertToast from '@/components/AlertToast';
import AisUpstreamBanner from '@/components/AisUpstreamBanner';
import { useAlertToasts } from '@/hooks/useAlertToasts';
import { useWatchlist } from '@/hooks/useWatchlist';
import WatchlistWidget from '@/components/WatchlistWidget';
import {
  requestSecureMeshTerminalLauncherOpen,
  subscribeMeshTerminalOpen,
} from '@/lib/meshTerminalLauncher';
import {
  hasSentinelInfoBeenSeen,
  markSentinelInfoSeen,
  hasSentinelCredentials,
  checkBackendSentinelStatus,
} from '@/lib/sentinelHub';
import { useTranslation } from '@/i18n';
import { LocateBar } from './LocateBar';
import { SentinelInfoModal } from './SentinelInfoModal';
import SarAoiEditorModal from '@/components/SarAoiEditorModal';

// Use dynamic loads for Maplibre to avoid SSR window is not defined errors
const MaplibreViewer = dynamic(() => import('@/components/MaplibreViewer'), { ssr: false });

// LocateBar and SentinelInfoModal extracted to page-local modules (Sprint 4B)

export default function Dashboard() {
  const viewBoundsRef = useRef<{ south: number; west: number; north: number; east: number } | null>(null);
  const { t } = useTranslation();
  // Start the critical map data request before panel/control-plane effects.
  // Non-map widgets can warm up after this; first paint needs flights, ships, and intel first.
  useDataPolling();
  const { mouseCoords, locationLabel, handleMouseCoords } = useReverseGeocode();
  const [selectedEntity, setSelectedEntity] = useState<SelectedEntity | null>(null);
  const [showEntityGraph, setShowEntityGraph] = useState(false);
  useEffect(() => {
    setShowEntityGraph(false);
  }, [selectedEntity]);
  const [trackedSdr, setTrackedSdr] = useState<KiwiSDR | null>(null);
  const [trackedScanner, setTrackedScanner] = useState<Scanner | null>(null);
  const { regionDossier, regionDossierLoading, handleMapRightClick } = useRegionDossier(
    selectedEntity,
    setSelectedEntity,
  );

  // Agent can push satellite imagery to the same full-screen viewer as right-click,
  // and can fly the map to a point (e.g. sar_focus_aoi).  The hook is invoked
  // below — after setFlyToLocation is declared — so the fly_to callback can
  // close over it without hitting a temporal dead zone.

  const [uiVisible, setUiVisible] = useState(true);
  const [leftOpen, setLeftOpen] = useState(true);
  const [rightOpen, setRightOpen] = useState(true);
  const [tickerOpen, setTickerOpen] = useState(true);

  // Persist UI panel states
  useEffect(() => {
    const l = localStorage.getItem('sb_left_open');
    const r = localStorage.getItem('sb_right_open');
    const tk = localStorage.getItem('sb_ticker_open');
    if (l !== null) setLeftOpen(l === 'true');
    if (r !== null) setRightOpen(r === 'true');
    if (tk !== null) setTickerOpen(tk === 'true');
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

  // Issue #298: kick the one-time backend Sentinel-status check on mount.
  // This populates the cached value that ``hasSentinelCredentials()`` reads
  // synchronously elsewhere (MaplibreViewer's tile-URL memo, the
  // Sentinel-info modal flow). Fire-and-forget — the cache stays false
  // until resolved so the UI fails safely.
  useEffect(() => {
    void checkBackendSentinelStatus();
  }, []);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [legendOpen, setLegendOpen] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const [terminalOpen, setTerminalOpen] = useState(false);
  const [terminalLaunchToken, setTerminalLaunchToken] = useState(0);
  const [infonetOpen, setInfonetOpen] = useState(false);
  const [meshChatLaunchRequest, setMeshChatLaunchRequest] = useState<{
    tab: 'infonet' | 'meshtastic' | 'dms';
    gate?: string;
    peerId?: string;
    showSas?: boolean;
    nonce: number;
  } | null>(null);
  const [dmCount, setDmCount] = useState(0);
  const [mapView, setMapView] = useState({ zoom: 2, latitude: 20 });
  const [locateBarOpen, setLocateBarOpen] = useState(false);
  const [measureMode, setMeasureMode] = useState(false);
  const [measurePoints, setMeasurePoints] = useState<{ lat: number; lng: number }[]>([]);
  const [pinPlacementMode, setPinPlacementMode] = useState(false);

  // SAR AOI editor + map drop mode
  const [sarAoiEditorOpen, setSarAoiEditorOpen] = useState(false);
  const [sarAoiDropMode, setSarAoiDropMode] = useState(false);
  const [sarAoiDroppedCoords, setSarAoiDroppedCoords] = useState<{ lat: number; lng: number } | null>(null);
  const sarAoiListChangedRef = useRef(0);
  const [sarAoiListVersion, setSarAoiListVersion] = useState(0);

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
    setInfonetOpen((prev) => {
      if (prev) {
        void endInfonetTerminalSession();
        return false;
      }
      return true;
    });
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
    road_corridor_trends: false,
    malware_c2: false,
    submarine_cables: false,
    scm_suppliers: false,
    cyber_threats: false,
    telegram_osint: true,
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
    contradictions: true,
    uap_sightings: true,
    // Biosurveillance
    wastewater: true,
    // CrowdThreat is operator opt-in only.
    crowdthreat: false,
    gt_risk: false,
    // Shodan
    shodan_overlay: false,
    // AI Intel
    ai_intel: true,
    // SAR (Synthetic Aperture Radar)
    sar: true,
  });
  const regionLat =
    selectedEntity?.type === 'region_dossier' ? selectedEntity.extra?.lat : undefined;
  const regionLng =
    selectedEntity?.type === 'region_dossier' ? selectedEntity.extra?.lng : undefined;
  const { gtDossier, gtDossierLoading } = useGtDossier(
    typeof regionLat === 'number' ? regionLat : undefined,
    typeof regionLng === 'number' ? regionLng : undefined,
    regionDossier?.country?.name,
    activeLayers.gt_risk,
  );
  const [shodanResults, setShodanResults] = useState<ShodanSearchMatch[]>([]);
  const [, setShodanQueryLabel] = useState('');
  const [shodanStyle, setShodanStyle] = useState<import('@/types/shodan').ShodanStyleConfig>({ shape: 'circle', color: '#16a34a', size: 'md' });
  const backendStatus = useBackendStatus();
  const spaceWeather = useDataKey('space_weather');
  const feedHealth = useFeedHealth();
  const bootSignals = useDataKeys([
    'bootstrap_ready',
    'commercial_flights',
    'military_flights',
    'tracked_flights',
    'ships',
    'news',
    'threat_level',
  ] as const);
  const criticalPaintReady = Boolean(
    bootSignals.bootstrap_ready ||
      (bootSignals.commercial_flights?.length || 0) > 0 ||
      (bootSignals.military_flights?.length || 0) > 0 ||
      (bootSignals.tracked_flights?.length || 0) > 0 ||
      (bootSignals.ships?.length || 0) > 0 ||
      (bootSignals.news?.length || 0) > 0 ||
      bootSignals.threat_level,
  );
  const [secondaryBootReady, setSecondaryBootReady] = useState(false);

  useEffect(() => {
    if (secondaryBootReady) return;
    const delay = criticalPaintReady ? 900 : 5500;
    const id = window.setTimeout(() => setSecondaryBootReady(true), delay);
    return () => window.clearTimeout(id);
  }, [criticalPaintReady, secondaryBootReady]);

  // Global keyboard shortcuts
  useKeyboardShortcuts({
    toggleLeft: () => setLeftOpen((p) => !p),
    toggleRight: () => setRightOpen((p) => !p),
    toggleMarkets: () => setTickerOpen((p) => !p),
    openSettings: () => setSettingsOpen(true),
    openLegend: () => setLegendOpen((p) => !p),
    openShortcuts: () => setShortcutsOpen((p) => !p),
    deselectEntity: () => {
      if (shortcutsOpen) { setShortcutsOpen(false); return; }
      if (settingsOpen) { setSettingsOpen(false); return; }
      if (legendOpen) { setLegendOpen(false); return; }
      setSelectedEntity(null);
    },
    focusSearch: () => {
      const el = document.querySelector<HTMLInputElement>('[data-search-input]');
      el?.focus();
    },
  });

  // Alert toast notifications for high-severity news
  const { toasts, dismiss: dismissToast } = useAlertToasts();

  // Persistent entity watchlist
  const { items: watchlistItems, removeFromWatchlist, clearWatchlist } = useWatchlist();

  // Notify backend of layer toggles so it can skip disabled fetchers / stop streams.
  // After the POST completes, dispatch a custom event so useDataPolling immediately
  // refetches slow-tier data — this makes toggled layers (power plants, GDELT, etc.)
  // appear instantly instead of waiting up to 120 seconds.
  const layersTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const initialLayerSyncRef = useRef(false);
  useEffect(() => {
    if (!secondaryBootReady) return;
    const syncLayers = (triggerRefetch: boolean) =>
      fetch(`${API_BASE}/api/layers`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ layers: activeLayers }),
      }).then(() => {
        if (triggerRefetch) {
          window.dispatchEvent(new Event(LAYER_TOGGLE_EVENT));
        }
      }).catch((e) => console.warn('Backend layer sync will retry after runtime is reachable:', e));

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
  }, [activeLayers, secondaryBootReady]);

  // Left panel accordion state
  const [leftDataMinimized, setLeftDataMinimized] = useState(false);
  const [leftMeshExpanded, setLeftMeshExpanded] = useState(true);
  const [leftShodanMinimized, setLeftShodanMinimized] = useState(true);

  const launchMeshChatTab = useCallback(
    (
      tab: 'infonet' | 'meshtastic' | 'dms',
      gate?: string,
      peerId?: string,
      showSas?: boolean,
    ) => {
      setLeftOpen(true);
      setLeftMeshExpanded(true);
      setMeshChatLaunchRequest({ tab, gate, peerId, showSas, nonce: Date.now() });
    },
    [],
  );

  const openLiveGateFromShell = useCallback((gate: string) => {
    setInfonetOpen(false);
    launchMeshChatTab('infonet', gate);
  }, [launchMeshChatTab]);

  const openDeadDropFromShell = useCallback(
    (peerId: string, options?: { showSas?: boolean }) => {
      setInfonetOpen(false);
      launchMeshChatTab('dms', undefined, peerId, Boolean(options?.showSas));
    },
    [launchMeshChatTab],
  );

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

  const [flyToLocation, setFlyToLocation] = useState<{
    lat: number;
    lng: number;
    ts: number;
  } | null>(null);

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
  const firstPaintActiveLayers = useMemo<ActiveLayers>(() => {
    if (secondaryBootReady) return activeLayers;
    return {
      ...activeLayers,
      cctv: false,
      sar: false,
      gibs_imagery: false,
      highres_satellite: false,
      sentinel_hub: false,
      viirs_nightlights: false,
      road_corridor_trends: false,
      psk_reporter: false,
      tinygs: false,
      datacenters: false,
      power_plants: false,
    };
  }, [activeLayers, secondaryBootReady]);
  // Agent fly_to handler (sar_focus_aoi etc.) — wired here now that
  // setFlyToLocation is in scope.  show_image is routed through
  // useAgentActions at the top of Dashboard.
  useAgentActions(handleMapRightClick, ({ lat, lng }) => {
    setFlyToLocation({ lat, lng, ts: Date.now() });
  }, secondaryBootReady);

  // Eavesdrop Mode State
  const [isEavesdropping] = useState(false);
  const [, setEavesdropLocation] = useState<{ lat: number; lng: number } | null>(null);
  const [, setCameraCenter] = useState<{ lat: number; lng: number } | null>(null);

  // Onboarding & connection status
  const { showOnboarding, setShowOnboarding } = useOnboarding();
  const { showWarmupNotice, setShowWarmupNotice } = useStartupWarmupNotice();
  const { showChangelog, setShowChangelog } = useChangelog();

  return (
    <>
      <main className="fixed inset-0 w-full h-full bg-[var(--bg-primary)] overflow-hidden font-sans">
        {/* MAPLIBRE WEBGL OVERLAY */}
        <ErrorBoundary name="Map">
          <MaplibreViewer
            activeLayers={firstPaintActiveLayers}
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
            pinPlacementMode={pinPlacementMode}
            onPinPlaced={() => setPinPlacementMode(false)}
            sarAoiDropMode={sarAoiDropMode}
            onSarAoiDropped={(coords) => {
              setSarAoiDropMode(false);
              setSarAoiDroppedCoords(coords);
              setSarAoiEditorOpen(true);
            }}
            sarAoiListVersion={sarAoiListVersion}
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
                <span className="text-[11px] text-[var(--text-muted)] font-mono tracking-[0.3em] mt-1 ml-1">
                  {t('brand.subtitle')}
                </span>
              </div>
            </motion.div>

            {/* SYSTEM METRICS TOP LEFT */}
            <div className="absolute top-2 left-6 text-[11px] font-mono tracking-widest text-cyan-500/50 z-[200] pointer-events-none hud-zone">
              {t('brand.systemMetrics')}
            </div>

            {/* SYSTEM METRICS TOP RIGHT — removed, label moved into TimelineScrubber */}

            {/* LEFT HUD CONTAINER — mirrors right side: one scroll container, scrollbar on LEFT edge */}
            <motion.div
              className="absolute left-6 top-24 bottom-9 w-80 flex flex-col gap-3 z-[200] pointer-events-auto overflow-y-auto styled-scrollbar pl-2 pr-2 hud-zone"
              style={{ direction: 'rtl' }}
              animate={{ x: leftOpen ? 0 : -360 }}
              transition={{ type: 'spring', damping: 30, stiffness: 250 }}
            >
              {/* 1. DATA LAYERS (Top) */}
              <div className="contents" style={{ direction: 'ltr' }}>
                {secondaryBootReady ? (
                  <ErrorBoundary name="WorldviewLeftPanel">
                    <WorldviewLeftPanel
                      activeLayers={activeLayers}
                      setActiveLayers={setActiveLayers}
                      shodanResultCount={shodanResults.length}
                      onSettingsClick={() => setSettingsOpen(true)}
                      onLegendClick={() => setLegendOpen(true)}
                      onOpenSarAoiEditor={() => setSarAoiEditorOpen(true)}
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
                      viewBoundsRef={viewBoundsRef}
                    />
                  </ErrorBoundary>
                ) : (
                  <div className="bg-[#05090d]/95 border border-cyan-900/50 p-4 font-mono text-cyan-500/70">
                    <div className="text-[11px] tracking-[0.2em] text-cyan-400 font-bold">{t('nav.dataLayers')}</div>
                    <div className="mt-3 text-[10px] tracking-wider">{t('nav.prioritizingMapFeeds')}</div>
                  </div>
                )}
              </div>

              {/* 2. MESHTASTIC CHAT (Middle) */}
              {secondaryBootReady && (
                <div className="contents" style={{ direction: 'ltr' }}>
                  <MeshChat
                    onFlyTo={handleFlyTo}
                    expanded={leftMeshExpanded}
                    onExpandedChange={setLeftMeshExpanded}
                    onSettingsClick={() => setSettingsOpen(true)}
                    onTerminalToggle={openSecureTerminalLauncher}
                    onOpenLiveGate={openLiveGateFromShell}
                    onOpenDeadDrop={openDeadDropFromShell}
                    launchRequest={meshChatLaunchRequest}
                  />
                </div>
              )}

              {/* 3. SHODAN CONNECTOR (Bottom) */}
              {secondaryBootReady && (
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
              )}

              {/* 4. RECON + SCM */}
              {secondaryBootReady && (
                <div className="contents" style={{ direction: 'ltr' }}>
                  <ReconPanel />
                  <ScmPanel layerEnabled={activeLayers.scm_suppliers} />
                </div>
              )}

              {/* 5. AI INTEL */}
              {secondaryBootReady && (
                <div className="contents" style={{ direction: 'ltr' }}>
                  <AIIntelPanel
                    onFlyTo={handleFlyTo}
                    pinPlacementMode={pinPlacementMode}
                    onPinPlacementModeChange={setPinPlacementMode}
                  />
                </div>
              )}
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
                  {t('nav.layers')}
                </span>
              </button>
            </motion.div>

            {/* RIGHT SIDEBAR TOGGLE TAB */}
            <motion.div
              className="absolute right-0 top-[12.5rem] z-[201] pointer-events-auto hud-zone"
              animate={{ x: rightOpen ? -424 : 0 }}
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
                  {t('nav.intel')}
                </span>
              </button>
            </motion.div>

            {/* RIGHT HUD CONTAINER — slides off right edge when hidden */}
            <motion.div
              className="absolute right-6 top-24 bottom-9 w-[400px] flex flex-col gap-4 z-[200] pointer-events-auto overflow-y-auto styled-scrollbar pr-2 pl-2 hud-zone"
              animate={{ x: rightOpen ? 0 : 440 }}
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

              {/* EVENT TIMELINE */}
              {secondaryBootReady && (
                <div className={`flex-shrink-0 ${rightFocusedPanel && rightFocusedPanel !== 'predictions' ? 'hidden' : ''}`}>
                  <ErrorBoundary name="TimelinePanel">
                    <TimelinePanel />
                  </ErrorBoundary>
                </div>
              )}

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
                    gtDossier={gtDossier}
                    gtDossierLoading={gtDossierLoading}
                    onExpandEntityGraph={() => {
                      if (isEntityGraphEligible(selectedEntity)) setShowEntityGraph(true);
                    }}
                    onArticleClick={(idx, lat, lng, title) => {
                      if (lat !== undefined && lng !== undefined) {
                        setFlyToLocation({ lat, lng, ts: Date.now() });
                        // Also highlight the corresponding map alert
                        if (title) {
                          const alertKey = `${title}|${lat},${lng}`;
                          setSelectedEntity({ id: alertKey, type: 'news' });
                        }
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
                  className="bg-[#0a0a0a]/90 border border-cyan-900/40 px-6 py-2 flex items-center gap-6 border-b-2 border-b-cyan-800 cursor-pointer backdrop-blur-sm"
                  onClick={cycleStyle}
                >
                  {/* Coordinates */}
                  <div className="flex flex-col items-center min-w-[140px]">
                    <div className="text-[10px] text-[var(--text-muted)] font-mono tracking-[0.2em]">
                      {t('controls.coordinates')}
                    </div>
                    <div className="text-[14px] text-cyan-400 font-mono font-bold tracking-wide">
                      {mouseCoords
                        ? `${mouseCoords.lat.toFixed(4)}, ${mouseCoords.lng.toFixed(4)}`
                        : '0.0000, 0.0000'}
                    </div>
                  </div>

                  {/* Divider */}
                  <div className="w-px h-6 bg-[var(--border-primary)]" />

                  {/* Location name */}
                  <div className="flex flex-col items-center min-w-[180px] max-w-[320px]">
                    <div className="text-[10px] text-[var(--text-muted)] font-mono tracking-[0.2em]">
                      {t('controls.location')}
                    </div>
                    <div className="text-[13px] text-[var(--text-secondary)] font-mono truncate max-w-[320px]">
                      {locationLabel || t('controls.hoverMap')}
                    </div>
                  </div>

                  {/* Divider */}
                  <div className="w-px h-6 bg-[var(--border-primary)]" />

                  {/* Style preset (compact) */}
                  <div className="flex flex-col items-center">
                    <div className="text-[10px] text-[var(--text-muted)] font-mono tracking-[0.2em]">
                      {t('controls.style')}
                    </div>
                    <div className="text-[14px] text-cyan-400 font-mono font-bold">
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
                        <div className="text-[10px] text-[var(--text-muted)] font-mono tracking-[0.2em]">
                          {t('controls.solar')}
                        </div>
                        <div
                          className={`text-[14px] font-mono font-bold ${
                            (sw?.kp_index ?? 0) >= 5
                              ? 'text-red-400'
                              : (sw?.kp_index ?? 0) >= 4
                                ? 'text-yellow-400'
                                : 'text-green-400'
                          }`}
                        >
                          {sw?.kp_text || t('controls.na')}
                        </div>
                      </div>
                    );
                  })()}

                  {/* Divider */}
                  <div className="w-px h-6 bg-[var(--border-primary)]" />

                  {/* Feed Health */}
                  <div className="flex items-center gap-3">
                    {feedHealth.map((f) => (
                      <div key={f.label} className="flex items-center gap-1 text-[10px] font-mono tracking-wider">
                        <span className={`feed-dot feed-dot-${f.status}`} />
                        <span className="text-[var(--text-muted)]">{f.label}</span>
                        <span className="text-cyan-400 font-bold">{f.count}</span>
                      </div>
                    ))}
                  </div>
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
            {t('nav.restoreUi')}
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

        {/* WATCHLIST WIDGET */}
        <WatchlistWidget
          items={watchlistItems}
          onRemove={removeFromWatchlist}
          onClear={clearWatchlist}
          onFlyTo={handleFlyTo}
        />


        {/* SETTINGS PANEL */}
        <ErrorBoundary name="SettingsPanel">
          <SettingsPanel isOpen={settingsOpen} onClose={() => setSettingsOpen(false)} />
        </ErrorBoundary>

        {/* MAP LEGEND */}
        <ErrorBoundary name="MapLegend">
          <MapLegend isOpen={legendOpen} onClose={() => setLegendOpen(false)} />
        </ErrorBoundary>

        {/* KEYBOARD SHORTCUTS OVERLAY */}
        <KeyboardShortcutsOverlay isOpen={shortcutsOpen} onClose={() => setShortcutsOpen(false)} />

        {/* ALERT TOAST NOTIFICATIONS */}
        <AlertToast
          toasts={toasts}
          onDismiss={dismissToast}
          onFlyTo={handleFlyTo}
        />

        {/* AIS UPSTREAM OUTAGE BANNER — renders only when AIS is configured
            but the WebSocket upstream is unreachable. Tells users the empty
            ocean isn't their fault. */}
        <AisUpstreamBanner />

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

        {/* FIRST-RUN WARMUP NOTICE — shows once after onboarding */}
        {!showOnboarding && showWarmupNotice && (
          <StartupWarmupModal onClose={() => setShowWarmupNotice(false)} />
        )}

        {/* v0.4 CHANGELOG MODAL — shows once per version after onboarding */}
        {!showOnboarding && !showWarmupNotice && showChangelog && (
          <ChangelogModal onClose={() => setShowChangelog(false)} />
        )}

        {/* SENTINEL HUB — first-time info modal (extracted to SentinelInfoModal.tsx) */}
        {showSentinelInfo && (
          <SentinelInfoModal onClose={() => setShowSentinelInfo(false)} />
        )}

        {/* SAR AOI EDITOR — portals to document.body internally */}
        {(sarAoiEditorOpen || sarAoiDropMode) && (
          <SarAoiEditorModal
            onClose={() => { setSarAoiEditorOpen(false); setSarAoiDropMode(false); }}
            onRequestMapPick={() => { setSarAoiEditorOpen(false); setSarAoiDropMode(true); }}
            pickedCoords={sarAoiDroppedCoords}
            onPickConsumed={() => setSarAoiDroppedCoords(null)}
            onAoiListChanged={() => setSarAoiListVersion((v) => v + 1)}
            dropModeActive={sarAoiDropMode}
          />
        )}

        {/* MESH TERMINAL */}
        <MeshTerminal
          isOpen={terminalOpen}
          launchToken={terminalLaunchToken}
          onClose={() => setTerminalOpen(false)}
          onDmCount={setDmCount}
          onSettingsClick={() => setSettingsOpen(true)}
        />

        {showEntityGraph && selectedEntity && isEntityGraphEligible(selectedEntity) && (
          <EntityGraphPanel entity={selectedEntity} onClose={() => setShowEntityGraph(false)} />
        )}

        {/* INFONET TERMINAL */}
        <InfonetTerminal
          isOpen={infonetOpen}
          onClose={() => {
            setInfonetOpen(false);
            void endInfonetTerminalSession();
          }}
          onOpenLiveGate={openLiveGateFromShell}
          onOpenDeadDrop={openDeadDropFromShell}
        />

        {/* BACKEND DISCONNECTED BANNER */}
        {backendStatus === 'disconnected' && (
          <div className="absolute top-0 left-0 right-0 z-[9000] flex items-center justify-center py-2 bg-red-950/90 border-b border-red-500/40 backdrop-blur-sm">
            <span className="text-[10px] font-mono tracking-widest text-red-400">
              {t('backend.offline')}
            </span>
          </div>
        )}
        {/* BOTTOM TICKER TOGGLE TAB — moved to center-right to avoid panel overlap */}
        <motion.div
           className={`absolute bottom-0 right-[28rem] z-[8001] pointer-events-auto hud-zone transition-opacity duration-300 ${tickerOpen ? 'opacity-100' : 'opacity-40 hover:opacity-100'}`}
           animate={{ y: tickerOpen ? -28 : 0 }}
           transition={{ type: 'spring', damping: 30, stiffness: 250 }}
        >
          <button
            onClick={() => setTickerOpen(!tickerOpen)}
            className="flex items-center gap-2 px-3 py-1 bg-cyan-950/40 border border-cyan-800/50 border-b-0 rounded-t text-cyan-700 hover:text-cyan-400 hover:bg-cyan-950/60 hover:border-cyan-500/40 transition-colors"
          >
            <div className="text-[7.5px] font-mono tracking-[0.25em] font-bold uppercase">
              {t('nav.markets')}
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
