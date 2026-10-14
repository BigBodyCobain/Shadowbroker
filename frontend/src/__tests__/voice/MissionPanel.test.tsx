import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import MissionPanel from '@/components/MissionPanel';
import type { MissionWorkspace } from '@/hooks/useMissionWorkspace';
import type { Mission } from '@/lib/missionClient';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
function workspace(mission: Mission | null = null): MissionWorkspace {
  return {
    open: true,
    setOpen: vi.fn(),
    mission,
    missions: [],
    busy: false,
    error: '',
    refresh: vi.fn(async () => {}),
    select: vi.fn(async () => {}),
    create: vi.fn(async () => ({}) as Mission),
    startFromText: vi.fn(async () => {}),
    run: vi.fn(async () => {}),
    control: vi.fn(async () => {}),
    approve: vi.fn(async () => {}),
    pin: vi.fn(async () => {}),
    showArticle: vi.fn(async () => {}),
    remove: vi.fn(async () => {}),
  };
}
function fetchSetup() {
  const calls: Array<{ path: string; body: unknown }> = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      calls.push({ path, body: init?.body ? JSON.parse(String(init.body)) : null });
      const data = path.includes('missions/config')
        ? {
            provider: 'compat',
            model: 'test-model',
            providers: [{ id: 'compat', label: 'Custom API' }],
            role_purposes: {},
          }
        : {
            watches: [
              {
                id: 'watch-1',
                type: 'keyword',
                params: { keyword: 'harbor' },
                fires: 2,
                paused: false,
              },
            ],
          };
      return new Response(JSON.stringify({ ok: true, ...data }));
    }),
  );
  return calls;
}
function savedMission(): Mission {
  return {
    id: 'mission-1',
    objective: 'Investigate the harbor',
    status: 'needs_approval',
    reason: 'Review action',
    calls: 2,
    max_calls: 5,
    role_index: 0,
    roles: [{ role: 'analyst', provider: 'compat', model: 'test-model', max_calls: 5, calls: 2 }],
    pending: {
      id: 'action-1',
      kind: 'approval',
      owner: 'dashboard-1',
      tool: 'add_watch',
      args: { type: 'keyword', params: { keyword: 'harbor' } },
      started: false,
    },
    events: [],
    reports: [],
    evidence: [
      {
        id: 'source-1',
        title: 'Harbor story',
        url: 'javascript:alert(1)',
        summary: 'Source evidence',
        tool: 'search_news',
        at: 1,
        pinned: false,
      },
    ],
  } as Mission;
}

describe('mission workspace', () => {
  it('creates a saved mission with explicit per-role model and call limits', async () => {
    fetchSetup();
    const api = workspace();
    render(<MissionPanel workspace={api} onClose={vi.fn()} />);
    await waitFor(() =>
      expect((screen.getByLabelText('researcher model') as HTMLInputElement).value).toBe(
        'test-model',
      ),
    );
    fireEvent.change(screen.getByLabelText('Mission objective'), {
      target: { value: 'Investigate this area' },
    });
    fireEvent.change(screen.getByLabelText('reviewer call limit'), { target: { value: '2' } });
    fireEvent.click(screen.getByText('Save mission'));
    await waitFor(() =>
      expect(api.create).toHaveBeenCalledWith(
        'Investigate this area',
        expect.arrayContaining([
          { role: 'reviewer', provider: 'compat', model: 'test-model', max_calls: 2 },
        ]),
      ),
    );
    expect(api.run).not.toHaveBeenCalled();
  });
  it('does not approve a proposed action until the operator clicks', async () => {
    fetchSetup();
    const api = workspace(savedMission());
    render(<MissionPanel workspace={api} onClose={vi.fn()} />);
    expect(api.approve).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText('Approve this exact action'));
    await waitFor(() => expect(api.approve).toHaveBeenCalledWith(true));
    expect(api.run).not.toHaveBeenCalled();
  });
  it('offers explicit recovery for a queued action from a saved dashboard without replaying it', async () => {
    fetchSetup();
    const mission = savedMission();
    mission.status = 'waiting_client';
    mission.pending = { ...mission.pending!, kind: 'client', tool: 'map_zoom', started: false };
    const api = workspace(mission);
    render(<MissionPanel workspace={api} onClose={vi.fn()} />);
    fireEvent.click(screen.getByText('Skip unconfirmed action'));
    await waitFor(() => expect(api.control).toHaveBeenCalledWith('resolve'));
    expect(api.run).not.toHaveBeenCalled();
  });

  it('pins evidence without turning an unsafe URL into a source link', async () => {
    fetchSetup();
    const api = workspace(savedMission());
    render(<MissionPanel workspace={api} onClose={vi.fn()} />);
    expect(screen.queryByRole('link', { name: /Source/ })).toBeNull();
    fireEvent.click(screen.getByText('Pin evidence'));
    await waitFor(() => expect(api.pin).toHaveBeenCalledWith('source-1', true));
  });
  it('exposes persisted monitoring and explicit pause controls', async () => {
    const calls = fetchSetup();
    render(<MissionPanel workspace={workspace()} onClose={vi.fn()} />);
    await screen.findByText('Pause watch');
    fireEvent.click(screen.getByText('Pause watch'));
    await waitFor(() =>
      expect(
        calls.some(
          (call) =>
            call.path.includes('watches/watch-1') &&
            JSON.stringify(call.body) === '{"paused":true}',
        ),
      ).toBe(true),
    );
  });
});
