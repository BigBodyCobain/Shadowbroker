"use client";

import React, { useEffect, useState, useRef } from "react";
import { MapContainer, TileLayer, Marker, Popup, useMap, Tooltip, CircleMarker, useMapEvents } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

// Fix standard leaflet icon path issues in React
delete (L.Icon.Default.prototype as any)._getIconUrl;
L.Icon.Default.mergeOptions({
    iconRetinaUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-icon-2x.png',
    iconUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-icon.png',
    shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-shadow.png',
});

// Create custom icons dynamically for the layers
const createDivIcon = (svg: string, size = 16, rotate = 0) => {
    return L.divIcon({
        className: 'custom-div-icon',
        html: `<div style="transform: rotate(${rotate}deg); width: ${size}px; height: ${size}px;">${svg}</div>`,
        iconSize: [size, size],
        iconAnchor: [size / 2, size / 2]
    });
};

const svgPlaneCyan = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="#00d4ff"><path d="M21 16v-2l-8-5V3.5c0-.83-.67-1.5-1.5-1.5S10 2.67 10 3.5V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5l8 2.5z"/></svg>`;
const svgPlaneOrange = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="#ffaa00"><path d="M21 16v-2l-8-5V3.5c0-.83-.67-1.5-1.5-1.5S10 2.67 10 3.5V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5l8 2.5z"/></svg>`;
const svgPlaneRed = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="#ff3333"><path d="M21 16v-2l-8-5V3.5c0-.83-.67-1.5-1.5-1.5S10 2.67 10 3.5V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5l8 2.5z"/></svg>`;
const svgShip = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="#888888"><path d="M12 22V8" /><path d="M5 12H19" /><path d="M9 22H15" /><circle cx="12" cy="5" r="3" /><path d="M12 22C8 22 4 19 4 15V13M12 22C16 22 20 19 20 15V13" /></svg>`;
const svgThreat = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="#ffff00" stroke="#ff0000" stroke-width="2"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" /><path d="M12 9v4" /><path d="M12 17h.01" /></svg>`;
const svgTriangleYellow = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="#ffaa00" stroke="#000" stroke-width="1"><path d="M1 21h22L12 2 1 21z"/></svg>`;
const svgTriangleRed = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="#ff0000" stroke="#fff" stroke-width="1"><path d="M1 21h22L12 2 1 21z"/></svg>`;

// Helper component to center map when Find Locater is used
function MapCenterControl({ location }: { location: { lat: number, lng: number } | null }) {
    const map = useMap();
    useEffect(() => {
        if (location) {
            map.flyTo([location.lat, location.lng], 8, { duration: 1.5 });
        }
    }, [location, map]);
    return null;
}

// Eavesdrop mode controller
function ClickHandler({ isEavesdropping, onEavesdropClick }: any) {
    const map = useMap();
    useEffect(() => {
        if (!isEavesdropping) return;
        const cb = (e: any) => onEavesdropClick({ lat: e.latlng.lat, lng: e.latlng.lng });
        map.on('click', cb);
        return () => { map.off('click', cb); };
    }, [isEavesdropping, map, onEavesdropClick]);
    return null;
}

// Map state tracker for LOD
function MapStateTracker({ onStateChange }: { onStateChange: (zoom: number, bounds: L.LatLngBounds) => void }) {
    const map = useMapEvents({
        moveend: () => onStateChange(map.getZoom(), map.getBounds()),
        zoomend: () => onStateChange(map.getZoom(), map.getBounds()),
    });
    useEffect(() => {
        onStateChange(map.getZoom(), map.getBounds());
    }, [map, onStateChange]);
    return null;
}

