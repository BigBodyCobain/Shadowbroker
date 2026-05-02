import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

describe('fetchDmPublicKey lookup posture', () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('does not use legacy agent-id lookup unless explicitly allowed', async () => {
    const mod = await import('@/mesh/meshDmClient');

    const result = await mod.fetchDmPublicKey('http://localhost:8000', '!sb_legacy');

    expect(result).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('uses invite lookup handles without enabling legacy agent-id lookup', async () => {
    fetchMock.mockResolvedValueOnce({
      json: async () => ({ ok: true, dh_pub_key: 'peer-dh', lookup_mode: 'invite_lookup_handle' }),
    });
    const mod = await import('@/mesh/meshDmClient');

    const result = await mod.fetchDmPublicKey(
      'http://localhost:8000',
      '!sb_peer',
      'invite-handle-123',
    );

    expect(result?.dh_pub_key).toBe('peer-dh');
    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8000/api/mesh/dm/pubkey?lookup_token=invite-handle-123',
    );
  });

  it('still supports explicit legacy agent-id lookup for migration-only paths', async () => {
    fetchMock.mockResolvedValueOnce({
      json: async () => ({ ok: true, dh_pub_key: 'peer-dh', lookup_mode: 'legacy_agent_id' }),
    });
    const mod = await import('@/mesh/meshDmClient');

    const result = await mod.fetchDmPublicKey('http://localhost:8000', '!sb_legacy', undefined, {
      allowLegacyAgentId: true,
    });

    expect(result?.dh_pub_key).toBe('peer-dh');
    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8000/api/mesh/dm/pubkey?agent_id=%21sb_legacy',
    );
  });
});
