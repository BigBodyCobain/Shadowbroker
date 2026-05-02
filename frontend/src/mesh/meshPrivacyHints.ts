import type { Contact } from '@/mesh/meshIdentity';
import { getContactTrustSummary, rootWitnessIdentityLabel } from '@/mesh/contactTrustSummary';

export type PrivateLaneHint = {
  severity: 'warn' | 'danger';
  title: string;
  detail: string;
};

export type DmTrustHint = {
  severity: 'warn' | 'danger';
  title: string;
  detail: string;
};

export type PrivateLaneMode =
  | 'reticulum'
  | 'relay'
  | 'ready'
  | 'hidden'
  | 'blocked'
  | 'degraded';

function cleanReason(value: string | undefined): string {
  return String(value || '').trim();
}

export function shortTrustFingerprint(fingerprint: string | undefined): string {
  const value = String(fingerprint || '').trim().toLowerCase();
  if (!value) return 'unknown';
  if (value.length <= 14) return value;
  return `${value.slice(0, 8)}..${value.slice(-6)}`;
}

export function isInvitePinnedFirstContact(contact?: Partial<Contact> | null): boolean {
  return getContactTrustSummary(contact)?.state === 'invite_pinned';
}

export function isFirstContactTrustOnly(contact?: Partial<Contact> | null): boolean {
  return getContactTrustSummary(contact)?.state === 'tofu_pinned';
}

export function hasKnownFirstContactAnchor(contact?: Partial<Contact> | null): boolean {
  if (!contact) return false;
  return Boolean(
    contact.dhPubKey ||
      contact.sharedAlias ||
      contact.remotePrekeyFingerprint ||
      contact.remotePrekeyObservedFingerprint ||
      contact.remotePrekeyPinnedAt ||
      contact.invitePinnedTrustFingerprint ||
      contact.invitePinnedDhPubKey ||
      contact.invitePinnedAt ||
      contact.verified ||
      contact.verify_registry ||
      contact.verify_inband ||
      String(contact.trust_level || '').trim(),
  );
}

export function hasVerifiedFirstContactAnchor(contact?: Partial<Contact> | null): boolean {
  const summary = getContactTrustSummary(contact);
  return Boolean(summary?.verifiedFirstContact);
}

export function requiresVerifiedFirstContact(contact?: Partial<Contact> | null): boolean {
  return !hasVerifiedFirstContactAnchor(contact);
}

export function requiresExplicitTofuDowngrade(contact?: Partial<Contact> | null): boolean {
  return !hasKnownFirstContactAnchor(contact);
}

export function shouldAutoRevealSasForTrust(contact?: Partial<Contact> | null): boolean {
  const summary = getContactTrustSummary(contact);
  if (!summary) return false;
  return Boolean(
    summary.state === 'tofu_pinned' ||
      summary.state === 'mismatch' ||
      summary.state === 'continuity_broken' ||
      summary.registryMismatch,
  );
}

export function dmTrustPrimaryActionLabel(contact?: Partial<Contact> | null): string {
  const action = getContactTrustSummary(contact)?.recommendedAction;
  if (action === 'import_invite') {
    return 'IMPORT INVITE';
  }
  if (action === 'verify_sas') {
    return 'VERIFY SAS NOW';
  }
  if (action === 'reverify') {
    return 'REVERIFY NOW';
  }
  return 'SHOW SAS';
}

export function buildPrivateLaneHint(opts: {
  activeTab: 'infonet' | 'meshtastic' | 'dms';
  recentPrivateFallback?: boolean;
  recentPrivateFallbackReason?: string;
  dmTransportMode?: PrivateLaneMode;
  privateInfonetReady?: boolean;
  privateInfonetTransportReady?: boolean;
}): PrivateLaneHint | null {
  const reason =
    cleanReason(opts.recentPrivateFallbackReason) ||
    'A recent private-tier send fell back to clearnet relay.';
  if (opts.recentPrivateFallback && (opts.activeTab === 'dms' || opts.activeTab === 'infonet')) {
    return {
      severity: 'danger',
      title: 'RECENT PRIVACY DOWNGRADE',
      detail: `${reason} Treat recent traffic as exposed to weaker metadata protection until the private lane is healthy again.`,
    };
  }
  if (opts.activeTab === 'dms' && opts.dmTransportMode === 'relay') {
    return {
      severity: 'warn',
      title: 'RELAY DELIVERY ACTIVE',
      detail:
        'Dead Drop is currently using relay delivery. Content stays encrypted, but timing and mailbox metadata are weaker than direct private delivery.',
    };
  }
  if (
    opts.activeTab === 'infonet' &&
    opts.privateInfonetReady &&
    !opts.privateInfonetTransportReady
  ) {
    return {
      severity: 'warn',
      title: 'CONTROL-ONLY PRIVATE LANE',
      detail:
        'Gate chat is available once Wormhole is ready, but this setup is still only PRIVATE / CONTROL_ONLY. Content stays encrypted, while metadata resistance is reduced until a stronger private carrier comes online. Dead Drop / DM remains the stronger lane.',
    };
  }
  return null;
}

