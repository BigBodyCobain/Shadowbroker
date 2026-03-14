import React from "react";
import { Marker } from "react-map-gl/maplibre";
import type { ViewState } from "react-map-gl/maplibre";

// Shared monospace label style base
const LABEL_BASE: React.CSSProperties = {
    fontFamily: 'monospace',
    fontWeight: 'bold',
    textShadow: '0 0 3px #000, 0 0 3px #000',
    pointerEvents: 'none',
};

const LABEL_SHADOW_EXTRA = '0 0 3px #000, 0 0 3px #000, 1px 1px 2px #000';

// -- Cluster count label (ships / earthquakes) --
export function ClusterCountLabels({ clusters, prefix }: { clusters: any[]; prefix: string }) {
    return (
        <>
            {clusters.map((c: any) => (
                <Marker key={`${prefix}-${c.id}`} longitude={c.lng} latitude={c.lat} anchor="center" style={{ zIndex: 1 }}>
                    <div style={{ ...LABEL_BASE, color: '#fff', fontSize: '11px', textAlign: 'center' }}>
                        {c.count}
                    </div>
                </Marker>
            ))}
        </>
    );
}

// -- Tracked flights labels --
const TRACKED_LABEL_COLOR_MAP: Record<string, string> = {
    '#ff1493': '#ff1493', pink: '#ff1493', red: '#ff4444',
    blue: '#3b82f6', orange: '#FF8C00', '#32cd32': '#32cd32',
    purple: '#b266ff', white: '#cccccc',
};

interface TrackedFlightLabelsProps {
    flights: any[];
    viewState: ViewState;
    inView: (lat: number, lng: number) => boolean;
    interpFlight: (f: any) => [number, number];
}

export function TrackedFlightLabels({ flights, viewState, inView, interpFlight }: TrackedFlightLabelsProps) {
    return (
        <>
            {flights.map((f: any, i: number) => {
                if (f.lat == null || f.lng == null) return null;
                if (!inView(f.lat, f.lng)) return null;

                const alertColor = f.alert_color || '#ff1493';
                if (alertColor === 'yellow' || alertColor === 'black') return null;

                const isHighPriority = alertColor === '#ff1493' || alertColor === 'pink' || alertColor === 'red';
                if (!isHighPriority && viewState.zoom < 5) return null;

                let displayName = f.alert_operator || f.operator || f.owner || f.name || f.callsign || f.icao24 || "UNKNOWN";
                if (displayName === 'Private' || displayName === 'private') return null;

                const grounded = f.alt != null && f.alt <= 100;
                const labelColor = grounded ? '#888' : (TRACKED_LABEL_COLOR_MAP[alertColor] || alertColor);
                const [iLng, iLat] = interpFlight(f);

                return (
                    <Marker key={`tf-label-${i}`} longitude={iLng} latitude={iLat} anchor="top" offset={[0, 10]} style={{ zIndex: 2 }}>
                        <div style={{ ...LABEL_BASE, color: labelColor, fontSize: '10px', textShadow: LABEL_SHADOW_EXTRA, whiteSpace: 'nowrap' }}>
                            {String(displayName)}
                        </div>
                    </Marker>
                );
            })}
        </>
    );
}

// -- Carrier labels --
interface CarrierLabelsProps {
    ships: any[];
    inView: (lat: number, lng: number) => boolean;
    interpShip: (s: any) => [number, number];
}

