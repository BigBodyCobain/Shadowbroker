// ─── Pure GeoJSON builder functions ─────────────────────────────────────────
// Extracted from MaplibreViewer to reduce component size and enable unit testing.
// Each function takes data arrays + optional helpers and returns a GeoJSON FeatureCollection or null.

import type { Earthquake, GPSJammingZone, FireHotspot, InternetOutage, DataCenter, MilitaryBase, EthNode, GDELTIncident, LiveUAmapIncident, CCTVCamera, KiwiSDR, FrontlineGeoJSON, UAV, Satellite, Ship, ActiveLayers } from "@/types/dashboard";
import { classifyAircraft } from "@/utils/aircraftClassification";
import { MISSION_COLORS, MISSION_ICON_MAP } from "@/components/map/icons/SatelliteIcons";

type FC = GeoJSON.FeatureCollection | null;
type InViewFilter = (lat: number, lng: number) => boolean;

// ─── Earthquakes ────────────────────────────────────────────────────────────

export function buildEarthquakesGeoJSON(earthquakes?: Earthquake[]): FC {
    if (!earthquakes?.length) return null;
    return {
        type: 'FeatureCollection',
        features: earthquakes.map((eq, i) => {
            if (eq.lat == null || eq.lng == null) return null;
            return {
                type: 'Feature' as const,
                properties: {
                    id: i,
                    type: 'earthquake',
                    name: `[M${eq.mag}]\n${eq.place || 'Unknown Location'}`,
                    title: eq.title,
                },
                geometry: { type: 'Point' as const, coordinates: [eq.lng, eq.lat] }
            };
        }).filter(Boolean) as GeoJSON.Feature[]
    };
}

// ─── GPS Jamming Zones ──────────────────────────────────────────────────────

export function buildJammingGeoJSON(zones?: GPSJammingZone[]): FC {
    if (!zones?.length) return null;
    return {
        type: 'FeatureCollection',
        features: zones.map((zone, i) => {
            const halfDeg = 0.5;
            return {
                type: 'Feature' as const,
                properties: {
                    id: i,
                    severity: zone.severity,
                    ratio: zone.ratio,
                    degraded: zone.degraded,
                    total: zone.total,
                    opacity: zone.severity === 'high' ? 0.45 : zone.severity === 'medium' ? 0.3 : 0.18
                },
                geometry: {
                    type: 'Polygon' as const,
                    coordinates: [[
                        [zone.lng - halfDeg, zone.lat - halfDeg],
                        [zone.lng + halfDeg, zone.lat - halfDeg],
                        [zone.lng + halfDeg, zone.lat + halfDeg],
                        [zone.lng - halfDeg, zone.lat + halfDeg],
                        [zone.lng - halfDeg, zone.lat - halfDeg]
                    ]]
                }
            };
        })
    };
}

// ─── CCTV Cameras ──────────────────────────────────────────────────────────

export function buildCctvGeoJSON(cameras?: CCTVCamera[], inView?: InViewFilter): FC {
    if (!cameras?.length) return null;
    return {
        type: 'FeatureCollection' as const,
        features: cameras.filter(c => c.lat != null && c.lon != null && (!inView || inView(c.lat, c.lon))).map((c, i) => ({
            type: 'Feature' as const,
            properties: {
                id: c.id || i,
                type: 'cctv',
                name: c.direction_facing || 'Camera',
                source_agency: c.source_agency || 'Unknown',
                media_url: c.media_url || '',
                media_type: c.media_type || 'image'
            },
            geometry: { type: 'Point' as const, coordinates: [c.lon, c.lat] }
        }))
    };
}

// ─── KiwiSDR Receivers ─────────────────────────────────────────────────────

export function buildKiwisdrGeoJSON(receivers?: KiwiSDR[], inView?: InViewFilter): FC {
    if (!receivers?.length) return null;
    return {
        type: 'FeatureCollection' as const,
        features: receivers.filter(k => k.lat != null && k.lon != null && (!inView || inView(k.lat, k.lon))).map((k, i) => ({
            type: 'Feature' as const,
            properties: {
                id: i,
                type: 'kiwisdr',
                name: k.name || 'Unknown SDR',
                url: k.url || '',
                users: k.users || 0,
                users_max: k.users_max || 0,
                bands: k.bands || '',
                antenna: k.antenna || '',
                location: k.location || '',
                lat: k.lat,
                lon: k.lon,
            },
            geometry: { type: 'Point' as const, coordinates: [k.lon, k.lat] }
        }))
    };
}

// ─── NASA FIRMS Fires ───────────────────────────────────────────────────────

