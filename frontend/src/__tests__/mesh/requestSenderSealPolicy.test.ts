import {
  ensureCanonicalRequestV2SenderSeal,
  REQUEST_V2_SENDER_SEAL_VERSION_ERROR,
  requiresCanonicalRequestV2SenderSeal,
} from '@/mesh/requestSenderSealPolicy';

describe('requestSenderSealPolicy', () => {
  it('requires canonical v3 seals only for request-class sealed sender', () => {
    expect(
      requiresCanonicalRequestV2SenderSeal({
        deliveryClass: 'request',
        useSealedSender: true,
      }),
    ).toBe(true);
    expect(
      requiresCanonicalRequestV2SenderSeal({
        deliveryClass: 'request',
        useSealedSender: false,
      }),
    ).toBe(false);
    expect(
      requiresCanonicalRequestV2SenderSeal({
        deliveryClass: 'shared',
        useSealedSender: true,
      }),
    ).toBe(false);
  });

  it('accepts v3 seals and rejects non-v3 seals for canonical request-v2 sender sealing', () => {
    expect(ensureCanonicalRequestV2SenderSeal('v3:ephemeral:payload')).toBe(
      'v3:ephemeral:payload',
    );
    expect(() => ensureCanonicalRequestV2SenderSeal('v2:legacy-payload')).toThrow(
      REQUEST_V2_SENDER_SEAL_VERSION_ERROR,
    );
    expect(() => ensureCanonicalRequestV2SenderSeal('')).toThrow(
      REQUEST_V2_SENDER_SEAL_VERSION_ERROR,
    );
  });
});
