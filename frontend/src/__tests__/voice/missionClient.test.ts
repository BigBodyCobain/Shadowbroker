import { afterEach, describe, expect, it, vi } from 'vitest';
import { executeMissionAction, type Mission } from '@/lib/missionClient';
import { executeClientVerb, type ClientToolContext } from '@/lib/clientTools';
import type { GroundingSnapshot } from '@/lib/voiceGroundingTypes';

vi.mock('@/lib/clientTools', () => ({ executeClientVerb: vi.fn() }));
afterEach(() => {
  vi.unstubAllGlobals();
  vi.resetAllMocks();
});
const bindings = () => ({}) as ClientToolContext;
const mission = (overrides: Partial<Mission> = {}): Mission =>
  ({
    id: 'mission-test',
    owner: 'dashboard-test',
    status: 'waiting_client',
    pending: {
      id: 'action-test',
      kind: 'client',
      owner: 'dashboard-test',
      tool: 'open_article',
      args: { query: 'harbor' },
      started: false,
    },
    ...overrides,
  }) as Mission;
const view = (selection: GroundingSnapshot['selection']) =>
  ({ schema: 'sb.grounding.v1', selection }) as GroundingSnapshot;

describe('mission action receipts', () => {
  it('records start before executing, verifies selection, then sends the result', async () => {
    const calls: string[] = [];
    const initial = mission();
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const path = String(input);
        calls.push(path.includes('client-start') ? 'start' : 'receipt');
        if (path.includes('receipt')) {
          expect(JSON.parse(String(init?.body))).toMatchObject({
            action_id: 'action-test',
            result: { ok: true, action: 'open_article' },
            snapshot: { selection: { id: 'harbor', type: 'news' } },
          });
          return new Response(
            JSON.stringify({ ok: true, mission: { ...initial, status: 'running', pending: null } }),
          );
        }
        return new Response(
          JSON.stringify({
            ok: true,
            mission: { ...initial, pending: { ...initial.pending, started: true } },
          }),
        );
      }),
    );
    vi.mocked(executeClientVerb).mockImplementation(async () => {
      calls.push('execute');
      return { ok: true, action: 'open_article', article: { id: 'harbor' } };
    });
    const result = await executeMissionAction(
      initial,
      'dashboard-test',
      bindings,
      async () => view({ id: 'harbor', type: 'news' }),
      new AbortController().signal,
    );
    expect(calls).toEqual(['start', 'execute', 'receipt']);
    expect(result.status).toBe('running');
  });

  it('reports failed selection instead of believing an optimistic tool response', async () => {
    const initial = mission();
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        if (String(input).includes('receipt')) {
          expect(JSON.parse(String(init?.body)).result).toMatchObject({
            ok: false,
            error: 'Requested selection was not confirmed by the dashboard',
          });
        }
        return new Response(JSON.stringify({ ok: true, mission: initial }));
      }),
    );
    vi.mocked(executeClientVerb).mockResolvedValue({
      ok: true,
      action: 'open_article',
      article: { id: 'expected' },
    });
    await executeMissionAction(
      initial,
      'dashboard-test',
      bindings,
      async () => view({ id: 'different', type: 'news' }),
      new AbortController().signal,
    );
  });

  it('verifies long article IDs against the full binding instead of a truncated snapshot prefix', async () => {
    const initial = mission();
    const id = 'A'.repeat(90) + '|0,0';
    const selected = () =>
      ({ selectedEntity: { id, type: 'news' } }) as ClientToolContext & {
        selectedEntity: { id: string; type: string };
      };
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        if (String(input).includes('receipt'))
          expect(JSON.parse(String(init?.body)).result.ok).toBe(true);
        return new Response(JSON.stringify({ ok: true, mission: initial }));
      }),
    );
    vi.mocked(executeClientVerb).mockResolvedValue({
      ok: true,
      action: 'open_article',
      article: { id },
    });
    await executeMissionAction(
      initial,
      'dashboard-test',
      selected,
      async () => view({ id: id.slice(0, 64), type: 'news' }),
      new AbortController().signal,
    );
  });

  it('does not execute an action already started before a reload', async () => {
    const initial = mission();
    const fetch = vi.fn();
    vi.stubGlobal('fetch', fetch);
    await expect(
      executeMissionAction(
        mission({ pending: { ...initial.pending!, started: true } }),
        'dashboard-test',
        bindings,
        async () => view(null),
        new AbortController().signal,
      ),
    ).rejects.toThrow('Unconfirmed');
    expect(executeClientVerb).not.toHaveBeenCalled();
    expect(fetch).not.toHaveBeenCalled();
  });

  it('does not execute actions for another dashboard', async () => {
    await expect(
      executeMissionAction(
        mission(),
        'someone-else',
        bindings,
        async () => view(null),
        new AbortController().signal,
      ),
    ).rejects.toThrow('Unconfirmed');
    expect(executeClientVerb).not.toHaveBeenCalled();
  });

  it('cancels before the browser mutation if cancellation arrives after start', async () => {
    const controller = new AbortController();
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        controller.abort();
        return new Response(JSON.stringify({ ok: true, mission: mission() }));
      }),
    );
    await expect(
      executeMissionAction(
        mission(),
        'dashboard-test',
        bindings,
        async () => view(null),
        controller.signal,
      ),
    ).rejects.toThrow();
    expect(executeClientVerb).not.toHaveBeenCalled();
  });

  it('still records an already executed action when cancellation arrives afterwards', async () => {
    const controller = new AbortController();
    let receipt = false;
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        if (String(input).includes('receipt')) {
          receipt = true;
          expect(init?.signal).toBeUndefined();
        }
        return new Response(JSON.stringify({ ok: true, mission: mission() }));
      }),
    );
    vi.mocked(executeClientVerb).mockImplementation(async () => {
      controller.abort();
      return { ok: false, action: 'open_article', error: 'Article missing' };
    });
    await executeMissionAction(
      mission(),
      'dashboard-test',
      bindings,
      async () => view(null),
      controller.signal,
    );
    expect(receipt).toBe(true);
  });
});
