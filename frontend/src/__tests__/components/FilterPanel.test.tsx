import React from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import FilterPanel from '@/components/FilterPanel';
import { getDefaultActiveLayers } from '@/lib/layerPreferences';

vi.mock('@/hooks/useDataStore', () => ({
  useDataKeys: () => ({
    commercial_flights: [],
    private_flights: [],
    private_jets: [],
    military_flights: [],
    tracked_flights: [],
    ships: [],
  }),
}));

vi.mock('@/i18n', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock('@/lib/motion', () => ({
  motion: {
    div: ({ children, ...props }: React.ComponentProps<'div'> & Record<string, unknown>) => {
      const rest = { ...props };
      for (const key of ['initial', 'animate', 'exit', 'transition']) delete rest[key];
      return <div {...(rest as React.ComponentProps<'div'>)}>{children}</div>;
    },
  },
  AnimatePresence: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

function openSection(title: string) {
  fireEvent.click(screen.getByText('FILTERS.TITLE'));
  fireEvent.click(screen.getByText(title));
}

describe('FilterPanel layer-off handling', () => {
  afterEach(() => cleanup());

  it('flags a section, warns, and enables the layer from the dialog', () => {
    const layers = { ...getDefaultActiveLayers(), tracked: false };
    const setActiveFilters = vi.fn();
    const onEnableLayers = vi.fn();
    render(
      <FilterPanel
        activeFilters={{}}
        setActiveFilters={setActiveFilters}
        activeLayers={layers}
        onEnableLayers={onEnableLayers}
      />,
    );

    fireEvent.click(screen.getByText('FILTERS.TITLE'));
    expect(screen.getAllByText('LAYER OFF')).toHaveLength(1);

    fireEvent.click(screen.getByText('TRACKED AIRCRAFT'));
    expect(screen.getByRole('status').textContent).toContain(
      'TRACKED AIRCRAFT LAYER IS OFF — THIS FILTER WILL NOT CHANGE THE MAP',
    );

    fireEvent.click(screen.getByRole('button', { name: 'ENABLE TRACKED AIRCRAFT' }));
    expect(onEnableLayers).toHaveBeenCalledWith(['tracked']);

    // Apply stays a plain apply; it never toggles layers itself.
    fireEvent.click(screen.getByText('Celebrity'));
    fireEvent.click(screen.getByRole('button', { name: 'APPLY (1)' }));
    expect(onEnableLayers).toHaveBeenCalledTimes(1);
    expect(setActiveFilters).toHaveBeenCalledWith({ tracked_category: ['Celebrity'] });
  });

  it('explains an empty list by layer state instead of "no matching results"', () => {
    const layers = { ...getDefaultActiveLayers(), flights: false };
    const { unmount } = render(
      <FilterPanel activeFilters={{}} setActiveFilters={vi.fn()} activeLayers={layers} />,
    );
    openSection('COMMERCIAL FLIGHTS');
    expect(screen.getByText('LAYER IS OFF — ENABLE IT ABOVE TO LOAD OPTIONS')).toBeTruthy();
    // No enable control when the caller cannot toggle layers.
    expect(screen.queryByRole('button', { name: /^ENABLE / })).toBeNull();
    unmount();

    render(
      <FilterPanel
        activeFilters={{}}
        setActiveFilters={vi.fn()}
        activeLayers={getDefaultActiveLayers()}
      />,
    );
    openSection('COMMERCIAL FLIGHTS');
    expect(screen.queryByRole('status')).toBeNull();
    expect(screen.getByText('WAITING FOR DATA…')).toBeTruthy();
  });

  it('offers one enable chip per layer for the private / jets section', () => {
    const layers = { ...getDefaultActiveLayers(), private: false };
    const onEnableLayers = vi.fn();
    render(
      <FilterPanel
        activeFilters={{}}
        setActiveFilters={vi.fn()}
        activeLayers={layers}
        onEnableLayers={onEnableLayers}
      />,
    );

    fireEvent.click(screen.getByText('FILTERS.TITLE'));
    // Jets is still on, so the section itself is not flagged.
    expect(screen.queryByText('LAYER OFF')).toBeNull();

    fireEvent.click(screen.getByText('PRIVATE / JETS'));
    expect(screen.getByRole('status').textContent).toContain(
      'PRIVATE AIRCRAFT LAYER IS OFF — THIS FILTER ONLY AFFECTS THE ENABLED LAYERS',
    );
    expect(screen.queryByRole('button', { name: 'ENABLE PRIVATE JETS' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'ENABLE PRIVATE AIRCRAFT' }));
    expect(onEnableLayers).toHaveBeenCalledWith(['private']);
  });

  it('does not flag anything when layer state is not supplied', () => {
    render(<FilterPanel activeFilters={{}} setActiveFilters={vi.fn()} />);
    openSection('TRACKED AIRCRAFT');
    expect(screen.queryByText('LAYER OFF')).toBeNull();
    expect(screen.queryByRole('status')).toBeNull();
  });
});
