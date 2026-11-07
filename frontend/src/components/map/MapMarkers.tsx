import type * as GeoJSON from 'geojson';
import React from 'react';
import { Marker, useMap } from 'react-map-gl/maplibre';
import type { Earthquake, SelectedEntity, Ship, TrackedFlight, UAV } from '@/types/dashboard';
import type { SpreadAlertItem } from '@/utils/alertSpread';
import { TELEGRAM_MARKER_OFFSET } from '@/components/map/geoJSONBuilders';

// Shared monospace label style base
const LABEL_BASE: React.CSSProperties = {
  fontFamily: 'var(--font-jetbrains-mono), ui-monospace, monospace',
  fontWeight: 'bold',
  textShadow: '0 0 3px #02050b, 0 0 4px #02050b',
  pointerEvents: 'none',
};

const LABEL_SHADOW_EXTRA = '0 0 3px #02050b, 0 0 4px #02050b, 1px 1px 2px #02050b';

// Small dark plate behind entity name labels so they stay legible over dense icons.
const LABEL_PLATE: React.CSSProperties = {
  background: 'rgba(3, 7, 15, 0.62)',
  borderRadius: '4px',
  padding: '0 4px 1px',
};

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
          <div data-sb-label="cluster" style={{ ...LABEL_BASE, color: '#fff', fontSize: '11px', textAlign: 'center' }}>
            {c.count}
          </div>
        </Marker>
      ))}
    </>
  );
}