export function buildDmTrustHint(contact?: Partial<Contact> | null): DmTrustHint | null {
  const summary = getContactTrustSummary(contact);
  if (!contact || !summary) return null;
  const witnessedRootLabel = rootWitnessIdentityLabel(summary);
  if (summary.state === 'continuity_broken' || summary.state === 'mismatch') {
    return {
      severity: 'danger',
      title: summary.state === 'continuity_broken' ? 'CONTINUITY BROKEN' : 'REMOTE PREKEY CHANGED',
      detail:
        summary.rootMismatch
          ? summary.state === 'continuity_broken'
            ? summary.rootWitnessed
              ? `A previously trusted contact changed ${witnessedRootLabel}. Pause private DM sending and replace the signed invite or re-verify SAS before trusting the new key.`
              : 'A previously trusted contact changed stable root identity. Pause private DM sending and replace the signed invite or re-verify SAS before trusting the new key.'
            : summary.rootWitnessed
              ? `Pause private DM sending. The observed ${witnessedRootLabel} changed; replace the invite or compare SAS before trusting the new key.`
              : 'Pause private DM sending. The observed stable root identity changed; replace the invite or compare SAS before trusting the new key.'
          : summary.state === 'continuity_broken'
            ? 'A previously trusted contact changed identity material. Pause private DM sending and replace the invite or re-verify SAS before trusting the new key.'
            : 'Pause private DM sending. Refresh the contact, compare the SAS phrase or another trusted fingerprint, then explicitly trust the new prekey only if it checks out.',
    };
  }
  if (summary.registryMismatch) {
    return {
      severity: 'danger',
      title: 'CONTACT KEY MISMATCH',
      detail:
        'Registry and in-band key evidence disagree for this contact. Re-verify before continuing with private messaging.',
    };
  }
  if (summary.legacyLookup && summary.state === 'sas_verified') {
    return {
      severity: 'warn',
      title: 'LEGACY LOOKUP',
      detail:
        'This contact is SAS verified, but key refresh still relies on direct agent ID lookup. Import or re-import a signed invite to move off stable-ID lookup before removal.',
    };
  }
  if (
    summary.rootAttested &&
    !summary.rootWitnessed &&
    (summary.state === 'invite_pinned' || summary.state === 'sas_verified')
  ) {
    return {
      severity: 'warn',
      title: 'ROOT INTERNAL ONLY',
      detail:
        summary.state === 'invite_pinned'
          ? 'This contact is anchored to an internal stable root, but not to witnessed root distribution yet. Re-import a current signed invite to refresh stronger root provenance.'
          : 'This contact is SAS verified on an internal stable root, but root distribution is not witnessed yet. Re-import a current signed invite if you want witnessed root provenance too.',
    };
  }
  if (
    summary.rootDistributionState === 'single_witness' &&
    (summary.state === 'invite_pinned' || summary.state === 'sas_verified')
  ) {
    return {
      severity: 'warn',
      title: 'ROOT SINGLE WITNESS',
      detail:
        summary.state === 'invite_pinned'
          ? 'This contact is anchored to a single-witness stable root. Re-import a current signed invite if you want stronger quorum witness provenance.'
          : 'This contact is SAS verified on a single-witness stable root. Re-import a current signed invite if you want stronger quorum witness provenance too.',
    };
  }
  if (
    summary.rootWitnessProvenanceState === 'local_quorum' &&
    !(summary.rootWitnessed && Number(summary.rootManifestGeneration || 0) > 1 && !summary.rootRotationProven) &&
    (summary.state === 'invite_pinned' || summary.state === 'sas_verified')
  ) {
    return {
      severity: 'warn',
      title: 'ROOT LOCAL QUORUM',
      detail:
        summary.state === 'invite_pinned'
          ? 'This contact is anchored to a locally quorum-witnessed stable root. The current witness policy is satisfied, but those witnesses are still co-resident in one trust domain.'
          : 'This contact is SAS verified on a locally quorum-witnessed stable root. The current witness policy is satisfied, but those witnesses are still co-resident in one trust domain.',
    };
  }
  if (
    summary.rootWitnessProvenanceState === 'independent_quorum' &&
    !(summary.rootWitnessed && Number(summary.rootManifestGeneration || 0) > 1 && !summary.rootRotationProven) &&
    (summary.state === 'invite_pinned' || summary.state === 'sas_verified')
  ) {
    return {
      severity: 'warn',
      title: 'ROOT INDEPENDENT QUORUM',
      detail:
        summary.state === 'invite_pinned'
          ? 'This contact is anchored to an independently quorum-witnessed stable root instead of first-sight TOFU.'
          : 'This contact is SAS verified on an independently quorum-witnessed stable root.',
    };
  }
  if (
    summary.rootWitnessed &&
    Number(summary.rootManifestGeneration || 0) > 1 &&
    !summary.rootRotationProven &&
    (summary.state === 'invite_pinned' || summary.state === 'sas_verified')
  ) {
    return {
      severity: 'danger',
      title: 'ROOT ROTATION UNPROVEN',
      detail:
        summary.state === 'invite_pinned'
          ? 'This contact resolves to a witnessed stable root, but the current root replacement does not carry previous-root proof. Replace the signed invite before treating this root as continuous.'
          : 'This contact is SAS verified, but the current witnessed root replacement does not carry previous-root proof. Replace the signed invite before treating this root as continuous.',
    };
  }
  if (
    summary.rootDistributionState === 'witness_policy_not_met' &&
    (summary.state === 'invite_pinned' || summary.state === 'sas_verified')
  ) {
    return {
      severity: 'danger',
      title: 'ROOT WITNESS POLICY NOT MET',
      detail:
        summary.state === 'invite_pinned'
          ? 'This contact resolves to a witnessed stable root, but the current receipt set does not satisfy the published witness policy. Replace or re-import the signed invite before private use.'
          : 'This contact is SAS verified, but the current witnessed root no longer satisfies its published witness policy. Replace or re-import the signed invite before private use.',
    };
  }
  if (summary.state === 'invite_pinned') {
    return {
      severity: 'warn',
      title: 'INVITE PINNED',
      detail:
        summary.rootAttested
          ? summary.rootWitnessProvenanceState === 'independent_quorum'
            ? 'This contact was anchored by an imported signed invite and independently quorum-witnessed stable root identity instead of first-sight TOFU. Keep the invite channel trusted, and use SAS if you want an additional continuity check.'
            : summary.rootWitnessProvenanceState === 'local_quorum'
              ? 'This contact was anchored by an imported signed invite and locally quorum-witnessed stable root identity instead of first-sight TOFU. Keep the invite channel trusted, and use SAS if you want an additional continuity check.'
            : summary.rootDistributionState === 'single_witness'
              ? 'This contact was anchored by an imported signed invite and single-witness stable root identity instead of first-sight TOFU. Re-import a current signed invite if you want stronger quorum witness provenance.'
              : summary.rootWitnessed
                ? 'This contact was anchored by an imported signed invite and witnessed stable root identity instead of first-sight TOFU, but the current witness policy is not satisfied.'
                : 'This contact was anchored by an imported signed invite and stable root identity instead of first-sight TOFU. Root distribution is still internal-only.'
          : 'This contact was anchored by an imported signed invite instead of first-sight TOFU. Keep the invite channel trusted, and use SAS if you want an additional continuity check.',
    };
  }
  if (summary.state === 'tofu_pinned') {
    return {
      severity: 'warn',
      title: 'FIRST CONTACT (TOFU ONLY)',
      detail:
        'This contact is pinned on first sight only. A decrypted DM is not proof of sender identity. Compare the SAS phrase or another trusted fingerprint before sharing sensitive material or acting on requests.',
    };
  }
  if (contact.verify_registry && !contact.verify_inband) {
    return {
      severity: 'warn',
      title: 'REGISTRY ONLY',
      detail:
        'This contact has registry verification, but no matching in-band verification yet. SAS comparison is still recommended before sensitive use.',
    };
  }
  if (contact.verify_inband && !contact.verify_registry) {
    return {
      severity: 'warn',
      title: 'IN-BAND ONLY',
      detail:
        'This contact has in-band verification, but no matching registry proof yet. Refresh the contact before sensitive use.',
    };
  }
  return null;
}
