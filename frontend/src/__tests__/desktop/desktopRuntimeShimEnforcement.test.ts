import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { createHttpBackedDesktopRuntime } from '@/lib/desktopRuntimeShim';

describe('desktopRuntimeShim enforcement guard', () => {
  const fetchMock = vi.fn();
  const warnMock = vi.spyOn(console, 'warn').mockImplementation(() => {});

  beforeEach(() => {
    fetchMock.mockReset();
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('refuses strictly enforced commands in the HTTP-backed shim', async () => {
    const runtime = createHttpBackedDesktopRuntime();

    await expect(
      runtime.invokeLocalControl?.(
        'wormhole.gate.key.rotate',
        { gate_id: 'infonet', reason: 'operator_reset' },
        {
          capability: 'wormhole_gate_key',
          sessionProfileHint: 'gate_operator',
          enforceProfileHint: true,
        },
      ),
    ).rejects.toThrow('desktop_runtime_shim_enforcement_inactive');

    expect(fetchMock).not.toHaveBeenCalled();
    expect(warnMock).toHaveBeenCalledWith(
      '[desktop-shim] strict native session-profile enforcement is unavailable in the HTTP-backed shim',
      expect.objectContaining({
        command: 'wormhole.gate.key.rotate',
        sessionProfileHint: 'gate_operator',
      }),
    );
    expect(runtime.getNativeControlAuditReport?.(5)).toEqual(
      expect.objectContaining({
        totalEvents: 1,
        totalRecorded: 1,
        byOutcome: expect.objectContaining({ shim_refused: 1 }),
        lastDenied: expect.objectContaining({
          command: 'wormhole.gate.key.rotate',
          targetRef: 'infonet',
          outcome: 'shim_refused',
        }),
      }),
    );
  });
});
