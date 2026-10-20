import { describe, expect, it } from 'vitest';

import {
  isLikelyDmShortAddress,
  parseDmInviteImportBlob,
  inviteFromParsedBlob,
} from '@/mesh/dmConnect';

describe('dmConnect', () => {
  it('detects short lookup handles', () => {
    expect(isLikelyDmShortAddress('5881eb8705c9abc1234567890abcd')).toBe(true);
    expect(isLikelyDmShortAddress('{"type":"invite"}')).toBe(false);
  });

  it('parses short address without JSON', () => {
    const parsed = parseDmInviteImportBlob('abcd1234ef567890abcd1234ef567890');
    expect(parsed.short_address).toBe('abcd1234ef567890abcd1234ef567890');
  });

  it('unwraps nested invite objects', () => {
    const invite = { event_type: 'dm_invite', payload: {} };
    const parsed = inviteFromParsedBlob({ invite, version: 1 });
    expect(parsed).toEqual(invite);
  });
});
