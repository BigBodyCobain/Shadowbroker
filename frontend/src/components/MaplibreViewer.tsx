'use client';
import type * as GeoJSON from 'geojson';

import { API_BASE } from '@/lib/api';
import { articleSourceUrl } from '@/lib/newsArticles';
import { clampZoom, ZOOM_MAX, ZOOM_FALLBACK } from '@/lib/mapZoom';
import { useMemo, useState, useEffect, useCallback, useRef } from 'react';
import Map, {
  Source,
  Layer,
  MapRef,
  ViewState,
 
 
  MapLayerMouseEvent,
  AttributionControl } from 'react-map-gl/maplibre';
import 'maplibre-gl/dist/maplibre-gl.css';
import { createPortal } from 'react-dom';

/** One consistent, local-time format for feed timestamps (sources mix GMT / +0000 / ISO). */
function formatDossierTime(raw: unknown): string {
  const text = String(raw ?? '');
  const d = new Date(text);
  if (Number.isNaN(d.getTime())) return text;
  return d.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}
import { computeNightPolygon } from '@/utils/solarTerminator';
import {
  buildBasemapStyle,
  applyBasemapPalette,
  CARTO_ATTRIBUTION_HTML,
  OPENFREEMAP_ATTRIBUTION_HTML,
  OSM_ATTRIBUTION_HTML } from '@/components/map/styles/mapStyles';
import { useBasemapConfig } from '@/hooks/useBasemapConfig';
import * as maplibregl from 'maplibre-gl';
maplibregl.setWorkerUrl('/maplibre-gl-worker.mjs');
import { AlertTriangle, Radio, Activity, Play, Satellite, ExternalLink, Info } from 'lucide-react';
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
  CT_ICON_SPECS } from '@/components/map/icons/AircraftIcons';
import { makeSatSvg, makeISSSvg, makeTrainSvg } from '@/components/map/icons/SatelliteIcons';
import { makeUfoSvg, makeUfoClusterSvg, makeWaterDropSvg, makeWaterDropClusterSvg } from '@/components/map/icons/OverlayIcons';
import { EMPTY_FC } from '@/components/map/mapConstants';
import { useMapImperativeSources } from '@/components/map/hooks/useMapImperativeSources';
import { useMapPins } from '@/components/map/useMapPins';
import { useMapControlRequests } from '@/components/map/hooks/useMapControlRequests';
import { useMapCoreGeoJson } from '@/components/map/useMapCoreGeoJson';
import { useMapAlertGeoJson } from '@/components/map/useMapAlertGeoJson';
import { useMapTrackedSatGeoJson } from '@/components/map/useMapTrackedSatGeoJson';
import { useMapLabelData, useMapCarrierData } from '@/components/map/useMapLabelData';
import { useMapSarData } from '@/components/map/useMapSarData';
import { useSelectedEntityTrail } from '@/components/map/hooks/useSelectedEntityTrail';
import { registerMapImages } from '@/components/map/registerMapImages';
import { useDynamicMapLayersWorker } from '@/components/map/hooks/useDynamicMapLayersWorker';
import { useStaticMapLayersWorker } from '@/components/map/hooks/useStaticMapLayersWorker';
import { applyDynamicLayerInterp } from '@/components/map/applyDynamicLayerInterp';
import { filterShipsByActiveFilters } from '@/components/map/shipFilters';
import { shipsWithIcons, trackedFlightsWithIcons } from '@/components/map/labelSubjects';
import {
  ClusterCountLabels,
  TrackedFlightLabels,
  CarrierLabels,
  TrackedYachtLabels,
  UavLabels,
  EarthquakeLabels,
  ThreatMarkers,
  LabelDeclutter,
  TelegramOsintMarkers } from '@/components/map/MapMarkers';
import type { DashboardData, Flight, KiwiSDR, MaplibreViewerProps, Scanner, Ship, SigintSignal } from '@/types/dashboard';
import { useDataKeys } from '@/hooks/useDataStore';
import { emitViewState, onRequest as onMapControlRequest } from '@/lib/mapControlBus';
import { useInterpolation } from '@/components/map/hooks/useInterpolation';
import { useClusterLabels } from '@/components/map/hooks/useClusterLabels';
import { spreadAlertItems } from '@/utils/alertSpread';
import {
  applyTelegramAlertAvoidance,
  telegramClusterKey,
  telegramClusterNearNewsAlert,
  telegramMapPinCoords } from '@/components/map/geoJSONBuilders';