// -- Tracked flights labels --
const TRACKED_LABEL_COLOR_MAP: Record<string, string> = {
  '#ff1493': '#ff4fa3',
  pink: '#ff4fa3',
  red: '#ff3b5c',
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
  const { current: mapRef } = useMap();
  const map = mapRef?.getMap?.();
  // Screen-space declutter: skip a label whose box would overlap one already placed.
  const placed: { x: number; y: number }[] = [];
  const collides = (lng: number, lat: number): boolean => {
    if (!map) return false;
    const pt = map.project([lng, lat]);
    if (placed.some((q) => Math.abs(q.x - pt.x) < 96 && Math.abs(q.y - pt.y) < 18)) return true;
    placed.push({ x: pt.x, y: pt.y });
    return false;
  };
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
        const labelColor = grounded ? '#8ea3bf' : TRACKED_LABEL_COLOR_MAP[alertColor] || alertColor;
        const [iLng, iLat] = interpFlight(f);
        if (collides(iLng, iLat)) return null;

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
              data-sb-label="tracked"
              style={{
                ...LABEL_BASE,
                ...LABEL_PLATE,
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
  const { current: mapRef } = useMap();
  const map = mapRef?.getMap?.();
  const placed: { x: number; y: number }[] = [];
  return (
    <>
      {ships.map((s, i) => {
        if (s.type !== 'carrier' || s.lat == null || s.lng == null) return null;
        if (!inView(s.lat, s.lng)) return null;
        const [iLng, iLat] = interpShip(s);
        if (map) {
          // two carriers in port together would print over each other — keep the first
          const pt = map.project([iLng, iLat]);
          if (placed.some((q) => Math.abs(q.x - pt.x) < 150 && Math.abs(q.y - pt.y) < 30)) return null;
          placed.push({ x: pt.x, y: pt.y });
        }
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
              data-sb-label="carrier"
              style={{
                ...LABEL_BASE,
                textShadow: 'none',
                whiteSpace: 'nowrap',
                textAlign: 'left',
                // backing plate so route lines and icons never run through the text
                background: 'rgba(3, 7, 15, 0.78)',
                // a label plate, not a callout: no frame, just an amber rule on the left
                borderLeft: '2px solid rgba(255, 176, 32, 0.85)',
                borderRadius: '3px',
                padding: '2px 6px 3px',
              }}
            >
              <div style={{ color: '#ffb020', fontSize: '11px', fontWeight: 'bold' }}>
                {s.name}
              </div>
              {s.estimated && (
                <div style={{ color: '#ff8a5c', fontSize: '10px', letterSpacing: '1.2px' }}>
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
              data-sb-label="yacht"
              style={{
                ...LABEL_BASE,
                ...LABEL_PLATE,
                color: s.yacht_color || '#FF69B4',
                fontSize: '11px',
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
              data-sb-label="uav"
              style={{
                ...LABEL_BASE,
                ...LABEL_PLATE,
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
              data-sb-label="quake"
              style={{
                ...LABEL_BASE,
                ...LABEL_PLATE,
                color: '#ffcc00',
                fontSize: '11px',
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
  const { current: mapRef } = useMap();
  // HUD regions (side columns, bottom dock) that a callout must not slide under.
  // Callouts only render while the map is idle, so measuring here per render is cheap.
  const hudRects: DOMRect[] =
    typeof document === 'undefined'
      ? []
      : Array.from(document.querySelectorAll('.sb-left-col, .sb-right-col, .sb-dock, .sb-edge-tab, .sb-scalebar, .sb-offline-toast'))
          .map((el) => el.getBoundingClientRect())
          .filter((r) => r.width > 0 && r.height > 0 && r.right > 0 && r.left < window.innerWidth);
  // .sb-alert is CSS-zoomed with the HUD on wide screens; offsets and notch math follow it
  const vw = typeof window === 'undefined' ? 0 : window.innerWidth;
  const hudZoom = vw >= 3000 ? 1.5 : vw >= 2300 ? 1.125 : 1;
  // approximate callout half-extents in screen px (~310 x 90 at 1x)
  const HALF_W = 165 * hudZoom;
  const HALF_H = 48 * hudZoom;
  const vh = typeof window === 'undefined' ? 0 : window.innerHeight;
  // a box also counts as covered when it would leave the screen (top/bottom/side margins)
  const overHud = (l: number, t: number, r: number, b: number) =>
    t < 10 * hudZoom || b > vh - 4 || l < 4 || r > vw - 4 ||
    hudRects.some((h) => l < h.right && r > h.left && t < h.bottom && b > h.top);
  const coveredByHud = (lng: number, lat: number, dx: number, dy: number): boolean => {
    const map = mapRef?.getMap?.();
    if (!map || !hudRects.length) return false;
    const pt = map.project([lng, lat]);
    const canvas = map.getCanvas().getBoundingClientRect();
    const px = canvas.left + pt.x;
    const py = canvas.top + pt.y;
    // the event's own point must be on open map, and so must the box
    if (overHud(px - 4, py - 4, px + 4, py + 4)) return true;
    const cx = px + dx;
    const cy = py + dy;
    return overHud(cx - HALF_W, cy - HALF_H, cx + HALF_W, cy + HALF_H);
  };
  return (
    <>
      {spreadAlerts.map((n) => {
        const count = n.cluster_count || 1;
        const score = n.risk_score || 0;
        const riskColor = getRiskColor(score);
        const alertKey = n.alertKey || `${n.title}|${n.coords?.[0]},${n.coords?.[1]}`;

        // Color-blind accessible border pattern based on severity
        const threatBorderClass =
          score >= 9 ? 'threat-border-critical' :
          score >= 7 ? 'threat-border-high' :
          score >= 4 ? 'threat-border-medium' :
                       'threat-border-low';

        // A callout only counts as "spread" (leader line to its point) when the offset
        // actually clears the box; otherwise it sits just above its point with a notch and a
        // ringed anchor dot, so it never hides the spot it is about. A lifted callout slides
        // sideways (notch stays on the point) before giving up near the side rails.
        const spread = Math.abs(n.offsetX) > HALF_W + 8 || Math.abs(n.offsetY) > HALF_H + 8;
        const lifted = !spread;
        const liftDy = -(14 * hudZoom + HALF_H);
        let shift = 0;
        let isVisible = zoom >= 1;
        if (!selectedEntity) {
          if (spread) {
            if (coveredByHud(n.coords[1], n.coords[0], n.offsetX, n.offsetY)) isVisible = false;
          } else {
            const maxShift = HALF_W - 26 * hudZoom;
            const found = [0, -0.5, 0.5, -1, 1]
              .map((k) => Math.round(k * maxShift))
              .find((dx) => !coveredByHud(n.coords[1], n.coords[0], dx, liftDy));
            if (found === undefined) isVisible = false;
            else shift = found;
          }
        }
        const notchLeft = `calc(50% - ${shift / hudZoom}px)`;
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
            anchor={lifted ? 'bottom' : 'center'}
            offset={lifted ? [shift, -14 * hudZoom] : [n.offsetX, n.offsetY]}
            style={{ zIndex: 120 + score }}
            onClick={(e) => {
              e.originalEvent.stopPropagation();
              onEntityClick?.({ id: alertKey, type: 'news' });
            }}
          >
            <div className="relative group/alert">
              {spread && isVisible && (
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
                    strokeWidth="2"
                    strokeDasharray="4,3"
                    className="opacity-90"
                  />
                  <circle cx={-n.offsetX} cy={-n.offsetY} r="6" fill="none" stroke={riskColor} strokeOpacity="0.45" strokeWidth="2" />
                  <circle cx={-n.offsetX} cy={-n.offsetY} r="3.5" fill={riskColor} stroke="rgba(2,5,11,0.95)" strokeWidth="1.5" />
                </svg>
              )}

              <div
                data-sb-score={score}
                className={`sb-alert cursor-pointer transition-opacity duration-300 relative ${threatBorderClass}`}
                style={{
                  opacity: isVisible ? 1.0 : 0.0,
                  pointerEvents: isVisible ? 'auto' : 'none',
                  backgroundColor: 'rgba(var(--sb-glass), 0.9)',
                  borderColor: riskColor,
                  borderRadius: '12px',
                  padding: '9px 24px 10px 14px',
                  ['--risk' as string]: riskColor,
                  color: riskColor,
                  fontFamily: 'var(--font-jetbrains-mono), monospace',
                  fontSize: '12px',
                  fontWeight: 'bold',
                  textAlign: 'center',
                  zIndex: 10,
                  lineHeight: '1.3',
                  minWidth: '200px',
                }}
              >
                {isVisible && lifted && (
                  <div
                    className="absolute"
                    style={{
                      width: 0,
                      height: 0,
                      borderLeft: '7px solid transparent',
                      borderRight: '7px solid transparent',
                      borderTop: `7px solid ${riskColor}`,
                      left: notchLeft,
                      bottom: '-8px',
                      transform: 'translateX(-50%)',
                    }}
                  />
                )}
                {isVisible && lifted && (
                  <span
                    aria-hidden="true"
                    className="absolute pointer-events-none"
                    style={{
                      left: notchLeft,
                      bottom: '-18px',
                      width: 8,
                      height: 8,
                      marginLeft: -4,
                      borderRadius: '50%',
                      background: riskColor,
                      // dark ring + halo so the anchor reads even over dense clusters
                      boxShadow: `0 0 0 2px rgba(2, 5, 11, 0.95), 0 0 0 4px ${riskColor}55, 0 0 12px 2px ${riskColor}`,
                    }}
                  />
                )}
                {onDismiss && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onDismiss(alertKey);
                    }}
                    style={{
                      position: 'absolute',
                      top: '2px',
                      right: '2px',
                      width: '24px',
                      height: '24px',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      borderRadius: '8px',
                      background: 'transparent',
                      border: 'none',
                      cursor: 'pointer',
                      color: riskColor,
                      fontSize: '16px',
                      fontWeight: 'bold',
                      lineHeight: 1,
                      padding: 0,
                      opacity: 0.7,
                      zIndex: 20,
                    }}
                    onMouseEnter={(e) => (e.currentTarget.style.opacity = '1')}
                    onMouseLeave={(e) => (e.currentTarget.style.opacity = '0.7')}
                    aria-label="Dismiss alert"
                  >
                    ×
                  </button>
                )}
                <div className="sb-alert-head">
                  <span className="sb-alert-dot" aria-hidden="true" />
                  ALERT · LVL {score}
                </div>
                <div className="sb-alert-title">
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

// -- Telegram OSINT pins (HTML, above threat alert boxes) --
interface TelegramOsintMarkersProps {
  features: GeoJSON.Feature[];
  onEntityClick?: (entity: SelectedEntity | null) => void;
}

export function TelegramOsintMarkers({ features, onEntityClick }: TelegramOsintMarkersProps) {
  if (!features.length) return null;

  return (
    <>
      {features.map((feature) => {
        if (feature.geometry?.type !== 'Point') return null;
        const [lng, lat] = feature.geometry.coordinates as [number, number];
        const props = feature.properties || {};
        const id = String(props.id || '');
        if (!id) return null;
        const postCount = Number(props.post_count || 1);
        const size = postCount > 1 ? Math.min(30, 16 + Math.log2(postCount) * 5) : 16;

        return (
          <Marker
            key={`telegram-osint-${id}`}
            longitude={lng}
            latitude={lat}
            anchor="center"
            offset={TELEGRAM_MARKER_OFFSET}
            style={{ zIndex: 95 }}
            onClick={(e) => {
              e.originalEvent.stopPropagation();
              onEntityClick?.({
                id,
                type: 'telegram_osint',
                name: String(props.name || 'Telegram OSINT'),
              });
            }}
          >
            <div
              title={`Telegram OSINT${postCount > 1 ? ` (${postCount} posts)` : ''}`}
              style={{
                width: size,
                height: size,
                borderRadius: '50%',
                background: '#ef4444',
                border: '2.5px solid #fca5a5',
                boxShadow: '0 0 14px rgba(239, 68, 68, 0.75)',
                cursor: 'pointer',
              }}
            />
          </Marker>
        );
      })}
    </>
  );
}


/**
 * Cross-layer label declutter. Each label component only knows its own labels, so this
 * pass works on the rendered DOM: visible alert callouts win, then carrier labels, then
 * tracked-entity labels; anything overlapping a higher-priority box is hidden.
 * Runs when the map settles and on a slow interval while data ticks in.
 */
const MAX_CALLOUTS = 2;

export function LabelDeclutter() {
  const { current: mapRef } = useMap();
  React.useEffect(() => {
    const map = mapRef?.getMap?.();
    if (!map) return;
    const pad = 6;
    const run = () => {
      const boxes: DOMRect[] = [];
      const hits = (r: DOMRect) =>
        boxes.some(
          (b) => r.left - pad < b.right && r.right + pad > b.left && r.top - pad < b.bottom && r.bottom + pad > b.top,
        );
      document
        .querySelectorAll<HTMLElement>('.sb-left-col, .sb-right-col, .sb-dock, .sb-edge-tab, .sb-scalebar')
        .forEach((el) => {
          const r = el.getBoundingClientRect();
          if (r.width > 0 && r.height > 0) boxes.push(r);
        });
      // callouts: highest severity first; a lower one that would overlap is hidden, and at
      // most MAX_CALLOUTS stay open so the busiest regions of the map are not buried
      const callouts = Array.from(document.querySelectorAll<HTMLElement>('.sb-alert'))
        .filter((el) => getComputedStyle(el).opacity !== '0')
        .sort((a, b) => Number(b.dataset.sbScore || 0) - Number(a.dataset.sbScore || 0));
      let shown = 0;
      for (const el of callouts) {
        // hide the whole callout group (box + leader line + anchor dot), not just the box
        const host = el.parentElement ?? el;
        host.style.visibility = 'visible';
        el.style.visibility = ''; // inherit from the host
        const r = el.getBoundingClientRect();
        if (shown >= MAX_CALLOUTS || hits(r)) {
          host.style.visibility = 'hidden';
        } else {
          boxes.push(r);
          shown += 1;
        }
      }
      // cluster bubbles drawn in WebGL are obstacles too, so names never print across a count
      const canvas = map.getCanvas().getBoundingClientRect();
      const clusterLayers = (map.getStyle()?.layers || [])
        .filter((l) => l.type === 'circle' && /cluster/.test(l.id) && !/pulse|bg|halo/.test(l.id))
        .map((l) => l.id);
      if (clusterLayers.length) {
        try {
          for (const f of map.queryRenderedFeatures(undefined, { layers: clusterLayers })) {
            if (f.geometry.type !== 'Point') continue;
            const p = map.project(f.geometry.coordinates as [number, number]);
            const x = canvas.left + p.x;
            const y = canvas.top + p.y;
            boxes.push(new DOMRect(x - 12, y - 12, 24, 24));
          }
        } catch {
          /* style mid-reload: skip the WebGL obstacles this pass */
        }
      }
      // HTML cluster counts are never hidden, only treated as obstacles
      document.querySelectorAll<HTMLElement>('[data-sb-label="cluster"]').forEach((el) => {
        const r = el.getBoundingClientRect();
        if (r.width > 0) boxes.push(new DOMRect(r.left - 6, r.top - 4, r.width + 12, r.height + 8));
      });
      for (const kind of ['carrier', 'tracked', 'yacht', 'uav', 'quake']) {
        document.querySelectorAll<HTMLElement>(`[data-sb-label="${kind}"]`).forEach((el) => {
          el.style.visibility = 'visible';
          const r = el.getBoundingClientRect();
          if (r.width === 0) return;
          if (hits(r)) {
            el.style.visibility = 'hidden';
          } else {
            boxes.push(r);
          }
        });
      }
    };
    map.on('idle', run);
    map.on('moveend', run);
    const id = window.setInterval(run, 1200);
    run();
    return () => {
      map.off('idle', run);
      map.off('moveend', run);
      window.clearInterval(id);
    };
  }, [mapRef]);
  return null;
}
