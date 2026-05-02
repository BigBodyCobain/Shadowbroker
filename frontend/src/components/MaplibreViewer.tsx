'use client';

import { API_BASE } from '@/lib/api';
import React, { useMemo, useState, useEffect, useCallback, useRef } from 'react';
import Map, {
  Source,
  Layer,
  MapRef,
  ViewState,
  Popup,
  Marker,
  MapLayerMouseEvent,
  AttributionControl,
} from 'react-map-gl/maplibre';
import 'maplibre-gl/dist/maplibre-gl.css';
import { computeNightPolygon } from '@/utils/solarTerminator';
import { darkStyle, lightStyle } from '@/components/map/styles/mapStyles';
import maplibregl from 'maplibre-gl';
import { AlertTriangle, Radio, Activity, Play, Satellite } from 'lucide-react';
import WikiImage from '@/components/WikiImage';
import FishingDestinationRoute from '@/components/map/FishingDestinationRoute';
import { useTheme } from '@/lib/ThemeContext';
import { PIN_CATEGORY_LABELS, PIN_CATEGORY_COLORS, type PinCategory } from '@/types/aiIntel';
import { getAllPinIcons } from '@/components/map/pinIcons';
import { AIIntelPinDetail } from '@/components/map/AIIntelPinDetail';

import {
  svgPlaneCyan,
  svgPlaneYellow,
  svgPlaneOrange,
  svgPlanePurple,
  svgFighter,
  svgHeli,
  svgHeliCyan,
  svgHeliDimCyan,
  svgHeliOrange,
  svgHeliPurple,
  svgHeliSlate,
  svgHeliAmber,
  svgTanker,
  svgRecon,
  svgPlanePink,
  svgPlaneAlertRed,
  svgPlaneDarkBlue,
  svgPlaneWhiteAlert,
  svgHeliPink,
  svgHeliAlertRed,
  svgHeliDarkBlue,
  svgHeliBlue,
  svgHeliLime,
  svgHeliWhiteAlert,
  svgPlaneBlack,
  svgHeliBlack,
  svgDrone,
  svgDataCenter,
  svgPowerPlant,
  svgRadioTower,
  svgShipGray,
  svgShipRed,
  svgShipYellow,
  svgShipBlue,
  svgShipWhite,
  svgShipPink,
  svgShipGreyBlue,
  svgShipAmber,
  svgCarrier,
  svgCctv,
  svgSatDish,
  svgLoRaSat,
  svgScannerTower,
  svgWarning,
  svgThreat,
  svgTriangleYellow,
  svgTriangleRed,
  svgTrianglePink,
  svgTriangleGreen,
  svgFireYellow,
  svgFireOrange,
  svgFireRed,
  svgFireDarkRed,
  svgFireClusterSmall,
  svgFireClusterMed,
  svgFireClusterLarge,
  svgFireClusterXL,
  svgPotusPlane,
  svgPotusHeli,
  svgAirlinerCyan,
  svgAirlinerDimCyan,
  svgAirlinerOrange,
  svgAirlinerPurple,
  svgAirlinerSlate,
  svgAirlinerYellow,
  svgAirlinerAmber,
  svgAirlinerPink,
  svgAirlinerRed,
  svgAirlinerDarkBlue,
  svgAirlinerBlue,
  svgAirlinerLime,
  svgAirlinerBlack,
  svgAirlinerWhite,
  svgTurbopropCyan,
  svgTurbopropDimCyan,
  svgTurbopropOrange,
  svgTurbopropPurple,
  svgTurbopropSlate,
  svgTurbopropYellow,
  svgTurbopropAmber,
  svgTurbopropPink,
  svgTurbopropRed,
  svgTurbopropDarkBlue,
  svgTurbopropBlue,
  svgTurbopropLime,
  svgTurbopropBlack,
  svgTurbopropWhite,
  svgBizjetCyan,
  svgBizjetDimCyan,
  svgBizjetOrange,
  svgBizjetPurple,
  svgBizjetSlate,
  svgBizjetYellow,
  svgBizjetAmber,
  svgBizjetPink,
  svgBizjetRed,
  svgBizjetDarkBlue,
  svgBizjetBlue,
  svgBizjetLime,
  svgBizjetBlack,
  svgBizjetWhite,
  svgAirlinerGrey,
  svgTurbopropGrey,
  svgBizjetGrey,
  svgHeliGrey,
  GROUNDED_ICON_MAP,
  COLOR_MAP_COMMERCIAL,
  COLOR_MAP_PRIVATE,
  COLOR_MAP_JETS,
  COLOR_MAP_MILITARY,
  MIL_SPECIAL_MAP,
  makeMilBaseSvg,
  makeMilBaseCircleSvg,
  MILBASE_ICON_SPECS,
  makeVolcanoSvg,
  VOLCANO_ICON_SPECS,
  WEATHER_ICON_SPECS,
  CT_ICON_SPECS,
} from '@/components/map/icons/AircraftIcons';
import { makeSatSvg, makeISSSvg, makeTrainSvg } from '@/components/map/icons/SatelliteIcons';
import { makeUfoSvg, makeUfoClusterSvg, makeWaterDropSvg, makeWaterDropClusterSvg } from '@/components/map/icons/OverlayIcons';
import { EMPTY_FC } from '@/components/map/mapConstants';
import { useImperativeSource } from '@/components/map/hooks/useImperativeSource';
import { useDynamicMapLayersWorker } from '@/components/map/hooks/useDynamicMapLayersWorker';
import { useStaticMapLayersWorker } from '@/components/map/hooks/useStaticMapLayersWorker';
import {
  ClusterCountLabels,
  TrackedFlightLabels,
  CarrierLabels,
  TrackedYachtLabels,
  UavLabels,
  EarthquakeLabels,
  ThreatMarkers,
} from '@/components/map/MapMarkers';
import type { DashboardData, KiwiSDR, MaplibreViewerProps, Scanner, SigintSignal } from '@/types/dashboard';
import { useDataKeys } from '@/hooks/useDataStore';
import { useInterpolation } from '@/components/map/hooks/useInterpolation';
import { useClusterLabels } from '@/components/map/hooks/useClusterLabels';
import { spreadAlertItems } from '@/utils/alertSpread';

import { useViewportBounds } from '@/components/map/hooks/useViewportBounds';
import { MeasurementLayers } from '@/components/map/layers/MeasurementLayers';
import { buildCctvProxyUrl } from '@/lib/cctvProxy';
import { CctvFullscreenModal } from '@/components/MaplibreViewer/CctvFullscreenModal';
import { SatellitePopup } from '@/components/MaplibreViewer/popups/SatellitePopup';
import { ShipPopup } from '@/components/MaplibreViewer/popups/ShipPopup';
import { SigintPopup } from '@/components/MaplibreViewer/popups/SigintPopup';
import { CorrelationPopup } from '@/components/MaplibreViewer/popups/CorrelationPopup';
import { WastewaterPopup } from '@/components/MaplibreViewer/popups/WastewaterPopup';
import { MilitaryBasePopup } from '@/components/MaplibreViewer/popups/MilitaryBasePopup';
import { RegionDossierPanel } from '@/components/MaplibreViewer/popups/RegionDossierPanel';
import {
  buildSentinelTileUrl,
  hasSentinelCredentials,
  getSentinelToken,
  registerSentinelProtocol,
} from '@/lib/sentinelHub';
import {
  buildEarthquakesGeoJSON,
  buildJammingGeoJSON,
  buildCorrelationsGeoJSON,
  buildTinygsGeoJSON,
  buildShodanGeoJSON,
  buildAIIntelGeoJSON,
  type AIIntelPinData,
  buildFrontlineGeoJSON,
  buildUavGeoJSON,
  buildSatellitesGeoJSON,
  buildCarriersGeoJSON,
  findSelectedEntity,
  buildPredictiveGeoJSON,
  buildProximityRingsGeoJSON,
  buildUkraineAlertsGeoJSON,
  buildUkraineAlertLabelsGeoJSON,
  buildWeatherAlertsGeoJSON,
  buildWeatherAlertLabelsGeoJSON,
  buildSarAnomaliesGeoJSON,
  buildSarAoisGeoJSON,
  type FlightLayerConfig,
} from '@/components/map/geoJSONBuilders';

type ViewBounds = { south: number; west: number; north: number; east: number };

type DynamicRoute = {
  orig_loc?: [number, number];
  dest_loc?: [number, number];
  origin_name?: string;
  dest_name?: string;
};

type GeoExtras = {
  lat?: number;
  lng?: number;
  lon?: number;
  geometry?: { coordinates?: [number, number] };
};

type KiwiProps = Partial<KiwiSDR> & GeoExtras;
type ScannerProps = Partial<Scanner> & GeoExtras;
type SigintProps = Partial<SigintSignal> & GeoExtras;

const MAP_EXTRA_DATA_KEYS = [
  'air_quality',
  'cctv',
  'commercial_flights',
  'correlations',
  'crowdthreat',
  'datacenters',
  'firms_fires',
  'fishing_activity',
  'frontlines',
  'gps_jamming',
  'internet_outages',
  'kiwisdr',
  'military_bases',
  'military_flights',
  'power_plants',
  'private_flights',
  'private_jets',
  'psk_reporter',
  'sar_anomalies',
  'satellite_analysis',
  'satellites',
  'satnogs_stations',
  'scanners',
  'sigint',
  'tinygs_satellites',
  'trains',
  'uap_sightings',
  'ukraine_alerts',
  'viirs_change_nodes',
  'volcanoes',
  'wastewater',
  'weather_alerts',
] as const satisfies readonly (keyof DashboardData)[];

const VIIRS_TILE_TEMPLATES = [
  // The older daily Day/Night Band path now 404s in GIBS. Black Marble is the
  // current stable night-lights product and has a best-available endpoint.
  'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/VIIRS_Black_Marble/default/GoogleMapsCompatible_Level8/{z}/{y}/{x}.png',
  'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/VIIRS_Black_Marble/default/2016-01-01/GoogleMapsCompatible_Level8/{z}/{y}/{x}.png',
];

function buildProbeRasterUrl(tileTemplate: string): string {
  return tileTemplate
    .replace('{z}', '0')
    .replace('{y}', '0')
    .replace('{x}', '0');
}

function probeRasterTile(url: string): Promise<boolean> {
  return new Promise((resolve) => {
    const img = new Image();
    let settled = false;
    const finish = (ok: boolean) => {
      if (settled) return;
      settled = true;
      img.onload = null;
      img.onerror = null;
      resolve(ok);
    };
    img.onload = () => finish(true);
    img.onerror = () => finish(false);
    img.referrerPolicy = 'no-referrer';
    img.src = url;
  });
}

