import type { Contact } from '@/mesh/meshIdentity';

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

export function isFirstContactTrustOnly(contact?: Partial<Contact> | null): boolean {
  if (!contact) return false;
  if (contact.remotePrekeyMismatch || contact.verify_mismatch || contact.verified) return false;
  if (contact.verify_registry || contact.verify_inband) return false;
  return Boolean(contact.remotePrekeyFingerprint || contact.remotePrekeyPinnedAt);
}

export function shouldAutoRevealSasForTrust(contact?: Partial<Contact> | null): boolean {
  if (!contact) return false;
  return Boolean(
    contact.remotePrekeyMismatch || contact.verify_mismatch || isFirstContactTrustOnly(contact),
  );
}

export function dmTrustPrimaryActionLabel(contact?: Partial<Contact> | null): string {
  return isFirstContactTrustOnly(contact) ? 'VERIFY SAS NOW' : 'SHOW SAS';
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
      title: 'TRANSITIONAL PRIVATE LANE',
      detail:
        'INFONET gate chat is available, but the strongest transport posture is still warming up. Treat metadata resistance as reduced until Reticulum is ready.',
    };
  }
  return null;
}

export function buildDmTrustHint(contact?: Partial<Contact> | null): DmTrustHint | null {
  if (!contact) return null;
  if (contact.remotePrekeyMismatch) {
    return {
      severity: 'danger',
      title: 'REMOTE PREKEY CHANGED',
      detail:
        'Pause private DM sending. Refresh the contact, compare the SAS phrase or another trusted fingerprint, then explicitly trust the new prekey only if it checks out.',
    };
  }
  if (contact.verify_mismatch) {
    return {
      severity: 'danger',
      title: 'CONTACT KEY MISMATCH',
      detail:
        'Registry and in-band key evidence disagree for this contact. Re-verify before continuing with private messaging.',
    };
  }
  if (isFirstContactTrustOnly(contact)) {
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
