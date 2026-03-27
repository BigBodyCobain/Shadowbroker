/// <reference lib="webworker" />

import { interpolatePosition } from '@/utils/positioning';
import { classifyAircraft } from '@/utils/aircraftClassification';
import type { Flight, Ship, SigintSignal } from '@/types/dashboard';
import type { FlightLayerConfig } from '@/components/map/geoJSONBuilders';

type BoundsTuple = [number, number, number, number];
type FC = GeoJSON.FeatureCollection | null;

export type DynamicMapLayersPayload = {
  commercialFlights?: Flight[];
  privateFlights?: Flight[];
  privateJets?: Flight[];
  militaryFlights?: Flight[];
  trackedFlights?: Flight[];
  ships?: Ship[];
  sigint?: SigintSignal[];
  commConfig: FlightLayerConfig;
  privConfig: FlightLayerConfig;
  jetsConfig: FlightLayerConfig;
  milConfig: FlightLayerConfig;
};

export type DynamicMapLayersDataPayload = DynamicMapLayersPayload;

export type DynamicMapLayersBuildPayload = {
  bounds: BoundsTuple;
  dtSeconds: number;
  trackedIcaos: string[];
  activeLayers: {
    flights: boolean;
    private: boolean;
    jets: boolean;
    military: boolean;
    tracked: boolean;
    ships_military: boolean;
    ships_cargo: boolean;
    ships_civilian: boolean;
    ships_passenger: boolean;
    ships_tracked_yachts: boolean;
    sigint_meshtastic: boolean;
    sigint_aprs: boolean;
  };
  activeFilters?: Record<string, string[]>;
};

export type DynamicMapLayersResult = {
  commercialFlightsGeoJSON: FC;
  privateFlightsGeoJSON: FC;
  privateJetsGeoJSON: FC;
  militaryFlightsGeoJSON: FC;
  trackedFlightsGeoJSON: FC;
  shipsGeoJSON: FC;
  meshtasticGeoJSON: FC;
  aprsGeoJSON: FC;
};

type SyncRequest = {
  id: string;
  action: 'sync_dynamic_layers';
  payload: DynamicMapLayersDataPayload;
};

type BuildRequest = {
  id: string;
  action: 'build_dynamic_layers';
  payload: DynamicMapLayersBuildPayload;
};

type WorkerRequest = SyncRequest | BuildRequest;

type WorkerResponse = {
  id: string;
  ok: boolean;
  result?: DynamicMapLayersResult;
  error?: string;
};

const EMPTY_RESULT: DynamicMapLayersResult = {
  commercialFlightsGeoJSON: null,
  privateFlightsGeoJSON: null,
  privateJetsGeoJSON: null,
  militaryFlightsGeoJSON: null,
  trackedFlightsGeoJSON: null,
  shipsGeoJSON: null,
  meshtasticGeoJSON: null,
  aprsGeoJSON: null,
};

const UNBOUNDED_INTERP_SECONDS = Number.POSITIVE_INFINITY;

const TRACKED_GROUNDED_ICON_MAP: Record<string, string> = {
  airliner: 'svgAirlinerGrey',
  turboprop: 'svgTurbopropGrey',
  bizjet: 'svgBizjetGrey',
  heli: 'svgHeliGrey',
};

const TRACKED_ICON_MAP: Record<string, Record<string, string>> = {
  heli: {
    '#ff1493': 'svgHeliPink',
    pink: 'svgHeliPink',
    red: 'svgHeliAlertRed',
    blue: 'svgHeliBlue',
    darkblue: 'svgHeliDarkBlue',
    yellow: 'svgHeli',
    orange: 'svgHeliOrange',
    purple: 'svgHeliPurple',
    '#32cd32': 'svgHeliLime',
    black: 'svgHeliBlack',
    white: 'svgHeliWhiteAlert',
  },
  airliner: {
    '#ff1493': 'svgAirlinerPink',
    pink: 'svgAirlinerPink',
    red: 'svgAirlinerRed',
    blue: 'svgAirlinerBlue',
    darkblue: 'svgAirlinerDarkBlue',
    yellow: 'svgAirlinerYellow',
    orange: 'svgAirlinerOrange',
    purple: 'svgAirlinerPurple',
    '#32cd32': 'svgAirlinerLime',
    black: 'svgAirlinerBlack',
    white: 'svgAirlinerWhite',
  },
  turboprop: {
    '#ff1493': 'svgTurbopropPink',
    pink: 'svgTurbopropPink',
    red: 'svgTurbopropRed',
    blue: 'svgTurbopropBlue',
    darkblue: 'svgTurbopropDarkBlue',
    yellow: 'svgTurbopropYellow',
    orange: 'svgTurbopropOrange',
    purple: 'svgTurbopropPurple',
    '#32cd32': 'svgTurbopropLime',
    black: 'svgTurbopropBlack',
    white: 'svgTurbopropWhite',
  },
  bizjet: {
    '#ff1493': 'svgBizjetPink',
    pink: 'svgBizjetPink',
    red: 'svgBizjetRed',
    blue: 'svgBizjetBlue',
    darkblue: 'svgBizjetDarkBlue',
    yellow: 'svgBizjetYellow',
    orange: 'svgBizjetOrange',
    purple: 'svgBizjetPurple',
    '#32cd32': 'svgBizjetLime',
    black: 'svgBizjetBlack',
    white: 'svgBizjetWhite',
  },
};

