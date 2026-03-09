"use client";

import { API_BASE } from "@/lib/api";
import { useEffect, useState, useRef, useCallback } from "react";
import dynamic from 'next/dynamic';
import { motion } from "framer-motion";
import WorldviewLeftPanel from "@/components/WorldviewLeftPanel";
import WorldviewRightPanel from "@/components/WorldviewRightPanel";
import NewsFeed from "@/components/NewsFeed";
import MarketsPanel from "@/components/MarketsPanel";
import FilterPanel from "@/components/FilterPanel";
import FindLocateBar from "@/components/FindLocateBar";
import RadioInterceptPanel from "@/components/RadioInterceptPanel";
import SettingsPanel from "@/components/SettingsPanel";
import MapLegend from "@/components/MapLegend";
import ScaleBar from "@/components/ScaleBar";
import ErrorBoundary from "@/components/ErrorBoundary";
import OnboardingModal, { useOnboarding } from "@/components/OnboardingModal";

// Use dynamic loads for Maplibre to avoid SSR window is not defined errors
const MaplibreViewer = dynamic(() => import('@/components/MaplibreViewer'), { ssr: false });

export default function Dashboard() {
  const dataRef = useRef<any>({});
  const [dataVersion, setDataVersion] = useState(0);
  // Stable reference for child components — only changes when dataVersion increments
  const data = dataRef.current;
  const [uiVisible, setUiVisible] = useState(true);
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
    ships_important: true,
    ships_civilian: false,
    ships_passenger: true,
    earthquakes: true,
    cctv: false,
    ukraine_frontline: true,
    global_incidents: true,
    day_night: true,
    gps_jamming: true,
  });

  const [effects, setEffects] = useState({
    bloom: true,
  });

  const [activeStyle, setActiveStyle] = useState('DEFAULT');
  const stylesList = ['DEFAULT', 'FLIR', 'NVG', 'CRT'];

  const cycleStyle = () => {
    setActiveStyle((prev) => {
      const idx = stylesList.indexOf(prev);
      return stylesList[(idx + 1) % stylesList.length];
    });
  };

  const [selectedEntity, setSelectedEntity] = useState<{ type: string, id: string | number, extra?: any } | null>(null);
  const [activeFilters, setActiveFilters] = useState<Record<string, string[]>>({});
  const [flyToLocation, setFlyToLocation] = useState<{ lat: number, lng: number, ts: number } | null>(null);

  // Eavesdrop Mode State
  const [isEavesdropping, setIsEavesdropping] = useState(false);
  const [eavesdropLocation, setEavesdropLocation] = useState<{ lat: number, lng: number } | null>(null);
  const [cameraCenter, setCameraCenter] = useState<{ lat: number, lng: number } | null>(null);

  // Mouse coordinate + reverse geocoding state
  const [mouseCoords, setMouseCoords] = useState<{ lat: number, lng: number } | null>(null);
  const [locationLabel, setLocationLabel] = useState('');

  // Onboarding & connection status
  const { showOnboarding, setShowOnboarding } = useOnboarding();
  const [backendStatus, setBackendStatus] = useState<'connecting' | 'connected' | 'disconnected'>('connecting');
  const geocodeCache = useRef<Map<string, string>>(new Map());
  const geocodeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const lastGeocodedPos = useRef<{ lat: number; lng: number } | null>(null);
  const geocodeAbort = useRef<AbortController | null>(null);

  const handleMouseCoords = useCallback((coords: { lat: number, lng: number }) => {
    setMouseCoords(coords);

    // Throttle reverse geocoding to every 1500ms + distance check
    if (geocodeTimer.current) clearTimeout(geocodeTimer.current);
    geocodeTimer.current = setTimeout(async () => {
      // Skip if cursor hasn't moved far enough (0.05 degrees ~= 5km)
      if (lastGeocodedPos.current) {
        const dLat = Math.abs(coords.lat - lastGeocodedPos.current.lat);
        const dLng = Math.abs(coords.lng - lastGeocodedPos.current.lng);
        if (dLat < 0.05 && dLng < 0.05) return;
      }

      const gridKey = `${(coords.lat).toFixed(2)},${(coords.lng).toFixed(2)}`;
      const cached = geocodeCache.current.get(gridKey);
      if (cached) {
        setLocationLabel(cached);
        lastGeocodedPos.current = coords;
        return;
      }

      // Cancel any in-flight geocode request
      if (geocodeAbort.current) geocodeAbort.current.abort();
      geocodeAbort.current = new AbortController();

      try {
        const res = await fetch(
          `https://nominatim.openstreetmap.org/reverse?lat=${coords.lat}&lon=${coords.lng}&format=json&zoom=10&addressdetails=1`,
          { headers: { 'Accept-Language': 'en' }, signal: geocodeAbort.current.signal }
        );
        if (res.ok) {
          const data = await res.json();
          const addr = data.address || {};
          const city = addr.city || addr.town || addr.village || addr.county || '';
          const state = addr.state || addr.region || '';
          const country = addr.country || '';
          const parts = [city, state, country].filter(Boolean);
          const label = parts.join(', ') || data.display_name?.split(',').slice(0, 3).join(',') || 'Unknown';

          // LRU-style cache pruning: keep max 500 entries (Map preserves insertion order)
          if (geocodeCache.current.size > 500) {
            const iter = geocodeCache.current.keys();
            for (let i = 0; i < 100; i++) {
              const key = iter.next().value;
              if (key !== undefined) geocodeCache.current.delete(key);
            }
          }
          geocodeCache.current.set(gridKey, label);
          setLocationLabel(label);
          lastGeocodedPos.current = coords;
        }
      } catch (e: any) {
        if (e.name !== 'AbortError') { /* Silently fail - keep last label */ }
      }
    }, 1500);
  }, []);

  // Region dossier state (right-click intelligence)
  const [regionDossier, setRegionDossier] = useState<any>(null);
  const [regionDossierLoading, setRegionDossierLoading] = useState(false);

  const handleMapRightClick = useCallback(async (coords: { lat: number, lng: number }) => {
    setSelectedEntity({ type: 'region_dossier', id: `${coords.lat.toFixed(4)}_${coords.lng.toFixed(4)}`, extra: coords });
    setRegionDossierLoading(true);
    setRegionDossier(null);
    try {
      const res = await fetch(`${API_BASE}/api/region-dossier?lat=${coords.lat}&lng=${coords.lng}`);
      if (res.ok) {
        const data = await res.json();
        setRegionDossier(data);
      }
    } catch (e) {
      console.error("Failed to fetch region dossier", e);
    } finally {
      setRegionDossierLoading(false);
    }
  }, []);

  // Clear dossier when selecting a different entity type
  useEffect(() => {
    if (selectedEntity?.type !== 'region_dossier') {
      setRegionDossier(null);
      setRegionDossierLoading(false);
    }
  }, [selectedEntity]);

  // ETag tracking for conditional requests
  const fastEtag = useRef<string | null>(null);
  const slowEtag = useRef<string | null>(null);

  useEffect(() => {
    const fetchFastData = async () => {
      try {
        const headers: Record<string, string> = {};
        if (fastEtag.current) headers['If-None-Match'] = fastEtag.current;
        const res = await fetch(`${API_BASE}/api/live-data/fast`, { headers });
        if (res.status === 304) { setBackendStatus('connected'); return; }
        if (res.ok) {
          setBackendStatus('connected');
          fastEtag.current = res.headers.get('etag') || null;
          const json = await res.json();
          dataRef.current = { ...dataRef.current, ...json };
          setDataVersion(v => v + 1);
        }
      } catch (e) {
        console.error("Failed fetching fast live data", e);
        setBackendStatus('disconnected');
      }
    };

    const fetchSlowData = async () => {
      try {
        const headers: Record<string, string> = {};
        if (slowEtag.current) headers['If-None-Match'] = slowEtag.current;
        const res = await fetch(`${API_BASE}/api/live-data/slow`, { headers });
        if (res.status === 304) return;
        if (res.ok) {
          slowEtag.current = res.headers.get('etag') || null;
          const json = await res.json();
          dataRef.current = { ...dataRef.current, ...json };
          setDataVersion(v => v + 1);
        }
      } catch (e) {
        console.error("Failed fetching slow live data", e);
      }
    };

    fetchFastData();
    fetchSlowData();

    // Fast polling: 60s (matches backend update cadence — was 15s, wasting 75% on 304s)
    // Slow polling: 120s (backend updates every 30min)
    const fastInterval = setInterval(fetchFastData, 60000);
    const slowInterval = setInterval(fetchSlowData, 120000);

    return () => {
      clearInterval(fastInterval);
      clearInterval(slowInterval);
    };
  }, []);

  return (
    <main className="fixed inset-0 w-full h-full bg-black overflow-hidden font-sans">

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
        />
      </ErrorBoundary>

      {uiVisible && (
        <>
          {/* WORLDVIEW HEADER */}
          <motion.div
            initial={{ opacity: 0, y: -20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 1 }}
            className="absolute top-6 left-6 z-[200] pointer-events-none flex items-center gap-4"
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
              <h1 className="text-2xl font-bold tracking-[0.4em] text-white flex items-center gap-3" style={{ fontFamily: 'monospace' }}>
                S H A D O W <span className="text-cyan-400">B R O K E R</span>
              </h1>
              <span className="text-[9px] text-gray-500 font-mono tracking-[0.3em] mt-1 ml-1">GLOBAL THREAT INTERCEPT</span>
            </div>
          </motion.div>

          {/* SYSTEM METRICS TOP LEFT */}
          <div className="absolute top-2 left-6 text-[8px] font-mono tracking-widest text-cyan-500/50 z-[200] pointer-events-none">
            OPTIC VIS:113  SRC:180  DENS:1.42  0.8ms
          </div>

          {/* SYSTEM METRICS TOP RIGHT */}
          <div className="absolute top-2 right-6 text-[9px] flex flex-col items-end font-mono tracking-widest text-gray-600 z-[200] pointer-events-none">
            <div>RTX</div>
            <div>VSR</div>
          </div>

          {/* LEFT HUD CONTAINER */}
          <div className="absolute left-6 top-24 bottom-6 w-80 flex flex-col gap-6 z-[200] pointer-events-none">
            {/* LEFT PANEL - DATA LAYERS */}
            <WorldviewLeftPanel data={data} activeLayers={activeLayers} setActiveLayers={setActiveLayers} onSettingsClick={() => setSettingsOpen(true)} onLegendClick={() => setLegendOpen(true)} />

            {/* LEFT BOTTOM - DISPLAY CONFIG */}
            <WorldviewRightPanel effects={effects} setEffects={setEffects} setUiVisible={setUiVisible} />
          </div>

          {/* RIGHT HUD CONTAINER */}
          <div className="absolute right-6 top-24 bottom-6 w-80 flex flex-col gap-4 z-[200] pointer-events-auto overflow-y-auto styled-scrollbar pr-2">
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
              <MarketsPanel data={data} />
            </div>

            {/* SIGINT & RADIO INTERCEPTS */}
            <div className="flex-shrink-0">
              <RadioInterceptPanel
                data={data}
                isEavesdropping={isEavesdropping}
                setIsEavesdropping={setIsEavesdropping}
                eavesdropLocation={eavesdropLocation}
                cameraCenter={cameraCenter}
              />
            </div>

            {/* DATA FILTERS */}
            <div className="flex-shrink-0">
              <FilterPanel data={data} activeFilters={activeFilters} setActiveFilters={setActiveFilters} />
            </div>

            {/* BOTTOM RIGHT - NEWS FEED (fills remaining space) */}
            <div className="flex-1 min-h-0 flex flex-col">
              <NewsFeed data={data} selectedEntity={selectedEntity} regionDossier={regionDossier} regionDossierLoading={regionDossierLoading} />
            </div>
          </div>

          {/* BOTTOM CENTER COORDINATE / LOCATION BAR */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 1, duration: 1 }}
            className="absolute bottom-6 left-1/2 -translate-x-1/2 z-[200] pointer-events-auto"
          >
            <div
              className="bg-black/60 backdrop-blur-md border border-gray-800 rounded-xl px-6 py-2.5 flex items-center gap-6 shadow-[0_4px_30px_rgba(0,0,0,0.5)] border-b-2 border-b-cyan-900 cursor-pointer"
              onClick={cycleStyle}
            >
              {/* Coordinates */}
              <div className="flex flex-col items-center min-w-[120px]">
                <div className="text-[8px] text-gray-600 font-mono tracking-[0.2em]">COORDINATES</div>
                <div className="text-[11px] text-cyan-400 font-mono font-bold tracking-wide">
                  {mouseCoords ? `${mouseCoords.lat.toFixed(4)}, ${mouseCoords.lng.toFixed(4)}` : '0.0000, 0.0000'}
                </div>
              </div>

              {/* Divider */}
              <div className="w-px h-8 bg-gray-700" />

              {/* Location name */}
              <div className="flex flex-col items-center min-w-[180px] max-w-[320px]">
                <div className="text-[8px] text-gray-600 font-mono tracking-[0.2em]">LOCATION</div>
                <div className="text-[10px] text-gray-300 font-mono truncate max-w-[320px]">
                  {locationLabel || 'Hover over map...'}
                </div>
              </div>

              {/* Divider */}
              <div className="w-px h-8 bg-gray-700" />

              {/* Style preset (compact) */}
              <div className="flex flex-col items-center">
                <div className="text-[8px] text-gray-600 font-mono tracking-[0.2em]">STYLE</div>
                <div className="text-[11px] text-cyan-400 font-mono font-bold">{activeStyle}</div>
              </div>
            </div>
          </motion.div>
        </>
      )}

      {/* RESTORE UI BUTTON (If Hidden) */}
      {!uiVisible && (
        <button
          onClick={() => setUiVisible(true)}
          className="absolute bottom-6 right-6 z-[200] bg-black/60 backdrop-blur-md border border-gray-800 rounded px-4 py-2 text-[10px] font-mono tracking-widest text-cyan-500 hover:text-cyan-300 hover:border-cyan-800 transition-colors pointer-events-auto"
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
      <SettingsPanel isOpen={settingsOpen} onClose={() => setSettingsOpen(false)} />

      {/* MAP LEGEND */}
      <MapLegend isOpen={legendOpen} onClose={() => setLegendOpen(false)} />

      {/* ONBOARDING MODAL */}
      {showOnboarding && (
        <OnboardingModal
          onClose={() => setShowOnboarding(false)}
          onOpenSettings={() => { setShowOnboarding(false); setSettingsOpen(true); }}
        />
      )}

      {/* BACKEND DISCONNECTED BANNER */}
      {backendStatus === 'disconnected' && (
        <div className="absolute top-0 left-0 right-0 z-[9000] flex items-center justify-center py-2 bg-red-950/90 border-b border-red-500/40 backdrop-blur-sm">
          <span className="text-[10px] font-mono tracking-widest text-red-400">
            BACKEND OFFLINE — Cannot reach {API_BASE}. Start the backend server or check your connection.
          </span>
        </div>
      )}

    </main>
  );
}
