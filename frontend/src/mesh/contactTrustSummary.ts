import type { Contact } from '@/mesh/meshIdentity';
import type {
  ContactRootDistributionState,
  ContactRootWitnessProvenanceState,
  ContactTrustRecommendedAction,
  ContactTrustSeverity,
  ContactTrustSummary,
} from '@/mesh/contactTrustTypes';

function normalizeState(value: string | undefined): string {
  const state = String(value || '').trim();
  if (
    state === 'unpinned' ||
    state === 'tofu_pinned' ||
    state === 'invite_pinned' ||
    state === 'sas_verified' ||
    state === 'mismatch' ||
    state === 'continuity_broken'
  ) {
    return state;
  }
  return 'unpinned';
}

function normalizeExistingTrustSummary(
  summary: Partial<ContactTrustSummary> | null | undefined,
): ContactTrustSummary | null {
  if (!summary || typeof summary !== 'object') return null;
  const severity = String(summary.severity || '').trim() as ContactTrustSeverity;
  const recommendedAction = String(
    summary.recommendedAction || '',
  ).trim() as ContactTrustRecommendedAction;
  if (
    !['danger', 'warn', 'good', 'info'].includes(severity) ||
    !['none', 'import_invite', 'verify_sas', 'show_sas', 'reverify'].includes(
      recommendedAction,
    )
  ) {
    return null;
  }
  const label = String(summary.label || '').trim();
  const detail = String(summary.detail || '').trim();
  if (!label || !detail) return null;
  const rootDistributionState = String(
    summary.rootDistributionState || 'none',
  ).trim() as ContactRootDistributionState;
  if (
    ![
      'none',
      'internal_only',
      'single_witness',
      'quorum_witnessed',
      'witness_policy_not_met',
    ].includes(rootDistributionState)
  ) {
    return null;
  }
  const rootWitnessThreshold = Number(summary.rootWitnessThreshold || 0);
  const rootWitnessCount = Number(summary.rootWitnessCount || 0);
  const rootWitnessQuorumMet = Boolean(
    summary.rootWitnessQuorumMet ||
      rootDistributionState === 'quorum_witnessed' ||
      rootDistributionState === 'single_witness',
  );
  const rootWitnessDomainCount = Number(
    summary.rootWitnessDomainCount ||
      (rootDistributionState === 'quorum_witnessed' || rootDistributionState === 'single_witness' ? 1 : 0),
  );
  const rootWitnessIndependentQuorumMet = Boolean(
    summary.rootWitnessIndependentQuorumMet ||
      (rootWitnessThreshold > 1 && rootWitnessDomainCount >= rootWitnessThreshold),
  );
  const rootWitnessProvenanceState = String(
    summary.rootWitnessProvenanceState ||
      (rootDistributionState === 'quorum_witnessed'
        ? rootWitnessIndependentQuorumMet
          ? 'independent_quorum'
          : 'local_quorum'
        : rootDistributionState),
  ).trim() as ContactRootWitnessProvenanceState;
  if (
    ![
      'none',
      'internal_only',
      'single_witness',
      'witness_policy_not_met',
      'local_quorum',
      'independent_quorum',
    ].includes(rootWitnessProvenanceState)
  ) {
    return null;
  }
  return {
    state: normalizeState(summary.state),
    label,
    severity,
    detail,
    verifiedFirstContact: Boolean(summary.verifiedFirstContact),
    recommendedAction,
    legacyLookup: Boolean(summary.legacyLookup),
    inviteAttested: Boolean(summary.inviteAttested),
    rootAttested: Boolean(summary.rootAttested),
    rootWitnessed: Boolean(summary.rootWitnessed),
    rootDistributionState,
    rootWitnessPolicyFingerprint: String(summary.rootWitnessPolicyFingerprint || '').trim().toLowerCase(),
    rootWitnessCount,
    rootWitnessThreshold,
    rootWitnessQuorumMet,
    rootWitnessProvenanceState,
    rootWitnessDomainCount,
    rootWitnessIndependentQuorumMet,
    rootManifestGeneration: Number(summary.rootManifestGeneration || 0),
    rootRotationProven: Boolean(summary.rootRotationProven),
    rootMismatch: Boolean(summary.rootMismatch),
    registryMismatch: Boolean(summary.registryMismatch),
    transparencyConflict: Boolean(summary.transparencyConflict),
  };
}

