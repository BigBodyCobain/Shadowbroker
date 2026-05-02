import { describe, expect, it } from 'vitest';

import {
  buildDmTrustHint,
  buildPrivateLaneHint,
  dmTrustPrimaryActionLabel,
  hasKnownFirstContactAnchor,
  hasVerifiedFirstContactAnchor,
  isInvitePinnedFirstContact,
  isFirstContactTrustOnly,
  requiresVerifiedFirstContact,
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

  it('treats invite-pinned first contact as stronger than TOFU', () => {
    const contact = {
      trustSummary: {
        state: 'invite_pinned',
        label: 'INVITE PINNED',
        severity: 'warn',
        detail: 'anchored by signed invite',
        verifiedFirstContact: true,
        recommendedAction: 'show_sas',
        legacyLookup: false,
        inviteAttested: true,
        rootAttested: true,
        rootWitnessed: true,
        rootDistributionState: 'quorum_witnessed',
        rootWitnessThreshold: 2,
        rootWitnessCount: 2,
        rootWitnessDomainCount: 1,
        rootWitnessProvenanceState: 'local_quorum',
        rootWitnessIndependentQuorumMet: false,
        rootMismatch: false,
        registryMismatch: false,
        transparencyConflict: false,
      },
    };

    expect(isInvitePinnedFirstContact(contact)).toBe(true);
    expect(isFirstContactTrustOnly(contact)).toBe(false);
    expect(buildDmTrustHint(contact)).toEqual(
      expect.objectContaining({
        severity: 'warn',
        title: 'ROOT LOCAL QUORUM',
      }),
    );
    expect(buildDmTrustHint(contact)?.detail).toContain('co-resident in one trust domain');
    expect(dmTrustPrimaryActionLabel(contact)).toBe('SHOW SAS');
    expect(shouldAutoRevealSasForTrust(contact)).toBe(false);
  });

  it('distinguishes independent quorum provenance from local quorum', () => {
    const contact = {
      trustSummary: {
        state: 'invite_pinned',
        label: 'INVITE PINNED',
        severity: 'warn',
        detail: 'anchored by signed invite on independent quorum root',
        verifiedFirstContact: true,
        recommendedAction: 'show_sas',
        legacyLookup: false,
        inviteAttested: true,
        rootAttested: true,
        rootWitnessed: true,
        rootDistributionState: 'quorum_witnessed',
        rootWitnessThreshold: 2,
        rootWitnessCount: 2,
        rootWitnessDomainCount: 2,
        rootWitnessProvenanceState: 'independent_quorum',
        rootWitnessIndependentQuorumMet: true,
        rootMismatch: false,
        registryMismatch: false,
        transparencyConflict: false,
      },
    };

    expect(buildDmTrustHint(contact)).toEqual(
      expect.objectContaining({
        severity: 'warn',
        title: 'ROOT INDEPENDENT QUORUM',
      }),
    );
    expect(buildDmTrustHint(contact)?.detail).toContain('independently quorum-witnessed');
  });

  it('requires verified first-contact anchors before secure bootstrap', () => {
    expect(requiresVerifiedFirstContact(undefined)).toBe(true);
    expect(hasKnownFirstContactAnchor(undefined)).toBe(false);
    expect(hasVerifiedFirstContactAnchor(undefined)).toBe(false);

    expect(
      requiresVerifiedFirstContact({
        trustSummary: {
          state: 'invite_pinned',
          label: 'INVITE PINNED',
          severity: 'warn',
          detail: 'anchored by signed invite',
          verifiedFirstContact: true,
          recommendedAction: 'show_sas',
          legacyLookup: false,
          inviteAttested: true,
          rootWitnessed: true,
          rootDistributionState: 'quorum_witnessed',
          registryMismatch: false,
          transparencyConflict: false,
        },
      }),
    ).toBe(false);
    expect(
      hasVerifiedFirstContactAnchor({
        trustSummary: {
          state: 'invite_pinned',
          label: 'INVITE PINNED',
          severity: 'warn',
          detail: 'anchored by signed invite',
          verifiedFirstContact: true,
          recommendedAction: 'show_sas',
          legacyLookup: false,
          inviteAttested: true,
          rootWitnessed: true,
          rootDistributionState: 'quorum_witnessed',
          registryMismatch: false,
          transparencyConflict: false,
        },
      }),
    ).toBe(true);

    expect(
      requiresVerifiedFirstContact({
        remotePrekeyFingerprint: 'abc123',
        remotePrekeyPinnedAt: 123,
      }),
    ).toBe(true);
    expect(
      hasVerifiedFirstContactAnchor({
        remotePrekeyFingerprint: 'abc123',
        remotePrekeyPinnedAt: 123,
      }),
    ).toBe(false);

    expect(
      requiresVerifiedFirstContact({
        verified: true,
        verify_inband: true,
        verify_registry: true,
      }),
    ).toBe(true);
    expect(
      hasVerifiedFirstContactAnchor({
        verified: true,
        verify_inband: true,
        verify_registry: true,
      }),
    ).toBe(false);
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
        trustSummary: {
          state: 'sas_verified',
          label: 'SAS VERIFIED',
          severity: 'good',
          detail: 'sas verified',
          verifiedFirstContact: true,
          recommendedAction: 'show_sas',
          legacyLookup: false,
          inviteAttested: false,
          rootDistributionState: 'none',
          registryMismatch: false,
          transparencyConflict: false,
        },
      }),
    ).toBe(false);
    expect(
      dmTrustPrimaryActionLabel({
        trustSummary: {
          state: 'sas_verified',
          label: 'SAS VERIFIED',
          severity: 'good',
          detail: 'sas verified',
          verifiedFirstContact: true,
          recommendedAction: 'show_sas',
          legacyLookup: false,
          inviteAttested: false,
          rootDistributionState: 'none',
          registryMismatch: false,
          transparencyConflict: false,
        },
      }),
    ).toBe('SHOW SAS');
  });

  it('maps import-invite and reverify actions to distinct labels', () => {
    expect(
      dmTrustPrimaryActionLabel({
        trustSummary: {
          state: 'unpinned',
          label: 'UNVERIFIED',
          severity: 'warn',
          detail: 'invite required',
          verifiedFirstContact: false,
          recommendedAction: 'import_invite',
          legacyLookup: false,
          inviteAttested: false,
          registryMismatch: false,
          transparencyConflict: false,
        },
      }),
    ).toBe('IMPORT INVITE');
    expect(
      dmTrustPrimaryActionLabel({
        trustSummary: {
          state: 'continuity_broken',
          label: 'CONTINUITY BROKEN',
          severity: 'danger',
          detail: 'reverify',
          verifiedFirstContact: false,
          recommendedAction: 'reverify',
          legacyLookup: false,
          inviteAttested: true,
          registryMismatch: true,
          transparencyConflict: false,
        },
      }),
    ).toBe('REVERIFY NOW');
  });

  it('surfaces stable root mismatch as a continuity hazard', () => {
    const contact = {
      trustSummary: {
        state: 'continuity_broken',
        label: 'CONTINUITY BROKEN',
        severity: 'danger',
        detail: 'root changed',
        verifiedFirstContact: false,
        recommendedAction: 'reverify',
        legacyLookup: false,
        inviteAttested: true,
        rootAttested: true,
        rootWitnessed: true,
        rootDistributionState: 'quorum_witnessed',
        rootMismatch: true,
        registryMismatch: false,
        transparencyConflict: false,
      },
    };

    expect(buildDmTrustHint(contact)).toEqual(
      expect.objectContaining({
        severity: 'danger',
        title: 'CONTINUITY BROKEN',
      }),
    );
    expect(buildDmTrustHint(contact)?.detail).toContain('stable root identity');
  });

  it('treats legacy lookup on an otherwise verified contact as an invite-import migration state', () => {
    const contact = {
      trustSummary: {
        state: 'sas_verified',
        label: 'SAS VERIFIED',
        severity: 'good',
        detail: 'sas verified but still legacy lookup',
        verifiedFirstContact: true,
        recommendedAction: 'import_invite',
        legacyLookup: true,
        inviteAttested: false,
        rootDistributionState: 'none',
        registryMismatch: false,
        transparencyConflict: false,
      },
    };

    expect(dmTrustPrimaryActionLabel(contact)).toBe('IMPORT INVITE');
    expect(buildDmTrustHint(contact)).toEqual(
      expect.objectContaining({
        severity: 'warn',
        title: 'LEGACY LOOKUP',
      }),
    );
  });

  it('surfaces internal-only root continuity as an invite refresh state', () => {
    const contact = {
      trustSummary: {
        state: 'invite_pinned',
        label: 'INVITE PINNED',
        severity: 'warn',
        detail: 'invite pinned on internal root only',
        verifiedFirstContact: true,
        recommendedAction: 'import_invite',
        legacyLookup: false,
        inviteAttested: true,
        rootAttested: true,
        rootWitnessed: false,
        rootDistributionState: 'internal_only',
        rootMismatch: false,
        registryMismatch: false,
        transparencyConflict: false,
      },
    };

    expect(dmTrustPrimaryActionLabel(contact)).toBe('IMPORT INVITE');
    expect(buildDmTrustHint(contact)).toEqual(
      expect.objectContaining({
        severity: 'warn',
        title: 'ROOT INTERNAL ONLY',
      }),
    );
    expect(buildDmTrustHint(contact)?.detail).toContain('witnessed root');
  });

  it('surfaces single-witness root continuity as a weaker witnessed state', () => {
    const contact = {
      trustSummary: {
        state: 'invite_pinned',
        label: 'INVITE PINNED',
        severity: 'warn',
        detail: 'invite pinned on single witness root',
        verifiedFirstContact: true,
        recommendedAction: 'import_invite',
        legacyLookup: false,
        inviteAttested: true,
        rootAttested: true,
        rootWitnessed: true,
        rootDistributionState: 'single_witness',
        rootWitnessCount: 1,
        rootWitnessThreshold: 1,
        rootWitnessQuorumMet: true,
        rootMismatch: false,
        registryMismatch: false,
        transparencyConflict: false,
      },
    };

    expect(dmTrustPrimaryActionLabel(contact)).toBe('IMPORT INVITE');
    expect(buildDmTrustHint(contact)).toEqual(
      expect.objectContaining({
        severity: 'warn',
        title: 'ROOT SINGLE WITNESS',
      }),
    );
    expect(buildDmTrustHint(contact)?.detail).toContain('quorum witness provenance');
  });

  it('surfaces unproven witnessed root rotation as a hard invite refresh state', () => {
    const contact = {
      trustSummary: {
        state: 'invite_pinned',
        label: 'INVITE PINNED',
        severity: 'warn',
        detail: 'invite pinned on witnessed root without rotation proof',
        verifiedFirstContact: false,
        recommendedAction: 'import_invite',
        legacyLookup: false,
        inviteAttested: true,
        rootAttested: true,
        rootWitnessed: true,
        rootDistributionState: 'quorum_witnessed',
        rootManifestGeneration: 2,
        rootRotationProven: false,
        rootMismatch: false,
        registryMismatch: false,
        transparencyConflict: false,
      },
    };

    expect(dmTrustPrimaryActionLabel(contact)).toBe('IMPORT INVITE');
    expect(buildDmTrustHint(contact)).toEqual(
      expect.objectContaining({
        severity: 'danger',
        title: 'ROOT ROTATION UNPROVEN',
      }),
    );
    expect(buildDmTrustHint(contact)?.detail).toContain('previous-root proof');
  });

  it('surfaces unsatisfied witness policy as a hard invite refresh state', () => {
    const contact = {
      trustSummary: {
        state: 'invite_pinned',
        label: 'INVITE PINNED',
        severity: 'warn',
        detail: 'invite pinned on root missing witness quorum',
        verifiedFirstContact: false,
        recommendedAction: 'import_invite',
        legacyLookup: false,
        inviteAttested: true,
        rootAttested: true,
        rootWitnessed: true,
        rootDistributionState: 'witness_policy_not_met',
        rootWitnessCount: 1,
        rootWitnessThreshold: 2,
        rootWitnessQuorumMet: false,
        rootMismatch: false,
        registryMismatch: false,
        transparencyConflict: false,
      },
    };

    expect(dmTrustPrimaryActionLabel(contact)).toBe('IMPORT INVITE');
    expect(buildDmTrustHint(contact)).toEqual(
      expect.objectContaining({
        severity: 'danger',
        title: 'ROOT WITNESS POLICY NOT MET',
      }),
    );
    expect(buildDmTrustHint(contact)?.detail).toContain('witness policy');
  });

  it('transitional lane hint separates gate posture from DM posture', () => {
    const hint = buildPrivateLaneHint({
      activeTab: 'infonet',
      privateInfonetReady: true,
      privateInfonetTransportReady: false,
    });

    expect(hint).toEqual(
      expect.objectContaining({
        severity: 'warn',
        title: 'TRANSITIONAL PRIVATE LANE',
      }),
    );
    // Must explicitly mention gate is on a transitional lane
    expect(hint?.detail).toContain('transitional');
    // Must explicitly mention DM requires a stronger tier
    expect(hint?.detail).toContain('Dead Drop');
    expect(hint?.detail).toMatch(/PRIVATE \/ STRONG/i);
    // Must not imply gate and DM share the same posture
    expect(hint?.detail).toContain('weaker than DM');
  });

  it('relay delivery hint is specific to Dead Drop, not gate', () => {
    const hint = buildPrivateLaneHint({
      activeTab: 'dms',
      dmTransportMode: 'relay',
    });

    expect(hint).toEqual(
      expect.objectContaining({
        severity: 'warn',
        title: 'RELAY DELIVERY ACTIVE',
      }),
    );
    expect(hint?.detail).toContain('Dead Drop');
  });

  it('shortens long trust fingerprints for display', () => {
    expect(shortTrustFingerprint('abcdef0123456789fedcba9876543210')).toBe('abcdef01..543210');
    expect(shortTrustFingerprint('abcd1234')).toBe('abcd1234');
    expect(shortTrustFingerprint('')).toBe('unknown');
  });
});