const POTUS_ICAOS = new Set(['adfdf8', 'adfdf9', 'adfdfa', 'adfdfb', 'adfdfc', 'adfdff']);
let dynamicData: DynamicMapLayersDataPayload = {
  commConfig: {} as FlightLayerConfig,
  privConfig: {} as FlightLayerConfig,
  jetsConfig: {} as FlightLayerConfig,
  milConfig: {} as FlightLayerConfig,
};

function inView(lat: number, lng: number, bounds: BoundsTuple): boolean {
  return lng >= bounds[0] && lng <= bounds[2] && lat >= bounds[1] && lat <= bounds[3];
}

function interpFlightPosition(f: Flight, dtSeconds: number): [number, number] {
  if (!f.speed_knots || f.speed_knots <= 0 || dtSeconds <= 0) return [f.lng, f.lat];
  if (f.alt != null && f.alt <= 100) return [f.lng, f.lat];
  if (dtSeconds < 1) return [f.lng, f.lat];
  const heading = f.true_track || f.heading || 0;
  const [newLat, newLng] = interpolatePosition(
    f.lat,
    f.lng,
    heading,
    f.speed_knots,
    dtSeconds,
    0,
    UNBOUNDED_INTERP_SECONDS,
  );
  return [newLng, newLat];
}

function interpShipPosition(s: Ship, dtSeconds: number): [number, number] {
  if (typeof s.sog !== 'number' || !s.sog || s.sog <= 0 || dtSeconds <= 0) return [s.lng, s.lat];
  const heading = (typeof s.cog === 'number' ? s.cog : 0) || s.heading || 0;
  const [newLat, newLng] = interpolatePosition(
    s.lat,
    s.lng,
    heading,
    s.sog,
    dtSeconds,
    0,
    UNBOUNDED_INTERP_SECONDS,
  );
  return [newLng, newLat];
}

function buildFlightLayerGeoJSONWorker(
  flights: Flight[] | undefined,
  config: FlightLayerConfig,
  bounds: BoundsTuple,
  dtSeconds: number,
  trackedIcaos: Set<string>,
): FC {
  if (!flights?.length) return null;
  const { colorMap, groundedMap, typeLabel, idPrefix, milSpecialMap, useTrackHeading } = config;
  const features: GeoJSON.Feature[] = [];

  for (let i = 0; i < flights.length; i += 1) {
    const f = flights[i];
    if (f.lat == null || f.lng == null) continue;
    const [iLng, iLat] = interpFlightPosition(f, dtSeconds);
    if (!inView(iLat, iLng, bounds)) continue;
    if (f.icao24 && trackedIcaos.has(f.icao24.toLowerCase())) continue;

    const acType = classifyAircraft(f.model, f.aircraft_category);
    const grounded = f.alt != null && f.alt <= 100;

    let iconId: string;
    if (milSpecialMap) {
      const milType = ('military_type' in f ? f.military_type : undefined) || 'default';
      iconId = milSpecialMap[milType] || '';
      if (!iconId) {
        iconId = grounded ? groundedMap[acType] : colorMap[acType];
      } else if (grounded) {
        iconId = groundedMap[acType];
      }
    } else {
      iconId = grounded ? groundedMap[acType] : colorMap[acType];
    }

    const rotation = useTrackHeading ? f.true_track || f.heading || 0 : f.heading || 0;
    features.push({
      type: 'Feature',
      properties: {
        id: f.icao24 || f.callsign || `${idPrefix}${i}`,
        type: typeLabel,
        callsign: f.callsign || f.icao24,
        rotation,
        iconId,
      },
      geometry: { type: 'Point', coordinates: [iLng, iLat] },
    });
  }

  return { type: 'FeatureCollection', features };
}