function deriveRootWitnessProvenanceState(args: {
  rootAttested: boolean;
  rootWitnessed: boolean;
  rootWitnessQuorumMet: boolean;
  rootWitnessThreshold: number;
  rootWitnessIndependentQuorumMet: boolean;
}): ContactRootWitnessProvenanceState {
  const {
    rootAttested,
    rootWitnessed,
    rootWitnessQuorumMet,
    rootWitnessThreshold,
    rootWitnessIndependentQuorumMet,
  } = args;
  if (!rootAttested) return 'none';
  if (!rootWitnessed) return 'internal_only';
  if (!rootWitnessQuorumMet) return 'witness_policy_not_met';
  if (rootWitnessThreshold <= 1) return 'single_witness';
  return rootWitnessIndependentQuorumMet ? 'independent_quorum' : 'local_quorum';
}

export function rootWitnessBadgeLabel(
  summary: Pick<ContactTrustSummary, 'rootAttested' | 'rootWitnessProvenanceState' | 'rootWitnessed'> | null | undefined,
): string {
  if (!summary?.rootAttested) return 'Root';
  switch (summary.rootWitnessProvenanceState) {
    case 'independent_quorum':
      return 'Independent quorum root';
    case 'local_quorum':
      return 'Local quorum root';
    case 'single_witness':
      return 'Single-witness root';
    case 'witness_policy_not_met':
      return 'Witness-policy root';
    default:
      return summary.rootWitnessed ? 'Witnessed root' : 'Root';
  }
}

export function rootWitnessContinuityLabel(
  summary: Pick<ContactTrustSummary, 'rootAttested' | 'rootWitnessProvenanceState' | 'rootWitnessed'> | null | undefined,
): string {
  if (!summary?.rootAttested) return 'Stable root continuity';
  switch (summary.rootWitnessProvenanceState) {
    case 'independent_quorum':
      return 'Independent-quorum stable root continuity';
    case 'local_quorum':
      return 'Local-quorum stable root continuity';
    case 'single_witness':
      return 'Single-witness stable root continuity';
    case 'witness_policy_not_met':
      return 'Witness-policy-not-met stable root continuity';
    default:
      return summary.rootWitnessed ? 'Witnessed stable root continuity' : 'Stable root continuity';
  }
}

export function rootWitnessIdentityLabel(
  summary: Pick<ContactTrustSummary, 'rootAttested' | 'rootWitnessProvenanceState' | 'rootWitnessed'> | null | undefined,
): string {
  if (!summary?.rootAttested) return 'stable root identity';
  switch (summary.rootWitnessProvenanceState) {
    case 'independent_quorum':
      return 'independently quorum-witnessed stable root identity';
    case 'local_quorum':
      return 'locally quorum-witnessed stable root identity';
    case 'single_witness':
      return 'single-witness stable root identity';
    case 'witness_policy_not_met':
      return 'witnessed stable root identity';
    default:
      return summary.rootWitnessed ? 'witnessed stable root identity' : 'stable root identity';
  }
}