export function CarrierLabels({ ships, inView, interpShip }: CarrierLabelsProps) {
    return (
        <>
            {ships.map((s: any, i: number) => {
                if (s.type !== 'carrier' || s.lat == null || s.lng == null) return null;
                if (!inView(s.lat, s.lng)) return null;
                const [iLng, iLat] = interpShip(s);
                return (
                    <Marker key={`carrier-label-${i}`} longitude={iLng} latitude={iLat} anchor="top" offset={[0, 12]} style={{ zIndex: 2 }}>
                        <div style={{ ...LABEL_BASE, textShadow: LABEL_SHADOW_EXTRA, whiteSpace: 'nowrap', textAlign: 'center' }}>
                            <div style={{ color: '#ffaa00', fontSize: '11px', fontWeight: 'bold' }}>
                                [[{s.name}]]
                            </div>
                            {s.estimated && (
                                <div style={{ color: '#ff6644', fontSize: '8px', letterSpacing: '1.5px' }}>
                                    EST. POSITION — OSINT
                                </div>
                            )}
                        </div>
                    </Marker>
                );
            })}
        </>
    );
}

// -- UAV labels --
interface UavLabelsProps {
    uavs: any[];
    inView: (lat: number, lng: number) => boolean;
}

export function UavLabels({ uavs, inView }: UavLabelsProps) {
    return (
        <>
            {uavs.map((uav: any, i: number) => {
                if (uav.lat == null || uav.lng == null) return null;
                if (!inView(uav.lat, uav.lng)) return null;
                const name = uav.aircraft_model ? `[UAV: ${uav.aircraft_model}]` : `[UAV: ${uav.callsign}]`;
                return (
                    <Marker key={`uav-label-${i}`} longitude={uav.lng} latitude={uav.lat} anchor="top" offset={[0, 10]} style={{ zIndex: 2 }}>
                        <div style={{ ...LABEL_BASE, color: '#ff8c00', fontSize: '10px', textShadow: LABEL_SHADOW_EXTRA, whiteSpace: 'nowrap' }}>
                            {name}
                        </div>
                    </Marker>
                );
            })}
        </>
    );
}

// -- Earthquake labels --
interface EarthquakeLabelsProps {
    earthquakes: any[];
    inView: (lat: number, lng: number) => boolean;
}

export function EarthquakeLabels({ earthquakes, inView }: EarthquakeLabelsProps) {
    return (
        <>
            {earthquakes.map((eq: any, i: number) => {
                if (eq.lat == null || eq.lng == null) return null;
                if (!inView(eq.lat, eq.lng)) return null;
                return (
                    <Marker key={`eq-label-${i}`} longitude={eq.lng} latitude={eq.lat} anchor="top" offset={[0, 14]} style={{ zIndex: 1 }}>
                        <div style={{ ...LABEL_BASE, color: '#ffcc00', fontSize: '10px', textShadow: LABEL_SHADOW_EXTRA, whiteSpace: 'nowrap' }}>
                            [M{eq.mag}] {eq.place || ''}
                        </div>
                    </Marker>
                );
            })}
        </>
    );
}

// -- Threat alert markers --
function getRiskColor(score: number): string {
    if (score >= 9) return '#ef4444';
    if (score >= 7) return '#f97316';
    if (score >= 4) return '#eab308';
    if (score >= 1) return '#3b82f6';
    return '#22c55e';
}

interface ThreatMarkerProps {
    spreadAlerts: any[];
    viewState: ViewState;
    selectedEntity: any;
    onEntityClick?: (entity: { id: string | number; type: string } | null) => void;
    onDismiss?: (alertKey: string) => void;
}