function buildTrackedFlightsGeoJSONWorker(
  flights: Flight[] | undefined,
  bounds: BoundsTuple,
  dtSeconds: number,
): FC {
  if (!flights?.length) return null;
  const features: GeoJSON.Feature[] = [];

  for (let i = 0; i < flights.length; i += 1) {
    const f = flights[i];
    if (f.lat == null || f.lng == null) continue;
    const [lng, lat] = interpFlightPosition(f, dtSeconds);
    if (!inView(lat, lng, bounds)) continue;

    const alertColor = ('alert_color' in f ? f.alert_color : '') || 'white';
    const acType = classifyAircraft(f.model, f.aircraft_category);
    const grounded = f.alt != null && f.alt <= 100;
    const icaoHex = (f.icao24 || '').toUpperCase();
    const isPotus = POTUS_ICAOS.has(icaoHex.toLowerCase());
    const potusIcon = acType === 'heli' ? 'svgPotusHeli' : 'svgPotusPlane';
    const iconId = isPotus
      ? potusIcon
      : grounded
        ? TRACKED_GROUNDED_ICON_MAP[acType]
        : TRACKED_ICON_MAP[acType]?.[alertColor] ||
          TRACKED_ICON_MAP.airliner[alertColor] ||
          'svgAirlinerWhite';
    const displayName =
      ('alert_operator' in f ? f.alert_operator : '') ||
      ('operator' in f ? f.operator : '') ||
      ('owner' in f ? f.owner : '') ||
      ('name' in f ? f.name : '') ||
      f.callsign ||
      f.icao24 ||
      'UNKNOWN';

    features.push({
      type: 'Feature',
      properties: {
        id: f.icao24 || i,
        type: 'tracked_flight',
        callsign: String(displayName),
        rotation: f.heading || 0,
        iconId,
      },
      geometry: { type: 'Point', coordinates: [lng, lat] },
    });
  }

  return { type: 'FeatureCollection', features };
}

function buildShipsGeoJSONWorker(
  ships: Ship[] | undefined,
  activeLayers: DynamicMapLayersBuildPayload['activeLayers'],
  bounds: BoundsTuple,
  dtSeconds: number,
): FC {
  if (
    !ships?.length ||
    !(
      activeLayers.ships_military ||
      activeLayers.ships_cargo ||
      activeLayers.ships_civilian ||
      activeLayers.ships_passenger ||
      activeLayers.ships_tracked_yachts
    )
  ) {
    return null;
  }

  const features: GeoJSON.Feature[] = [];
  for (let i = 0; i < ships.length; i += 1) {
    const s = ships[i];
    if (s.lat == null || s.lng == null) continue;
    const [iLng, iLat] = interpShipPosition(s, dtSeconds);
    if (!inView(iLat, iLng, bounds)) continue;
    if (s.type === 'carrier') continue;

    const isTrackedYacht = Boolean(s.yacht_alert);
    const isMilitary = s.type === 'military_vessel';
    const isCargo = s.type === 'tanker' || s.type === 'cargo';
    const isPassenger = s.type === 'passenger';

    if (isTrackedYacht) {
      if (!activeLayers.ships_tracked_yachts) continue;
    } else if (isMilitary && !activeLayers.ships_military) continue;
    else if (isCargo && !activeLayers.ships_cargo) continue;
    else if (isPassenger && !activeLayers.ships_passenger) continue;
    else if (!isMilitary && !isCargo && !isPassenger && !activeLayers.ships_civilian) continue;

    let iconId = 'svgShipBlue';
    if (isTrackedYacht) iconId = 'svgShipPink';
    else if (isCargo) iconId = 'svgShipRed';
    else if (s.type === 'yacht' || isPassenger) iconId = 'svgShipWhite';
    else if (isMilitary) iconId = 'svgShipAmber';

    features.push({
      type: 'Feature',
      properties: {
        id: s.mmsi || s.name || `ship-${i}`,
        type: 'ship',
        name: s.name,
        rotation: s.heading || 0,
        iconId,
      },
      geometry: { type: 'Point', coordinates: [iLng, iLat] },
    });
  }

  return { type: 'FeatureCollection', features };
}

