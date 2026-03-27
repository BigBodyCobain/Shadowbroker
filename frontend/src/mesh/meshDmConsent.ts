type ContactAliasLike = {
  sharedAlias?: string;
  previousSharedAliases?: string[];
  pendingSharedAlias?: string;
  sharedAliasGraceUntil?: number;
};

export type DmConsentKind = 'contact_offer' | 'contact_accept' | 'contact_deny';

export type DmConsentMessage =
  | {
      kind: 'contact_offer';
      dh_pub_key?: string;
      dh_algo?: string;
      geo_hint?: string;
    }
  | {
      kind: 'contact_accept';
      shared_alias?: string;
    }
  | {
      kind: 'contact_deny';
      reason?: string;
    };

const DM_CONSENT_PREFIX = 'DM_CONSENT:';

export function generateSharedAlias(): string {
  const bytes = new Uint8Array(12);
  crypto.getRandomValues(bytes);
  const suffix = Array.from(bytes)
    .map((byte) => byte.toString(16).padStart(2, '0'))
    .join('');
  return `dmx_${suffix}`;
}

export function buildContactOfferMessage(
  dhPubKey: string,
  dhAlgo: string,
  geoHint?: string,
): string {
  return `${DM_CONSENT_PREFIX}${JSON.stringify({
    kind: 'contact_offer',
    dh_pub_key: dhPubKey,
    dh_algo: dhAlgo,
    geo_hint: geoHint || '',
  })}`;
}

export function buildContactAcceptMessage(sharedAlias: string): string {
  return `${DM_CONSENT_PREFIX}${JSON.stringify({
    kind: 'contact_accept',
    shared_alias: sharedAlias,
  })}`;
}

export function buildContactDenyMessage(reason: string = ''): string {
  return `${DM_CONSENT_PREFIX}${JSON.stringify({
    kind: 'contact_deny',
    reason,
  })}`;
}

export function parseDmConsentMessage(text: string): DmConsentMessage | null {
  try {
    if (text.startsWith(DM_CONSENT_PREFIX)) {
      const payload = JSON.parse(text.slice(DM_CONSENT_PREFIX.length));
      const kind = String(payload?.kind || '').trim() as DmConsentKind;
      if (kind === 'contact_offer') {
        const dhPubKey = String(payload?.dh_pub_key || '').trim();
        const dhAlgo = String(payload?.dh_algo || '').trim();
        const geoHint = String(payload?.geo_hint || '').trim();
        if (!dhPubKey) return null;
        return {
          kind,
          dh_pub_key: dhPubKey,
          dh_algo: dhAlgo || undefined,
          geo_hint: geoHint || undefined,
        };
      }
      if (kind === 'contact_accept') {
        const sharedAlias = String(payload?.shared_alias || '').trim();
        if (!sharedAlias) return null;
        return { kind, shared_alias: sharedAlias };
      }
      if (kind === 'contact_deny') {
        const reason = String(payload?.reason || '').trim();
        return { kind, reason: reason || undefined };
      }
    }
  } catch {
    return null;
  }

  try {
    if (text.startsWith('ACCESS_REQUEST:')) {
      const payload = text.slice('ACCESS_REQUEST:'.length);
      const [base, ...metaParts] = payload.split('|');
      const parts = base.split(':');
      let geoHint: string | undefined;
      for (const part of metaParts) {
        if (part.startsWith('geo=')) {
          geoHint = part.slice(4);
        }
      }
      if (parts.length >= 2) {
        return {
          kind: 'contact_offer',
          dh_algo: parts[0] || undefined,
          dh_pub_key: parts.slice(1).join(':') || undefined,
          geo_hint: geoHint,
        };
      }
      return { kind: 'contact_offer', dh_pub_key: base || undefined, geo_hint: geoHint };
    }
  } catch {
    return null;
  }

  try {
    if (text.startsWith('ACCESS_GRANTED:')) {
      const payload = JSON.parse(text.slice('ACCESS_GRANTED:'.length));
      const sharedAlias = String(payload?.shared_alias || '').trim();
      if (!sharedAlias) return null;
      return { kind: 'contact_accept', shared_alias: sharedAlias };
    }
  } catch {
    return null;
  }

  return null;
}

export function buildAccessGrantedMessage(sharedAlias: string): string {
  return buildContactAcceptMessage(sharedAlias);
}

export function parseAccessGrantedMessage(
  text: string,
): { shared_alias?: string } | null {
  const consent = parseDmConsentMessage(text);
  if (consent?.kind !== 'contact_accept' || !consent.shared_alias) return null;
  return { shared_alias: consent.shared_alias };
}

export function buildAliasRotateMessage(sharedAlias: string): string {
  return `ALIAS_ROTATE:${JSON.stringify({ shared_alias: sharedAlias })}`;
}

export function parseAliasRotateMessage(
  text: string,
): { shared_alias?: string } | null {
  try {
    if (!text.startsWith('ALIAS_ROTATE:')) return null;
    const payload = JSON.parse(text.slice('ALIAS_ROTATE:'.length));
    const sharedAlias = String(payload?.shared_alias || '').trim();
    if (!sharedAlias) return null;
    return { shared_alias: sharedAlias };
  } catch {
    return null;
  }
}

export function mergeAliasHistory(
  aliases: Array<string | undefined | null>,
  limit: number = 3,
): string[] {
  const unique = new Set<string>();
  const ordered: string[] = [];
  for (const alias of aliases) {
    const value = String(alias || '').trim();
    if (!value || unique.has(value)) continue;
    unique.add(value);
    ordered.push(value);
    if (ordered.length >= limit) break;
  }
  return ordered;
}

export function preferredDmPeerId(
  peerId: string,
  contact?: ContactAliasLike | null,
): string {
  const pendingAlias = String(contact?.pendingSharedAlias || '').trim();
  const graceUntil = Number(contact?.sharedAliasGraceUntil || 0);
  if (pendingAlias && graceUntil > 0 && Date.now() >= graceUntil) {
    return pendingAlias;
  }
  const sharedAlias = String(contact?.sharedAlias || '').trim();
  return sharedAlias || peerId;
}

export function allDmPeerIds(
  peerId: string,
  contact?: ContactAliasLike | null,
): string[] {
  const unique = new Set<string>();
  const sharedAlias = String(contact?.sharedAlias || '').trim();
  const pendingAlias = String(contact?.pendingSharedAlias || '').trim();
  if (pendingAlias) unique.add(pendingAlias);
  if (sharedAlias) unique.add(sharedAlias);
  for (const alias of contact?.previousSharedAliases || []) {
    const value = String(alias || '').trim();
    if (value) unique.add(value);
  }
  if (peerId) unique.add(peerId);
  return Array.from(unique);
}
