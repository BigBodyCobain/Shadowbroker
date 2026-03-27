import React from 'react';
import { Marker } from 'react-map-gl/maplibre';
import type { Earthquake, SelectedEntity, Ship, TrackedFlight, UAV } from '@/types/dashboard';
import type { SpreadAlertItem } from '@/utils/alertSpread';

// Shared monospace label style base
const LABEL_BASE: React.CSSProperties = {
  fontFamily: 'monospace',
  fontWeight: 'bold',
  textShadow: '0 0 3px #000, 0 0 3px #000',
  pointerEvents: 'none',
};

const LABEL_SHADOW_EXTRA = '0 0 3px #000, 0 0 3px #000, 1px 1px 2px #000';

// -- Cluster count label (ships / earthquakes) --
type ClusterPoint = {
  id: string | number;
  lat: number;
  lng: number;
  count: string | number;
};

export function ClusterCountLabels({ clusters, prefix }: { clusters: ClusterPoint[]; prefix: string }) {
  return (
    <>
      {clusters.map((c) => (
        <Marker
          key={`${prefix}-${c.id}`}
          longitude={c.lng}
          latitude={c.lat}
          anchor="center"
          style={{ zIndex: 1 }}
        >
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
  '#ff1493': '#ff1493',
  pink: '#ff1493',
  red: '#ff4444',
  blue: '#3b82f6',
  orange: '#FF8C00',
  '#32cd32': '#32cd32',
  purple: '#b266ff',
  white: '#cccccc',
};

interface TrackedFlightLabelsProps {
  flights: TrackedFlight[];
  zoom: number;
  inView: (lat: number, lng: number) => boolean;
  interpFlight: (f: TrackedFlight) => [number, number];
}

export function TrackedFlightLabels({
  flights,
  zoom,
  inView,
  interpFlight,
}: TrackedFlightLabelsProps) {
  return (
    <>
      {flights.map((f, i) => {
        if (f.lat == null || f.lng == null) return null;
        if (!inView(f.lat, f.lng)) return null;

        const alertColor = f.alert_color || '#ff1493';
        if (alertColor === 'yellow' || alertColor === 'black') return null;

        const isHighPriority =
          alertColor === '#ff1493' || alertColor === 'pink' || alertColor === 'red';
        if (!isHighPriority && zoom < 5) return null;

        const displayName =
          f.alert_operator ||
          f.operator ||
          f.owner ||
          f.name ||
          f.callsign ||
          f.icao24 ||
          'UNKNOWN';
        if (displayName === 'Private' || displayName === 'private') return null;

        const grounded = f.alt != null && f.alt <= 100;
        const labelColor = grounded ? '#888' : TRACKED_LABEL_COLOR_MAP[alertColor] || alertColor;
        const [iLng, iLat] = interpFlight(f);

        return (
          <Marker
            key={`tf-label-${i}`}
            longitude={iLng}
            latitude={iLat}
            anchor="top"
            offset={[0, 10]}
            style={{ zIndex: 2 }}
          >
            <div
              style={{
                ...LABEL_BASE,
                color: labelColor,
                fontSize: `${Math.max(10, Math.min(16, 10 + (zoom - 5) * 1.2))}px`,
                textShadow: LABEL_SHADOW_EXTRA,
                whiteSpace: 'nowrap',
              }}
            >
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
  ships: Ship[];
  inView: (lat: number, lng: number) => boolean;
  interpShip: (s: Ship) => [number, number];
}

export function CarrierLabels({ ships, inView, interpShip }: CarrierLabelsProps) {
  return (
    <>
      {ships.map((s, i) => {
        if (s.type !== 'carrier' || s.lat == null || s.lng == null) return null;
        if (!inView(s.lat, s.lng)) return null;
        const [iLng, iLat] = interpShip(s);
        return (
          <Marker
            key={`carrier-label-${i}`}
            longitude={iLng}
            latitude={iLat}
            anchor="top"
            offset={[0, 12]}
            style={{ zIndex: 2 }}
          >
            <div
              style={{
                ...LABEL_BASE,
                textShadow: LABEL_SHADOW_EXTRA,
                whiteSpace: 'nowrap',
                textAlign: 'center',
              }}
            >
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

// -- Tracked yacht labels --
interface TrackedYachtLabelsProps {
  ships: Ship[];
  inView: (lat: number, lng: number) => boolean;
  interpShip: (s: Ship) => [number, number];
}

export function TrackedYachtLabels({ ships, inView, interpShip }: TrackedYachtLabelsProps) {
  return (
    <>
      {ships.map((s, i) => {
        if (!s.yacht_alert || s.lat == null || s.lng == null) return null;
        if (!inView(s.lat, s.lng)) return null;
        const [iLng, iLat] = interpShip(s);
        return (
          <Marker
            key={`yacht-label-${i}`}
            longitude={iLng}
            latitude={iLat}
            anchor="top"
            offset={[0, 12]}
            style={{ zIndex: 2 }}
          >
            <div
              style={{
                ...LABEL_BASE,
                color: s.yacht_color || '#FF69B4',
                fontSize: '10px',
                textShadow: LABEL_SHADOW_EXTRA,
                whiteSpace: 'nowrap',
              }}
            >
              {s.yacht_owner || s.name || 'TRACKED YACHT'}
            </div>
          </Marker>
        );
      })}
    </>
  );
}

// -- UAV labels --
interface UavLabelsProps {
  uavs: UAV[];
  inView: (lat: number, lng: number) => boolean;
  zoom?: number;
}

export function UavLabels({ uavs, inView, zoom = 5 }: UavLabelsProps) {
  const labelSize = `${Math.max(10, Math.min(16, 10 + (zoom - 5) * 1.2))}px`;
  return (
    <>
      {uavs.map((uav, i) => {
        if (uav.lat == null || uav.lng == null) return null;
        if (!inView(uav.lat, uav.lng)) return null;
        const name = uav.aircraft_model ? `[UAV: ${uav.aircraft_model}]` : `[UAV: ${uav.callsign}]`;
        return (
          <Marker
            key={`uav-label-${i}`}
            longitude={uav.lng}
            latitude={uav.lat}
            anchor="top"
            offset={[0, 10]}
            style={{ zIndex: 2 }}
          >
            <div
              style={{
                ...LABEL_BASE,
                color: '#ff8c00',
                fontSize: labelSize,
                textShadow: LABEL_SHADOW_EXTRA,
                whiteSpace: 'nowrap',
              }}
            >
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
  earthquakes: Earthquake[];
  inView: (lat: number, lng: number) => boolean;
}

export function EarthquakeLabels({ earthquakes, inView }: EarthquakeLabelsProps) {
  return (
    <>
      {earthquakes.map((eq, i) => {
        if (eq.lat == null || eq.lng == null) return null;
        if (!inView(eq.lat, eq.lng)) return null;
        return (
          <Marker
            key={`eq-label-${i}`}
            longitude={eq.lng}
            latitude={eq.lat}
            anchor="top"
            offset={[0, 14]}
            style={{ zIndex: 1 }}
          >
            <div
              style={{
                ...LABEL_BASE,
                color: '#ffcc00',
                fontSize: '10px',
                textShadow: LABEL_SHADOW_EXTRA,
                whiteSpace: 'nowrap',
              }}
            >
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
  spreadAlerts: SpreadAlertItem[];
  zoom: number;
  selectedEntity: SelectedEntity | null;
  onEntityClick?: (entity: SelectedEntity | null) => void;
  onDismiss?: (alertKey: string) => void;
}

export function ThreatMarkers({
  spreadAlerts,
  zoom,
  selectedEntity,
  onEntityClick,
  onDismiss,
}: ThreatMarkerProps) {
  return (
    <>
      {spreadAlerts.map((n) => {
        const count = n.cluster_count || 1;
        const score = n.risk_score || 0;
        const riskColor = getRiskColor(score);
        const alertKey = n.alertKey || `${n.title}|${n.coords?.[0]},${n.coords?.[1]}`;

        let isVisible = zoom >= 1;
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
                    x2={-n.offsetX}
                    y2={-n.offsetY}
                    stroke={riskColor}
                    strokeWidth="1.5"
                    strokeDasharray="3,3"
                    className="opacity-80"
                  />
                  <circle cx={-n.offsetX} cy={-n.offsetY} r="2" fill={riskColor} />
                </svg>
              )}

              <div
                className="cursor-pointer transition-opacity duration-300 relative"
                style={{
                  opacity: isVisible ? 1.0 : 0.0,
                  pointerEvents: isVisible ? 'auto' : 'none',
                  backgroundColor: 'rgba(5, 5, 5, 0.96)',
                  border: `2px solid ${riskColor}`,
                  borderRadius: '4px',
                  padding: '8px 20px 8px 12px',
                  color: riskColor,
                  fontFamily: "'JetBrains Mono', monospace",
                  fontSize: '12px',
                  fontWeight: 'bold',
                  textAlign: 'center',
                  boxShadow: `0 0 20px ${riskColor}80, 0 0 40px ${riskColor}30`,
                  zIndex: 10,
                  lineHeight: '1.3',
                  minWidth: '200px',
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
                      transform: 'translateX(-50%)',
                    }}
                  />
                )}

                <div
                  className="absolute inset-0 border border-current rounded opacity-50"
                  style={{ color: riskColor, zIndex: -1 }}
                ></div>
                {onDismiss && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onDismiss(alertKey);
                    }}
                    style={{
                      position: 'absolute',
                      top: '4px',
                      right: '6px',
                      background: 'transparent',
                      border: 'none',
                      cursor: 'pointer',
                      color: riskColor,
                      fontSize: '16px',
                      fontWeight: 'bold',
                      lineHeight: 1,
                      padding: '0 2px',
                      opacity: 0.7,
                      zIndex: 20,
                    }}
                    onMouseEnter={(e) => (e.currentTarget.style.opacity = '1')}
                    onMouseLeave={(e) => (e.currentTarget.style.opacity = '0.7')}
                  >
                    ×
                  </button>
                )}
                <div style={{ fontSize: '14px', letterSpacing: '1.5px', textTransform: 'uppercase' as const }}>
                  !! ALERT LVL {score} !!
                </div>
                <div
                  style={{
                    color: '#fff',
                    fontSize: '12px',
                    marginTop: '4px',
                    maxWidth: '260px',
                    lineHeight: '1.4',
                  }}
                >
                  {n.title}
                </div>
                {count > 1 && (
                  <div
                    style={{ color: riskColor, opacity: 0.9, fontSize: '10px', marginTop: '4px', letterSpacing: '0.5px' }}
                  >
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
