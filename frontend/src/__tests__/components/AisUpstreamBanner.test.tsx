import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import type { AisUpstreamHealth } from '@/hooks/useAisUpstreamHealth';

const healthMock = vi.fn<() => AisUpstreamHealth | null>();
vi.mock('@/hooks/useAisUpstreamHealth', () => ({
  useAisUpstreamHealth: () => healthMock(),
}));

import { AisUpstreamBanner } from '@/components/AisUpstreamBanner';

function outage(overrides: Partial<AisUpstreamHealth> = {}): AisUpstreamHealth {
  return {
    connected: false,
    lastMsgAgeSeconds: 600,
    degradedTls: false,
    proxySpawnCount: 3,
    aisEnabled: true,
    aishubConfigured: false,
    shipLayersActive: true,
    ...overrides,
  };
}

describe('AisUpstreamBanner', () => {
  beforeEach(() => healthMock.mockReset());

  it('shows the outage notice when ship layers are on and AIS is silent', () => {
    healthMock.mockReturnValue(outage());
    render(<AisUpstreamBanner />);
    expect(screen.getByRole('status').textContent).toContain('Ship data temporarily unavailable');
  });

  it('stays hidden when every ship layer is off (#666)', () => {
    healthMock.mockReturnValue(outage({ shipLayersActive: false }));
    const { container } = render(<AisUpstreamBanner />);
    expect(container.innerHTML).toBe('');
  });

  it('stays hidden when AIS is connected', () => {
    healthMock.mockReturnValue(outage({ connected: true }));
    const { container } = render(<AisUpstreamBanner />);
    expect(container.innerHTML).toBe('');
  });
});
