'use client';

// The guard must load before anything that could make a request.
import '@/viewer/netGuard';

import { useEffect, useState, useRef, useCallback, useMemo } from 'react';
import dynamic from 'next/dynamic';
import { motion } from '@/lib/motion';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import WorldviewLeftPanel from '@/components/WorldviewLeftPanel';
import NewsFeed from '@/components/NewsFeed';
import FilterPanel from '@/components/FilterPanel';
import FindLocateBar from '@/components/FindLocateBar';
import MapLegend from '@/components/MapLegend';
import ScaleBar from '@/components/ScaleBar';
import ScmPanel from '@/components/ScmPanel';
import CyberThreatPanel from '@/components/CyberThreatPanel';
import ErrorBoundary from '@/components/ErrorBoundary';
import AlertToast from '@/components/AlertToast';
import WatchlistWidget from '@/components/WatchlistWidget';
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
import { useDataPolling } from '@/hooks/useDataPolling';
import { useDataKey, useDataKeys } from '@/hooks/useDataStore';
import { useFeedHealth } from '@/hooks/useFeedHealth';
import { useAlertToasts } from '@/hooks/useAlertToasts';
import { useWatchlist } from '@/hooks/useWatchlist';
import { useTranslation } from '@/i18n';
import { LocateBar } from './LocateBar';
import { VIEWER_HIDDEN_LAYERS } from '@/viewer/config';
import { AboutModal, StaleBanner, ViewerHeaderCard, ViewerToolsPanel } from '@/viewer/ViewerChrome';
import SkillModal from '@/viewer/SkillModal';

const MaplibreViewer = dynamic(() => import('@/components/MaplibreViewer'), { ssr: false });

/** Basemaps the viewer offers. The app's third style needs the owner's tile proxy. */
const VIEWER_STYLES: MapStyle[] = ['DEFAULT', 'SATELLITE'];

function viewerLayers(layers: ActiveLayers): ActiveLayers {
  const next = { ...layers };
  for (const key of VIEWER_HIDDEN_LAYERS) {
    if (key in next) (next as Record<string, boolean>)[key] = false;
  }
  return next;
}

function viewerStyle(style: MapStyle): MapStyle {
  return VIEWER_STYLES.includes(style) ? style : 'DEFAULT';
}

const noop = () => {};

/** Open a third-party page in a new tab. The visitor's browser goes there by itself. */
function openExternal(raw: string | undefined | null): void {
  if (!raw) return;
  try {
    const url = new URL(raw);
    if (url.protocol !== 'https:' && url.protocol !== 'http:') return;
    window.open(url.href, '_blank', 'noopener,noreferrer');
  } catch {
    /* not a usable address */
  }
}

/** Receivers and scanners are shown as locations; listening happens on their own sites. */
const openReceiver = (sdr: KiwiSDR | null) => openExternal(sdr?.url);
const openScanner = (scanner: Scanner | null) => {
  if (scanner?.shortName) openExternal(`https://openmhz.com/system/${encodeURIComponent(scanner.shortName)}`);
};

