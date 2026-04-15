import { describe, expect, it } from 'vitest';

import {
  buildDmTrustHint,
  buildPrivateLaneHint,
  dmTrustPrimaryActionLabel,
  isFirstContactTrustOnly,
  shortTrustFingerprint,
  shouldAutoRevealSasForTrust,
} from '@/mesh/meshPrivacyHints';

describe('meshPrivacyHints', () => {
  it('flags recent private-lane fallback as a danger hint', () => {
    const hint = buildPrivateLaneHint({
      activeTab: 'dms',
      recentPrivateFallback: true,
      recentPrivateFallbackReason: 'Tor transport failed and clearnet relay was used.',
      dmTransportMode: 'relay',
    });

    expect(hint).toEqual(
      expect.objectContaining({
        severity: 'danger',
        title: 'RECENT PRIVACY DOWNGRADE',
      }),
    );
    expect(hint?.detail).toContain('clearnet relay');
  });

  it('flags remote prekey mismatch as a danger trust hint', () => {
    const hint = buildDmTrustHint({
      remotePrekeyMismatch: true,
    });

    expect(hint).toEqual(
      expect.objectContaining({
        severity: 'danger',
        title: 'REMOTE PREKEY CHANGED',
      }),
    );
  });

  it('flags first-seen pinned contacts as TOFU until verified', () => {
    const contact = {
      remotePrekeyFingerprint: 'abc123',
      remotePrekeyPinnedAt: 123,
      verify_registry: false,
      verify_inband: false,
      verified: false,
    };

    expect(isFirstContactTrustOnly(contact)).toBe(true);
    expect(buildDmTrustHint(contact)).toEqual(
      expect.objectContaining({
        severity: 'warn',
        title: 'FIRST CONTACT (TOFU ONLY)',
      }),
    );
    expect(buildDmTrustHint(contact)?.detail).toContain('not proof of sender identity');
    expect(dmTrustPrimaryActionLabel(contact)).toBe('VERIFY SAS NOW');
    expect(shouldAutoRevealSasForTrust(contact)).toBe(true);
  });

  it('auto-reveals SAS for trust hazards but keeps ordinary verified contacts quiet', () => {
    expect(
      shouldAutoRevealSasForTrust({
        remotePrekeyMismatch: true,
      }),
    ).toBe(true);
    expect(
      shouldAutoRevealSasForTrust({
        verify_mismatch: true,
      }),
    ).toBe(true);
    expect(
      shouldAutoRevealSasForTrust({
        verified: true,
        verify_inband: true,
        verify_registry: true,
      }),
    ).toBe(false);
    expect(
      dmTrustPrimaryActionLabel({
        verified: true,
        verify_inband: true,
        verify_registry: true,
      }),
    ).toBe('SHOW SAS');
  });

  it('shortens long trust fingerprints for display', () => {
    expect(shortTrustFingerprint('abcdef0123456789fedcba9876543210')).toBe('abcdef01..543210');
    expect(shortTrustFingerprint('abcd1234')).toBe('abcd1234');
    expect(shortTrustFingerprint('')).toBe('unknown');
  });
});
