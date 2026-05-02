import { beforeEach, describe, expect, it, vi } from 'vitest';

const controlPlaneFetch = vi.fn();

vi.mock('@/lib/controlPlane', () => ({
  controlPlaneFetch,
}));

describe('gateSessionStream manager', () => {
  beforeEach(() => {
    vi.resetModules();
    controlPlaneFetch.mockReset();
  });

  it('marks the stream disabled when the backend feature flag is off', async () => {
    controlPlaneFetch.mockResolvedValue(
      new Response(JSON.stringify({ ok: false, detail: 'gate_session_stream_disabled' }), {
        status: 404,
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    const mod = await import('@/mesh/gateSessionStream');

    mod.connectGateSessionStream();
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(mod.getGateSessionStreamStatus()).toMatchObject({
      enabled: false,
      phase: 'disabled',
      detail: 'gate_session_stream_disabled',
    });
  });

  it('parses hello and heartbeat events from the session stream skeleton', async () => {
    const encoder = new TextEncoder();
    controlPlaneFetch.mockResolvedValue(
      new Response(
        new ReadableStream({
          start(controller) {
            controller.enqueue(
              encoder.encode(
                [
                  'event: hello',
                  'data: {"session_id":"sess-1","subscriptions":["alpha","beta"],"heartbeat_s":20,"batch_ms":1500,"transport":"sse","gate_access":{"alpha":{"node_id":"!node_alpha","proof":"proof-alpha","ts":"1712360000"}},"gate_key_status":{"alpha":{"ok":true,"gate_id":"alpha","current_epoch":7,"has_local_access":true}}}',
                  '',
                  'event: heartbeat',
                  'data: {"session_id":"sess-1","ts":1712360000}',
                  '',
                ].join('\n'),
              ),
            );
            controller.close();
          },
        }),
        {
          status: 200,
          headers: { 'Content-Type': 'text/event-stream' },
        },
      ),
    );

    const mod = await import('@/mesh/gateSessionStream');

    mod.setGateSessionStreamSubscriptions(['Alpha', 'beta']);
    mod.connectGateSessionStream();
    await new Promise((resolve) => setTimeout(resolve, 0));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(controlPlaneFetch).toHaveBeenCalledWith(
      '/api/mesh/infonet/session-stream?gates=alpha%2Cbeta',
      expect.objectContaining({
        requireAdminSession: true,
        cache: 'no-store',
        headers: { Accept: 'text/event-stream' },
      }),
    );
    expect(mod.getGateSessionStreamStatus()).toMatchObject({
      enabled: false,
      phase: 'closed',
      sessionId: 'sess-1',
      subscriptions: ['alpha', 'beta'],
      heartbeatS: 20,
      batchMs: 1500,
      lastEventType: 'heartbeat',
    });
    expect(mod.getGateSessionStreamAccessHeaders('alpha')).toEqual({
      'X-Wormhole-Node-Id': '!node_alpha',
      'X-Wormhole-Gate-Proof': 'proof-alpha',
      'X-Wormhole-Gate-Ts': '1712360000',
    });
    expect(mod.getGateSessionStreamKeyStatus('alpha')).toEqual({
      ok: true,
      gate_id: 'alpha',
      current_epoch: 7,
      has_local_access: true,
    });
  });

  it('retains one shared subscription set across multiple same-gate consumers', async () => {
    controlPlaneFetch.mockResolvedValue(
      new Response(JSON.stringify({ ok: false, detail: 'gate_session_stream_disabled' }), {
        status: 404,
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    const mod = await import('@/mesh/gateSessionStream');

    const releaseA = mod.retainGateSessionStreamGate('Alpha');
    const releaseB = mod.retainGateSessionStreamGate('alpha');
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(controlPlaneFetch).toHaveBeenCalledTimes(1);
    expect(mod.getGateSessionStreamStatus().subscriptions).toEqual(['alpha']);

    releaseA();
    expect(mod.getGateSessionStreamStatus().subscriptions).toEqual(['alpha']);

    releaseB();
    expect(mod.getGateSessionStreamStatus()).toMatchObject({
      phase: 'idle',
      subscriptions: [],
    });
  });

  it('can invalidate cached per-gate stream bootstrap context without dropping the stream status', async () => {
    const encoder = new TextEncoder();
    controlPlaneFetch.mockResolvedValue(
      new Response(
        new ReadableStream({
          start(controller) {
            controller.enqueue(
              encoder.encode(
                [
                  'event: hello',
                  'data: {"session_id":"sess-ctx","subscriptions":["alpha"],"heartbeat_s":20,"batch_ms":1500,"transport":"sse","gate_access":{"alpha":{"node_id":"!node_alpha","proof":"proof-alpha","ts":"1712360000"}},"gate_key_status":{"alpha":{"ok":true,"gate_id":"alpha","current_epoch":7,"has_local_access":true}}}',
                  '',
                ].join('\n'),
              ),
            );
            controller.close();
          },
        }),
        {
          status: 200,
          headers: { 'Content-Type': 'text/event-stream' },
        },
      ),
    );

    const mod = await import('@/mesh/gateSessionStream');

    mod.retainGateSessionStreamGate('alpha');
    await new Promise((resolve) => setTimeout(resolve, 0));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(mod.getGateSessionStreamAccessHeaders('alpha')).toBeDefined();
    expect(mod.getGateSessionStreamKeyStatus('alpha')).toBeTruthy();

    mod.invalidateGateSessionStreamGateContext('alpha');

    expect(mod.getGateSessionStreamAccessHeaders('alpha')).toBeUndefined();
    expect(mod.getGateSessionStreamKeyStatus('alpha')).toBeNull();
    expect(mod.getGateSessionStreamStatus().sessionId).toBe('sess-ctx');
  });

  it('emits parsed gate_update events to stream event listeners', async () => {
    const encoder = new TextEncoder();
    controlPlaneFetch.mockResolvedValue(
      new Response(
        new ReadableStream({
          start(controller) {
            controller.enqueue(
              encoder.encode(
                [
                  'event: hello',
                  'data: {"session_id":"sess-2","subscriptions":["alpha"],"heartbeat_s":20,"batch_ms":1500,"transport":"sse"}',
                  '',
                  'event: gate_update',
                  'data: {"session_id":"sess-2","updates":[{"gate_id":"alpha","cursor":3}],"ts":1712360001}',
                  '',
                ].join('\n'),
              ),
            );
            controller.close();
          },
        }),
        {
          status: 200,
          headers: { 'Content-Type': 'text/event-stream' },
        },
      ),
    );

    const mod = await import('@/mesh/gateSessionStream');
    const events: Array<{ event: string; data: unknown }> = [];
    const unsubscribe = mod.subscribeGateSessionStreamEvents((event) => {
      events.push({ event: event.event, data: event.data });
    });

    mod.retainGateSessionStreamGate('alpha');
    await new Promise((resolve) => setTimeout(resolve, 0));
    await new Promise((resolve) => setTimeout(resolve, 0));

    unsubscribe();

    expect(events.some((event) => event.event === 'hello')).toBe(true);
    expect(events).toContainEqual({
      event: 'gate_update',
      data: {
        session_id: 'sess-2',
        updates: [{ gate_id: 'alpha', cursor: 3 }],
        ts: 1712360001,
      },
    });
  });

  it('reconnects with retained subscriptions after the stream closes', async () => {
    vi.useFakeTimers();
    try {
      const encoder = new TextEncoder();
      let callCount = 0;
      controlPlaneFetch.mockImplementation(async () => {
        callCount += 1;
        if (callCount === 1) {
          return new Response(
            new ReadableStream({
              start(controller) {
                controller.enqueue(
                  encoder.encode(
                    [
                      'event: hello',
                      'data: {"session_id":"sess-3","subscriptions":["alpha"],"heartbeat_s":20,"batch_ms":1500,"transport":"sse"}',
                      '',
                    ].join('\n'),
                  ),
                );
                controller.close();
              },
            }),
            {
              status: 200,
              headers: { 'Content-Type': 'text/event-stream' },
            },
          );
        }
        return new Response(
          new ReadableStream({
            start(controller) {
              controller.enqueue(
                encoder.encode(
                  [
                    'event: hello',
                    'data: {"session_id":"sess-4","subscriptions":["alpha"],"heartbeat_s":20,"batch_ms":1500,"transport":"sse"}',
                    '',
                  ].join('\n'),
                ),
              );
            },
          }),
          {
            status: 200,
            headers: { 'Content-Type': 'text/event-stream' },
          },
        );
      });

      const mod = await import('@/mesh/gateSessionStream');
      const release = mod.retainGateSessionStreamGate('alpha');

      await Promise.resolve();
      await Promise.resolve();

      await vi.advanceTimersByTimeAsync(1_000);
      await Promise.resolve();
      await Promise.resolve();

      expect(controlPlaneFetch).toHaveBeenCalledTimes(2);
      expect(mod.getGateSessionStreamStatus()).toMatchObject({
        enabled: true,
        subscriptions: ['alpha'],
      });
      expect(['connecting', 'open']).toContain(mod.getGateSessionStreamStatus().phase);

      release();
      mod.disconnectGateSessionStream();
    } finally {
      vi.useRealTimers();
    }
  });
});