export function buildFirmsGeoJSON(fires?: FireHotspot[]): FC {
    if (!fires?.length) return null;
    return {
        type: 'FeatureCollection',
        features: fires.map((f, i) => {
            const frp = f.frp || 0;
            const iconId = frp >= 100 ? 'fire-darkred' : frp >= 20 ? 'fire-red' : frp >= 5 ? 'fire-orange' : 'fire-yellow';
            return {
                type: 'Feature' as const,
                properties: {
                    id: i,
                    type: 'firms_fire',
                    name: `Fire ${frp.toFixed(1)} MW`,
                    frp,
                    iconId,
                    brightness: f.brightness || 0,
                    confidence: f.confidence || '',
                    daynight: f.daynight === 'D' ? 'Day' : 'Night',
                    acq_date: f.acq_date || '',
                    acq_time: f.acq_time || '',
                },
                geometry: { type: 'Point' as const, coordinates: [f.lng, f.lat] }
            };
        })
    };
}

// ─── Internet Outages ───────────────────────────────────────────────────────

export function buildInternetOutagesGeoJSON(outages?: InternetOutage[]): FC {
    if (!outages?.length) return null;
    return {
        type: 'FeatureCollection',
        features: outages.map((o) => {
            if (o.lat == null || o.lng == null) return null;
            const severity = o.severity || 0;
            const region = o.region_name || o.region_code || '?';
            const country = o.country_name || o.country_code || '';
            const label = `${region}, ${country}`;
            const detail = `${label}\n${severity}% drop · ${o.datasource || 'IODA'}`;
            return {
                type: 'Feature' as const,
                properties: {
                    id: o.region_code || region,
                    type: 'internet_outage',
                    name: label,
                    country,
                    region,
                    level: o.level,
                    severity,
                    datasource: o.datasource || '',
                    detail,
                },
                geometry: { type: 'Point' as const, coordinates: [o.lng, o.lat] }
            };
        }).filter(Boolean) as GeoJSON.Feature[]
    };
}

// ─── Data Centers ───────────────────────────────────────────────────────────

export function buildDataCentersGeoJSON(datacenters?: DataCenter[]): FC {
    if (!datacenters?.length) return null;
    return {
        type: 'FeatureCollection',
        features: datacenters.map((dc, i) => ({
            type: 'Feature' as const,
            properties: {
                id: `dc-${i}`,
                type: 'datacenter',
                name: dc.name || 'Unknown',
                company: dc.company || '',
                street: dc.street || '',
                city: dc.city || '',
                country: dc.country || '',
                zip: dc.zip || '',
            },
            geometry: { type: 'Point' as const, coordinates: [dc.lng, dc.lat] }
        }))
    };
}

// ─── Military Bases ─────────────────────────────────────────────────────────

// Classify base alignment: red = adversary, blue = US/allied, green = ROC
const _ADVERSARY_COUNTRIES = new Set(["China", "Russia", "North Korea"]);
const _ROC_COUNTRIES = new Set(["Taiwan"]);

function _baseSide(country: string, operator: string): "red" | "blue" | "green" {
    if (_ADVERSARY_COUNTRIES.has(country)) return "red";
    if (_ROC_COUNTRIES.has(country)) return "green";
    return "blue";
}

export function buildMilitaryBasesGeoJSON(bases?: MilitaryBase[]): FC {
    if (!bases?.length) return null;
    return {
        type: 'FeatureCollection',
        features: bases.map((base, i) => ({
            type: 'Feature' as const,
            properties: {
                id: `milbase-${i}`,
                type: 'military_base',
                name: base.name || 'Unknown',
                country: base.country || '',
                operator: base.operator || '',
                branch: base.branch || '',
                side: _baseSide(base.country || '', base.operator || ''),
            },
            geometry: { type: 'Point' as const, coordinates: [base.lng, base.lat] }
        }))
    };
}

// ─── Ethereum Nodes ─────────────────────────────────────────────────────────

export function buildEthNodesGeoJSON(nodes?: EthNode[]): FC {
    if (!nodes?.length) return null;
    return {
        type: 'FeatureCollection',
        features: nodes.map((n, i) => ({
            type: 'Feature' as const,
            properties: {
                id: `eth-${i}`,
                type: 'eth_node',
                name: n.city || n.org || n.ip,
                ip: n.ip,
                port: n.port,
                country: n.country || '',
                city: n.city || '',
                org: n.org || '',
                isp: n.isp || '',
                asn: n.asn || '',
                os: n.os || '',
            },
            geometry: { type: 'Point' as const, coordinates: [n.lng, n.lat] }
        }))
    };
}

// ─── GDELT Incidents ────────────────────────────────────────────────────────

