/**
 * Agent fly_to zoom regression.
 *
 * `sar_focus_aoi` carries a zoom: a world-view revert asks for ~2, a tight
 * AOI for ~9.  The zoom used to be dropped between the poll and the map, so
 * every agent move landed at a hardcoded zoom 8 — "show the whole world"
 * rendered as a patch of empty ocean.  These tests pin the whole path:
 * the hook forwards zoom, the dashboard stores it, the viewer honors it.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import * as fs from 'fs';
import * as path from 'path';

import { useAgentActions } from '@/hooks/useAgentActions';

const SRC_DIR = path.resolve(__dirname, '../../');

function readSource(rel: string): string {
  return fs.readFileSync(path.join(SRC_DIR, rel), 'utf-8');
}

function mockActions(actions: unknown[]) {
  return vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ actions }),
  });
}

describe('useAgentActions — fly_to zoom', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('forwards the zoom the agent asked for', async () => {
    vi.stubGlobal(
      'fetch',
      mockActions([{ action: 'fly_to', lat: 20, lng: 0, zoom: 2, aoi_id: 'world' }]),
    );
    const onFlyTo = vi.fn();
    renderHook(() => useAgentActions(vi.fn(), onFlyTo));

    await waitFor(() =>
      expect(onFlyTo).toHaveBeenCalledWith({ lat: 20, lng: 0, zoom: 2 }),
    );
  });

  it('leaves zoom undefined when the action omits it', async () => {
    vi.stubGlobal('fetch', mockActions([{ action: 'fly_to', lat: 51.5, lng: -0.1 }]));
    const onFlyTo = vi.fn();
    renderHook(() => useAgentActions(vi.fn(), onFlyTo));

    await waitFor(() =>
      expect(onFlyTo).toHaveBeenCalledWith({ lat: 51.5, lng: -0.1, zoom: undefined }),
    );
  });
});

describe('fly_to zoom survives the wiring', () => {
  it('the dashboard stores the agent zoom in flyToLocation', () => {
    const page = readSource('app/page.tsx');
    expect(page).toMatch(
      /useAgentActions\(\s*handleMapRightClick,\s*\(\{ lat, lng, zoom \}\) => \{\s*setFlyToLocation\(\{ lat, lng, zoom, ts: Date\.now\(\) \}\);/,
    );
  });

  it('the viewer flies to the requested zoom, defaulting to 8', () => {
    const viewer = readSource('components/MaplibreViewer.tsx');
    expect(viewer).toContain('zoom: flyToLocation.zoom ?? 8,');
    expect(viewer).not.toMatch(/center: \[flyToLocation\.lng, flyToLocation\.lat\],\s*zoom: 8,/);
  });
});