function buildSigintGeoJSONWorker(
  signals: SigintSignal[] | undefined,
  source: 'meshtastic' | 'aprs',
  bounds: BoundsTuple,
): FC {
  if (!signals?.length) return null;
  const wanted =
    source === 'meshtastic'
      ? (s: SigintSignal) => s.source === 'meshtastic'
      : (s: SigintSignal) => s.source === 'aprs' || s.source === 'js8call';

  const features: GeoJSON.Feature[] = [];
  for (let i = 0; i < signals.length; i += 1) {
    const sig = signals[i];
    if (!wanted(sig) || sig.lat == null || sig.lng == null) continue;
    if (!inView(sig.lat, sig.lng, bounds)) continue;
    features.push({
      type: 'Feature',
      properties: {
        id: `${sig.source || 'unknown'}:${sig.callsign || 'unknown'}`,
        type: 'sigint',
        name: sig.callsign,
        callsign: sig.callsign,
        source: sig.source,
        confidence: sig.confidence,
        raw_message: sig.raw_message || '',
        snr: sig.snr ?? null,
        frequency: sig.frequency ?? null,
        timestamp: sig.timestamp,
        region: sig.region ?? null,
        channel: sig.channel ?? null,
        status: sig.status ?? null,
        altitude: sig.altitude ?? null,
        emergency: sig.emergency ?? false,
        emergency_keyword: sig.emergency_keyword ?? null,
        from_api: sig.from_api ?? false,
        position_updated_at: sig.position_updated_at ?? null,
        long_name: sig.long_name ?? null,
        hardware: sig.hardware ?? null,
        role: sig.role ?? null,
        battery_level: sig.battery_level ?? null,
        voltage: sig.voltage ?? null,
      },
      geometry: { type: 'Point', coordinates: [sig.lng, sig.lat] },
    });
  }

  return features.length ? { type: 'FeatureCollection', features } : null;
}

/** Apply user-selected filters to flight/ship arrays before building GeoJSON. */
function applyFilters(activeFilters: Record<string, string[]> | undefined) {
  const f = activeFilters;
  if (!f || Object.keys(f).length === 0) {
    return {
      commercial: dynamicData.commercialFlights,
      private_: dynamicData.privateFlights,
      jets: dynamicData.privateJets,
      military: dynamicData.militaryFlights,
      tracked: dynamicData.trackedFlights,
      ships: dynamicData.ships,
    };
  }

  const has = (key: string) => f[key] && f[key].length > 0;
  const set = (key: string) => new Set(f[key]);

  // ── Commercial flights ──
  let commercial = dynamicData.commercialFlights;
  if (commercial && (has('commercial_departure') || has('commercial_arrival') || has('commercial_airline'))) {
    const depSet = has('commercial_departure') ? set('commercial_departure') : null;
    const arrSet = has('commercial_arrival') ? set('commercial_arrival') : null;
    const airSet = has('commercial_airline') ? set('commercial_airline') : null;
    commercial = commercial.filter((fl: any) => {
      if (depSet && !depSet.has(fl.origin_name)) return false;
      if (arrSet && !arrSet.has(fl.dest_name)) return false;
      if (airSet && !airSet.has(fl.airline_code)) return false;
      return true;
    });
  }

  // ── Private flights ──
  let private_ = dynamicData.privateFlights;
  if (private_ && (has('private_callsign') || has('private_aircraft_type'))) {
    const csSet = has('private_callsign') ? set('private_callsign') : null;
    const typeSet = has('private_aircraft_type') ? set('private_aircraft_type') : null;
    private_ = private_.filter((fl: any) => {
      if (csSet && !csSet.has(fl.callsign) && !csSet.has(fl.registration)) return false;
      if (typeSet && !typeSet.has(fl.model)) return false;
      return true;
    });
  }

  // ── Private jets ──
  let jets = dynamicData.privateJets;
  if (jets && (has('private_callsign') || has('private_aircraft_type'))) {
    const csSet = has('private_callsign') ? set('private_callsign') : null;
    const typeSet = has('private_aircraft_type') ? set('private_aircraft_type') : null;
    jets = jets.filter((fl: any) => {
      if (csSet && !csSet.has(fl.callsign) && !csSet.has(fl.registration)) return false;
      if (typeSet && !typeSet.has(fl.model)) return false;
      return true;
    });
  }

  // ── Military flights ──
  let military = dynamicData.militaryFlights;
  if (military && (has('military_country') || has('military_aircraft_type'))) {
    const countrySet = has('military_country') ? set('military_country') : null;
    const typeSet = has('military_aircraft_type') ? set('military_aircraft_type') : null;
    military = military.filter((fl: any) => {
      if (countrySet && !countrySet.has(fl.country)) return false;
      if (typeSet && !typeSet.has(fl.military_type)) return false;
      return true;
    });
  }

  // ── Tracked flights ──
  let tracked = dynamicData.trackedFlights;
  if (tracked && (has('tracked_category') || has('tracked_owner'))) {
    const catSet = has('tracked_category') ? set('tracked_category') : null;
    const ownSet = has('tracked_owner') ? set('tracked_owner') : null;
    tracked = tracked.filter((fl: any) => {
      if (catSet && !catSet.has(fl.alert_category)) return false;
      if (ownSet && !ownSet.has(fl.alert_operator)) return false;
      return true;
    });
  }

  // ── Ships ──
  let ships = dynamicData.ships;
  if (ships && (has('ship_name') || has('ship_type'))) {
    const nameSet = has('ship_name') ? set('ship_name') : null;
    const typeSet = has('ship_type') ? set('ship_type') : null;
    ships = ships.filter((s: any) => {
      if (nameSet && !nameSet.has(s.name)) return false;
      if (typeSet && !typeSet.has(s.type)) return false;
      return true;
    });
  }

  return { commercial, private_, jets, military, tracked, ships };
}