export default function ViewerDashboard() {
  const viewBoundsRef = useRef<{ south: number; west: number; north: number; east: number } | null>(null);
  const { t } = useTranslation();
  useDataPolling();

  const [mouseCoords, setMouseCoords] = useState<{ lat: number; lng: number } | null>(null);
  const [selectedEntity, setSelectedEntity] = useState<SelectedEntity | null>(null);
  const [leftOpen, setLeftOpen] = useState(true);
  const [rightOpen, setRightOpen] = useState(true);
  const [legendOpen, setLegendOpen] = useState(false);
  const [aboutOpen, setAboutOpen] = useState(false);
  const [skillOpen, setSkillOpen] = useState(false);
  const [mapView, setMapView] = useState({ zoom: 2, latitude: 20 });
  const [locateBarOpen, setLocateBarOpen] = useState(false);
  const [measureMode, setMeasureMode] = useState(false);
  const [measurePoints, setMeasurePoints] = useState<{ lat: number; lng: number }[]>([]);
  const [leftDataMinimized, setLeftDataMinimized] = useState(false);

  useEffect(() => {
    const l = localStorage.getItem('sb_left_open');
    const r = localStorage.getItem('sb_right_open');
    if (l !== null) setLeftOpen(l === 'true');
    if (r !== null) setRightOpen(r === 'true');
    // A link ending in #skill opens the agent skill screen directly.
    if (window.location.hash === '#skill') {
      setSkillOpen(true);
      return;
    }
    // First visit: say what this page is.
    if (localStorage.getItem('sb_viewer_about_seen') !== '1') {
      setAboutOpen(true);
      localStorage.setItem('sb_viewer_about_seen', '1');
    }
  }, []);
  useEffect(() => {
    localStorage.setItem('sb_left_open', leftOpen.toString());
  }, [leftOpen]);
  useEffect(() => {
    localStorage.setItem('sb_right_open', rightOpen.toString());
  }, [rightOpen]);

  // Layer switches, filters and basemap live in this browser only.
  const [activeLayers, setActiveLayersRaw] = useState<ActiveLayers>(() => viewerLayers(getDefaultActiveLayers()));
  const [activeStyle, setActiveStyle] = useState<MapStyle>(() => viewerStyle(getDefaultMapStyle()));
  const [activeFilters, setActiveFilters] = useState<Record<string, string[]>>({});
  const [prefsHydrated, setPrefsHydrated] = useState(false);

  const setActiveLayers = useCallback<React.Dispatch<React.SetStateAction<ActiveLayers>>>((update) => {
    setActiveLayersRaw((prev) => viewerLayers(typeof update === 'function' ? update(prev) : update));
  }, []);

  useEffect(() => {
    setActiveLayersRaw(viewerLayers(loadActiveLayers()));
    setActiveStyle(viewerStyle(loadMapStyle()));
    setActiveFilters(loadActiveFilters());
    setPrefsHydrated(true);
  }, []);
  useEffect(() => {
    if (prefsHydrated) saveActiveLayers(activeLayers);
  }, [activeLayers, prefsHydrated]);
  useEffect(() => {
    if (prefsHydrated) saveMapStyle(activeStyle);
  }, [activeStyle, prefsHydrated]);
  useEffect(() => {
    if (prefsHydrated) saveActiveFilters(activeFilters);
  }, [activeFilters, prefsHydrated]);

  useEffect(() => {
    document.documentElement.setAttribute(
      'data-basemap',
      activeStyle === 'DEFAULT' ? 'map' : activeStyle.toLowerCase(),
    );
  }, [activeStyle]);

  // "More below" fade on the side columns.
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
    const id = window.setInterval(watch, 1500);
    document.addEventListener('scroll', update, true);
    return () => {
      ro.disconnect();
      window.clearInterval(id);
      document.removeEventListener('scroll', update, true);
    };
  }, []);

  const resetActiveLayers = useCallback(() => {
    setActiveLayers(getDefaultActiveLayers());
  }, [setActiveLayers]);
  const enableLayers = useCallback(
    (keys: (keyof ActiveLayers)[]) => {
      setActiveLayers((prev) => {
        const next = { ...prev };
        for (const key of keys) next[key] = true;
        return next;
      });
    },
    [setActiveLayers],
  );

  const spaceWeather = useDataKey('space_weather');
  const feedHealth = useFeedHealth();
  const bootSignals = useDataKeys([
    'commercial_flights',
    'military_flights',
    'tracked_flights',
    'ships',
    'news',
    'threat_level',
  ] as const);
  const criticalPaintReady = Boolean(
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
    const id = window.setTimeout(() => setSecondaryBootReady(true), criticalPaintReady ? 900 : 5500);
    return () => window.clearTimeout(id);
  }, [criticalPaintReady, secondaryBootReady]);

  // Keyboard: panels, legend, deselect. No settings or voice keys here.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) return;
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.key === 'Escape') {
        if (legendOpen) setLegendOpen(false);
        else setSelectedEntity(null);
      } else if (e.key === '[') setLeftOpen((p) => !p);
      else if (e.key === ']') setRightOpen((p) => !p);
      else if (e.key === 'k' || e.key === 'K') setLegendOpen((p) => !p);
      else if (e.key === '/') {
        const el = document.querySelector<HTMLInputElement>('[data-search-input]');
        if (el) {
          e.preventDefault();
          el.focus();
        }
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [legendOpen]);

  const { toasts, dismiss: dismissToast } = useAlertToasts();
  const { items: watchlistItems, removeFromWatchlist, clearWatchlist } = useWatchlist();

  // NASA GIBS imagery date (tiles load straight from NASA).
  const [gibsDate, setGibsDate] = useState<string>(() => {
    const d = new Date();
    d.setDate(d.getDate() - 1);
    return d.toISOString().slice(0, 10);
  });
  const [gibsOpacity, setGibsOpacity] = useState(0.6);

  const memoizedEffects = useMemo(
    () => ({ bloom: activeStyle !== 'DEFAULT', style: activeStyle }),
    [activeStyle],
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

  const handleArticleClick = useCallback((_idx: number, lat?: number, lng?: number, title?: string) => {
    if (lat !== undefined && lng !== undefined) {
      setFlyToLocation({ lat, lng, ts: Date.now() });
      if (title) setSelectedEntity({ id: `${title}|${lat},${lng}`, type: 'news' });
    }
  }, []);

  const handleMeasureClick = useCallback((pt: { lat: number; lng: number }) => {
    setMeasurePoints((prev) => (prev.length >= 3 ? prev : [...prev, pt]));
  }, []);

  const applyStyle = useCallback(
    (style: MapStyle) => {
      const next = viewerStyle(style);
      setActiveStyle(next);
      setActiveLayers((l) => ({ ...l, highres_satellite: next === 'SATELLITE' }));
    },
    [setActiveLayers],
  );
  const cycleStyle = () => {
    applyStyle(VIEWER_STYLES[(VIEWER_STYLES.indexOf(activeStyle) + 1) % VIEWER_STYLES.length]);
  };

  // Heavy overlays wait until the first data has painted.
  const paintLayers = useMemo<ActiveLayers>(() => {
    if (secondaryBootReady) return activeLayers;
    return {
      ...activeLayers,
      cctv: false,
      gibs_imagery: false,
      highres_satellite: false,
      viirs_nightlights: false,
      psk_reporter: false,
      tinygs: false,
      datacenters: false,
      power_plants: false,
    };
  }, [activeLayers, secondaryBootReady]);

  // Full-screen views (news dossier, camera) hide the dock and scale bar.
  const overlayOpen = selectedEntity?.type === 'news' || selectedEntity?.type === 'cctv';

  return (
    <main className="fixed inset-0 w-full h-full bg-[var(--bg-primary)] overflow-hidden font-sans">
      <ErrorBoundary name="Map">
        <MaplibreViewer
          activeLayers={paintLayers}
          activeStyle={activeStyle}
          activeFilters={activeFilters}
          effects={memoizedEffects}
          onEntityClick={setSelectedEntity}
          selectedEntity={selectedEntity}
          flyToLocation={flyToLocation}
          gibsDate={gibsDate}
          gibsOpacity={gibsOpacity}
          onMouseCoords={setMouseCoords}
          onRightClick={noop}
          regionDossier={null}
          regionDossierLoading={false}
          onViewStateChange={setMapView}
          measureMode={measureMode}
          onMeasureClick={handleMeasureClick}
          measurePoints={measurePoints}
          viewBoundsRef={viewBoundsRef}
          trackedSdr={null}
          setTrackedSdr={openReceiver}
          trackedScanner={null}
          setTrackedScanner={openScanner}
          shodanResults={[]}
        />
      </ErrorBoundary>

      {/* WORDMARK */}
      <motion.div
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 1 }}
        className="absolute top-6 left-6 z-[200] pointer-events-none flex items-center gap-4 hud-zone"
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/brand/sb-mark-72.webp" alt="" width={40} height={33} className="sb-brand-mark" />
        <div className="flex flex-col">
          <h1 className="sb-wordmark" aria-label="ShadowBroker">
            SHADOW<span className="sb-wordmark-accent">BROKER</span>
          </h1>
          <span className="sb-wordmark-sub">{t('brand.subtitle')}</span>
        </div>
      </motion.div>

      {/* LEFT: DATA LAYERS + REFERENCE LISTS */}
      <motion.div
        className="sb-left-col absolute left-6 top-24 bottom-[32px] w-80 flex flex-col gap-3 z-[201] pointer-events-auto overflow-y-auto styled-scrollbar pl-2 pr-2 hud-zone"
        style={{ direction: 'rtl' }}
        animate={{ x: leftOpen ? 0 : -360 }}
        transition={{ type: 'spring', damping: 30, stiffness: 250 }}
      >
        <div className="contents" style={{ direction: 'ltr' }}>
          {secondaryBootReady ? (
            <ErrorBoundary name="WorldviewLeftPanel">
              <WorldviewLeftPanel
                activeLayers={paintLayers}
                setActiveLayers={setActiveLayers}
                onResetLayers={resetActiveLayers}
                onLegendClick={() => setLegendOpen(true)}
                mapStyle={activeStyle}
                onMapStyleChange={applyStyle}
                gibsDate={gibsDate}
                setGibsDate={setGibsDate}
                gibsOpacity={gibsOpacity}
                setGibsOpacity={setGibsOpacity}
                onEntityClick={setSelectedEntity}
                onFlyTo={handleFlyTo}
                trackedSdr={null}
                setTrackedSdr={noop}
                trackedScanner={null}
                setTrackedScanner={noop}
                isMinimized={leftDataMinimized}
                onMinimizedChange={setLeftDataMinimized}
                viewBoundsRef={viewBoundsRef}
              />
            </ErrorBoundary>
          ) : (
            <div className="sb-panel px-3 py-3 font-mono text-cyan-500/70" aria-busy="true">
              <div className="sb-title text-cyan-400">{t('nav.dataLayers')}</div>
              <div className="mt-1 text-[10.5px] tracking-wider text-[var(--text-muted)]">
                {t('nav.prioritizingMapFeeds')}
              </div>
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
        {secondaryBootReady && (
          <div className="contents" style={{ direction: 'ltr' }}>
            <ViewerToolsPanel
              panels={{
                scm: <ScmPanel embedded layerEnabled={activeLayers.scm_suppliers} />,
                cyber: <CyberThreatPanel embedded layerEnabled={activeLayers.cyber_threats} />,
              }}
            />
          </div>
        )}
        <div aria-hidden="true" className="sb-col-fade" />
      </motion.div>

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
          <span className="text-[11px] font-mono tracking-[0.18em] font-bold" style={{ writingMode: 'vertical-rl' }}>
            {t('nav.intel')}
          </span>
        </button>
      </motion.div>

      {/* RIGHT: VIEWER CARD, FIND, FILTERS, NEWS */}
      <motion.div
        className="sb-right-col absolute right-6 top-24 bottom-[32px] w-[400px] flex flex-col gap-4 z-[200] pointer-events-auto overflow-y-auto styled-scrollbar pr-2 pl-2 hud-zone"
        animate={{ x: rightOpen ? 0 : 440 }}
        transition={{ type: 'spring', damping: 30, stiffness: 250 }}
      >
        <ViewerHeaderCard onAbout={() => setAboutOpen(true)} onSkill={() => setSkillOpen(true)} />

        <div className="flex-shrink-0">
          <FindLocateBar
            onLocate={(lat, lng) => setFlyToLocation({ lat, lng, ts: Date.now() })}
            onFilter={(filterKey, value) => {
              setActiveFilters((prev) => {
                const current = prev[filterKey] || [];
                return current.includes(value) ? prev : { ...prev, [filterKey]: [...current, value] };
              });
            }}
          />
        </div>

        <div className="flex-shrink-0">
          <ErrorBoundary name="FilterPanel">
            <FilterPanel
              activeFilters={activeFilters}
              setActiveFilters={setActiveFilters}
              activeLayers={activeLayers}
              onEnableLayers={enableLayers}
            />
          </ErrorBoundary>
        </div>

        <div className="flex-1 min-h-[300px] flex flex-col">
          <ErrorBoundary name="NewsFeed">
            <NewsFeed
              selectedEntity={selectedEntity}
              regionDossier={null}
              regionDossierLoading={false}
              gtDossier={null}
              gtDossierLoading={false}
              onArticleClick={handleArticleClick}
            />
          </ErrorBoundary>
        </div>
      </motion.div>

      {/* BOTTOM: LOCATE + STATUS BAR */}
      {!overlayOpen && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 1, duration: 1 }}
          className="sb-dock absolute bottom-[32px] left-1/2 -translate-x-1/2 z-[200] pointer-events-auto flex flex-col items-center gap-2 hud-zone"
        >
          <LocateBar
            onLocate={(lat, lng, bounds) => setFlyToLocation({ lat, lng, bounds, ts: Date.now() })}
            onOpenChange={setLocateBarOpen}
          />
          <div className="sb-panel sb-statusbar px-6 py-2 flex items-center gap-6">
            <div className="flex flex-col items-center min-w-[140px] sb-wide-only">
              <div className="text-[11px] text-[var(--text-muted)] font-mono tracking-[0.14em]">
                {t('controls.coordinates')}
              </div>
              <div className="text-[14px] text-cyan-400 font-mono font-bold tracking-wide">
                {mouseCoords ? `${mouseCoords.lat.toFixed(4)}, ${mouseCoords.lng.toFixed(4)}` : '—'}
              </div>
            </div>
            <div className="w-px h-6 bg-[var(--border-primary)] sb-wide-only" />
            <button
              type="button"
              onClick={cycleStyle}
              title={`Switch basemap to ${activeStyle === 'DEFAULT' ? 'SATELLITE' : 'MAP'} (also under VIEW)`}
              aria-label={`Basemap: ${activeStyle === 'DEFAULT' ? 'map' : activeStyle.toLowerCase()}. Click to switch.`}
              className="sb-style-cell group flex flex-col items-center w-[104px] -my-1 py-1 rounded-lg border border-transparent hover:border-cyan-500/40 hover:bg-cyan-500/10 transition-colors cursor-pointer"
            >
              <span className="text-[11px] text-[var(--text-muted)] font-mono tracking-[0.14em] group-hover:text-cyan-300">
                {t('controls.style')} ⇄
              </span>
              <span className="text-[14px] text-cyan-400 font-mono font-bold">
                {activeStyle === 'DEFAULT' ? 'MAP' : activeStyle}
              </span>
            </button>
            <div className="w-px h-6 bg-[var(--border-primary)]" />
            {(() => {
              const sw = spaceWeather as { kp_index?: number; kp_text?: string } | undefined;
              return (
                <div className="flex flex-col items-center" title={`Kp Index: ${sw?.kp_index ?? 'N/A'}`}>
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
            <div className="w-px h-6 bg-[var(--border-primary)]" />
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

      {!overlayOpen && !locateBarOpen && (
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

      {/* VIGNETTE, SENSOR OPTICS, SCANLINES (same look as the full app) */}
      <div
        className="absolute inset-0 pointer-events-none z-[2]"
        style={{
          background:
            'radial-gradient(ellipse 120% 90% at 50% 45%, transparent 48%, rgba(2,6,14,0.82) 100%), radial-gradient(60% 50% at 50% 0%, rgba(30,155,255,0.07), transparent 70%)',
        }}
      />
      <div aria-hidden="true" className="sb-sensor-fx absolute inset-0 pointer-events-none z-[3]" />
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
      <div
        className="absolute inset-x-0 top-0 h-[230px] pointer-events-none z-[3]"
        style={{
          background:
            'radial-gradient(ellipse 520px 230px at 0% 0%, rgba(3,6,12,0.9), transparent 75%), linear-gradient(180deg, rgba(3,6,12,0.78) 0%, rgba(3,6,12,0.32) 55%, transparent 100%)',
        }}
      />
      <div
        className="absolute inset-0 pointer-events-none z-[3] opacity-[0.08] bg-[linear-gradient(rgba(255,255,255,0.1)_1px,transparent_1px)]"
        style={{ backgroundSize: '100% 4px' }}
      />

      <WatchlistWidget
        items={watchlistItems}
        onRemove={removeFromWatchlist}
        onClear={clearWatchlist}
        onFlyTo={handleFlyTo}
      />

      <ErrorBoundary name="MapLegend">
        <MapLegend isOpen={legendOpen} onClose={() => setLegendOpen(false)} />
      </ErrorBoundary>

      <AlertToast toasts={toasts} onDismiss={dismissToast} onFlyTo={handleFlyTo} />

      <StaleBanner />
      {aboutOpen && <AboutModal onClose={() => setAboutOpen(false)} />}
      {skillOpen && <SkillModal onClose={() => setSkillOpen(false)} />}
    </main>
  );
}
