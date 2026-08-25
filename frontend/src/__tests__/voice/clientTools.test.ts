/**
 * §7.D item 29 — clientTools executor discipline: toggle_layer reports
 * actual-not-requested state on simulated reducer refusal; clamps truncate
 * 300-char queries and >24-item arrays; superseded turns return cancelled.
 */
import { describe, expect, it, vi, afterEach } from 'vitest';

import {
  executeClientVerb,
  CLIENT_TOOL_DESCRIPTORS,
  type ClientToolContext,
} from '@/lib/clientTools';
import { onRequest } from '@/lib/mapControlBus';

function makeCtx(overrides: Partial<ClientToolContext> = {}): ClientToolContext & Record<string, ReturnType<typeof vi.fn>> {
  return {
    flyTo: vi.fn(),
    toggleLayer: vi.fn(() => true),
    applyMapStyle: vi.fn((style: 'DEFAULT' | 'SATELLITE') => style),
    setFilter: vi.fn(),
    setSelectedEntity: vi.fn(),
    viewSummary: vi.fn(() => ({ activeLayers: { flights: false, ships_military: true }, filters: {} })),
    ...overrides,
  } as ClientToolContext & Record<string, ReturnType<typeof vi.fn>>;
}

describe('clientTools executors', () => {
  it('descriptor block carries exactly the 16 fixture verbs', () => {
    expect(CLIENT_TOOL_DESCRIPTORS).toHaveLength(16);
    expect(CLIENT_TOOL_DESCRIPTORS.map((d) => d.name)).toContain('map_fly_to');
  });

  it('toggle_layer reports actual-not-requested state on refusal', async () => {
    const ctx = makeCtx({ toggleLayer: vi.fn(() => null) });
    const result = await executeClientVerb(
      'toggle_layer',
      { layer: 'flights', enabled: true },
      ctx,
    );
    // Simulated reducer refusal → honest failure, never a claimed success.
    expect(result.ok).toBe(false);
    expect(result.error).toBe('layer toggle was not applied');
  });

  it('toggle_layer rejects unknown layer ids without touching state', async () => {
    const ctx = makeCtx();
    const result = await executeClientVerb(
      'toggle_layer',
      { layer: '__not_a_layer__', enabled: true },
      ctx,
    );
    expect(result.ok).toBe(false);
    expect(result.error).toBe('unknown layer id');
    expect(ctx.toggleLayer).not.toHaveBeenCalled();
  });

  it('clamps a 300-character select_entity query to the string cap', async () => {
    const ctx = makeCtx();
    await executeClientVerb('select_entity', { query: 'x'.repeat(300) }, ctx);
    expect(ctx.setSelectedEntity).not.toHaveBeenCalled(); // no fabricated match
  });

  it('clamps set_filter values arrays to 24 items', async () => {
    const ctx = makeCtx();
    const values = Array.from({ length: 40 }, (_, i) => `v${i}`);
    const result = await executeClientVerb('set_filter', { filter_key: 'type', values }, ctx);
    expect(result.ok).toBe(true);
    expect(ctx.setFilter).toHaveBeenCalledWith('type', values.slice(0, 24));
  });

  it('superseded late finishers return cancelled:true', async () => {
    let resolveFirst: ((r: { ok: boolean; action: string }) => void) | null = null;
    const unsub = onRequest((cmd) => {
      if (cmd.type === 'easeTo' && !resolveFirst) {
        return new Promise((resolve) => {
          resolveFirst = resolve;
        });
      }
      return { ok: true, action: cmd.type };
    });
    try {
      // First turn hangs in flight (turnId assigned synchronously at call).
      const first = executeClientVerb('map_ease_to', { lat: 1, lng: 1 }, makeCtx());
      // A later turn supersedes it for this verb before it finishes.
      const second = await executeClientVerb('map_ease_to', { lat: 2, lng: 2 }, makeCtx());
      expect(second.ok).toBe(true);
      resolveFirst!({ ok: true, action: 'map_ease_to' });
      const late = await first;
      expect(late.cancelled).toBe(true);
      expect(late.ok).toBe(false);
    } finally {
      unsub();
    }
  });

  it('map_fly_to clamps coordinates into range and reports evidence', async () => {
    const ctx = makeCtx();
    const result = await executeClientVerb(
      'map_fly_to',
      { lat: 999, lng: -9999, zoom: 55 },
      ctx,
    );
    expect(result.ok).toBe(true);
    expect(result.center).toEqual({ lat: 90, lng: -180 });
    expect(result.zoom).toBe(20);
    expect(ctx.flyTo).toHaveBeenCalledWith({ lat: 90, lng: -180, zoom: 20 });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });
});