export function buildGdeltGeoJSON(gdelt?: GDELTIncident[], inView?: InViewFilter): FC {
    if (!gdelt?.length) return null;
    return {
        type: 'FeatureCollection',
        features: gdelt.map((g) => {
            if (!g.geometry || !g.geometry.coordinates) return null;
            const [gLng, gLat] = g.geometry.coordinates;
            if (inView && !inView(gLat, gLng)) return null;
            return {
                type: 'Feature' as const,
                properties: { id: g.properties?.name || String(g.geometry.coordinates), type: 'gdelt', title: g.properties?.name || '' },
                geometry: g.geometry
            };
        }).filter(Boolean) as GeoJSON.Feature[]
    };
}

// ─── LiveUAMap Incidents ────────────────────────────────────────────────────

export function buildLiveuaGeoJSON(incidents?: LiveUAmapIncident[], inView?: InViewFilter): FC {
    if (!incidents?.length) return null;
    return {
        type: 'FeatureCollection',
        features: incidents.map((incident) => {
            if (incident.lat == null || incident.lng == null) return null;
            if (inView && !inView(incident.lat, incident.lng)) return null;
            const isViolent = /bomb|missil|strike|attack|kill|destroy|fire|shoot|expl|raid/i.test(incident.title || "");
            return {
                type: 'Feature' as const,
                properties: {
                    id: incident.id,
                    type: 'liveuamap',
                    title: incident.title || '',
                    iconId: isViolent ? 'icon-liveua-red' : 'icon-liveua-yellow',
                },
                geometry: { type: 'Point' as const, coordinates: [incident.lng, incident.lat] }
            };
        }).filter(Boolean) as GeoJSON.Feature[]
    };
}

// ─── Ukraine Frontline ──────────────────────────────────────────────────────

export function buildFrontlineGeoJSON(frontlines?: FrontlineGeoJSON | null): FC {
    if (!frontlines?.features?.length) return null;
    return frontlines;
}

// ─── Parameterized Flight Layer ─────────────────────────────────────────────
// Deduplicates commercial / private / jets / military flight GeoJSON builders.

export interface FlightLayerConfig {
    colorMap: Record<string, string>;
    groundedMap: Record<string, string>;
    typeLabel: string;
    idPrefix: string;
    /** For military flights: special icon overrides by military_type */
    milSpecialMap?: Record<string, string>;
    /** If true, prefer true_track over heading for rotation (commercial flights) */
    useTrackHeading?: boolean;
}

export function buildFlightLayerGeoJSON(
    flights: any[] | undefined,
    config: FlightLayerConfig,
    helpers: {
        interpFlight: (f: any) => [number, number];
        inView: InViewFilter;
        trackedIcaoSet: Set<string>;
    }
): FC {
    if (!flights?.length) return null;
    const { colorMap, groundedMap, typeLabel, idPrefix, milSpecialMap, useTrackHeading } = config;
    const { interpFlight, inView, trackedIcaoSet } = helpers;
    return {
        type: 'FeatureCollection',
        features: flights.map((f: any, i: number) => {
            if (f.lat == null || f.lng == null) return null;
            if (!inView(f.lat, f.lng)) return null;
            if (f.icao24 && trackedIcaoSet.has(f.icao24.toLowerCase())) return null;
            const acType = classifyAircraft(f.model, f.aircraft_category);
            const grounded = f.alt != null && f.alt <= 100;

            let iconId: string;
            if (milSpecialMap) {
                const milType = f.military_type || 'default';
                iconId = milSpecialMap[milType] || '';
                if (!iconId) {
                    iconId = grounded ? groundedMap[acType] : colorMap[acType];
                } else if (grounded) {
                    iconId = groundedMap[acType];
                }
            } else {
                iconId = grounded ? groundedMap[acType] : colorMap[acType];
            }

            const rotation = useTrackHeading ? (f.true_track || f.heading || 0) : (f.heading || 0);
            const [iLng, iLat] = interpFlight(f);
            return {
                type: 'Feature' as const,
                properties: { id: f.icao24 || f.callsign || `${idPrefix}${i}`, type: typeLabel, callsign: f.callsign || f.icao24, rotation, iconId },
                geometry: { type: 'Point' as const, coordinates: [iLng, iLat] }
            };
        }).filter(Boolean) as GeoJSON.Feature[]
    };
}

// ─── UAVs / Drones ──────────────────────────────────────────────────────────

