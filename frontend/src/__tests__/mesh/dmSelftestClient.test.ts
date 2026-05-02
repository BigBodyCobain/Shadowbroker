import { beforeEach, describe, expect, it, vi } from 'vitest';

const controlPlaneJson = vi.fn();

vi.mock('@/lib/controlPlane', () => ({
  controlPlaneJson,
}));

describe('DM selftest client', () => {
  beforeEach(() => {
    controlPlaneJson.mockReset();
  });

  it('runs the local DM selftest without requiring an admin browser session', async () => {
    controlPlaneJson.mockResolvedValue({ ok: true });

    const { runWormholeDmSelftest } = await import('@/mesh/wormholeIdentityClient');

    await runWormholeDmSelftest('probe');

    expect(controlPlaneJson).toHaveBeenCalledWith(
      '/api/wormhole/dm/selftest',
      expect.objectContaining({
        method: 'POST',
        requireAdminSession: false,
        body: JSON.stringify({ message: 'probe' }),
      }),
    );
  });
});
