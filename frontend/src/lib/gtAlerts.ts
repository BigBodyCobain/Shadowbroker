import type { GTRiskPayload } from '@/types/dashboard';

export interface GtAlertRow {
  region: string;
  regionLabel: string;
  risk: number;
  conflict: number;
  unrest: number;
  financial: number;
  contagion: number;
  lat: number;
  lng: number;
  score: number;
  ignition: boolean;
  risk3d?: number;
  riskDelta?: number;
}

export function formatGtRegionLabel(region: string): string {
  const text = String(region || '').trim();
  if (!text) return 'unknown';
  const coord = text.match(/^(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)$/);
  if (coord) {
    return `${Number(coord[1]).toFixed(2)}°, ${Number(coord[2]).toFixed(2)}°`;
  }
  const parts = text.split(',').map((piece) => piece.trim()).filter(Boolean);
  if (parts.length >= 2) {
    const lat = Number(parts[0]);
    const lng = Number(parts[parts.length - 1]);
    if (Number.isFinite(lat) && Number.isFinite(lng)) {
      return `${lat.toFixed(2)}°, ${lng.toFixed(2)}°`;
    }
  }
  return text.replace(/_/g, ' ');
}

function validCoords(coords: unknown): { lat: number; lng: number } | null {
  if (!Array.isArray(coords) || coords.length < 2) return null;
  const lng = Number(coords[0]);
  const lat = Number(coords[1]);
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null;
  if (Math.abs(lat) < 0.001 && Math.abs(lng) < 0.001) return null;
  return { lat, lng };
}

function peakScore(props: Record<string, unknown>): number {
  const composite = Number(props.risk ?? 0);
  const financial = Number(props.financial ?? 0);
  const unrest = Number(props.unrest ?? 0);
  const conflict = Number(props.conflict ?? 0);
  return Math.max(composite, financial, unrest, conflict);
}

export function extractGtAlerts(
  payload?: GTRiskPayload | null,
  limit = 8,
): {
  alerts: GtAlertRow[];
  trackedRegions: number;
  plottedRegions: number;
  maxRegions: number;
} {
  const features = payload?.heatmap?.features || [];
  const meta = payload?.meta;
  const rows: GtAlertRow[] = [];

  for (const feature of features) {
    const coords = validCoords(feature.geometry?.coordinates);
    if (!coords) continue;
    const props = (feature.properties || {}) as Record<string, unknown>;
    const region = String(props.region || '').trim().toLowerCase();
    if (!region) continue;
    rows.push({
      region,
      regionLabel: formatGtRegionLabel(region),
      risk: Number(props.risk ?? 0),
      financial: Number(props.financial ?? 0),
      unrest: Number(props.unrest ?? 0),
      conflict: Number(props.conflict ?? 0),
      contagion: Number(props.contagion ?? 0),
      lat: coords.lat,
      lng: coords.lng,
      score: peakScore(props),
      ignition: Boolean(props.micro_ignition),
      risk3d: props.risk_3d_avg != null ? Number(props.risk_3d_avg) : undefined,
      riskDelta: props.risk_delta != null ? Number(props.risk_delta) : undefined,
    });
  }

  rows.sort((a, b) => {
    if (a.ignition !== b.ignition) return a.ignition ? -1 : 1;
    const deltaA = a.riskDelta ?? 0;
    const deltaB = b.riskDelta ?? 0;
    if (deltaA !== deltaB) return deltaB - deltaA;
    return b.score - a.score;
  });

  return {
    alerts: rows.slice(0, limit),
    trackedRegions: meta?.tracked_regions ?? features.length,
    plottedRegions: meta?.plotted_regions ?? rows.length,
    maxRegions: meta?.max_regions ?? 500,
  };
}