export default function LeafletViewer({ data, activeLayers, activeFilters, effects, onEntityClick, selectedEntity, flyToLocation, isEavesdropping, onEavesdropClick, onCameraMove }: any) {
    const [zoom, setZoom] = useState(3);
    const [bounds, setBounds] = useState<L.LatLngBounds | null>(null);

    const handleMapState = (z: number, b: L.LatLngBounds) => {
        setZoom(z);
        setBounds(b);
    };

    const isVisible = (lat: number, lng: number) => {
        if (!bounds) return true;
        return bounds.pad(0.2).contains([lat, lng]);
    };

    return (
        <div style={{ width: "100vw", height: "100vh", position: "fixed", top: 0, left: 0, zIndex: 0, background: "black" }}>
            <MapContainer
                center={[20, 0]}
                zoom={3}
                style={{ width: "100%", height: "100%", background: "#06080a" }} // Extremely dark ocean base
                zoomControl={false}
                minZoom={2}
                maxZoom={12}
            >
                <MapStateTracker onStateChange={handleMapState} />
                <MapCenterControl location={flyToLocation} />
                <ClickHandler isEavesdropping={isEavesdropping} onEavesdropClick={onEavesdropClick} />

                {/* Dark Mode Satellite Stamen / CartoDB Voyager basemap substitute */}
                <TileLayer
                    url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
                    attribution='&copy; <a href="https://carto.com/">CARTO</a>'
                    maxZoom={19}
                />

                {/* --- COMMERCIAL FLIGHTS --- */}
                {activeLayers.flights && data?.commercial_flights?.map((f: any, idx: number) => {
                    if (f.lat == null || f.lng == null) return null;
                    if (zoom >= 6 && !isVisible(f.lat, f.lng)) return null;

                    if (zoom < 6) {
                        return (
                            <CircleMarker
                                key={`comm-${idx}`}
                                center={[f.lat, f.lng]}
                                radius={2}
                                pathOptions={{ color: '#00d4ff', fillColor: '#00d4ff', fillOpacity: 0.8, weight: 1, stroke: false }}
                                eventHandlers={{ click: () => onEntityClick?.({ type: 'flight', id: idx, callsign: f.callsign || f.icao24 }) }}
                            />
                        );
                    }

                    const icon = createDivIcon(svgPlaneCyan, 18, f.true_track || f.heading || 0);
                    return (
                        <Marker
                            key={`comm-${idx}`}
                            position={[f.lat, f.lng]}
                            icon={icon}
                            eventHandlers={{ click: () => onEntityClick?.({ type: 'flight', id: idx, callsign: f.callsign || f.icao24 }) }}
                        >
                            <Tooltip direction="top" offset={[0, -10]} opacity={0.9}>
                                <div className="text-cyan-400 font-bold bg-black px-1 text-xs border border-cyan-500/50">{f.callsign || f.icao24}</div>
                            </Tooltip>
                        </Marker>
                    );
                })}

                {/* --- PRIVATE FLIGHTS --- */}
                {activeLayers.private && data?.private_flights?.map((f: any, idx: number) => {
                    if (f.lat == null || f.lng == null) return null;
                    if (zoom >= 6 && !isVisible(f.lat, f.lng)) return null;

                    if (zoom < 6) {
                        return (
                            <CircleMarker
                                key={`priv-${idx}`}
                                center={[f.lat, f.lng]}
                                radius={2}
                                pathOptions={{ color: '#ffaa00', fillColor: '#ffaa00', fillOpacity: 0.8, weight: 1, stroke: false }}
                                eventHandlers={{ click: () => onEntityClick?.({ type: 'private_flight', id: idx, callsign: f.callsign || f.icao24 }) }}
                            />
                        );
                    }

                    const icon = createDivIcon(svgPlaneOrange, 18, f.true_track || f.heading || 0);
                    return (
                        <Marker
                            key={`priv-${idx}`}
                            position={[f.lat, f.lng]}
                            icon={icon}
                            eventHandlers={{ click: () => onEntityClick?.({ type: 'private_flight', id: idx, callsign: f.callsign || f.icao24 }) }}
                        >
                            <Tooltip direction="top" offset={[0, -10]} opacity={0.9}>
                                <div className="text-orange-400 font-bold bg-black px-1 text-xs border border-orange-500/50">{f.callsign || f.icao24}</div>
                            </Tooltip>
                        </Marker>
                    );
                })}

                {/* --- MILITARY FLIGHTS --- */}
                {activeLayers.military && data?.military_flights?.map((f: any, idx: number) => {
                    if (f.lat == null || f.lng == null) return null;
                    if (zoom >= 6 && !isVisible(f.lat, f.lng)) return null;

                    if (zoom < 6) {
                        return (
                            <CircleMarker
                                key={`mil-${idx}`}
                                center={[f.lat, f.lng]}
                                radius={3}
                                pathOptions={{ color: '#ff3333', fillColor: '#ff3333', fillOpacity: 0.9, weight: 1, stroke: false }}
                                eventHandlers={{ click: () => onEntityClick?.({ type: 'military_flight', id: idx, callsign: f.callsign || f.icao24 }) }}
                            />
                        );
                    }

                    const icon = createDivIcon(svgPlaneRed, 20, f.true_track || f.heading || 0);
                    return (
                        <Marker
                            key={`mil-${idx}`}
                            position={[f.lat, f.lng]}
                            icon={icon}
                            eventHandlers={{ click: () => onEntityClick?.({ type: 'military_flight', id: idx, callsign: f.callsign || f.icao24 }) }}
                        >
                            <Tooltip direction="top" offset={[0, -10]} opacity={0.9}>
                                <div className="text-red-500 font-bold bg-black px-1 text-xs border border-red-500/50">{f.callsign || f.icao24}</div>
                            </Tooltip>
                        </Marker>
                    );
                })}

                {/* --- SHIPS --- */}
                {(activeLayers.ships_important || activeLayers.ships_civilian || activeLayers.ships_passenger) && data?.ships?.map((s: any, idx: number) => {
                    if (s.lat == null || s.lng == null) return null;
                    if (zoom >= 6 && !isVisible(s.lat, s.lng)) return null;

                    if (zoom < 6) {
                        return (
                            <CircleMarker
                                key={`ship-${idx}`}
                                center={[s.lat, s.lng]}
                                radius={1.5}
                                pathOptions={{ color: '#888888', fillColor: '#888888', fillOpacity: 0.6, weight: 0.5, stroke: false }}
                                eventHandlers={{ click: () => onEntityClick?.({ type: 'ship', id: idx, name: s.name }) }}
                            />
                        );
                    }

                    const icon = createDivIcon(svgShip, 12, s.heading || 0);
                    return (
                        <Marker
                            key={`ship-${idx}`}
                            position={[s.lat, s.lng]}
                            icon={icon}
                            eventHandlers={{ click: () => onEntityClick?.({ type: 'ship', id: idx, name: s.name }) }}
                        >
                            <Tooltip direction="top" offset={[0, -5]} opacity={0.8}>
                                <div className="text-gray-300 font-bold bg-black px-1 text-[10px] border border-gray-600/50">{s.name}</div>
                            </Tooltip>
                        </Marker>
                    );
                })}

                {/* --- GDELT GLOBAL INCIDENTS --- */}
                {activeLayers.global_incidents && data?.gdelt?.map((incident: any, idx: number) => {
                    const geom = incident.geometry;
                    if (!geom || geom.type !== 'Point' || !geom.coordinates) return null;
                    const lng = geom.coordinates[0];
                    const lat = geom.coordinates[1];
                    if (!isVisible(lat, lng)) return null;

                    return (
                        <CircleMarker
                            key={`gdelt-${idx}`}
                            center={[geom.coordinates[1], geom.coordinates[0]]}
                            radius={8}
                            pathOptions={{ color: '#ff0000', fillColor: '#ff8c00', fillOpacity: 0.6, weight: 2 }}
                            eventHandlers={{ click: () => onEntityClick?.({ type: 'gdelt', id: idx }) }}
                        >
                            <Tooltip>
                                <div className="text-orange-500 text-xs bg-black p-1 max-w-[200px] whitespace-normal">
                                    {incident.title}
                                </div>
                            </Tooltip>
                        </CircleMarker>
                    );
                })}

                {/* --- LIVEUAMAP INCIDENTS --- */}
                {activeLayers.global_incidents && data?.liveuamap?.map((incident: any, idx: number) => {
                    if (incident.lat == null || incident.lng == null) return null;
                    if (!isVisible(incident.lat, incident.lng)) return null;
                    const isViolent = /bomb|missil|strike|attack|kill|destroy|fire|shoot|expl|raid/i.test(incident.title || "");
                    const icon = createDivIcon(isViolent ? svgTriangleRed : svgTriangleYellow, 18);
                    return (
                        <Marker
                            key={`liveua-${idx}`}
                            position={[incident.lat, incident.lng]}
                            icon={icon}
                            eventHandlers={{ click: () => onEntityClick?.({ type: 'liveuamap', id: incident.id, title: incident.title }) }}
                        >
                            <Tooltip direction="top" offset={[0, -10]} opacity={0.95}>
                                <div className="text-white font-bold bg-black p-1 text-[11px] border border-gray-600 max-w-[200px] whitespace-normal">
                                    <span className={isViolent ? "text-red-500" : "text-yellow-500"}>[LIVEUA]</span> {incident.title}
                                </div>
                            </Tooltip>
                        </Marker>
                    );
                })}

                {/* --- RSS THREAT ALERTS --- */}
                {activeLayers.global_incidents && data?.news?.filter((n: any) => n.coordinates)?.map((n: any, idx: number) => {
                    if (n.coordinates.lat == null || n.coordinates.lng == null) return null;
                    if (!isVisible(n.coordinates.lat, n.coordinates.lng)) return null;
                    const icon = createDivIcon(svgThreat, 24);
                    return (
                        <Marker
                            key={`threat-${idx}`}
                            position={[n.coordinates.lat, n.coordinates.lng]}
                            icon={icon}
                            eventHandlers={{ click: () => onEntityClick?.({ type: 'news', id: idx }) }}
                        >
                            <Tooltip direction="top" offset={[0, -12]} opacity={1.0} permanent={true} className="bg-transparent border-0 shadow-none">
                                <div className="text-red-500 font-bold bg-black/80 px-2 py-1 text-[10px] border border-red-500/50 backdrop-blur" style={{ textShadow: "0px 0px 4px #000" }}>
                                    !! LVL {n.threat_level} !!<br />
                                    <span className="text-yellow-400 font-normal">{n.title.substring(0, 30)}...</span>
                                </div>
                            </Tooltip>
                        </Marker>
                    );
                })}

            </MapContainer>
        </div>
    );
}
