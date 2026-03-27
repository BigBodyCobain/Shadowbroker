import { useCallback, useState, useEffect } from 'react';
import type { RegionDossier, SelectedEntity } from '@/types/dashboard';

// ─── CACHE ─────────────────────────────────────────────────────────────────
// Simple in-memory cache keyed by rounded lat/lng (0.1° ≈ 11km grid), 24h TTL.
const _dossierCache = new Map<string, { data: RegionDossier; ts: number }>();
const CACHE_TTL = 86400_000; // 24 hours in ms

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
  // Evict oldest entries if cache exceeds 500
  if (_dossierCache.size > 500) {
    const oldest = _dossierCache.keys().next().value;
    if (oldest) _dossierCache.delete(oldest);
  }
}

// ─── ESRI WORLD IMAGERY FALLBACK ───────────────────────────────────────────
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

// ─── BROWSER-DIRECT API CALLS ──────────────────────────────────────────────
// All external APIs below support CORS — no backend proxy needed.

/** Reverse geocode via Nominatim (direct browser call). */
async function reverseGeocode(lat: number, lng: number) {
  const url =
    `https://nominatim.openstreetmap.org/reverse?` +
    `lat=${lat}&lon=${lng}&format=json&zoom=10&addressdetails=1&accept-language=en`;
  const res = await fetch(url, {
    headers: { 'User-Agent': 'ShadowBroker-OSINT/1.0 (live-risk-dashboard)' },
  });
  if (!res.ok) throw new Error(`Nominatim HTTP ${res.status}`);
  const data = await res.json();
  const addr = data.address || {};
  return {
    city: addr.city || addr.town || addr.village || addr.county || '',
    state: addr.state || addr.region || '',
    country: addr.country || '',
    country_code: (addr.country_code || '').toUpperCase(),
    display_name: data.display_name || '',
  };
}

/** Fetch country data from RestCountries (direct browser call). */
async function fetchCountryData(countryCode: string) {
  if (!countryCode) return {};
  const url =
    `https://restcountries.com/v3.1/alpha/${countryCode}` +
    `?fields=name,population,capital,languages,region,subregion,area,currencies,borders,flag`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`RestCountries HTTP ${res.status}`);
  const data = await res.json();
  return Array.isArray(data) ? data[0] || {} : data || {};
}

/** Fetch head of state + government type from Wikidata SPARQL (direct browser call). */
async function fetchLeader(countryName: string) {
  if (!countryName) return { leader: 'Unknown', government_type: 'Unknown' };
  const safeName = countryName.replace(/"/g, '\\"').replace(/'/g, "\\'");
  const sparql = `
    SELECT ?leaderLabel ?govTypeLabel WHERE {
      ?country wdt:P31 wd:Q6256 ;
               rdfs:label "${safeName}"@en .
      OPTIONAL { ?country wdt:P35 ?leader . }
      OPTIONAL { ?country wdt:P122 ?govType . }
      SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
    } LIMIT 1
  `;
  const url = `https://query.wikidata.org/sparql?query=${encodeURIComponent(sparql)}&format=json`;
  const res = await fetch(url, {
    headers: { Accept: 'application/sparql-results+json' },
  });
  if (!res.ok) throw new Error(`Wikidata HTTP ${res.status}`);
  const results = (await res.json()).results?.bindings || [];
  if (results.length > 0) {
    return {
      leader: results[0].leaderLabel?.value || 'Unknown',
      government_type: results[0].govTypeLabel?.value || 'Unknown',
    };
  }
  return { leader: 'Unknown', government_type: 'Unknown' };
}

/** Fetch Wikipedia summary for a place (direct browser call). */
async function fetchLocalWikiSummary(placeName: string, countryName = '') {
  if (!placeName) return {};
  const candidates = [placeName];
  if (countryName) candidates.push(`${placeName}, ${countryName}`);

  for (const name of candidates) {
    try {
      const slug = encodeURIComponent(name.replace(/ /g, '_'));
      const url = `https://en.wikipedia.org/api/rest_v1/page/summary/${slug}`;
      const res = await fetch(url);
      if (!res.ok) continue;
      const data = await res.json();
      if (data.type === 'disambiguation') continue;
      return {
        description: data.description || '',
        extract: data.extract || '',
        thumbnail: data.thumbnail?.source || '',
      };
    } catch {
      continue;
    }
  }
  return {};
}

