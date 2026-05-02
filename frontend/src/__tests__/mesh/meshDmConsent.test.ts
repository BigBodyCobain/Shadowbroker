import { describe, expect, it } from 'vitest';

import {
  allDmPeerIds,
  mailboxPeerRefs,
  buildAliasRotateMessage,
  buildAccessGrantedMessage,
  buildContactAcceptMessage,
  buildContactDenyMessage,
  buildContactOfferMessage,
  mergeAliasHistory,
  parseAliasRotateMessage,
  parseAccessGrantedMessage,
  parseDmConsentMessage,
  preferredDmPeerId,
} from '@/mesh/meshDmConsent';

describe('mesh DM consent helpers', () => {
  it('builds and parses access-granted payloads', () => {
    const message = buildAccessGrantedMessage('dmx_alpha');
    expect(parseAccessGrantedMessage(message)).toEqual({ shared_alias: 'dmx_alpha' });
  });

  it('builds and parses off-ledger contact offer payloads', () => {
    const message = buildContactOfferMessage('dh_pub', 'X25519', '40.12,-105.27');
    expect(parseDmConsentMessage(message)).toEqual({
      kind: 'contact_offer',
      dh_pub_key: 'dh_pub',
      dh_algo: 'X25519',
      geo_hint: '40.12,-105.27',
    });
  });

  it('builds and parses off-ledger contact accept payloads', () => {
    const message = buildContactAcceptMessage('dmx_pairwise');
    expect(parseDmConsentMessage(message)).toEqual({
      kind: 'contact_accept',
      shared_alias: 'dmx_pairwise',
    });
  });

  it('builds and parses off-ledger contact deny payloads', () => {
    const message = buildContactDenyMessage('declined');
    expect(parseDmConsentMessage(message)).toEqual({
      kind: 'contact_deny',
      reason: 'declined',
    });
  });

  it('prefers the pairwise alias for shared DM routing', () => {
    expect(preferredDmPeerId('node_public', { sharedAlias: 'dmx_pairwise' })).toBe('dmx_pairwise');
    expect(preferredDmPeerId('node_public', { sharedAlias: '' })).toBe('node_public');
  });

  it('keeps both alias and public ids during the transition window', () => {
    expect(allDmPeerIds('node_public', { sharedAlias: 'dmx_pairwise' })).toEqual([
      'dmx_pairwise',
      'node_public',
    ]);
    expect(allDmPeerIds('node_public', { sharedAlias: 'node_public' })).toEqual(['node_public']);
  });

  it('prefers alias history for mailbox refs and drops stable public id once aliasing exists', () => {
    expect(
      mailboxPeerRefs('node_public', {
        sharedAlias: 'dmx_current',
        pendingSharedAlias: 'dmx_next',
        previousSharedAliases: ['dmx_prev'],
      }),
    ).toEqual(['dmx_current', 'dmx_next', 'dmx_prev']);
    expect(mailboxPeerRefs('node_public', { sharedAlias: '' })).toEqual(['node_public']);
  });

  it('builds and parses alias rotation control payloads', () => {
    const message = buildAliasRotateMessage('dmx_next');
    expect(parseAliasRotateMessage(message)).toEqual({ shared_alias: 'dmx_next' });
  });

  it('promotes pending alias after the grace window elapses', () => {
    const now = Date.now();
    expect(
      preferredDmPeerId('node_public', {
        sharedAlias: 'dmx_current',
        pendingSharedAlias: 'dmx_next',
        sharedAliasGraceUntil: now - 1,
      }),
    ).toBe('dmx_next');
  });

  it('keeps alias history compact and unique', () => {
    expect(mergeAliasHistory(['dmx_a', 'dmx_b', 'dmx_a', 'dmx_c', 'dmx_d'])).toEqual([
      'dmx_a',
      'dmx_b',
    ]);
    expect(mergeAliasHistory(['dmx_a', 'dmx_b', 'dmx_a', 'dmx_c', 'dmx_d'], 3)).toEqual([
      'dmx_a',
      'dmx_b',
      'dmx_c',
    ]);
  });

  it('bounds mailbox peer refs to 4 and excludes long tail', () => {
    expect(
      mailboxPeerRefs('node_public', {
        sharedAlias: 'dmx_current',
        pendingSharedAlias: 'dmx_next',
        previousSharedAliases: ['dmx_prev1', 'dmx_prev2', 'dmx_prev3'],
      }),
    ).toEqual(['dmx_current', 'dmx_next', 'dmx_prev1', 'dmx_prev2']);
  });

  it('bounds allDmPeerIds previous alias enumeration to 2', () => {
    const ids = allDmPeerIds('node_public', {
      sharedAlias: 'dmx_current',
      pendingSharedAlias: 'dmx_next',
      previousSharedAliases: ['dmx_prev1', 'dmx_prev2', 'dmx_prev3'],
    });
    // current + pending + at most 2 previous + peerId
    expect(ids).toContain('dmx_current');
    expect(ids).toContain('dmx_next');
    expect(ids).toContain('dmx_prev1');
    expect(ids).toContain('dmx_prev2');
    expect(ids).not.toContain('dmx_prev3');
  });
});
