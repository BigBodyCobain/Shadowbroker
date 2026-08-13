import { afterEach, describe, expect, it, vi } from 'vitest';

import * as api from '@/lib/investigationsApi';
import { ApiError } from '@/lib/investigationsApi';

afterEach(() => {
  vi.restoreAllMocks();
});

function mockFetch(status: number, body: unknown) {
  return vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    statusText: 'x',
    json: async () => body,
  } as unknown as Response);
}

describe('investigationsApi', () => {
  it('lists investigations', async () => {
    global.fetch = mockFetch(200, { investigations: [{ id: 'inv_1', title: 'C' }], count: 1 }) as typeof fetch;
    const res = await api.listInvestigations();
    expect(res.count).toBe(1);
    expect(res.investigations[0].id).toBe('inv_1');
  });

  it('creates an investigation with a JSON body', async () => {
    const f = mockFetch(201, { id: 'inv_2', title: 'New' });
    global.fetch = f as typeof fetch;
    const inv = await api.createInvestigation({ title: 'New' });
    expect(inv.id).toBe('inv_2');
    const [, init] = f.mock.calls[0];
    expect((init as RequestInit).method).toBe('POST');
    expect(JSON.parse((init as RequestInit).body as string).title).toBe('New');
  });

  it('throws ApiError with the backend detail on failure', async () => {
    global.fetch = mockFetch(404, { detail: 'not found: inv_x' }) as typeof fetch;
    await expect(api.getInvestigation('inv_x')).rejects.toMatchObject({
      name: 'ApiError',
      status: 404,
      message: 'not found: inv_x',
    });
  });

  it('wraps network failures as ApiError status 0', async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error('boom')) as unknown as typeof fetch;
    const err = await api.listInvestigations().catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(0);
  });

  it('encodes ids in the path', async () => {
    const f = mockFetch(200, { timeline: [] });
    global.fetch = f as typeof fetch;
    await api.getTimeline('inv/../evil');
    expect(f.mock.calls[0][0]).toContain('inv%2F..%2Fevil');
  });
});
