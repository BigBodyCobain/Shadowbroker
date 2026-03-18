"use client";

import { API_BASE } from "@/lib/api";
import React, { useMemo, useState, useEffect, useCallback, useRef } from "react";
import Map, { Source, Layer, MapRef, ViewState, Popup, Marker } from "react-map-gl/maplibre";
import "maplibre-gl/dist/maplibre-gl.css";
import { computeNightPolygon } from "@/utils/solarTerminator";
import { interpolatePosition } from "@/utils/positioning";
import { darkStyle, lightStyle } from "@/components/map/styles/mapStyles";
import ScaleBar from "@/components/ScaleBar";
import maplibregl from "maplibre-gl";
import { AlertTriangle, Radio, Globe, Activity, Play } from "lucide-react";
import WikiImage from "@/components/WikiImage";
import { useTheme } from "@/lib/ThemeContext";

import {
    svgPlaneCyan, svgPlaneYellow, svgPlaneOrange, svgPlanePurple,
    svgFighter, svgHeli, svgHeliCyan, svgHeliOrange, svgHeliPurple,
    svgTanker, svgRecon, svgPlanePink, svgPlaneAlertRed, svgPlaneDarkBlue,
    svgPlaneWhiteAlert, svgHeliPink, svgHeliAlertRed, svgHeliDarkBlue,
    svgHeliBlue, svgHeliLime, svgHeliWhiteAlert, svgPlaneBlack, svgHeliBlack,
    svgDrone, svgDataCenter, svgEthNode, svgRadioTower, svgShipGray, svgShipRed, svgShipYellow,
    svgShipBlue, svgShipWhite, svgShipPink, svgCarrier, svgCctv, svgWarning, svgThreat,
    svgTriangleYellow, svgTriangleRed,
    svgFireYellow, svgFireOrange, svgFireRed, svgFireDarkRed,
    svgFireClusterSmall, svgFireClusterMed, svgFireClusterLarge, svgFireClusterXL,
    svgPotusPlane, svgPotusHeli, POTUS_ICAOS,
    svgAirlinerCyan, svgAirlinerOrange, svgAirlinerPurple, svgAirlinerYellow,
    svgAirlinerPink, svgAirlinerRed, svgAirlinerDarkBlue, svgAirlinerBlue,
    svgAirlinerLime, svgAirlinerBlack, svgAirlinerWhite,
    svgTurbopropCyan, svgTurbopropOrange, svgTurbopropPurple, svgTurbopropYellow,
    svgTurbopropPink, svgTurbopropRed, svgTurbopropDarkBlue, svgTurbopropBlue,
    svgTurbopropLime, svgTurbopropBlack, svgTurbopropWhite,
    svgBizjetCyan, svgBizjetOrange, svgBizjetPurple, svgBizjetYellow,
    svgBizjetPink, svgBizjetRed, svgBizjetDarkBlue, svgBizjetBlue,
    svgBizjetLime, svgBizjetBlack, svgBizjetWhite,
    svgAirlinerGrey, svgTurbopropGrey, svgBizjetGrey, svgHeliGrey,
    GROUNDED_ICON_MAP, COLOR_MAP_COMMERCIAL, COLOR_MAP_PRIVATE,
    COLOR_MAP_JETS, COLOR_MAP_MILITARY, MIL_SPECIAL_MAP,
} from "@/components/map/icons/AircraftIcons";
import { classifyAircraft } from "@/utils/aircraftClassification";
import { makeSatSvg, MISSION_COLORS, MISSION_ICON_MAP } from "@/components/map/icons/SatelliteIcons";
import { EMPTY_FC } from "@/components/map/mapConstants";
import { useImperativeSource } from "@/components/map/hooks/useImperativeSource";
import { ClusterCountLabels, TrackedFlightLabels, CarrierLabels, TrackedYachtLabels, UavLabels, EarthquakeLabels, ThreatMarkers } from "@/components/map/MapMarkers";
import type { MaplibreViewerProps } from "@/types/dashboard";
import { INTERP_TICK_MS, ALERT_BOX_WIDTH_PX, ALERT_MAX_OFFSET_PX } from "@/lib/constants";
import { useInterpolation } from "@/components/map/hooks/useInterpolation";
import { useClusterLabels } from "@/components/map/hooks/useClusterLabels";
import { spreadAlertItems } from "@/utils/alertSpread";
import {
    buildEarthquakesGeoJSON, buildJammingGeoJSON, buildCctvGeoJSON, buildKiwisdrGeoJSON,
    buildFirmsGeoJSON, buildInternetOutagesGeoJSON, buildDataCentersGeoJSON, buildMilitaryBasesGeoJSON,
    buildEthNodesGeoJSON,
    buildGdeltGeoJSON, buildLiveuaGeoJSON, buildFrontlineGeoJSON,
    buildFlightLayerGeoJSON, buildUavGeoJSON,
    buildSatellitesGeoJSON, buildShipsGeoJSON, buildCarriersGeoJSON,
    type FlightLayerConfig,
} from "@/components/map/geoJSONBuilders";

