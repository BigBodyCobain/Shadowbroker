/**
 * Public-viewer stand-in for the app's right-click "region dossier".
 *
 * The app asks its own backend, which then asks other services. The viewer
 * has no backend, so the visitor's browser asks one public service itself:
 * Microsoft Planetary Computer (the open Copernicus Sentinel-2 catalogue),
 * for the most recent low-cloud satellite scenes over the point. No key, no
 * account. The pictures are loaded straight from that service.
 *
 * It is a plain GET request to a host on the viewer's short allowlist. If
 * the search fails or is rate-limited, the panel falls back to the Esri
 * World Imagery picture of the same spot.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import type { RegionDossier, SelectedEntity } from '@/types/dashboard';

const STAC_SEARCH = 'https://planetarycomputer.microsoft.com/api/stac/v1/search';
const PREVIEW_HOST = 'planetarycomputer.microsoft.com';
const LOOKBACK_DAYS = 60;
const MAX_CLOUD_PERCENT = 30;
const CACHE_TTL_MS = 6 * 3600_000;
const REQUEST_TIMEOUT_MS = 12_000;

type Scene = Record<string, unknown>;
const cache = new Map<string, { data: RegionDossier; at: number }>();
const SEARCHING = { found: false, searching: true };

function cacheKey(lat: number, lng: number): string {
  return `${lat.toFixed(2)}_${lng.toFixed(2)}`;
}

async function getJson(url: string): Promise<unknown> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const res = await fetch(url, { signal: controller.signal, headers: { Accept: 'application/json' } });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } finally {
    window.clearTimeout(timer);
  }
}

function esriFallback(lat: number, lng: number, message: string): Scene {
  const latSpan = 0.18;
  const lngSpan = 0.24;
  const bbox = `${lng - lngSpan},${lat - latSpan},${lng + lngSpan},${lat + latSpan}`;
  const base = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/export';
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
    message,
  };
}

/** Only a picture address on the imagery service itself is ever shown. */
function previewAddress(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && url.hostname === PREVIEW_HOST ? url.toString() : null;
  } catch {
    return null;
  }
}

function sceneFromFeature(feature: Record<string, unknown>): Scene | null {
  const assets = (feature.assets || {}) as Record<string, { href?: unknown }>;
  const props = (feature.properties || {}) as Record<string, unknown>;
  const picture = previewAddress(assets.rendered_preview?.href);
  if (!picture) return null;
  return {
    found: true,
    scene_id: typeof feature.id === 'string' ? feature.id : null,
    datetime: typeof props.datetime === 'string' ? props.datetime : null,
    cloud_cover: typeof props['eo:cloud_cover'] === 'number' ? props['eo:cloud_cover'] : null,
    thumbnail_url: picture,
    fullres_url: picture,
    bbox: Array.isArray(feature.bbox) ? feature.bbox : null,
    platform: typeof props.platform === 'string' ? props.platform : 'Sentinel-2',
  };
}

async function fetchSentinelScenes(lat: number, lng: number): Promise<Scene> {
  const end = new Date();
  const start = new Date(end.getTime() - LOOKBACK_DAYS * 86400_000);
  const pad = 0.0005;
  const query = new URLSearchParams({
    collections: 'sentinel-2-l2a',
    bbox: [lng - pad, lat - pad, lng + pad, lat + pad].map((n) => n.toFixed(5)).join(','),
    datetime: `${start.toISOString().slice(0, 19)}Z/${end.toISOString().slice(0, 19)}Z`,
    sortby: '-datetime',
    limit: '3',
    query: JSON.stringify({ 'eo:cloud_cover': { lt: MAX_CLOUD_PERCENT } }),
  });
  try {
    const data = (await getJson(`${STAC_SEARCH}?${query}`)) as { features?: Record<string, unknown>[] };
    const scenes = (data.features || []).map(sceneFromFeature).filter((s): s is Scene => s !== null);
    if (scenes.length) return { ...scenes[0], scenes };
    return esriFallback(lat, lng, `No clear Sentinel-2 pass over this point in the last ${LOOKBACK_DAYS} days; showing Esri World Imagery instead.`);
  } catch {
    return esriFallback(lat, lng, 'The Sentinel-2 search did not answer; showing Esri World Imagery instead.');
  }
}

function dossier(lat: number, lng: number, sentinel2: Scene): RegionDossier {
  return {
    lat,
    lng,
    coordinates: { lat, lng },
    location: { display_name: `${lat.toFixed(4)}, ${lng.toFixed(4)}` },
    country: null,
    local: {
      name: 'Selected point',
      state: '',
      description: 'Satellite view',
      summary: 'The satellite picture of this point is shown on the map.',
      thumbnail: '',
    },
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

      setSelectedEntity({ type: 'region_dossier', id: `${lat.toFixed(4)}_${lng.toFixed(4)}`, extra: coords });

      const cached = cache.get(cacheKey(lat, lng));
      if (cached && Date.now() - cached.at < CACHE_TTL_MS) {
        setRegionDossier(cached.data);
        setRegionDossierLoading(false);
        return;
      }

      setRegionDossierLoading(true);
      setRegionDossier(dossier(lat, lng, SEARCHING));

      const sentinel2 = await fetchSentinelScenes(lat, lng);
      if (!isCurrent()) return;
      const result = dossier(lat, lng, sentinel2);
      setRegionDossier(result);
      setRegionDossierLoading(false);
      if (!sentinel2.fallback) {
        cache.set(cacheKey(lat, lng), { data: result, at: Date.now() });
        if (cache.size > 200) cache.delete(cache.keys().next().value as string);
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
