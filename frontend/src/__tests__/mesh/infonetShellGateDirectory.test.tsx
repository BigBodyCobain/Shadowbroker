import React from 'react';
import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/mesh/meshIdentity', () => ({
  getNodeIdentity: vi.fn(() => ({ publicKey: 'test-public-key', nodeId: '!sb_test' })),
  getWormholeIdentityDescriptor: vi.fn(() => ({ publicKey: 'wormhole-public-key' })),
}));

vi.mock('@/mesh/wormholeIdentityClient', () => ({
  activateWormholeGatePersona: vi.fn(),
  createWormholeGatePersona: vi.fn(),
  enterWormholeGate: vi.fn(),
  fetchWormholeIdentity: vi.fn(),
  listWormholeGatePersonas: vi.fn(async () => ({ personas: [] })),
}));

vi.mock('@/components/InfonetTerminal/GateView', () => ({ default: () => <div>Gate view</div> }));
vi.mock('@/components/InfonetTerminal/MarketView', () => ({ default: () => <div>Market view</div> }));
vi.mock('@/components/InfonetTerminal/ProfileView', () => ({ default: () => <div>Profile view</div> }));
vi.mock('@/components/InfonetTerminal/MessagesView', () => ({ default: () => <div>Messages view</div> }));
vi.mock('@/components/InfonetTerminal/TerminalDashboard', () => ({ default: () => <div>Dashboard</div> }));
vi.mock('@/components/InfonetTerminal/WeatherWidget', () => ({ default: () => <div>Weather</div> }));
vi.mock('@/components/InfonetTerminal/TrendingPosts', () => ({ default: () => <div>Trending</div> }));
vi.mock('@/components/InfonetTerminal/HashchainEvents', () => ({ default: () => <div>Hashchain</div> }));
vi.mock('@/components/InfonetTerminal/NetworkStats', () => ({ default: () => <div>Network stats</div> }));
vi.mock('@/components/InfonetTerminal/AIQueryView', () => ({ default: () => <div>AI view</div> }));
vi.mock('@/components/InfonetTerminal/PetitionsView', () => ({ default: () => <div>Petitions</div> }));
vi.mock('@/components/InfonetTerminal/UpgradeView', () => ({ default: () => <div>Upgrades</div> }));
vi.mock('@/components/InfonetTerminal/ResolutionView', () => ({ default: () => <div>Resolution</div> }));
vi.mock('@/components/InfonetTerminal/GateShutdownView', () => ({ default: () => <div>Gate shutdown</div> }));
vi.mock('@/components/InfonetTerminal/BootstrapView', () => ({ default: () => <div>Bootstrap</div> }));
vi.mock('@/components/InfonetTerminal/FunctionKeyView', () => ({ default: () => <div>Function keys</div> }));

describe('InfonetShell gate directory', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    cleanup();
  });

  it('renders available gates under the landing logo section', async () => {
    const { default: InfonetShell } = await import('@/components/InfonetTerminal/InfonetShell');

    render(<InfonetShell isOpen onClose={() => {}} />);
    await act(async () => {
      vi.advanceTimersByTime(2500);
    });

    expect(screen.getByText('AVAILABLE GATES:')).toBeTruthy();
    expect(screen.getByRole('button', { name: /\[>\]\s*infonet/i })).toBeTruthy();
    expect(screen.getByRole('button', { name: /\[>\]\s*gathered-intel/i })).toBeTruthy();
  });
});