const MaplibreViewer = ({ data, activeLayers, onEntityClick, flyToLocation, selectedEntity, onMouseCoords, onRightClick, regionDossier, regionDossierLoading, onViewStateChange, measureMode, onMeasureClick, measurePoints, gibsDate, gibsOpacity, viewBoundsRef, setTrackedSdr }: MaplibreViewerProps) => {
    const mapRef = useRef<MapRef>(null);
    const [mapReady, setMapReady] = useState(false);
    const { theme } = useTheme();
    const mapThemeStyle = useMemo(() => theme === 'light' ? lightStyle : darkStyle, [theme]);

    const [viewState, setViewState] = useState<ViewState>({
        longitude: 0,
        latitude: 20,
        zoom: 2,
        bearing: 0,
        pitch: 0,
        padding: { top: 0, bottom: 0, left: 0, right: 0 }
    });

    // Viewport bounds for culling off-screen features [west, south, east, north]
    // Buffer extends bounds by ~20% so features near edges don't pop in/out
    const [mapBounds, setMapBounds] = useState<[number, number, number, number]>([-180, -90, 180, 90]);
    const boundsTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    const updateBounds = useCallback(() => {
        const map = mapRef.current?.getMap();
        if (!map) return;
        const b = map.getBounds();
        const latRange = b.getNorth() - b.getSouth();
        const lngRange = b.getEast() - b.getWest();
        const buf = 0.2; // 20% buffer
        setMapBounds([
            b.getWest() - lngRange * buf,
            b.getSouth() - latRange * buf,
            b.getEast() + lngRange * buf,
            b.getNorth() + latRange * buf
        ]);
        // Write raw (unpadded) bounds for server-side viewport filtering
        if (viewBoundsRef && 'current' in viewBoundsRef) {
            (viewBoundsRef as React.MutableRefObject<any>).current = {
                south: b.getSouth(),
                west: b.getWest(),
                north: b.getNorth(),
                east: b.getEast(),
            };
        }
        
        // Debounce POSTing viewport bounds to backend for dynamic AIS stream filtering
        if (boundsTimerRef.current) clearTimeout(boundsTimerRef.current);
        boundsTimerRef.current = setTimeout(() => {
            fetch(`${API_BASE}/api/viewport`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    s: b.getSouth(),
                    w: b.getWest(),
                    n: b.getNorth(),
                    e: b.getEast()
                })
            }).catch(e => console.error("Failed to update backend viewport:", e));
        }, 1500); // 1.5s debounce after map stops moving
    }, [viewBoundsRef]);

    // Fast bounds check — used by all GeoJSON builders and Marker loops
    const inView = useCallback((lat: number, lng: number) =>
        lng >= mapBounds[0] && lng <= mapBounds[2] && lat >= mapBounds[1] && lat <= mapBounds[3],
        [mapBounds]
    );

    const [dynamicRoute, setDynamicRoute] = useState<any>(null);
    const prevCallsign = useRef<string | null>(null);

    // Global Incidents popup: dismiss state
    // Keys use stable content hash (title+coords) to survive data.news array replacement on refresh
    // NOTE: Using Set (not Map) to avoid collision with the `Map` react-map-gl import
    const [dismissedAlerts, setDismissedAlerts] = useState<Set<string>>(new Set());

    // --- Smooth interpolation via extracted hook ---
    const { interpTick, interpFlight, interpShip, interpSat, dtSeconds, dataTimestamp } = useInterpolation();

    // Track when flight/ship/satellite data actually changes (new fetch arrived)
    useEffect(() => {
        dataTimestamp.current = Date.now();
    }, [data?.commercial_flights, data?.ships, data?.satellites]);

    // --- Solar Terminator: recompute the night polygon every 60 seconds ---
    const [nightGeoJSON, setNightGeoJSON] = useState<GeoJSON.FeatureCollection>(() => computeNightPolygon());
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
            if (selectedEntity.type === 'flight') entity = data?.commercial_flights?.find((f: any) => f.icao24 === selectedEntity.id);
            else if (selectedEntity.type === 'private_flight') entity = data?.private_flights?.find((f: any) => f.icao24 === selectedEntity.id);
            else if (selectedEntity.type === 'military_flight') entity = data?.military_flights?.find((f: any) => f.icao24 === selectedEntity.id);
            else if (selectedEntity.type === 'private_jet') entity = data?.private_jets?.find((f: any) => f.icao24 === selectedEntity.id);
            else if (selectedEntity.type === 'tracked_flight') entity = data?.tracked_flights?.find((f: any) => f.icao24 === selectedEntity.id);

            if (entity && entity.callsign) {
                callsign = entity.callsign;
                entityLat = entity.lat ?? 0;
                entityLng = entity.lng ?? 0;
            }
        }

        if (callsign && callsign !== prevCallsign.current) {
            prevCallsign.current = callsign;
            fetch(`${API_BASE}/api/route/${callsign}?lat=${entityLat}&lng=${entityLng}`)
                .then(res => res.json())
                .then(routeData => {
                    if (isMounted) setDynamicRoute(routeData);
                })
                .catch(() => {
                    if (isMounted) setDynamicRoute(null);
                });
        } else if (!callsign) {
            prevCallsign.current = null;
            if (isMounted) setDynamicRoute(null);
        }

        return () => { isMounted = false; };
    }, [selectedEntity, data]);

    useEffect(() => {
        if (flyToLocation && mapRef.current) {
            mapRef.current.flyTo({
                center: [flyToLocation.lng, flyToLocation.lat],
                zoom: 8,
                duration: 1500
            });
        }
    }, [flyToLocation]);

    const earthquakesGeoJSON = useMemo(() =>
        activeLayers.earthquakes ? buildEarthquakesGeoJSON(data?.earthquakes) : null,
        [activeLayers.earthquakes, data?.earthquakes]);

    const jammingGeoJSON = useMemo(() =>
        activeLayers.gps_jamming ? buildJammingGeoJSON(data?.gps_jamming) : null,
        [activeLayers.gps_jamming, data?.gps_jamming]);

    const cctvGeoJSON = useMemo(() =>
        activeLayers.cctv ? buildCctvGeoJSON(data?.cctv, inView) : null,
        [activeLayers.cctv, data?.cctv, inView]);

    const kiwisdrGeoJSON = useMemo(() =>
        activeLayers.kiwisdr ? buildKiwisdrGeoJSON(data?.kiwisdr, inView) : null,
        [activeLayers.kiwisdr, data?.kiwisdr, inView]);

    const firmsGeoJSON = useMemo(() =>
        activeLayers.firms ? buildFirmsGeoJSON(data?.firms_fires) : null,
        [activeLayers.firms, data?.firms_fires]);

    const internetOutagesGeoJSON = useMemo(() =>
        activeLayers.internet_outages ? buildInternetOutagesGeoJSON(data?.internet_outages) : null,
        [activeLayers.internet_outages, data?.internet_outages]);

    const dataCentersGeoJSON = useMemo(() =>
        activeLayers.datacenters ? buildDataCentersGeoJSON(data?.datacenters) : null,
        [activeLayers.datacenters, data?.datacenters]);

    const militaryBasesGeoJSON = useMemo(() =>
        activeLayers.military_bases ? buildMilitaryBasesGeoJSON(data?.military_bases) : null,
        [activeLayers.military_bases, data?.military_bases]);

    const ethNodesGeoJSON = useMemo(() =>
        activeLayers.eth_nodes ? buildEthNodesGeoJSON(data?.eth_nodes) : null,
        [activeLayers.eth_nodes, data?.eth_nodes]);

    // Load Images into the Map Style once loaded
    const onMapLoad = useCallback((e: any) => {
        const map = e.target;

        // Track which images are still loading so we can retry on styleimagemissing
        const pendingImages: Record<string, string> = {};

        const loadImg = (id: string, url: string) => {
            if (!map.hasImage(id)) {
                pendingImages[id] = url;
                const img = new Image();
                img.crossOrigin = "anonymous";
                img.src = url;
                img.onload = () => {
                    if (!map.hasImage(id)) map.addImage(id, img);
                    delete pendingImages[id];
                };
            }
        };

        // Suppress "image not found" warnings — retry when the async load finishes
        map.on('styleimagemissing', (ev: any) => {
            const id = ev.id;
            const url = pendingImages[id];
            if (url) {
                const img = new Image();
                img.crossOrigin = "anonymous";
                img.src = url;
                img.onload = () => {
                    if (!map.hasImage(id)) map.addImage(id, img);
                    delete pendingImages[id];
                };
            }
        });

        // Critical icons — needed immediately for default-on layers
        loadImg('svgPlaneCyan', svgPlaneCyan);
        loadImg('svgPlaneYellow', svgPlaneYellow);
        loadImg('svgPlaneOrange', svgPlaneOrange);
        loadImg('svgPlanePurple', svgPlanePurple);
        loadImg('svgHeli', svgHeli);
        loadImg('svgHeliCyan', svgHeliCyan);
        loadImg('svgHeliOrange', svgHeliOrange);
        loadImg('svgHeliPurple', svgHeliPurple);
        loadImg('svgHeliBlue', svgHeliBlue);
        loadImg('svgHeliLime', svgHeliLime);
        loadImg('svgFighter', svgFighter);
        loadImg('svgTanker', svgTanker);
        loadImg('svgRecon', svgRecon);
        loadImg('svgAirlinerCyan', svgAirlinerCyan);
        loadImg('svgAirlinerOrange', svgAirlinerOrange);
        loadImg('svgAirlinerPurple', svgAirlinerPurple);
        loadImg('svgAirlinerYellow', svgAirlinerYellow);
        loadImg('svgTurbopropCyan', svgTurbopropCyan);
        loadImg('svgTurbopropOrange', svgTurbopropOrange);
        loadImg('svgTurbopropPurple', svgTurbopropPurple);
        loadImg('svgTurbopropYellow', svgTurbopropYellow);
        loadImg('svgBizjetCyan', svgBizjetCyan);
        loadImg('svgBizjetOrange', svgBizjetOrange);
        loadImg('svgBizjetPurple', svgBizjetPurple);
        loadImg('svgBizjetYellow', svgBizjetYellow);
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
        loadImg('svgCarrier', svgCarrier);
        loadImg('svgWarning', svgWarning);
        loadImg('icon-threat', svgThreat);

        // Deferred icons — for off-by-default layers and rare variants
        // Loaded in next frame to avoid blocking initial map render
        setTimeout(() => {
            loadImg('svgRadioTower', svgRadioTower);
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
            // Ethereum node icon
            loadImg('eth-node', svgEthNode);
            // Satellite mission-type icons
            loadImg('sat-mil', makeSatSvg('#ff3333'));
            loadImg('sat-sar', makeSatSvg('#00e5ff'));
            loadImg('sat-sigint', makeSatSvg('#ffffff'));
            loadImg('sat-nav', makeSatSvg('#4488ff'));
            loadImg('sat-ew', makeSatSvg('#ff00ff'));
            loadImg('sat-com', makeSatSvg('#44ff44'));
            loadImg('sat-station', makeSatSvg('#ffdd00'));
            loadImg('sat-gen', makeSatSvg('#aaaaaa'));
        }, 0);

        setMapReady(true);
    }, []);

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
    const satellitesGeoJSON = useMemo(() =>
        activeLayers.satellites ? buildSatellitesGeoJSON(data?.satellites, inView, interpSat) : null,
        [activeLayers.satellites, data?.satellites, dtSeconds, inView]);

    // Flight layer configs — shared across 4 near-identical builders
    const flightHelpers = useMemo(() => ({ interpFlight, inView, trackedIcaoSet }), [interpFlight, inView, trackedIcaoSet]);
    const commConfig: FlightLayerConfig = { colorMap: COLOR_MAP_COMMERCIAL, groundedMap: GROUNDED_ICON_MAP, typeLabel: 'flight', idPrefix: 'flight-', useTrackHeading: true };
    const privConfig: FlightLayerConfig = { colorMap: COLOR_MAP_PRIVATE, groundedMap: GROUNDED_ICON_MAP, typeLabel: 'private_flight', idPrefix: 'pflight-' };
    const jetsConfig: FlightLayerConfig = { colorMap: COLOR_MAP_JETS, groundedMap: GROUNDED_ICON_MAP, typeLabel: 'private_jet', idPrefix: 'pjet-' };
    const milConfig: FlightLayerConfig = { colorMap: COLOR_MAP_MILITARY, groundedMap: GROUNDED_ICON_MAP, typeLabel: 'military_flight', idPrefix: 'mflight-', milSpecialMap: MIL_SPECIAL_MAP };

    const commFlightsGeoJSON = useMemo(() =>
        activeLayers.flights ? buildFlightLayerGeoJSON(data?.commercial_flights, commConfig, flightHelpers) : null,
        [activeLayers.flights, data?.commercial_flights, flightHelpers]);

    const privFlightsGeoJSON = useMemo(() =>
        activeLayers.private ? buildFlightLayerGeoJSON(data?.private_flights, privConfig, flightHelpers) : null,
        [activeLayers.private, data?.private_flights, flightHelpers]);

    const privJetsGeoJSON = useMemo(() =>
        activeLayers.jets ? buildFlightLayerGeoJSON(data?.private_jets, jetsConfig, flightHelpers) : null,
        [activeLayers.jets, data?.private_jets, flightHelpers]);

    const milFlightsGeoJSON = useMemo(() =>
        activeLayers.military ? buildFlightLayerGeoJSON(data?.military_flights, milConfig, flightHelpers) : null,
        [activeLayers.military, data?.military_flights, flightHelpers]);

    const shipsGeoJSON = useMemo(() =>
        buildShipsGeoJSON(data?.ships, activeLayers, inView, interpShip),
        [activeLayers.ships_military, activeLayers.ships_cargo, activeLayers.ships_civilian, activeLayers.ships_passenger, activeLayers.ships_tracked_yachts, data?.ships, inView]);

    // Extract cluster label positions via shared hook
    const shipClusters = useClusterLabels(mapRef, 'ships', shipsGeoJSON);
    const eqClusters = useClusterLabels(mapRef, 'earthquakes', earthquakesGeoJSON);

    const carriersGeoJSON = useMemo(() =>
        activeLayers.ships_military ? buildCarriersGeoJSON(data?.ships) : null,
        [activeLayers.ships_military, data?.ships]);

    const activeRouteGeoJSON = useMemo(() => {
        if (!selectedEntity || !data) return null;

        // Polymorphic entity lookup — runtime guards ensure correct type access
        let entity: any = null;
        if (selectedEntity.type === 'flight') entity = data?.commercial_flights?.find((f) => f.icao24 === selectedEntity.id);
        else if (selectedEntity.type === 'private_flight') entity = data?.private_flights?.find((f) => f.icao24 === selectedEntity.id);
        else if (selectedEntity.type === 'military_flight') entity = data?.military_flights?.find((f) => f.icao24 === selectedEntity.id);
        else if (selectedEntity.type === 'private_jet') entity = data?.private_jets?.find((f) => f.icao24 === selectedEntity.id);
        else if (selectedEntity.type === 'tracked_flight') entity = data?.tracked_flights?.find((f) => f.icao24 === selectedEntity.id);
        else if (selectedEntity.type === 'ship') entity = data?.ships?.find((s) => s.mmsi === selectedEntity.id);

        if (!entity) return null;

        const currentLoc = [entity.lng, entity.lat];
        let originLoc = entity.origin_loc;
        let destLoc = entity.dest_loc;

        if (dynamicRoute && dynamicRoute.orig_loc && dynamicRoute.dest_loc) {
            originLoc = dynamicRoute.orig_loc;
            destLoc = dynamicRoute.dest_loc;
            // Also override display names so NewsFeed shows the resolved airport info
            if (dynamicRoute.origin_name) entity.origin_name = dynamicRoute.origin_name;
            if (dynamicRoute.dest_name) entity.dest_name = dynamicRoute.dest_name;
        }

        const features = [];
        // Extract IATA codes from "IATA: Airport Name" format
        const originCode = (entity.origin_name || '').split(':')[0]?.trim() || '';
        const destCode = (entity.dest_name || '').split(':')[0]?.trim() || '';

        if (originLoc) {
            features.push({
                type: 'Feature',
                properties: { type: 'route-origin' },
                geometry: { type: 'LineString', coordinates: [currentLoc, originLoc] }
            });
            // Airport dot at origin
            features.push({
                type: 'Feature',
                properties: { type: 'airport', code: originCode, role: 'DEP' },
                geometry: { type: 'Point', coordinates: originLoc }
            });
        }
        if (destLoc) {
            features.push({
                type: 'Feature',
                properties: { type: 'route-dest' },
                geometry: { type: 'LineString', coordinates: [currentLoc, destLoc] }
            });
            // Airport dot at destination
            features.push({
                type: 'Feature',
                properties: { type: 'airport', code: destCode, role: 'ARR' },
                geometry: { type: 'Point', coordinates: destLoc }
            });
        }

        if (features.length === 0) return null;
        return { type: 'FeatureCollection', features };
    }, [selectedEntity, data, dynamicRoute]);

    // Trail history GeoJSON: shows where the SELECTED aircraft has been (only for no-route flights)
    const trailGeoJSON = useMemo(() => {
        if (!selectedEntity || !data) return null;

        let entity: any = null;
        if (selectedEntity.type === 'flight') entity = data?.commercial_flights?.find((f) => f.icao24 === selectedEntity.id);
        else if (selectedEntity.type === 'private_flight') entity = data?.private_flights?.find((f) => f.icao24 === selectedEntity.id);
        else if (selectedEntity.type === 'military_flight') entity = data?.military_flights?.find((f) => f.icao24 === selectedEntity.id);
        else if (selectedEntity.type === 'private_jet') entity = data?.private_jets?.find((f) => f.icao24 === selectedEntity.id);
        else if (selectedEntity.type === 'tracked_flight') entity = data?.tracked_flights?.find((f) => f.icao24 === selectedEntity.id);

        if (!entity || !entity.trail || entity.trail.length < 2) return null;
        if (entity.origin_name && entity.origin_name !== 'UNKNOWN') return null;

        const coords = entity.trail.map((p: any) => [p[1] ?? p.lng, p[0] ?? p.lat]);
        if (entity.lat != null && entity.lng != null) {
            coords.push([entity.lng, entity.lat]);
        }

        return {
            type: 'FeatureCollection',
            features: [{
                type: 'Feature',
                properties: { type: 'trail' },
                geometry: { type: 'LineString', coordinates: coords }
            }]
        };
    }, [selectedEntity, data]);

    const spreadAlerts = useMemo(() => {
        if (!data?.news) return [];
        return spreadAlertItems(data.news, viewState.zoom, dismissedAlerts);
    }, [data?.news, Math.round(viewState.zoom), dismissedAlerts]);

    // Tracked flights GeoJSON with interpolation
    const trackedFlightsGeoJSON = useMemo(() => {
        if (!activeLayers.tracked || !data?.tracked_flights) return null;

        // Tracked icon maps by aircraft shape and alert color
        const trackedIconMap: Record<string, Record<string, string>> = {
            heli: { '#ff1493': 'svgHeliPink', pink: 'svgHeliPink', red: 'svgHeliAlertRed', blue: 'svgHeliBlue', darkblue: 'svgHeliDarkBlue', yellow: 'svgHeli', orange: 'svgHeliOrange', purple: 'svgHeliPurple', '#32cd32': 'svgHeliLime', black: 'svgHeliBlack', white: 'svgHeliWhiteAlert' },
            airliner: { '#ff1493': 'svgAirlinerPink', pink: 'svgAirlinerPink', red: 'svgAirlinerRed', blue: 'svgAirlinerBlue', darkblue: 'svgAirlinerDarkBlue', yellow: 'svgAirlinerYellow', orange: 'svgAirlinerOrange', purple: 'svgAirlinerPurple', '#32cd32': 'svgAirlinerLime', black: 'svgAirlinerBlack', white: 'svgAirlinerWhite' },
            turboprop: { '#ff1493': 'svgTurbopropPink', pink: 'svgTurbopropPink', red: 'svgTurbopropRed', blue: 'svgTurbopropBlue', darkblue: 'svgTurbopropDarkBlue', yellow: 'svgTurbopropYellow', orange: 'svgTurbopropOrange', purple: 'svgTurbopropPurple', '#32cd32': 'svgTurbopropLime', black: 'svgTurbopropBlack', white: 'svgTurbopropWhite' },
            bizjet: { '#ff1493': 'svgBizjetPink', pink: 'svgBizjetPink', red: 'svgBizjetRed', blue: 'svgBizjetBlue', darkblue: 'svgBizjetDarkBlue', yellow: 'svgBizjetYellow', orange: 'svgBizjetOrange', purple: 'svgBizjetPurple', '#32cd32': 'svgBizjetLime', black: 'svgBizjetBlack', white: 'svgBizjetWhite' },
        };

        const features: any[] = [];
        for (let i = 0; i < data.tracked_flights.length; i++) {
            const f = data.tracked_flights[i];
            if (f.lat == null || f.lng == null) continue;

            const [lng, lat] = interpFlight(f);
            const alertColor = f.alert_color || 'white';
            const acType = classifyAircraft(f.model, f.aircraft_category);
            const grounded = f.alt != null && f.alt <= 100;
            const icaoHex = (f.icao24 || '').toUpperCase();
            const isPotus = POTUS_ICAOS.has(icaoHex);
            const potusIcon = acType === 'heli' ? 'svgPotusHeli' : 'svgPotusPlane';
            const iconId = isPotus ? potusIcon : grounded ? GROUNDED_ICON_MAP[acType] : (trackedIconMap[acType]?.[alertColor] || trackedIconMap.airliner[alertColor] || 'svgAirlinerWhite');
            const displayName = f.alert_operator || f.operator || f.owner || f.name || f.callsign || f.icao24 || "UNKNOWN";

            features.push({
                type: 'Feature',
                properties: { id: f.icao24 || i, type: 'tracked_flight', callsign: String(displayName), rotation: f.heading || 0, iconId },
                geometry: { type: 'Point', coordinates: [lng, lat] }
            });
        }
        return { type: 'FeatureCollection', features };
    }, [activeLayers.tracked, data?.tracked_flights, dtSeconds]);

    const uavGeoJSON = useMemo(() =>
        activeLayers.military ? buildUavGeoJSON(data?.uavs, inView) : null,
        [activeLayers.military, data?.uavs, inView]);

    // UAV range circles removed — real ADS-B drones don't have a fixed orbit center

    const gdeltGeoJSON = useMemo(() =>
        activeLayers.global_incidents ? buildGdeltGeoJSON(data?.gdelt, inView) : null,
        [activeLayers.global_incidents, data?.gdelt, inView]);

    const liveuaGeoJSON = useMemo(() =>
        activeLayers.global_incidents ? buildLiveuaGeoJSON(data?.liveuamap, inView) : null,
        [activeLayers.global_incidents, data?.liveuamap, inView]);

    const frontlineGeoJSON = useMemo(() =>
        activeLayers.ukraine_frontline ? buildFrontlineGeoJSON(data?.frontlines) : null,
        [activeLayers.ukraine_frontline, data?.frontlines]);



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
        cctvGeoJSON && 'cctv-layer',
        kiwisdrGeoJSON && 'kiwisdr-clusters',
        kiwisdrGeoJSON && 'kiwisdr-layer',
        internetOutagesGeoJSON && 'internet-outages-layer',
        dataCentersGeoJSON && 'datacenters-layer',
        militaryBasesGeoJSON && 'military-bases-layer',
        ethNodesGeoJSON && 'eth-nodes-layer',
        firmsGeoJSON && 'firms-viirs-layer'
    ].filter(Boolean) as string[];


    // --- Imperative source updates: bypass React reconciliation for GeoJSON layers ---
    const mapForHook = mapReady ? mapRef.current : null;
    useImperativeSource(mapForHook, 'commercial-flights', commFlightsGeoJSON);
    useImperativeSource(mapForHook, 'private-flights', privFlightsGeoJSON);
    useImperativeSource(mapForHook, 'private-jets', privJetsGeoJSON);
    useImperativeSource(mapForHook, 'military-flights', milFlightsGeoJSON);
    useImperativeSource(mapForHook, 'tracked-flights', trackedFlightsGeoJSON);
    useImperativeSource(mapForHook, 'uavs', uavGeoJSON);
    useImperativeSource(mapForHook, 'satellites', satellitesGeoJSON);
    useImperativeSource(mapForHook, 'firms-fires', firmsGeoJSON, 2000);

    const handleMouseMove = useCallback((evt: any) => {
        if (onMouseCoords) onMouseCoords({ lat: evt.lngLat.lat, lng: evt.lngLat.lng });
    }, [onMouseCoords]);

    const opacityFilter: any = selectedEntity
        ? ['case', ['all', ['==', ['get', 'type'], selectedEntity.type], ['==', ['get', 'id'], selectedEntity.id]], 1.0, 0.0]
        : 1.0;

    return (
        <div className={`relative h-full w-full z-0 isolate ${selectedEntity && ['region_dossier', 'gdelt', 'liveuamap', 'news'].includes(selectedEntity.type) ? 'map-focus-active' : ''}`}>
            <Map
                ref={mapRef}
                reuseMaps
                maxTileCacheSize={200}
                fadeDuration={0}
                initialViewState={viewState}
                onMove={evt => {
                    setViewState(evt.viewState);
                    onViewStateChange?.({ zoom: evt.viewState.zoom, latitude: evt.viewState.latitude });
                    // Debounce bounds update to avoid thrashing during drag
                    if (boundsTimerRef.current) clearTimeout(boundsTimerRef.current);
                    boundsTimerRef.current = setTimeout(updateBounds, 500);
                }}
                onMouseMove={handleMouseMove}
                onContextMenu={(evt) => {
                    evt.preventDefault();
                    onRightClick?.({ lat: evt.lngLat.lat, lng: evt.lngLat.lng });
                }}
                mapStyle={mapThemeStyle as any}
                mapLib={maplibregl}
                onLoad={onMapLoad}
                onIdle={updateBounds}
                interactiveLayerIds={activeInteractiveLayerIds}
                onClick={(e) => {
                    // Measurement mode: place waypoints instead of selecting entities
                    if (measureMode && onMeasureClick) {
                        onMeasureClick({ lat: e.lngLat.lat, lng: e.lngLat.lng });
                        return;
                    }
                    if (selectedEntity) {
                        onEntityClick?.(null);
                    } else if (e.features && e.features.length > 0) {
                        const feature = e.features[0];
                        const props = feature.properties || {};

                        // If the clicked feature is a cluster, zoom into it instead of selecting an entity
                        if (props.cluster) {
                            mapRef.current?.flyTo({
                                center: [e.lngLat.lng, e.lngLat.lat],
                                zoom: viewState.zoom + 2,
                                duration: 500
                            });
                            return;
                        }
                        onEntityClick?.({
                            id: props.id,
                            type: props.type,
                            name: props.name,
                            media_url: props.media_url,
                            extra: props
                        });
                    } else {
                        onEntityClick?.(null);
                    }
                }}
            >
                {/* Esri World Imagery — high-res static satellite (zoom 0-18+) */}
                {activeLayers.highres_satellite && (
                    <Source
                        id="esri-world-imagery"
                        type="raster"
                        tiles={['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}']}
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
                                'raster-fade-duration': 300
                            }}
                        />
                    </Source>
                )}
                {/* Esri Reference Overlay — borders, labels, cities on top of satellite imagery */}
                {activeLayers.highres_satellite && (
                    <Source
                        id="esri-reference-overlay"
                        type="raster"
                        tiles={['https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}']}
                        tileSize={256}
                        maxzoom={18}
                    >
                        <Layer
                            id="esri-reference-overlay-layer"
                            type="raster"
                            paint={{
                                'raster-opacity': 0.9,
                                'raster-fade-duration': 300
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
                        tiles={[`https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/MODIS_Terra_CorrectedReflectance_TrueColor/default/${gibsDate}/GoogleMapsCompatible_Level9/{z}/{y}/{x}.jpg`]}
                        tileSize={256}
                        maxzoom={9}
                    >
                        <Layer
                            id="gibs-modis-layer"
                            type="raster"
                            beforeId="imagery-ceiling"
                            paint={{
                                'raster-opacity': gibsOpacity ?? 0.6,
                                'raster-fade-duration': 0
                            }}
                        />
                    </Source>
                )}

                {/* NASA FIRMS VIIRS — fire hotspot icons from FIRMS CSV feed */}
                {/* firms-fires: data pushed imperatively via useImperativeSource */}
                    <Source id="firms-fires" type="geojson" data={EMPTY_FC as any} cluster={true} clusterRadius={40} clusterMaxZoom={10}>
                        {/* Cluster fire icons — flame shape to differentiate from Global Incidents circles */}
                        <Layer
                            id="firms-clusters"
                            type="symbol"
                            filter={['has', 'point_count']}
                            layout={{
                                'icon-image': ['step', ['get', 'point_count'],
                                    'fire-cluster-sm', 10, 'fire-cluster-md', 50, 'fire-cluster-lg', 200, 'fire-cluster-xl'],
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
                                'icon-size': ['interpolate', ['linear'], ['zoom'],
                                    2, 0.4,
                                    5, 0.6,
                                    8, 0.8,
                                    12, 1.0
                                ],
                                'icon-allow-overlap': true,
                                'icon-ignore-placement': true,
                            }}
                        />
                    </Source>

                {/* SOLAR TERMINATOR — night overlay */}
                {activeLayers.day_night && nightGeoJSON && (
                    <Source id="night-overlay" type="geojson" data={nightGeoJSON as any}>
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

                {/* commercial/private/military flights: data pushed imperatively */}
                    <Source id="commercial-flights" type="geojson" data={EMPTY_FC as any}>
                        <Layer
                            id="commercial-flights-layer"
                            type="symbol"
                            layout={{
                                'icon-image': ['get', 'iconId'],
                                'icon-size': 0.8,
                                'icon-allow-overlap': true,
                                'icon-rotate': ['get', 'rotation'],
                                'icon-rotation-alignment': 'map'
                            }}
                            paint={{ 'icon-opacity': opacityFilter }}
                        />
                    </Source>

                    <Source id="private-flights" type="geojson" data={EMPTY_FC as any}>
                        <Layer
                            id="private-flights-layer"
                            type="symbol"
                            layout={{
                                'icon-image': ['get', 'iconId'],
                                'icon-size': 0.8,
                                'icon-allow-overlap': true,
                                'icon-rotate': ['get', 'rotation'],
                                'icon-rotation-alignment': 'map'
                            }}
                            paint={{ 'icon-opacity': opacityFilter }}
                        />
                    </Source>

                    <Source id="private-jets" type="geojson" data={EMPTY_FC as any}>
                        <Layer
                            id="private-jets-layer"
                            type="symbol"
                            layout={{
                                'icon-image': ['get', 'iconId'],
                                'icon-size': 0.8,
                                'icon-allow-overlap': true,
                                'icon-rotate': ['get', 'rotation'],
                                'icon-rotation-alignment': 'map'
                            }}
                            paint={{ 'icon-opacity': opacityFilter }}
                        />
                    </Source>

                    <Source id="military-flights" type="geojson" data={EMPTY_FC as any}>
                        <Layer
                            id="military-flights-layer"
                            type="symbol"
                            layout={{
                                'icon-image': ['get', 'iconId'],
                                'icon-size': 0.8,
                                'icon-allow-overlap': true,
                                'icon-rotate': ['get', 'rotation'],
                                'icon-rotation-alignment': 'map'
                            }}
                            paint={{ 'icon-opacity': opacityFilter }}
                        />
                    </Source>

                {shipsGeoJSON && (
                    <Source
                        id="ships"
                        type="geojson"
                        data={shipsGeoJSON as any}
                        cluster={true}
                        clusterMaxZoom={8}
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
                                    10, 15,
                                    100, 20,
                                    1000, 25,
                                    5000, 30
                                ],
                                'circle-stroke-width': 2,
                                'circle-stroke-color': 'rgba(59, 130, 246, 1.0)'
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
                            minzoom={4}
                            filter={['!', ['has', 'point_count']]}
                            layout={{
                                'icon-image': ['get', 'iconId'],
                                'icon-size': 0.8,
                                'icon-allow-overlap': true,
                                'icon-rotate': ['get', 'rotation'],
                                'icon-rotation-alignment': 'map'
                            }}
                            paint={{
                                'icon-opacity': opacityFilter
                            }}
                        />
                    </Source>
                )}

                {carriersGeoJSON && (
                    <Source id="carriers" type="geojson" data={carriersGeoJSON as any}>
                        <Layer
                            id="carriers-layer"
                            type="symbol"
                            layout={{
                                'icon-image': 'svgCarrier',
                                'icon-size': 0.8,
                                'icon-allow-overlap': true,
                                'icon-rotate': ['get', 'rotation'],
                                'icon-rotation-alignment': 'map'
                            }}
                            paint={{ 'icon-opacity': opacityFilter }}
                        />
                    </Source>
                )}


                {activeRouteGeoJSON && (
                    <Source id="active-route" type="geojson" data={activeRouteGeoJSON as any}>
                        <Layer
                            id="active-route-layer"
                            type="line"
                            filter={['in', ['get', 'type'], ['literal', ['route-origin', 'route-dest']]]}
                            paint={{
                                'line-color': [
                                    'match',
                                    ['get', 'type'],
                                    'route-origin', '#38bdf8',
                                    'route-dest', '#fcd34d',
                                    '#ffffff'
                                ],
                                'line-width': 2,
                                'line-dasharray': [2, 2],
                                'line-opacity': 0.8
                            }}
                        />
                        {/* Airport dots at origin/destination */}
                        <Layer
                            id="airport-dots"
                            type="circle"
                            filter={['==', ['get', 'type'], 'airport']}
                            paint={{
                                'circle-radius': 5,
                                'circle-color': ['match', ['get', 'role'], 'DEP', '#38bdf8', 'ARR', '#fcd34d', '#ffffff'],
                                'circle-stroke-color': '#000',
                                'circle-stroke-width': 1.5,
                                'circle-opacity': 0.9
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
                                'text-color': ['match', ['get', 'role'], 'DEP', '#38bdf8', 'ARR', '#fcd34d', '#ffffff'],
                                'text-halo-color': '#000',
                                'text-halo-width': 1.5,
                            }}
                        />
                    </Source>
                )}

                {/* Flight trail history (where the aircraft has been) */}
                {trailGeoJSON && (
                    <Source id="flight-trail" type="geojson" data={trailGeoJSON as any}>
                        <Layer
                            id="flight-trail-layer"
                            type="line"
                            paint={{
                                'line-color': '#22d3ee',
                                'line-width': 2,
                                'line-opacity': 0.6,
                            }}
                        />
                    </Source>
                )}

                {/* tracked-flights & UAVs: data pushed imperatively */}
                    <Source id="tracked-flights" type="geojson" data={EMPTY_FC as any}>
                        {/* Gold halo ring — POTUS aircraft only (Air Force One/Two, Marine One) */}
                        <Layer
                            id="tracked-flights-halo"
                            type="circle"
                            filter={['any',
                                ['==', ['get', 'iconId'], 'svgPotusPlane'],
                                ['==', ['get', 'iconId'], 'svgPotusHeli'],
                            ]}
                            paint={{
                                'circle-radius': 18,
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
                                'icon-size': ['case',
                                    ['==', ['get', 'iconId'], 'svgPotusPlane'], 1.3,
                                    ['==', ['get', 'iconId'], 'svgPotusHeli'], 1.3,
                                    0.8
                                ],
                                'icon-allow-overlap': true,
                                'icon-rotate': ['get', 'rotation'],
                                'icon-rotation-alignment': 'map'
                            }}
                            paint={{ 'icon-opacity': opacityFilter }}
                        />
                    </Source>

                    <Source id="uavs" type="geojson" data={EMPTY_FC as any}>
                        <Layer
                            id="uav-layer"
                            type="symbol"
                            layout={{
                                'icon-image': ['get', 'iconId'],
                                'icon-size': 0.8,
                                'icon-allow-overlap': true,
                                'icon-rotate': ['get', 'rotation'],
                                'icon-rotation-alignment': 'map'
                            }}
                            paint={{ 'icon-opacity': opacityFilter }}
                        />
                    </Source>

                {/* UAV range circles removed — real ADS-B data has no fixed orbit */}

                {gdeltGeoJSON && (
                    <Source id="gdelt" type="geojson" data={gdeltGeoJSON as any}>
                        <Layer
                            id="gdelt-layer"
                            type="circle"
                            minzoom={4}
                            paint={{
                                'circle-radius': 5,
                                'circle-color': '#ff8c00',
                                'circle-stroke-color': '#ff0000',
                                'circle-stroke-width': 1,
                                'circle-opacity': 0.7
                            }}
                        />
                    </Source>
                )}

                {liveuaGeoJSON && (
                    <Source id="liveuamap" type="geojson" data={liveuaGeoJSON as any}>
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
                )}

                {/* HTML labels for ship cluster counts (hidden when any entity popup is active) */}
                {shipsGeoJSON && !selectedEntity && <ClusterCountLabels clusters={shipClusters} prefix="sc" />}

                {/* HTML labels for tracked flights — color-matched, zoom-gated for non-HVA */}
                {trackedFlightsGeoJSON && !selectedEntity && data?.tracked_flights && (
                    <TrackedFlightLabels flights={data.tracked_flights} viewState={viewState} inView={inView} interpFlight={interpFlight} />
                )}

                {/* HTML labels for carriers (orange names, with ESTIMATED badge for OSINT positions) */}
                {carriersGeoJSON && !selectedEntity && data?.ships && (
                    <CarrierLabels ships={data.ships} inView={inView} interpShip={interpShip} />
                )}

                {/* HTML labels for tracked yachts (pink owner names) */}
                {shipsGeoJSON && activeLayers.ships_tracked_yachts && !selectedEntity && data?.ships && (
                    <TrackedYachtLabels ships={data.ships} inView={inView} interpShip={interpShip} />
                )}

                {/* HTML labels for earthquake cluster counts (hidden when any entity popup is active) */}
                {earthquakesGeoJSON && !selectedEntity && <ClusterCountLabels clusters={eqClusters} prefix="eqc" />}

                {/* HTML labels for UAVs (orange names) */}
                {uavGeoJSON && !selectedEntity && data?.uavs && (
                    <UavLabels uavs={data.uavs} inView={inView} />
                )}

                {/* HTML labels for earthquakes (yellow) - only show when zoomed in (~2000 miles = zoom ~5) */}
                {earthquakesGeoJSON && !selectedEntity && viewState.zoom >= 5 && data?.earthquakes && (
                    <EarthquakeLabels earthquakes={data.earthquakes} inView={inView} />
                )}

                {/* Maplibre HTML Custom Markers for high-importance Threat Overlays (highest z-index) */}
                {activeLayers.global_incidents && (
                    <ThreatMarkers spreadAlerts={spreadAlerts} viewState={viewState} selectedEntity={selectedEntity} onEntityClick={onEntityClick} onDismiss={(alertKey: string) => { setDismissedAlerts(prev => new Set(prev).add(alertKey)); if (selectedEntity?.type === 'news') onEntityClick?.(null); }} />
                )}

                {frontlineGeoJSON && (
                    <Source id="frontlines" type="geojson" data={frontlineGeoJSON as any}>
                        <Layer
                            id="ukraine-frontline-layer"
                            type="fill"
                            paint={{
                                'fill-color': '#ff0000',
                                'fill-opacity': 0.3,
                                'fill-outline-color': '#ff5500'
                            }}
                        />
                    </Source>
                )}

                {earthquakesGeoJSON && (
                    <Source
                        id="earthquakes"
                        type="geojson"
                        data={earthquakesGeoJSON as any}
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
                                'circle-radius': [
                                    'step',
                                    ['get', 'point_count'],
                                    12,
                                    5, 16,
                                    10, 20,
                                    20, 24
                                ],
                                'circle-stroke-width': 2,
                                'circle-stroke-color': 'rgba(255, 200, 0, 1.0)'
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
                                'icon-allow-overlap': true
                            }}
                            paint={{ 'icon-opacity': 1.0 }}
                        />
                    </Source>
                )}

                {/* GPS Jamming Zones — red translucent grid squares */}
                {jammingGeoJSON && (
                    <Source id="gps-jamming" type="geojson" data={jammingGeoJSON as any}>
                        <Layer
                            id="gps-jamming-fill"
                            type="fill"
                            paint={{
                                'fill-color': '#ff0040',
                                'fill-opacity': ['get', 'opacity']
                            }}
                        />
                        <Layer
                            id="gps-jamming-outline"
                            type="line"
                            paint={{
                                'line-color': '#ff0040',
                                'line-width': 1.5,
                                'line-opacity': 0.6
                            }}
                        />
                        <Layer
                            id="gps-jamming-label"
                            type="symbol"
                            layout={{
                                'text-field': ['concat', 'GPS JAM ', ['to-string', ['round', ['*', 100, ['get', 'ratio']]]], '%'],
                                'text-size': [
                                    'interpolate', ['linear'], ['zoom'],
                                    2, 8,
                                    5, 10,
                                    8, 12
                                ],
                                'text-allow-overlap': false,
                                'text-ignore-placement': false
                            }}
                            paint={{
                                'text-color': '#ff4060',
                                'text-halo-color': '#000000',
                                'text-halo-width': 1.5
                            }}
                        />
                    </Source>
                )}

                {/* CCTV Cameras — clustered green dots */}
                {cctvGeoJSON && (
                    <Source id="cctv" type="geojson" data={cctvGeoJSON as any} cluster={true} clusterRadius={50} clusterMaxZoom={14}>
                        {/* Cluster circles — green, sized by count */}
                        <Layer
                            id="cctv-clusters"
                            type="circle"
                            filter={['has', 'point_count']}
                            paint={{
                                'circle-color': '#22c55e',
                                'circle-radius': [
                                    'step', ['get', 'point_count'],
                                    14, 10,
                                    18, 50,
                                    24, 200,
                                    30
                                ],
                                'circle-opacity': 0.8,
                                'circle-stroke-width': 2,
                                'circle-stroke-color': '#16a34a'
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
                                'text-allow-overlap': true
                            }}
                            paint={{
                                'text-color': '#ffffff',
                                'text-halo-color': '#000000',
                                'text-halo-width': 1
                            }}
                        />
                        {/* Individual camera dots */}
                        <Layer
                            id="cctv-layer"
                            type="circle"
                            filter={['!', ['has', 'point_count']]}
                            paint={{
                                'circle-color': '#22c55e',
                                'circle-radius': [
                                    'interpolate', ['linear'], ['zoom'],
                                    2, 2,
                                    8, 4,
                                    14, 6
                                ],
                                'circle-opacity': 0.9,
                                'circle-stroke-width': 1,
                                'circle-stroke-color': '#16a34a'
                            }}
                        />
                    </Source>
                )}

                {/* KiwiSDR Receivers — radio tower icons with pulse rings */}
                {kiwisdrGeoJSON && (
                    <Source id="kiwisdr" type="geojson" data={kiwisdrGeoJSON as any} cluster={true} clusterRadius={50} clusterMaxZoom={14}>
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
                )}

                {/* Internet Outages — region-level grey markers with % and labels */}
                {internetOutagesGeoJSON && (
                    <Source id="internet-outages" type="geojson" data={internetOutagesGeoJSON as any}>
                        {/* Outer ring */}
                        <Layer
                            id="internet-outages-pulse"
                            type="circle"
                            paint={{
                                'circle-radius': ['interpolate', ['linear'], ['get', 'severity'], 0, 14, 50, 18, 80, 22],
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
                                'circle-radius': ['interpolate', ['linear'], ['get', 'severity'], 0, 6, 50, 9, 80, 12],
                                'circle-color': '#888888',
                                'circle-stroke-width': 2,
                                'circle-stroke-color': 'rgba(0, 0, 0, 0.6)',
                                'circle-opacity': 0.9
                            }}
                        />
                        {/* Severity % inside circle */}
                        <Layer
                            id="internet-outages-pct"
                            type="symbol"
                            layout={{
                                'text-field': ['case', ['>', ['get', 'severity'], 0], ['concat', ['to-string', ['get', 'severity']], '%'], '!'],
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
                )}

                {/* Data Center positions */}
                {dataCentersGeoJSON && (
                    <Source id="datacenters" type="geojson" data={dataCentersGeoJSON as any} cluster={true} clusterRadius={30} clusterMaxZoom={8}>
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
                )}

                {/* Military Base positions */}
                {militaryBasesGeoJSON && (
                    <Source id="military-bases" type="geojson" data={militaryBasesGeoJSON as any}>
                        <Layer
                            id="military-bases-layer"
                            type="circle"
                            paint={{
                                'circle-color': ['match', ['get', 'side'], 'red', '#ef4444', 'green', '#22c55e', '#3b82f6'],
                                'circle-radius': ['interpolate', ['linear'], ['zoom'], 2, 4, 6, 7, 10, 10],
                                'circle-opacity': 0.8,
                                'circle-stroke-width': 2,
                                'circle-stroke-color': ['match', ['get', 'side'], 'red', '#fca5a5', 'green', '#86efac', '#93c5fd'],
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
                                'text-color': ['match', ['get', 'side'], 'red', '#fca5a5', 'green', '#86efac', '#93c5fd'],
                                'text-halo-color': 'rgba(0,0,0,0.9)',
                                'text-halo-width': 1,
                            }}
                        />
                    </Source>
                )}

                {/* Ethereum Node positions */}
                {ethNodesGeoJSON && (
                    <Source id="eth-nodes" type="geojson" data={ethNodesGeoJSON as any} cluster={true} clusterRadius={35} clusterMaxZoom={8}>
                        {/* Cluster circles */}
                        <Layer
                            id="eth-nodes-clusters"
                            type="circle"
                            filter={['has', 'point_count']}
                            paint={{
                                'circle-color': '#0e7490',
                                'circle-radius': ['step', ['get', 'point_count'], 12, 10, 16, 50, 20],
                                'circle-opacity': 0.7,
                                'circle-stroke-width': 1,
                                'circle-stroke-color': '#67e8f9',
                            }}
                        />
                        <Layer
                            id="eth-nodes-cluster-count"
                            type="symbol"
                            filter={['has', 'point_count']}
                            layout={{
                                'text-field': '{point_count_abbreviated}',
                                'text-font': ['Noto Sans Bold'],
                                'text-size': 10,
                                'text-allow-overlap': true,
                            }}
                            paint={{
                                'text-color': '#cffafe',
                            }}
                        />
                        {/* Individual node icons */}
                        <Layer
                            id="eth-nodes-layer"
                            type="symbol"
                            filter={['!', ['has', 'point_count']]}
                            layout={{
                                'icon-image': 'eth-node',
                                'icon-size': ['interpolate', ['linear'], ['zoom'], 2, 0.5, 6, 0.7, 10, 1.0],
                                'icon-allow-overlap': true,
                                'text-field': ['step', ['zoom'], '', 8, ['get', 'name']],
                                'text-font': ['Noto Sans Regular'],
                                'text-size': 9,
                                'text-offset': [0, 1.2],
                                'text-anchor': 'top',
                                'text-allow-overlap': false,
                            }}
                            paint={{
                                'text-color': '#67e8f9',
                                'text-halo-color': 'rgba(0,0,0,0.9)',
                                'text-halo-width': 1,
                            }}
                        />
                    </Source>
                )}

                {/* Satellite positions — mission-type icons */}
                {/* satellites: data pushed imperatively */}
                    <Source id="satellites" type="geojson" data={EMPTY_FC as any}>
                        <Layer
                            id="satellites-layer"
                            type="symbol"
                            layout={{
                                'icon-image': ['get', 'iconId'],
                                'icon-size': [
                                    'interpolate', ['linear'], ['zoom'],
                                    0, 0.4,
                                    3, 0.5,
                                    6, 0.7,
                                    10, 1.0
                                ],
                                'icon-allow-overlap': true,
                            }}
                        />
                    </Source>

                {/* Satellite click popup */}
                {selectedEntity?.type === 'satellite' && (() => {
                    const sat = data?.satellites?.find((s: any) => s.id === selectedEntity.id);
                    if (!sat) return null;
                    const missionLabels: Record<string, string> = {
                        military_recon: '🔴 MILITARY RECON', military_sar: '🔴 MILITARY SAR',
                        sar: '🔷 SAR IMAGING', sigint: '🟠 SIGINT / ELINT',
                        navigation: '🔵 NAVIGATION', early_warning: '🟣 EARLY WARNING',
                        commercial_imaging: '🟢 COMMERCIAL IMAGING', space_station: '🏠 SPACE STATION',
                        communication: '📡 COMMUNICATION'
                    };
                    return (
                        <Popup
                            longitude={sat.lng} latitude={sat.lat}
                            closeButton={false} closeOnClick={false}
                            onClose={() => onEntityClick?.(null)}
                            anchor="bottom" offset={12}
                        >
                            <div className="map-popup border border-cyan-500/30">
                                <div className="map-popup-title text-[#00c8ff]">
                                    🛰️ {sat.name}
                                </div>
                                <div className="map-popup-row text-[#8899aa]">
                                    NORAD ID: <span className="text-white">{sat.id}</span>
                                </div>
                                {sat.sat_type && (
                                    <div className="map-popup-row">
                                        Type: <span className="text-[#ffcc00]">{sat.sat_type}</span>
                                    </div>
                                )}
                                {sat.country && (
                                    <div className="map-popup-row">
                                        Country: <span className="text-white">{sat.country}</span>
                                    </div>
                                )}
                                {sat.mission && (
                                    <div className="map-popup-row font-semibold">
                                        {missionLabels[sat.mission] || `⚪ ${sat.mission.toUpperCase()}`}
                                    </div>
                                )}
                                <div className="map-popup-row">
                                    Altitude: <span className="text-[#44ff88]">{sat.alt_km?.toLocaleString()} km</span>
                                </div>
                                {sat.wiki && (
                                    <div className="mt-2 border-t border-[var(--border-primary)]/50 pt-2">
                                        <WikiImage wikiUrl={sat.wiki} label={sat.sat_type || sat.name} maxH="max-h-28" accent="hover:border-cyan-500/50" />
                                    </div>
                                )}
                            </div>
                        </Popup>
                    );
                })()}

                {/* UAV click popup — real ADS-B detected drones */}
                {selectedEntity?.type === 'uav' && (() => {
                    const uav = data?.uavs?.find((u: any) => u.id === selectedEntity.id);
                    if (!uav) return null;
                    return (
                        <Popup
                            longitude={uav.lng} latitude={uav.lat}
                            closeButton={false} closeOnClick={false}
                            onClose={() => onEntityClick?.(null)}
                            anchor="bottom" offset={12}
                        >
                            <div className="map-popup border border-red-500/40">
                                <div className="map-popup-title text-[#ff4444]">
                                    {uav.callsign}
                                </div>
                                <div className="map-popup-subtitle text-[#ff8844]">
                                    LIVE ADS-B TRANSPONDER
                                </div>
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
                                        <WikiImage wikiUrl={uav.wiki} label={uav.callsign} maxH="max-h-28" accent="hover:border-red-500/50" />
                                    </div>
                                )}
                            </div>
                        </Popup>
                    );
                })()}

                {/* KiwiSDR Receivers Popup */}
                {selectedEntity?.type === 'kiwisdr' && (() => {
                    const receiver = data?.kiwisdr?.find((k: any) => k.name === selectedEntity.name || String(k.id) === String(selectedEntity.id));
                    // use extra if available from the click event, otherwise fallback
                    const props = selectedEntity.extra || receiver || {} as any;
                    const lat = props.lat ?? selectedEntity.extra?.lat ?? selectedEntity.extra?.geometry?.coordinates?.[1];
                    const lng = props.lon ?? (props as any).lng ?? selectedEntity.extra?.lon ?? selectedEntity.extra?.geometry?.coordinates?.[0];
                    if (lat == null || lng == null) return null;
                    return (
                        <Popup
                            longitude={lng} latitude={lat}
                            closeButton={false} closeOnClick={false}
                            onClose={() => onEntityClick?.(null)}
                            anchor="bottom" offset={12}
                        >
                            <div className="map-popup !border-amber-500/40" style={{ borderWidth: 1, borderStyle: 'solid' }}>
                                <div className="flex justify-between items-start mb-1">
                                    <div className="map-popup-title text-amber-400">
                                        {(props.name || 'UNKNOWN SDR RECEIVER').toUpperCase()}
                                    </div>
                                    <button onClick={() => onEntityClick?.(null)} className="text-[var(--text-secondary)] hover:text-[var(--text-primary)] ml-2">✕</button>
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
                                        Active Users: <span className={props.users >= (props.users_max || 4) ? 'text-red-400' : 'text-amber-400'}>{props.users} / {props.users_max || '?'}</span>
                                    </div>
                                )}
                                {props.antenna && (
                                    <div className="map-popup-row">
                                        Antenna: <span className="text-[#888]">{props.antenna}</span>
                                    </div>
                                )}
                                {props.bands && (
                                    <div className="map-popup-row">
                                        Bands: <span className="text-cyan-400">{(Number(props.bands.split('-')[0]) / 1e6).toFixed(0)}-{(Number(props.bands.split('-')[1]) / 1e6).toFixed(0)} MHz</span>
                                    </div>
                                )}

                                <div className="flex items-center gap-2 mt-3 pt-2 border-t border-[var(--border-primary)]">
                                    <button
                                        onClick={(e) => {
                                            e.stopPropagation();
                                            // The extra object contains the raw GeoJSON properties, including URL
                                            if (setTrackedSdr) {
                                                setTrackedSdr({
                                                    lat, lon: lng,
                                                    name: props.name,
                                                    url: props.url,
                                                    users: props.users,
                                                    users_max: props.users_max,
                                                    bands: props.bands,
                                                    antenna: props.antenna,
                                                    location: props.location
                                                });
                                            }
                                            onEntityClick?.(null);
                                        }}
                                        className="flex-1 text-center px-2 py-1.5 rounded bg-amber-950/40 border border-amber-500/30 hover:bg-amber-900/60 hover:border-amber-400 text-amber-400 text-[9px] font-mono tracking-widest transition-colors flex justify-center items-center gap-1.5"
                                    >
                                        <Activity size={10} /> TRACK SIGNAL
                                    </button>
                                    
                                    {props.url && (
                                        <a
                                            href={props.url}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                            className="px-2 py-1.5 rounded bg-amber-500/10 border border-amber-500/50 hover:bg-amber-500/20 hover:border-amber-400 text-amber-400 text-[9px] font-mono tracking-widest transition-colors"
                                            title="Open SDR interface in new tab"
                                        >
                                            <Play size={10} className="fill-amber-400/20" />
                                        </a>
                                    )}
                                </div>
                            </div>
                        </Popup>
                    );
                })()}

                {/* Ship / carrier click popup */}
                {selectedEntity?.type === 'ship' && (() => {
                    const ship = data?.ships?.find((s: any, i: number) => {
                        return (s.mmsi || s.name || `ship-${i}`) === selectedEntity.id ||
                               (s.mmsi || s.name || `carrier-${i}`) === selectedEntity.id;
                    });
                    if (!ship) return null;
                    const [iLng, iLat] = interpShip(ship);
                    return (
                        <Popup
                            longitude={iLng} latitude={iLat}
                            closeButton={false} closeOnClick={false}
                            onClose={() => onEntityClick?.(null)}
                            anchor="bottom" offset={12}
                        >
                            <div className="map-popup" style={{ borderWidth: 1, borderStyle: 'solid', borderColor: ship.yacht_alert ? 'rgba(255,105,180,0.5)' : ship.type === 'carrier' ? 'rgba(255,170,0,0.5)' : 'rgba(59,130,246,0.4)' }}>
                                <div className="flex justify-between items-start mb-1">
                                    <div className="map-popup-title" style={{ color: ship.yacht_alert ? '#FF69B4' : ship.type === 'carrier' ? '#ffaa00' : '#3b82f6' }}>
                                        {ship.name || 'UNKNOWN VESSEL'}
                                    </div>
                                    <button onClick={() => onEntityClick?.(null)} className="text-[var(--text-secondary)] hover:text-[var(--text-primary)] ml-2">✕</button>
                                </div>
                                {ship.estimated && (
                                    <div className="map-popup-subtitle text-[#ff6644] border-b border-[#ff664450] pb-1">
                                        ESTIMATED POSITION — {ship.source || 'OSINT DERIVED'}
                                    </div>
                                )}
                                {ship.type && (
                                    <div className="map-popup-row">
                                        Type: <span className="text-white capitalize">{ship.type.replace('_', ' ')}</span>
                                    </div>
                                )}
                                {ship.mmsi && (
                                    <div className="map-popup-row">
                                        MMSI: <span className="text-[#888]">{ship.mmsi}</span>
                                    </div>
                                )}
                                {ship.imo && (
                                    <div className="map-popup-row">
                                        IMO: <span className="text-[#888]">{ship.imo}</span>
                                    </div>
                                )}
                                {ship.callsign && (
                                    <div className="map-popup-row">
                                        Callsign: <span className="text-[#00e5ff]">{ship.callsign}</span>
                                    </div>
                                )}
                                {ship.country && (
                                    <div className="map-popup-row">
                                        Flag: <span className="text-white">{ship.country}</span>
                                    </div>
                                )}
                                {ship.destination && (
                                    <div className="map-popup-row">
                                        Destination: <span className="text-[#44ff88]">{ship.destination}</span>
                                    </div>
                                )}
                                {typeof ship.sog === 'number' && ship.sog > 0 && (
                                    <div className="map-popup-row">
                                        Speed: <span className="text-[#00e5ff]">{ship.sog.toFixed(1)} kn</span>
                                    </div>
                                )}
                                <div className="map-popup-row">
                                    Heading: <span style={{ color: ship.heading != null ? '#888' : '#ff6644' }}>
                                        {ship.heading != null ? `${Math.round(ship.heading)}°` : 'UNKNOWN'}
                                    </span>
                                </div>
                                {ship.type === 'carrier' && ship.source && (
                                    <div className="mt-1.5 p-[5px_7px] bg-[rgba(255,170,0,0.08)] border border-[rgba(255,170,0,0.3)] rounded text-[9px] tracking-wide">
                                        <div className="text-[#ffaa00] mb-0.5">
                                            SOURCE: {ship.source_url ? (
                                                <a href={ship.source_url} target="_blank" rel="noopener noreferrer"
                                                    className="text-[#00e5ff] underline">{ship.source}</a>
                                            ) : (
                                                <span className="text-white">{ship.source}</span>
                                            )}
                                        </div>
                                        {ship.last_osint_update && (
                                            <div className="text-[#888]">LAST OSINT UPDATE: {new Date(ship.last_osint_update).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' })}</div>
                                        )}
                                        {ship.desc && (
                                            <div className="text-[#aaa] mt-0.5 text-[8px] leading-tight">{ship.desc}</div>
                                        )}
                                    </div>
                                )}
                                {ship.type !== 'carrier' && ship.last_osint_update && (
                                    <div className="map-popup-row">
                                        Last OSINT Update: <span className="text-[#888]">{new Date(ship.last_osint_update).toLocaleDateString()}</span>
                                    </div>
                                )}
                                {ship.yacht_alert && (
                                    <div className="mt-1.5 p-[5px_7px] bg-[rgba(255,105,180,0.08)] border border-[rgba(255,105,180,0.3)] rounded text-[9px] tracking-wide">
                                        <div className="text-[#FF69B4] font-bold mb-0.5">TRACKED YACHT</div>
                                        <div>Owner: <span className="text-white">{ship.yacht_owner}</span></div>
                                        {ship.yacht_builder && <div>Builder: <span className="text-[#888]">{ship.yacht_builder}</span></div>}
                                        {(ship.yacht_length ?? 0) > 0 && <div>Length: <span className="text-[#888]">{ship.yacht_length}m</span></div>}
                                        {(ship.yacht_year ?? 0) > 0 && <div>Year: <span className="text-[#888]">{ship.yacht_year}</span></div>}
                                        {ship.yacht_category && <div>Category: <span className="text-[#FF69B4]">{ship.yacht_category}</span></div>}
                                        {ship.yacht_link && <a href={ship.yacht_link} target="_blank" rel="noopener noreferrer" className="text-[#00e5ff] underline">Wikipedia</a>}
                                    </div>
                                )}
                            </div>
                        </Popup>
                    );
                })()}

                {/* Data Center click popup */}
                {selectedEntity?.type === 'datacenter' && (() => {
                    const dc = data?.datacenters?.find((_: any, i: number) => `dc-${i}` === selectedEntity.id);
                    if (!dc) return null;
                    // Check if any internet outage is in the same country
                    const outagesInCountry = (data?.internet_outages || []).filter((o: any) =>
                        o.country_name && dc.country && o.country_name.toLowerCase() === dc.country.toLowerCase()
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
                                        Address: <span className="text-white">{dc.street}{dc.zip ? ` ${dc.zip}` : ''}</span>
                                    </div>
                                )}
                                {dc.city && (
                                    <div className="map-popup-row">
                                        Location: <span className="text-white">{dc.city}{dc.country ? `, ${dc.country}` : ''}</span>
                                    </div>
                                )}
                                {!dc.city && dc.country && (
                                    <div className="map-popup-row">
                                        Country: <span className="text-white">{dc.country}</span>
                                    </div>
                                )}
                                {outagesInCountry.length > 0 && (
                                    <div className="mt-1.5 px-2 py-1 bg-red-500/15 border border-red-400/40 rounded text-[10px] text-[#ff6b6b]">
                                        OUTAGE IN REGION — {outagesInCountry.map((o: any) => `${o.region_name} (${o.severity}%)`).join(', ')}
                                    </div>
                                )}
                                <div className="mt-1.5 text-[9px] text-violet-600 tracking-wider">
                                    DATA CENTER
                                </div>
                            </div>
                        </Popup>
                    );
                })()}

                {selectedEntity?.type === 'military_base' && (() => {
                    const base = data?.military_bases?.find((_: any, i: number) => `milbase-${i}` === selectedEntity.id);
                    if (!base) return null;
                    const branchLabel: Record<string, string> = {
                        air_force: 'AIR FORCE', navy: 'NAVY', marines: 'MARINES', army: 'ARMY',
                        gsdf: 'GSDF (陸自)', msdf: 'MSDF (海自)', asdf: 'ASDF (空自)',
                        missile: 'MISSILE FORCES', nuclear: 'NUCLEAR FACILITY',
                    };
                    const isAdversary = ['China', 'Russia', 'North Korea'].includes(base.country);
                    const isROC = base.country === 'Taiwan';
                    const accentColor = isAdversary ? 'red' : isROC ? 'green' : 'blue';
                    const borderCls = isAdversary ? 'border-red-400/40' : isROC ? 'border-green-400/40' : 'border-blue-400/40';
                    const textCls = isAdversary ? 'text-[#fca5a5]' : isROC ? 'text-[#86efac]' : 'text-[#93c5fd]';
                    const titleCls = isAdversary ? 'text-red-400 border-b border-red-400/20' : isROC ? 'text-green-400 border-b border-green-400/20' : 'text-blue-400 border-b border-blue-400/20';
                    const footerCls = isAdversary ? 'text-red-600' : isROC ? 'text-green-600' : 'text-blue-600';
                    return (
                        <Popup
                            longitude={base.lng}
                            latitude={base.lat}
                            closeButton={false}
                            closeOnClick={false}
                            onClose={() => onEntityClick?.(null)}
                            className="threat-popup"
                            maxWidth="280px"
                        >
                            <div className={`map-popup bg-[#1a1035] border ${borderCls} ${textCls} min-w-[200px]`}>
                                <div className={`map-popup-title ${titleCls} pb-1`}>
                                    {base.name}
                                </div>
                                <div className="map-popup-row">
                                    Operator: <span className="text-white">{base.operator}</span>
                                </div>
                                <div className="map-popup-row">
                                    Location: <span className="text-white">{base.country}</span>
                                </div>
                                <div className={`mt-1.5 text-[9px] ${footerCls} tracking-wider`}>
                                    MILITARY BASE — {branchLabel[base.branch] || base.branch.toUpperCase()}
                                </div>
                            </div>
                        </Popup>
                    );
                })()}

                {/* Ethereum Node click popup */}
                {selectedEntity?.type === 'eth_node' && (() => {
                    const node = data?.eth_nodes?.find((_: any, i: number) => `eth-${i}` === selectedEntity.id);
                    if (!node) return null;
                    const maskedIp = node.ip.replace(/\.\d+$/, '.***');
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
                            <div className="map-popup bg-[#0a1a2a] border border-cyan-400/40 text-[#cffafe] min-w-[200px]">
                                <div className="map-popup-title text-cyan-400 border-b border-cyan-400/20 pb-1">
                                    Ethereum Node
                                </div>
                                <div className="map-popup-row">
                                    IP: <span className="text-white font-mono">{maskedIp}:{node.port}</span>
                                </div>
                                {node.city && (
                                    <div className="map-popup-row">
                                        Location: <span className="text-white">{node.city}{node.country ? `, ${node.country}` : ''}</span>
                                    </div>
                                )}
                                {!node.city && node.country && (
                                    <div className="map-popup-row">
                                        Country: <span className="text-white">{node.country}</span>
                                    </div>
                                )}
                                {node.isp && (
                                    <div className="map-popup-row">
                                        ISP: <span className="text-[#67e8f9]">{node.isp}</span>
                                    </div>
                                )}
                                {node.asn && (
                                    <div className="map-popup-row">
                                        ASN: <span className="text-[#67e8f9] font-mono">{node.asn}</span>
                                    </div>
                                )}
                                {node.org && (
                                    <div className="map-popup-row">
                                        Org: <span className="text-white">{node.org}</span>
                                    </div>
                                )}
                                {node.os && (
                                    <div className="map-popup-row">
                                        OS: <span className="text-[#67e8f9]">{node.os}</span>
                                    </div>
                                )}
                                <div className="mt-1.5 text-[9px] text-cyan-700 tracking-wider">
                                    ETH NODE · PORT 30303
                                </div>
                            </div>
                        </Popup>
                    );
                })()}

                {(() => {
                    if (selectedEntity?.type !== 'gdelt' || !data?.gdelt) return null;
                    const item = data.gdelt.find((g: any) => (g.properties?.name || String(g.geometry?.coordinates)) === selectedEntity.id);
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
                            <div className="bg-[var(--bg-secondary)]/90 backdrop-blur-md border border-orange-800 rounded-lg flex flex-col z-[100] font-mono shadow-[0_4px_30px_rgba(255,140,0,0.4)] pointer-events-auto overflow-hidden w-[300px]">
                                <div className="p-2 border-b border-orange-500/30 bg-orange-950/40 flex justify-between items-center">
                                    <h2 className="text-[10px] tracking-widest font-bold text-orange-400 flex items-center gap-1">
                                        <AlertTriangle size={12} className="text-orange-400" /> NEWS ON THE GROUND
                                    </h2>
                                    <button onClick={() => onEntityClick?.(null)} className="text-[var(--text-secondary)] hover:text-[var(--text-primary)]">✕</button>
                                </div>
                                <div className="p-3 flex flex-col gap-2">
                                    <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-1">
                                        <span className="text-[var(--text-muted)] text-[9px]">LOCATION</span>
                                        <span className="text-white text-[10px] font-bold text-right ml-2 break-words max-w-[150px]">{item.properties?.name || 'UNKNOWN REGION'}</span>
                                    </div>
                                    <div className="flex flex-col gap-1 mt-1">
                                        <span className="text-[var(--text-muted)] text-[9px]">LATEST REPORTS: ({item.properties?.count || 1})</span>
                                        <div className="flex flex-col gap-2 max-h-[200px] overflow-y-auto styled-scrollbar mt-1">
                                            {(() => {
                                                const urls: string[] = item.properties?._urls_list || [];
                                                const headlines: string[] = item.properties?._headlines_list || [];
                                                if (urls.length === 0) return <span className="text-[var(--text-muted)] text-[10px]">No articles available.</span>;
                                                return urls.map((url: string, idx: number) => {
                                                    const headline = headlines[idx] || '';
                                                    let domain = '';
                                                    try { domain = new URL(url).hostname.replace('www.', ''); } catch { domain = ''; }
                                                    return (
                                                        <a
                                                            key={idx}
                                                            href={url}
                                                            target="_blank"
                                                            rel="noopener noreferrer"
                                                            onClick={(e) => e.stopPropagation()}
                                                            className="block py-1.5 border-b border-[var(--border-primary)]/50 last:border-0 cursor-pointer group"
                                                            style={{ pointerEvents: 'all' }}
                                                        >
                                                            <span className="text-orange-400 text-[11px] font-bold leading-tight group-hover:text-orange-300 block">
                                                                {headline || domain || 'View Article'}
                                                            </span>
                                                            {headline && domain && (
                                                                <span className="text-[var(--text-muted)] text-[9px] block mt-0.5">{domain}</span>
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

                {
                    selectedEntity?.type === 'liveuamap' && data?.liveuamap?.find((l: any) => String(l.id) === String(selectedEntity.id)) && (() => {
                        const item = data.liveuamap.find((l: any) => String(l.id) === String(selectedEntity.id));
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
                                            <AlertTriangle size={12} className="text-yellow-400" /> REGIONAL TACTICAL EVENT
                                        </h2>
                                        <button onClick={() => onEntityClick?.(null)} className="text-[var(--text-secondary)] hover:text-[var(--text-primary)]">✕</button>
                                    </div>
                                    <div className="p-3 flex flex-col gap-2">
                                        <div className="flex flex-col gap-1 border-b border-[var(--border-primary)] pb-1">
                                            <span className="text-yellow-400 text-[10px] font-bold leading-tight">{item.title}</span>
                                        </div>
                                        <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-1 mt-1">
                                            <span className="text-[var(--text-muted)] text-[9px]">TIME</span>
                                            <span className="text-white text-[9px] font-bold">{item.timestamp || 'UNKNOWN'}</span>
                                        </div>
                                        {item.link && (
                                            <div className="flex justify-between items-center mt-1">
                                                <a href={item.link} target="_blank" rel="noreferrer" className="text-yellow-400 hover:text-yellow-300 text-[9px] font-bold underline">
                                                    View Source Report
                                                </a>
                                            </div>
                                        )}
                                    </div>
                                </div>
                            </Popup>
                        );
                    })()
                }

                {(() => {
                    if (selectedEntity?.type !== 'news' || !data?.news) return null;
                    const item = data.news.find((n: any) => {
                        const key = n.alertKey || `${n.title}|${n.coords?.[0]},${n.coords?.[1]}`;
                        return key === selectedEntity.id;
                    });
                    if (!item) return null;
                        let threatColor = "text-yellow-400";
                        let borderColor = "border-yellow-800";
                        let bgHeaderColor = "bg-yellow-950/40";
                        let shadowColor = "rgba(255,255,0,0.3)";
                        if (item.risk_score >= 8) {
                            threatColor = "text-red-400";
                            borderColor = "border-red-800";
                            bgHeaderColor = "bg-red-950/40";
                            shadowColor = "rgba(255,0,0,0.3)";
                        } else if (item.risk_score <= 4) {
                            threatColor = "text-green-400";
                            borderColor = "border-green-800";
                            bgHeaderColor = "bg-green-950/40";
                            shadowColor = "rgba(0,255,0,0.3)";
                        }

                    if (!item.coords) return null;

                        return (
                            <Popup
                                longitude={item.coords[1]}
                                latitude={item.coords[0]}
                                closeButton={false}
                                closeOnClick={false}
                                onClose={() => onEntityClick?.(null)}
                                anchor="bottom"
                                offset={25}
                            >
                                <div className={`bg-[var(--bg-secondary)]/90 backdrop-blur-md border ${borderColor} rounded-lg flex flex-col z-[100] font-mono shadow-[0_4px_30px_${shadowColor}] pointer-events-auto overflow-hidden w-[280px]`}>
                                    <div className={`p-2 border-b ${borderColor}/50 ${bgHeaderColor} flex justify-between items-center`}>
                                        <h2 className={`text-[10px] tracking-widest font-bold ${threatColor} flex items-center gap-1`}>
                                            <AlertTriangle size={12} className={threatColor} /> THREAT INTERCEPT
                                        </h2>
                                        <div className="flex items-center gap-2">
                                            <span className={`text-[10px] ${threatColor} font-mono font-bold animate-pulse`}>LVL: {item.risk_score}/10</span>
                                            <button onClick={() => onEntityClick?.(null)} className="text-[var(--text-secondary)] hover:text-[var(--text-primary)]">✕</button>
                                        </div>
                                    </div>
                                    <div className="p-3 flex flex-col gap-2">
                                        <div className="flex flex-col gap-1 border-b border-[var(--border-primary)] pb-1">
                                            <span className={`text-[10px] font-bold leading-tight ${threatColor}`}>{item.title}</span>
                                        </div>
                                        <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-1 mt-1">
                                            <span className="text-[var(--text-muted)] text-[9px]">SOURCE</span>
                                            <span className="text-white text-[9px] font-bold text-right ml-2">{item.source || 'UNKNOWN'}</span>
                                        </div>
                                        {item.machine_assessment && (
                                            <div className="mt-1 p-2 bg-black/60 border border-cyan-800/50 rounded-sm text-[8px] text-cyan-400 font-mono leading-tight relative overflow-hidden shadow-[inset_0_0_10px_rgba(0,255,255,0.05)]">
                                                <div className="absolute top-0 left-0 w-[2px] h-full bg-cyan-500 animate-pulse"></div>
                                                <span className="font-bold text-white">&gt;_ SYS.ANALYSIS: </span>
                                                <span className="text-cyan-300 opacity-90">{item.machine_assessment}</span>
                                            </div>
                                        )}
                                        {item.link && (
                                            <div className="flex justify-between items-center mt-1">
                                                <a href={item.link} target="_blank" rel="noreferrer" className={`${threatColor} hover:text-red-300 text-[9px] font-bold underline`}>
                                                    View Details
                                                </a>
                                            </div>
                                        )}
                                    </div>
                                </div>
                            </Popup>
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
                {selectedEntity?.type === 'region_dossier' && selectedEntity.extra && regionDossier?.sentinel2 && !regionDossierLoading && (() => {
                    const s2 = regionDossier.sentinel2;
                    const imgUrl = s2.fullres_url || s2.thumbnail_url;
                    return (
                        <div
                            style={{
                                position: 'fixed',
                                top: 0,
                                left: 0,
                                right: 0,
                                bottom: 0,
                                zIndex: 9999,
                                background: 'rgba(0,0,0,0.85)',
                                backdropFilter: 'blur(8px)',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                padding: '60px 20px 80px 20px',
                            }}
                            onClick={(e) => { if (e.target === e.currentTarget) onEntityClick(null); }}
                            onKeyDown={(e: any) => { if (e.key === 'Escape') onEntityClick(null); }}
                            tabIndex={-1}
                            ref={(el) => el?.focus()}
                        >
                            <div style={{
                                background: 'rgba(0,0,0,0.95)',
                                border: '1px solid rgba(34,197,94,0.5)',
                                borderRadius: 12,
                                overflow: 'hidden',
                                maxWidth: 'calc(100vw - 40px)',
                                maxHeight: 'calc(100vh - 80px)',
                                display: 'flex',
                                flexDirection: 'column',
                                boxShadow: '0 0 60px rgba(34,197,94,0.3)',
                            }}>
                                {/* Header bar */}
                                <div style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: 'space-between',
                                    padding: '10px 16px',
                                    background: 'rgba(20,83,45,0.4)',
                                    borderBottom: '1px solid rgba(34,197,94,0.3)',
                                }}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                        <div style={{ width: 6, height: 6, borderRadius: '50%', background: '#4ade80', animation: 'pulse 2s infinite' }} />
                                        <span style={{ fontSize: 11, color: '#4ade80', fontFamily: 'monospace', letterSpacing: '0.2em', fontWeight: 'bold' }}>
                                            SENTINEL-2 IMAGERY
                                        </span>
                                    </div>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                                        <span style={{ fontSize: 10, color: 'rgba(134,239,172,0.6)', fontFamily: 'monospace' }}>
                                            {selectedEntity.extra.lat.toFixed(4)}, {selectedEntity.extra.lng.toFixed(4)}
                                        </span>
                                        <button
                                            onClick={() => onEntityClick(null)}
                                            style={{
                                                background: 'rgba(239,68,68,0.2)',
                                                border: '1px solid rgba(239,68,68,0.4)',
                                                borderRadius: 6,
                                                color: '#ef4444',
                                                fontSize: 10,
                                                fontFamily: 'monospace',
                                                padding: '4px 10px',
                                                cursor: 'pointer',
                                                letterSpacing: '0.1em',
                                            }}
                                        >
                                            ✕ CLOSE
                                        </button>
                                    </div>
                                </div>

                                {s2.found ? (
                                    <>
                                        {/* Metadata row */}
                                        <div style={{
                                            display: 'flex',
                                            alignItems: 'center',
                                            justifyContent: 'space-between',
                                            padding: '8px 16px',
                                            fontSize: 11,
                                            fontFamily: 'monospace',
                                            borderBottom: '1px solid rgba(20,83,45,0.4)',
                                        }}>
                                            <span style={{ color: '#86efac' }}>{s2.platform}</span>
                                            <span style={{ color: '#4ade80', fontWeight: 'bold' }}>{s2.datetime?.slice(0, 10)}</span>
                                            <span style={{ color: '#86efac' }}>{s2.cloud_cover?.toFixed(0)}% cloud</span>
                                        </div>

                                        {/* Image */}
                                        {imgUrl ? (
                                            <div style={{ flex: 1, overflow: 'auto', display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: 400 }}>
                                                <img
                                                    src={imgUrl}
                                                    alt="Sentinel-2 scene"
                                                    style={{
                                                        maxWidth: '100%',
                                                        maxHeight: 'calc(100vh - 220px)',
                                                        objectFit: 'contain',
                                                        display: 'block',
                                                    }}
                                                />
                                            </div>
                                        ) : (
                                            <div style={{ padding: '40px 16px', fontSize: 11, color: 'rgba(134,239,172,0.5)', fontFamily: 'monospace', textAlign: 'center' }}>
                                                Scene found — no preview available
                                            </div>
                                        )}

                                        {/* Action buttons */}
                                        {imgUrl && (
                                            <div style={{
                                                display: 'flex',
                                                alignItems: 'center',
                                                justifyContent: 'center',
                                                gap: 12,
                                                padding: '10px 16px',
                                                background: 'rgba(20,83,45,0.3)',
                                                borderTop: '1px solid rgba(34,197,94,0.2)',
                                            }}>
                                                <a
                                                    href={imgUrl}
                                                    download={`sentinel2_${selectedEntity.extra.lat.toFixed(4)}_${selectedEntity.extra.lng.toFixed(4)}.jpg`}
                                                    target="_blank"
                                                    rel="noopener noreferrer"
                                                    style={{
                                                        background: 'rgba(34,197,94,0.2)',
                                                        border: '1px solid rgba(34,197,94,0.5)',
                                                        borderRadius: 6,
                                                        color: '#4ade80',
                                                        fontSize: 10,
                                                        fontFamily: 'monospace',
                                                        padding: '6px 16px',
                                                        cursor: 'pointer',
                                                        textDecoration: 'none',
                                                        letterSpacing: '0.15em',
                                                        fontWeight: 'bold',
                                                    }}
                                                >
                                                    ⬇ DOWNLOAD
                                                </a>
                                                <button
                                                    onClick={async () => {
                                                        try {
                                                            const resp = await fetch(imgUrl);
                                                            const blob = await resp.blob();
                                                            await navigator.clipboard.write([
                                                                new ClipboardItem({ [blob.type]: blob })
                                                            ]);
                                                        } catch {
                                                            // fallback: copy URL
                                                            await navigator.clipboard.writeText(imgUrl);
                                                        }
                                                    }}
                                                    style={{
                                                        background: 'rgba(34,197,94,0.15)',
                                                        border: '1px solid rgba(34,197,94,0.4)',
                                                        borderRadius: 6,
                                                        color: '#4ade80',
                                                        fontSize: 10,
                                                        fontFamily: 'monospace',
                                                        padding: '6px 16px',
                                                        cursor: 'pointer',
                                                        letterSpacing: '0.15em',
                                                        fontWeight: 'bold',
                                                    }}
                                                >
                                                    📋 COPY
                                                </button>
                                                <a
                                                    href={imgUrl}
                                                    target="_blank"
                                                    rel="noopener noreferrer"
                                                    style={{
                                                        background: 'rgba(16,185,129,0.15)',
                                                        border: '1px solid rgba(16,185,129,0.4)',
                                                        borderRadius: 6,
                                                        color: '#10b981',
                                                        fontSize: 10,
                                                        fontFamily: 'monospace',
                                                        padding: '6px 16px',
                                                        cursor: 'pointer',
                                                        textDecoration: 'none',
                                                        letterSpacing: '0.15em',
                                                        fontWeight: 'bold',
                                                    }}
                                                >
                                                    ↗ OPEN FULL RES
                                                </a>
                                            </div>
                                        )}
                                    </>
                                ) : (
                                    <div style={{ padding: '40px 16px', fontSize: 11, color: 'rgba(134,239,172,0.5)', fontFamily: 'monospace', textAlign: 'center' }}>
                                        No clear imagery in last 30 days
                                    </div>
                                )}
                            </div>
                        </div>
                    );
                })()}

                {/* MEASUREMENT LINES */}
                {measurePoints && measurePoints.length >= 2 && (
                    <Source id="measure-lines" type="geojson" data={{
                        type: 'FeatureCollection',
                        features: [{
                            type: 'Feature',
                            properties: {},
                            geometry: {
                                type: 'LineString',
                                coordinates: measurePoints.map((p: any) => [p.lng, p.lat])
                            }
                        }]
                    } as any}>
                        <Layer
                            id="measure-lines-layer"
                            type="line"
                            paint={{
                                'line-color': '#00ffff',
                                'line-width': 2,
                                'line-dasharray': [4, 3],
                                'line-opacity': 0.8,
                            }}
                        />
                    </Source>
                )}

                {/* MEASUREMENT WAYPOINTS */}
                {measurePoints && measurePoints.map((pt: any, idx: number) => (
                    <Marker key={`measure-${idx}`} longitude={pt.lng} latitude={pt.lat} anchor="center">
                        <div className="flex flex-col items-center pointer-events-none">
                            <div className="w-6 h-6 rounded-full border-2 border-cyan-400 animate-ping absolute opacity-20" />
                            <div className="w-4 h-4 rounded-full bg-cyan-500 border-2 border-cyan-300 shadow-[0_0_12px_rgba(0,255,255,0.6)] flex items-center justify-center">
                                <span className="text-[7px] font-mono font-bold text-black">{idx + 1}</span>
                            </div>
                        </div>
                    </Marker>
                ))}

            </Map>
        </div>
    );
}

import dynamic from "next/dynamic";

export default dynamic(() => Promise.resolve(MaplibreViewer), {
    ssr: false
});