function deriveTrustSummary(contact?: Partial<Contact> | null): ContactTrustSummary | null {
  if (!contact) return null;
  const transparencyConflict = Boolean(contact.remotePrekeyTransparencyConflict);
  const registryMismatch = Boolean(contact.verify_mismatch);
  const inviteAttested = Boolean(contact.invitePinnedTrustFingerprint || contact.invitePinnedAt);
  const rootAttested = Boolean(contact.invitePinnedRootFingerprint || contact.remotePrekeyRootFingerprint);
  const rootWitnessed = Boolean(
    contact.invitePinnedRootManifestFingerprint ||
      contact.remotePrekeyRootManifestFingerprint ||
      contact.remotePrekeyObservedRootManifestFingerprint,
  );
  const rootMismatch = Boolean(contact.remotePrekeyRootMismatch);
  const rootWitnessPolicyFingerprint = String(
    rootMismatch
      ? contact.remotePrekeyObservedRootWitnessPolicyFingerprint || ''
      : contact.remotePrekeyRootWitnessPolicyFingerprint ||
          contact.invitePinnedRootWitnessPolicyFingerprint ||
          '',
  )
    .trim()
    .toLowerCase();
  const rawRootWitnessThreshold = Number(
    rootMismatch
      ? contact.remotePrekeyObservedRootWitnessThreshold || 0
      : contact.remotePrekeyRootWitnessThreshold || contact.invitePinnedRootWitnessThreshold || 0,
  );
  const rawRootWitnessCount = Number(
    rootMismatch
      ? contact.remotePrekeyObservedRootWitnessCount || 0
      : contact.remotePrekeyRootWitnessCount || contact.invitePinnedRootWitnessCount || 0,
  );
  const rawRootWitnessDomainCount = Number(
    rootMismatch
      ? contact.remotePrekeyObservedRootWitnessDomainCount || 0
      : contact.remotePrekeyRootWitnessDomainCount || contact.invitePinnedRootWitnessDomainCount || 0,
  );
  const rootWitnessThreshold = rootWitnessed
    ? rawRootWitnessThreshold > 0
      ? rawRootWitnessThreshold
      : 1
    : 0;
  const rootWitnessCount = rootWitnessed
    ? rawRootWitnessCount > 0
      ? rawRootWitnessCount
      : 1
    : 0;
  const rootWitnessDomainCount = rootWitnessed
    ? rawRootWitnessDomainCount > 0
      ? rawRootWitnessDomainCount
      : 1
    : 0;
  const rootWitnessQuorumMet = rootWitnessed
    ? rootWitnessThreshold <= 1 || rootWitnessCount >= rootWitnessThreshold
    : false;
  const rootWitnessIndependentQuorumMet = rootWitnessed
    ? rootWitnessThreshold <= 1 || rootWitnessDomainCount >= rootWitnessThreshold
    : false;
  const rootDistributionState: ContactRootDistributionState = !rootAttested
    ? 'none'
    : !rootWitnessed
      ? 'internal_only'
      : !rootWitnessQuorumMet
        ? 'witness_policy_not_met'
        : rootWitnessThreshold <= 1
          ? 'single_witness'
          : 'quorum_witnessed';
  const rootWitnessProvenanceState = deriveRootWitnessProvenanceState({
    rootAttested,
    rootWitnessed,
    rootWitnessQuorumMet,
    rootWitnessThreshold,
    rootWitnessIndependentQuorumMet,
  });
  const rootManifestGeneration = Number(
    rootMismatch
      ? contact.remotePrekeyObservedRootManifestGeneration ||
          contact.remotePrekeyRootManifestGeneration ||
          contact.invitePinnedRootManifestGeneration ||
          0
      : contact.remotePrekeyRootManifestGeneration ||
          contact.invitePinnedRootManifestGeneration ||
          0,
  );
  const rootRotationProven =
    rootManifestGeneration > 0 &&
    (rootManifestGeneration <= 1 ||
      Boolean(
        rootMismatch
          ? contact.remotePrekeyObservedRootRotationProven
          : contact.remotePrekeyRootRotationProven || contact.invitePinnedRootRotationProven,
      ));
  const rootRotationUnproven =
    rootWitnessed && rootManifestGeneration > 1 && !rootRotationProven;
  const rootDistributionUpgradeNeeded =
    rootAttested &&
    ['internal_only', 'single_witness', 'witness_policy_not_met'].includes(rootDistributionState);
  let state = normalizeState(contact.trust_level);
  if (contact.remotePrekeyMismatch) {
    state =
      state === 'invite_pinned' || state === 'sas_verified' || inviteAttested
        ? 'continuity_broken'
        : 'mismatch';
  } else if (rootMismatch) {
    state =
      state === 'invite_pinned' || state === 'sas_verified' || inviteAttested || rootAttested
        ? 'continuity_broken'
        : 'mismatch';
  } else if (!contact.trust_level && (contact.remotePrekeyFingerprint || contact.remotePrekeyPinnedAt)) {
    state = inviteAttested ? 'invite_pinned' : 'tofu_pinned';
  }
  const legacyLookup =
    String(contact.remotePrekeyLookupMode || '').trim().toLowerCase() === 'legacy_agent_id';

  let label = 'UNVERIFIED';
  let severity: ContactTrustSeverity = 'warn';
  let detail =
    'No trusted first-contact anchor. Import a signed invite before secure first contact.';
  let recommendedAction: ContactTrustRecommendedAction = 'import_invite';

  if (state === 'continuity_broken') {
    label = 'CONTINUITY BROKEN';
    severity = 'danger';
    detail =
      'Pinned trust anchor changed. Re-verify SAS or replace the invite before private use.';
    recommendedAction = 'reverify';
  } else if (state === 'mismatch' || (state === 'unpinned' && contact.remotePrekeyMismatch)) {
    label = 'REVERIFY';
    severity = 'danger';
    detail = 'Observed prekey identity changed. Compare SAS before trusting the new key.';
    recommendedAction = 'reverify';
  } else if (
    state === 'tofu_pinned' ||
    (!contact.trust_level && (contact.remotePrekeyFingerprint || contact.remotePrekeyPinnedAt))
  ) {
    label = 'TOFU PINNED';
    detail = rootAttested
      ? rootWitnessed
        ? rootRotationUnproven
          ? 'Current prekey is seen under one witnessed stable root, but that root rotation lacks previous-root proof. Replace the signed invite before treating this root as continuous.'
          : rootWitnessProvenanceState === 'independent_quorum'
            ? 'Current prekey is seen under one independently quorum-witnessed stable root, but first contact is still TOFU-only. Verify SAS before sensitive use.'
            : rootWitnessProvenanceState === 'local_quorum'
              ? 'Current prekey is seen under one locally quorum-witnessed stable root, but first contact is still TOFU-only. Verify SAS before sensitive use.'
            : rootDistributionState === 'single_witness'
              ? 'Current prekey is seen under one single-witness stable root, but first contact is still TOFU-only. Re-import a current signed invite if you want stronger quorum witness provenance.'
              : 'Current prekey is seen under a witnessed stable root, but the current witness policy is not satisfied. Replace or re-import the signed invite before treating this root as strong first-contact provenance.'
        : 'Current prekey is seen under one stable root, but first contact is still TOFU-only. Verify SAS before sensitive use.'
      : 'First contact is pinned on first sight only. Verify SAS before sensitive use.';
    recommendedAction = rootRotationUnproven ? 'import_invite' : 'verify_sas';
  } else if (state === 'invite_pinned' || inviteAttested) {
    label = 'INVITE PINNED';
    detail = rootAttested
      ? rootWitnessed
        ? rootRotationUnproven
          ? 'First contact is anchored to an imported signed invite and a witnessed stable root identity, but its current root rotation lacks previous-root proof. Replace the signed invite before private use.'
          : rootWitnessProvenanceState === 'independent_quorum'
            ? 'First contact is anchored to an imported signed invite and an independently quorum-witnessed stable root identity. SAS is optional but recommended for continuity.'
            : rootWitnessProvenanceState === 'local_quorum'
              ? 'First contact is anchored to an imported signed invite and a locally quorum-witnessed stable root identity. SAS is optional but recommended for continuity.'
            : rootDistributionState === 'single_witness'
              ? 'First contact is anchored to an imported signed invite and a single-witness stable root identity. Re-import a current signed invite if you want stronger quorum witness provenance.'
              : 'First contact is anchored to an imported signed invite and a witnessed stable root identity, but the current witness policy is not satisfied. Replace the signed invite before private use.'
        : 'First contact is anchored to an imported signed invite and a stable root identity, but root distribution is still internal-only. Re-import a current signed invite to refresh witnessed root distribution.'
      : 'First contact is anchored to an imported signed invite. SAS is optional but recommended for continuity.';
    recommendedAction = rootDistributionUpgradeNeeded || rootRotationUnproven ? 'import_invite' : 'show_sas';
  } else if (state === 'sas_verified') {
    label = 'SAS VERIFIED';
    severity = 'good';
    detail = rootAttested
      ? rootWitnessed
        ? rootRotationUnproven
          ? 'This contact was SAS confirmed on the current pinned fingerprint, but its current witnessed root rotation lacks previous-root proof.'
          : rootWitnessProvenanceState === 'independent_quorum'
            ? 'This contact was SAS confirmed on the current pinned fingerprint and independently quorum-witnessed stable root identity.'
            : rootWitnessProvenanceState === 'local_quorum'
              ? 'This contact was SAS confirmed on the current pinned fingerprint and locally quorum-witnessed stable root identity.'
            : rootDistributionState === 'single_witness'
              ? 'This contact was SAS confirmed on the current pinned fingerprint and single-witness stable root identity. Re-import a current signed invite if you want stronger quorum witness provenance.'
              : 'This contact was SAS confirmed on the current pinned fingerprint, but the current witnessed root does not satisfy its witness policy.'
        : 'This contact was SAS confirmed on the current pinned fingerprint and stable root identity, but root distribution is still internal-only.'
      : 'This contact was confirmed with a shared SAS phrase on the current pinned fingerprint.';
    recommendedAction = rootDistributionUpgradeNeeded || rootRotationUnproven ? 'import_invite' : 'show_sas';
  }

  if (rootMismatch && state !== 'continuity_broken' && state !== 'mismatch') {
    state = inviteAttested || rootAttested ? 'continuity_broken' : 'mismatch';
  }
  if (rootMismatch) {
    label = state === 'continuity_broken' ? 'CONTINUITY BROKEN' : 'REVERIFY';
    severity = 'danger';
    detail =
      state === 'continuity_broken'
        ? rootWitnessProvenanceState === 'independent_quorum'
          ? 'Pinned independently quorum-witnessed stable root identity changed. Replace the signed invite or re-verify SAS before private use.'
          : rootWitnessProvenanceState === 'local_quorum'
            ? 'Pinned locally quorum-witnessed stable root identity changed. Replace the signed invite or re-verify SAS before private use.'
          : rootDistributionState === 'single_witness'
            ? 'Pinned single-witness stable root identity changed. Replace the signed invite or re-verify SAS before private use.'
            : rootWitnessed
              ? 'Pinned stable root identity changed and its witness policy is not satisfied. Replace the signed invite or re-verify SAS before private use.'
              : 'Pinned stable root identity changed. Replace the signed invite or re-verify SAS before private use.'
        : rootWitnessProvenanceState === 'independent_quorum'
          ? 'Observed independently quorum-witnessed stable root identity changed. Replace the invite or compare SAS before trusting the new key.'
          : rootWitnessProvenanceState === 'local_quorum'
            ? 'Observed locally quorum-witnessed stable root identity changed. Replace the invite or compare SAS before trusting the new key.'
          : rootDistributionState === 'single_witness'
            ? 'Observed single-witness stable root identity changed. Replace the invite or compare SAS before trusting the new key.'
            : rootWitnessed
              ? 'Observed stable root identity changed and its witness policy is not satisfied. Replace the invite before trusting the new key.'
              : 'Observed stable root identity changed. Replace the invite or compare SAS before trusting the new key.';
    recommendedAction = 'reverify';
  }

  if (rootRotationUnproven && state !== 'continuity_broken' && state !== 'mismatch') {
    recommendedAction = 'import_invite';
  }

  if (transparencyConflict) {
    detail =
      'Prekey transparency history conflicted. Trust stays degraded until you explicitly acknowledge the changed fingerprint.';
  }
  if (legacyLookup && state !== 'mismatch' && state !== 'continuity_broken' && !transparencyConflict) {
    detail = `${detail} This contact still bootstraps through legacy direct agent ID lookup. Import or re-import a signed invite to avoid stable-ID lookup before removal.`;
    recommendedAction = 'import_invite';
  }

  return {
    state,
    label,
    severity,
    detail,
    verifiedFirstContact:
      (state === 'invite_pinned' || state === 'sas_verified') &&
      !rootRotationUnproven &&
      rootDistributionState !== 'witness_policy_not_met',
    recommendedAction,
    legacyLookup,
    inviteAttested,
    rootAttested,
    rootWitnessed,
    rootDistributionState,
    rootWitnessPolicyFingerprint,
    rootWitnessCount,
    rootWitnessThreshold,
    rootWitnessQuorumMet,
    rootWitnessProvenanceState,
    rootWitnessDomainCount,
    rootWitnessIndependentQuorumMet,
    rootManifestGeneration,
    rootRotationProven,
    rootMismatch,
    registryMismatch,
    transparencyConflict,
  };
}

export function getContactTrustSummary(
  contact?: Partial<Contact> | null,
): ContactTrustSummary | null {
  const existing = normalizeExistingTrustSummary(
    contact?.trustSummary as Partial<ContactTrustSummary> | null | undefined,
  );
  if (existing) return existing;
  return deriveTrustSummary(contact);
}
