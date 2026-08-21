import React from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import FindLocateBar from '@/components/FindLocateBar';
import { getDefaultActiveLayers, saveActiveLayers } from '@/lib/layerPreferences';

const mockState = vi.hoisted(() => ({
  data: {} as Record<string, unknown>,
}));

vi.mock('@/hooks/useDataStore', () => ({
  useDataKeys: () => mockState.data,
}));

vi.mock('@/i18n', () => ({
  useTranslation: () => ({ t: () => 'Find / Locate' }),
}));

describe('FindLocateBar supplemental visible-layer search', () => {
  beforeEach(() => {
    localStorage.clear();
    mockState.data = {
      commercial_flights: [],
      private_flights: [],
      private_jets: [],
      military_flights: [],
      tracked_flights: [],
      ships: [],
      fishing_activity: [
        {
          id: 'gfw-rauda',
          type: 'fishing',
          lat: 57.1,
          lng: 21.4,
          start: '2026-08-20T00:00:00Z',
          end: '2026-08-20T01:00:00Z',
          vessel_id: 'v-1',
          vessel_ssvid: '275123456',
          vessel_name: 'RAUDA',
          vessel_flag: 'LVA',
          duration_hrs: 1,
        },
      ],
      satellites: [],
      trains: [],
      military_bases: [],
      kiwisdr: [],
    };
  });

  afterEach(() => {
    cleanup();
    localStorage.clear();
  });

  it('finds a fishing vessel while the fishing layer is visible', async () => {
    const onLocate = vi.fn();
    render(<FindLocateBar onLocate={onLocate} />);

    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'RAUDA' } });

    const result = await screen.findByText('RAUDA');
    expect(result).toBeTruthy();
    fireEvent.click(result);
    expect(onLocate).toHaveBeenCalledWith(57.1, 21.4, 'fishing-gfw-rauda', 'fishing_activity');
  });

  it('does not surface assets from a hidden supplemental layer', async () => {
    saveActiveLayers({ ...getDefaultActiveLayers(), fishing_activity: false });
    render(<FindLocateBar onLocate={vi.fn()} />);

    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'RAUDA' } });

    expect(await screen.findByText('NO MATCHING ASSETS')).toBeTruthy();
    expect(screen.queryByText('RAUDA')).toBeNull();
  });
});