function buildDynamicLayers(payload: DynamicMapLayersBuildPayload): DynamicMapLayersResult {
  const trackedIcaos = new Set(payload.trackedIcaos);
  const filtered = applyFilters(payload.activeFilters);
  return {
    commercialFlightsGeoJSON: payload.activeLayers.flights
      ? buildFlightLayerGeoJSONWorker(
          filtered.commercial,
          dynamicData.commConfig,
          payload.bounds,
          payload.dtSeconds,
          trackedIcaos,
        )
      : null,
    privateFlightsGeoJSON: payload.activeLayers.private
      ? buildFlightLayerGeoJSONWorker(
          filtered.private_,
          dynamicData.privConfig,
          payload.bounds,
          payload.dtSeconds,
          trackedIcaos,
        )
      : null,
    privateJetsGeoJSON: payload.activeLayers.jets
      ? buildFlightLayerGeoJSONWorker(
          filtered.jets,
          dynamicData.jetsConfig,
          payload.bounds,
          payload.dtSeconds,
          trackedIcaos,
        )
      : null,
    militaryFlightsGeoJSON: payload.activeLayers.military
      ? buildFlightLayerGeoJSONWorker(
          filtered.military,
          dynamicData.milConfig,
          payload.bounds,
          payload.dtSeconds,
          trackedIcaos,
        )
      : null,
    trackedFlightsGeoJSON: payload.activeLayers.tracked
      ? buildTrackedFlightsGeoJSONWorker(filtered.tracked, payload.bounds, payload.dtSeconds)
      : null,
    shipsGeoJSON: buildShipsGeoJSONWorker(
      filtered.ships,
      payload.activeLayers,
      payload.bounds,
      payload.dtSeconds,
    ),
    meshtasticGeoJSON: payload.activeLayers.sigint_meshtastic
      ? buildSigintGeoJSONWorker(dynamicData.sigint, 'meshtastic', payload.bounds)
      : null,
    aprsGeoJSON: payload.activeLayers.sigint_aprs
      ? buildSigintGeoJSONWorker(dynamicData.sigint, 'aprs', payload.bounds)
      : null,
  };
}

self.onmessage = (event: MessageEvent<WorkerRequest>) => {
  const { id, action, payload } = event.data;
  try {
    if (action === 'sync_dynamic_layers') {
      dynamicData = payload;
      postMessage({ id, ok: true, result: EMPTY_RESULT } satisfies WorkerResponse);
      return;
    }
    if (action !== 'build_dynamic_layers') {
      postMessage({ id, ok: false, error: 'unsupported_action' } satisfies WorkerResponse);
      return;
    }
    const result = buildDynamicLayers(payload);
    postMessage({ id, ok: true, result } satisfies WorkerResponse);
  } catch (error) {
    const message = error instanceof Error ? error.message : 'worker_error';
    postMessage({ id, ok: false, error: message } satisfies WorkerResponse);
  }
};

export {};