const MaplibreViewer = ({
  activeLayers,
  activeFilters,
  onEntityClick,
  flyToLocation,
  selectedEntity,
  onMouseCoords,
  onRightClick,
  regionDossier,
  regionDossierLoading,
  onViewStateChange,
  measureMode,
  onMeasureClick,
  measurePoints,
  gibsDate,
  gibsOpacity,
  sentinelDate,
  sentinelOpacity,
  sentinelPreset,
  viewBoundsRef,
  setTrackedSdr,
  setTrackedScanner,
  shodanResults,
  shodanStyle,
  pinPlacementMode,
  onPinPlaced,
  sarAoiDropMode,
  onSarAoiDropped,
  sarAoiListVersion,
}: Omit<MaplibreViewerProps, 'data'>) => {
  const coreData = useDataKeys([
    'tracked_flights',
    'news',
    'ships',
    'uavs',
    'earthquakes',
    'gdelt',
    'liveuamap',
  ]);
  const extraData = useDataKeys(MAP_EXTRA_DATA_KEYS);
  const data = useMemo(() => ({ ...coreData, ...extraData }) as DashboardData, [coreData, extraData]);
  const mapRef = useRef<MapRef>(null);
  const mapInitRef = useRef(false);
  const { theme } = useTheme();
  const mapThemeStyle = useMemo<maplibregl.StyleSpecification>(
    () => (theme === 'light' ? lightStyle : darkStyle) as maplibregl.StyleSpecification,
    [theme],
  );

  const initialViewState = useMemo<ViewState>(
    () => ({
      longitude: 0,
      latitude: 20,
      zoom: 2,
      bearing: 0,
      pitch: 0,
      padding: { top: 0, bottom: 0, left: 0, right: 0 },
    }),
    [],
  );
  const viewStateRef = useRef<ViewState>(initialViewState);
  const [mapZoom, setMapZoom] = useState(initialViewState.zoom);
  const [dismissedAlerts, setDismissedAlerts] = useState<Set<string>>(new Set());
  const [viirsResolvedTileTemplate, setViirsResolvedTileTemplate] = useState<string | null>(null);
  const [isMapInteracting, setIsMapInteracting] = useState(false);

  // Pin placement state
  const [pendingPin, setPendingPin] = useState<{
    lat: number;
    lng: number;
    entity: { entity_type: string; entity_id: string; entity_label: string } | null;
  } | null>(null);
  const [pinLabel, setPinLabel] = useState('');
  const [pinNotes, setPinNotes] = useState('');
  const [pinCategory, setPinCategory] = useState<PinCategory>('custom');
  const [pinSaving, setPinSaving] = useState(false);
  const [aiIntelPins, setAiIntelPins] = useState<AIIntelPinData[]>([]);
  const [aiIntelRefreshTick, setAiIntelRefreshTick] = useState(0);
  // Currently-open AI Intel pin detail popup (pin id)
  const [openPinDetailId, setOpenPinDetailId] = useState<string | null>(null);
  const pinLabelInputRef = useRef<HTMLInputElement | null>(null);

  // Force focus to the label input whenever the pin dialog opens — the
  // maplibre canvas otherwise keeps focus and global hotkeys eat keystrokes.
  useEffect(() => {
    if (!pendingPin) return;
    const t = setTimeout(() => pinLabelInputRef.current?.focus(), 50);
    return () => clearTimeout(t);
  }, [pendingPin]);

  const handleSavePin = useCallback(async () => {
    if (!pendingPin || !pinLabel.trim()) return;
    setPinSaving(true);
    try {
      const body: Record<string, unknown> = {
        lat: pendingPin.lat,
        lng: pendingPin.lng,
        label: pinLabel.trim(),
        description: pinNotes.trim(),
        source: 'user',
        category: pinCategory,
      };
      if (pendingPin.entity) {
        body.entity_attachment = pendingPin.entity;
      }
      await fetch(`${API_BASE}/api/ai/pins`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      setPendingPin(null);
      setPinLabel('');
      setPinNotes('');
      setPinCategory('custom');
      setAiIntelRefreshTick((t) => t + 1);
      onPinPlaced?.();
    } catch (err) {
      console.error('Failed to save pin:', err);
    }
    setPinSaving(false);
  }, [pendingPin, pinLabel, pinNotes, pinCategory, onPinPlaced]);

  const showImageryReferenceOverlay =
    activeLayers.highres_satellite ||
    activeLayers.gibs_imagery ||
    activeLayers.viirs_nightlights ||
    activeLayers.sentinel_hub;
  const imageryReferenceOverlayOpacity = activeLayers.viirs_nightlights ? 1 : 0.9;
  const backendViewportSyncEnabled =
    activeLayers.ships_military ||
    activeLayers.ships_cargo ||
    activeLayers.ships_civilian ||
    activeLayers.ships_passenger ||
    activeLayers.ships_tracked_yachts;

  const { mapBounds, inView, updateBounds } = useViewportBounds(
    mapRef,
    viewBoundsRef as React.MutableRefObject<ViewBounds | null> | undefined,
    backendViewportSyncEnabled,
  );

  useEffect(() => {
    if (backendViewportSyncEnabled) {
      updateBounds();
    }
  }, [backendViewportSyncEnabled, updateBounds]);

  const viirsProbeDayKey = new Date().toISOString().slice(0, 10);
  useEffect(() => {
    if (!activeLayers.viirs_nightlights) {
      setViirsResolvedTileTemplate(null);
      return undefined;
    }
    let cancelled = false;

    const resolveViirsDate = async () => {
      for (const tileTemplate of VIIRS_TILE_TEMPLATES) {
        const ok = await probeRasterTile(buildProbeRasterUrl(tileTemplate));
        if (cancelled) return;
        if (ok) {
          setViirsResolvedTileTemplate(tileTemplate);
          return;
        }
      }
      if (!cancelled) {
        setViirsResolvedTileTemplate(VIIRS_TILE_TEMPLATES[0] ?? null);
      }
    };

    void resolveViirsDate();
    return () => {
      cancelled = true;
    };
  }, [activeLayers.viirs_nightlights, viirsProbeDayKey]);

  const [dynamicRoute, setDynamicRoute] = useState<DynamicRoute | null>(null);
  const prevCallsign = useRef<string | null>(null);

  // Oracle region intel for map entity popups
  const [oracleIntel, setOracleIntel] = useState<{
    found: boolean;
    top_headline?: string;
    oracle_score?: number;
    tier?: string;
    avg_sentiment?: number;
    nearby_count?: number;
    market?: { title: string; consensus_pct: number | null } | null;
  } | null>(null);

  // Global Incidents popup: dismiss no longer permanently removes alerts.
  // Clicking × just deselects, allowing re-opening from the right-panel feed.

  // --- Smooth interpolation via extracted hook ---
  const {
    interpFlight,
    interpShip,
    interpSat,
    interpTick,
    dtSeconds,
    resetTimestamp,
  } =
    useInterpolation();

  // Track when flight/ship/satellite data actually changes (new fetch arrived)
  useEffect(() => {
    resetTimestamp();
  }, [
    data?.commercial_flights,
    data?.private_flights,
    data?.military_flights,
    data?.private_jets,
    data?.tracked_flights,
    data?.ships,
    data?.satellites,
    resetTimestamp,
  ]);

  // --- Solar Terminator: recompute the night polygon every 60 seconds ---
  const [nightGeoJSON, setNightGeoJSON] = useState<GeoJSON.FeatureCollection>(() =>
    computeNightPolygon(),
  );
  useEffect(() => {
    const timer = setInterval(() => setNightGeoJSON(computeNightPolygon()), 60000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    let isMounted = true;

    let callsign = null;
    let entityLat = 0;
    let entityLng = 0;
    if (selectedEntity && data) {
      let entity = null;
      if (selectedEntity.type === 'flight')
        entity = data?.commercial_flights?.find((f) => f.icao24 === selectedEntity.id);
      else if (selectedEntity.type === 'private_flight')
        entity = data?.private_flights?.find((f) => f.icao24 === selectedEntity.id);
      else if (selectedEntity.type === 'military_flight')
        entity = data?.military_flights?.find((f) => f.icao24 === selectedEntity.id);
      else if (selectedEntity.type === 'private_jet')
        entity = data?.private_jets?.find((f) => f.icao24 === selectedEntity.id);
      else if (selectedEntity.type === 'tracked_flight')
        entity = data?.tracked_flights?.find((f) => f.icao24 === selectedEntity.id);

      if (entity && entity.callsign) {
        callsign = entity.callsign;
        entityLat = entity.lat ?? 0;
        entityLng = entity.lng ?? 0;
      }
    }

    if (callsign && callsign !== prevCallsign.current) {
      prevCallsign.current = callsign;
      fetch(`${API_BASE}/api/route/${callsign}?lat=${entityLat}&lng=${entityLng}`)
        .then((res) => res.json())
        .then((routeData) => {
          if (isMounted) setDynamicRoute(routeData);
        })
        .catch(() => {
          if (isMounted) setDynamicRoute(null);
        });
    } else if (!callsign) {
      prevCallsign.current = null;
      if (isMounted) setDynamicRoute(null);
    }

    return () => {
      isMounted = false;
    };
  }, [selectedEntity, data]);

  // Fetch oracle region intel for entity popups
  useEffect(() => {
    if (!selectedEntity) {
      setOracleIntel(null);
      return;
    }
    const oracleTypes = ['military_base', 'liveuamap', 'gps_jamming', 'earthquake', 'conflict_zone'];
    if (!oracleTypes.includes(selectedEntity.type)) {
      setOracleIntel(null);
      return;
    }
    const lat = selectedEntity.extra?.lat;
    const lng = selectedEntity.extra?.lng;
    if (lat == null || lng == null) {
      setOracleIntel(null);
      return;
    }
    let alive = true;
    fetch(`${API_BASE}/api/oracle/region-intel?lat=${lat}&lng=${lng}`)
      .then(r => r.json())
      .then(d => { if (alive) setOracleIntel(d); })
      .catch(() => { if (alive) setOracleIntel(null); });
    return () => { alive = false; };
  }, [selectedEntity]);

  useEffect(() => {
    if (flyToLocation && mapRef.current) {
      mapRef.current.flyTo({
        center: [flyToLocation.lng, flyToLocation.lat],
        zoom: 8,
        duration: 1500,
      });
    }
  }, [flyToLocation]);

  const earthquakesGeoJSON = useMemo(
    () => (activeLayers.earthquakes ? buildEarthquakesGeoJSON(data?.earthquakes) : null),
    [activeLayers.earthquakes, data?.earthquakes],
  );

  const jammingGeoJSON = useMemo(
    () => (activeLayers.gps_jamming ? buildJammingGeoJSON(data?.gps_jamming) : null),
    [activeLayers.gps_jamming, data?.gps_jamming],
  );

  const correlationsGeoJSON = useMemo(
    () => {
      if (!activeLayers.correlations && !activeLayers.contradictions) return null;
      const alerts = data?.correlations?.filter((a) => {
        if (a.type === 'contradiction') return activeLayers.contradictions;
        return activeLayers.correlations;
      });
      return buildCorrelationsGeoJSON(alerts);
    },
    [activeLayers.correlations, activeLayers.contradictions, data?.correlations],
  );

  const tinygsGeoJSON = useMemo(
    () => {
      void interpTick;
      return activeLayers.tinygs ? buildTinygsGeoJSON(data?.tinygs_satellites, inView, interpSat) : null;
    },
    [activeLayers.tinygs, data?.tinygs_satellites, inView, interpSat, interpTick],
  );

  const shodanGeoJSON = useMemo(
    () => (activeLayers.shodan_overlay ? buildShodanGeoJSON(shodanResults) : null),
    [activeLayers.shodan_overlay, shodanResults],
  );

  // AI Intel layer — pins from OpenClaw and the AI co-pilot
  useEffect(() => {
    if (!activeLayers.ai_intel) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const resp = await fetch(`${API_BASE}/api/ai/pins/geojson`);
        if (!resp.ok || cancelled) return;
        const gj = await resp.json();
        const pins = (gj.features || []).map((f: any) => ({
          ...f.properties,
          lat: f.geometry?.coordinates?.[1],
          lng: f.geometry?.coordinates?.[0],
        }));
        if (!cancelled) setAiIntelPins(pins);
      } catch {}
    };
    poll();
    const tid = setInterval(poll, 15_000); // poll every 15s
    return () => { cancelled = true; clearInterval(tid); };
  }, [activeLayers.ai_intel, aiIntelRefreshTick]);
  const aiIntelGeoJSON = useMemo(
    () => (activeLayers.ai_intel ? buildAIIntelGeoJSON(aiIntelPins, data) : null),
    [activeLayers.ai_intel, aiIntelPins, data],
  );

  const ukraineAlertsGeoJSON = useMemo(
    () => (activeLayers.ukraine_alerts ? buildUkraineAlertsGeoJSON(data?.ukraine_alerts) : null),
    [activeLayers.ukraine_alerts, data?.ukraine_alerts],
  );

  const ukraineAlertLabelsGeoJSON = useMemo(
    () => (activeLayers.ukraine_alerts ? buildUkraineAlertLabelsGeoJSON(data?.ukraine_alerts) : null),
    [activeLayers.ukraine_alerts, data?.ukraine_alerts],
  );

  const weatherAlertsGeoJSON = useMemo(
    () => (activeLayers.weather_alerts ? buildWeatherAlertsGeoJSON(data?.weather_alerts) : null),
    [activeLayers.weather_alerts, data?.weather_alerts],
  );

  const weatherAlertLabelsGeoJSON = useMemo(
    () => (activeLayers.weather_alerts ? buildWeatherAlertLabelsGeoJSON(data?.weather_alerts) : null),
    [activeLayers.weather_alerts, data?.weather_alerts],
  );

  // Sentinel Hub — tile URL (only built when layer is active + credentials are set)
  const sentinelTileUrl = useMemo(() => {
    if (!activeLayers.sentinel_hub) return null;
    if (!hasSentinelCredentials()) return null;
    return buildSentinelTileUrl(sentinelPreset || 'TRUE-COLOR', sentinelDate || '');
  }, [activeLayers.sentinel_hub, sentinelPreset, sentinelDate]);

  // Register sentinel:// custom protocol for Process API tile fetching
  useEffect(() => {
    registerSentinelProtocol(maplibregl);
  }, []);

  // Pre-fetch Sentinel Hub token when layer is toggled on
  useEffect(() => {
    if (!activeLayers.sentinel_hub) return;
    getSentinelToken().catch((err) => console.warn('Sentinel Hub token error:', err));
  }, [activeLayers.sentinel_hub, sentinelPreset, sentinelDate]);

  // Initialize images/sources as soon as the local style is available.
  // Do not wait for remote basemap tiles to load, because blocked tile hosts
  // would otherwise prevent the map "load" event from ever firing.
  const initializeMap = useCallback((map: maplibregl.Map) => {
    if (mapInitRef.current) return;
    mapInitRef.current = true;

    // Track which images are still loading so we can retry on styleimagemissing
    const pendingImages: Record<string, string> = {};

    const loadImg = (id: string, url: string) => {
      if (!map.hasImage(id)) {
        pendingImages[id] = url;
        const img = new Image();
        img.crossOrigin = 'anonymous';
        img.src = url;
        img.onload = () => {
          if (!map.hasImage(id)) map.addImage(id, img);
          delete pendingImages[id];
        };
      }
    };

    // Suppress "image not found" warnings — retry when the async load finishes
    map.on('styleimagemissing', (ev: maplibregl.MapStyleImageMissingEvent) => {
      const id = ev.id;
      const url = pendingImages[id];
      if (url) {
        const img = new Image();
        img.crossOrigin = 'anonymous';
        img.src = url;
        img.onload = () => {
          if (!map.hasImage(id)) map.addImage(id, img);
          delete pendingImages[id];
        };
      }
    });

    // AI Intel teardrop pin icons — one per category color
    for (const [id, url] of getAllPinIcons()) {
      loadImg(id, url);
    }

    // Critical icons — needed immediately for default-on layers
    loadImg('svgPlaneCyan', svgPlaneCyan);
    loadImg('svgPlaneYellow', svgPlaneYellow);
    loadImg('svgPlaneOrange', svgPlaneOrange);
    loadImg('svgPlanePurple', svgPlanePurple);
    loadImg('svgHeli', svgHeli);
    loadImg('svgHeliCyan', svgHeliCyan);
    loadImg('svgHeliDimCyan', svgHeliDimCyan);
    loadImg('svgHeliOrange', svgHeliOrange);
    loadImg('svgHeliPurple', svgHeliPurple);
    loadImg('svgHeliSlate', svgHeliSlate);
    loadImg('svgHeliAmber', svgHeliAmber);
    loadImg('svgHeliBlue', svgHeliBlue);
    loadImg('svgHeliLime', svgHeliLime);
    loadImg('svgFighter', svgFighter);
    loadImg('svgTanker', svgTanker);
    loadImg('svgRecon', svgRecon);
    loadImg('svgAirlinerCyan', svgAirlinerCyan);
    loadImg('svgAirlinerDimCyan', svgAirlinerDimCyan);
    loadImg('svgAirlinerOrange', svgAirlinerOrange);
    loadImg('svgAirlinerPurple', svgAirlinerPurple);
    loadImg('svgAirlinerSlate', svgAirlinerSlate);
    loadImg('svgAirlinerYellow', svgAirlinerYellow);
    loadImg('svgAirlinerAmber', svgAirlinerAmber);
    loadImg('svgTurbopropCyan', svgTurbopropCyan);
    loadImg('svgTurbopropDimCyan', svgTurbopropDimCyan);
    loadImg('svgTurbopropOrange', svgTurbopropOrange);
    loadImg('svgTurbopropPurple', svgTurbopropPurple);
    loadImg('svgTurbopropSlate', svgTurbopropSlate);
    loadImg('svgTurbopropYellow', svgTurbopropYellow);
    loadImg('svgTurbopropAmber', svgTurbopropAmber);
    loadImg('svgBizjetCyan', svgBizjetCyan);
    loadImg('svgBizjetDimCyan', svgBizjetDimCyan);
    loadImg('svgBizjetOrange', svgBizjetOrange);
    loadImg('svgBizjetPurple', svgBizjetPurple);
    loadImg('svgBizjetSlate', svgBizjetSlate);
    loadImg('svgBizjetYellow', svgBizjetYellow);
    loadImg('svgBizjetAmber', svgBizjetAmber);
    loadImg('svgAirlinerGrey', svgAirlinerGrey);
    loadImg('svgTurbopropGrey', svgTurbopropGrey);
    loadImg('svgBizjetGrey', svgBizjetGrey);
    loadImg('svgHeliGrey', svgHeliGrey);
    loadImg('svgShipGray', svgShipGray);
    loadImg('svgShipRed', svgShipRed);
    loadImg('svgShipYellow', svgShipYellow);
    loadImg('svgShipBlue', svgShipBlue);
    loadImg('svgShipWhite', svgShipWhite);
    loadImg('svgShipPink', svgShipPink);
    loadImg('svgShipGreyBlue', svgShipGreyBlue);
    loadImg('svgShipAmber', svgShipAmber);
    loadImg('svgCarrier', svgCarrier);
    loadImg('svgWarning', svgWarning);
    loadImg('icon-threat', svgThreat);

    // Deferred icons — for off-by-default layers and rare variants
    // Loaded in next frame to avoid blocking initial map render
    setTimeout(() => {
      loadImg('svgRadioTower', svgRadioTower);
      loadImg('svgSatDish', svgSatDish);
      loadImg('svgLoRaSat', svgLoRaSat);
      loadImg('svgScannerTower', svgScannerTower);
      loadImg('svgPlanePink', svgPlanePink);
      loadImg('svgPlaneAlertRed', svgPlaneAlertRed);
      loadImg('svgPlaneDarkBlue', svgPlaneDarkBlue);
      loadImg('svgPlaneWhiteAlert', svgPlaneWhiteAlert);
      loadImg('svgPlaneBlack', svgPlaneBlack);
      loadImg('svgHeliPink', svgHeliPink);
      loadImg('svgHeliAlertRed', svgHeliAlertRed);
      loadImg('svgHeliDarkBlue', svgHeliDarkBlue);
      loadImg('svgHeliWhiteAlert', svgHeliWhiteAlert);
      loadImg('svgHeliBlack', svgHeliBlack);
      loadImg('svgPotusPlane', svgPotusPlane);
      loadImg('svgPotusHeli', svgPotusHeli);
      loadImg('svgAirlinerPink', svgAirlinerPink);
      loadImg('svgAirlinerRed', svgAirlinerRed);
      loadImg('svgAirlinerDarkBlue', svgAirlinerDarkBlue);
      loadImg('svgAirlinerBlue', svgAirlinerBlue);
      loadImg('svgAirlinerLime', svgAirlinerLime);
      loadImg('svgAirlinerBlack', svgAirlinerBlack);
      loadImg('svgAirlinerWhite', svgAirlinerWhite);
      loadImg('svgTurbopropPink', svgTurbopropPink);
      loadImg('svgTurbopropRed', svgTurbopropRed);
      loadImg('svgTurbopropDarkBlue', svgTurbopropDarkBlue);
      loadImg('svgTurbopropBlue', svgTurbopropBlue);
      loadImg('svgTurbopropLime', svgTurbopropLime);
      loadImg('svgTurbopropBlack', svgTurbopropBlack);
      loadImg('svgTurbopropWhite', svgTurbopropWhite);
      loadImg('svgBizjetPink', svgBizjetPink);
      loadImg('svgBizjetRed', svgBizjetRed);
      loadImg('svgBizjetDarkBlue', svgBizjetDarkBlue);
      loadImg('svgBizjetBlue', svgBizjetBlue);
      loadImg('svgBizjetLime', svgBizjetLime);
      loadImg('svgBizjetBlack', svgBizjetBlack);
      loadImg('svgBizjetWhite', svgBizjetWhite);
      loadImg('svgDrone', svgDrone);
      loadImg('svgCctv', svgCctv);
      loadImg('icon-liveua-yellow', svgTriangleYellow);
      loadImg('icon-liveua-red', svgTriangleRed);
      loadImg('icon-aprs-triangle', svgTrianglePink);
      loadImg('icon-mesh-triangle', svgTriangleGreen);
      // FIRMS fire icons
      loadImg('fire-yellow', svgFireYellow);
      loadImg('fire-orange', svgFireOrange);
      loadImg('fire-red', svgFireRed);
      loadImg('fire-darkred', svgFireDarkRed);
      loadImg('fire-cluster-sm', svgFireClusterSmall);
      loadImg('fire-cluster-md', svgFireClusterMed);
      loadImg('fire-cluster-lg', svgFireClusterLarge);
      loadImg('fire-cluster-xl', svgFireClusterXL);
      // Data center icon
      loadImg('datacenter', svgDataCenter);
      // Power plant icon
      loadImg('power-plant', svgPowerPlant);
      // Satellite mission-type icons
      loadImg('sat-mil', makeSatSvg('#ff3333'));
      loadImg('sat-sar', makeSatSvg('#00e5ff'));
      loadImg('sat-sigint', makeSatSvg('#ffffff'));
      loadImg('sat-nav', makeSatSvg('#4488ff'));
      loadImg('sat-ew', makeSatSvg('#ff00ff'));
      loadImg('sat-com', makeSatSvg('#44ff44'));
      loadImg('sat-station', makeSatSvg('#ffdd00'));
      loadImg('sat-gen', makeSatSvg('#aaaaaa'));
      // ISS special icon (larger, with built-in halo ring)
      loadImg('sat-iss', makeISSSvg());
      // Train icons
      loadImg('train-amtrak', makeTrainSvg('#ffffff'));
      loadImg('train-fin', makeTrainSvg('#ffffff'));
      // Military base icons (square with X or circle)
      for (const spec of MILBASE_ICON_SPECS) {
        loadImg(
          spec.id,
          spec.svg ?? (spec.shape === 'circle'
            ? makeMilBaseCircleSvg(spec.fill, spec.inner)
            : makeMilBaseSvg(spec.fill, spec.inner)),
        );
      }
      // Volcano icons (triangle cone)
      for (const spec of VOLCANO_ICON_SPECS) {
        loadImg(spec.id, makeVolcanoSvg(spec.fill));
      }
      // Weather alert icons
      for (const spec of WEATHER_ICON_SPECS) {
        loadImg(spec.id, spec.svg);
      }
      // CrowdThreat category icons
      for (const spec of CT_ICON_SPECS) {
        loadImg(spec.id, spec.svg);
      }
      // UAP (UFO) icons — individual + cluster
      loadImg('ufo-icon', makeUfoSvg());
      loadImg('ufo-cluster', makeUfoClusterSvg());
      // Wastewater water drop icons — individual + cluster
      loadImg('ww-clean', makeWaterDropSvg('#00e5ff'));
      loadImg('ww-alert', makeWaterDropSvg('#ff2222', '#ff4444'));
      loadImg('ww-stale', makeWaterDropSvg('#556677'));
      loadImg('ww-cluster', makeWaterDropClusterSvg('#00e5ff'));
    }, 0);

  }, []);

  // Load Images into the Map Style once loaded
  const onMapLoad = useCallback((e: { target: maplibregl.Map }) => {
    initializeMap(e.target);
  }, [initializeMap]);

  const onMapStyleData = useCallback((e: { target: maplibregl.Map }) => {
    initializeMap(e.target);
  }, [initializeMap]);

  useEffect(() => {
    const map = mapRef.current?.getMap();
    if (map) initializeMap(map);
  }, [initializeMap, theme]);

  // Build a set of tracked icao24s to exclude from other flight layers
  const trackedIcaoSet = useMemo(() => {
    const s = new Set<string>();
    if (data?.tracked_flights) {
      for (const t of data.tracked_flights) {
        if (t.icao24) s.add(t.icao24.toLowerCase());
      }
    }
    return s;
  }, [data?.tracked_flights]);

  // Satellite GeoJSON with interpolated positions
  const satellitesGeoJSON = useMemo(
    () => {
      void interpTick;
      return activeLayers.satellites ? buildSatellitesGeoJSON(data?.satellites, inView, interpSat) : null;
    },
    [activeLayers.satellites, data?.satellites, inView, interpSat, interpTick],
  );

  const commConfig = useMemo<FlightLayerConfig>(
    () => ({
      colorMap: COLOR_MAP_COMMERCIAL,
      groundedMap: GROUNDED_ICON_MAP,
      typeLabel: 'flight',
      idPrefix: 'flight-',
      useTrackHeading: true,
    }),
    [],
  );
  const privConfig = useMemo<FlightLayerConfig>(
    () => ({
      colorMap: COLOR_MAP_PRIVATE,
      groundedMap: GROUNDED_ICON_MAP,
      typeLabel: 'private_flight',
      idPrefix: 'pflight-',
    }),
    [],
  );
  const jetsConfig = useMemo<FlightLayerConfig>(
    () => ({
      colorMap: COLOR_MAP_JETS,
      groundedMap: GROUNDED_ICON_MAP,
      typeLabel: 'private_jet',
      idPrefix: 'pjet-',
    }),
    [],
  );
  const milConfig = useMemo<FlightLayerConfig>(
    () => ({
      colorMap: COLOR_MAP_MILITARY,
      groundedMap: GROUNDED_ICON_MAP,
      typeLabel: 'military_flight',
      idPrefix: 'mflight-',
      milSpecialMap: MIL_SPECIAL_MAP,
    }),
    [],
  );

  const shipsLayerEnabled = backendViewportSyncEnabled;
  const sigintLayerEnabled = activeLayers.sigint_meshtastic || activeLayers.sigint_aprs;
  const globalIncidentsEnabled = activeLayers.global_incidents;

  const dynamicCommercialFlights = activeLayers.flights ? data?.commercial_flights : undefined;
  const dynamicPrivateFlights = activeLayers.private ? data?.private_flights : undefined;
  const dynamicPrivateJets = activeLayers.jets ? data?.private_jets : undefined;
  const dynamicMilitaryFlights = activeLayers.military ? data?.military_flights : undefined;
  const dynamicTrackedFlights = activeLayers.tracked ? data?.tracked_flights : undefined;
  const dynamicShips = shipsLayerEnabled ? data?.ships : undefined;
  const dynamicSigint = sigintLayerEnabled ? data?.sigint : undefined;

  const staticCctv = activeLayers.cctv ? data?.cctv : undefined;
  const staticKiwisdr = activeLayers.kiwisdr ? data?.kiwisdr : undefined;
  const staticPskReporter = activeLayers.psk_reporter ? data?.psk_reporter : undefined;
  const staticSatnogsStations = activeLayers.satnogs ? data?.satnogs_stations : undefined;
  const staticScanners = activeLayers.scanners ? data?.scanners : undefined;
  const staticFirmsFires = activeLayers.firms ? data?.firms_fires : undefined;
  const staticInternetOutages = activeLayers.internet_outages ? data?.internet_outages : undefined;
  const staticDatacenters = activeLayers.datacenters ? data?.datacenters : undefined;
  const staticPowerPlants = activeLayers.power_plants ? data?.power_plants : undefined;
  const staticViirsChangeNodes = activeLayers.viirs_nightlights ? data?.viirs_change_nodes : undefined;
  const staticMilitaryBases = activeLayers.military_bases ? data?.military_bases : undefined;
  const staticGdelt = globalIncidentsEnabled ? data?.gdelt : undefined;
  const staticLiveuamap = globalIncidentsEnabled ? data?.liveuamap : undefined;
  const staticAirQuality = activeLayers.air_quality ? data?.air_quality : undefined;
  const staticVolcanoes = activeLayers.volcanoes ? data?.volcanoes : undefined;
  const staticFishingActivity = activeLayers.fishing_activity ? data?.fishing_activity : undefined;
  const staticTrains = activeLayers.trains ? data?.trains : undefined;
  const staticUapSightings = activeLayers.uap_sightings ? data?.uap_sightings : undefined;
  const staticWastewater = activeLayers.wastewater ? data?.wastewater : undefined;
  const staticCrowdthreat = activeLayers.crowdthreat ? data?.crowdthreat : undefined;

  const dynamicMapLayers = useDynamicMapLayersWorker(
    {
      commercialFlights: dynamicCommercialFlights,
      privateFlights: dynamicPrivateFlights,
      privateJets: dynamicPrivateJets,
      militaryFlights: dynamicMilitaryFlights,
      trackedFlights: dynamicTrackedFlights,
      ships: dynamicShips,
      sigint: dynamicSigint,
      commConfig,
      privConfig,
      jetsConfig,
      milConfig,
    },
    [
      dynamicCommercialFlights,
      dynamicPrivateFlights,
      dynamicPrivateJets,
      dynamicMilitaryFlights,
      dynamicTrackedFlights,
      dynamicShips,
      dynamicSigint,
      commConfig,
      privConfig,
      jetsConfig,
      milConfig,
    ],
    {
      bounds: mapBounds,
      dtSeconds: dtSeconds.current,
      trackedIcaos: Array.from(trackedIcaoSet),
      activeLayers: {
        flights: activeLayers.flights,
        private: activeLayers.private,
        jets: activeLayers.jets,
        military: activeLayers.military,
        tracked: activeLayers.tracked,
        ships_military: activeLayers.ships_military,
        ships_cargo: activeLayers.ships_cargo,
        ships_civilian: activeLayers.ships_civilian,
        ships_passenger: activeLayers.ships_passenger,
        ships_tracked_yachts: activeLayers.ships_tracked_yachts,
        sigint_meshtastic: activeLayers.sigint_meshtastic,
        sigint_aprs: activeLayers.sigint_aprs,
      },
      activeFilters: activeFilters || {},
    },
    [
      mapBounds,
      interpTick,
      trackedIcaoSet,
      activeLayers.flights,
      activeLayers.private,
      activeLayers.jets,
      activeLayers.military,
      activeLayers.tracked,
      activeLayers.ships_military,
      activeLayers.ships_cargo,
      activeLayers.ships_civilian,
      activeLayers.ships_passenger,
      activeLayers.ships_tracked_yachts,
      activeLayers.sigint_meshtastic,
      activeLayers.sigint_aprs,
      activeFilters,
    ],
  );

  const staticMapLayers = useStaticMapLayersWorker(
    {
      cctv: staticCctv,
      kiwisdr: staticKiwisdr,
      pskReporter: staticPskReporter,
      satnogsStations: staticSatnogsStations,
      scanners: staticScanners,
      firmsFires: staticFirmsFires,
      internetOutages: staticInternetOutages,
      datacenters: staticDatacenters,
      powerPlants: staticPowerPlants,
      viirsChangeNodes: staticViirsChangeNodes,
      militaryBases: staticMilitaryBases,
      gdelt: staticGdelt,
      liveuamap: staticLiveuamap,
      airQuality: staticAirQuality,
      volcanoes: staticVolcanoes,
      fishingActivity: staticFishingActivity,
      ships: data?.ships,
      trains: staticTrains,
      uapSightings: staticUapSightings,
      wastewater: staticWastewater,
      crowdthreat: staticCrowdthreat,
    },
    [
      staticCctv,
      staticKiwisdr,
      staticPskReporter,
      staticSatnogsStations,
      staticScanners,
      staticFirmsFires,
      staticInternetOutages,
      staticDatacenters,
      staticPowerPlants,
      staticViirsChangeNodes,
      staticMilitaryBases,
      staticGdelt,
      staticLiveuamap,
      staticAirQuality,
      staticVolcanoes,
      staticFishingActivity,
      data?.ships,
      staticTrains,
      staticUapSightings,
      staticWastewater,
      staticCrowdthreat,
    ],
    {
      bounds: mapBounds,
      activeLayers: {
        cctv: activeLayers.cctv,
        kiwisdr: activeLayers.kiwisdr,
        psk_reporter: activeLayers.psk_reporter,
        satnogs: activeLayers.satnogs,
        scanners: activeLayers.scanners,
        firms: activeLayers.firms,
        internet_outages: activeLayers.internet_outages,
        datacenters: activeLayers.datacenters,
        power_plants: activeLayers.power_plants,
        viirs_nightlights: activeLayers.viirs_nightlights,
        military_bases: activeLayers.military_bases,
        global_incidents: activeLayers.global_incidents,
        air_quality: activeLayers.air_quality,
        volcanoes: activeLayers.volcanoes,
        fishing_activity: activeLayers.fishing_activity,
        trains: activeLayers.trains,
        uap_sightings: activeLayers.uap_sightings,
        wastewater: activeLayers.wastewater,
        crowdthreat: activeLayers.crowdthreat,
      },
    },
    [
      mapBounds,
      activeLayers.cctv,
      activeLayers.kiwisdr,
      activeLayers.psk_reporter,
      activeLayers.satnogs,
      activeLayers.scanners,
      activeLayers.firms,
      activeLayers.internet_outages,
      activeLayers.datacenters,
      activeLayers.power_plants,
      activeLayers.viirs_nightlights,
      activeLayers.military_bases,
      activeLayers.global_incidents,
      activeLayers.air_quality,
      activeLayers.volcanoes,
      activeLayers.fishing_activity,
      activeLayers.trains,
      activeLayers.uap_sightings,
      activeLayers.wastewater,
      activeLayers.crowdthreat,
    ],
  );

  const {
    commercialFlightsGeoJSON: commFlightsGeoJSON,
    privateFlightsGeoJSON: privFlightsGeoJSON,
    privateJetsGeoJSON: privJetsGeoJSON,
    militaryFlightsGeoJSON: milFlightsGeoJSON,
    trackedFlightsGeoJSON,
    shipsGeoJSON,
    meshtasticGeoJSON,
    aprsGeoJSON,
  } = dynamicMapLayers;

  const {
    cctvGeoJSON,
    kiwisdrGeoJSON,
    pskReporterGeoJSON,
    satnogsGeoJSON,
    scannerGeoJSON,
    firmsGeoJSON,
    internetOutagesGeoJSON,
    dataCentersGeoJSON,
    powerPlantsGeoJSON,
    viirsChangeNodesGeoJSON,
    militaryBasesGeoJSON,
    gdeltGeoJSON,
    liveuaGeoJSON,
    airQualityGeoJSON,
    volcanoesGeoJSON,
    fishingGeoJSON,
    trainsGeoJSON,
    uapSightingsGeoJSON,
    wastewaterGeoJSON,
    crowdthreatGeoJSON,
  } = staticMapLayers;

  // Extract cluster label positions via shared hook
  const shipClusters = useClusterLabels(mapRef, 'ships-clusters-layer', shipsGeoJSON);
  const eqClusters = useClusterLabels(mapRef, 'eq-clusters-layer', earthquakesGeoJSON);

  const carriersGeoJSON = useMemo(
    () => (activeLayers.ships_military ? buildCarriersGeoJSON(data?.ships) : null),
    [activeLayers.ships_military, data?.ships],
  );

  // SAR anomaly pins (Mode B) + AOI watchbox circles.  AOIs render whenever
  // the SAR layer is on; anomalies only appear when Mode B has produced
  // something.  The render path is fully imperative via useImperativeSource.
  //
  // AOIs come from their own endpoint (/api/sar/aois) rather than the
  // dashboard payload because they're operator-managed metadata, not a
  // polled feed — the list rarely changes and we don't want to bloat
  // dashboard responses with it.
  const [sarAoisList, setSarAoisList] = useState<
    import('@/types/dashboard').SarAoi[]
  >([]);
  useEffect(() => {
    if (!activeLayers.sar) return;
    let cancelled = false;
    const run = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/sar/aois`, {
          credentials: 'include',
        });
        if (!res.ok || cancelled) return;
        const body = await res.json();
        if (!cancelled && Array.isArray(body?.aois)) {
          setSarAoisList(body.aois);
        }
      } catch {
        // ignore — AOIs are a nice-to-have
      }
    };
    run();
    // Refresh every 2 minutes while the layer is on so operator edits
    // propagate without a full page reload.
    const iv = setInterval(run, 120_000);
    return () => {
      cancelled = true;
      clearInterval(iv);
    };
  }, [activeLayers.sar, sarAoiListVersion]);

  const sarAnomaliesGeoJSON = useMemo(
    () => (activeLayers.sar ? buildSarAnomaliesGeoJSON(data?.sar_anomalies) : null),
    [activeLayers.sar, data?.sar_anomalies],
  );
  const sarAoisGeoJSON = useMemo(
    () => (activeLayers.sar ? buildSarAoisGeoJSON(sarAoisList) : null),
    [activeLayers.sar, sarAoisList],
  );

  const getSelectedEntityLiveCoords = useCallback(
    (entity: ReturnType<typeof findSelectedEntity>): [number, number] | null => {
      if (!entity || entity.lat == null || entity.lng == null) return null;
      switch (selectedEntity?.type) {
        case 'ship':
          return interpShip(entity);
        case 'flight':
        case 'private_flight':
        case 'military_flight':
        case 'private_jet':
        case 'tracked_flight':
        case 'uav':
          return interpFlight(entity);
        default:
          return [entity.lng, entity.lat];
      }
    },
    [interpFlight, interpShip, selectedEntity?.type],
  );

  const activeRouteGeoJSON = useMemo(() => {
    void interpTick;
    const entity = findSelectedEntity(selectedEntity, data);
    if (!entity) return null;

    const currentLoc = getSelectedEntityLiveCoords(entity) ?? [entity.lng, entity.lat];
    let originLoc = 'origin_loc' in entity ? entity.origin_loc : null;
    let destLoc = 'dest_loc' in entity ? entity.dest_loc : null;
    let originName = 'origin_name' in entity ? entity.origin_name : '';
    let destName = 'dest_name' in entity ? entity.dest_name : '';

    if (dynamicRoute && dynamicRoute.orig_loc && dynamicRoute.dest_loc) {
      originLoc = dynamicRoute.orig_loc;
      destLoc = dynamicRoute.dest_loc;
      originName = dynamicRoute.origin_name || originName;
      destName = dynamicRoute.dest_name || destName;
    }

    if (!originLoc && !destLoc) return null;

    const features: GeoJSON.Feature[] = [];
    // Extract IATA codes from "IATA: Airport Name" format
    const originCode = (originName || '').split(':')[0]?.trim() || '';
    const destCode = (destName || '').split(':')[0]?.trim() || '';

    if (originLoc) {
      features.push({
        type: 'Feature',
        properties: { type: 'route-origin' },
        geometry: { type: 'LineString', coordinates: [currentLoc, originLoc] },
      });
      features.push({
        type: 'Feature',
        properties: { type: 'airport', code: originCode, role: 'DEP' },
        geometry: { type: 'Point', coordinates: originLoc },
      });
    }
    if (destLoc) {
      features.push({
        type: 'Feature',
        properties: { type: 'route-dest' },
        geometry: { type: 'LineString', coordinates: [currentLoc, destLoc] },
      });
      features.push({
        type: 'Feature',
        properties: { type: 'airport', code: destCode, role: 'ARR' },
        geometry: { type: 'Point', coordinates: destLoc },
      });
    }

    if (features.length === 0) return null;
    return { type: 'FeatureCollection' as const, features };
  }, [selectedEntity, data, dynamicRoute, getSelectedEntityLiveCoords, interpTick]);

  // Trail history GeoJSON: shows where the SELECTED aircraft has been
  const trailGeoJSON = useMemo(() => {
    void interpTick;
    const entity = findSelectedEntity(selectedEntity, data);
    if (!entity || !('trail' in entity) || !entity.trail || entity.trail.length < 2) return null;

    // Parse trail points — backend sends [lat, lng, alt, ts] arrays
    type TrailPt = { lng: number; lat: number; alt: number; ts: number };
    const points: TrailPt[] = (
      entity.trail as Array<{ lat?: number; lng?: number; alt?: number; ts?: number } | number[]>
    ).map((p) => {
      if (Array.isArray(p)) {
        return { lat: p[0] as number, lng: p[1] as number, alt: (p[2] as number) || 0, ts: (p[3] as number) || 0 };
      }
      return { lat: p.lat ?? 0, lng: p.lng ?? 0, alt: p.alt ?? 0, ts: p.ts ?? 0 };
    }).filter((p) => p.lat !== 0 || p.lng !== 0);

    const currentLoc = getSelectedEntityLiveCoords(entity);
    if (currentLoc && points.length > 0) {
      const lastPt = points[points.length - 1];
      points.push({ lng: currentLoc[0], lat: currentLoc[1], alt: lastPt.alt, ts: Date.now() / 1000 });
    }

    if (points.length < 2) return null;

    // Split into segments colored by altitude for gradient effect
    // Color ramp: ground(magenta) → low(blue) → mid(cyan) → high(green) → very high(yellow) → max(orange/red)
    const altToColor = (altM: number): string => {
      const ft = altM / 0.3048;
      if (ft < 1000) return '#ff44ff';     // magenta — ground/taxi
      if (ft < 5000) return '#6366f1';     // indigo — low
      if (ft < 15000) return '#22d3ee';    // cyan — mid climb/descent
      if (ft < 25000) return '#22c55e';    // green — medium
      if (ft < 35000) return '#eab308';    // yellow — high
      return '#f97316';                     // orange — cruise
    };

    const features: GeoJSON.Feature[] = [];
    for (let i = 0; i < points.length - 1; i++) {
      const a = points[i], b = points[i + 1];
      const progress = i / (points.length - 1);
      features.push({
        type: 'Feature' as const,
        properties: {
          type: 'trail',
          color: altToColor((a.alt + b.alt) / 2),
          opacity: 0.4 + progress * 0.5, // older segments more transparent
          segIndex: i,
        },
        geometry: {
          type: 'LineString' as const,
          coordinates: [[a.lng, a.lat], [b.lng, b.lat]],
        },
      });
    }

    return { type: 'FeatureCollection' as const, features };
  }, [selectedEntity, data, getSelectedEntityLiveCoords, interpTick]);

  // Predictive vector GeoJSON: dotted line projecting ~5 min ahead based on heading + speed
  // Skip when entity has a known route (origin+dest) — the route line already shows where it's going
  const predictiveGeoJSON = useMemo(() => {
    void interpTick;
    const entity = findSelectedEntity(selectedEntity, data);
    if (dynamicRoute?.orig_loc || dynamicRoute?.dest_loc) {
      return null;
    }
    if (
      entity &&
      'dest_name' in entity &&
      entity.dest_name &&
      entity.dest_name !== 'UNKNOWN'
    ) {
      return null;
    }
    const currentLoc = getSelectedEntityLiveCoords(entity);
    if (!entity || !currentLoc) return buildPredictiveGeoJSON(entity);
    return buildPredictiveGeoJSON({
      ...entity,
      lng: currentLoc[0],
      lat: currentLoc[1],
    });
  }, [selectedEntity, data, dynamicRoute, getSelectedEntityLiveCoords, interpTick]);

  // Proximity range rings: 10nm, 50nm, 100nm around selected entity
  const proximityRingsGeoJSON = useMemo(() => {
    void interpTick;
    const entity = findSelectedEntity(selectedEntity, data);
    const currentLoc = getSelectedEntityLiveCoords(entity);
    if (!currentLoc) return null;
    return buildProximityRingsGeoJSON(currentLoc[1], currentLoc[0], [10, 50, 100]);
  }, [selectedEntity, data, getSelectedEntityLiveCoords, interpTick]);

  const spreadAlerts = useMemo(() => {
    if (!data?.news) return [];
    // Limit visible alerts by zoom: at low zoom show only top threats,
    // at high zoom show more. Prevents map clutter with dozens of boxes.
    const maxAlerts = mapZoom < 4 ? 6 : mapZoom < 6 ? 10 : 16;
    const sorted = [...data.news].sort((a, b) => (b.risk_score || 0) - (a.risk_score || 0));
    return spreadAlertItems(sorted.slice(0, maxAlerts), mapZoom, dismissedAlerts);
  }, [data?.news, mapZoom, dismissedAlerts]);

  const uavGeoJSON = useMemo(
    () => (activeLayers.military ? buildUavGeoJSON(data?.uavs, inView) : null),
    [activeLayers.military, data?.uavs, inView],
  );

  // UAV range circles removed — real ADS-B drones don't have a fixed orbit center

  const frontlineGeoJSON = useMemo(
    () => (activeLayers.ukraine_frontline ? buildFrontlineGeoJSON(data?.frontlines) : null),
    [activeLayers.ukraine_frontline, data?.frontlines],
  );

  // Interactive layer IDs for click handling
  const activeInteractiveLayerIds = [
    commFlightsGeoJSON && 'commercial-flights-layer',
    privFlightsGeoJSON && 'private-flights-layer',
    privJetsGeoJSON && 'private-jets-layer',
    milFlightsGeoJSON && 'military-flights-layer',
    shipsGeoJSON && 'ships-clusters-layer',
    shipsGeoJSON && 'ships-layer',
    carriersGeoJSON && 'carriers-layer',
    trackedFlightsGeoJSON && 'tracked-flights-layer',
    uavGeoJSON && 'uav-layer',
    gdeltGeoJSON && 'gdelt-layer',
    liveuaGeoJSON && 'liveuamap-layer',
    frontlineGeoJSON && 'ukraine-frontline-layer',
    earthquakesGeoJSON && 'earthquakes-layer',
    satellitesGeoJSON && 'satellites-layer',
    cctvGeoJSON && 'cctv-clusters',
    cctvGeoJSON && 'cctv-cluster-count',
    cctvGeoJSON && 'cctv-layer',
    kiwisdrGeoJSON && 'kiwisdr-clusters',
    kiwisdrGeoJSON && 'kiwisdr-layer',
    pskReporterGeoJSON && 'psk-reporter-clusters',
    pskReporterGeoJSON && 'psk-reporter-layer',
    satnogsGeoJSON && 'satnogs-clusters',
    satnogsGeoJSON && 'satnogs-layer',
    tinygsGeoJSON && 'tinygs-layer',
    scannerGeoJSON && 'scanner-clusters',
    scannerGeoJSON && 'scanner-layer',
    internetOutagesGeoJSON && 'internet-outages-layer',
    dataCentersGeoJSON && 'datacenters-layer',
    powerPlantsGeoJSON && 'power-plants-layer',
    viirsChangeNodesGeoJSON && 'viirs-change-nodes-layer',
    shodanGeoJSON && 'shodan-clusters',
    shodanGeoJSON && 'shodan-cluster-count',
    shodanGeoJSON && 'shodan-layer',
    militaryBasesGeoJSON && 'military-bases-layer',
    firmsGeoJSON && 'firms-viirs-layer',
    meshtasticGeoJSON && 'meshtastic-clusters',
    meshtasticGeoJSON && 'meshtastic-cluster-count',
    meshtasticGeoJSON && 'meshtastic-circles',
    aprsGeoJSON && 'aprs-clusters',
    aprsGeoJSON && 'aprs-cluster-count',
    aprsGeoJSON && 'aprs-triangles',
    ukraineAlertsGeoJSON && 'ukraine-alerts-fill',
    weatherAlertsGeoJSON && 'weather-alerts-fill',
    weatherAlertLabelsGeoJSON && 'weather-alert-icons',
    airQualityGeoJSON && 'air-quality-layer',
    volcanoesGeoJSON && 'volcanoes-layer',
    fishingGeoJSON && 'fishing-clusters',
    fishingGeoJSON && 'fishing-layer',
    trainsGeoJSON && 'trains-layer',
    uapSightingsGeoJSON && 'uap-sightings-cluster-bg',
    uapSightingsGeoJSON && 'uap-sightings-clusters',
    uapSightingsGeoJSON && 'uap-sightings-dot',
    uapSightingsGeoJSON && 'uap-sightings-layer',
    wastewaterGeoJSON && 'wastewater-cluster-bg',
    wastewaterGeoJSON && 'wastewater-clusters',
    wastewaterGeoJSON && 'wastewater-dot',
    wastewaterGeoJSON && 'wastewater-layer',
    crowdthreatGeoJSON && 'crowdthreat-layer',
    sarAnomaliesGeoJSON && 'sar-anomalies-layer',
    sarAoisGeoJSON && 'sar-aois-fill',
    aiIntelGeoJSON && 'ai-intel-clusters',
    aiIntelGeoJSON && 'ai-intel-pin-layer',
    correlationsGeoJSON && 'corr-rf-fill',
    correlationsGeoJSON && 'corr-mil-fill',
    correlationsGeoJSON && 'corr-infra-fill',
    correlationsGeoJSON && 'corr-contra-fill',
    correlationsGeoJSON && 'corr-analysis-fill',
  ].filter(Boolean) as string[];

  useEffect(() => {
    const map = mapRef.current?.getMap();
    if (!map) return;

    const emphasizedLayers = [
      'uap-sightings-cluster-bg',
      'uap-sightings-clusters',
      'uap-sightings-dot',
      'uap-sightings-layer',
      'wastewater-cluster-bg',
      'wastewater-clusters',
      'wastewater-dot',
      'wastewater-layer',
    ];

    const moveEmphasizedLayersToTop = () => {
      for (const layerId of emphasizedLayers) {
        if (map.getLayer(layerId)) {
          map.moveLayer(layerId);
        }
      }
    };

    const rafId = window.requestAnimationFrame(moveEmphasizedLayersToTop);
    const timeoutId = window.setTimeout(moveEmphasizedLayersToTop, 120);

    return () => {
      window.cancelAnimationFrame(rafId);
      window.clearTimeout(timeoutId);
    };
  }, [activeLayers.uap_sightings, activeLayers.wastewater, theme]);

  // --- Imperative source updates: bypass React reconciliation for GeoJSON layers ---
  const mapForHook = mapRef.current;
  useImperativeSource(mapForHook, 'commercial-flights', commFlightsGeoJSON);
  useImperativeSource(mapForHook, 'private-flights', privFlightsGeoJSON);
  useImperativeSource(mapForHook, 'private-jets', privJetsGeoJSON);
  useImperativeSource(mapForHook, 'military-flights', milFlightsGeoJSON);
  useImperativeSource(mapForHook, 'tracked-flights', trackedFlightsGeoJSON);
  useImperativeSource(mapForHook, 'uavs', uavGeoJSON);
  useImperativeSource(mapForHook, 'satellites', satellitesGeoJSON);
  useImperativeSource(mapForHook, 'tinygs', tinygsGeoJSON);
  useImperativeSource(mapForHook, 'cctv', cctvGeoJSON, 75);
  useImperativeSource(mapForHook, 'kiwisdr', kiwisdrGeoJSON, 75);
  useImperativeSource(mapForHook, 'psk-reporter', pskReporterGeoJSON, 75);
  useImperativeSource(mapForHook, 'satnogs', satnogsGeoJSON, 75);
  useImperativeSource(mapForHook, 'scanners', scannerGeoJSON, 75);
  useImperativeSource(mapForHook, 'firms-fires', firmsGeoJSON, 900);
  useImperativeSource(mapForHook, 'internet-outages', internetOutagesGeoJSON, 100);
  useImperativeSource(mapForHook, 'datacenters', dataCentersGeoJSON, 120);
  useImperativeSource(mapForHook, 'power-plants', powerPlantsGeoJSON, 140);
  useImperativeSource(mapForHook, 'viirs-change-nodes', viirsChangeNodesGeoJSON, 120);
  useImperativeSource(mapForHook, 'military-bases', militaryBasesGeoJSON, 75);
  useImperativeSource(mapForHook, 'gdelt', gdeltGeoJSON, 75);
  useImperativeSource(mapForHook, 'liveuamap', liveuaGeoJSON, 75);
  useImperativeSource(mapForHook, 'air-quality-source', airQualityGeoJSON, 100);
  useImperativeSource(mapForHook, 'volcanoes-source', volcanoesGeoJSON, 100);
  useImperativeSource(mapForHook, 'fishing-source', fishingGeoJSON, 100);
  useImperativeSource(mapForHook, 'uap-sightings-source', uapSightingsGeoJSON, 100);
  useImperativeSource(mapForHook, 'wastewater-source', wastewaterGeoJSON, 100);
  useImperativeSource(mapForHook, 'crowdthreat-source', crowdthreatGeoJSON, 100);
  useImperativeSource(mapForHook, 'ships', shipsGeoJSON, 75);
  useImperativeSource(mapForHook, 'meshtastic-source', meshtasticGeoJSON, 60);
  useImperativeSource(mapForHook, 'aprs-source', aprsGeoJSON, 60);
  useImperativeSource(mapForHook, 'trains', trainsGeoJSON, 60);
  useImperativeSource(mapForHook, 'sar-aois', sarAoisGeoJSON, 120);
  useImperativeSource(mapForHook, 'sar-anomalies', sarAnomaliesGeoJSON, 120);

  const handleMouseMove = useCallback(
    (evt: MapLayerMouseEvent) => {
      if (onMouseCoords) onMouseCoords({ lat: evt.lngLat.lat, lng: evt.lngLat.lng });
    },
    [onMouseCoords],
  );

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const opacityFilter: any = selectedEntity
    ? [
      'case',
      [
        'all',
        ['==', ['get', 'type'], selectedEntity.type],
        ['==', ['get', 'id'], selectedEntity.id],
      ],
      1.0,
      0.0,
    ]
    : 1.0;

  return (
    <div
      className={`relative h-full w-full z-0 isolate ${selectedEntity && ['region_dossier', 'gdelt', 'liveuamap', 'news'].includes(selectedEntity.type) ? 'map-focus-active' : ''}`}
      style={pinPlacementMode || sarAoiDropMode ? { cursor: 'crosshair' } : undefined}
    >
      <Map
        ref={mapRef}
        reuseMaps
        maxTileCacheSize={200}
        fadeDuration={0}
        style={{ width: '100%', height: '100%' }}
        initialViewState={initialViewState}
        onMoveStart={() => {
          setIsMapInteracting((prev) => (prev ? prev : true));
        }}
        onMove={(evt) => {
          viewStateRef.current = evt.viewState;
        }}
        onMoveEnd={() => {
          setIsMapInteracting(false);
          const currentViewState = viewStateRef.current;
          setMapZoom((prevZoom) =>
            Math.abs(prevZoom - currentViewState.zoom) > 0.01 ? currentViewState.zoom : prevZoom,
          );
          onViewStateChange?.({
            zoom: currentViewState.zoom,
            latitude: currentViewState.latitude,
          });
          updateBounds();
        }}
        onMouseMove={handleMouseMove}
        onContextMenu={(evt) => {
          evt.preventDefault();
          onRightClick?.({ lat: evt.lngLat.lat, lng: evt.lngLat.lng });
        }}
        mapStyle={mapThemeStyle}
        mapLib={maplibregl}
        attributionControl={false}
        onLoad={onMapLoad}
        onStyleData={onMapStyleData}
        onIdle={() => {
          setIsMapInteracting(false);
          updateBounds();
        }}
        interactiveLayerIds={activeInteractiveLayerIds}
        onClick={(e) => {
          // Measurement mode: place waypoints instead of selecting entities
          if (measureMode && onMeasureClick) {
            onMeasureClick({ lat: e.lngLat.lat, lng: e.lngLat.lng });
            return;
          }
          // SAR AOI drop mode
          if (sarAoiDropMode) {
            onSarAoiDropped?.({ lat: e.lngLat.lat, lng: e.lngLat.lng });
            return;
          }
          // Pin placement mode
          if (pinPlacementMode) {
            const clickedFeature = e.features?.[0];
            const clickedProps = clickedFeature?.properties || {};
            const isEntity = clickedFeature && clickedProps.type && clickedProps.id && !clickedProps.cluster;
            setPendingPin({
              lat: e.lngLat.lat,
              lng: e.lngLat.lng,
              entity: isEntity ? {
                entity_type: String(clickedProps.type || ''),
                entity_id: String(clickedProps.id || ''),
                entity_label: String(clickedProps.name || clickedProps.callsign || clickedProps.label || ''),
              } : null,
            });
            return;
          }
          // AI Intel pin click → open detail popup (takes precedence over entity selection)
          if (e.features && e.features.length > 0) {
            const aiPin = e.features.find(
              (f) => f.layer?.id === 'ai-intel-pin-layer' && !(f.properties as Record<string, unknown> | null)?.cluster,
            );
            if (aiPin && aiPin.properties?.id) {
              setOpenPinDetailId(String(aiPin.properties.id));
              return;
            }
          }
          if (selectedEntity) {
            onEntityClick?.(null);
          } else if (e.features && e.features.length > 0) {
            // SAR AOI fill spans large polygons (often hundreds of km wide)
            // and renders above entity layers. If an entity (flight, ship,
            // SDR receiver, etc.) is also under the cursor, prefer it — the
            // AOI should only win when the user clicks empty space inside it.
            const nonAoiFeature = e.features.find(
              (f) => f.layer?.id !== 'sar-aois-fill',
            );
            const feature = nonAoiFeature ?? e.features[0];
            const props = feature.properties || {};

            // If the clicked feature is a cluster, zoom into it instead of selecting an entity
            if (props.cluster) {
              const targetZoom = (mapRef.current?.getMap().getZoom() ?? mapZoom) + 2;
              mapRef.current?.flyTo({
                center: [e.lngLat.lng, e.lngLat.lat],
                zoom: targetZoom,
                duration: 500,
              });
              return;
            }
            onEntityClick?.({
              id: props.id,
              type: props.type,
              name: props.name,
              media_url: props.media_url,
              extra: props,
            });
          } else {
            onEntityClick?.(null);
          }
        }}
      >
        <AttributionControl
          compact
          customAttribution={[
            '<a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">© OpenStreetMap contributors</a>',
            '<a href="https://carto.com/attribution" target="_blank" rel="noopener">CARTO</a>',
            '<a href="https://adsb.lol" target="_blank" rel="noopener">adsb.lol (ODbL)</a>',
            '<a href="https://opensky-network.org" target="_blank" rel="noopener">OpenSky</a>',
            '<a href="https://celestrak.org" target="_blank" rel="noopener">CelesTrak</a>',
            '<a href="https://aisstream.io" target="_blank" rel="noopener">aisstream.io</a>',
            '<a href="https://meshtastic.liamcottle.net" target="_blank" rel="noopener">Meshtastic map by Liam Cottle</a>',
            'NASA · NOAA · USGS · GDELT',
            '<a href="https://github.com/BigBodyCobain/Shadowbroker/blob/main/DATA-ATTRIBUTION.md" target="_blank" rel="noopener">full sources</a>',
          ]}
        />
        {/* Esri World Imagery — high-res static satellite (zoom 0-18+) */}
        {activeLayers.highres_satellite && (
          <Source
            id="esri-world-imagery"
            type="raster"
            tiles={[
              'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
            ]}
            tileSize={256}
            maxzoom={18}
            attribution="Esri, Maxar, Earthstar Geographics"
          >
            <Layer
              id="esri-world-imagery-layer"
              type="raster"
              beforeId="imagery-ceiling"
              paint={{
                'raster-opacity': 1,
                'raster-fade-duration': 300,
              }}
            />
          </Source>
        )}

        {/* NASA GIBS MODIS Terra — daily satellite imagery overlay */}
        {activeLayers.gibs_imagery && gibsDate && (
          <Source
            key={`gibs-${gibsDate}`}
            id="gibs-modis"
            type="raster"
            tiles={[
              `https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/MODIS_Terra_CorrectedReflectance_TrueColor/default/${gibsDate}/GoogleMapsCompatible_Level9/{z}/{y}/{x}.jpg`,
            ]}
            tileSize={256}
            maxzoom={9}
          >
            <Layer
              id="gibs-modis-layer"
              type="raster"
              beforeId="imagery-ceiling"
              paint={{
                'raster-opacity': gibsOpacity ?? 0.6,
                'raster-fade-duration': 0,
              }}
            />
          </Source>
        )}

        {/* NASA GIBS VIIRS Night Lights — Black Marble night-lights overlay */}
        {activeLayers.viirs_nightlights && viirsResolvedTileTemplate && (() => {
          const viirsTileTemplate = viirsResolvedTileTemplate;
          return (
            <Source
              key={`viirs-nl-${viirsTileTemplate}`}
              id="viirs-nightlights"
              type="raster"
              tiles={[viirsTileTemplate]}
              tileSize={256}
              maxzoom={8}
            >
              <Layer
                id="viirs-nightlights-layer"
                type="raster"
                beforeId="imagery-ceiling"
                paint={{
                  'raster-opacity': 0.9,
                  'raster-fade-duration': 0,
                }}
              />
            </Source>
          );
        })()}

        {/* Sentinel Hub — user-provided Copernicus CDSE WMTS tiles */}
        {activeLayers.sentinel_hub && sentinelTileUrl && (
          <Source
            key={`sentinel-${sentinelDate}-${sentinelPreset}`}
            id="sentinel-hub"
            type="raster"
            tiles={[sentinelTileUrl]}
            tileSize={256}
            minzoom={5}
            maxzoom={14}
          >
            <Layer
              id="sentinel-hub-layer"
              type="raster"
              beforeId="imagery-ceiling"
              paint={{
                'raster-opacity': sentinelOpacity ?? 0.6,
                'raster-fade-duration': 0,
              }}
            />
          </Source>
        )}

        {/* Esri Reference Overlay — borders, labels, and places on top of imagery layers */}
        {showImageryReferenceOverlay && (
          <Source
            id="esri-reference-overlay"
            type="raster"
            tiles={[
              'https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}',
            ]}
            tileSize={256}
            maxzoom={18}
          >
            <Layer
              id="esri-reference-overlay-layer"
              type="raster"
              paint={{
                'raster-opacity': imageryReferenceOverlayOpacity,
                'raster-fade-duration': 300,
              }}
            />
          </Source>
        )}

        {/* NASA FIRMS VIIRS — fire hotspot icons from FIRMS CSV feed */}
        {/* firms-fires: data pushed imperatively via useImperativeSource */}
        <Source
          id="firms-fires"
          type="geojson"
          data={EMPTY_FC}
          cluster={true}
          clusterRadius={40}
          clusterMaxZoom={10}
        >
          {/* Cluster fire icons — flame shape to differentiate from Global Incidents circles */}
          <Layer
            id="firms-clusters"
            type="symbol"
            filter={['has', 'point_count']}
            layout={{
              'icon-image': [
                'step',
                ['get', 'point_count'],
                'fire-cluster-sm',
                10,
                'fire-cluster-md',
                50,
                'fire-cluster-lg',
                200,
                'fire-cluster-xl',
              ],
              'icon-size': ['step', ['get', 'point_count'], 1.0, 10, 1.1, 50, 1.2, 200, 1.3],
              'icon-allow-overlap': true,
              'icon-ignore-placement': true,
              'text-field': '{point_count_abbreviated}',
              'text-font': ['Noto Sans Bold'],
              'text-size': ['step', ['get', 'point_count'], 9, 10, 10, 50, 11, 200, 12],
              'text-offset': [0, 0.15],
              'text-allow-overlap': true,
            }}
            paint={{
              'text-color': '#ffffff',
              'text-halo-color': 'rgba(0,0,0,0.8)',
              'text-halo-width': 1.2,
            }}
          />
          {/* Individual fire icons — flame shape sized by FRP */}
          <Layer
            id="firms-viirs-layer"
            type="symbol"
            filter={['!', ['has', 'point_count']]}
            layout={{
              'icon-image': ['get', 'iconId'],
              'icon-size': ['interpolate', ['linear'], ['zoom'], 2, 0.4, 5, 0.6, 8, 0.8, 12, 1.0],
              'icon-allow-overlap': true,
              'icon-ignore-placement': true,
            }}
          />
        </Source>

        {/* SOLAR TERMINATOR — night overlay */}
        {activeLayers.day_night && nightGeoJSON && (
          <Source id="night-overlay" type="geojson" data={nightGeoJSON}>
            <Layer
              id="night-overlay-layer"
              type="fill"
              paint={{
                'fill-color': '#0a0e1a',
                'fill-opacity': 0.35,
              }}
            />
          </Source>
        )}

        {/* ═══ GROUND OVERLAYS — rendered below ships, mesh, and flights ═══ */}

        <Source id="frontlines" type="geojson" data={(frontlineGeoJSON ?? EMPTY_FC)}>
          <Layer
            id="ukraine-frontline-layer"
            type="fill"
            paint={{
              'fill-color': '#ff0000',
              'fill-opacity': 0.3,
              'fill-outline-color': '#ff5500',
            }}
          />
        </Source>

        <Source
          id="earthquakes"
          type="geojson"
          data={(earthquakesGeoJSON ?? EMPTY_FC)}
          cluster={true}
          clusterMaxZoom={10}
          clusterRadius={60}
        >
          {/* Earthquake cluster circles */}
          <Layer
            id="eq-clusters-layer"
            type="circle"
            filter={['has', 'point_count']}
            paint={{
              'circle-color': 'rgba(255, 170, 0, 0.85)',
              'circle-radius': ['step', ['get', 'point_count'], 12, 5, 16, 10, 20, 20, 24],
              'circle-stroke-width': 2,
              'circle-stroke-color': 'rgba(255, 200, 0, 1.0)',
            }}
          />
          {/* Individual (unclustered) earthquake icons */}
          <Layer
            id="earthquakes-layer"
            type="symbol"
            filter={['!', ['has', 'point_count']]}
            layout={{
              'icon-image': 'icon-threat',
              'icon-size': 0.5,
              'icon-allow-overlap': true,
            }}
            paint={{ 'icon-opacity': 1.0 }}
          />
        </Source>

        {/* GPS Jamming Zones — red translucent grid squares */}
        <Source id="gps-jamming" type="geojson" data={(jammingGeoJSON ?? EMPTY_FC)}>
          <Layer
            id="gps-jamming-fill"
            type="fill"
            paint={{
              'fill-color': '#ff0040',
              'fill-opacity': ['get', 'opacity'],
            }}
          />
          <Layer
            id="gps-jamming-outline"
            type="line"
            paint={{
              'line-color': '#ff0040',
              'line-width': 1.5,
              'line-opacity': 0.6,
            }}
          />
          <Layer
            id="gps-jamming-label"
            type="symbol"
            layout={{
              'text-field': [
                'concat',
                'GPS JAM ',
                ['to-string', ['round', ['*', 100, ['get', 'ratio']]]],
                '%',
              ],
              'text-size': ['interpolate', ['linear'], ['zoom'], 2, 8, 5, 10, 8, 12],
              'text-allow-overlap': false,
              'text-ignore-placement': false,
            }}
            paint={{
              'text-color': '#ff4060',
              'text-halo-color': '#000000',
              'text-halo-width': 1.5,
            }}
          />
        </Source>

        {/* Correlation Alerts — Emergent Intelligence grid squares */}
        <Source id="correlations" type="geojson" data={(correlationsGeoJSON ?? EMPTY_FC)}>
          {/* RF Anomaly — grey */}
          <Layer
            id="corr-rf-fill"
            type="fill"
            filter={['==', ['get', 'corr_type'], 'rf_anomaly']}
            minzoom={3}
            paint={{
              'fill-color': '#6b7280',
              'fill-opacity': ['get', 'opacity'],
            }}
          />
          <Layer
            id="corr-rf-outline"
            type="line"
            filter={['==', ['get', 'corr_type'], 'rf_anomaly']}
            minzoom={3}
            paint={{
              'line-color': '#6b7280',
              'line-width': 1.5,
              'line-opacity': 0.6,
            }}
          />
          <Layer
            id="corr-rf-label"
            type="symbol"
            filter={['==', ['get', 'corr_type'], 'rf_anomaly']}
            minzoom={3}
            layout={{
              'text-field': ['concat', 'RF ANOMALY\n', ['get', 'drivers']],
              'text-size': ['interpolate', ['linear'], ['zoom'], 3, 7, 5, 9, 8, 11],
              'text-allow-overlap': false,
              'text-ignore-placement': false,
            }}
            paint={{
              'text-color': '#9ca3af',
              'text-halo-color': '#000000',
              'text-halo-width': 1.5,
            }}
          />
          {/* Military Buildup — red dashed */}
          <Layer
            id="corr-mil-fill"
            type="fill"
            filter={['==', ['get', 'corr_type'], 'military_buildup']}
            minzoom={3}
            paint={{
              'fill-color': '#dc2626',
              'fill-opacity': ['get', 'opacity'],
            }}
          />
          <Layer
            id="corr-mil-outline"
            type="line"
            filter={['==', ['get', 'corr_type'], 'military_buildup']}
            minzoom={3}
            paint={{
              'line-color': '#dc2626',
              'line-width': 2,
              'line-opacity': 0.7,
              'line-dasharray': [4, 2],
            }}
          />
          <Layer
            id="corr-mil-label"
            type="symbol"
            filter={['==', ['get', 'corr_type'], 'military_buildup']}
            minzoom={3}
            layout={{
              'text-field': ['concat', 'MIL BUILDUP\n', ['get', 'drivers']],
              'text-size': ['interpolate', ['linear'], ['zoom'], 3, 7, 5, 9, 8, 11],
              'text-allow-overlap': false,
              'text-ignore-placement': false,
            }}
            paint={{
              'text-color': '#f87171',
              'text-halo-color': '#000000',
              'text-halo-width': 1.5,
            }}
          />
          {/* Infrastructure Cascade — black */}
          <Layer
            id="corr-infra-fill"
            type="fill"
            filter={['==', ['get', 'corr_type'], 'infra_cascade']}
            minzoom={3}
            paint={{
              'fill-color': '#1f2937',
              'fill-opacity': ['get', 'opacity'],
            }}
          />
          <Layer
            id="corr-infra-outline"
            type="line"
            filter={['==', ['get', 'corr_type'], 'infra_cascade']}
            minzoom={3}
            paint={{
              'line-color': '#374151',
              'line-width': 1.5,
              'line-opacity': 0.7,
            }}
          />
          <Layer
            id="corr-infra-label"
            type="symbol"
            filter={['==', ['get', 'corr_type'], 'infra_cascade']}
            minzoom={3}
            layout={{
              'text-field': ['concat', 'INFRA CASCADE\n', ['get', 'drivers']],
              'text-size': ['interpolate', ['linear'], ['zoom'], 3, 7, 5, 9, 8, 11],
              'text-allow-overlap': false,
              'text-ignore-placement': false,
            }}
            paint={{
              'text-color': '#9ca3af',
              'text-halo-color': '#000000',
              'text-halo-width': 1.5,
            }}
          />
          {/* Possible Contradiction — amber pulsing, hypothesis not verdict */}
          <Layer
            id="corr-contra-fill"
            type="fill"
            filter={['==', ['get', 'corr_type'], 'contradiction']}
            minzoom={2}
            paint={{
              'fill-color': '#f59e0b',
              'fill-opacity': ['get', 'opacity'],
            }}
          />
          <Layer
            id="corr-contra-outline"
            type="line"
            filter={['==', ['get', 'corr_type'], 'contradiction']}
            minzoom={2}
            paint={{
              'line-color': '#f59e0b',
              'line-width': 2,
              'line-opacity': 0.7,
              'line-dasharray': [6, 3],
            }}
          />
          <Layer
            id="corr-contra-label"
            type="symbol"
            filter={['==', ['get', 'corr_type'], 'contradiction']}
            minzoom={2}
            layout={{
              'text-field': ['concat', '? CONTRADICTION\n', ['get', 'context'], ' · ', ['get', 'drivers']],
              'text-size': ['interpolate', ['linear'], ['zoom'], 2, 7, 5, 9, 8, 11],
              'text-allow-overlap': false,
              'text-ignore-placement': false,
            }}
            paint={{
              'text-color': '#fbbf24',
              'text-halo-color': '#000000',
              'text-halo-width': 1.5,
            }}
          />
          {/* Analysis Zone fill */}
          <Layer
            id="corr-analysis-fill"
            type="fill"
            filter={['==', ['get', 'corr_type'], 'analysis_zone']}
            paint={{
              'fill-color': ['match', ['get', 'zone_category'],
                'contradiction', '#f59e0b',
                'warning', '#ef4444',
                'observation', '#3b82f6',
                'hypothesis', '#a855f7',
                '#06b6d4',
              ],
              'fill-opacity': ['get', 'opacity'],
            }}
          />
          {/* Analysis Zone dashed outline */}
          <Layer
            id="corr-analysis-outline"
            type="line"
            filter={['==', ['get', 'corr_type'], 'analysis_zone']}
            paint={{
              'line-color': ['match', ['get', 'zone_category'],
                'contradiction', '#f59e0b',
                'warning', '#ef4444',
                'observation', '#3b82f6',
                'hypothesis', '#a855f7',
                '#06b6d4',
              ],
              'line-width': 1.5,
              'line-dasharray': [4, 3],
              'line-opacity': 0.7,
            }}
          />
          {/* Analysis Zone label */}
          <Layer
            id="corr-analysis-label"
            type="symbol"
            filter={['==', ['get', 'corr_type'], 'analysis_zone']}
            minzoom={2}
            layout={{
              'text-field': ['concat', ['get', 'zone_title'], '\n', ['get', 'drivers']],
              'text-size': ['interpolate', ['linear'], ['zoom'], 2, 7, 5, 9, 8, 11],
              'text-allow-overlap': false,
              'text-ignore-placement': false,
              'text-max-width': 18,
            }}
            paint={{
              'text-color': '#67e8f9',
              'text-halo-color': '#000000',
              'text-halo-width': 1.5,
            }}
          />
        </Source>

        {/* CCTV Cameras — clustered white dots */}
        <Source
          id="cctv"
          type="geojson"
          data={EMPTY_FC}
          cluster={true}
          clusterRadius={50}
          clusterMaxZoom={14}
        >
          {/* Cluster circles — white, sized by count */}
          <Layer
            id="cctv-clusters"
            type="circle"
            filter={['has', 'point_count']}
            paint={{
              'circle-color': '#ffffff',
              'circle-radius': ['step', ['get', 'point_count'], 14, 10, 18, 50, 24, 200, 30],
              'circle-opacity': 0.8,
              'circle-stroke-width': 2,
              'circle-stroke-color': '#a0a0a0',
            }}
          />
          {/* Cluster count labels */}
          <Layer
            id="cctv-cluster-count"
            type="symbol"
            filter={['has', 'point_count']}
            layout={{
              'text-field': '{point_count_abbreviated}',
              'text-size': 12,
              'text-allow-overlap': true,
            }}
            paint={{
              'text-color': '#000000',
              'text-halo-color': '#ffffff',
              'text-halo-width': 1,
            }}
          />
          {/* Individual camera dots */}
          <Layer
            id="cctv-layer"
            type="circle"
            filter={['!', ['has', 'point_count']]}
            paint={{
              'circle-color': '#ffffff',
              'circle-radius': ['interpolate', ['linear'], ['zoom'], 2, 2, 8, 4, 14, 6],
              'circle-opacity': 0.9,
              'circle-stroke-width': 1,
              'circle-stroke-color': '#a0a0a0',
            }}
          />
        </Source>

        {/* KiwiSDR Receivers — radio tower icons with pulse rings */}
        <Source
          id="kiwisdr"
          type="geojson"
          data={EMPTY_FC}
          cluster={true}
          clusterRadius={50}
          clusterMaxZoom={14}
        >
          {/* Pulse ring behind clusters */}
          <Layer
            id="kiwisdr-cluster-pulse"
            type="circle"
            filter={['has', 'point_count']}
            paint={{
              'circle-radius': ['step', ['get', 'point_count'], 20, 10, 26, 50, 32, 200, 40],
              'circle-color': 'rgba(245, 158, 11, 0.08)',
              'circle-stroke-width': 1.5,
              'circle-stroke-color': 'rgba(245, 158, 11, 0.35)',
              'circle-blur': 0.4,
            }}
          />
          {/* Clusters — tower icon with count */}
          <Layer
            id="kiwisdr-clusters"
            type="symbol"
            filter={['has', 'point_count']}
            layout={{
              'icon-image': 'svgRadioTower',
              'icon-size': 0.9,
              'icon-allow-overlap': true,
              'text-field': '{point_count_abbreviated}',
              'text-size': 10,
              'text-offset': [0, 1.4],
              'text-allow-overlap': true,
              'text-font': ['Noto Sans Bold'],
            }}
            paint={{
              'text-color': '#f59e0b',
              'text-halo-color': '#000000',
              'text-halo-width': 1.5,
            }}
          />
          {/* Pulse ring behind individual towers */}
          <Layer
            id="kiwisdr-pulse"
            type="circle"
            filter={['!', ['has', 'point_count']]}
            paint={{
              'circle-radius': ['interpolate', ['linear'], ['zoom'], 2, 6, 8, 10, 14, 14],
              'circle-color': 'rgba(245, 158, 11, 0.06)',
              'circle-stroke-width': 1,
              'circle-stroke-color': 'rgba(245, 158, 11, 0.3)',
              'circle-blur': 0.5,
            }}
          />
          {/* Individual tower icons */}
          <Layer
            id="kiwisdr-layer"
            type="symbol"
            filter={['!', ['has', 'point_count']]}
            layout={{
              'icon-image': 'svgRadioTower',
              'icon-size': ['interpolate', ['linear'], ['zoom'], 2, 0.5, 8, 0.8, 14, 1.0],
              'icon-allow-overlap': true,
            }}
          />
        </Source>

        {/* PSK Reporter — green HF digital mode spots with clustering */}
        <Source
          id="psk-reporter"
          type="geojson"
          data={EMPTY_FC}
          cluster={true}
          clusterRadius={50}
          clusterMaxZoom={14}
        >
          {/* Pulse ring behind clusters */}
          <Layer
            id="psk-reporter-cluster-pulse"
            type="circle"
            filter={['has', 'point_count']}
            minzoom={4}
            paint={{
              'circle-radius': ['step', ['get', 'point_count'], 20, 10, 26, 50, 32, 200, 40],
              'circle-color': 'rgba(34, 197, 94, 0.08)',
              'circle-stroke-width': 1.5,
              'circle-stroke-color': 'rgba(34, 197, 94, 0.35)',
              'circle-blur': 0.4,
            }}
          />
          {/* Clusters — count */}
          <Layer
            id="psk-reporter-clusters"
            type="circle"
            filter={['has', 'point_count']}
            minzoom={4}
            paint={{
              'circle-radius': ['step', ['get', 'point_count'], 12, 10, 16, 50, 20, 200, 26],
              'circle-color': 'rgba(34, 197, 94, 0.6)',
              'circle-stroke-width': 1.5,
              'circle-stroke-color': 'rgba(34, 197, 94, 0.9)',
            }}
          />
          <Layer
            id="psk-reporter-cluster-count"
            type="symbol"
            filter={['has', 'point_count']}
            minzoom={4}
            layout={{
              'text-field': '{point_count_abbreviated}',
              'text-size': 10,
              'text-allow-overlap': true,
              'text-font': ['Noto Sans Bold'],
            }}
            paint={{
              'text-color': '#ffffff',
              'text-halo-color': '#000000',
              'text-halo-width': 1,
            }}
          />
          {/* Individual spots — small green dots */}
          <Layer
            id="psk-reporter-pulse"
            type="circle"
            filter={['!', ['has', 'point_count']]}
            minzoom={4}
            paint={{
              'circle-radius': ['interpolate', ['linear'], ['zoom'], 2, 4, 8, 6, 14, 8],
              'circle-color': 'rgba(34, 197, 94, 0.06)',
              'circle-stroke-width': 1,
              'circle-stroke-color': 'rgba(34, 197, 94, 0.3)',
              'circle-blur': 0.5,
            }}
          />
          <Layer
            id="psk-reporter-layer"
            type="circle"
            filter={['!', ['has', 'point_count']]}
            minzoom={4}
            paint={{
              'circle-radius': ['interpolate', ['linear'], ['zoom'], 2, 2.5, 8, 4, 14, 6],
              'circle-color': '#22c55e',
              'circle-stroke-width': 0.5,
              'circle-stroke-color': 'rgba(34, 197, 94, 0.8)',
            }}
          />
        </Source>

        {/* SatNOGS Ground Stations — teal satellite dish icons with clustering */}
        <Source
          id="satnogs"
          type="geojson"
          data={EMPTY_FC}
          cluster={true}
          clusterRadius={50}
          clusterMaxZoom={14}
        >
          <Layer
            id="satnogs-cluster-pulse"
            type="circle"
            filter={['has', 'point_count']}
            paint={{
              'circle-radius': ['step', ['get', 'point_count'], 20, 10, 26, 50, 32, 200, 40],
              'circle-color': 'rgba(20, 184, 166, 0.08)',
              'circle-stroke-width': 1.5,
              'circle-stroke-color': 'rgba(20, 184, 166, 0.35)',
              'circle-blur': 0.4,
            }}
          />
          <Layer
            id="satnogs-clusters"
            type="symbol"
            filter={['has', 'point_count']}
            layout={{
              'icon-image': 'svgSatDish',
              'icon-size': 0.9,
              'icon-allow-overlap': true,
              'text-field': '{point_count_abbreviated}',
              'text-size': 10,
              'text-offset': [0, 1.4],
              'text-allow-overlap': true,
              'text-font': ['Noto Sans Bold'],
            }}
            paint={{
              'text-color': '#14b8a6',
              'text-halo-color': '#000000',
              'text-halo-width': 1.5,
            }}
          />
          <Layer
            id="satnogs-pulse"
            type="circle"
            filter={['!', ['has', 'point_count']]}
            paint={{
              'circle-radius': ['interpolate', ['linear'], ['zoom'], 2, 6, 8, 10, 14, 14],
              'circle-color': 'rgba(20, 184, 166, 0.06)',
              'circle-stroke-width': 1,
              'circle-stroke-color': 'rgba(20, 184, 166, 0.3)',
              'circle-blur': 0.5,
            }}
          />
          <Layer
            id="satnogs-layer"
            type="symbol"
            filter={['!', ['has', 'point_count']]}
            layout={{
              'icon-image': 'svgSatDish',
              'icon-size': ['interpolate', ['linear'], ['zoom'], 2, 0.5, 8, 0.8, 14, 1.0],
              'icon-allow-overlap': true,
            }}
          />
        </Source>

        {/* TinyGS LoRa Satellites — purple satellite icons (no clustering, small count) */}
        <Source id="tinygs" type="geojson" data={EMPTY_FC}>
          <Layer
            id="tinygs-layer"
            type="symbol"
            layout={{
              'icon-image': 'svgLoRaSat',
              'icon-size': 0.8,
              'icon-allow-overlap': true,
              'text-field': ['get', 'name'],
              'text-font': ['Noto Sans Regular'],
              'text-size': 10,
              'text-offset': [0, 1.4],
              'text-optional': true,
            }}
            paint={{
              'text-color': '#c084fc',
              'text-halo-color': '#000000',
              'text-halo-width': 1.5,
            }}
          />
        </Source>

        {/* Police Scanners (OpenMHZ) — red scanner icons with clusters */}
        <Source
          id="scanners"
          type="geojson"
          data={EMPTY_FC}
          cluster={true}
          clusterRadius={50}
          clusterMaxZoom={14}
        >
          {/* Pulse ring behind clusters */}
          <Layer
            id="scanner-cluster-pulse"
            type="circle"
            filter={['has', 'point_count']}
            paint={{
              'circle-radius': ['step', ['get', 'point_count'], 20, 10, 26, 50, 32, 200, 40],
              'circle-color': 'rgba(220, 38, 38, 0.08)',
              'circle-stroke-width': 1.5,
              'circle-stroke-color': 'rgba(220, 38, 38, 0.35)',
              'circle-blur': 0.4,
            }}
          />
          {/* Cluster icons + count */}
          <Layer
            id="scanner-clusters"
            type="symbol"
            filter={['has', 'point_count']}
            layout={{
              'icon-image': 'svgScannerTower',
              'icon-size': 0.9,
              'icon-allow-overlap': true,
              'text-field': '{point_count_abbreviated}',
              'text-size': 10,
              'text-offset': [0, 1.4],
              'text-allow-overlap': true,
              'text-font': ['Noto Sans Bold'],
            }}
            paint={{
              'text-color': '#dc2626',
              'text-halo-color': '#000000',
              'text-halo-width': 1.5,
            }}
          />
          {/* Pulse ring behind individual scanners */}
          <Layer
            id="scanner-pulse"
            type="circle"
            filter={['!', ['has', 'point_count']]}
            paint={{
              'circle-radius': ['interpolate', ['linear'], ['zoom'], 2, 6, 8, 10, 14, 14],
              'circle-color': 'rgba(220, 38, 38, 0.06)',
              'circle-stroke-width': 1,
              'circle-stroke-color': 'rgba(220, 38, 38, 0.3)',
              'circle-blur': 0.5,
            }}
          />
          {/* Individual scanner icons */}
          <Layer
            id="scanner-layer"
            type="symbol"
            filter={['!', ['has', 'point_count']]}
            layout={{
              'icon-image': 'svgScannerTower',
              'icon-size': ['interpolate', ['linear'], ['zoom'], 2, 0.5, 8, 0.8, 14, 1.0],
              'icon-allow-overlap': true,
            }}
          />
        </Source>

        {/* Internet Outages — region-level grey markers with % and labels */}
        <Source id="internet-outages" type="geojson" data={EMPTY_FC}>
          {/* Outer ring */}
          <Layer
            id="internet-outages-pulse"
            type="circle"
            paint={{
              'circle-radius': [
                'interpolate',
                ['linear'],
                ['get', 'severity'],
                0,
                14,
                50,
                18,
                80,
                22,
              ],
              'circle-color': 'rgba(180, 180, 180, 0.1)',
              'circle-stroke-width': 1.5,
              'circle-stroke-color': 'rgba(180, 180, 180, 0.35)',
            }}
          />
          {/* Inner solid circle — all grey, size conveys severity */}
          <Layer
            id="internet-outages-layer"
            type="circle"
            paint={{
              'circle-radius': [
                'interpolate',
                ['linear'],
                ['get', 'severity'],
                0,
                6,
                50,
                9,
                80,
                12,
              ],
              'circle-color': '#888888',
              'circle-stroke-width': 2,
              'circle-stroke-color': 'rgba(0, 0, 0, 0.6)',
              'circle-opacity': 0.9,
            }}
          />
          {/* Severity % inside circle */}
          <Layer
            id="internet-outages-pct"
            type="symbol"
            layout={{
              'text-field': [
                'case',
                ['>', ['get', 'severity'], 0],
                ['concat', ['to-string', ['get', 'severity']], '%'],
                '!',
              ],
              'text-size': 9,
              'text-font': ['Noto Sans Bold'],
              'text-allow-overlap': true,
              'text-ignore-placement': true,
            }}
            paint={{
              'text-color': '#ffffff',
              'text-halo-color': 'rgba(0,0,0,0.8)',
              'text-halo-width': 1,
            }}
          />
          {/* Region name label below — grey */}
          <Layer
            id="internet-outages-label"
            type="symbol"
            layout={{
              'text-field': ['get', 'region'],
              'text-size': 10,
              'text-font': ['Noto Sans Bold'],
              'text-offset': [0, 1.8],
              'text-anchor': 'top',
              'text-allow-overlap': false,
            }}
            paint={{
              'text-color': '#aaaaaa',
              'text-halo-color': 'rgba(0,0,0,0.9)',
              'text-halo-width': 1.5,
            }}
          />
        </Source>

        {/* Data Center positions */}
        <Source
          id="datacenters"
          type="geojson"
          data={EMPTY_FC}
          cluster={true}
          clusterRadius={30}
          clusterMaxZoom={8}
        >
          {/* Cluster circles */}
          <Layer
            id="datacenters-clusters"
            type="circle"
            filter={['has', 'point_count']}
            paint={{
              'circle-color': '#7c3aed',
              'circle-radius': ['step', ['get', 'point_count'], 12, 10, 16, 50, 20],
              'circle-opacity': 0.7,
              'circle-stroke-width': 1,
              'circle-stroke-color': '#a78bfa',
            }}
          />
          <Layer
            id="datacenters-cluster-count"
            type="symbol"
            filter={['has', 'point_count']}
            layout={{
              'text-field': '{point_count_abbreviated}',
              'text-font': ['Noto Sans Bold'],
              'text-size': 10,
              'text-allow-overlap': true,
            }}
            paint={{
              'text-color': '#e9d5ff',
            }}
          />
          {/* Individual DC icons */}
          <Layer
            id="datacenters-layer"
            type="symbol"
            filter={['!', ['has', 'point_count']]}
            layout={{
              'icon-image': 'datacenter',
              'icon-size': ['interpolate', ['linear'], ['zoom'], 2, 0.5, 6, 0.7, 10, 1.0],
              'icon-allow-overlap': true,
              'text-field': ['step', ['zoom'], '', 6, ['get', 'name']],
              'text-font': ['Noto Sans Regular'],
              'text-size': 9,
              'text-offset': [0, 1.2],
              'text-anchor': 'top',
              'text-allow-overlap': false,
            }}
            paint={{
              'text-color': '#c4b5fd',
              'text-halo-color': 'rgba(0,0,0,0.9)',
              'text-halo-width': 1,
            }}
          />
        </Source>

        {/* Power Plant positions */}
        {powerPlantsGeoJSON && (
            <Source id="power-plants" type="geojson" data={EMPTY_FC} cluster={true} clusterRadius={30} clusterMaxZoom={8}>
                {/* Cluster circles */}
                <Layer
                    id="power-plants-clusters"
                    type="circle"
                    minzoom={4}
                    filter={['has', 'point_count']}
                    paint={{
                        'circle-color': '#92400e',
                        'circle-radius': ['step', ['get', 'point_count'], 12, 10, 16, 50, 20],
                        'circle-opacity': 0.7,
                        'circle-stroke-width': 1,
                        'circle-stroke-color': '#f59e0b',
                    }}
                />
                <Layer
                    id="power-plants-cluster-count"
                    type="symbol"
                    minzoom={4}
                    filter={['has', 'point_count']}
                    layout={{
                        'text-field': '{point_count_abbreviated}',
                        'text-font': ['Noto Sans Bold'],
                        'text-size': 10,
                        'text-allow-overlap': true,
                    }}
                    paint={{
                        'text-color': '#fde68a',
                    }}
                />
                {/* Individual power plant icons */}
                <Layer
                    id="power-plants-layer"
                    type="symbol"
                    minzoom={4}
                    filter={['!', ['has', 'point_count']]}
                    layout={{
                        'icon-image': 'power-plant',
                        'icon-size': ['interpolate', ['linear'], ['zoom'], 2, 0.5, 6, 0.7, 10, 1.0],
                        'icon-allow-overlap': true,
                        'text-field': ['step', ['zoom'], '', 6, ['get', 'name']],
                        'text-font': ['Noto Sans Regular'],
                        'text-size': 9,
                        'text-offset': [0, 1.2],
                        'text-anchor': 'top',
                        'text-allow-overlap': false,
                    }}
                    paint={{
                        'text-color': '#fbbf24',
                        'text-halo-color': 'rgba(0,0,0,0.9)',
                        'text-halo-width': 1,
                    }}
                />
            </Source>
        )}

        {/* VIIRS Change Detection Nodes */}
        {viirsChangeNodesGeoJSON && (
            <Source id="viirs-change-nodes" type="geojson" data={EMPTY_FC}>
                <Layer
                    id="viirs-change-nodes-layer"
                    type="circle"
                    paint={{
                        'circle-radius': ['interpolate', ['linear'], ['zoom'], 2, 4, 6, 8, 10, 12],
                        'circle-color': ['get', 'color'],
                        'circle-opacity': 0.85,
                        'circle-stroke-width': 1,
                        'circle-stroke-color': 'rgba(255,255,255,0.4)',
                    }}
                />
            </Source>
        )}

        {/* SAR AOIs — operator watchbox circles, drawn beneath anomaly pins */}
        {sarAoisGeoJSON && (
          <Source id="sar-aois" type="geojson" data={EMPTY_FC}>
            <Layer
              id="sar-aois-fill"
              type="fill"
              paint={{
                'fill-color': [
                  'match',
                  ['get', 'category'],
                  'conflict', '#ef4444',
                  'geohazard', '#f97316',
                  'infrastructure', '#06b6d4',
                  'geopolitical', '#a855f7',
                  '#eab308',
                ],
                'fill-opacity': 0.08,
              }}
            />
            <Layer
              id="sar-aois-outline"
              type="line"
              paint={{
                'line-color': [
                  'match',
                  ['get', 'category'],
                  'conflict', '#ef4444',
                  'geohazard', '#f97316',
                  'infrastructure', '#06b6d4',
                  'geopolitical', '#a855f7',
                  '#eab308',
                ],
                'line-width': 1.2,
                'line-opacity': 0.55,
                'line-dasharray': [2, 2],
              }}
            />
            <Layer
              id="sar-aois-label"
              type="symbol"
              minzoom={4}
              layout={{
                'text-field': ['get', 'name'],
                'text-font': ['Noto Sans Regular'],
                'text-size': 10,
                'text-offset': [0, 0.5],
                'text-anchor': 'top',
                'text-allow-overlap': false,
              }}
              paint={{
                'text-color': '#fde68a',
                'text-halo-color': 'rgba(0,0,0,0.9)',
                'text-halo-width': 1,
              }}
            />
          </Source>
        )}

        {/* SAR Anomalies — Mode B pre-processed findings (OPERA/EGMS/GFM/EMS/UNOSAT) */}
        {sarAnomaliesGeoJSON && (
          <Source id="sar-anomalies" type="geojson" data={EMPTY_FC}>
            <Layer
              id="sar-anomalies-halo"
              type="circle"
              paint={{
                'circle-radius': [
                  'interpolate', ['linear'], ['zoom'],
                  2, 6, 6, 10, 10, 16,
                ],
                'circle-color': ['get', 'color'],
                'circle-opacity': 0.2,
                'circle-blur': 0.6,
              }}
            />
            <Layer
              id="sar-anomalies-layer"
              type="circle"
              paint={{
                'circle-radius': [
                  'interpolate', ['linear'], ['zoom'],
                  2, 3, 6, 5, 10, 8,
                ],
                'circle-color': ['get', 'color'],
                'circle-opacity': 0.9,
                'circle-stroke-width': 1.5,
                'circle-stroke-color': '#000',
              }}
            />
            <Layer
              id="sar-anomalies-label"
              type="symbol"
              minzoom={7}
              layout={{
                'text-field': ['get', 'title'],
                'text-font': ['Noto Sans Regular'],
                'text-size': 10,
                'text-offset': [0, 1.2],
                'text-anchor': 'top',
                'text-allow-overlap': false,
                'text-max-width': 12,
              }}
              paint={{
                'text-color': '#fef3c7',
                'text-halo-color': 'rgba(0,0,0,0.9)',
                'text-halo-width': 1,
              }}
            />
          </Source>
        )}

        {/* Shodan — operator-triggered local overlay, clustered and clearly distinct */}
        {(() => {
          const sc = shodanStyle ?? { shape: 'circle' as const, color: '#16a34a', size: 'md' as const };
          const sizeMap = { sm: [3, 4, 5] as const, md: [4, 6, 8] as const, lg: [6, 9, 12] as const };
          const textSizeMap = { sm: 10, md: 14, lg: 20 };
          const shapeGlyphs: Record<string, string> = { triangle: '▲', diamond: '◆', square: '■' };
          const radii = sizeMap[sc.size] ?? sizeMap.md;
          const isCircle = sc.shape === 'circle';
          const labelOffset = isCircle ? 1.1 : (sc.size === 'lg' ? 1.6 : sc.size === 'sm' ? 0.9 : 1.2);
          return (
            <Source
              id="shodan-overlay"
              type="geojson"
              data={(shodanGeoJSON ?? EMPTY_FC)}
              cluster={true}
              clusterRadius={42}
              clusterMaxZoom={9}
            >
              {/* Cluster circles — always circles, inherit color */}
              <Layer
                id="shodan-clusters"
                type="circle"
                filter={['has', 'point_count']}
                paint={{
                  'circle-color': sc.color,
                  'circle-radius': ['step', ['get', 'point_count'], 14, 10, 18, 50, 22, 200, 26],
                  'circle-opacity': 0.8,
                  'circle-stroke-width': 1.5,
                  'circle-stroke-color': `${sc.color}66`,
                }}
              />
              <Layer
                id="shodan-cluster-count"
                type="symbol"
                filter={['has', 'point_count']}
                layout={{
                  'text-field': '{point_count_abbreviated}',
                  'text-font': ['Noto Sans Bold'],
                  'text-size': 10,
                  'text-allow-overlap': true,
                }}
                paint={{
                  'text-color': '#ffffff',
                }}
              />
              {/* Individual markers — circle layer (hidden when non-circle shape) */}
              {isCircle && (
                <Layer
                  id="shodan-layer"
                  type="circle"
                  filter={['!', ['has', 'point_count']]}
                  paint={{
                    'circle-radius': ['interpolate', ['linear'], ['zoom'], 2, radii[0], 6, radii[1], 10, radii[2]],
                    'circle-color': sc.color,
                    'circle-opacity': 0.9,
                    'circle-stroke-width': 1.5,
                    'circle-stroke-color': '#ffffff44',
                  }}
                />
              )}
              {/* Individual markers — symbol layer for triangle/diamond/square */}
              {!isCircle && (
                <Layer
                  id="shodan-layer"
                  type="symbol"
                  filter={['!', ['has', 'point_count']]}
                  layout={{
                    'text-field': shapeGlyphs[sc.shape] ?? '●',
                    'text-font': ['Noto Sans Bold'],
                    'text-size': textSizeMap[sc.size] ?? 14,
                    'text-allow-overlap': true,
                    'text-ignore-placement': true,
                  }}
                  paint={{
                    'text-color': sc.color,
                    'text-halo-color': 'rgba(0,0,0,0.7)',
                    'text-halo-width': 1,
                  }}
                />
              )}
              {/* Labels */}
              <Layer
                id="shodan-labels"
                type="symbol"
                filter={['!', ['has', 'point_count']]}
                layout={{
                  'text-field': ['step', ['zoom'], '', 7, ['get', 'name']],
                  'text-font': ['Noto Sans Bold'],
                  'text-size': 10,
                  'text-offset': [0, labelOffset],
                  'text-anchor': 'top',
                  'text-allow-overlap': false,
                }}
                paint={{
                  'text-color': sc.color,
                  'text-halo-color': 'rgba(0,0,0,0.85)',
                  'text-halo-width': 1,
                }}
              />
            </Source>
          );
        })()}

        {/* AI Intel Layer — pins from OpenClaw / AI co-pilot */}
        {aiIntelGeoJSON && (
          <Source
            id="ai-intel-source"
            type="geojson"
            data={aiIntelGeoJSON}
            cluster={true}
            clusterRadius={40}
            clusterMaxZoom={10}
          >
            <Layer
              id="ai-intel-clusters"
              type="circle"
              filter={['has', 'point_count']}
              paint={{
                'circle-color': '#8b5cf6',
                'circle-radius': ['step', ['get', 'point_count'], 14, 5, 18, 20, 22, 100, 28],
                'circle-opacity': 0.85,
                'circle-stroke-width': 2,
                'circle-stroke-color': '#a78bfa66',
              }}
            />
            <Layer
              id="ai-intel-cluster-count"
              type="symbol"
              filter={['has', 'point_count']}
              layout={{
                'text-field': '{point_count_abbreviated}',
                'text-font': ['Noto Sans Bold'],
                'text-size': 12,
              }}
              paint={{ 'text-color': '#ffffff' }}
            />
            <Layer
              id="ai-intel-pin-layer"
              type="symbol"
              filter={['!', ['has', 'point_count']]}
              layout={{
                'icon-image': ['concat', 'ai-pin-', ['get', 'category']],
                'icon-size': ['interpolate', ['linear'], ['zoom'], 2, 0.45, 6, 0.7, 10, 0.9, 14, 1.0],
                'icon-anchor': 'bottom',
                'icon-allow-overlap': true,
                'icon-ignore-placement': true,
                'text-field': ['step', ['zoom'], '', 6, ['get', 'label']],
                'text-font': ['Noto Sans Bold'],
                'text-size': 11,
                'text-offset': [0, 0.5],
                'text-anchor': 'top',
                'text-optional': true,
              }}
              paint={{
                'text-color': ['get', 'color'],
                'text-halo-color': 'rgba(0,0,0,0.85)',
                'text-halo-width': 1,
              }}
            />
          </Source>
        )}

        {/* Military Bases — per-country colors */}
        <Source id="military-bases" type="geojson" data={EMPTY_FC}>
          <Layer
            id="military-bases-layer"
            type="symbol"
            layout={{
              'icon-image': ['get', 'iconId'],
              'icon-size': ['interpolate', ['linear'], ['zoom'], 2, 0.5, 6, 0.8, 10, 1.0],
              'icon-allow-overlap': true,
            }}
          />
          <Layer
            id="military-bases-label"
            type="symbol"
            layout={{
              'text-field': ['step', ['zoom'], '', 5, ['get', 'name']],
              'text-font': ['Noto Sans Bold'],
              'text-size': 10,
              'text-offset': [0, 1.4],
              'text-anchor': 'top',
              'text-allow-overlap': false,
            }}
            paint={{
              'text-color': ['get', 'color'],
              'text-halo-color': 'rgba(0,0,0,0.9)',
              'text-halo-width': 1,
            }}
          />
        </Source>

        {/* Ukraine Air Raid Alerts — red/orange oblast polygons */}
        <Source id="ukraine-alerts-source" type="geojson" data={(ukraineAlertsGeoJSON ?? EMPTY_FC)}>
          <Layer
            id="ukraine-alerts-fill"
            type="fill"
            paint={{
              'fill-color': ['get', 'color'],
              'fill-opacity': 0.18,
            }}
          />
          <Layer
            id="ukraine-alerts-outline"
            type="line"
            paint={{
              'line-color': ['get', 'color'],
              'line-width': 2.5,
              'line-opacity': 0.8,
              'line-dasharray': [6, 3],
            }}
          />
        </Source>
        <Source id="ukraine-alert-labels-source" type="geojson" data={(ukraineAlertLabelsGeoJSON ?? EMPTY_FC)}>
          <Layer
            id="ukraine-alert-labels"
            type="symbol"
            layout={{
              'text-field': ['concat', ['get', 'alert_label'], '\n', ['get', 'name_en']],
              'text-font': ['Noto Sans Bold'],
              'text-size': 11,
              'text-allow-overlap': false,
              'text-max-width': 12,
            }}
            paint={{
              'text-color': ['get', 'color'],
              'text-halo-color': '#000000',
              'text-halo-width': 1.5,
            }}
          />
        </Source>

        {/* Weather Alerts — severity-colored polygons with icon + label overlay */}
        <Source id="weather-alerts-source" type="geojson" data={(weatherAlertsGeoJSON ?? EMPTY_FC)}>
          <Layer
            id="weather-alerts-fill"
            type="fill"
            paint={{
              'fill-color': ['get', 'color'],
              'fill-opacity': 0.12,
            }}
          />
          <Layer
            id="weather-alerts-outline"
            type="line"
            paint={{
              'line-color': ['get', 'color'],
              'line-width': 2,
              'line-opacity': 0.7,
              'line-dasharray': [4, 3],
            }}
          />
        </Source>
        <Source id="weather-alert-labels-source" type="geojson" data={(weatherAlertLabelsGeoJSON ?? EMPTY_FC)}>
          <Layer
            id="weather-alert-icons"
            type="symbol"
            layout={{
              'icon-image': ['get', 'iconId'],
              'icon-size': 1.1,
              'icon-allow-overlap': true,
              'icon-anchor': 'bottom',
              'text-field': ['get', 'event'],
              'text-font': ['Noto Sans Bold'],
              'text-size': 11,
              'text-offset': [0, 0.4],
              'text-anchor': 'top',
              'text-allow-overlap': false,
              'text-max-width': 14,
            }}
            paint={{
              'text-color': ['get', 'color'],
              'text-halo-color': '#000000',
              'text-halo-width': 1.5,
            }}
          />
        </Source>

        {/* Air Quality — AQI-colored circles */}
        <Source id="air-quality-source" type="geojson" data={EMPTY_FC} cluster={true} clusterMaxZoom={8} clusterRadius={40}>
          <Layer
            id="air-quality-clusters"
            type="circle"
            filter={['has', 'point_count']}
            paint={{
              'circle-radius': ['step', ['get', 'point_count'], 12, 10, 16, 50, 20],
              'circle-color': '#94a3b8',
              'circle-opacity': 0.6,
            }}
          />
          <Layer
            id="air-quality-layer"
            type="circle"
            filter={['!', ['has', 'point_count']]}
            paint={{
              'circle-radius': ['interpolate', ['linear'], ['zoom'], 2, 3, 6, 5, 10, 8],
              'circle-color': ['get', 'color'],
              'circle-opacity': 0.75,
              'circle-stroke-width': 1,
              'circle-stroke-color': '#000',
            }}
          />
        </Source>

        {/* Volcanoes — activity-colored triangle icons */}
        <Source id="volcanoes-source" type="geojson" data={EMPTY_FC}>
          <Layer
            id="volcanoes-layer"
            type="symbol"
            layout={{
              'icon-image': ['get', 'iconId'],
              'icon-size': ['interpolate', ['linear'], ['zoom'], 2, 0.4, 6, 0.7, 10, 1.0],
              'icon-allow-overlap': true,
            }}
          />
          <Layer
            id="volcanoes-label"
            type="symbol"
            layout={{
              'text-field': ['step', ['zoom'], '', 6, ['get', 'name']],
              'text-font': ['Noto Sans Bold'],
              'text-size': 10,
              'text-offset': [0, 1.2],
              'text-anchor': 'top',
              'text-allow-overlap': false,
            }}
            paint={{
              'text-color': '#f97316',
              'text-halo-color': 'rgba(0,0,0,0.9)',
              'text-halo-width': 1,
            }}
          />
        </Source>

        {/* Fishing Activity — AIS-style ship clusters and icons */}
        <Source
          id="fishing-source"
          type="geojson"
          data={EMPTY_FC}
          cluster={true}
          clusterMaxZoom={6}
          clusterRadius={50}
          clusterProperties={{
            cargo_count: ['+', ['case', ['==', ['get', 'shipCategory'], 'cargo'], 1, 0]],
            passenger_count: ['+', ['case', ['==', ['get', 'shipCategory'], 'passenger'], 1, 0]],
            military_count: ['+', ['case', ['==', ['get', 'shipCategory'], 'military'], 1, 0]],
            yacht_count: ['+', ['case', ['==', ['get', 'shipCategory'], 'yacht'], 1, 0]],
            civilian_count: ['+', ['case', ['==', ['get', 'shipCategory'], 'civilian'], 1, 0]],
          }}
        >
          <Layer
            id="fishing-clusters"
            type="symbol"
            filter={['has', 'point_count']}
            layout={{
              'icon-image': 'svgShipBlue',
              'icon-size': ['step', ['get', 'point_count'], 1.35, 10, 1.55, 50, 1.8, 250, 2.05, 1000, 2.3],
              'icon-allow-overlap': true,
              'icon-ignore-placement': true,
              'icon-rotate': 90,
              'icon-rotation-alignment': 'viewport',
            }}
            paint={{
              'icon-opacity': 0.98,
            }}
          />
          <Layer
            id="fishing-cluster-count"
            type="symbol"
            filter={['has', 'point_count']}
            layout={{
              'text-field': '{point_count_abbreviated}',
              'text-font': ['Noto Sans Bold'],
              'text-size': ['step', ['get', 'point_count'], 10, 10, 11, 50, 12, 250, 13, 1000, 14],
              'text-offset': [0, 0.82],
              'text-anchor': 'center',
              'text-allow-overlap': true,
              'text-ignore-placement': true,
            }}
            paint={{
              'text-color': '#ffffff',
              'text-halo-color': 'rgba(0, 0, 0, 0.95)',
              'text-halo-width': 1.8,
            }}
          />
          <Layer
            id="fishing-layer"
            type="symbol"
            filter={['!', ['has', 'point_count']]}
            layout={{
              'icon-image': ['get', 'iconId'],
              'icon-size': ['interpolate', ['linear'], ['zoom'], 2, 0.4, 6, 0.65, 10, 0.9],
              'icon-allow-overlap': true,
              'icon-rotate': ['get', 'rotation'],
              'icon-rotation-alignment': 'map',
            }}
            paint={{
              'icon-opacity': 0.85,
            }}
          />
        </Source>

        {/* UAP Sightings — purple UFO icons with detail labels */}
        <Source id="uap-sightings-source" type="geojson" data={EMPTY_FC} cluster={true} clusterMaxZoom={10} clusterRadius={40}>
          {/* Cluster glow — faint backdrop behind UFO icon */}
          <Layer
            id="uap-sightings-cluster-bg"
            type="circle"
            filter={['has', 'point_count']}
            paint={{
              'circle-radius': ['step', ['get', 'point_count'], 12, 10, 14, 50, 18],
              'circle-color': 'rgba(139, 92, 246, 0.10)',
              'circle-stroke-width': 0,
              'circle-stroke-color': 'transparent',
            }}
          />
          {/* Cluster UFO icon + count */}
          <Layer
            id="uap-sightings-clusters"
            type="symbol"
            filter={['has', 'point_count']}
            layout={{
              'icon-image': 'ufo-cluster',
              'icon-size': ['interpolate', ['linear'], ['zoom'], 0, 1.45, 2, 1.5, 4, 1.52, 6, 1.48, 8, 1.44, 10, 1.4],
              'icon-allow-overlap': true,
              'icon-ignore-placement': true,
              'text-field': '{point_count_abbreviated}',
              'text-font': ['Noto Sans Bold'],
              'text-size': ['interpolate', ['linear'], ['zoom'], 0, 10, 4, 11, 8, 12],
              'text-offset': [0, 0.05],
              'text-allow-overlap': true,
              'text-ignore-placement': true,
            }}
            paint={{
              'icon-opacity': 1,
              'text-color': '#ffffff',
              'text-halo-color': 'rgba(88, 28, 135, 1)',
              'text-halo-width': 2.4,
            }}
          />
          {/* Individual glow — faint backdrop behind UFO icon */}
          <Layer
            id="uap-sightings-dot"
            type="circle"
            filter={['!', ['has', 'point_count']]}
            paint={{
              'circle-radius': ['interpolate', ['linear'], ['zoom'], 2, 3, 6, 4, 10, 5],
              'circle-color': 'rgba(139, 92, 246, 0.20)',
              'circle-stroke-width': 0.75,
              'circle-stroke-color': 'rgba(216, 180, 254, 0.25)',
            }}
          />
          {/* Individual UFO icon overlay */}
          <Layer
            id="uap-sightings-layer"
            type="symbol"
            filter={['!', ['has', 'point_count']]}
            layout={{
              'icon-image': 'ufo-icon',
              'icon-size': ['interpolate', ['linear'], ['zoom'], 1, 0.7, 3, 0.8, 6, 0.95, 10, 1.1, 14, 1.2],
              'icon-allow-overlap': true,
              'icon-ignore-placement': true,
              'text-field': ['step', ['zoom'], '', 5, ['get', 'label']],
              'text-font': ['Noto Sans Bold'],
              'text-size': ['interpolate', ['linear'], ['zoom'], 5, 9, 10, 11],
              'text-offset': [0, 2.0],
              'text-anchor': 'top',
              'text-allow-overlap': false,
              'text-optional': true,
              'text-max-width': 16,
            }}
            paint={{
              'icon-opacity': 1,
              'text-color': '#d8b4fe',
              'text-halo-color': 'rgba(0,0,0,0.98)',
              'text-halo-width': 1.25,
            }}
          />
        </Source>

        {/* WastewaterSCAN — pathogen surveillance network (water drops) */}
        <Source id="wastewater-source" type="geojson" data={EMPTY_FC} cluster={true} clusterMaxZoom={10} clusterRadius={35}>
          {/* Cluster glow — faint backdrop behind water drop icon */}
          <Layer
            id="wastewater-cluster-bg"
            type="circle"
            filter={['has', 'point_count']}
            paint={{
              'circle-radius': ['step', ['get', 'point_count'], 12, 10, 14, 50, 18],
              'circle-color': 'rgba(0, 229, 255, 0.10)',
              'circle-stroke-width': 0,
              'circle-stroke-color': 'transparent',
            }}
          />
          {/* Cluster water drop icon + count */}
          <Layer
            id="wastewater-clusters"
            type="symbol"
            filter={['has', 'point_count']}
            layout={{
              'icon-image': 'ww-cluster',
              'icon-size': ['interpolate', ['linear'], ['zoom'], 0, 1.5, 2, 1.55, 4, 1.57, 6, 1.52, 8, 1.46, 10, 1.4],
              'icon-allow-overlap': true,
              'icon-ignore-placement': true,
              'text-field': '{point_count_abbreviated}',
              'text-font': ['Noto Sans Bold'],
              'text-size': ['interpolate', ['linear'], ['zoom'], 0, 10, 4, 11, 8, 12],
              'text-offset': [0, 0.1],
              'text-allow-overlap': true,
              'text-ignore-placement': true,
            }}
            paint={{
              'icon-opacity': 1,
              'text-color': '#ffffff',
              'text-halo-color': 'rgba(0, 80, 100, 1)',
              'text-halo-width': 2.4,
            }}
          />
          {/* Individual glow — faint backdrop behind water drop icon */}
          <Layer
            id="wastewater-dot"
            type="circle"
            filter={['!', ['has', 'point_count']]}
            paint={{
              'circle-radius': ['interpolate', ['linear'], ['zoom'], 2, 3, 8, 4, 12, 5, 16, 6],
              'circle-color': ['case', ['>', ['get', 'alert_count'], 0], 'rgba(255, 34, 34, 0.20)', 'rgba(0, 229, 255, 0.20)'],
              'circle-stroke-width': 0.75,
              'circle-stroke-color': ['case', ['>', ['get', 'alert_count'], 0], 'rgba(255, 82, 82, 0.25)', 'rgba(128, 222, 234, 0.25)'],
            }}
          />
          {/* Individual water drop icon overlay */}
          <Layer
            id="wastewater-layer"
            type="symbol"
            filter={['!', ['has', 'point_count']]}
            layout={{
              'icon-image': ['get', 'icon'],
              'icon-size': ['interpolate', ['linear'], ['zoom'], 1, 0.7, 3, 0.8, 6, 0.95, 10, 1.1, 14, 1.2],
              'icon-allow-overlap': true,
              'icon-ignore-placement': true,
              'text-field': ['step', ['zoom'], '', 7, ['get', 'label']],
              'text-font': ['Noto Sans Bold'],
              'text-size': ['interpolate', ['linear'], ['zoom'], 7, 9, 10, 11],
              'text-offset': [0, 2.0],
              'text-anchor': 'top',
              'text-allow-overlap': false,
              'text-optional': true,
              'text-max-width': 16,
            }}
            paint={{
              'icon-opacity': 1,
              'text-color': ['case', ['>', ['get', 'alert_count'], 0], '#ff5252', '#80deea'],
              'text-halo-color': 'rgba(0,0,0,0.98)',
              'text-halo-width': 1.25,
            }}
          />
        </Source>

        {/* CrowdThreat — crowdsourced threat intelligence with category icons */}
        <Source id="crowdthreat-source" type="geojson" data={EMPTY_FC} cluster={true} clusterMaxZoom={8} clusterRadius={40}>
          <Layer
            id="crowdthreat-clusters"
            type="circle"
            filter={['has', 'point_count']}
            paint={{
              'circle-radius': ['step', ['get', 'point_count'], 14, 10, 18, 50, 24],
              'circle-color': 'rgba(239, 68, 68, 0.7)',
              'circle-stroke-width': 2,
              'circle-stroke-color': '#ef4444',
            }}
          />
          <Layer
            id="crowdthreat-cluster-count"
            type="symbol"
            filter={['has', 'point_count']}
            layout={{
              'text-field': '{point_count_abbreviated}',
              'text-font': ['Noto Sans Bold'],
              'text-size': 12,
            }}
            paint={{
              'text-color': '#ffffff',
            }}
          />
          <Layer
            id="crowdthreat-layer"
            type="symbol"
            filter={['!', ['has', 'point_count']]}
            layout={{
              'icon-image': ['get', 'iconId'],
              'icon-size': ['interpolate', ['linear'], ['zoom'], 2, 0.6, 6, 0.8, 10, 1.0],
              'icon-allow-overlap': true,
            }}
          />
          <Layer
            id="crowdthreat-label"
            type="symbol"
            filter={['!', ['has', 'point_count']]}
            layout={{
              'text-field': ['step', ['zoom'], '', 8, ['get', 'threat_type']],
              'text-font': ['Noto Sans Bold'],
              'text-size': 9,
              'text-offset': [0, 1.6],
              'text-anchor': 'top',
              'text-allow-overlap': false,
            }}
            paint={{
              'text-color': '#fca5a5',
              'text-halo-color': 'rgba(0,0,0,0.9)',
              'text-halo-width': 1,
            }}
          />
        </Source>

        {/* Ships — rendered below flights (water surface level) */}
        <Source
          id="ships"
          type="geojson"
          data={EMPTY_FC}
          cluster={true}
          clusterMaxZoom={6}
          clusterRadius={40}
        >
          {/* Clustered circles */}
          <Layer
            id="ships-clusters-layer"
            type="circle"
            filter={['has', 'point_count']}
            paint={{
              'circle-opacity': opacityFilter,
              'circle-stroke-opacity': opacityFilter,
              'circle-color': 'rgba(30, 64, 175, 0.85)',
              'circle-radius': [
                'step',
                ['get', 'point_count'],
                12,
                10,
                15,
                100,
                20,
                1000,
                25,
                5000,
                30,
              ],
              'circle-stroke-width': 2,
              'circle-stroke-color': 'rgba(59, 130, 246, 1.0)',
            }}
          />

          {/* Cluster count - rendered via HTML markers below */}
          <Layer
            id="ships-cluster-count-layer"
            type="circle"
            filter={['has', 'point_count']}
            paint={{ 'circle-radius': 0, 'circle-opacity': 0 }}
          />

          {/* Unclustered individual ships (Cargo, Tankers, etc.) */}
          <Layer
            id="ships-layer"
            type="symbol"
            minzoom={2}
            filter={['!', ['has', 'point_count']]}
            layout={{
              'icon-image': ['get', 'iconId'],
              'icon-size': ['interpolate', ['linear'], ['zoom'], 2, 0.35, 5, 0.55, 8, 0.8, 12, 1.0],
              'icon-allow-overlap': true,
              'icon-rotate': ['get', 'rotation'],
              'icon-rotation-alignment': 'map',
            }}
            paint={{
              'icon-opacity': opacityFilter,
            }}
          />
        </Source>

        <Source id="carriers" type="geojson" data={(carriersGeoJSON ?? EMPTY_FC)}>
          <Layer
            id="carriers-layer"
            type="symbol"
            layout={{
              'icon-image': 'svgCarrier',
              'icon-size': 0.8,
              'icon-allow-overlap': true,
              'icon-rotate': ['get', 'rotation'],
              'icon-rotation-alignment': 'map',
            }}
            paint={{ 'icon-opacity': opacityFilter }}
          />
        </Source>

        {/* Meshtastic — green triangle clusters that break apart on zoom */}
        <Source
          id="meshtastic-source"
          type="geojson"
          data={EMPTY_FC}
          cluster={true}
          clusterRadius={42}
          clusterMaxZoom={8}
        >
          <Layer
            id="meshtastic-clusters"
            type="symbol"
            filter={['has', 'point_count']}
            layout={{
              'icon-image': 'icon-mesh-triangle',
              'icon-size': [
                'step',
                ['get', 'point_count'],
                1.1,
                10,
                1.35,
                50,
                1.65,
                100,
                1.95,
                500,
                2.3,
              ],
              'icon-allow-overlap': true,
            }}
            paint={{
              'icon-opacity': 0.95,
            }}
          />
          <Layer
            id="meshtastic-cluster-count"
            type="symbol"
            filter={['has', 'point_count']}
            layout={{
              'text-field': ['get', 'point_count_abbreviated'],
              'text-size': 11,
              'text-font': ['Noto Sans Bold'],
              'text-offset': [0, 0.05],
              'text-anchor': 'center',
              'text-allow-overlap': true,
            }}
            paint={{
              'text-color': '#052e16',
              'text-halo-color': '#86efac',
              'text-halo-width': 0.8,
            }}
          />
          <Layer
            id="meshtastic-circles"
            type="symbol"
            filter={['!', ['has', 'point_count']]}
            layout={{
              'icon-image': 'icon-mesh-triangle',
              'icon-size': 0.7,
              'icon-allow-overlap': true,
            }}
            paint={{
              'icon-opacity': 0.85,
            }}
          />
          <Layer
            id="meshtastic-labels"
            type="symbol"
            minzoom={8}
            layout={{
              'text-field': ['get', 'callsign'],
              'text-size': 9,
              'text-offset': [0, 1.2],
              'text-anchor': 'top',
              'text-font': ['Noto Sans Regular'],
              'text-allow-overlap': false,
            }}
            paint={{
              'text-color': '#86efac',
              'text-halo-color': 'rgba(0,0,0,0.8)',
              'text-halo-width': 1,
            }}
          />
        </Source>

        {/* APRS / JS8Call — pink triangles with clustering */}
        <Source
          id="aprs-source"
          type="geojson"
          data={EMPTY_FC}
          cluster={true}
          clusterRadius={42}
          clusterMaxZoom={8}
        >
          <Layer
            id="aprs-clusters"
            type="symbol"
            filter={['has', 'point_count']}
            layout={{
              'icon-image': 'icon-aprs-triangle',
              'icon-size': [
                'step',
                ['get', 'point_count'],
                1.1,
                10,
                1.35,
                50,
                1.65,
                100,
                1.95,
                500,
                2.3,
              ],
              'icon-allow-overlap': true,
            }}
            paint={{
              'icon-opacity': 0.95,
            }}
          />
          <Layer
            id="aprs-cluster-count"
            type="symbol"
            filter={['has', 'point_count']}
            layout={{
              'text-field': ['get', 'point_count_abbreviated'],
              'text-size': 11,
              'text-font': ['Noto Sans Bold'],
              'text-offset': [0, 0.05],
              'text-anchor': 'center',
              'text-allow-overlap': true,
            }}
            paint={{
              'text-color': '#4a0525',
              'text-halo-color': '#f9a8d4',
              'text-halo-width': 0.8,
            }}
          />
          <Layer
            id="aprs-triangles"
            type="symbol"
            filter={['!', ['has', 'point_count']]}
            layout={{
              'icon-image': 'icon-aprs-triangle',
              'icon-size': 0.7,
              'icon-allow-overlap': true,
            }}
            paint={{
              'icon-opacity': 0.85,
            }}
          />
          <Layer
            id="aprs-labels"
            type="symbol"
            minzoom={8}
            layout={{
              'text-field': ['get', 'callsign'],
              'text-size': 9,
              'text-offset': [0, 1.2],
              'text-anchor': 'top',
              'text-font': ['Noto Sans Regular'],
              'text-allow-overlap': false,
            }}
            paint={{
              'text-color': '#f9a8d4',
              'text-halo-color': 'rgba(0,0,0,0.8)',
              'text-halo-width': 1,
            }}
          />
        </Source>

        {/* ═══ FLIGHTS — always rendered above ground/ship/mesh layers ═══ */}
        <Source id="commercial-flights" type="geojson" data={EMPTY_FC}>
          <Layer
            id="commercial-flights-layer"
            type="symbol"
            layout={{
              'icon-image': ['get', 'iconId'],
              'icon-size': ['interpolate', ['linear'], ['zoom'], 5, 0.8, 8, 1.0, 12, 2.0],
              'icon-allow-overlap': true,
              'icon-rotate': ['get', 'rotation'],
              'icon-rotation-alignment': 'map',
            }}
            paint={{ 'icon-opacity': opacityFilter }}
          />
        </Source>

        <Source id="private-flights" type="geojson" data={EMPTY_FC}>
          <Layer
            id="private-flights-layer"
            type="symbol"
            layout={{
              'icon-image': ['get', 'iconId'],
              'icon-size': ['interpolate', ['linear'], ['zoom'], 5, 0.8, 8, 1.0, 12, 2.0],
              'icon-allow-overlap': true,
              'icon-rotate': ['get', 'rotation'],
              'icon-rotation-alignment': 'map',
            }}
            paint={{ 'icon-opacity': opacityFilter }}
          />
        </Source>

        <Source id="private-jets" type="geojson" data={EMPTY_FC}>
          <Layer
            id="private-jets-layer"
            type="symbol"
            layout={{
              'icon-image': ['get', 'iconId'],
              'icon-size': ['interpolate', ['linear'], ['zoom'], 5, 0.8, 8, 1.0, 12, 2.0],
              'icon-allow-overlap': true,
              'icon-rotate': ['get', 'rotation'],
              'icon-rotation-alignment': 'map',
            }}
            paint={{ 'icon-opacity': opacityFilter }}
          />
        </Source>

        <Source id="military-flights" type="geojson" data={EMPTY_FC}>
          <Layer
            id="military-flights-layer"
            type="symbol"
            layout={{
              'icon-image': ['get', 'iconId'],
              'icon-size': ['interpolate', ['linear'], ['zoom'], 5, 0.8, 8, 1.0, 12, 2.0],
              'icon-allow-overlap': true,
              'icon-rotate': ['get', 'rotation'],
              'icon-rotation-alignment': 'map',
            }}
            paint={{ 'icon-opacity': opacityFilter }}
          />
        </Source>

        <Source id="active-route" type="geojson" data={(activeRouteGeoJSON ?? EMPTY_FC)}>
          <Layer
            id="active-route-layer"
            type="line"
            filter={['in', ['get', 'type'], ['literal', ['route-origin', 'route-dest']]]}
            paint={{
              'line-color': [
                'match',
                ['get', 'type'],
                'route-origin',
                '#38bdf8',
                'route-dest',
                '#fcd34d',
                '#ffffff',
              ],
              'line-width': 2,
              'line-dasharray': [2, 2],
              'line-opacity': 0.8,
            }}
          />
          {/* Airport dots at origin/destination */}
          <Layer
            id="airport-dots"
            type="circle"
            filter={['==', ['get', 'type'], 'airport']}
            paint={{
              'circle-radius': 5,
              'circle-color': [
                'match',
                ['get', 'role'],
                'DEP',
                '#38bdf8',
                'ARR',
                '#fcd34d',
                '#ffffff',
              ],
              'circle-stroke-color': '#000',
              'circle-stroke-width': 1.5,
              'circle-opacity': 0.9,
            }}
          />
          {/* IATA code labels at airports */}
          <Layer
            id="airport-labels"
            type="symbol"
            filter={['==', ['get', 'type'], 'airport']}
            layout={{
              'text-field': ['get', 'code'],
              'text-font': ['Noto Sans Bold'],
              'text-size': 11,
              'text-offset': [0, -1.4],
              'text-anchor': 'bottom',
              'text-allow-overlap': true,
            }}
            paint={{
              'text-color': [
                'match',
                ['get', 'role'],
                'DEP',
                '#38bdf8',
                'ARR',
                '#fcd34d',
                '#ffffff',
              ],
              'text-halo-color': '#000',
              'text-halo-width': 1.5,
            }}
          />
        </Source>

        {/* Flight trail history (where the aircraft has been) — altitude-colored gradient */}
        <Source id="flight-trail" type="geojson" data={(trailGeoJSON ?? EMPTY_FC)}>
          <Layer
            id="flight-trail-layer"
            type="line"
            paint={{
              'line-color': ['get', 'color'],
              'line-width': 3,
              'line-opacity': ['coalesce', ['get', 'opacity'], 0.7],
            }}
            layout={{
              'line-cap': 'round',
              'line-join': 'round',
            }}
          />
        </Source>

        {/* Predictive vector (where entity is heading — 5 min forward projection) */}
        <Source id="predictive-path" type="geojson" data={(predictiveGeoJSON ?? EMPTY_FC)}>
          <Layer
            id="predictive-path-layer"
            type="line"
            filter={['==', ['get', 'type'], 'predictive-line']}
            paint={{
              'line-color': '#22d3ee',
              'line-width': 1.5,
              'line-opacity': 0.4,
              'line-dasharray': [4, 4],
            }}
          />
          <Layer
            id="predictive-endpoint"
            type="circle"
            filter={['==', ['get', 'type'], 'predictive-endpoint']}
            paint={{
              'circle-radius': 4,
              'circle-color': 'transparent',
              'circle-stroke-width': 1.5,
              'circle-stroke-color': '#22d3ee',
              'circle-stroke-opacity': 0.4,
              'circle-opacity': 0,
            }}
          />
        </Source>

        {/* Proximity range rings (10nm, 50nm, 100nm around selected entity) */}
        <Source id="proximity-rings" type="geojson" data={(proximityRingsGeoJSON ?? EMPTY_FC)}>
          <Layer
            id="proximity-rings-layer"
            type="line"
            paint={{
              'line-color': 'rgba(34, 211, 238, 0.15)',
              'line-width': 1,
              'line-dasharray': [6, 4],
            }}
          />
          <Layer
            id="proximity-rings-labels"
            type="symbol"
            layout={{
              'symbol-placement': 'line',
              'text-field': ['get', 'label'],
              'text-size': 10,
              'text-font': ['Noto Sans Regular'],
              'text-offset': [0, -0.8],
            }}
            paint={{
              'text-color': 'rgba(34, 211, 238, 0.35)',
              'text-halo-color': '#000',
              'text-halo-width': 1,
            }}
          />
        </Source>

        {/* GDELT & LiveUA — ground-level incidents, rendered below flights */}
        <Source id="gdelt" type="geojson" data={EMPTY_FC}>
          <Layer
            id="gdelt-layer"
            type="circle"
            minzoom={4}
            paint={{
              'circle-radius': 5,
              'circle-color': '#ff8c00',
              'circle-stroke-color': '#ff0000',
              'circle-stroke-width': 1,
              'circle-opacity': 0.7,
            }}
          />
        </Source>

        <Source id="liveuamap" type="geojson" data={EMPTY_FC}>
          <Layer
            id="liveuamap-layer"
            type="symbol"
            minzoom={4}
            layout={{
              'icon-image': ['get', 'iconId'],
              'icon-size': 0.8,
              'icon-allow-overlap': true,
            }}
          />
        </Source>

        {/* tracked-flights & UAVs: rendered above ground layers (airborne) */}
        <Source id="tracked-flights" type="geojson" data={EMPTY_FC}>
          {/* Gold halo ring — POTUS aircraft only (Air Force One/Two, Marine One) */}
          <Layer
            id="tracked-flights-halo"
            type="circle"
            filter={[
              'any',
              ['==', ['get', 'iconId'], 'svgPotusPlane'],
              ['==', ['get', 'iconId'], 'svgPotusHeli'],
            ]}
            paint={{
              'circle-radius': ['interpolate', ['linear'], ['zoom'], 5, 18, 8, 22, 12, 40],
              'circle-color': 'transparent',
              'circle-stroke-width': 2,
              'circle-stroke-color': 'gold',
              'circle-stroke-opacity': opacityFilter,
              'circle-opacity': 0,
            }}
          />
          <Layer
            id="tracked-flights-layer"
            type="symbol"
            layout={{
              'icon-image': ['get', 'iconId'],
              'icon-size': [
                'interpolate', ['linear'], ['zoom'],
                5, ['case',
                  ['==', ['get', 'iconId'], 'svgPotusPlane'], 1.3,
                  ['==', ['get', 'iconId'], 'svgPotusHeli'], 1.3,
                  0.8,
                ],
                8, ['case',
                  ['==', ['get', 'iconId'], 'svgPotusPlane'], 1.6,
                  ['==', ['get', 'iconId'], 'svgPotusHeli'], 1.6,
                  1.0,
                ],
                12, ['case',
                  ['==', ['get', 'iconId'], 'svgPotusPlane'], 2.6,
                  ['==', ['get', 'iconId'], 'svgPotusHeli'], 2.6,
                  2.0,
                ],
              ],
              'icon-allow-overlap': true,
              'icon-rotate': ['get', 'rotation'],
              'icon-rotation-alignment': 'map',
            }}
            paint={{ 'icon-opacity': opacityFilter }}
          />
        </Source>

        <Source id="uavs" type="geojson" data={EMPTY_FC}>
          <Layer
            id="uav-layer"
            type="symbol"
            layout={{
              'icon-image': ['get', 'iconId'],
              'icon-size': ['interpolate', ['linear'], ['zoom'], 5, 0.8, 8, 1.0, 12, 2.0],
              'icon-allow-overlap': true,
              'icon-rotate': ['get', 'rotation'],
              'icon-rotation-alignment': 'map',
            }}
            paint={{ 'icon-opacity': opacityFilter }}
          />
        </Source>

        {/* HTML labels for ship cluster counts (hidden when any entity popup is active) */}
        {shipsGeoJSON && !selectedEntity && !isMapInteracting && (
          <ClusterCountLabels clusters={shipClusters} prefix="sc" />
        )}

        {/* HTML labels for tracked flights — color-matched, zoom-gated for non-HVA */}
        {trackedFlightsGeoJSON && !selectedEntity && !isMapInteracting && data?.tracked_flights && (
          <TrackedFlightLabels
            flights={data.tracked_flights}
            zoom={mapZoom}
            inView={inView}
            interpFlight={interpFlight}
          />
        )}

        {/* HTML labels for carriers (orange names, with ESTIMATED badge for OSINT positions) */}
        {carriersGeoJSON && !selectedEntity && !isMapInteracting && data?.ships && (
          <CarrierLabels ships={data.ships} inView={inView} interpShip={interpShip} />
        )}

        {/* HTML labels for tracked yachts (pink owner names) */}
        {shipsGeoJSON && activeLayers.ships_tracked_yachts && !selectedEntity && !isMapInteracting && data?.ships && (
          <TrackedYachtLabels ships={data.ships} inView={inView} interpShip={interpShip} />
        )}

        {/* HTML labels for earthquake cluster counts (hidden when any entity popup is active) */}
        {earthquakesGeoJSON && !selectedEntity && !isMapInteracting && (
          <ClusterCountLabels clusters={eqClusters} prefix="eqc" />
        )}

        {/* HTML labels for UAVs (orange names) */}
        {uavGeoJSON && !selectedEntity && !isMapInteracting && data?.uavs && (
          <UavLabels uavs={data.uavs} inView={inView} zoom={mapZoom} />
        )}

        {/* HTML labels for earthquakes (yellow) - only show when zoomed in (~2000 miles = zoom ~5) */}
        {earthquakesGeoJSON && !selectedEntity && !isMapInteracting && mapZoom >= 5 && data?.earthquakes && (
          <EarthquakeLabels earthquakes={data.earthquakes} inView={inView} />
        )}

        {/* Maplibre HTML Custom Markers for high-importance Threat Overlays (highest z-index) */}
        {activeLayers.global_incidents && !isMapInteracting && (
          <ThreatMarkers
            spreadAlerts={spreadAlerts}
            zoom={mapZoom}
            selectedEntity={selectedEntity}
            onEntityClick={onEntityClick}
            onDismiss={(alertKey: string) => {
              setDismissedAlerts((prev) => new Set(prev).add(alertKey));
              onEntityClick?.(null);
            }}
          />
        )}

        {/* Satellite positions — mission-type icons */}
        {/* satellites: data pushed imperatively */}
        <Source id="satellites" type="geojson" data={EMPTY_FC}>
          {/* Golden halo ring — ISS only */}
          <Layer
            id="satellites-iss-halo"
            type="circle"
            filter={['==', ['get', 'isISS'], true]}
            paint={{
              'circle-radius': ['interpolate', ['linear'], ['zoom'], 0, 10, 3, 14, 6, 18, 10, 24],
              'circle-color': 'transparent',
              'circle-stroke-width': 2,
              'circle-stroke-color': '#ffdd00',
              'circle-stroke-opacity': 0.8,
              'circle-opacity': 0,
            }}
          />
          <Layer
            id="satellites-layer"
            type="symbol"
            layout={{
              'icon-image': ['get', 'iconId'],
              'icon-size': ['interpolate', ['linear'], ['zoom'], 0, 0.4, 3, 0.5, 6, 0.7, 10, 1.0],
              'icon-allow-overlap': true,
            }}
          />
        </Source>

        {/* Train positions */}
        <Source id="trains" type="geojson" data={EMPTY_FC}>
          <Layer
            id="trains-layer"
            type="symbol"
            layout={{
              'icon-image': ['get', 'iconId'],
              'icon-size': ['interpolate', ['linear'], ['zoom'], 0, 0.3, 4, 0.5, 8, 0.8, 12, 1.0],
              'icon-allow-overlap': true,
            }}
          />
        </Source>

        {/* Satellite click popup (with ISS live feed + maneuver alerts) */}
        {selectedEntity?.type === 'satellite' &&
          (() => {
            const sat = data?.satellites?.find((s) => s.id === selectedEntity.id);
            if (!sat) return null;
            const maneuverAlert = data?.satellite_analysis?.maneuvers?.find(
              (m) => m.norad_id === sat.id
            );
            return (
              <SatellitePopup
                sat={sat}
                maneuverAlert={maneuverAlert}
                onClose={() => onEntityClick?.(null)}
              />
            );
          })()}

        {/* Correlation / Contradiction click popup */}
        {selectedEntity?.type === 'correlation' &&
          (() => {
            const corrIndex = typeof selectedEntity.extra?.corr_index === 'number'
              ? selectedEntity.extra.corr_index
              : parseInt(String(selectedEntity.id).replace('corr-', ''), 10);
            const alert = data?.correlations?.[corrIndex];
            if (!alert) return null;
            return (
              <CorrelationPopup
                alert={alert}
                onClose={() => onEntityClick?.(null)}
              />
            );
          })()}

        {/* UAP Sighting popup */}
        {selectedEntity?.type === 'uap_sighting' &&
          (() => {
            const props = selectedEntity.extra || {};
            const sighting = data?.uap_sightings?.find((s) => s.id === selectedEntity.id);
            const lat = sighting?.lat ?? props.lat;
            const lng = sighting?.lng ?? props.lng;
            if (lat == null || lng == null) return null;
            const location = [props.city, props.state, props.country].filter(Boolean).join(', ') || 'Unknown location';
            const count = props.count ?? 1;
            const hasShape = props.shape && props.shape !== 'unknown';
            const hasSummary = props.summary && props.summary !== 'Sighting reported' && !props.summary?.match(/^\d+ sighting\(s\) reported$/);
            return (
              <Popup longitude={lng} latitude={lat} closeButton={false} closeOnClick={false} onClose={() => onEntityClick?.(null)} className="threat-popup" maxWidth="320px">
                <div className="map-popup bg-[#1a0a30] min-w-[220px]" style={{ borderColor: '#a855f766' }}>
                  <div className="map-popup-title pb-1 flex items-center gap-2" style={{ color: '#c084fc', borderBottom: '1px solid #a855f733' }}>
                    <span style={{ fontSize: 16 }}>👽</span>
                    <span>UAP Sighting</span>
                    <button onClick={() => onEntityClick?.(null)} className="ml-auto text-[var(--text-secondary)] hover:text-[var(--text-primary)]">✕</button>
                  </div>

                  {/* Core details */}
                  <div className="map-popup-row">Location: <span className="text-white">{location}</span></div>
                  {props.date_time && <div className="map-popup-row">Date: <span className="text-white">{props.date_time}</span></div>}
                  {count > 1 && <div className="map-popup-row">Sightings: <span className="text-purple-300 font-bold">{count}</span></div>}

                  {/* Enriched details from NUFORC database */}
                  {(hasShape || props.duration) && (
                    <div className="mt-1.5 pt-1.5 border-t border-purple-500/20">
                      {hasShape && (
                        <div className="map-popup-row">Shape: <span className="text-purple-200 font-semibold">{props.shape_raw || props.shape}</span></div>
                      )}
                      {props.duration && (
                        <div className="map-popup-row">Duration: <span className="text-white">{props.duration}</span></div>
                      )}
                    </div>
                  )}

                  {/* Witness summary */}
                  {hasSummary && (
                    <div className="mt-1.5 pt-1.5 border-t border-purple-500/20">
                      <div className="text-[11px] font-mono tracking-widest text-purple-400/50 mb-1">WITNESS REPORT</div>
                      <div className="text-[10px] leading-relaxed" style={{ color: '#d8b4fe' }}>
                        &ldquo;{props.summary}&rdquo;
                      </div>
                    </div>
                  )}

                  <div className="mt-2 pt-1 border-t border-purple-500/10 text-[11px] tracking-wider" style={{ color: '#a855f799' }}>
                    {props.source || 'NUFORC'} — UAP SIGHTING REPORT
                  </div>
                </div>
              </Popup>
            );
          })()}

        {/* Wastewater plant popup */}
        {selectedEntity?.type === 'wastewater' &&
          (() => {
            const plant = data?.wastewater?.find((w) => w.id === selectedEntity.id);
            if (!plant) return null;
            return (
              <WastewaterPopup
                plant={plant}
                onClose={() => onEntityClick?.(null)}
              />
            );
          })()}

        {/* CrowdThreat popup */}
        {selectedEntity?.type === 'crowdthreat' &&
          (() => {
            const props = selectedEntity.extra || {};
            const ct = data?.crowdthreat?.find((c) => `ct-${c.id}` === selectedEntity.id);
            const lat = ct?.lat ?? props.lat;
            const lng = ct?.lng ?? props.lng;
            if (lat == null || lng == null) return null;
            const accent = props.category_colour || '#6b7280';
            const location = [props.address || props.city, props.country].filter(Boolean).join(', ') || 'Unknown';
            return (
              <Popup longitude={lng} latitude={lat} closeButton={false} closeOnClick={false} onClose={() => onEntityClick?.(null)} className="threat-popup" maxWidth="320px">
                <div className="map-popup min-w-[220px]" style={{ borderColor: `${accent}66`, background: 'var(--bg-secondary)' }}>
                  <div className="map-popup-title pb-1 flex items-center gap-2" style={{ color: accent, borderBottom: `1px solid ${accent}33` }}>
                    <span className="font-bold text-[11px] leading-tight flex-1">{props.title}</span>
                    <button onClick={() => onEntityClick?.(null)} className="ml-auto text-[var(--text-secondary)] hover:text-[var(--text-primary)] shrink-0">✕</button>
                  </div>
                  {props.summary && (
                    <div className="text-[10px] text-white/80 leading-relaxed mt-1 mb-1.5">{props.summary}</div>
                  )}
                  <div className="map-popup-row">Category: <span className="font-semibold" style={{ color: accent }}>{props.category}</span></div>
                  {props.subcategory && <div className="map-popup-row">Subcategory: <span className="text-white">{props.subcategory}</span></div>}
                  {props.threat_type && <div className="map-popup-row">Type: <span className="text-white">{props.threat_type}</span></div>}
                  <div className="map-popup-row">Location: <span className="text-white">{location}</span></div>
                  {props.occurred && <div className="map-popup-row">Occurred: <span className="text-white">{props.occurred}</span></div>}
                  {props.timeago && <div className="map-popup-row">Reported: <span className="text-white">{props.timeago}</span></div>}
                  {props.verification && (
                    <div className="map-popup-row">Status: <span className={props.verification === 'approved' ? 'text-green-400 font-bold' : 'text-yellow-400'}>{props.verification.toUpperCase()}</span></div>
                  )}
                  {props.severity && (
                    <div className="map-popup-row">Severity: <span className="text-red-400 font-bold">{props.severity}</span></div>
                  )}
                  {props.source_url && (
                    <div className="mt-1.5 pt-1.5 border-t border-[var(--border-primary)]">
                      <a href={props.source_url} target="_blank" rel="noreferrer" className="text-[9px] font-bold underline" style={{ color: accent }}>View Source</a>
                    </div>
                  )}
                  <div className="mt-1.5 text-[11px] tracking-wider" style={{ color: `${accent}88` }}>
                    CROWDTHREAT — VERIFIED THREAT INTELLIGENCE
                  </div>
                </div>
              </Popup>
            );
          })()}

        {/* Train click popup */}
        {selectedEntity?.type === 'train' &&
          (() => {
            const train = data?.trains?.find((t) => t.id === selectedEntity.id);
            if (!train) return null;
            const isAmtrak = train.source === 'amtrak';
            const sourceLabel = train.source_label || train.source.toUpperCase();
            const subtitleParts = [sourceLabel];
            if (train.operator && train.operator !== sourceLabel) subtitleParts.push(train.operator);
            return (
              <Popup
                longitude={train.lng}
                latitude={train.lat}
                closeButton={false}
                closeOnClick={false}
                onClose={() => onEntityClick?.(null)}
                anchor="bottom"
                offset={12}
              >
                <div className="map-popup border border-orange-500/30">
                  <div className="flex justify-between items-start mb-0.5">
                  <div className={`map-popup-title ${isAmtrak ? 'text-[#ff8800]' : 'text-[#00aaff]'}`}>
                      {train.name}
                    </div>
                    <button onClick={() => onEntityClick?.(null)}
                      className="text-[var(--text-secondary)] hover:text-[var(--text-primary)] ml-2">✕</button>
                  </div>
                  <div className="map-popup-subtitle text-[#8899aa] border-b border-gray-700/50 pb-1">
                    {subtitleParts.join(' / ')}{train.number ? ` — #${train.number}` : ''}
                  </div>
                  {train.country && (
                    <div className="map-popup-row">
                      Country: <span className="text-white">{train.country}</span>
                    </div>
                  )}
                  {train.route && (
                    <div className="map-popup-row">
                      Route: <span className="text-white">{train.route}</span>
                    </div>
                  )}
                  {train.speed_kmh != null && (
                    <div className="map-popup-row">
                      Speed: <span className="text-[#44ff88]">{train.speed_kmh} km/h</span>
                    </div>
                  )}
                  <div className="map-popup-row">
                    Status: <span className={train.status?.toLowerCase().includes('late') || train.status?.toLowerCase().includes('delay')
                      ? 'text-red-400' : 'text-green-400'}>{train.status || 'Active'}</span>
                  </div>
                </div>
              </Popup>
            );
          })()}

        {/* UAV click popup — real ADS-B detected drones */}
        {selectedEntity?.type === 'uav' &&
          (() => {
            const uav = data?.uavs?.find((u) => u.id === selectedEntity.id);
            if (!uav) return null;
            return (
              <Popup
                longitude={uav.lng}
                latitude={uav.lat}
                closeButton={false}
                closeOnClick={false}
                onClose={() => onEntityClick?.(null)}
                anchor="bottom"
                offset={12}
              >
                <div className="map-popup border border-red-500/40">
                  <div className="map-popup-title text-[#ff4444]">{uav.callsign}</div>
                  <div className="map-popup-subtitle text-[#ff8844]">LIVE ADS-B TRANSPONDER</div>
                  {uav.aircraft_model && (
                    <div className="map-popup-row">
                      Model: <span className="text-white">{uav.aircraft_model}</span>
                    </div>
                  )}
                  {uav.uav_type && (
                    <div className="map-popup-row">
                      Classification: <span className="text-[#ffcc00]">{uav.uav_type}</span>
                    </div>
                  )}
                  {uav.country && (
                    <div className="map-popup-row">
                      Registration: <span className="text-white">{uav.country}</span>
                    </div>
                  )}
                  {uav.icao24 && (
                    <div className="map-popup-row">
                      ICAO: <span className="text-[#888]">{uav.icao24}</span>
                    </div>
                  )}
                  <div className="map-popup-row">
                    Altitude: <span className="text-[#44ff88]">{uav.alt?.toLocaleString()} m</span>
                  </div>
                  {(uav.speed_knots ?? 0) > 0 && (
                    <div className="map-popup-row">
                      Speed: <span className="text-[#00e5ff]">{uav.speed_knots} kn</span>
                    </div>
                  )}
                  {uav.squawk && (
                    <div className="map-popup-row">
                      Squawk: <span className="text-[#888]">{uav.squawk}</span>
                    </div>
                  )}
                  {uav.wiki && (
                    <div className="mt-2 border-t border-[var(--border-primary)]/50 pt-2">
                      <WikiImage
                        wikiUrl={uav.wiki}
                        label={uav.callsign}
                        maxH="max-h-28"
                        accent="hover:border-red-500/50"
                      />
                    </div>
                  )}
                </div>
              </Popup>
            );
          })()}

        {/* KiwiSDR Receivers Popup */}
        {selectedEntity?.type === 'kiwisdr' &&
          (() => {
            const receiver = data?.kiwisdr?.find(
              (k) => k.name === selectedEntity.name || k.name === String(selectedEntity.id),
            );
            // use extra if available from the click event, otherwise fallback
            const props = (selectedEntity.extra || receiver || {}) as KiwiProps;
            const lat =
              props.lat ??
              selectedEntity.extra?.lat ??
              selectedEntity.extra?.geometry?.coordinates?.[1];
            const lng =
              props.lon ??
              props.lng ??
              selectedEntity.extra?.lon ??
              selectedEntity.extra?.geometry?.coordinates?.[0];
            if (lat == null || lng == null) return null;
            return (
              <Popup
                longitude={lng}
                latitude={lat}
                closeButton={false}
                closeOnClick={false}
                onClose={() => onEntityClick?.(null)}
                anchor="bottom"
                offset={12}
              >
                <div
                  className="map-popup !border-amber-500/40"
                  style={{ borderWidth: 1, borderStyle: 'solid' }}
                >
                  <div className="flex justify-between items-start mb-1">
                    <div className="map-popup-title text-amber-400">
                      {(props.name || 'UNKNOWN SDR RECEIVER').toUpperCase()}
                    </div>
                    <button
                      onClick={() => onEntityClick?.(null)}
                      className="text-[var(--text-secondary)] hover:text-[var(--text-primary)] ml-2"
                    >
                      ✕
                    </button>
                  </div>
                  <div className="map-popup-subtitle text-amber-600/80 border-b border-amber-900/30 pb-1 flex items-center gap-1.5">
                    <Radio size={10} /> PUBLIC NETWORK RECEIVER
                  </div>

                  {props.location && (
                    <div className="map-popup-row mt-1">
                      Location: <span className="text-white">{props.location}</span>
                    </div>
                  )}
                  {props.users !== undefined && (
                    <div className="map-popup-row">
                      Active Users:{' '}
                      <span
                        className={
                          props.users >= (props.users_max || 4) ? 'text-red-400' : 'text-amber-400'
                        }
                      >
                        {props.users} / {props.users_max || '?'}
                      </span>
                    </div>
                  )}
                  {props.antenna && (
                    <div className="map-popup-row">
                      Antenna: <span className="text-[#888]">{props.antenna}</span>
                    </div>
                  )}
                  {props.bands && (
                    <div className="map-popup-row">
                      Bands:{' '}
                      <span className="text-cyan-400">
                        {(Number(props.bands.split('-')[0]) / 1e6).toFixed(0)}-
                        {(Number(props.bands.split('-')[1]) / 1e6).toFixed(0)} MHz
                      </span>
                    </div>
                  )}

                  <div className="flex items-center gap-2 mt-3 pt-2 border-t border-[var(--border-primary)]">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        if (setTrackedSdr) {
                          setTrackedSdr({
                            lat,
                            lon: lng,
                            name: props.name || 'Unknown',
                            url: props.url,
                            users: props.users,
                            users_max: props.users_max,
                            bands: props.bands,
                            antenna: props.antenna,
                            location: props.location,
                          });
                        }
                        onEntityClick?.(null);
                      }}
                      className="flex-1 text-center px-2 py-1.5 rounded bg-amber-950/40 border border-amber-500/30 hover:bg-amber-900/60 hover:border-amber-400 text-amber-400 text-[9px] font-mono tracking-widest transition-colors flex justify-center items-center gap-1.5"
                    >
                      <Activity size={10} /> TRACK
                    </button>
                    {props.url && (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          if (setTrackedSdr) {
                            setTrackedSdr({
                              lat,
                              lon: lng,
                              name: props.name || 'Unknown',
                              url: props.url,
                              users: props.users,
                              users_max: props.users_max,
                              bands: props.bands,
                              antenna: props.antenna,
                              location: props.location,
                            });
                          }
                          onEntityClick?.(null);
                        }}
                        className="flex-1 text-center px-2 py-1.5 rounded bg-amber-500/20 border border-amber-500/50 hover:bg-amber-500/30 hover:border-amber-400 text-amber-300 text-[9px] font-mono tracking-widest transition-colors flex justify-center items-center gap-1.5"
                      >
                        <Play size={10} /> TUNE IN
                      </button>
                    )}
                  </div>
                </div>
              </Popup>
            );
          })()}

        {/* SatNOGS Ground Station Popup */}
        {selectedEntity?.type === 'satnogs_station' &&
          (() => {
            const props = (selectedEntity.extra || {}) as Record<string, unknown>;
            const lat = (props.lat as number) ?? selectedEntity.extra?.geometry?.coordinates?.[1];
            const lng = (props.lng as number) ?? selectedEntity.extra?.geometry?.coordinates?.[0];
            if (lat == null || lng == null) return null;
            return (
              <Popup
                longitude={lng}
                latitude={lat}
                closeButton={false}
                closeOnClick={false}
                onClose={() => onEntityClick?.(null)}
                anchor="bottom"
                offset={12}
              >
                <div
                  className="map-popup !border-teal-500/40"
                  style={{ borderWidth: 1, borderStyle: 'solid' }}
                >
                  <div className="flex justify-between items-start mb-1">
                    <div className="map-popup-title text-teal-400">
                      {((props.name as string) || 'UNKNOWN STATION').toUpperCase()}
                    </div>
                    <button
                      onClick={() => onEntityClick?.(null)}
                      className="text-[var(--text-secondary)] hover:text-[var(--text-primary)] ml-2"
                    >
                      ✕
                    </button>
                  </div>
                  <div className="map-popup-subtitle text-teal-600/80 border-b border-teal-900/30 pb-1 flex items-center gap-1.5">
                    <Satellite size={10} /> SATNOGS GROUND STATION
                  </div>
                  {String(props.antenna || '') !== '' && (
                    <div className="map-popup-row mt-1">
                      Antenna: <span className="text-[#888]">{String(props.antenna)}</span>
                    </div>
                  )}
                  {Number(props.observations || 0) > 0 && (
                    <div className="map-popup-row">
                      Observations: <span className="text-teal-400">{Number(props.observations).toLocaleString()}</span>
                    </div>
                  )}
                  {String(props.last_seen || '') !== '' && (
                    <div className="map-popup-row">
                      Last seen: <span className="text-[#888]">{new Date(String(props.last_seen)).toLocaleString()}</span>
                    </div>
                  )}
                  <div className="map-popup-row text-[10px] text-[#555] mt-1">
                    {lat.toFixed(4)}°, {lng.toFixed(4)}°
                  </div>
                </div>
              </Popup>
            );
          })()}

        {/* TinyGS LoRa Satellite Popup */}
        {selectedEntity?.type === 'tinygs_satellite' &&
          (() => {
            const props = (selectedEntity.extra || {}) as Record<string, unknown>;
            const lat = (props.lat as number) ?? selectedEntity.extra?.geometry?.coordinates?.[1];
            const lng = (props.lng as number) ?? selectedEntity.extra?.geometry?.coordinates?.[0];
            if (lat == null || lng == null) return null;
            return (
              <Popup
                longitude={lng}
                latitude={lat}
                closeButton={false}
                closeOnClick={false}
                onClose={() => onEntityClick?.(null)}
                anchor="bottom"
                offset={12}
              >
                <div
                  className="map-popup !border-purple-500/40"
                  style={{ borderWidth: 1, borderStyle: 'solid' }}
                >
                  <div className="flex justify-between items-start mb-1">
                    <div className="map-popup-title text-purple-400">
                      {String(props.name || 'UNKNOWN SATELLITE').toUpperCase()}
                    </div>
                    <button
                      onClick={() => onEntityClick?.(null)}
                      className="text-[var(--text-secondary)] hover:text-[var(--text-primary)] ml-2"
                    >
                      ✕
                    </button>
                  </div>
                  <div className="map-popup-subtitle text-purple-600/80 border-b border-purple-900/30 pb-1 flex items-center gap-1.5">
                    <Satellite size={10} /> LORA SATELLITE
                    {props.tinygs_confirmed ? (
                      <span className="text-green-400 text-[11px] ml-1">TINYGS LIVE</span>
                    ) : props.sgp4_propagated ? (
                      <span className="text-purple-400 text-[11px] ml-1">SGP4 ORBIT</span>
                    ) : null}
                  </div>
                  {Number(props.alt_km || 0) > 0 && (
                    <div className="map-popup-row mt-1">
                      Altitude: <span className="text-purple-400">{Number(props.alt_km).toFixed(0)} km</span>
                    </div>
                  )}
                  {String(props.modulation || '') !== '' && (
                    <div className="map-popup-row">
                      Modulation: <span className="text-purple-400">{String(props.modulation)}</span>
                    </div>
                  )}
                  {String(props.frequency || '') !== '' && (
                    <div className="map-popup-row">
                      Frequency: <span className="text-purple-400">{String(props.frequency)} MHz</span>
                    </div>
                  )}
                  {String(props.status || '') !== '' && (
                    <div className="map-popup-row">
                      Status: <span className="text-[#888]">{String(props.status)}</span>
                    </div>
                  )}
                  <div className="map-popup-row text-[10px] text-[#555] mt-1">
                    {lat.toFixed(4)}°, {lng.toFixed(4)}°
                  </div>
                </div>
              </Popup>
            );
          })()}

        {/* CCTV popup removed — now handled by fullscreen OPTIC INTERCEPT modal */}

        {/* Police Scanner click popup */}
        {selectedEntity?.type === 'scanner' &&
          (() => {
            const props = (selectedEntity.extra || {}) as ScannerProps;
            const lat = props.lat ?? selectedEntity.extra?.geometry?.coordinates?.[1];
            const lng = props.lng ?? selectedEntity.extra?.geometry?.coordinates?.[0];
            if (lat == null || lng == null) return null;
            return (
              <Popup
                longitude={lng}
                latitude={lat}
                closeButton={false}
                closeOnClick={false}
                onClose={() => onEntityClick?.(null)}
                anchor="bottom"
                offset={12}
              >
                <div
                  className="map-popup !border-red-500/40"
                  style={{ borderWidth: 1, borderStyle: 'solid' }}
                >
                  <div className="flex justify-between items-start mb-1">
                    <div className="map-popup-title text-red-400">
                      {(props.name || 'UNKNOWN SYSTEM').toUpperCase()}
                    </div>
                    <button
                      onClick={() => onEntityClick?.(null)}
                      className="text-[var(--text-secondary)] hover:text-[var(--text-primary)] ml-2"
                    >
                      ✕
                    </button>
                  </div>
                  <div className="map-popup-subtitle text-red-600/80 border-b border-red-900/30 pb-1 flex items-center gap-1.5">
                    <Radio size={10} /> TRUNKED RADIO SYSTEM
                  </div>

                  {(props.city || props.state) && (
                    <div className="map-popup-row mt-1">
                      Location:{' '}
                      <span className="text-white">
                        {[props.city, props.state].filter(Boolean).join(', ')}
                      </span>
                    </div>
                  )}
                  <div className="map-popup-row">
                    Active Listeners: <span className="text-red-400">{props.clientCount || 0}</span>
                  </div>
                  {props.description && (
                    <div className="map-popup-row">
                      <span className="text-[#888]">{String(props.description).slice(0, 120)}</span>
                    </div>
                  )}

                  <div className="flex items-center gap-2 mt-3 pt-2 border-t border-[var(--border-primary)]">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        if (setTrackedScanner) {
                          setTrackedScanner({
                            shortName: props.shortName || '',
                            name: props.name || '',
                            lat,
                            lng,
                            city: props.city || '',
                            state: props.state || '',
                            clientCount: props.clientCount || 0,
                            description: props.description || '',
                          });
                        }
                        onEntityClick?.(null);
                      }}
                      className="flex-1 text-center px-2 py-1.5 rounded bg-red-950/40 border border-red-500/30 hover:bg-red-900/60 hover:border-red-400 text-red-400 text-[9px] font-mono tracking-widest transition-colors flex justify-center items-center gap-1.5"
                    >
                      <Activity size={10} /> TRACK
                    </button>
                    <button
                      onClick={async (e) => {
                        e.stopPropagation();
                        const sn = props.shortName || '';
                        if (setTrackedScanner) {
                          setTrackedScanner({
                            shortName: sn,
                            name: props.name || '',
                            lat,
                            lng,
                            city: props.city || '',
                            state: props.state || '',
                            clientCount: props.clientCount || 0,
                            description: props.description || '',
                          });
                        }
                        onEntityClick?.(null);
                      }}
                      className="flex-1 text-center px-2 py-1.5 rounded bg-red-500/20 border border-red-500/50 hover:bg-red-500/30 hover:border-red-400 text-red-300 text-[9px] font-mono tracking-widest transition-colors flex justify-center items-center gap-1.5"
                    >
                      <Play size={10} /> OPEN PLAYER
                    </button>
                  </div>
                </div>
              </Popup>
            );
          })()}

        {/* SIGINT signal click popup */}
        {selectedEntity?.type === 'sigint' &&
          (() => {
            const props = (selectedEntity.extra || {}) as SigintProps;
            const sig = data?.sigint?.find(
              (s) => `${s.source}:${s.callsign}` === selectedEntity.id,
            );
            const d = sig || props;
            const lat = sig?.lat ?? props.geometry?.coordinates?.[1];
            const lng = sig?.lng ?? props.geometry?.coordinates?.[0];
            if (lat == null || lng == null) return null;
            return (
              <SigintPopup
                data={d}
                lat={lat}
                lng={lng}
                kiwisdrs={data?.kiwisdr || []}
                setTrackedSdr={setTrackedSdr}
                onClose={() => onEntityClick?.(null)}
              />
            );
          })()}

        {/* Ship / carrier click popup */}
        {selectedEntity?.type === 'ship' &&
          (() => {
            const ship = data?.ships?.find((s, i: number) => {
              return (
                (s.mmsi || s.name || `ship-${i}`) === selectedEntity.id ||
                (s.mmsi || s.name || `carrier-${i}`) === selectedEntity.id
              );
            });
            if (!ship) return null;
            const [iLng, iLat] = interpShip(ship);
            return (
              <ShipPopup
                ship={ship}
                longitude={iLng}
                latitude={iLat}
                onClose={() => onEntityClick?.(null)}
              />
            );
          })()}

        {/* SAR anomaly click popup */}
        {selectedEntity?.type === 'sar_anomaly' &&
          (() => {
            const extra = (selectedEntity.extra || {}) as Record<string, unknown>;
            const anomaly = data?.sar_anomalies?.find(
              (a) => a.anomaly_id === selectedEntity.id,
            );
            const a = anomaly || extra;
            const lat = typeof a.lat === 'number' ? a.lat : Number(extra.center_lat);
            const lng =
              typeof (a as { lon?: number }).lon === 'number'
                ? (a as { lon: number }).lon
                : Number(extra.center_lon);
            if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null;
            const kind = String(a.kind || extra.kind || 'anomaly');
            const title = String(a.title || extra.title || `SAR ${kind}`);
            const summary = String(a.summary || extra.summary || '');
            const solver = String(a.solver || extra.solver || '');
            const constellation = String(
              (a as { source_constellation?: string }).source_constellation ||
                extra.source_constellation ||
                '',
            );
            const magnitude = Number(a.magnitude ?? extra.magnitude ?? 0);
            const unit = String(a.magnitude_unit || extra.magnitude_unit || '');
            const confidence = Number(a.confidence ?? extra.confidence ?? 0);
            const lastSeen = Number(a.last_seen ?? extra.last_seen ?? 0);
            const provenance = String(a.provenance_url || extra.provenance_url || '');
            const aoiId = String(a.aoi_id || extra.aoi_id || '');
            const color = String(extra.color || '#eab308');
            return (
              <Popup
                longitude={lng}
                latitude={lat}
                closeButton={false}
                closeOnClick={false}
                onClose={() => onEntityClick?.(null)}
                className="threat-popup"
                maxWidth="320px"
              >
                <div
                  className="map-popup bg-zinc-950/95 text-amber-100 min-w-[240px]"
                  style={{ border: `1px solid ${color}66` }}
                >
                  <div
                    className="map-popup-title flex items-center justify-between gap-2 border-b pb-1"
                    style={{ borderColor: `${color}33`, color }}
                  >
                    <span className="font-semibold">{title}</span>
                    <button
                      type="button"
                      onClick={() => onEntityClick?.(null)}
                      className="text-amber-200/60 hover:text-amber-100"
                      aria-label="Close"
                    >
                      ✕
                    </button>
                  </div>
                  {summary && (
                    <div className="map-popup-row text-[11px] text-amber-100/80 leading-snug">
                      {summary}
                    </div>
                  )}
                  <div className="map-popup-row text-[11px]">
                    Kind:{' '}
                    <span className="text-amber-200 font-mono">
                      {kind.replace(/_/g, ' ')}
                    </span>
                  </div>
                  {solver && (
                    <div className="map-popup-row text-[11px]">
                      Solver: <span className="text-amber-200">{solver}</span>
                    </div>
                  )}
                  {constellation && (
                    <div className="map-popup-row text-[11px]">
                      Source: <span className="text-amber-200">{constellation}</span>
                    </div>
                  )}
                  {magnitude !== 0 && (
                    <div className="map-popup-row text-[11px]">
                      Magnitude:{' '}
                      <span className="text-amber-200">
                        {magnitude.toFixed(3)} {unit}
                      </span>
                    </div>
                  )}
                  <div className="map-popup-row text-[11px]">
                    Confidence:{' '}
                    <span className="text-amber-200">{(confidence * 100).toFixed(0)}%</span>
                  </div>
                  {lastSeen > 0 && (
                    <div className="map-popup-row text-[11px]">
                      Last seen:{' '}
                      <span className="text-amber-200">
                        {new Date(lastSeen * 1000).toISOString().replace('T', ' ').slice(0, 19)}Z
                      </span>
                    </div>
                  )}
                  {aoiId && (
                    <div className="map-popup-row text-[11px]">
                      AOI: <span className="text-amber-200 font-mono">{aoiId}</span>
                    </div>
                  )}
                  {provenance && (
                    <div className="map-popup-row text-[11px]">
                      <a
                        href={provenance}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-cyan-300 hover:text-cyan-200 underline"
                      >
                        Provenance ↗
                      </a>
                    </div>
                  )}
                </div>
              </Popup>
            );
          })()}

        {/* SAR AOI click popup — operator watchbox details */}
        {selectedEntity?.type === 'sar_aoi' &&
          (() => {
            const extra = (selectedEntity.extra || {}) as Record<string, unknown>;
            const lat = Number(extra.center_lat);
            const lng = Number(extra.center_lon);
            if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null;
            const name = String(extra.name || selectedEntity.id);
            const description = String(extra.description || '');
            const category = String(extra.category || 'watchlist');
            const radius = Number(extra.radius_km || 0);
            return (
              <Popup
                longitude={lng}
                latitude={lat}
                closeButton={false}
                closeOnClick={false}
                onClose={() => onEntityClick?.(null)}
                className="threat-popup"
                maxWidth="300px"
              >
                <div className="map-popup bg-zinc-950/95 border border-amber-400/40 text-amber-100 min-w-[220px]">
                  <div className="map-popup-title flex items-center justify-between gap-2 text-amber-300 border-b border-amber-400/20 pb-1">
                    <span>AOI · {name}</span>
                    <button
                      type="button"
                      onClick={() => onEntityClick?.(null)}
                      className="text-amber-200/60 hover:text-amber-100"
                      aria-label="Close"
                    >
                      ✕
                    </button>
                  </div>
                  {description && (
                    <div className="map-popup-row text-[11px] text-amber-100/80 leading-snug">
                      {description}
                    </div>
                  )}
                  <div className="map-popup-row text-[11px]">
                    Category:{' '}
                    <span className="text-amber-200 font-mono">{category}</span>
                  </div>
                  <div className="map-popup-row text-[11px]">
                    Radius: <span className="text-amber-200">{radius.toFixed(0)} km</span>
                  </div>
                  <div className="map-popup-row text-[11px]">
                    Center:{' '}
                    <span className="text-amber-200 font-mono">
                      {lat.toFixed(3)}, {lng.toFixed(3)}
                    </span>
                  </div>
                </div>
              </Popup>
            );
          })()}

        {/* Data Center click popup */}
        {selectedEntity?.type === 'datacenter' &&
          (() => {
            const dc = data?.datacenters?.find((_, i: number) => `dc-${i}` === selectedEntity.id);
            if (!dc) return null;
            // Check if any internet outage is in the same country
            const outagesInCountry = (data?.internet_outages || []).filter(
              (o) =>
                o.country_name &&
                dc.country &&
                o.country_name.toLowerCase() === dc.country.toLowerCase(),
            );
            return (
              <Popup
                longitude={dc.lng}
                latitude={dc.lat}
                closeButton={false}
                closeOnClick={false}
                onClose={() => onEntityClick?.(null)}
                className="threat-popup"
                maxWidth="280px"
              >
                <div className="map-popup bg-[#1a1035] border border-violet-400/40 text-[#e9d5ff] min-w-[200px]">
                  <div className="map-popup-title text-violet-400 border-b border-violet-400/20 pb-1">
                    {dc.name}
                  </div>
                  {dc.company && (
                    <div className="map-popup-row">
                      Operator: <span className="text-[#c4b5fd]">{dc.company}</span>
                    </div>
                  )}
                  {dc.street && (
                    <div className="map-popup-row">
                      Address:{' '}
                      <span className="text-white">
                        {dc.street}
                        {dc.zip ? ` ${dc.zip}` : ''}
                      </span>
                    </div>
                  )}
                  {dc.city && (
                    <div className="map-popup-row">
                      Location:{' '}
                      <span className="text-white">
                        {dc.city}
                        {dc.country ? `, ${dc.country}` : ''}
                      </span>
                    </div>
                  )}
                  {!dc.city && dc.country && (
                    <div className="map-popup-row">
                      Country: <span className="text-white">{dc.country}</span>
                    </div>
                  )}
                  {outagesInCountry.length > 0 && (
                    <div className="mt-1.5 px-2 py-1 bg-red-500/15 border border-red-400/40 rounded text-[10px] text-[#ff6b6b]">
                      OUTAGE IN REGION —{' '}
                      {outagesInCountry.map((o) => `${o.region_name} (${o.severity}%)`).join(', ')}
                    </div>
                  )}
                  <div className="mt-1.5 text-[9px] text-violet-600 tracking-wider">
                    DATA CENTER
                  </div>
                </div>
              </Popup>
            );
          })()}

        {/* Power Plant click popup */}
        {selectedEntity?.type === 'power_plant' && (() => {
            const pp = data?.power_plants?.find((_: any, i: number) => `pp-${i}` === selectedEntity.id);
            if (!pp) return null;
            return (
                <Popup
                    longitude={pp.lng}
                    latitude={pp.lat}
                    closeButton={false}
                    closeOnClick={false}
                    onClose={() => onEntityClick?.(null)}
                    className="threat-popup"
                    maxWidth="280px"
                >
                    <div className="map-popup bg-[#1a0f00] border border-amber-400/40 text-[#fde68a] min-w-[200px]">
                        <div className="map-popup-title text-amber-400 border-b border-amber-400/20 pb-1">
                            {pp.name}
                        </div>
                        {pp.fuel_type && (
                            <div className="map-popup-row">
                                Fuel: <span className="text-[#fbbf24]">{pp.fuel_type}</span>
                            </div>
                        )}
                        {pp.capacity_mw != null && (
                            <div className="map-popup-row">
                                Capacity: <span className="text-white">{pp.capacity_mw.toLocaleString()} MW</span>
                            </div>
                        )}
                        {pp.owner && (
                            <div className="map-popup-row">
                                Operator: <span className="text-white">{pp.owner}</span>
                            </div>
                        )}
                        {pp.country && (
                            <div className="map-popup-row">
                                Country: <span className="text-white">{pp.country}</span>
                            </div>
                        )}
                        <div className="mt-1.5 text-[9px] text-amber-600 tracking-wider">
                            POWER PLANT
                        </div>
                    </div>
                </Popup>
            );
        })()}

        {/* VIIRS Change Node click popup */}
        {selectedEntity?.type === 'viirs_change_node' && (() => {
            const node = data?.viirs_change_nodes?.find(
                (_: any, i: number) => `viirs-${i}` === selectedEntity.id
            );
            if (!node) return null;
            const isLoss = node.mean_change_pct < 0;
            return (
                <Popup
                    longitude={node.lng}
                    latitude={node.lat}
                    closeButton={false}
                    closeOnClick={false}
                    onClose={() => onEntityClick?.(null)}
                    className="threat-popup"
                    maxWidth="280px"
                >
                    <div className="map-popup bg-black/90 border border-cyan-500/30 text-white min-w-[200px]">
                        <div className="map-popup-title text-cyan-400 border-b border-cyan-500/20 pb-1 tracking-wider">
                            VIIRS NIGHT LIGHTS
                        </div>
                        <div className="map-popup-row">
                            Region: <span className="text-white">{node.aoi_name}</span>
                        </div>
                        <div className="map-popup-row">
                            Change: <span className={`text-lg font-bold ${isLoss ? 'text-red-400' : 'text-green-400'}`}>
                                {isLoss ? '' : '+'}{node.mean_change_pct.toFixed(1)}%
                            </span>
                        </div>
                        <div className="map-popup-row">
                            Severity: <span className="text-white uppercase">{node.severity.replace('_', ' ')}</span>
                        </div>
                        <div className="mt-1.5 text-[9px] text-cyan-600 tracking-wider">
                            {isLoss ? 'LIGHTS WENT DARK' : 'LIGHTS INCREASED'}
                        </div>
                    </div>
                </Popup>
            );
        })()}

        {selectedEntity?.type === 'military_base' &&
          (() => {
            const base = data?.military_bases?.find(
              (_, i: number) => `milbase-${i}` === selectedEntity.id,
            );
            if (!base) return null;
            return (
              <MilitaryBasePopup
                base={base}
                oracleIntel={oracleIntel}
                onClose={() => onEntityClick?.(null)}
              />
            );
          })()}

        {/* Ukraine Air Raid Alert popup */}
        {selectedEntity?.type === 'ukraine_alert' &&
          (() => {
            const alert = data?.ukraine_alerts?.find((a) => String(a.id) === String(selectedEntity.id));
            if (!alert) return null;
            const accent = alert.color || '#ef4444';
            const geom = alert.geometry;
            const coords = geom?.type === 'Polygon' ? geom.coordinates?.[0]?.[0] : geom?.type === 'MultiPolygon' ? geom.coordinates?.[0]?.[0]?.[0] : null;
            if (!coords) return null;
            const started = alert.started_at ? new Date(alert.started_at) : null;
            const durationMin = started ? Math.round((Date.now() - started.getTime()) / 60000) : null;
            const durationStr = durationMin != null ? (durationMin >= 60 ? `${Math.floor(durationMin / 60)}h ${durationMin % 60}m` : `${durationMin}m`) : '';
            const alertLabel = ({ air_raid: 'AIR RAID', artillery_shelling: 'SHELLING', urban_fights: 'URBAN COMBAT', chemical: 'CHEMICAL', nuclear: 'NUCLEAR' } as Record<string, string>)[alert.alert_type] || alert.alert_type.toUpperCase();
            return (
              <Popup longitude={coords[0]} latitude={coords[1]} closeButton={false} closeOnClick={false} onClose={() => onEntityClick?.(null)} className="threat-popup" maxWidth="300px">
                <div className="map-popup bg-[#1a1035] min-w-[220px]" style={{ borderColor: `${accent}66` }}>
                  <div className="map-popup-title pb-1" style={{ color: accent, borderBottom: `1px solid ${accent}33` }}>
                    {alertLabel}
                  </div>
                  <div className="map-popup-row text-white text-[11px]">{alert.name_en || alert.location_title}</div>
                  <div className="map-popup-row">Oblast: <span className="text-white">{alert.location_title}</span></div>
                  {started && <div className="map-popup-row">Since: <span className="text-white">{started.toLocaleTimeString()}</span></div>}
                  {durationStr && <div className="map-popup-row">Duration: <span style={{ color: accent }}>{durationStr}</span></div>}
                  <div className="mt-1.5 text-[9px] tracking-wider text-gray-500">UKRAINE AIR RAID — ALERTS.IN.UA</div>
                </div>
              </Popup>
            );
          })()}

        {/* Weather Alert popup */}
        {selectedEntity?.type === 'weather_alert' &&
          (() => {
            const alert = data?.weather_alerts?.find((a) => a.id === selectedEntity.id);
            if (!alert) return null;
            const sevColors: Record<string, string> = { Extreme: '#ef4444', Severe: '#f97316', Moderate: '#eab308', Minor: '#3b82f6' };
            const accent = sevColors[alert.severity] || '#3b82f6';
            const geom = alert.geometry;
            const coords = geom?.type === 'Polygon' ? geom.coordinates?.[0]?.[0] : geom?.type === 'MultiPolygon' ? geom.coordinates?.[0]?.[0]?.[0] : null;
            if (!coords) return null;
            return (
              <Popup longitude={coords[0]} latitude={coords[1]} closeButton={false} closeOnClick={false} onClose={() => onEntityClick?.(null)} className="threat-popup" maxWidth="300px">
                <div className="map-popup bg-[#1a1035] min-w-[220px]" style={{ borderColor: `${accent}66` }}>
                  <div className="map-popup-title pb-1" style={{ color: accent, borderBottom: `1px solid ${accent}33` }}>
                    {alert.event}
                  </div>
                  <div className="map-popup-row text-white text-[10px] leading-snug">{alert.headline}</div>
                  <div className="map-popup-row">Severity: <span style={{ color: accent }}>{alert.severity}</span></div>
                  {alert.expires && <div className="map-popup-row">Expires: <span className="text-white">{new Date(alert.expires).toLocaleString()}</span></div>}
                  <div className="mt-1 text-[9px] text-gray-400 leading-snug max-h-[60px] overflow-hidden">{alert.description}</div>
                </div>
              </Popup>
            );
          })()}

        {/* Air Quality popup */}
        {selectedEntity?.type === 'air_quality' &&
          (() => {
            const station = data?.air_quality?.find((s) => `aq-${s.id}` === selectedEntity.id);
            if (!station) return null;
            const aqiColors: Record<string, string> = { Good: '#22c55e', Moderate: '#eab308', 'Unhealthy (Sensitive)': '#f97316', Unhealthy: '#ef4444', 'Very Unhealthy': '#a855f7', Hazardous: '#7f1d1d' };
            const label = station.aqi <= 50 ? 'Good' : station.aqi <= 100 ? 'Moderate' : station.aqi <= 150 ? 'Unhealthy (Sensitive)' : station.aqi <= 200 ? 'Unhealthy' : station.aqi <= 300 ? 'Very Unhealthy' : 'Hazardous';
            const accent = aqiColors[label] || '#22c55e';
            return (
              <Popup longitude={station.lng} latitude={station.lat} closeButton={false} closeOnClick={false} onClose={() => onEntityClick?.(null)} className="threat-popup" maxWidth="260px">
                <div className="map-popup bg-[#1a1035] min-w-[180px]" style={{ borderColor: `${accent}66` }}>
                  <div className="map-popup-title pb-1" style={{ color: accent, borderBottom: `1px solid ${accent}33` }}>
                    {station.name}
                  </div>
                  <div className="map-popup-row">AQI: <span style={{ color: accent, fontWeight: 'bold' }}>{station.aqi}</span> <span className="text-gray-400">({label})</span></div>
                  <div className="map-popup-row">PM2.5: <span className="text-white">{station.pm25} µg/m³</span></div>
                  {station.country && <div className="map-popup-row">Country: <span className="text-white">{station.country}</span></div>}
                  <div className="mt-1.5 text-[9px] tracking-wider text-gray-500">AIR QUALITY — OPENAQ</div>
                </div>
              </Popup>
            );
          })()}

        {/* Volcano popup */}
        {selectedEntity?.type === 'volcano' &&
          (() => {
            const idx = parseInt(String(selectedEntity.id).replace('volcano-', ''), 10);
            const volcano = data?.volcanoes?.[idx];
            if (!volcano) return null;
            const now = new Date().getFullYear();
            const yearsAgo = volcano.last_eruption_year ? now - volcano.last_eruption_year : null;
            const accent = yearsAgo !== null && yearsAgo <= 50 ? '#ef4444' : yearsAgo !== null && yearsAgo <= 500 ? '#f97316' : '#6b7280';
            return (
              <Popup longitude={volcano.lng} latitude={volcano.lat} closeButton={false} closeOnClick={false} onClose={() => onEntityClick?.(null)} className="threat-popup" maxWidth="260px">
                <div className="map-popup bg-[#1a1035] min-w-[180px]" style={{ borderColor: `${accent}66` }}>
                  <div className="map-popup-title pb-1" style={{ color: accent, borderBottom: `1px solid ${accent}33` }}>
                    {volcano.name}
                  </div>
                  <div className="map-popup-row">Type: <span className="text-white">{volcano.type}</span></div>
                  <div className="map-popup-row">Country: <span className="text-white">{volcano.country}</span></div>
                  {volcano.region && <div className="map-popup-row">Region: <span className="text-white">{volcano.region}</span></div>}
                  <div className="map-popup-row">Elevation: <span className="text-white">{volcano.elevation?.toLocaleString()}m</span></div>
                  <div className="map-popup-row">Last Eruption: <span className="text-white">{volcano.last_eruption_year || 'Unknown'}</span></div>
                  <div className="mt-1.5 text-[9px] tracking-wider" style={{ color: `${accent}99` }}>
                    VOLCANO — SMITHSONIAN GVP
                  </div>
                </div>
              </Popup>
            );
          })()}

        {/* Fishing Event popup — cross-references with AIS when available */}
        {selectedEntity?.type === 'fishing_event' &&
          (() => {
            const event = data?.fishing_activity?.find((e) => (e.id || '') === selectedEntity.id);
            if (!event) return null;
            // Cross-reference with AIS ships by vessel name
            const vesselNameUpper = (event.vessel_name || '').toUpperCase().trim();
            const aisMatch = vesselNameUpper && data?.ships?.find((s) => {
              const shipName = (s.name || '').toUpperCase().trim();
              return shipName && (shipName === vesselNameUpper || shipName.includes(vesselNameUpper) || vesselNameUpper.includes(shipName));
            });
            return (
              <Popup longitude={event.lng} latitude={event.lat} closeButton={false} closeOnClick={false} onClose={() => onEntityClick?.(null)} className="threat-popup" maxWidth="320px">
                <div className="map-popup bg-[#1a1035] min-w-[220px]" style={{ borderColor: '#0ea5e966' }}>
                  <div className="flex justify-between items-start">
                    <div className="map-popup-title pb-1 flex-1" style={{ color: '#0ea5e9', borderBottom: '1px solid #0ea5e933' }}>
                      {event.vessel_name}
                    </div>
                    <button onClick={() => onEntityClick?.(null)} className="text-[var(--text-secondary)] hover:text-[var(--text-primary)] ml-2 shrink-0">✕</button>
                  </div>
                  <div className="map-popup-row">Flag: <span className="text-white">{event.vessel_flag || 'Unknown'}</span></div>
                  <div className="map-popup-row">Activity: <span className="text-cyan-400 capitalize">{event.type}</span></div>
                  <div className="map-popup-row">Duration: <span className="text-white">{event.duration_hrs}h</span></div>
                  {event.start && <div className="map-popup-row">Start: <span className="text-white">{new Date(event.start).toLocaleDateString()}</span></div>}

                  {/* AIS cross-reference data */}
                  {aisMatch && (
                    <div className="mt-2 pt-2 border-t border-cyan-500/20">
                      <div className="text-[11px] font-mono text-cyan-400 tracking-wider mb-1">AIS CROSS-REFERENCE</div>
                      {aisMatch.mmsi && <div className="map-popup-row">MMSI: <span className="text-white">{aisMatch.mmsi}</span></div>}
                      {aisMatch.callsign && <div className="map-popup-row">Callsign: <span className="text-white">{aisMatch.callsign}</span></div>}
                      {aisMatch.type && <div className="map-popup-row">Vessel Type: <span className="text-cyan-400 uppercase">{aisMatch.type}</span></div>}
                      {aisMatch.destination && <div className="map-popup-row">Destination: <span className="text-cyan-400">{aisMatch.destination}</span></div>}
                      {aisMatch.sog > 0 && <div className="map-popup-row">Speed: <span className="text-white">{aisMatch.sog} kts</span></div>}
                      {aisMatch.cog > 0 && <div className="map-popup-row">Course: <span className="text-white">{Math.round(aisMatch.cog)}°</span></div>}
                      {aisMatch.country && <div className="map-popup-row">Country: <span className="text-white">{aisMatch.country}</span></div>}
                      {aisMatch.imo && <div className="map-popup-row">IMO: <span className="text-white">{aisMatch.imo}</span></div>}
                    </div>
                  )}

                  <div className="mt-1.5 text-[11px] tracking-wider text-gray-500">
                    FISHING — GLOBAL FISHING WATCH
                    {aisMatch && <span className="text-cyan-500"> + AIS</span>}
                  </div>
                </div>
              </Popup>
            );
          })()}

        {/* Fishing vessel → AIS destination route line */}
        {selectedEntity?.type === 'fishing_event' &&
          (() => {
            const event = data?.fishing_activity?.find((e) => (e.id || '') === selectedEntity.id);
            if (!event) return null;
            const vesselNameUpper = (event.vessel_name || '').toUpperCase().trim();
            if (!vesselNameUpper) return null;
            const aisMatch = data?.ships?.find((s) => {
              const shipName = (s.name || '').toUpperCase().trim();
              return shipName && (shipName === vesselNameUpper || shipName.includes(vesselNameUpper) || vesselNameUpper.includes(shipName));
            });
            const dest = aisMatch?.destination;
            if (!dest || dest === 'UNKNOWN') return null;
            return <FishingDestinationRoute vesselLat={event.lat} vesselLng={event.lng} destination={dest} />;
          })()}

        {(() => {
          if (selectedEntity?.type !== 'gdelt' || !data?.gdelt) return null;
          const item = data.gdelt.find(
            (g) => (g.properties?.name || String(g.geometry?.coordinates)) === selectedEntity.id,
          );
          if (!item?.geometry?.coordinates) return null;
          return (
            <Popup
              longitude={item.geometry.coordinates[0]}
              latitude={item.geometry.coordinates[1]}
              closeButton={false}
              closeOnClick={false}
              onClose={() => onEntityClick?.(null)}
              anchor="bottom"
              offset={15}
            >
              <div className="bg-[var(--bg-secondary)]/90 backdrop-blur-md border border-orange-800 rounded-lg flex flex-col z-[100] font-mono shadow-[0_4px_30px_rgba(255,140,0,0.4)] pointer-events-auto overflow-hidden w-[440px]">
                <div className="p-2 border-b border-orange-500/30 bg-orange-950/40 flex justify-between items-center">
                  <h2 className="text-[11px] tracking-widest font-bold text-orange-400 flex items-center gap-1">
                    <AlertTriangle size={13} className="text-orange-400" /> NEWS ON THE GROUND
                  </h2>
                  <button
                    onClick={() => onEntityClick?.(null)}
                    className="text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
                  >
                    ✕
                  </button>
                </div>
                <div className="p-3 flex flex-col gap-2">
                  <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-1">
                    <span className="text-[var(--text-muted)] text-[10px]">LOCATION</span>
                    <span className="text-white text-[12px] font-bold text-right ml-2 break-words max-w-[260px]">
                      {item.properties?.name || 'UNKNOWN REGION'}
                    </span>
                  </div>
                  {/* Enriched GDELT fields */}
                  {item.properties?.event_date && (
                    <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-1">
                      <span className="text-[var(--text-muted)] text-[10px]">DATE</span>
                      <span className="text-white text-[11px] font-bold">
                        {String(item.properties.event_date).replace(/(\d{4})(\d{2})(\d{2})/, '$1-$2-$3')}
                      </span>
                    </div>
                  )}
                  {((item.properties?.actors?.length ?? 0) > 0) && (
                    <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-1">
                      <span className="text-[var(--text-muted)] text-[10px]">ACTORS</span>
                      <span className="text-orange-300 text-[11px] font-bold text-right ml-2 max-w-[280px] truncate">
                        {item.properties.actors!.join(' vs ')}
                      </span>
                    </div>
                  )}
                  {item.properties?.goldstein != null && item.properties.goldstein !== 0 && (
                    <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-1">
                      <span className="text-[var(--text-muted)] text-[10px]">INTENSITY</span>
                      <span className={`text-[11px] font-bold ${item.properties.goldstein <= -5 ? 'text-red-400' : item.properties.goldstein <= -2 ? 'text-orange-400' : 'text-yellow-400'}`}>
                        {item.properties.goldstein > 0 ? '+' : ''}{item.properties.goldstein} Goldstein
                      </span>
                    </div>
                  )}
                  <div className="flex gap-3 border-b border-[var(--border-primary)] pb-1">
                    <div className="flex-1 flex justify-between items-center">
                      <span className="text-[var(--text-muted)] text-[10px]">EVENTS</span>
                      <span className="text-white text-[11px] font-bold">{item.properties?.count || 1}</span>
                    </div>
                    {(item.properties?.num_sources ?? 0) > 0 && (
                      <div className="flex-1 flex justify-between items-center">
                        <span className="text-[var(--text-muted)] text-[10px]">SOURCES</span>
                        <span className="text-white text-[11px] font-bold">{item.properties.num_sources}</span>
                      </div>
                    )}
                    {(item.properties?.num_articles ?? 0) > 0 && (
                      <div className="flex-1 flex justify-between items-center">
                        <span className="text-[var(--text-muted)] text-[10px]">ARTICLES</span>
                        <span className="text-white text-[11px] font-bold">{item.properties.num_articles}</span>
                      </div>
                    )}
                  </div>
                  <div className="flex flex-col gap-1 mt-1">
                    <span className="text-[var(--text-muted)] text-[10px]">
                      LATEST REPORTS: ({(item.properties?._urls_list || []).length})
                    </span>
                    <div className="flex flex-col gap-2 max-h-[320px] overflow-y-auto styled-scrollbar mt-1">
                      {(() => {
                        const urls: string[] = item.properties?._urls_list || [];
                        const headlines: string[] = item.properties?._headlines_list || [];
                        const snippets: string[] = item.properties?._snippets_list || [];
                        if (urls.length === 0)
                          return (
                            <span className="text-[var(--text-muted)] text-[11px]">
                              No articles available.
                            </span>
                          );
                        return urls.map((url: string, idx: number) => {
                          const headline = headlines[idx] || '';
                          const snippet = snippets[idx] || '';
                          let domain = '';
                          try {
                            domain = new URL(url).hostname.replace('www.', '');
                          } catch {
                            domain = '';
                          }
                          return (
                            <a
                              key={idx}
                              href={url}
                              target="_blank"
                              rel="noopener noreferrer"
                              onClick={(e) => e.stopPropagation()}
                              className="block py-2 border-b border-[var(--border-primary)]/50 last:border-0 cursor-pointer group"
                              style={{ pointerEvents: 'all' }}
                            >
                              <span className="text-orange-400 text-[13px] font-bold leading-snug group-hover:text-orange-300 block">
                                {headline || domain || 'View Article'}
                              </span>
                              {snippet && (
                                <span className="text-[var(--text-secondary)] text-[11px] leading-relaxed block mt-1">
                                  {snippet}
                                </span>
                              )}
                              {domain && (
                                <span className="text-[var(--text-muted)] text-[10px] block mt-1">
                                  {domain}
                                </span>
                              )}
                            </a>
                          );
                        });
                      })()}
                    </div>
                  </div>
                </div>
              </div>
            </Popup>
          );
        })()}

        {selectedEntity?.type === 'liveuamap' &&
          data?.liveuamap?.find((l) => String(l.id) === String(selectedEntity.id)) &&
          (() => {
            const item = data.liveuamap.find((l) => String(l.id) === String(selectedEntity.id));
            if (!item) return null;
            return (
              <Popup
                longitude={item.lng}
                latitude={item.lat}
                closeButton={false}
                closeOnClick={false}
                onClose={() => onEntityClick?.(null)}
                anchor="bottom"
                offset={15}
              >
                <div className="bg-[var(--bg-secondary)]/90 backdrop-blur-md border border-yellow-800 rounded-lg flex flex-col z-[100] font-mono shadow-[0_4px_30px_rgba(255,255,0,0.3)] pointer-events-auto overflow-hidden w-[280px]">
                  <div className="p-2 border-b border-yellow-500/30 bg-yellow-950/40 flex justify-between items-center">
                    <h2 className="text-[10px] tracking-widest font-bold text-yellow-400 flex items-center gap-1">
                      <AlertTriangle size={12} className="text-yellow-400" /> REGIONAL TACTICAL
                      EVENT
                    </h2>
                    <button
                      onClick={() => onEntityClick?.(null)}
                      className="text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
                    >
                      ✕
                    </button>
                  </div>
                  <div className="p-3 flex flex-col gap-2">
                    <div className="flex flex-col gap-1 border-b border-[var(--border-primary)] pb-1">
                      <span className="text-yellow-400 text-[10px] font-bold leading-tight">
                        {item.title}
                      </span>
                    </div>
                    {item.description && (
                      <div className="text-[9px] text-white/70 leading-relaxed border-b border-[var(--border-primary)] pb-1.5">
                        {item.description}
                      </div>
                    )}
                    <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-1">
                      <span className="text-[var(--text-muted)] text-[9px]">REGION</span>
                      <span className="text-white text-[9px] font-bold">{item.region || 'Unknown'}</span>
                    </div>
                    <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-1">
                      <span className="text-[var(--text-muted)] text-[9px]">TIME</span>
                      <span className="text-white text-[9px] font-bold">
                        {item.date || (item.timestamp ? new Date(Number(item.timestamp) * 1000).toLocaleString() : 'UNKNOWN')}
                      </span>
                    </div>
                    {item.category && (
                      <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-1">
                        <span className="text-[var(--text-muted)] text-[9px]">TYPE</span>
                        <span className="text-yellow-300 text-[9px] font-bold">{item.category}</span>
                      </div>
                    )}
                    {item.source && (
                      <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-1">
                        <span className="text-[var(--text-muted)] text-[9px]">SOURCE</span>
                        <span className="text-white/60 text-[9px]">{item.source}</span>
                      </div>
                    )}
                    {item.link && (
                      <div className="flex justify-between items-center mt-1">
                        <a
                          href={item.link}
                          target="_blank"
                          rel="noreferrer"
                          className="text-yellow-400 hover:text-yellow-300 text-[9px] font-bold underline"
                        >
                          View Source Report
                        </a>
                      </div>
                    )}
                    {oracleIntel?.found && (
                      <div className="mt-2 pt-2 border-t border-cyan-500/20">
                        <div className="text-[11px] font-mono text-cyan-400 tracking-wider mb-1">ORACLE INTEL</div>
                        <div className="text-[11px] font-mono text-cyan-300/80">
                          <span className={oracleIntel.tier === 'CRITICAL' ? 'text-red-400' : oracleIntel.tier === 'ELEVATED' ? 'text-yellow-400' : 'text-green-400'}>
                            {oracleIntel.tier}
                          </span>
                          {' // '}
                          <span className={oracleIntel.avg_sentiment != null && oracleIntel.avg_sentiment < -0.05 ? 'text-red-400' : 'text-gray-400'}>
                            {oracleIntel.avg_sentiment != null ? `${oracleIntel.avg_sentiment > 0 ? '+' : ''}${oracleIntel.avg_sentiment.toFixed(2)} SENT` : ''}
                          </span>
                          {oracleIntel.market && (
                            <span className="text-purple-400">{' // '}{oracleIntel.market.consensus_pct}%</span>
                          )}
                        </div>
                        {oracleIntel.top_headline && (
                          <div className="text-[10px] text-white/60 mt-0.5 truncate">{oracleIntel.top_headline}</div>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              </Popup>
            );
          })()}

        {/* ── THREAT INTERCEPT — fullscreen intelligence dossier modal ── */}
        {(() => {
          if (selectedEntity?.type !== 'news' || !data?.news) return null;
          const item = data.news.find((n: any) => {
            const key = (n as any).alertKey || `${n.title}|${n.coords?.[0]},${n.coords?.[1]}`;
            return key === selectedEntity.id;
          }) as any;
          if (!item) return null;

          const rs = item.risk_score ?? 0;
          let threatHex = '#eab308';
          let threatColor = 'text-yellow-400';
          let borderColor = 'border-yellow-800';
          let bgHeaderColor = 'bg-yellow-950/50';
          if (rs >= 8) {
            threatHex = '#ef4444'; threatColor = 'text-red-400'; borderColor = 'border-red-700'; bgHeaderColor = 'bg-red-950/50';
          } else if (rs <= 4) {
            threatHex = '#22c55e'; threatColor = 'text-green-400'; borderColor = 'border-green-800'; bgHeaderColor = 'bg-green-950/50';
          }

          const sent = item.sentiment as number | undefined;
          const oScore = item.oracle_score as number | undefined;
          const oTier = oScore != null ? (oScore >= 8 ? 'CRITICAL' : oScore >= 6 ? 'ELEVATED' : oScore >= 4 ? 'MODERATE' : 'LOW') : null;
          const oTierColor = oScore != null ? (oScore >= 8 ? 'text-red-400' : oScore >= 6 ? 'text-orange-400' : oScore >= 4 ? 'text-yellow-400' : 'text-green-400') : '';
          const oTierBg = oScore != null ? (oScore >= 8 ? 'bg-red-500/10 border-red-500/30' : oScore >= 6 ? 'bg-orange-500/10 border-orange-500/30' : oScore >= 4 ? 'bg-yellow-500/10 border-yellow-500/30' : 'bg-green-500/10 border-green-500/30') : '';
          const sentColor = sent != null ? (sent < -0.1 ? 'text-red-400' : sent > 0.1 ? 'text-green-400' : 'text-gray-400') : '';
          const sentBg = sent != null ? (sent < -0.1 ? 'bg-red-500/10 border-red-500/30' : sent > 0.1 ? 'bg-green-500/10 border-green-500/30' : 'bg-gray-500/10 border-gray-500/30') : '';
          const sentArrow = sent != null ? (sent < -0.1 ? '▼' : sent > 0.1 ? '▲' : '—') : '';
          const sentLabel = sent != null ? (sent < -0.1 ? 'NEGATIVE' : sent > 0.1 ? 'POSITIVE' : 'NEUTRAL') : '';
          const pred = item.prediction_odds as any;
          const articles = (item.articles as any[]) || [];
          const clusterCount = (item.cluster_count as number) || 1;
          const isBreaking = item.breaking === true;

          return (
            <div
              style={{
                position: 'fixed',
                top: 0, left: 0, right: 0, bottom: 0,
                zIndex: 9999,
                background: 'rgba(0,0,0,0.88)',
                backdropFilter: 'blur(12px)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                padding: '40px 20px',
              }}
              onClick={(e) => { if (e.target === e.currentTarget) onEntityClick?.(null); }}
              onKeyDown={(e: React.KeyboardEvent<HTMLDivElement>) => { if (e.key === 'Escape') onEntityClick?.(null); }}
              tabIndex={-1}
              ref={(el) => el?.focus()}
            >
              <div
                className={`bg-[#080c12] border ${borderColor} rounded-lg flex flex-col font-mono overflow-hidden`}
                style={{
                  width: 'min(700px, calc(100vw - 40px))',
                  maxHeight: 'calc(100vh - 80px)',
                  boxShadow: `0 0 80px ${threatHex}33, 0 0 200px ${threatHex}11, inset 0 1px 0 rgba(255,255,255,0.05)`,
                }}
              >
                {/* ══════ HEADER ══════ */}
                <div className={`px-5 py-3 border-b ${borderColor}/60 ${bgHeaderColor} flex justify-between items-center shrink-0`}>
                  <div className="flex items-center gap-3">
                    <AlertTriangle size={18} className={threatColor} />
                    <span className={`text-[14px] tracking-[0.25em] font-bold ${threatColor}`}>
                      {isBreaking ? 'BREAKING INTERCEPT' : 'THREAT INTERCEPT'}
                    </span>
                    {isBreaking && <span className="text-[9px] bg-red-500 text-white px-2 py-0.5 rounded-sm font-bold animate-pulse">LIVE</span>}
                  </div>
                  <div className="flex items-center gap-3">
                    <span className={`text-[14px] ${threatColor} font-bold ${rs >= 8 ? 'animate-pulse' : ''}`}>
                      ALERT LVL: {rs}/10
                    </span>
                    <button
                      onClick={() => onEntityClick?.(null)}
                      className="text-[var(--text-secondary)] hover:text-white text-xl leading-none px-1 hover:bg-white/10 rounded transition-colors"
                    >
                      ✕
                    </button>
                  </div>
                </div>

                {/* ══════ SCROLLABLE BODY ══════ */}
                <div className="overflow-y-auto styled-scrollbar flex flex-col flex-1">

                  {/* ── HEADLINE ── */}
                  <div className="px-5 pt-4 pb-3">
                    <h2 className={`text-[18px] font-bold leading-snug ${threatColor}`}>
                      {item.title}
                    </h2>
                    <div className="flex items-center gap-3 mt-2 text-[11px] text-[var(--text-muted)]">
                      <span className="text-white font-bold text-[12px]">{item.source || 'UNKNOWN'}</span>
                      {item.published && <span>• {item.published}</span>}
                      {clusterCount > 1 && <span className="text-cyan-400 font-bold">• {clusterCount} SOURCES REPORTING</span>}
                      {item.coords && (
                        <span className="ml-auto text-[10px] font-mono text-[var(--text-muted)]">
                          {item.coords[0].toFixed(3)}°, {item.coords[1].toFixed(3)}°
                        </span>
                      )}
                    </div>
                  </div>

                  {/* ── INTEL GRID: Oracle + Sentiment + Risk ── */}
                  <div className="px-5 pb-3">
                    <div className="grid grid-cols-3 gap-2">
                      {/* Oracle Score */}
                      <div className={`border rounded p-3 text-center ${oTierBg || 'bg-black/40 border-cyan-800/30'}`}>
                        <div className="text-[9px] text-[var(--text-muted)] tracking-[0.15em] mb-1.5">ORACLE SCORE</div>
                        <div className={`text-[28px] font-bold leading-none ${oTierColor || 'text-gray-500'}`}>
                          {oScore != null ? oScore.toFixed(1) : '—'}
                        </div>
                        {oTier && <div className={`text-[10px] font-bold ${oTierColor} mt-1`}>{oTier}</div>}
                      </div>
                      {/* Sentiment */}
                      <div className={`border rounded p-3 text-center ${sentBg || 'bg-black/40 border-cyan-800/30'}`}>
                        <div className="text-[9px] text-[var(--text-muted)] tracking-[0.15em] mb-1.5">SENTIMENT</div>
                        <div className={`text-[28px] font-bold leading-none ${sentColor || 'text-gray-500'}`}>
                          {sent != null ? <>{sentArrow} {sent > 0 ? '+' : ''}{sent.toFixed(2)}</> : '—'}
                        </div>
                        {sentLabel && <div className={`text-[10px] font-bold ${sentColor} mt-1`}>{sentLabel}</div>}
                      </div>
                      {/* Threat Level */}
                      <div className={`border rounded p-3 text-center ${rs >= 8 ? 'bg-red-500/10 border-red-500/30' : rs >= 6 ? 'bg-orange-500/10 border-orange-500/30' : rs >= 4 ? 'bg-yellow-500/10 border-yellow-500/30' : 'bg-green-500/10 border-green-500/30'}`}>
                        <div className="text-[9px] text-[var(--text-muted)] tracking-[0.15em] mb-1.5">RISK LEVEL</div>
                        <div className={`text-[28px] font-bold leading-none ${threatColor}`}>{rs}/10</div>
                        <div className={`text-[10px] font-bold ${threatColor} mt-1`}>
                          {rs >= 9 ? 'CRITICAL' : rs >= 7 ? 'HIGH' : rs >= 4 ? 'MEDIUM' : 'LOW'}
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* ── PREDICTION MARKET ANALYSIS ── */}
                  {pred && pred.consensus_pct != null && (
                    <div className="px-5 pb-3">
                      <div className="bg-purple-950/30 border border-purple-500/40 rounded p-4">
                        <div className="text-[10px] text-purple-400 tracking-[0.2em] font-bold mb-2">
                          PREDICTION MARKET ANALYSIS
                        </div>
                        <div className="text-[14px] text-purple-200 font-bold leading-snug mb-3">
                          &quot;{pred.title}&quot;
                        </div>
                        {/* Progress bar */}
                        <div className="bg-black/50 rounded overflow-hidden h-8 relative border border-purple-500/20 mb-3">
                          <div
                            className="h-full bg-gradient-to-r from-purple-700 to-purple-400 transition-all"
                            style={{ width: `${pred.consensus_pct}%` }}
                          />
                          <span className="absolute inset-0 flex items-center justify-center text-[14px] font-bold text-white drop-shadow-lg">
                            {pred.consensus_pct}% CONSENSUS PROBABILITY
                          </span>
                        </div>
                        <div className="flex gap-6 text-[11px]">
                          {pred.polymarket_pct != null && (
                            <div className="flex items-center gap-2">
                              <span className="text-purple-400/70">Polymarket</span>
                              <span className="text-white font-bold text-[13px]">{pred.polymarket_pct}%</span>
                            </div>
                          )}
                          {pred.kalshi_pct != null && (
                            <div className="flex items-center gap-2">
                              <span className="text-purple-400/70">Kalshi</span>
                              <span className="text-white font-bold text-[13px]">{pred.kalshi_pct}%</span>
                            </div>
                          )}
                          {pred.match_score != null && (
                            <span className="text-purple-400/40 ml-auto text-[10px]">headline match: {(pred.match_score * 100).toFixed(0)}%</span>
                          )}
                        </div>
                      </div>
                    </div>
                  )}

                  {/* ── SYS.ANALYSIS ── */}
                  {item.machine_assessment && (
                    <div className="px-5 pb-3">
                      <div className="p-3 bg-black/60 border border-cyan-800/50 rounded text-[11px] text-cyan-400 font-mono leading-relaxed relative overflow-hidden">
                        <div className="absolute top-0 left-0 w-[3px] h-full bg-cyan-500 animate-pulse"></div>
                        <span className="font-bold text-white text-[12px]">&gt;_ SYS.ANALYSIS: </span>
                        <span className="text-cyan-300 opacity-90">{item.machine_assessment}</span>
                      </div>
                    </div>
                  )}

                  {/* ── CORROBORATING SOURCES ── */}
                  {articles.length > 1 && (
                    <div className="px-5 pb-3">
                      <div className="text-[10px] text-[var(--text-muted)] tracking-[0.2em] font-bold mb-2">
                        CORROBORATING SOURCES ({articles.length})
                      </div>
                      <div className="flex flex-col gap-1.5">
                        {articles.map((sub: any, si: number) => {
                          const subRs = sub.risk_score ?? 0;
                          const subColor = subRs >= 8 ? 'text-red-400' : subRs >= 6 ? 'text-orange-400' : subRs >= 4 ? 'text-yellow-400' : 'text-green-400';
                          return (
                            <div
                              key={si}
                              role="button"
                              tabIndex={0}
                              onClick={() => sub.link && window.open(sub.link, '_blank', 'noopener,noreferrer')}
                              onKeyDown={(e) => { if (e.key === 'Enter' && sub.link) window.open(sub.link, '_blank', 'noopener,noreferrer'); }}
                              className="flex items-start gap-3 py-2 px-3 border-l-2 border-cyan-800/40 bg-black/30 rounded-r hover:bg-cyan-950/30 transition-colors group cursor-pointer"
                            >
                              <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-2 text-[10px]">
                                  <span className="text-white font-bold">{sub.source}</span>
                                  <span className={`${subColor} font-bold`}>LVL: {subRs}/10</span>
                                  {sub.published && <span className="text-[var(--text-muted)] text-[9px]">{sub.published}</span>}
                                </div>
                                <div className="text-[11px] text-[var(--text-secondary)] leading-snug mt-0.5 group-hover:text-cyan-300 transition-colors">
                                  {sub.title}
                                </div>
                              </div>
                              <span className="text-[11px] text-cyan-500 group-hover:text-cyan-300 shrink-0 mt-1">↗</span>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}

                  {/* ── FOOTER ── */}
                  <div className="px-5 py-3 flex justify-between items-center border-t border-[var(--border-primary)] mt-auto shrink-0">
                    {item.link ? (
                      <button
                        onClick={() => window.open(item.link, '_blank', 'noopener,noreferrer')}
                        className={`${threatColor} hover:text-white text-[12px] font-bold underline underline-offset-2 cursor-pointer`}
                      >
                        VIEW FULL REPORT ↗
                      </button>
                    ) : <span />}
                    <button
                      onClick={() => onEntityClick?.(null)}
                      className="text-[11px] text-[var(--text-muted)] hover:text-white border border-[var(--border-primary)] hover:border-white/30 px-3 py-1 rounded transition-colors"
                    >
                      CLOSE DOSSIER
                    </button>
                  </div>
                </div>
              </div>
            </div>
          );
        })()}

        {/* REGION DOSSIER — location pin on map (full intel shown in right panel) */}
        {selectedEntity?.type === 'region_dossier' && selectedEntity.extra && (
          <Marker
            longitude={selectedEntity.extra.lng}
            latitude={selectedEntity.extra.lat}
            anchor="bottom"
            style={{ zIndex: 10 }}
          >
            <div className="flex flex-col items-center pointer-events-none">
              {/* Pulsing ring */}
              <div className="w-8 h-8 rounded-full border-2 border-emerald-500 animate-ping absolute opacity-30" />
              {/* Pin dot */}
              <div className="w-4 h-4 rounded-full bg-emerald-500 border-2 border-emerald-300 shadow-[0_0_15px_rgba(16,185,129,0.6)]" />
              {/* Label */}
              <div className="mt-2 bg-black/80 border border-emerald-800 rounded px-2 py-1 text-[9px] font-mono text-emerald-400 tracking-widest whitespace-nowrap shadow-[0_0_10px_rgba(16,185,129,0.3)]">
                {regionDossierLoading ? 'COMPILING...' : '▶ INTEL TARGET'}
              </div>
            </div>
          </Marker>
        )}

        {/* SENTINEL-2 IMAGERY — fullscreen overlay modal */}
        {selectedEntity?.type === 'region_dossier' &&
          selectedEntity.extra &&
          regionDossier?.sentinel2 && (
            <RegionDossierPanel
              sentinel2={regionDossier.sentinel2}
              lat={selectedEntity.extra.lat}
              lng={selectedEntity.extra.lng}
              onClose={() => onEntityClick(null)}
            />
          )}

        {/* OPTIC INTERCEPT — fullscreen CCTV camera modal */}
        {selectedEntity?.type === 'cctv' &&
          (() => {
            const props = (selectedEntity.extra || {}) as Record<string, unknown>;
            const rawUrl = String(selectedEntity.media_url || props.media_url || '');
            const mt = String(props.media_type || (
              rawUrl.includes('.mp4') || rawUrl.includes('.webm') ? 'video' :
                rawUrl.includes('.m3u8') || rawUrl.includes('hls') ? 'hls' :
                  rawUrl.includes('.mjpg') || rawUrl.includes('.mjpeg') || rawUrl.includes('mjpg') ? 'mjpeg' : 'image'
            ));
            // Proxy external URLs through backend to bypass CORS
            const url = buildCctvProxyUrl(rawUrl);
            const isVideo = mt === 'video' || mt === 'hls';
            const cameraName = String(selectedEntity.name || props.name || 'UNKNOWN MOUNT').toUpperCase();
            const sourceAgency = String(props.source_agency || 'CCTV').toUpperCase();

            return (
              <CctvFullscreenModal
                url={url}
                mediaType={mt}
                isVideo={isVideo}
                cameraName={cameraName}
                sourceAgency={sourceAgency}
                cameraId={String(selectedEntity.id || '')}
                onClose={() => onEntityClick(null)}
              />
            );
          })()}

        {/* ── AI Intel Pin Detail popup ── */}
        {openPinDetailId && (
          <AIIntelPinDetail
            pinId={openPinDetailId}
            onClose={() => setOpenPinDetailId(null)}
            onDeleted={() => {
              setOpenPinDetailId(null);
              setAiIntelRefreshTick((t) => t + 1);
              onPinPlaced?.();
            }}
            onUpdated={() => setAiIntelRefreshTick((t) => t + 1)}
          />
        )}

        {/* ── Pin Placement Dialog (offset marker + connecting line) ── */}
        {pendingPin && (
          <Marker
            latitude={pendingPin.lat}
            longitude={pendingPin.lng}
            anchor="center"
            offset={[0, -120]}
            style={{ zIndex: 9990 }}
          >
            <div
              className="relative"
              onClick={(e) => e.stopPropagation()}
              onMouseDown={(e) => e.stopPropagation()}
              onKeyDown={(e) => {
                // Prevent global hotkeys (l/r/m/s/k/f/space) from firing while
                // typing in the pin dialog — the maplibre canvas is still in
                // the document and document-level listeners otherwise fire.
                e.stopPropagation();
                e.nativeEvent.stopImmediatePropagation();
              }}
              onKeyUp={(e) => {
                e.stopPropagation();
                e.nativeEvent.stopImmediatePropagation();
              }}
            >
              {/* Connecting line + dot at actual pin location */}
              <svg
                className="absolute pointer-events-none"
                style={{
                  left: '50%',
                  top: '50%',
                  width: 1,
                  height: 1,
                  overflow: 'visible',
                  zIndex: -1,
                }}
              >
                <line
                  x1={0}
                  y1={0}
                  x2={0}
                  y2={120}
                  stroke="#8b5cf6"
                  strokeWidth="1.5"
                  strokeDasharray="4,3"
                  className="opacity-80"
                />
                <circle cx={0} cy={120} r="4" fill="#8b5cf6" stroke="#0a0a14" strokeWidth="1.5" />
              </svg>

              {/* Arrow triangle pointing down to pin */}
              <div
                style={{
                  position: 'absolute',
                  bottom: '-6px',
                  left: '50%',
                  transform: 'translateX(-50%)',
                  width: 0,
                  height: 0,
                  borderLeft: '6px solid transparent',
                  borderRight: '6px solid transparent',
                  borderTop: '6px solid #8b5cf6',
                }}
              />

              {/* Dialog box */}
              <div
                className="bg-[#0a0a14] border-2 border-violet-500/60 p-3 font-mono"
                style={{ minWidth: 260, maxWidth: 300, transform: 'translateX(-50%)', marginLeft: '50%' }}
              >
                {/* Close button */}
                <button
                  onClick={() => { setPendingPin(null); setPinLabel(''); setPinNotes(''); }}
                  style={{
                    position: 'absolute',
                    top: 4,
                    right: 8,
                    background: 'transparent',
                    border: 'none',
                    cursor: 'pointer',
                    color: '#8b5cf6',
                    fontSize: 16,
                    fontWeight: 'bold',
                    lineHeight: 1,
                    opacity: 0.7,
                    zIndex: 20,
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.opacity = '1')}
                  onMouseLeave={(e) => (e.currentTarget.style.opacity = '0.7')}
                >
                  &times;
                </button>

                <div className="text-[12px] text-violet-400 tracking-widest mb-2 font-bold">
                  {pendingPin.entity ? 'PIN TO ENTITY' : 'PIN TO LOCATION'}
                </div>
                {pendingPin.entity && (
                  <div className="text-[10px] text-cyan-400 mb-2 px-2 py-1 bg-cyan-500/10 border border-cyan-500/20">
                    Tracking: {pendingPin.entity.entity_label || pendingPin.entity.entity_id}
                    <span className="text-cyan-600 ml-1">({pendingPin.entity.entity_type})</span>
                  </div>
                )}
                {/* Category selector */}
                <select
                  title="Pin category"
                  aria-label="Pin category"
                  value={pinCategory}
                  onChange={(e) => setPinCategory(e.target.value as PinCategory)}
                  className="w-full px-2 py-1.5 text-[11px] font-mono bg-black/50 border border-violet-500/30 text-white focus:border-violet-500/60 outline-none mb-1.5 border-l-4"
                  style={{ borderLeftColor: PIN_CATEGORY_COLORS[pinCategory] }}
                >
                  {(Object.keys(PIN_CATEGORY_LABELS) as PinCategory[]).map((cat) => (
                    <option key={cat} value={cat} className="bg-[#0a0a14]">
                      {PIN_CATEGORY_LABELS[cat]}
                    </option>
                  ))}
                </select>
                <input
                  ref={pinLabelInputRef}
                  type="text"
                  value={pinLabel}
                  onChange={(e) => setPinLabel(e.target.value)}
                  placeholder="Label..."
                  autoFocus
                  className="w-full px-2 py-1.5 text-[12px] font-mono bg-black/50 border border-violet-500/30 text-white placeholder:text-gray-600 focus:border-violet-500/60 outline-none mb-1.5"
                  onKeyDown={(e) => {
                    e.stopPropagation();
                    e.nativeEvent.stopImmediatePropagation();
                    if (e.key === 'Enter' && pinLabel.trim()) {
                      e.preventDefault();
                      handleSavePin();
                    }
                    if (e.key === 'Escape') {
                      setPendingPin(null); setPinLabel(''); setPinNotes(''); setPinCategory('custom');
                    }
                  }}
                />
                <textarea
                  value={pinNotes}
                  onChange={(e) => setPinNotes(e.target.value)}
                  placeholder="Notes (optional)..."
                  rows={2}
                  className="w-full px-2 py-1 text-[11px] font-mono bg-black/50 border border-violet-500/20 text-gray-300 placeholder:text-gray-600 focus:border-violet-500/40 outline-none resize-none mb-2"
                  onMouseDown={(e) => {
                    // Force-focus the textarea on click — the maplibre canvas
                    // otherwise steals focus back and typing gets swallowed.
                    e.stopPropagation();
                    (e.currentTarget as HTMLTextAreaElement).focus();
                  }}
                  onClick={(e) => {
                    e.stopPropagation();
                    (e.currentTarget as HTMLTextAreaElement).focus();
                  }}
                  onKeyDown={(e) => {
                    e.stopPropagation();
                    e.nativeEvent.stopImmediatePropagation();
                    if (e.key === 'Escape') {
                      setPendingPin(null); setPinLabel(''); setPinNotes(''); setPinCategory('custom');
                    }
                  }}
                />
                <div className="text-[9px] text-gray-500 mb-2">
                  {pendingPin.lat.toFixed(5)}, {pendingPin.lng.toFixed(5)}
                </div>
                <div className="flex gap-1.5">
                  <button
                    type="button"
                    disabled={!pinLabel.trim() || pinSaving}
                    onClick={handleSavePin}
                    className="flex-1 py-1.5 text-[11px] font-mono tracking-wider bg-violet-600/30 border border-violet-500/50 text-violet-300 hover:bg-violet-600/50 transition-colors disabled:opacity-40"
                  >
                    {pinSaving ? '...' : 'CONFIRM'}
                  </button>
                  <button
                    type="button"
                    onClick={() => { setPendingPin(null); setPinLabel(''); setPinNotes(''); }}
                    className="px-3 py-1.5 text-[11px] font-mono tracking-wider border border-gray-600/40 text-gray-400 hover:text-gray-300 transition-colors"
                  >
                    CANCEL
                  </button>
                </div>
              </div>
            </div>
          </Marker>
        )}

        <MeasurementLayers measurePoints={measurePoints} />
      </Map>
    </div>
  );
};

import dynamic from 'next/dynamic';

export default dynamic(() => Promise.resolve(MaplibreViewer), {
  ssr: false,
});