/** Search for Sentinel-2 imagery via Microsoft Planetary Computer STAC (direct browser call). */
async function fetchSentinel2Direct(lat: number, lng: number) {
  const now = new Date();
  const thirtyDaysAgo = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);
  const payload = {
    collections: ['sentinel-2-l2a'],
    intersects: { type: 'Point', coordinates: [lng, lat] },
    datetime: `${thirtyDaysAgo.toISOString()}/${now.toISOString()}`,
    sortby: [{ field: 'datetime', direction: 'desc' }],
    limit: 3,
    query: { 'eo:cloud_cover': { lt: 30 } },
  };

  const res = await fetch('https://planetarycomputer.microsoft.com/api/stac/v1/search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });

  if (!res.ok) throw new Error(`Planetary Computer HTTP ${res.status}`);
  const data = await res.json();
  const features = data.features || [];
  if (!features.length) return null; // No scenes — caller uses Esri fallback

  const item = features[0];
  const assets = item.assets || {};
  const rendered = assets.rendered_preview || {};
  const thumbnail = assets.thumbnail || {};

  return {
    found: true,
    scene_id: item.id,
    datetime: item.properties?.datetime,
    cloud_cover: item.properties?.['eo:cloud_cover'],
    thumbnail_url: thumbnail.href || rendered.href,
    fullres_url: rendered.href || thumbnail.href,
    bbox: item.bbox ? [...item.bbox] : null,
    platform: item.properties?.platform || 'Sentinel-2',
  };
}

// ─── MAIN HOOK ─────────────────────────────────────────────────────────────

