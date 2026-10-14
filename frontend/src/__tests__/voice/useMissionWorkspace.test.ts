import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useMissionWorkspace } from '@/hooks/useMissionWorkspace';
import { executeClientVerb, type ClientToolContext } from '@/lib/clientTools';
import type { GroundingSnapshot } from '@/lib/voiceGroundingTypes';

vi.mock('@/lib/clientTools', () => ({ executeClientVerb: vi.fn() }));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.resetAllMocks();
  sessionStorage.clear();
});
const bindings = () => ({}) as ClientToolContext;
const snapshot = async () => ({ schema: 'sb.grounding.v1', selection: null }) as GroundingSnapshot;
const base = {
  id: 'mission',
  revision: 2,
  owner: 'dashboard-saved',
  status: 'running',
  pending: null,
  objective: 'Inspect the harbor',
};
const action = {
  id: 'action',
  kind: 'client',
  tool: 'toggle_layer',
  args: { layer: 'ships', enabled: true },
  owner: 'dashboard-saved',
  started: false,
};

describe('mission runner', () => {
  it('continues inference only after the actual browser receipt', async () => {
    sessionStorage.setItem('shadowbroker-mission-dashboard', 'dashboard-saved');
    const calls: string[] = [];
    let advanced = 0;
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const path = String(input).split('/').pop()!;
        calls.push(path);
        if (path === 'missions') return new Response(JSON.stringify({ ok: true, missions: [] }));
        let current: object = base;
        if (path === 'advance')
          current =
            ++advanced === 1
              ? { ...base, status: 'waiting_client', pending: action, revision: 3 }
              : { ...base, status: 'completed', revision: 6 };
        if (path === 'client-start')
          current = {
            ...base,
            status: 'waiting_client',
            pending: { ...action, started: true },
            revision: 4,
          };
        if (path === 'receipt') current = { ...base, revision: 5 };
        return new Response(JSON.stringify({ ok: true, mission: current }));
      }),
    );
    vi.mocked(executeClientVerb).mockResolvedValue({ ok: true, action: 'toggle_layer' });
    const { result } = renderHook(() => useMissionWorkspace(bindings, snapshot));
    await act(async () => {
      await result.current.run('mission');
    });
    expect(calls).toEqual(['control', 'advance', 'client-start', 'receipt', 'advance', 'missions']);
    expect(result.current.mission?.status).toBe('completed');
    expect(executeClientVerb).toHaveBeenCalledOnce();
  });

  it('creates and runs a mission from an explicit voice/text request using the current model', async () => {
    sessionStorage.setItem('shadowbroker-mission-dashboard', 'dashboard-saved');
    let creation: Record<string, unknown> = {};
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const path = String(input);
        if (path.endsWith('/missions/config'))
          return new Response(
            JSON.stringify({ ok: true, provider: 'compat', model: 'current-model' }),
          );
        if (path.endsWith('/missions') && init?.method === 'POST') {
          creation = JSON.parse(String(init.body));
          return new Response(JSON.stringify({ ok: true, mission: { ...base, status: 'paused' } }));
        }
        if (path.endsWith('/missions'))
          return new Response(JSON.stringify({ ok: true, missions: [] }));
        return new Response(
          JSON.stringify({
            ok: true,
            mission: { ...base, status: path.endsWith('/advance') ? 'completed' : 'running' },
          }),
        );
      }),
    );
    const { result } = renderHook(() => useMissionWorkspace(bindings, snapshot));
    await act(async () => {
      await result.current.startFromText('Investigate this harbor', new AbortController().signal);
    });
    expect(creation.objective).toBe('Investigate this harbor');
    expect(creation.roles).toEqual(
      ['researcher', 'analyst', 'reviewer'].map((role) => ({
        role,
        provider: 'compat',
        model: 'current-model',
        max_calls: 5,
      })),
    );
    expect(result.current.open).toBe(true);
    expect(result.current.mission?.status).toBe('completed');
  });

  it('pauses an active fetch and never executes a later browser action', async () => {
    sessionStorage.setItem('shadowbroker-mission-dashboard', 'dashboard-saved');
    let entered = false;
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const path = String(input);
        if (path.endsWith('/advance')) {
          entered = true;
          return await new Promise<Response>((_resolve, reject) =>
            init?.signal?.addEventListener('abort', () =>
              reject(new DOMException('Aborted', 'AbortError')),
            ),
          );
        }
        if (path.endsWith('/missions'))
          return new Response(JSON.stringify({ ok: true, missions: [] }));
        const operation = JSON.parse(String(init?.body)).action;
        return new Response(
          JSON.stringify({
            ok: true,
            mission: { ...base, status: operation === 'pause' ? 'paused' : 'running' },
          }),
        );
      }),
    );
    const { result } = renderHook(() => useMissionWorkspace(bindings, snapshot));
    let running!: Promise<void>;
    act(() => {
      running = result.current.run('mission');
    });
    await waitFor(() => expect(entered).toBe(true));
    await act(async () => {
      await result.current.control('pause');
      await running;
    });
    expect(result.current.mission?.status).toBe('paused');
    expect(executeClientVerb).not.toHaveBeenCalled();
  });
});
