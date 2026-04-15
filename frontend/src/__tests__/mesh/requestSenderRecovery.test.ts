import {
  getSenderRecoveryState,
  REQUEST_V2_REDUCED_VERSION,
  recoverSenderSealWithFallback,
  requiresSenderRecovery,
  shouldAllowRequestActions,
  shouldKeepUnresolvedRequestVisible,
  shouldPromoteRecoveredSenderForBootstrap,
  shouldPromoteRecoveredSenderForKnownContact,
} from '@/mesh/requestSenderRecovery';

describe('requestSenderRecovery', () => {
  it('only promotes a known-contact sender when the seal verified and the sender matches', () => {
    expect(
      shouldPromoteRecoveredSenderForKnownContact(
        { sender_id: 'alice', seal_verified: true },
        'alice',
      ),
    ).toBe(true);
    expect(
      shouldPromoteRecoveredSenderForKnownContact(
        { sender_id: 'alice', seal_verified: false },
        'alice',
      ),
    ).toBe(false);
    expect(
      shouldPromoteRecoveredSenderForKnownContact(
        { sender_id: 'mallory', seal_verified: true },
        'alice',
      ),
    ).toBe(false);
  });

  it('only promotes a bootstrap-recovered sender when the seal verified', () => {
    expect(
      shouldPromoteRecoveredSenderForBootstrap({
        sender_id: 'alice',
        seal_verified: true,
      }),
    ).toBe(true);
    expect(
      shouldPromoteRecoveredSenderForBootstrap({
        sender_id: 'alice',
        seal_verified: false,
      }),
    ).toBe(false);
    expect(shouldPromoteRecoveredSenderForBootstrap(null)).toBe(false);
  });

  it('prefers explicit request-v2 recovery markers over sealed-string inference', () => {
    expect(
      requiresSenderRecovery({
        sender_id: 'opaque',
        sender_seal: 'v3:test',
        request_contract_version: REQUEST_V2_REDUCED_VERSION,
        sender_recovery_required: true,
      }),
    ).toBe(true);
    expect(
      getSenderRecoveryState({
        sender_id: 'opaque',
        sender_seal: 'v3:test',
        request_contract_version: REQUEST_V2_REDUCED_VERSION,
        sender_recovery_required: true,
      }),
    ).toBe('pending');
    expect(
      requiresSenderRecovery({
        sender_id: 'sealed:abcd',
        sender_seal: 'v2:test',
      }),
    ).toBe(true);
  });

  it('only allows request actions once canonical recovery reaches verified', () => {
    expect(
      shouldAllowRequestActions({
        request_contract_version: REQUEST_V2_REDUCED_VERSION,
        sender_recovery_required: true,
        sender_recovery_state: 'verified',
      }),
    ).toBe(true);
    expect(
      shouldAllowRequestActions({
        request_contract_version: REQUEST_V2_REDUCED_VERSION,
        sender_recovery_required: true,
        sender_recovery_state: 'pending',
      }),
    ).toBe(false);
    expect(
      shouldAllowRequestActions({
        request_contract_version: REQUEST_V2_REDUCED_VERSION,
        sender_recovery_required: true,
        sender_recovery_state: 'failed',
      }),
    ).toBe(false);
    expect(
      shouldAllowRequestActions({
        request_contract_version: undefined,
        sender_recovery_required: undefined,
        sender_recovery_state: undefined,
      }),
    ).toBe(true);
  });

  it('keeps only pending or failed canonical request-v2 mail visible in the unresolved inbox flow', () => {
    expect(
      shouldKeepUnresolvedRequestVisible({
        delivery_class: 'request',
        request_contract_version: REQUEST_V2_REDUCED_VERSION,
        sender_recovery_required: true,
        sender_recovery_state: 'pending',
      }),
    ).toBe(true);
    expect(
      shouldKeepUnresolvedRequestVisible({
        delivery_class: 'request',
        request_contract_version: REQUEST_V2_REDUCED_VERSION,
        sender_recovery_required: true,
        sender_recovery_state: 'failed',
      }),
    ).toBe(true);
    expect(
      shouldKeepUnresolvedRequestVisible({
        delivery_class: 'request',
        request_contract_version: REQUEST_V2_REDUCED_VERSION,
        sender_recovery_required: true,
        sender_recovery_state: 'verified',
      }),
    ).toBe(false);
    expect(
      shouldKeepUnresolvedRequestVisible({
        delivery_class: 'request',
        request_contract_version: undefined,
        sender_recovery_required: undefined,
        sender_recovery_state: 'pending',
      }),
    ).toBe(false);
    expect(
      shouldKeepUnresolvedRequestVisible({
        delivery_class: 'shared',
        request_contract_version: REQUEST_V2_REDUCED_VERSION,
        sender_recovery_required: true,
        sender_recovery_state: 'pending',
      }),
    ).toBe(false);
  });

  it('prefers local recovery and only falls back to the helper on local failure', async () => {
    const openLocal = vi.fn().mockResolvedValue({
      sender_id: 'alice',
      seal_verified: true,
    });
    const openHelper = vi.fn().mockResolvedValue({
      sender_id: 'helper-alice',
      seal_verified: true,
    });

    await expect(
      recoverSenderSealWithFallback({
        wormholeReady: true,
        openLocal,
        openHelper,
      }),
    ).resolves.toEqual({ sender_id: 'alice', seal_verified: true });

    expect(openLocal).toHaveBeenCalledTimes(1);
    expect(openHelper).not.toHaveBeenCalled();
  });

  it('uses the helper only as fallback when local recovery cannot open the seal', async () => {
    const openLocal = vi.fn().mockResolvedValue(null);
    const openHelper = vi.fn().mockResolvedValue({
      sender_id: 'alice',
      seal_verified: true,
    });

    await expect(
      recoverSenderSealWithFallback({
        wormholeReady: true,
        openLocal,
        openHelper,
      }),
    ).resolves.toEqual({ sender_id: 'alice', seal_verified: true });

    expect(openLocal).toHaveBeenCalledTimes(1);
    expect(openHelper).toHaveBeenCalledTimes(1);
  });

  it('does not invoke the helper when Wormhole fallback is unavailable', async () => {
    const openLocal = vi.fn().mockResolvedValue(null);
    const openHelper = vi.fn().mockResolvedValue({
      sender_id: 'alice',
      seal_verified: true,
    });

    await expect(
      recoverSenderSealWithFallback({
        wormholeReady: false,
        openLocal,
        openHelper,
      }),
    ).resolves.toBeNull();

    expect(openLocal).toHaveBeenCalledTimes(1);
    expect(openHelper).not.toHaveBeenCalled();
  });

  it('treats helper failure as unresolved instead of promoting helper authority', async () => {
    const openLocal = vi.fn().mockResolvedValue(null);
    const openHelper = vi.fn().mockRejectedValue(new Error('helper_failed'));

    await expect(
      recoverSenderSealWithFallback({
        wormholeReady: true,
        openLocal,
        openHelper,
      }),
    ).resolves.toBeNull();

    expect(openLocal).toHaveBeenCalledTimes(1);
    expect(openHelper).toHaveBeenCalledTimes(1);
  });
});