import { useViewportBounds } from '@/components/map/hooks/useViewportBounds';
import { getLiveDataBounds } from '@/lib/liveDataViewport';
import { MeasurementLayers } from '@/components/map/layers/MeasurementLayers';
import { FirmsFireLayers } from '@/components/map/layers/FirmsFireLayers';
import { DayNightLayers } from '@/components/map/layers/DayNightLayers';
import { GpsJammingLayers } from '@/components/map/layers/GpsJammingLayers';
import { GtRiskLayers } from '@/components/map/layers/GtRiskLayers';
import { CorrelationLayers } from '@/components/map/layers/CorrelationLayers';
import { VolcanoLayers } from '@/components/map/layers/VolcanoLayers';
import { UapSightingsLayers } from '@/components/map/layers/UapSightingsLayers';
import { WastewaterLayers } from '@/components/map/layers/WastewaterLayers';
import { CrowdThreatLayers } from '@/components/map/layers/CrowdThreatLayers';
import { TelegramOsintLayers } from '@/components/map/layers/TelegramOsintLayers';
import { MalwareLayers } from '@/components/map/layers/MalwareLayers';
import { SubmarineCablesLayers } from '@/components/map/layers/SubmarineCablesLayers';
import { CarriersLayers } from '@/components/map/layers/CarriersLayers';
import { FlightCategoryLayers } from '@/components/map/layers/FlightCategoryLayers';
import { ActiveRouteLayers } from '@/components/map/layers/ActiveRouteLayers';
import { FlightTrailLayers } from '@/components/map/layers/FlightTrailLayers';
import { PredictivePathLayers } from '@/components/map/layers/PredictivePathLayers';
import { ProximityRingsLayers } from '@/components/map/layers/ProximityRingsLayers';
import { GdeltLayers } from '@/components/map/layers/GdeltLayers';
import { LiveuamapLayers } from '@/components/map/layers/LiveuamapLayers';
import { TrackedFlightsLayers } from '@/components/map/layers/TrackedFlightsLayers';
import { UavsLayers } from '@/components/map/layers/UavsLayers';
import { SatellitesLayers } from '@/components/map/layers/SatellitesLayers';
import { TrainsLayers } from '@/components/map/layers/TrainsLayers';
import { FrontlinesLayer } from '@/components/map/layers/FrontlinesLayer';
import { EarthquakesLayers } from '@/components/map/layers/EarthquakesLayers';
import { CctvLayers } from '@/components/map/layers/CctvLayers';
import { KiwiSdrLayers } from '@/components/map/layers/KiwiSdrLayers';
import { PskReporterLayers } from '@/components/map/layers/PskReporterLayers';
import { SatnogsLayers } from '@/components/map/layers/SatnogsLayers';
import { TinyGSLayers } from '@/components/map/layers/TinyGSLayers';
import { InternetOutagesLayers } from '@/components/map/layers/InternetOutagesLayers';
import { PowerPlantsLayers } from '@/components/map/layers/PowerPlantsLayers';
import { ViirsChangeNodesLayers } from '@/components/map/layers/ViirsChangeNodesLayers';
import { SarAoisLayers } from '@/components/map/layers/SarAoisLayers';
import { SarAnomaliesLayers } from '@/components/map/layers/SarAnomaliesLayers';
import { ShodanOverlayLayer } from '@/components/map/layers/ShodanOverlayLayer';
import { MilitaryBasesLayers } from '@/components/map/layers/MilitaryBasesLayers';
import { UkraineAlertsLayers } from '@/components/map/layers/UkraineAlertsLayers';
import { WeatherAlertsLayers } from '@/components/map/layers/WeatherAlertsLayers';
import { AirQualityLayers } from '@/components/map/layers/AirQualityLayers';
import { MapEntityPopups } from '@/components/map/MapEntityPopups';
import { sameEntityId } from '@/components/map/featureIds';
import { buildCctvProxyUrl } from '@/lib/cctvProxy';
import { sanitizeSubmarineCables } from '@/lib/submarineCables';
import { CctvFullscreenModal } from '@/components/MaplibreViewer/CctvFullscreenModal';
import { SatellitePopup } from '@/components/MaplibreViewer/popups/SatellitePopup';
import { ShipPopup } from '@/components/MaplibreViewer/popups/ShipPopup';
import { SigintPopup } from '@/components/MaplibreViewer/popups/SigintPopup';
import { CorrelationPopup } from '@/components/MaplibreViewer/popups/CorrelationPopup';
import { WastewaterPopup } from '@/components/MaplibreViewer/popups/WastewaterPopup';
import { MilitaryBasePopup } from '@/components/MaplibreViewer/popups/MilitaryBasePopup';
import { RegionDossierPanel } from '@/components/MaplibreViewer/popups/RegionDossierPanel';
import { GtRiskPopup } from '@/components/MaplibreViewer/popups/GtRiskPopup';
import { TelegramOsintPopup } from '@/components/MaplibreViewer/popups/TelegramOsintPopup';
import {
  buildSentinelTileUrl,
  hasSentinelCredentials,
  getSentinelToken,
  registerSentinelProtocol } from '@/lib/sentinelHub';
import {
  buildEarthquakesGeoJSON,
  buildJammingGeoJSON,
  buildCorrelationsGeoJSON,
  buildGtRiskGeoJSON,
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
  type FlightLayerConfig } from '@/components/map/geoJSONBuilders';
import type {
  ViewBounds,
  DynamicRoute,
  GeoExtras,
  KiwiProps,
  ScannerProps,
  SigintProps,
  TrailPoint,
  TrailKind } from './MaplibreViewer.helpers';
import {
  FLIGHT_SELECTION_TYPES,
  parseTrailPoints,
  hasKnownRouteName,
  flightHasKnownRoute,
  flightPayloadHasKnownRoute,
  MAP_EXTRA_DATA_KEYS,
  VIIRS_TILE_TEMPLATES,
  buildProbeRasterUrl,
  probeRasterTile,
  buildPolymarketUrl } from './MaplibreViewer.helpers';

