import { useCallback, useState, useEffect, useRef } from 'react';
import type { RegionDossier, SelectedEntity } from '@/types/dashboard';
import { API_BASE } from '@/lib/api';

// ─── CACHE ─────────────────────────────────────────────────────────────────
const _dossierCache = new Map<string, { data: RegionDossier; ts: number }>();
const CACHE_TTL = 86400_000;

function getCached(lat: number, lng: number): RegionDossier | null {
  const key = `${Math.round(lat * 10) / 10}_${Math.round(lng * 10) / 10}`;
  const entry = _dossierCache.get(key);
  if (entry && Date.now() - entry.ts < CACHE_TTL) return entry.data;
  if (entry) _dossierCache.delete(key);
  return null;
}

function setCache(lat: number, lng: number, data: RegionDossier) {
  const key = `${Math.round(lat * 10) / 10}_${Math.round(lng * 10) / 10}`;
  _dossierCache.set(key, { data, ts: Date.now() });
  if (_dossierCache.size > 500) {
    const oldest = _dossierCache.keys().next().value;
    if (oldest) _dossierCache.delete(oldest);
  }
}

function buildLocalSentinelFallback(lat: number, lng: number) {
  const latSpan = 0.18;
  const lngSpan = 0.24;
  const bbox = `${lng - lngSpan},${lat - latSpan},${lng + lngSpan},${lat + latSpan}`;
  const base =
    'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/export';
  return {
    found: true,
    scene_id: null,
    datetime: null,
    cloud_cover: null,
    thumbnail_url: `${base}?bbox=${bbox}&bboxSR=4326&imageSR=4326&size=640,360&format=png32&f=image`,
    fullres_url: `${base}?bbox=${bbox}&bboxSR=4326&imageSR=4326&size=1600,900&format=png32&f=image`,
    bbox: [lng - lngSpan, lat - latSpan, lng + lngSpan, lat + latSpan],
    platform: 'Esri World Imagery',
    fallback: true,
    message: 'Using local imagery fallback while live satellite search completes.',
  };
}

function buildLimitedDossier(lat: number, lng: number, error?: string): RegionDossier {
  return {
    lat,
    lng,
    coordinates: { lat, lng },
    location: {
      display_name: `${lat.toFixed(4)}, ${lng.toFixed(4)}`,
    },
    country: {
      name: 'LIMITED INTEL',
      official_name: '',
      leader: 'Unknown',
      government_type: 'Unavailable',
      population: 0,
      capital: 'Unknown',
      languages: [],
      currencies: [],
      region: '',
      subregion: '',
      area_km2: 0,
      flag_emoji: '',
    },
    local: {
      name: 'Selected coordinates',
      state: '',
      description: 'Fallback dossier',
      summary:
        'Live region enrichment is currently unavailable or slow. Local coordinates and fallback imagery are still available.',
      thumbnail: '',
    },
    warning: error || 'Region dossier is using local fallback data.',
  } as RegionDossier;
}

/**
 * Placeholder shown while the live Sentinel-2 search is in flight. It must not
 * look like a result: previously the Esri fallback filled this slot, so a slow
 * search read as "right-click only returns generic imagery".
 */
const SEARCHING_SENTINEL = { found: false, searching: true };

/** Self-hosted backend routes (#351) — no browser-direct third-party dossier calls. */
async function fetchSentinelScenes(lat: number, lng: number): Promise<Record<string, unknown>> {
  const qs = `lat=${encodeURIComponent(lat)}&lng=${encodeURIComponent(lng)}`;
  try {
    const res = await fetch(`${API_BASE}/api/sentinel2/search?${qs}`);
    if (res.ok) return await res.json();
    console.warn('[Dossier] Backend sentinel2/search HTTP', res.status);
  } catch (e) {
    console.warn('[Dossier] Backend sentinel2/search failed:', e);
  }
  return {
    ...buildLocalSentinelFallback(lat, lng),
    message: 'Live Sentinel-2 search failed; showing Esri World Imagery instead.',
  };
}