export function ThreatMarkers({ spreadAlerts, viewState, selectedEntity, onEntityClick, onDismiss }: ThreatMarkerProps) {
    return (
        <>
            {spreadAlerts.map((n: any) => {
                const count = n.cluster_count || 1;
                const score = n.risk_score || 0;
                const riskColor = getRiskColor(score);
                const alertKey = n.alertKey || `${n.title}|${n.coords?.[0]},${n.coords?.[1]}`;

                let isVisible = viewState.zoom >= 1;
                if (selectedEntity) {
                    if (selectedEntity.type === 'news') {
                        if (selectedEntity.id !== alertKey) isVisible = false;
                    } else {
                        isVisible = false;
                    }
                }

                return (
                    <Marker
                        key={`threat-${alertKey}`}
                        longitude={n.coords[1]}
                        latitude={n.coords[0]}
                        anchor="center"
                        offset={[n.offsetX, n.offsetY]}
                        style={{ zIndex: 50 + score }}
                        onClick={(e) => {
                            e.originalEvent.stopPropagation();
                            onEntityClick?.({ id: alertKey, type: 'news' });
                        }}
                    >
                        <div className="relative group/alert">
                            {n.showLine && isVisible && (
                                <svg className="absolute pointer-events-none" style={{ left: '50%', top: '50%', width: 1, height: 1, overflow: 'visible', zIndex: -1 }}>
                                    <line x1={0} y1={0} x2={-n.offsetX} y2={-n.offsetY} stroke={riskColor} strokeWidth="1.5" strokeDasharray="3,3" className="opacity-80" />
                                    <circle cx={-n.offsetX} cy={-n.offsetY} r="2" fill={riskColor} />
                                </svg>
                            )}

                            <div
                                className="cursor-pointer transition-all duration-300 relative"
                                style={{
                                    opacity: isVisible ? 1.0 : 0.0,
                                    pointerEvents: isVisible ? 'auto' : 'none',
                                    backgroundColor: 'rgba(5, 5, 5, 0.95)',
                                    border: `1.5px solid ${riskColor}`,
                                    borderRadius: '4px',
                                    padding: '5px 16px 5px 8px',
                                    color: riskColor,
                                    fontFamily: 'monospace',
                                    fontSize: '9px',
                                    fontWeight: 'bold',
                                    textAlign: 'center',
                                    boxShadow: `0 0 12px ${riskColor}60`,
                                    zIndex: 10,
                                    lineHeight: '1.2',
                                    minWidth: '120px'
                                }}
                            >
                                {n.showLine && isVisible && (
                                    <div
                                        className="absolute"
                                        style={{
                                            width: 0,
                                            height: 0,
                                            borderLeft: '6px solid transparent',
                                            borderRight: '6px solid transparent',
                                            borderTop: n.offsetY < 0 ? `6px solid ${riskColor}` : 'none',
                                            borderBottom: n.offsetY > 0 ? `6px solid ${riskColor}` : 'none',
                                            left: '50%',
                                            [n.offsetY < 0 ? 'bottom' : 'top']: '-6px',
                                            transform: 'translateX(-50%)'
                                        }}
                                    />
                                )}

                                <div className="absolute inset-0 border border-current rounded opacity-50 animate-pulse" style={{ color: riskColor, zIndex: -1 }}></div>
                                {onDismiss && (
                                    <button
                                        onClick={(e) => { e.stopPropagation(); onDismiss(alertKey); }}
                                        style={{
                                            position: 'absolute', top: '2px', right: '4px',
                                            background: 'transparent', border: 'none', cursor: 'pointer',
                                            color: riskColor, fontSize: '12px', fontWeight: 'bold',
                                            lineHeight: 1, padding: '0 2px', opacity: 0.7, zIndex: 20,
                                        }}
                                        onMouseEnter={(e) => (e.currentTarget.style.opacity = '1')}
                                        onMouseLeave={(e) => (e.currentTarget.style.opacity = '0.7')}
                                    >×</button>
                                )}
                                <div style={{ fontSize: '10px', letterSpacing: '0.5px' }}>!! ALERT LVL {score} !!</div>
                                <div style={{ color: '#fff', fontSize: '9px', marginTop: '2px', maxWidth: '160px', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                    {n.title}
                                </div>
                                {count > 1 && (
                                    <div style={{ color: riskColor, opacity: 0.8, fontSize: '8px', marginTop: '2px' }}>
                                        [+{count - 1} ACTIVE THREATS IN AREA]
                                    </div>
                                )}
                            </div>
                        </div>
                    </Marker>
                );
            })}
        </>
    );
}