const MaplibreViewer = ({
  activeLayers,
  activeStyle,
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
  sarAoiListVersion }: Omit<MaplibreViewerProps, 'data'>) => {
  const coreData = useDataKeys([
    'tracked_flights',
    'commercial_flights',
    'military_flights',
    'private_flights',
    'private_jets',
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
  const [mapReady, setMapReady] = useState(false);
  // Esri World Imagery is fetched directly by the browser. When that host is
  // unreachable, skip the raster sources entirely instead of emitting one
  // console error per tile (hundreds of them at higher zoom levels).
  const [esriImageryReachable, setEsriImageryReachable] = useState(true);
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 4000);
    fetch(
      'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/0/0/0',
      { mode: 'no-cors', signal: controller.signal },
    )
      .catch(() => setEsriImageryReachable(false))
      .finally(() => clearTimeout(timer));
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, []);
  const { theme: uiTheme, sensor } = useTheme();
  // Sensor modes always grade the dark basemap; MAP TONE (light) applies to the EO view only.
  const theme = sensor !== 'off' ? 'dark' : uiTheme;
  // Sensor modes (FLIR / NVG / CRT) grade the whole map canvas with the website's optic
  // filters (globals.css), so the basemap itself always uses the navy palette.
  const basemapPalette = 'navy' as const;
  const { cartoApiKey, loaded: basemapConfigLoaded } = useBasemapConfig();
  const mapThemeStyle = useMemo<maplibregl.StyleSpecification | string>(
    () => buildBasemapStyle(theme === 'light' ? 'light' : 'dark', cartoApiKey, activeStyle),
    [theme, cartoApiKey, activeStyle],
  );

  const initialViewState = useMemo<ViewState>(
    () => ({
      longitude: 0,
      latitude: 20,
      zoom: 2,
      bearing: 0,
      pitch: 0,
      padding: { top: 0, bottom: 0, left: 0, right: 0 } }),
    [],
  );
  const viewStateRef = useRef<ViewState>(initialViewState);
  const [mapZoom, setMapZoom] = useState(initialViewState.zoom);
  const [dismissedAlerts, setDismissedAlerts] = useState<Set<string>>(new Set());
  const [viirsResolvedTileTemplate, setViirsResolvedTileTemplate] = useState<string | null>(null);
  const [isMapInteracting, setIsMapInteracting] = useState(false);

  const {
    pendingPin, setPendingPin, pinLabel, setPinLabel, pinNotes, setPinNotes,
    pinCategory, setPinCategory, pinSaving, aiIntelPins, setAiIntelPins,
    aiIntelRefreshTick, setAiIntelRefreshTick, openPinDetailId, setOpenPinDetailId,
    pinLabelInputRef, handleSavePin } = useMapPins({ onPinPlaced, aiIntelEnabled: activeLayers.ai_intel });

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
  const [selectedTrailPoints, setSelectedTrailPoints] = useState<TrailPoint[]>([]);
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
    resetTimestamp } =
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
      setDynamicRoute(null);
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

  useSelectedEntityTrail({ selectedEntity, data, dynamicRoute, setSelectedTrailPoints });

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
    if (!flyToLocation || !mapRef.current) return;
    const map = mapRef.current.getMap();

    if (flyToLocation.bounds) {
      // cameraForBounds returns undefined when padding exceeds the viewport,
      // and silently returns the map's maxZoom (22) for a degenerate box —
      // hence both the clamped padding and the explicit maxZoom.
      const { clientWidth, clientHeight } = map.getContainer();
      const padding = Math.min(64, Math.min(clientWidth, clientHeight) / 6);
      const cam = map.cameraForBounds(flyToLocation.bounds, {  maxZoom: ZOOM_MAX });
      map.flyTo({
        center: cam?.center ?? [flyToLocation.lng, flyToLocation.lat],
        zoom: cam ? clampZoom(cam.zoom ?? ZOOM_FALLBACK) : ZOOM_FALLBACK,
        duration: 1500 });
      return;
    }

    // Agent moves (sar_focus_aoi) carry their own zoom: a world-view revert
    // asks for ~2, a tight AOI for ~9. Ignoring it pinned every move at 8,
    // which turned "show the whole world" into a patch of empty ocean.
    mapRef.current.flyTo({
      center: [flyToLocation.lng, flyToLocation.lat],
      zoom: flyToLocation.zoom ?? 8,
      duration: 1500 });
  }, [flyToLocation]);

  // Voice-agent map control bus (U4 §3.5) — one additive effect answering the
  // easeTo / zoom / orbit / getViewState verbs. flyTo-family verbs keep
  // flowing through the tested flyToLocation prop above; orbit is a rAF
  // bearing animation cancelled by user drag or an explicit stop.
  useMapControlRequests(mapRef);

  const {
    earthquakesGeoJSON, jammingGeoJSON, correlationsGeoJSON, gtRiskGeoJSON,
    tinygsGeoJSON, shodanGeoJSON, aiIntelGeoJSON } = useMapCoreGeoJson({ activeLayers, data, inView, interpSat, interpTick, shodanResults, aiIntelPins });

  const {
    ukraineAlertsGeoJSON, ukraineAlertLabelsGeoJSON, weatherAlertsGeoJSON, weatherAlertLabelsGeoJSON, sentinelTileUrl } = useMapAlertGeoJson({ activeLayers, data, sentinelPreset, sentinelDate });

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

    registerMapImages(loadImg);

  }, []);

  // Load Images into the Map Style once loaded
  const onMapLoad = useCallback((e: { target: maplibregl.Map }) => {
    if (theme !== 'light') applyBasemapPalette(e.target, basemapPalette);
    initializeMap(e.target);
    setMapReady(true);
  }, [initializeMap, theme, basemapPalette]);

  const onMapStyleData = useCallback((e: { target: maplibregl.Map }) => {
    if (theme !== 'light') applyBasemapPalette(e.target, basemapPalette);
    initializeMap(e.target);
    setMapReady(true);
  }, [initializeMap, theme, basemapPalette]);



  useEffect(() => {
    const map = mapRef.current?.getMap();
    if (map) {
      initializeMap(map);
      setMapReady(true);
    }
  }, [initializeMap, theme]);

  // Build a set of tracked icao24s to exclude from other flight layers
  const { trackedIcaoSet, satellitesGeoJSON } = useMapTrackedSatGeoJson({ data, activeLayers, inView, interpSat, interpTick });

  const commConfig: FlightLayerConfig = {
    colorMap: COLOR_MAP_COMMERCIAL,
    groundedMap: GROUNDED_ICON_MAP,
    typeLabel: 'flight',
    idPrefix: 'flight-',
    useTrackHeading: true,
  };
  const privConfig: FlightLayerConfig = {
    colorMap: COLOR_MAP_PRIVATE,
    groundedMap: GROUNDED_ICON_MAP,
    typeLabel: 'private_flight',
    idPrefix: 'pflight-',
  };
  const jetsConfig: FlightLayerConfig = {
    colorMap: COLOR_MAP_JETS,
    groundedMap: GROUNDED_ICON_MAP,
    typeLabel: 'private_jet',
    idPrefix: 'pjet-',
  };
  const milConfig: FlightLayerConfig = {
    colorMap: COLOR_MAP_MILITARY,
    groundedMap: GROUNDED_ICON_MAP,
    typeLabel: 'military_flight',
    idPrefix: 'mflight-',
    milSpecialMap: MIL_SPECIAL_MAP,
  };

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
  const staticMalwareThreats = activeLayers.malware_c2 ? data?.malware_threats?.threats : undefined;
  const staticTelegramOsintPosts = activeLayers.telegram_osint
    ? data?.telegram_osint?.posts
    : undefined;

  const [submarineCablesGeoJSON, setSubmarineCablesGeoJSON] = useState<GeoJSON.FeatureCollection | null>(null);
  useEffect(() => {
    if (!activeLayers.submarine_cables) {
      setSubmarineCablesGeoJSON(null);
      return;
    }
    let cancelled = false;
    fetch('/data/submarine-cables.json')
      .then((r) => r.json())
      .then((geo) => {
        if (!cancelled) setSubmarineCablesGeoJSON(sanitizeSubmarineCables(geo));
      })
      .catch(() => {
        if (!cancelled) setSubmarineCablesGeoJSON(null);
      });
    return () => {
      cancelled = true;
    };
  }, [activeLayers.submarine_cables]);

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
      milConfig },
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
      serverBboxScoped: getLiveDataBounds() !== null,
      // Worker stamps base positions; main-thread applyDynamicLayerInterp
      // dead-reckons between polls without rebuilding FeatureCollections.
      dtSeconds: 0,
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
        sigint_aprs: activeLayers.sigint_aprs },
      activeFilters: activeFilters || {} },
    [
      mapBounds,
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

  const interpolatedDynamicMapLayers = useMemo(
    () => {
      void interpTick;
      return applyDynamicLayerInterp(dynamicMapLayers, dtSeconds.current);
    },
    [dynamicMapLayers, interpTick, dtSeconds],
  );

  const {
    commercialFlightsGeoJSON: commFlightsGeoJSON,
    privateFlightsGeoJSON: privFlightsGeoJSON,
    privateJetsGeoJSON: privJetsGeoJSON,
    militaryFlightsGeoJSON: milFlightsGeoJSON,
    trackedFlightsGeoJSON,
    shipsGeoJSON,
    meshtasticGeoJSON,
    aprsGeoJSON } = interpolatedDynamicMapLayers;

  // Label subjects follow the worker output (pre-interp, stable between
  // rebuilds) so labels track the same data filters as the icons.
  const { trackedFlightsForLabels, shipsForYachtLabels } = useMapLabelData({ data, dynamicMapLayers });

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
      malwareThreats: staticMalwareThreats,
      telegramOsintPosts: staticTelegramOsintPosts },
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
      staticMalwareThreats,
      staticTelegramOsintPosts,
      mapZoom,
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
        malware_c2: activeLayers.malware_c2,
        telegram_osint: activeLayers.telegram_osint } },
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
      activeLayers.malware_c2,
      activeLayers.telegram_osint,
    ],
  );

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
    malwareGeoJSON,
    telegramOsintGeoJSON } = staticMapLayers;

  const telegramOsintGeoJSONPlaced = useMemo(
    () => applyTelegramAlertAvoidance(telegramOsintGeoJSON, data?.news),
    [telegramOsintGeoJSON, data?.news],
  );

  // Extract cluster label positions via shared hook
  const shipClusters = useClusterLabels(mapRef, 'ships-clusters-layer', shipsGeoJSON);
  const eqClusters = useClusterLabels(mapRef, 'eq-clusters-layer', earthquakesGeoJSON);

  const { carrierShips, carriersGeoJSON } = useMapCarrierData({ activeLayers, data, activeFilters });

  // SAR anomaly pins (Mode B) + AOI watchbox circles.  AOIs render whenever
  // the SAR layer is on; anomalies only appear when Mode B has produced
  // something.  The render path is fully imperative via useImperativeSource.
  //
  // AOIs come from their own endpoint (/api/sar/aois) rather than the
  // dashboard payload because they're operator-managed metadata, not a
  const { sarAoisList, sarAnomaliesGeoJSON, sarAoisGeoJSON } = useMapSarData({ activeLayers, data, sarAoiListVersion });

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
        geometry: { type: 'LineString', coordinates: [currentLoc, originLoc] } });
      features.push({
        type: 'Feature',
        properties: { type: 'airport', code: originCode, role: 'DEP' },
        geometry: { type: 'Point', coordinates: originLoc } });
    }
    if (destLoc) {
      features.push({
        type: 'Feature',
        properties: { type: 'route-dest' },
        geometry: { type: 'LineString', coordinates: [currentLoc, destLoc] } });
      features.push({
        type: 'Feature',
        properties: { type: 'airport', code: destCode, role: 'ARR' },
        geometry: { type: 'Point', coordinates: destLoc } });
    }

    if (features.length === 0) return null;
    return { type: 'FeatureCollection' as const, features };
  }, [selectedEntity, data, dynamicRoute, getSelectedEntityLiveCoords, interpTick]);

  // Trail history GeoJSON: shows where the selected unknown-route aircraft or vessel has been.
  const trailGeoJSON = useMemo(() => {
    void interpTick;
    const entity = findSelectedEntity(selectedEntity, data);
    if (!entity || selectedTrailPoints.length < 2) return null;
    if (selectedEntity && FLIGHT_SELECTION_TYPES.has(selectedEntity.type) && flightPayloadHasKnownRoute(entity)) {
      return null;
    }

    // Trails are loaded only for the selected asset to avoid open-map clutter.
    const isShipTrail = selectedEntity?.type === 'ship';
    const points = [...selectedTrailPoints];

    const currentLoc = getSelectedEntityLiveCoords(entity);
    if (currentLoc && points.length > 0) {
      const lastPt = points[points.length - 1];
      points.push({
        lng: currentLoc[0],
        lat: currentLoc[1],
        alt: lastPt.alt,
        sog: lastPt.sog,
        ts: Date.now() / 1000 });
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
          color: isShipTrail ? '#22d3ee' : altToColor(((a.alt ?? 0) + (b.alt ?? 0)) / 2),
          opacity: 0.4 + progress * 0.5, // older segments more transparent
          segIndex: i },
        geometry: {
          type: 'LineString' as const,
          coordinates: [[a.lng, a.lat], [b.lng, b.lat]] } });
    }

    return { type: 'FeatureCollection' as const, features };
  }, [selectedEntity, data, selectedTrailPoints, dynamicRoute, getSelectedEntityLiveCoords, interpTick]);

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
      lat: currentLoc[1] });
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
    malwareGeoJSON && 'malware-clusters',
    malwareGeoJSON && 'malware-layer',
    submarineCablesGeoJSON && 'submarine-cables-layer',
    sarAnomaliesGeoJSON && 'sar-anomalies-layer',
    sarAoisGeoJSON && 'sar-aois-fill',
    aiIntelGeoJSON && 'ai-intel-clusters',
    aiIntelGeoJSON && 'ai-intel-pin-layer',
    correlationsGeoJSON && 'corr-rf-fill',
    correlationsGeoJSON && 'corr-mil-fill',
    correlationsGeoJSON && 'corr-infra-fill',
    correlationsGeoJSON && 'corr-contra-fill',
    correlationsGeoJSON && 'corr-analysis-fill',
    gtRiskGeoJSON && 'gt-risk-heatmap',
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
  useMapImperativeSources({
    map: mapReady ? mapRef.current : null,
    commFlightsGeoJSON, privFlightsGeoJSON, privJetsGeoJSON, milFlightsGeoJSON, trackedFlightsGeoJSON,
    uavGeoJSON, satellitesGeoJSON, tinygsGeoJSON, cctvGeoJSON, kiwisdrGeoJSON, pskReporterGeoJSON, satnogsGeoJSON, scannerGeoJSON,
    firmsGeoJSON, internetOutagesGeoJSON, dataCentersGeoJSON, powerPlantsGeoJSON, viirsChangeNodesGeoJSON,
    militaryBasesGeoJSON, gdeltGeoJSON, liveuaGeoJSON, airQualityGeoJSON, volcanoesGeoJSON, fishingGeoJSON,
    uapSightingsGeoJSON, wastewaterGeoJSON, crowdthreatGeoJSON, malwareGeoJSON, telegramOsintGeoJSONPlaced, submarineCablesGeoJSON,
    shipsGeoJSON, meshtasticGeoJSON, aprsGeoJSON, trainsGeoJSON, sarAoisGeoJSON, sarAnomaliesGeoJSON,
    nightGeoJSON, frontlineGeoJSON, earthquakesGeoJSON, jammingGeoJSON, gtRiskGeoJSON, correlationsGeoJSON, shodanGeoJSON, aiIntelGeoJSON,
    ukraineAlertsGeoJSON, ukraineAlertLabelsGeoJSON, weatherAlertsGeoJSON, weatherAlertLabelsGeoJSON,
    carriersGeoJSON, activeRouteGeoJSON, trailGeoJSON, predictiveGeoJSON, proximityRingsGeoJSON });

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


  const handleMoveStart = useCallback(() => {
    setIsMapInteracting((prev) => (prev ? prev : true));
  }, []);
  const handleMove = useCallback((evt: any) => {
    viewStateRef.current = evt.viewState;
  }, []);
  const handleMoveEnd = useCallback(() => {
    setIsMapInteracting(false);
    const currentViewState = viewStateRef.current;
    setMapZoom((prevZoom) =>
      Math.abs(prevZoom - currentViewState.zoom) > 0.01 ? currentViewState.zoom : prevZoom,
    );
    onViewStateChange?.({
      zoom: currentViewState.zoom,
      latitude: currentViewState.latitude });
    updateBounds();
  }, [onViewStateChange, updateBounds]);
  const handleContextMenu = useCallback((evt: any) => {
    evt.preventDefault();
    onRightClick?.({ lat: evt.lngLat.lat, lng: evt.lngLat.lng });
  }, [onRightClick]);
  const handleIdle = useCallback(() => {
    setIsMapInteracting(false);
    updateBounds();
  }, [updateBounds]);
  const handleMapClick = useCallback((e: any) => {
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
              entity_label: String(clickedProps.name || clickedProps.callsign || clickedProps.label || '') } : null });
          return;
        }
        // AI Intel pin click → open detail popup (takes precedence over entity selection)
        if (e.features && e.features.length > 0) {
          const aiPin = e.features.find(
            (f: any) => f.layer?.id === 'ai-intel-pin-layer' && !(f.properties as Record<string, unknown> | null)?.cluster,
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
          // SDR receiver, etc.) is also under the  prefer it — the
          // AOI should only win when the user clicks empty space inside it.
          const nonAoiFeature = e.features.find(
            (f: any) => f.layer?.id !== 'sar-aois-fill',
          );
          const feature = nonAoiFeature ?? e.features[0];
          const props = feature.properties || {};

          // If the clicked feature is a  zoom into it instead of selecting an entity
          if (props.cluster) {
            const targetZoom = (mapRef.current?.getMap().getZoom() ?? mapZoom) + 2;
            mapRef.current?.flyTo({
              center: [e.lngLat.lng, e.lngLat.lat],
              zoom: targetZoom,
              duration: 500 });
            return;
          }
          onEntityClick?.({
            id: props.id,
            type: props.type,
            name: props.name,
            media_url: props.media_url,
            extra: props });
        } else {
          onEntityClick?.(null);
        }
  }, [measureMode, onMeasureClick, sarAoiDropMode, onSarAoiDropped, pinPlacementMode, setPendingPin, setOpenPinDetailId, selectedEntity, onEntityClick, mapRef, mapZoom]);

  return (
    <div
      className={`relative h-full w-full z-0 isolate ${selectedEntity && ['region_dossier', 'gdelt', 'liveuamap', 'news', 'telegram_osint', 'gt_risk'].includes(selectedEntity.type) ? 'map-focus-active' : ''}`}
      style={pinPlacementMode || sarAoiDropMode ? { cursor: 'crosshair' } : undefined}
    >
      {/* Resolve optional CARTO config before first paint. Without a CARTO key,
          buildBasemapStyle uses the keyless OpenFreeMap style instead. */}
      {basemapConfigLoaded && (
      <Map
        ref={mapRef}
        reuseMaps
        maxTileCacheSize={200}
        fadeDuration={0}
        style={{ width: '100%', height: '100%' }}
        initialViewState={initialViewState}
        onMoveStart={handleMoveStart}
        onMove={handleMove}
        onMoveEnd={handleMoveEnd}
        onMouseMove={handleMouseMove}
        onContextMenu={handleContextMenu}
        mapStyle={mapThemeStyle}
        mapLib={maplibregl}
        attributionControl={false}
        onLoad={onMapLoad}
        onStyleData={onMapStyleData}
        onIdle={handleIdle}
        interactiveLayerIds={activeInteractiveLayerIds}
        onClick={handleMapClick}
      >
        <AttributionControl
          compact
          customAttribution={[
            OSM_ATTRIBUTION_HTML,
            cartoApiKey ? CARTO_ATTRIBUTION_HTML : OPENFREEMAP_ATTRIBUTION_HTML,
            '<a href="https://adsb.lol" target="_blank" rel="noopener">adsb.lol (ODbL)</a>',
            '<a href="https://opensky-network.org" target="_blank" rel="noopener">OpenSky</a>',
            '<a href="https://celestrak.org" target="_blank" rel="noopener">CelesTrak</a>',
            '<a href="https://aisstream.io" target="_blank" rel="noopener">aisstream.io</a>',
            '<a href="https://meshtastic.liamcottle.net" target="_blank" rel="noopener">Meshtastic map by Liam Cottle</a>',
            'NASA · NOAA · USGS · GDELT',
            '<a href="https://github.com/BigBodyCobain/Shadowbroker/blob/main/DATA-ATTRIBUTION.md" target="_blank" rel="noopener">full sources</a>',
          ]}
        />
        {/* Imagery anchor: an empty layer added before every data layer. Raster imagery
            (satellite / GIBS / Sentinel) is inserted *below* it, so imagery never paints over
            aircraft,  clusters or any other data layer that mounts later. */}
        <Source id="sb-imagery-anchor" type="geojson" data={EMPTY_FC}>
          <Layer id="sb-imagery-anchor" type="circle" paint={{ 'circle-radius': 0, 'circle-opacity': 0 }} />
        </Source>
        {/* Esri World Imagery — high-res static satellite (zoom 0-18+) */}
        {activeLayers.highres_satellite && esriImageryReachable && (
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
              beforeId="sb-imagery-anchor"
              type="raster"
              paint={{
                'raster-opacity': 1,
                'raster-fade-duration': 300,
                // sensor modes dim the imagery itself so aircraft/ships stay brighter than the ground
                // NVG gain blooms bright ground (ice, desert) into flat mint, so it gets the hardest roll-off
                'raster-brightness-max': sensor === 'off' ? 1 : sensor === 'flir' ? 0.62 : sensor === 'crt' ? 0.42 : 0.4,
                'raster-saturation': sensor === 'off' ? 0 : sensor === 'nvg' ? -0.6 : -0.35,
                'raster-contrast': sensor === 'off' ? 0 : sensor === 'crt' ? -0.05 : sensor === 'nvg' ? -0.05 : 0.12 }}
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
              beforeId="sb-imagery-anchor"
              type="raster"
              paint={{
                'raster-opacity': gibsOpacity ?? 0.6,
                'raster-fade-duration': 0 }}
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
                beforeId="sb-imagery-anchor"
                type="raster"
                paint={{
                  'raster-opacity': 0.9,
                  'raster-fade-duration': 0 }}
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
              beforeId="sb-imagery-anchor"
              type="raster"
              paint={{
                'raster-opacity': sentinelOpacity ?? 0.6,
                'raster-fade-duration': 0 }}
            />
          </Source>
        )}

        {/* Esri Reference Overlay — borders, labels, and places on top of imagery layers */}
        {showImageryReferenceOverlay && esriImageryReachable && (
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
              beforeId="sb-imagery-anchor"
              type="raster"
              paint={{
                'raster-opacity': imageryReferenceOverlayOpacity,
                'raster-fade-duration': 300 }}
            />
          </Source>
        )}

        {/* NASA FIRMS VIIRS — fire hotspot icons from FIRMS CSV feed */}
        <FirmsFireLayers />

        {activeLayers.day_night && <DayNightLayers theme={theme} />}

        {/* ═══ GROUND OVERLAYS — rendered below  mesh, and flights ═══ */}

        <FrontlinesLayer />

        <EarthquakesLayers />

        {/* CCTV Cameras — clustered white dots */}
        <CctvLayers />

        {/* KiwiSDR Receivers — radio tower icons with pulse rings */}
        <KiwiSdrLayers />

        {/* PSK Reporter — green HF digital mode spots with clustering */}
        <PskReporterLayers />

        {/* SatNOGS Ground Stations — teal satellite dish icons with clustering */}
        <SatnogsLayers />

        {/* TinyGS LoRa Satellites — purple satellite icons (no clustering, small count) */}
        <TinyGSLayers />

        {/* Internet Outages — region-level grey markers with % and labels */}
        <InternetOutagesLayers />

        {/* Power Plant positions */}
        {powerPlantsGeoJSON && (
        <PowerPlantsLayers />
        )}

        {/* VIIRS Change Detection Nodes */}
        {viirsChangeNodesGeoJSON && (
        <ViirsChangeNodesLayers />
        )}

        {/* SAR AOIs — operator watchbox circles, drawn beneath anomaly pins */}
        {sarAoisGeoJSON && (
        <SarAoisLayers />
        )}

        {/* SAR Anomalies — Mode B pre-processed findings (OPERA/EGMS/GFM/EMS/UNOSAT) */}
        {sarAnomaliesGeoJSON && (
        <SarAnomaliesLayers />
        )}

        {/* Shodan — operator-triggered local  clustered and clearly distinct */}
        <ShodanOverlayLayer shodanStyle={shodanStyle} />


        {/* AI Intel Layer — pins from connected AI agents / AI co-pilot (data via useImperativeSource) */}
        <Source
          id="ai-intel-source"
          type="geojson"
          data={EMPTY_FC}
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
                'circle-stroke-color': '#a78bfa66' }}
            />
            <Layer
              id="ai-intel-cluster-count"
              type="symbol"
              filter={['has', 'point_count']}
              layout={{
                'text-field': '{point_count_abbreviated}',
                'text-font': ['Noto Sans Bold'],
                'text-size': 12 }}
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
                'text-optional': true }}
              paint={{
                'text-color': ['get', 'color'],
                'text-halo-color': 'rgba(0,0,0,0.85)',
                'text-halo-width': 1 }}
            />
          </Source>

        {/* Military Bases — per-country colors */}
        <MilitaryBasesLayers />

        {/* Ukraine Air Raid Alerts — red/orange oblast polygons */}
        <UkraineAlertsLayers />

        {/* Weather Alerts — severity-colored polygons with icon + label overlay */}        {/* Weather Alerts — severity-colored polygons with icon + label overlay */}
        <WeatherAlertsLayers />

        {/* Air Quality — AQI-colored circles */}        {/* Air Quality — AQI-colored circles */}
        <AirQualityLayers />

        {/* Volcanoes — activity-colored triangle icons */}        {/* Volcanoes — activity-colored triangle icons */}
        <VolcanoLayers />

        {/* Fishing Activity — AIS-style ship clusters and icons */}        {/* Fishing Activity — AIS-style ship clusters and icons */}
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
            civilian_count: ['+', ['case', ['==', ['get', 'shipCategory'], 'civilian'], 1, 0]] }}
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
              'icon-rotation-alignment': 'viewport' }}
            paint={{
              'icon-opacity': 0.98 }}
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
              'text-ignore-placement': true }}
            paint={{
              'text-color': '#ffffff',
              'text-halo-color': 'rgba(0, 0, 0, 0.95)',
              'text-halo-width': 1.8 }}
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
              'icon-rotation-alignment': 'map' }}
            paint={{
              'icon-opacity': 0.85 }}
          />
        </Source>

        {/* UAP Sightings — purple UFO icons with detail labels */}
        <UapSightingsLayers />

        {/* WastewaterSCAN — pathogen surveillance network (water drops) */}
        <WastewaterLayers />

        {/* CrowdThreat — crowdsourced threat intelligence with category icons */}
        <CrowdThreatLayers />

        {/* Telegram OSINT — one pin per geocoded city; scroll posts in popup */}
        <TelegramOsintLayers />

        {/* Malware C2 — abuse.ch Feodo Tracker, ViriBack C2 Tracker, C2IntelFeeds */}
        <MalwareLayers />

        {/* Submarine cables — static TeleGeography GeoJSON */}
        <SubmarineCablesLayers />

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
              // brand palette: deep navy-blue fill with a cyan rim (was Tailwind indigo)
              'circle-color': 'rgba(10, 52, 96, 0.88)',
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
              'circle-stroke-width': 1.75,
              'circle-stroke-color': 'rgba(69, 216, 255, 0.95)' }}
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
              'icon-rotation-alignment': 'map' }}
            paint={{
              'icon-opacity': opacityFilter }}
          />
        </Source>

        <CarriersLayers opacityFilter={opacityFilter} />

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
              'icon-allow-overlap': true }}
            paint={{
              'icon-opacity': 0.95 }}
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
              'text-allow-overlap': true }}
            paint={{
              'text-color': '#052e16',
              'text-halo-color': '#86efac',
              'text-halo-width': 0.8 }}
          />
          <Layer
            id="meshtastic-circles"
            type="symbol"
            filter={['!', ['has', 'point_count']]}
            layout={{
              'icon-image': 'icon-mesh-triangle',
              'icon-size': 0.7,
              'icon-allow-overlap': true }}
            paint={{
              'icon-opacity': 0.85 }}
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
              'text-allow-overlap': false }}
            paint={{
              'text-color': '#86efac',
              'text-halo-color': 'rgba(0,0,0,0.8)',
              'text-halo-width': 1 }}
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
              'icon-allow-overlap': true }}
            paint={{
              'icon-opacity': 0.95 }}
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
              'text-allow-overlap': true }}
            paint={{
              'text-color': '#4a0525',
              'text-halo-color': '#f9a8d4',
              'text-halo-width': 0.8 }}
          />
          <Layer
            id="aprs-triangles"
            type="symbol"
            filter={['!', ['has', 'point_count']]}
            layout={{
              'icon-image': 'icon-aprs-triangle',
              'icon-size': 0.7,
              'icon-allow-overlap': true }}
            paint={{
              'icon-opacity': 0.85 }}
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
              'text-allow-overlap': false }}
            paint={{
              'text-color': '#f9a8d4',
              'text-halo-color': 'rgba(0,0,0,0.8)',
              'text-halo-width': 1 }}
          />
        </Source>

        {/* ═══ FLIGHTS — always rendered above ground/ship/mesh layers ═══ */}
        <FlightCategoryLayers opacityFilter={opacityFilter} />

        <ActiveRouteLayers />

        {/* Flight trail history (where the aircraft has been) — altitude-colored gradient */}
        <FlightTrailLayers />

        {/* Predictive vector (where entity is heading — 5 min forward projection) */}
        <PredictivePathLayers />

        {/* Proximity range rings (10nm, 50nm, 100nm around selected entity) */}
        <ProximityRingsLayers />

        {/* GDELT & LiveUA — ground-level incidents, rendered below flights */}
        <GdeltLayers />

        <LiveuamapLayers />

        {/* tracked-flights & UAVs: rendered above ground layers (airborne) */}
        <TrackedFlightsLayers opacityFilter={opacityFilter} />

        <UavsLayers opacityFilter={opacityFilter} />

        {/* HTML labels for ship cluster counts (hidden when any entity popup is active) */}
        {shipsGeoJSON && !selectedEntity && !isMapInteracting && (
          <ClusterCountLabels clusters={shipClusters} prefix="sc" />
        )}

        {/* HTML labels for tracked flights — color-matched, zoom-gated for non-HVA */}
        {trackedFlightsGeoJSON && !selectedEntity && !isMapInteracting && trackedFlightsForLabels.length > 0 && (
          <TrackedFlightLabels
            flights={trackedFlightsForLabels}
            zoom={mapZoom}
            inView={inView}
            interpFlight={interpFlight}
          />
        )}

        {/* HTML labels for carriers (orange names, with ESTIMATED badge for OSINT positions) */}
        {carriersGeoJSON && !selectedEntity && !isMapInteracting && carrierShips.length > 0 && (
          <CarrierLabels ships={carrierShips as any} inView={inView} interpShip={interpShip} />
        )}

        {/* HTML labels for tracked yachts (pink owner names) */}
        {shipsGeoJSON && activeLayers.ships_tracked_yachts && !selectedEntity && !isMapInteracting && shipsForYachtLabels.length > 0 && (
          <TrackedYachtLabels ships={shipsForYachtLabels} inView={inView} interpShip={interpShip} />
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

        {/* one cross-layer pass that keeps callouts and labels from printing over each other */}
        <LabelDeclutter />

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

        {activeLayers.telegram_osint && !isMapInteracting && telegramOsintGeoJSONPlaced?.features?.length ? (
          <TelegramOsintMarkers
            features={telegramOsintGeoJSONPlaced.features}
            onEntityClick={onEntityClick}
          />
        ) : null}

        {/* Satellite positions — mission-type icons */}
        {/* satellites: data pushed imperatively */}
        <SatellitesLayers />

        {/* Train positions */}
        <TrainsLayers />

        <MapEntityPopups p={{ AIIntelPinDetail,  Activity,    AlertTriangle,          CctvFullscreenModal,            CorrelationPopup,                   ExternalLink,   FishingDestinationRoute,        GtRiskPopup,   Info,            Location,    MilitaryBasePopup,                    Play,             Radio,      RegionDossierPanel,  Satellite, SatellitePopup,          ShipPopup,   SigintPopup,           TelegramOsintPopup,                WastewaterPopup,  WikiImage,                                          articleSourceUrl,                                    buildCctvProxyUrl, buildPolymarketUrl,                                                    createPortal,         data,                                    external,                            formatDossierTime,                      handleSavePin,                       interpShip,                                                                                                     onEntityClick,    onPinPlaced,   open, openPinDetailId,      oracleIntel,                 pendingPin,  pinCategory,  pinLabel, pinLabelInputRef,   pinNotes, pinSaving,                                    regionDossier, regionDossierLoading,                     sameEntityId,           scroll,      selectedEntity,     setAiIntelRefreshTick, setOpenPinDetailId, setPendingPin, setPinCategory, setPinLabel, setPinNotes, setTrackedScanner, setTrackedSdr,                                     status,               telegramClusterKey, telegramClusterNearNewsAlert, telegramMapPinCoords}} />

        <MeasurementLayers measurePoints={measurePoints} />
      </Map>
      )}
    </div>
  );
};

import dynamic from 'next/dynamic';

export default dynamic(() => Promise.resolve(MaplibreViewer), {
  ssr: false });
