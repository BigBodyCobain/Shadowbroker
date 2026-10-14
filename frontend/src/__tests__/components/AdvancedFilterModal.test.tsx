import React from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import AdvancedFilterModal, { MAX_RENDERED_OPTIONS } from '@/components/AdvancedFilterModal';

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

const names = Array.from({ length: 1000 }, (_, i) => `VESSEL ${String(i).padStart(4, '0')}`);

function renderModal() {
  return render(
    <AdvancedFilterModal
      title="MARITIME VESSELS"
      icon={null}
      accentColor="#3B82F6"
      accentColorName="blue"
      fields={[{ key: 'ship_name', label: 'VESSEL NAME', options: names }]}
      activeFilters={{}}
      onApply={vi.fn()}
      onClose={vi.fn()}
    />,
  );
}

describe('AdvancedFilterModal large option lists', () => {
  afterEach(() => cleanup());

  it('mounts only the head of a long list and says how much is hidden', () => {
    renderModal();
    const rows = screen.getAllByRole('button').filter((b) => b.textContent?.startsWith('VESSEL '));
    expect(rows).toHaveLength(MAX_RENDERED_OPTIONS);
    expect(screen.getByText('1000 AVAILABLE')).toBeTruthy();
    expect(screen.getByText(/SHOWING 300 OF 1,000/)).toBeTruthy();
  });

  it('renders the whole list once the search narrows it', () => {
    renderModal();
    fireEvent.change(screen.getByPlaceholderText(/Search vessel name/i), {
      target: { value: 'VESSEL 09' },
    });
    const rows = screen.getAllByRole('button').filter((b) => b.textContent?.startsWith('VESSEL '));
    expect(rows).toHaveLength(100);
    expect(screen.queryByText(/SHOWING/)).toBeNull();
    expect(screen.getByText('100 AVAILABLE')).toBeTruthy();
  });
});