async function fetchRegionDossier(lat: number, lng: number): Promise<Record<string, unknown> | null> {
  const qs = `lat=${encodeURIComponent(lat)}&lng=${encodeURIComponent(lng)}`;
  try {
    const res = await fetch(`${API_BASE}/api/region-dossier?${qs}`);
    if (res.ok) return await res.json();
    console.warn('[Dossier] Backend region-dossier HTTP', res.status);
  } catch (e) {
    console.warn('[Dossier] Backend region-dossier failed:', e);
  }
  return null;
}

function dossierFromBackend(
  lat: number,
  lng: number,
  raw: Record<string, unknown>,
  sentinel2: Record<string, unknown>,
): RegionDossier {
  const coords = (raw.coordinates as { lat?: number; lng?: number }) || { lat, lng };
  return {
    lat,
    lng,
    coordinates: coords,
    location: raw.location ?? {},
    country: raw.country ?? null,
    local: raw.local ?? null,
    error: raw.error as string | undefined,
    warning: raw.warning as string | undefined,
    sentinel2,
  } as RegionDossier;
}

export function useRegionDossier(
  selectedEntity: SelectedEntity | null,
  setSelectedEntity: (entity: SelectedEntity | null) => void,
) {
  const [regionDossier, setRegionDossier] = useState<RegionDossier | null>(null);
  const [regionDossierLoading, setRegionDossierLoading] = useState(false);
  const requestRef = useRef(0);

  const handleMapRightClick = useCallback(
    async (coords: { lat: number; lng: number }) => {
      const { lat, lng } = coords;
      const request = ++requestRef.current;
      const isCurrent = () => requestRef.current === request;

      setSelectedEntity({
        type: 'region_dossier',
        id: `${lat.toFixed(4)}_${lng.toFixed(4)}`,
        extra: coords,
      });

      const cached = getCached(lat, lng);
      if (cached) {
        setRegionDossier(cached);
        setRegionDossierLoading(false);
        return;
      }

      setRegionDossierLoading(true);
      setRegionDossier({ ...buildLimitedDossier(lat, lng), sentinel2: SEARCHING_SENTINEL });

      // The imagery and the place lookup are independent: show Sentinel-2 scenes the
      // moment they arrive instead of waiting for the (often slower) region dossier.
      const sentinelPromise = fetchSentinelScenes(lat, lng).then((sentinel2) => {
        if (isCurrent()) setRegionDossier((prev) => (prev ? { ...prev, sentinel2 } : prev));
        return sentinel2;
      });
      const dossierPromise = fetchRegionDossier(lat, lng).then((dossier) => {
        if (isCurrent()) {
          setRegionDossier((prev) => {
            const sentinel2 = (prev?.sentinel2 as Record<string, unknown> | undefined) ?? SEARCHING_SENTINEL;
            return dossier
              ? dossierFromBackend(lat, lng, dossier, sentinel2)
              : {
                  ...buildLimitedDossier(lat, lng, 'Region dossier unavailable — check backend connection'),
                  sentinel2,
                };
          });
        }
        return dossier;
      });

      try {
        const [sentinel2, dossier] = await Promise.all([sentinelPromise, dossierPromise]);
        if (dossier && !sentinel2.fallback) setCache(lat, lng, dossierFromBackend(lat, lng, dossier, sentinel2));
      } catch (e) {
        console.error('[Dossier] Unexpected error:', e);
      } finally {
        if (isCurrent()) setRegionDossierLoading(false);
      }
    },
    [setSelectedEntity],
  );

  useEffect(() => {
    if (selectedEntity?.type !== 'region_dossier') {
      setRegionDossier(null);
      setRegionDossierLoading(false);
    }
  }, [selectedEntity]);

  return { regionDossier, regionDossierLoading, handleMapRightClick };
}
