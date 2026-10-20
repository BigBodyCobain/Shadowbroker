import fs from 'fs';
import path from 'path';
import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  CARTO_ATTRIBUTION_HTML,
  OPENFREEMAP_ATTRIBUTION_HTML,
  OPENFREEMAP_STYLE_URLS,
  OSM_ATTRIBUTION_HTML,
  buildBasemapStyle,
  cartoTileUrls,
  darkStyle,
  lightStyle,
} from '@/components/map/styles/mapStyles';
import {
  BASEMAP_CONFIG_HARD_TIMEOUT_MS,
  BASEMAP_CONFIG_SOFT_TIMEOUT_MS,
  __resetBasemapConfigCache,
  useBasemapConfig,
} from '@/hooks/useBasemapConfig';

const VIEWER_SRC = fs.readFileSync(
  path.join(__dirname, '..', '..', 'components', 'MaplibreViewer.tsx'),
  'utf-8',
);

describe('buildBasemapStyle', () => {
  it('uses keyless OpenFreeMap styles when CARTO is not configured', () => {
    expect(buildBasemapStyle('dark')).toBe(OPENFREEMAP_STYLE_URLS.dark);
    expect(buildBasemapStyle('light')).toBe(OPENFREEMAP_STYLE_URLS.light);
    expect(buildBasemapStyle('dark', '   ')).toBe(OPENFREEMAP_STYLE_URLS.dark);
  });

  it('keeps CARTO as the compatibility path when an operator configured a key', () => {
    const style = buildBasemapStyle('light', 'my key');
    expect(typeof style).toBe('object');
    if (typeof style === 'string') throw new Error('expected CARTO style object');

    const source = style.sources['carto-light'];
    expect(source.tiles).toHaveLength(4);
    for (const url of source.tiles) {
      expect(url).toMatch(/\/rastertiles\/light_all\/\{z\}\/\{x\}\/\{y\}@2x\.png\?key=my%20key$/);
    }
    expect(style.layers[0]).toMatchObject({ id: 'carto-light-layer', source: 'carto-light' });
  });

  it('requires a non-empty CARTO key before building CARTO tile URLs', () => {
    expect(cartoTileUrls('dark', 'my key')).toHaveLength(4);
    expect(cartoTileUrls('dark', 'my key')[0]).toContain('?key=my%20key');
  });

  it('keeps the keyless default exports in sync with the builder', () => {
    expect(darkStyle).toBe(OPENFREEMAP_STYLE_URLS.dark);
    expect(lightStyle).toBe(OPENFREEMAP_STYLE_URLS.light);
  });

  it('keeps OpenStreetMap/CARTO attribution on the optional CARTO raster path', () => {
    const style = buildBasemapStyle('dark', 'k');
    if (typeof style === 'string') throw new Error('expected CARTO style object');
    const source = Object.values(style.sources)[0];
    expect(source.attribution).toContain('openstreetmap.org/copyright');
    expect(source.attribution).toContain('carto.com/attribution');
  });
});

describe('MaplibreViewer attribution and basemap gating', () => {
  it('renders OSM plus provider-specific attribution', () => {
    expect(VIEWER_SRC).toContain('<AttributionControl');
    expect(VIEWER_SRC).toContain('OSM_ATTRIBUTION_HTML');
    expect(VIEWER_SRC).toContain('CARTO_ATTRIBUTION_HTML');
    expect(VIEWER_SRC).toContain('OPENFREEMAP_ATTRIBUTION_HTML');
    expect(OSM_ATTRIBUTION_HTML).toContain('openstreetmap.org/copyright');
    expect(CARTO_ATTRIBUTION_HTML).toContain('carto.com/attribution');
    expect(OPENFREEMAP_ATTRIBUTION_HTML).toContain('openfreemap.org');
  });

  it('gates only long enough to resolve the optional CARTO override', () => {
    expect(VIEWER_SRC).toContain('{basemapConfigLoaded && (');
    expect(VIEWER_SRC).toMatch(/const \{ cartoApiKey, loaded: basemapConfigLoaded \} = useBasemapConfig\(\)/);
    expect(BASEMAP_CONFIG_SOFT_TIMEOUT_MS).toBeLessThan(BASEMAP_CONFIG_HARD_TIMEOUT_MS);
  });

  it('does not require the old CARTO-only imagery insertion anchor', () => {
    expect(VIEWER_SRC).not.toContain('beforeId="imagery-ceiling"');
  });
});

