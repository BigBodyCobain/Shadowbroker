/**
 * Regression: right-click showed the generic Esri fallback instead of recent
 * Sentinel-2 scenes. The Esri placeholder filled the panel while the search ran,
 * and the scenes were only shown once the unrelated region-dossier lookup also
 * finished, so a slow dossier made the live imagery look missing.
 */
import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useRegionDossier } from '@/hooks/useRegionDossier';
import type { SelectedEntity } from '@/types/dashboard';

const SCENES = {
  found: true,
  platform: 'Sentinel-2B',
  datetime: '2026-10-17T17:53:29Z',
  fullres_url: 'https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?item=a',
  scenes: [
    { found: true, platform: 'Sentinel-2B', datetime: '2026-10-17T17:53:29Z' },
    { found: true, platform: 'Sentinel-2C', datetime: '2026-10-12T17:53:01Z' },
    { found: true, platform: 'Sentinel-2B', datetime: '2026-10-07T17:52:19Z' },
  ],
};

function jsonResponse(body: unknown, ok = true) {
  return Promise.resolve({ ok, status: ok ? 200 : 500, json: () => Promise.resolve(body) } as Response);
}

function setup() {
  let selected: SelectedEntity | null = null;
  const hook = renderHook(() =>
    useRegionDossier(selected, (entity) => {
      selected = entity;
    }),
  );
  return hook;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('useRegionDossier Sentinel-2 imagery', () => {
  it('shows a searching state, then scenes without waiting for the region dossier', async () => {
    let releaseDossier: (value: Response) => void = () => {};
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) =>
        url.includes('/api/sentinel2/search')
          ? jsonResponse(SCENES)
          : new Promise<Response>((resolve) => {
              releaseDossier = resolve;
            }),
      ),
    );
    const { result } = setup();

    let done: Promise<void> = Promise.resolve();
    act(() => {
      done = result.current.handleMapRightClick({ lat: 40.015, lng: -105.27 });
    });

    // First paint: an explicit searching placeholder, not Esri imagery dressed as a result.
    expect(result.current.regionDossier?.sentinel2).toMatchObject({ searching: true, found: false });

    // Scenes arrive while the dossier request is still pending.
    await waitFor(() => expect(result.current.regionDossier?.sentinel2).toMatchObject({ platform: 'Sentinel-2B' }));
    expect((result.current.regionDossier?.sentinel2 as typeof SCENES).scenes).toHaveLength(3);
    expect(result.current.regionDossierLoading).toBe(true);

    await act(async () => {
      releaseDossier({ ok: true, status: 200, json: () => Promise.resolve({ location: { display_name: 'Boulder' } }) } as Response);
      await done;
    });
    expect(result.current.regionDossier?.sentinel2).toMatchObject({ platform: 'Sentinel-2B' });
    expect(result.current.regionDossier?.location).toMatchObject({ display_name: 'Boulder' });
    expect(result.current.regionDossierLoading).toBe(false);
  });

  it('falls back to Esri imagery only when the live search fails', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => (url.includes('/api/sentinel2/search') ? jsonResponse({}, false) : jsonResponse({}))),
    );
    const { result } = setup();

    await act(async () => {
      await result.current.handleMapRightClick({ lat: 10, lng: 20 });
    });

    expect(result.current.regionDossier?.sentinel2).toMatchObject({ fallback: true, platform: 'Esri World Imagery' });
  });
});