export function buildUavGeoJSON(uavs?: UAV[], inView?: InViewFilter): FC {
    if (!uavs?.length) return null;
    return {
        type: 'FeatureCollection',
        features: uavs.map((uav, i) => {
            if (uav.lat == null || uav.lng == null) return null;
            if (inView && !inView(uav.lat, uav.lng)) return null;
            return {
                type: 'Feature' as const,
                properties: {
                    id: (uav as any).id || `uav-${i}`,
                    type: 'uav',
                    callsign: uav.callsign,
                    rotation: uav.heading || 0,
                    iconId: 'svgDrone',
                    name: uav.aircraft_model || uav.callsign,
                    country: uav.country || '',
                    uav_type: uav.uav_type || '',
                    alt: uav.alt || 0,
                    wiki: uav.wiki || '',
                    speed_knots: uav.speed_knots || 0,
                    icao24: uav.icao24 || '',
                    registration: uav.registration || '',
                    squawk: uav.squawk || '',
                },
                geometry: { type: 'Point' as const, coordinates: [uav.lng, uav.lat] }
            };
        }).filter(Boolean) as GeoJSON.Feature[]
    };
}
// ─── Satellites ─────────────────────────────────────────────────────────────

export function buildSatellitesGeoJSON(
    satellites: Satellite[] | undefined,
    inView: InViewFilter,
    interpSat: (s: Satellite) => [number, number]
): FC {
    if (!satellites?.length) return null;
    return {
        type: 'FeatureCollection',
        features: satellites
            .filter((s) => s.lat != null && s.lng != null && inView(s.lat, s.lng))
            .map((s, i) => ({
                type: 'Feature' as const,
                properties: {
                    id: s.id || i, type: 'satellite', name: s.name, mission: s.mission || 'general',
                    sat_type: s.sat_type || 'Satellite', country: s.country || '', alt_km: s.alt_km || 0,
                    wiki: s.wiki || '', color: MISSION_COLORS[s.mission] || '#aaaaaa',
                    iconId: MISSION_ICON_MAP[s.mission] || 'sat-gen'
                },
                geometry: { type: 'Point' as const, coordinates: interpSat(s) }
            }))
    };
}

// ─── Ships (non-carrier) ────────────────────────────────────────────────────

export function buildShipsGeoJSON(
    ships: Ship[] | undefined,
    activeLayers: ActiveLayers,
    inView: InViewFilter,
    interpShip: (s: Ship) => [number, number]
): FC {
    if (!(activeLayers.ships_military || activeLayers.ships_cargo || activeLayers.ships_civilian || activeLayers.ships_passenger || activeLayers.ships_tracked_yachts) || !ships) return null;
    return {
        type: 'FeatureCollection',
        features: ships.map((s, i) => {
            if (s.lat == null || s.lng == null) return null;
            if (!inView(s.lat, s.lng)) return null;
            const isTrackedYacht = !!s.yacht_alert;
            const isMilitary = s.type === 'carrier' || s.type === 'military_vessel';
            const isCargo = s.type === 'tanker' || s.type === 'cargo';
            const isPassenger = s.type === 'passenger';

            if (s.type === 'carrier') return null; // Handled by buildCarriersGeoJSON

            if (isTrackedYacht) {
                if (activeLayers?.ships_tracked_yachts === false) return null;
            } else if (isMilitary && activeLayers?.ships_military === false) return null;
            else if (isCargo && activeLayers?.ships_cargo === false) return null;
            else if (isPassenger && activeLayers?.ships_passenger === false) return null;
            else if (!isMilitary && !isCargo && !isPassenger && activeLayers?.ships_civilian === false) return null;

            let iconId = 'svgShipBlue';
            if (isTrackedYacht) iconId = 'svgShipPink';
            else if (isCargo) iconId = 'svgShipRed';
            else if (s.type === 'yacht' || isPassenger) iconId = 'svgShipWhite';
            else if (isMilitary) iconId = 'svgShipYellow';

            const [iLng, iLat] = interpShip(s);
            return {
                type: 'Feature',
                properties: { id: s.mmsi || s.name || `ship-${i}`, type: 'ship', name: s.name, rotation: s.heading || 0, iconId },
                geometry: { type: 'Point', coordinates: [iLng, iLat] }
            };
        }).filter(Boolean) as GeoJSON.Feature[]
    };
}

// ─── Carriers ───────────────────────────────────────────────────────────────

export function buildCarriersGeoJSON(ships: Ship[] | undefined): FC {
    if (!ships?.length) return null;
    return {
        type: 'FeatureCollection',
        features: ships.map((s, i) => {
            if (s.type !== 'carrier' || s.lat == null || s.lng == null) return null;
            return {
                type: 'Feature',
                properties: { id: s.mmsi || s.name || `carrier-${i}`, type: 'ship', name: s.name, rotation: s.heading || 0, iconId: 'svgCarrier' },
                geometry: { type: 'Point', coordinates: [s.lng, s.lat] }
            };
        }).filter(Boolean) as GeoJSON.Feature[]
    };
}