describe('useBasemapConfig', () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.useFakeTimers();
    __resetBasemapConfigCache();
    fetchMock.mockReset();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  function jsonResponse(body: unknown, ok = true) {
    return Promise.resolve({ ok, json: () => Promise.resolve(body) } as Response);
  }

  it('starts pending and resolves with the key', async () => {
    fetchMock.mockReturnValue(jsonResponse({ carto: { configured: true, key: ' abc ' } }));
    const { result } = renderHook(() => useBasemapConfig());
    expect(result.current).toEqual({ cartoApiKey: null, loaded: false });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current).toEqual({ cartoApiKey: 'abc', loaded: true });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0][0])).toMatch(/\/api\/basemap-config$/);
  });

  it('fails open with the unkeyed config on a non-OK response', async () => {
    fetchMock.mockReturnValue(jsonResponse({ detail: 'nope' }, false));
    const { result } = renderHook(() => useBasemapConfig());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current).toEqual({ cartoApiKey: null, loaded: true });
  });

  it('fails open on a network error', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));
    const { result } = renderHook(() => useBasemapConfig());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current).toEqual({ cartoApiKey: null, loaded: true });
  });

  it('releases the map after the soft timeout, then applies a late key', async () => {
    let resolveFetch: (value: Response) => void = () => {};
    fetchMock.mockReturnValue(new Promise<Response>((resolve) => (resolveFetch = resolve)));
    const { result } = renderHook(() => useBasemapConfig());

    await act(async () => {
      await vi.advanceTimersByTimeAsync(BASEMAP_CONFIG_SOFT_TIMEOUT_MS);
    });
    expect(result.current).toEqual({ cartoApiKey: null, loaded: true });

    await act(async () => {
      resolveFetch({ ok: true, json: () => Promise.resolve({ carto: { key: 'late' } }) } as Response);
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current).toEqual({ cartoApiKey: 'late', loaded: true });
  });

  it('aborts the request at the hard timeout and stays unkeyed', async () => {
    fetchMock.mockImplementation(
      (_url: string, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
        }),
    );
    const { result } = renderHook(() => useBasemapConfig());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(BASEMAP_CONFIG_HARD_TIMEOUT_MS + 1);
    });
    expect(result.current).toEqual({ cartoApiKey: null, loaded: true });
    expect(fetchMock.mock.calls[0][1]?.signal?.aborted).toBe(true);
  });

  it('shares one request across mounts and caches only successes', async () => {
    fetchMock.mockReturnValue(jsonResponse({ carto: { key: 'shared' } }));
    const a = renderHook(() => useBasemapConfig());
    const b = renderHook(() => useBasemapConfig());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(a.result.current.cartoApiKey).toBe('shared');
    expect(b.result.current.cartoApiKey).toBe('shared');
    expect(fetchMock).toHaveBeenCalledTimes(1);

    cleanup();
    const c = renderHook(() => useBasemapConfig());
    expect(c.result.current).toEqual({ cartoApiKey: 'shared', loaded: true });
    expect(fetchMock).toHaveBeenCalledTimes(1);

    __resetBasemapConfigCache();
    fetchMock.mockReturnValueOnce(jsonResponse({}, false));
    fetchMock.mockReturnValueOnce(jsonResponse({ carto: { key: 'second-try' } }));
    cleanup();
    const d = renderHook(() => useBasemapConfig());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(d.result.current).toEqual({ cartoApiKey: null, loaded: true });
    cleanup();
    const e = renderHook(() => useBasemapConfig());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(e.result.current).toEqual({ cartoApiKey: 'second-try', loaded: true });
  });
});