export function useRegionDossier(
  selectedEntity: SelectedEntity | null,
  setSelectedEntity: (entity: SelectedEntity | null) => void,
) {
  const [regionDossier, setRegionDossier] = useState<RegionDossier | null>(null);
  const [regionDossierLoading, setRegionDossierLoading] = useState(false);

  const handleMapRightClick = useCallback(
    async (coords: { lat: number; lng: number }) => {
      const { lat, lng } = coords;
      const esriFallback = buildLocalSentinelFallback(lat, lng);

      setSelectedEntity({
        type: 'region_dossier',
        id: `${lat.toFixed(4)}_${lng.toFixed(4)}`,
        extra: coords,
      });
      setRegionDossierLoading(true);

      // Check cache first
      const cached = getCached(lat, lng);
      if (cached) {
        setRegionDossier(cached);
        setRegionDossierLoading(false);
        return;
      }

      // Show fallback immediately while API calls are in flight
      setRegionDossier({
        ...buildLimitedDossier(lat, lng),
        sentinel2: esriFallback,
      });

      try {
        // ── Phase 1: Geocode + Sentinel-2 in parallel ──────────────────
        const [geoResult, sentinelResult] = await Promise.allSettled([
          reverseGeocode(lat, lng),
          fetchSentinel2Direct(lat, lng),
        ]);

        // Parse geocode
        let geo = { city: '', state: '', country: '', country_code: '', display_name: '' };
        if (geoResult.status === 'fulfilled') {
          geo = geoResult.value;
        } else {
          console.warn('[Dossier] Reverse geocode failed:', geoResult.reason);
        }

        // Parse sentinel
        let sentinel2: Record<string, unknown> = esriFallback;
        if (sentinelResult.status === 'fulfilled' && sentinelResult.value) {
          sentinel2 = sentinelResult.value;
        } else if (sentinelResult.status === 'rejected') {
          console.warn('[Dossier] Sentinel-2 search failed:', sentinelResult.reason);
        }
        // sentinelResult fulfilled but null → no scenes found, keep Esri fallback

        // If no country found (ocean, uninhabited), show limited dossier
        if (!geo.country) {
          const result: RegionDossier = {
            lat,
            lng,
            coordinates: { lat, lng },
            location: geo.display_name
              ? geo
              : { display_name: `${lat.toFixed(4)}, ${lng.toFixed(4)}` },
            country: null,
            local: null,
            error: 'No country data — possibly international waters or uninhabited area',
            sentinel2,
          } as RegionDossier;
          setRegionDossier(result);
          setCache(lat, lng, result);
          setRegionDossierLoading(false);
          return;
        }

        // ── Phase 2: Country + Leader + Wiki in parallel ───────────────
        const [countryResult, leaderResult, localWikiResult, countryWikiResult] =
          await Promise.allSettled([
            fetchCountryData(geo.country_code),
            fetchLeader(geo.country),
            fetchLocalWikiSummary(geo.city || geo.state, geo.country),
            fetchLocalWikiSummary(geo.country, ''),
          ]);

        // Parse country data
        let countryData: Record<string, unknown> = {};
        if (countryResult.status === 'fulfilled') {
          countryData = countryResult.value as Record<string, unknown>;
        } else {
          console.warn('[Dossier] Country data failed:', countryResult.reason);
        }

        // Parse leader data
        let leaderData = { leader: 'Unknown', government_type: 'Unknown' };
        if (leaderResult.status === 'fulfilled') {
          leaderData = leaderResult.value;
        } else {
          console.warn('[Dossier] Leader data failed:', leaderResult.reason);
        }

        // Parse local wiki
        let localData: Record<string, string> = {};
        if (localWikiResult.status === 'fulfilled') {
          localData = localWikiResult.value as Record<string, string>;
        } else {
          console.warn('[Dossier] Local wiki failed:', localWikiResult.reason);
        }

        // If no local data, try country wiki summary
        if (!localData.extract && countryWikiResult.status === 'fulfilled') {
          const cw = countryWikiResult.value as Record<string, string>;
          if (cw.extract) localData = cw;
        }

        // Build languages list
        const languages = countryData.languages as Record<string, string> | undefined;
        const langList = languages ? Object.values(languages) : [];

        // Build currencies list
        const currencies = countryData.currencies as
          | Record<string, { name: string; symbol?: string }>
          | undefined;
        const currencyList: string[] = [];
        if (currencies) {
          for (const v of Object.values(currencies)) {
            if (v && typeof v === 'object') {
              const sym = v.symbol || '';
              const nm = v.name || '';
              currencyList.push(sym ? `${nm} (${sym})` : nm);
            }
          }
        }

        const nameData = countryData.name as
          | { common?: string; official?: string }
          | undefined;
        const capitalData = countryData.capital as string[] | undefined;

        // ── Assemble final dossier (exact same shape as backend) ───────
        const result: RegionDossier = {
          lat,
          lng,
          coordinates: { lat, lng },
          location: {
            city: geo.city,
            state: geo.state,
            country: geo.country,
            country_code: geo.country_code,
            display_name: geo.display_name,
          },
          country: {
            name: nameData?.common || geo.country,
            official_name: nameData?.official || '',
            leader: leaderData.leader,
            government_type: leaderData.government_type,
            population: (countryData.population as number) || 0,
            capital: capitalData?.length ? capitalData[0] : 'Unknown',
            languages: langList,
            currencies: currencyList,
            region: (countryData.region as string) || '',
            subregion: (countryData.subregion as string) || '',
            area_km2: (countryData.area as number) || 0,
            flag_emoji: (countryData.flag as string) || '',
          },
          local: {
            name: geo.city,
            state: geo.state,
            description: localData.description || '',
            summary: localData.extract || '',
            thumbnail: localData.thumbnail || '',
          },
          sentinel2,
        } as RegionDossier;

        setRegionDossier(result);
        setCache(lat, lng, result);
      } catch (e) {
        console.error('[Dossier] Unexpected error:', e);
        setRegionDossier({
          ...buildLimitedDossier(lat, lng, 'Region dossier request failed unexpectedly'),
          sentinel2: esriFallback,
        });
      } finally {
        setRegionDossierLoading(false);
      }
    },
    [setSelectedEntity],
  );

  // Clear dossier when selecting a different entity type
  useEffect(() => {
    if (selectedEntity?.type !== 'region_dossier') {
      setRegionDossier(null);
      setRegionDossierLoading(false);
    }
  }, [selectedEntity]);

  return { regionDossier, regionDossierLoading, handleMapRightClick };
}
