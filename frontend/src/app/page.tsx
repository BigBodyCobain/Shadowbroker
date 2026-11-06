'use client';

import { useEffect, useState, useRef, useCallback, useMemo } from 'react';
import dynamic from 'next/dynamic';
import { motion } from '@/lib/motion';
import { ChevronLeft, ChevronRight, ChevronUp, ChevronDown, Target } from 'lucide-react';
import WorldviewLeftPanel from '@/components/WorldviewLeftPanel';

import NewsFeed from '@/components/NewsFeed';
import MarketsPanel from '@/components/MarketsPanel';
import FilterPanel from '@/components/FilterPanel';
import FindLocateBar from '@/components/FindLocateBar';
import TopRightControls from '@/components/TopRightControls';
import TimelinePanel from '@/components/TimelinePanel';
import MapLegend from '@/components/MapLegend';
import ScaleBar from '@/components/ScaleBar';
import MeshChat from '@/components/MeshChat';
import { endInfonetTerminalSession } from '@/lib/infonetTerminalSession';
import { requestInfonetLeave } from '@/lib/infonetLeaveNotice';
import InfonetLeaveConfirm from '@/components/InfonetLeaveConfirm';
import ShodanPanel from '@/components/ShodanPanel';
import ReconPanel from '@/components/ReconPanel';
import ScmPanel from '@/components/ScmPanel';
import CyberThreatPanel from '@/components/CyberThreatPanel';
import EntityGraphPanel from '@/components/EntityGraphPanel';
import { isEntityGraphEligible } from '@/lib/entityGraph';
import AIIntelPanel from '@/components/AIIntelPanel';
import ToolsPanel from '@/components/ToolsPanel';
import GlobalTicker from '@/components/GlobalTicker';
import ErrorBoundary from '@/components/ErrorBoundary';
import OnboardingModal, { useOnboarding } from '@/components/OnboardingModal';
import ChangelogModal, { markChangelogSeen, useChangelog } from '@/components/ChangelogModal';
import StartupWarmupModal, { useStartupWarmupNotice } from '@/components/StartupWarmupModal';
import type { ActiveLayers, KiwiSDR, Scanner, SelectedEntity } from '@/types/dashboard';
import {
  getDefaultActiveLayers,
  getDefaultMapStyle,
  loadActiveFilters,
  loadActiveLayers,
  loadMapStyle,
  saveActiveFilters,
  saveActiveLayers,
  saveMapStyle,
  type MapStyle,
} from '@/lib/layerPreferences';
import type { ShodanSearchMatch } from '@/types/shodan';
import { API_BASE } from '@/lib/api';
import { findNewsArticle } from '@/lib/newsArticles';
import { useDataPolling, LAYER_TOGGLE_EVENT } from '@/hooks/useDataPolling';
import { useBackendStatus, useDataKey, useDataKeys } from '@/hooks/useDataStore';
import { useReverseGeocode } from '@/hooks/useReverseGeocode';
import { useRegionDossier } from '@/hooks/useRegionDossier';
import { useGtDossier } from '@/hooks/useGtDossier';
import { useAgentActions } from '@/hooks/useAgentActions';
import { useVoiceAgent, type UseVoiceAgentResult } from '@/hooks/useVoiceAgent';
import VoiceMicButton from '@/components/VoiceMicButton';
import VoiceHudPanel from '@/components/VoiceHudPanel';
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
// Heavy panels — defer until opened so they stay out of the critical path
const SettingsPanel = dynamic(() => import('@/components/SettingsPanel'), { ssr: false });
const MeshTerminal = dynamic(() => import('@/components/MeshTerminal'), { ssr: false });
const InfonetTerminal = dynamic(() => import('@/components/InfonetTerminal'), { ssr: false });

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

  const closeInfonet = useCallback(() => {
    requestInfonetLeave(() => {
      setInfonetOpen(false);
      void endInfonetTerminalSession();
    });
  }, []);

  const toggleInfonet = useCallback(() => {
    if (infonetOpen) {
      closeInfonet();
    } else {
      setInfonetOpen(true);
    }
  }, [closeInfonet, infonetOpen]);

  const [activeLayers, setActiveLayers] = useState<ActiveLayers>(getDefaultActiveLayers);
  // Backend-driven layer overrides. Additive on top of activeLayers, never
  // persisted and never pushed back — the operator's own toggles stay theirs.
  const [layerOverrides, setLayerOverrides] = useState<Partial<ActiveLayers>>({});
  const [activeStyle, setActiveStyle] = useState<MapStyle>(getDefaultMapStyle);
  const [activeFilters, setActiveFilters] = useState<Record<string, string[]>>({});
  const [layerPrefsHydrated, setLayerPrefsHydrated] = useState(false);

  // SSR/hydration cannot read localStorage in useState — load saved UI prefs after mount.
  useEffect(() => {
    setActiveLayers(loadActiveLayers());
    setActiveStyle(loadMapStyle());
    setActiveFilters(loadActiveFilters());
    setLayerPrefsHydrated(true);
  }, []);

  useEffect(() => {
    if (!layerPrefsHydrated) return;
    saveActiveLayers(activeLayers);
  }, [activeLayers, layerPrefsHydrated]);

  useEffect(() => {
    if (!layerPrefsHydrated) return;
    saveMapStyle(activeStyle);
  }, [activeStyle, layerPrefsHydrated]);

  // exposes the basemap to CSS so sensor filters can tame bright satellite imagery
  useEffect(() => {
    document.documentElement.setAttribute('data-basemap', activeStyle === 'SATELLITE' ? 'satellite' : 'map');
  }, [activeStyle]);

  // The bottom fade on the HUD columns is a "more below" cue, so it only shows while a
  // column actually has content past its bottom edge.
  useEffect(() => {
    const update = () => {
      document.querySelectorAll<HTMLElement>('.sb-left-col, .sb-right-col').forEach((el) => {
        const more = el.scrollHeight - el.clientHeight - el.scrollTop > 4;
        if (el.dataset.more !== String(more)) el.dataset.more = String(more);
      });
    };
    const ro = new ResizeObserver(update);
    const watch = () => {
      document.querySelectorAll<HTMLElement>('.sb-left-col, .sb-right-col').forEach((el) => {
        ro.observe(el);
        Array.from(el.children).forEach((c) => ro.observe(c));
      });
      update();
    };
    watch();
    // panels mount late (secondary boot) and expand/collapse, so re-check on a slow beat
    const id = window.setInterval(watch, 1500);
    document.addEventListener('scroll', update, true);
    return () => {
      ro.disconnect();
      window.clearInterval(id);
      document.removeEventListener('scroll', update, true);
    };
  }, []);

  useEffect(() => {
    if (!layerPrefsHydrated) return;
    saveActiveFilters(activeFilters);
  }, [activeFilters, layerPrefsHydrated]);

  const resetActiveLayers = useCallback(() => {
    setActiveLayers(getDefaultActiveLayers());
  }, []);
  const enableLayers = useCallback((keys: (keyof ActiveLayers)[]) => {
    setActiveLayers((prev) => {
      const next = { ...prev };
      for (const key of keys) next[key] = true;
      return next;
    });
  }, []);
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

  // Voice console actions resolve through this ref: the V shortcut is
  // registered here while the single useVoiceAgent binding site sits further
  // down, next to the other agent wiring (§3.5).
  const voiceRef = useRef<UseVoiceAgentResult | null>(null);

  // Global keyboard shortcuts
  useKeyboardShortcuts({
    toggleLeft: () => setLeftOpen((p) => !p),
    toggleRight: () => setRightOpen((p) => !p),
    toggleMarkets: () => setTickerOpen((p) => !p),
    openSettings: () => setSettingsOpen(true),
    openLegend: () => setLegendOpen((p) => !p),
    openShortcuts: () => setShortcutsOpen((p) => !p),
    voicePtt: {
      begin: () => { voiceRef.current?.beginPtt(); },
      end: () => { voiceRef.current?.endPtt(); },
    },
    deselectEntity: () => {
      // Escape also cancels an open mic or aborts a thinking turn (§5.4).
      voiceRef.current?.cancelActive();
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
    if (!secondaryBootReady || !layerPrefsHydrated) return;
    const syncLayers = (triggerRefetch: boolean) =>
      fetch(`${API_BASE}/api/layers`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ layers: activeLayers }),
      }).then((response) => {
        // Shared dashboards can view public layers without controlling the
        // server's fetchers or authenticated integrations.
        if (response.status === 401 || response.status === 403) return;
        if (!response.ok) throw new Error(`Layer sync failed (${response.status})`);
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
  }, [activeLayers, secondaryBootReady, layerPrefsHydrated]);

  // Poll for backend layer overrides so an agent can switch an overlay on
  // without the operator reloading. Overrides carry a TTL server-side, so a
  // missed poll self-corrects and a dropped backend just lets them lapse.
  useEffect(() => {
    if (!secondaryBootReady) return;
    let cancelled = false;
    const pollOverrides = () =>
      fetch(`${API_BASE}/api/layers`)
        .then((r) => r.json())
        .then((d) => {
          if (!cancelled) setLayerOverrides(d?.overrides ?? {});
        })
        .catch(() => {});
    void pollOverrides();
    const id = setInterval(pollOverrides, 5000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [secondaryBootReady]);

  // Left panel accordion state
  const [leftDataMinimized, setLeftDataMinimized] = useState(false);
  const [leftMeshExpanded, setLeftMeshExpanded] = useState(true);
  const dockIntroDone = useRef(false);
  // Screens under 1200px tall (1080p and laptops): start the comms panel collapsed so the
  // Data Layers list gets the room; users can still expand it.
  useEffect(() => {
    if (typeof window !== 'undefined' && window.innerHeight < 1200) setLeftMeshExpanded(false);
  }, []);

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

  const memoizedEffects = useMemo(
    () => ({ ...effects, bloom: effects.bloom && activeStyle !== 'DEFAULT', style: activeStyle }),
    [effects, activeStyle],
  );

  const [flyToLocation, setFlyToLocation] = useState<{
    lat: number;
    lng: number;
    zoom?: number;
    bounds?: [number, number, number, number];
    ts: number;
  } | null>(null);

  const handleFlyTo = useCallback(
    (lat: number, lng: number) => setFlyToLocation({ lat, lng, ts: Date.now() }),
    [],
  );

  const handleExpandEntityGraph = useCallback(() => {
    if (isEntityGraphEligible(selectedEntity)) setShowEntityGraph(true);
  }, [selectedEntity]);

  const handleArticleClick = useCallback(
    (idx: number, lat?: number, lng?: number, title?: string) => {
      if (lat !== undefined && lng !== undefined) {
        setFlyToLocation({ lat, lng, ts: Date.now() });
        // Also highlight the corresponding map alert
        if (title) {
          const alertKey = `${title}|${lat},${lng}`;
          setSelectedEntity({ id: alertKey, type: 'news' });
        }
      }
    },
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
      const next = stylesList[(idx + 1) % stylesList.length] as MapStyle;
      // Auto-toggle High-Res Satellite layer with SATELLITE style
      setActiveLayers((l) => ({ ...l, highres_satellite: next === 'SATELLITE' }));
      return next;
    });
  };

  // Overrides merge last so they win over both the operator's toggles and the
  // first-paint suppressions below.
  const firstPaintActiveLayers = useMemo<ActiveLayers>(() => {
    if (secondaryBootReady) return { ...activeLayers, ...layerOverrides };
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
      ...layerOverrides,
    };
  }, [activeLayers, layerOverrides, secondaryBootReady]);
  // Agent fly_to handler (sar_focus_aoi etc.) — wired here now that
  // setFlyToLocation is in scope.  show_image is routed through
  // useAgentActions at the top of Dashboard.
  useAgentActions(handleMapRightClick, ({ lat, lng, zoom }) => {
    setFlyToLocation({ lat, lng, zoom, ts: Date.now() });
  }, secondaryBootReady, (reference) => {
    const article = findNewsArticle(reference);
    if (article) setSelectedEntity({ id: article.id, type: 'news', name: article.title });
  });

  // Voice console (U4) — the single wiring site for client tool bindings (§3.5).
  const voice = useVoiceAgent({
    flyTo: (target: { lat: number; lng: number; zoom?: number; bounds?: [number, number, number, number] }) => {
      setFlyToLocation({ ...target, ts: Date.now() });
    },
    toggleLayer: (layer, enabled) => {
      if (!Object.prototype.hasOwnProperty.call(activeLayers, layer)) return null;
      // §3.4 executor discipline ("actual ≠ requested ⇒ ok:false"): the
      // updater below assigns `enabled` unconditionally at this key and no
      // other reducer can rewrite it before React commits, so the committed
      // value equals the requested value by construction — returning it IS
      // the applied state. (The refusal path above is the only way to get null.)
      setActiveLayers((prev) => ({ ...prev, [layer]: enabled }));
      return enabled;
    },
    applyMapStyle: (style) => {
      setActiveStyle(style);
      setActiveLayers((l) => ({ ...l, highres_satellite: style === 'SATELLITE' }));
      return style;
    },
    setFilter: (filterKey, values) => setActiveFilters((prev) => ({ ...prev, [filterKey]: values })),
    setSelectedEntity,
    // §2.6 selectedEntity regen trigger (U6): page-local selection widened
    // into the hook bindings; only its identity is read.
    selectedEntity,
    viewSummary: () => ({
      activeLayers: { ...activeLayers, ...layerOverrides },
      filters: activeFilters,
    }),
  });
  voiceRef.current = voice;

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
              {/* Brand mark — same artwork as the website */}
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src="/brand/sb-mark-72.webp" alt="" width={40} height={33} className="sb-brand-mark" />
              <div className="flex flex-col">
                <h1 className="sb-wordmark" aria-label="ShadowBroker">
                  SHADOW<span className="sb-wordmark-accent">BROKER</span>
                </h1>
                <span className="sb-wordmark-sub">
                  {t('brand.subtitle')}
                </span>
              </div>
            </motion.div>


            {/* SYSTEM METRICS TOP RIGHT — removed, label moved into TimelineScrubber */}

            {/* LEFT HUD CONTAINER — mirrors right side: one scroll container, scrollbar on LEFT edge */}
            <motion.div
              className="sb-left-col absolute left-6 top-24 bottom-[60px] w-80 flex flex-col gap-3 z-[201] pointer-events-auto overflow-y-auto styled-scrollbar pl-2 pr-2 hud-zone"
              style={{ direction: 'rtl' }}
              animate={{ x: leftOpen ? 0 : -360 }}
              transition={{ type: 'spring', damping: 30, stiffness: 250 }}
            >
              {/* 1. DATA LAYERS (Top) */}
              <div className="contents" style={{ direction: 'ltr' }}>
                {secondaryBootReady ? (
                  <ErrorBoundary name="WorldviewLeftPanel">
                    <WorldviewLeftPanel
                      activeLayers={firstPaintActiveLayers}
                      setActiveLayers={setActiveLayers}
                      onResetLayers={resetActiveLayers}
                      shodanResultCount={shodanResults.length}
                      onSettingsClick={() => setSettingsOpen(true)}
                      onLegendClick={() => setLegendOpen(true)}
                      mapStyle={activeStyle}
                      onMapStyleChange={(style) => {
                        setActiveStyle(style);
                        setActiveLayers((l) => ({ ...l, highres_satellite: style === 'SATELLITE' }));
                      }}
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
                  <div className="sb-panel px-3 py-3 font-mono text-cyan-500/70" aria-busy="true">
                    <div className="sb-title text-cyan-400">{t('nav.dataLayers')}</div>
                    <div className="mt-1 text-[10.5px] tracking-wider text-[var(--text-muted)]">{t('nav.prioritizingMapFeeds')}</div>
                    <div className="mt-3 flex flex-col gap-2.5" aria-hidden="true">
                      {[72, 64, 52, 58].map((w) => (
                        <div key={w} className="flex items-center justify-between">
                          <span className="sb-skel h-3 rounded-md" style={{ width: `${w}%` }} />
                          <span className="sb-skel h-3.5 w-7 rounded-full" />
                        </div>
                      ))}
                    </div>
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

              {/* 3. TOOLS — Shodan, Recon, Supply Chain, Cyber Threats and AI Intel share one tabbed card */}
              {secondaryBootReady && (
                <div className="contents" style={{ direction: 'ltr' }}>
                  <ToolsPanel
                    panels={{
                      shodan: (
                        <ShodanPanel
                          embedded
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
                        />
                      ),
                      recon: <ReconPanel embedded />,
                      scm: <ScmPanel embedded layerEnabled={activeLayers.scm_suppliers} />,
                      cyber: <CyberThreatPanel embedded layerEnabled={activeLayers.cyber_threats} />,
                      ai: (
                        <AIIntelPanel
                          embedded
                          onFlyTo={handleFlyTo}
                          pinPlacementMode={pinPlacementMode}
                          onPinPlacementModeChange={setPinPlacementMode}
                        />
                      ),
                    }}
                  />
                </div>
              )}
              {/* soft fade at the bottom edge = "more below" cue for the scrolling column */}
              <div aria-hidden="true" className="sb-col-fade" />
            </motion.div>

            {/* LEFT SIDEBAR TOGGLE TAB — aligns with Data Layers section */}
            <motion.div
              className={`absolute left-0 top-[12.5rem] z-[201] pointer-events-auto hud-zone ${leftOpen ? 'sb-edge-left-open' : ''}`}
              animate={{ x: leftOpen ? 344 : 0 }}
              transition={{ type: 'spring', damping: 30, stiffness: 250 }}
            >
              <button
                onClick={() => setLeftOpen(!leftOpen)}
                className="flex flex-col items-center gap-1.5 py-5 px-1.5 sb-edge-tab border border-l-0 rounded-r-lg text-cyan-400/80 hover:text-cyan-400 hover:bg-cyan-950/60 hover:border-cyan-500/40 transition-colors"
              >
                {leftOpen ? <ChevronLeft size={10} /> : <ChevronRight size={10} />}
                <span
                  className="text-[11px] font-mono tracking-[0.18em] font-bold"
                  style={{ writingMode: 'vertical-rl', transform: 'rotate(180deg)' }}
                >
                  {t('nav.layers')}
                </span>
              </button>
            </motion.div>

            {/* RIGHT SIDEBAR TOGGLE TAB */}
            <motion.div
              className={`absolute right-0 top-[12.5rem] z-[201] pointer-events-auto hud-zone ${rightOpen ? 'sb-edge-right-open' : ''}`}
              animate={{ x: rightOpen ? -424 : 0 }}
              transition={{ type: 'spring', damping: 30, stiffness: 250 }}
            >
              <button
                onClick={() => setRightOpen(!rightOpen)}
                className="flex flex-col items-center gap-1.5 py-5 px-1.5 sb-edge-tab border border-r-0 rounded-l-lg text-cyan-400/80 hover:text-cyan-400 hover:bg-cyan-950/60 hover:border-cyan-500/40 transition-colors"
              >
                {rightOpen ? <ChevronRight size={10} /> : <ChevronLeft size={10} />}
                <span
                  className="text-[11px] font-mono tracking-[0.18em] font-bold"
                  style={{ writingMode: 'vertical-rl' }}
                >
                  {t('nav.intel')}
                </span>
              </button>
            </motion.div>

            {/* RIGHT HUD CONTAINER — slides off right edge when hidden */}
            <motion.div
              className="sb-right-col absolute right-6 top-24 bottom-[60px] w-[400px] flex flex-col gap-4 z-[200] pointer-events-auto overflow-y-auto styled-scrollbar pr-2 pl-2 hud-zone"
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
                    activeLayers={activeLayers}
                    onEnableLayers={enableLayers}
                  />
                </ErrorBoundary>
              </div>

              {/* BOTTOM RIGHT - NEWS FEED (fills remaining space) */}
              <div className={`flex-1 min-h-[300px] flex flex-col ${rightFocusedPanel ? 'hidden' : ''}`}>
                <ErrorBoundary name="NewsFeed">
                  <NewsFeed
                    selectedEntity={selectedEntity}
                    regionDossier={regionDossier}
                    regionDossierLoading={regionDossierLoading}
                    gtDossier={gtDossier}
                    gtDossierLoading={gtDossierLoading}
                    onExpandEntityGraph={handleExpandEntityGraph}
                    onArticleClick={handleArticleClick}
                  />
                </ErrorBoundary>
              </div>
            </motion.div>

            {/* BOTTOM CENTER COORDINATE / LOCATION BAR — hidden when fullscreen overlays are open */}
            {!(selectedEntity?.type === 'region_dossier' && regionDossier?.sentinel2) && selectedEntity?.type !== 'cctv' && selectedEntity?.type !== 'news' && (
              <motion.div
                // intro only on first appearance; re-mounting after a dossier closes is instant
                initial={dockIntroDone.current ? false : { opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={dockIntroDone.current ? { duration: 0 } : { delay: 1, duration: 1 }}
                onAnimationComplete={() => {
                  dockIntroDone.current = true;
                }}
                className="sb-dock absolute bottom-[60px] left-1/2 -translate-x-1/2 z-[200] pointer-events-auto flex flex-col items-center gap-2 hud-zone"
              >
                {/* LOCATE BAR + VOICE MIC — flex row wrap (§5.1) */}
                <div className="relative flex items-center gap-2">
                  <LocateBar
                    onLocate={(lat, lng, bounds) => setFlyToLocation({ lat, lng, bounds, ts: Date.now() })}
                    onOpenChange={setLocateBarOpen}
                  />
                  <ErrorBoundary name="VoiceMicButton">
                    <VoiceMicButton />
                  </ErrorBoundary>
                  <button type="button" aria-label="Open mission workspace" className="sb-chip flex items-center gap-2 px-5 py-2 text-[11px] font-mono tracking-[0.15em] uppercase text-cyan-300 hover:text-cyan-100" onClick={() => { voice.missions.setOpen(true); voice.openPanel(); }}><Target size={12} aria-hidden="true" />Missions</button>
                  {voice.state.panelOpen && (
                    <ErrorBoundary name="VoiceHudPanel">
                      <VoiceHudPanel onSubmit={voice.submitText} onClose={voice.closePanel} missionWorkspace={voice.missions} />
                    </ErrorBoundary>
                  )}
                </div>

                <div className="sb-panel sb-statusbar px-6 py-2 flex items-center gap-6">
                  {/* Coordinates */}
                  <div className="flex flex-col items-center min-w-[140px] sb-wide-only">
                    <div className="text-[11px] text-[var(--text-muted)] font-mono tracking-[0.14em]">
                      {t('controls.coordinates')}
                    </div>
                    <div className="text-[14px] text-cyan-400 font-mono font-bold tracking-wide">
                      {mouseCoords
                        ? `${mouseCoords.lat.toFixed(4)}, ${mouseCoords.lng.toFixed(4)}`
                        : '—'}
                    </div>
                  </div>

                  {/* Divider */}
                  <div className="w-px h-6 bg-[var(--border-primary)] sb-wide-only" />

                  {/* Location name */}
                  <div className="flex flex-col items-center w-[260px] min-w-0 sb-wide-only">
                    <div className="text-[11px] text-[var(--text-muted)] font-mono tracking-[0.14em]">
                      {t('controls.location')}
                    </div>
                    <div className="text-[13px] text-[var(--text-secondary)] font-mono truncate w-full text-center">
                      {locationLabel || (mouseCoords ? '—' : t('controls.hoverMap'))}
                    </div>
                  </div>

                  {/* Divider */}
                  <div className="w-px h-6 bg-[var(--border-primary)] sb-wide-only" />

                  {/* Style preset (compact) */}
                  <button
                    type="button"
                    onClick={cycleStyle}
                    title={`Switch basemap to ${activeStyle === 'SATELLITE' ? 'MAP' : 'SATELLITE'} (also under VIEW)`}
                    aria-label={`Basemap: ${activeStyle === 'SATELLITE' ? 'satellite' : 'map'}. Click to switch.`}
                    className="sb-style-cell group flex flex-col items-center w-[104px] -my-1 py-1 rounded-lg border border-transparent hover:border-cyan-500/40 hover:bg-cyan-500/10 transition-colors cursor-pointer"
                  >
                    <span className="text-[11px] text-[var(--text-muted)] font-mono tracking-[0.14em] group-hover:text-cyan-300">
                      {t('controls.style')} ⇄
                    </span>
                    <span className="text-[14px] text-cyan-400 font-mono font-bold">
                      {activeStyle === 'SATELLITE' ? 'SATELLITE' : 'MAP'}
                    </span>
                  </button>

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
                        <div className="text-[11px] text-[var(--text-muted)] font-mono tracking-[0.14em]">
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
                      <div key={f.label} className="flex items-center gap-1 text-[10px] font-mono tracking-wider whitespace-nowrap">
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


        {/* MAP SCALE + MEASURE — sits on the map itself (bottom-left of the open map area) */}
        {!(selectedEntity?.type === 'region_dossier' && regionDossier?.sentinel2) && selectedEntity?.type !== 'cctv' && selectedEntity?.type !== 'news' && !locateBarOpen && (
        <div className="sb-scalebar absolute z-[201] pointer-events-auto">
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
            background:
              'radial-gradient(ellipse 120% 90% at 50% 45%, transparent 48%, rgba(2,6,14,0.82) 100%), radial-gradient(60% 50% at 50% 0%, rgba(30,155,255,0.07), transparent 70%)',
          }}
        />

        {/* SENSOR MODE OPTICS — vignette / grain / scanlines over the map only (HUD stays crisp) */}
        <div aria-hidden="true" className="sb-sensor-fx absolute inset-0 pointer-events-none z-[3]" />

        {/* SENSOR FILTERS for the map canvas. Each blends the optic grade with ~20% of the
            original colours so data categories stay distinguishable (usable, not just moody). */}
        <svg aria-hidden="true" width="0" height="0" style={{ position: 'absolute' }}>
          <defs>
            <filter id="sb-f-flir" colorInterpolationFilters="sRGB">
              <feColorMatrix type="matrix" values="0.33 0.33 0.33 0 0  0.33 0.33 0.33 0 0  0.33 0.33 0.33 0 0  0 0 0 1 0" result="lum" />
              <feComponentTransfer in="lum" result="iron">
                <feFuncR type="table" tableValues="0.06 0.3 0.62 0.9 1 1 1" />
                <feFuncG type="table" tableValues="0.02 0.03 0.08 0.32 0.62 0.86 1" />
                <feFuncB type="table" tableValues="0.12 0.36 0.5 0.2 0.05 0.25 0.9" />
              </feComponentTransfer>
              <feComposite in="iron" in2="SourceGraphic" operator="arithmetic" k1="0" k2="0.82" k3="0.22" k4="0" />
            </filter>
            <filter id="sb-f-flir-sat" colorInterpolationFilters="sRGB">
              <feColorMatrix type="matrix" values="0.33 0.33 0.33 0 0  0.33 0.33 0.33 0 0  0.33 0.33 0.33 0 0  0 0 0 1 0" />
              <feComponentTransfer result="iron">
                <feFuncR type="table" tableValues="0.06 0.26 0.46 0.56 0.6 0.62" />
                <feFuncG type="table" tableValues="0.02 0.03 0.07 0.16 0.24 0.3" />
                <feFuncB type="table" tableValues="0.12 0.32 0.42 0.32 0.28 0.32" />
              </feComponentTransfer>
              <feComposite in="iron" in2="SourceGraphic" operator="arithmetic" k1="0" k2="0.88" k3="0.12" k4="0" />
            </filter>
            <filter id="sb-f-nvg" colorInterpolationFilters="sRGB">
              <feColorMatrix type="matrix" values="0.1 0.2 0.05 0 0  0.4 0.9 0.2 0 0.04  0.1 0.25 0.05 0 0  0 0 0 1 0" />
              <feComponentTransfer result="phosphor">
                <feFuncG type="gamma" amplitude="1.12" exponent="1.08" offset="0" />
                <feFuncR type="gamma" amplitude="1" exponent="1.1" offset="0" />
              </feComponentTransfer>
              <feComposite in="phosphor" in2="SourceGraphic" operator="arithmetic" k1="0" k2="0.82" k3="0.24" k4="0" />
            </filter>
            <filter id="sb-f-crt" colorInterpolationFilters="sRGB">
              <feColorMatrix type="matrix" values="0.42 0.78 0.12 0 0  0.32 0.74 0.14 0 0.02  0.02 0.04 0.01 0 0  0 0 0 1 0" />
              <feComponentTransfer result="mono">
                <feFuncG type="gamma" amplitude="1.3" exponent="0.85" offset="0" />
              </feComponentTransfer>
              <feComposite in="mono" in2="SourceGraphic" operator="arithmetic" k1="0" k2="0.85" k3="0.18" k4="0" />
            </filter>
          </defs>
        </svg>

        {/* HEADER SCRIM — keeps the wordmark and HUD labels readable over busy map areas */}
        <div
          className="absolute inset-x-0 top-0 h-[230px] pointer-events-none z-[3]"
          style={{
            background:
              'radial-gradient(ellipse 520px 230px at 0% 0%, rgba(3,6,12,0.9), transparent 75%), linear-gradient(180deg, rgba(3,6,12,0.78) 0%, rgba(3,6,12,0.32) 55%, transparent 100%)',
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
        <AisUpstreamBanner onOpenApiKeys={() => setSettingsOpen(true)} />

        {/* ONBOARDING MODAL */}
        {showOnboarding && (
          <OnboardingModal
            onClose={() => {
              setShowOnboarding(false);
              markChangelogSeen();
              setShowChangelog(false);
            }}
            onOpenSettings={() => {
              setShowOnboarding(false);
              markChangelogSeen();
              setShowChangelog(false);
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
          onClose={closeInfonet}
          onOpenLiveGate={openLiveGateFromShell}
          onOpenDeadDrop={openDeadDropFromShell}
        />

        <InfonetLeaveConfirm />

        {/* BACKEND DISCONNECTED BANNER */}
        {backendStatus === 'disconnected' && (
          <div role="status" className="sb-offline-toast absolute top-5 left-1/2 -translate-x-1/2 z-[9000] flex items-center gap-2 px-4 py-2">
            <span className="sb-alert-dot text-[#ff3b5c] shrink-0" aria-hidden="true" />
            {(() => {
              const msg = String(t('backend.offline'));
              const cut = msg.indexOf(' — ');
              const head = cut > 0 ? msg.slice(0, cut) : msg;
              const rest = cut > 0 ? msg.slice(cut + 3) : '';
              return (
                <span className="flex items-baseline gap-x-3 gap-y-0.5 flex-wrap">
                  <span className="font-[family-name:var(--font-display)] text-[13px] font-bold tracking-[0.14em] text-[#ff6b84] whitespace-nowrap">
                    {head}
                  </span>
                  {rest && <span className="sb-prose text-[12.5px] text-[#ffc2cd]">{rest}</span>}
                </span>
              );
            })()}
          </div>
        )}
        {/* BOTTOM TICKER TOGGLE TAB — moved to center-right to avoid panel overlap */}
        <motion.div
           className={`absolute bottom-0 right-6 z-[8001] pointer-events-auto hud-zone transition-opacity duration-300 ${tickerOpen ? 'opacity-100' : 'opacity-40 hover:opacity-100'}`}
           animate={{ y: tickerOpen ? -28 : 0 }}
           transition={{ type: 'spring', damping: 30, stiffness: 250 }}
        >
          <button
            onClick={() => setTickerOpen(!tickerOpen)}
            className="flex items-center gap-2 px-3 py-1 sb-edge-tab border border-b-0 rounded-t-lg text-cyan-400/80 hover:text-cyan-400 hover:bg-cyan-950/60 hover:border-cyan-500/40 transition-colors"
          >
            <div className="text-[10px] font-mono tracking-[0.25em] font-bold uppercase">
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
