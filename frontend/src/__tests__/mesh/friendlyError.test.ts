import { describe, expect, it } from 'vitest';

import { friendlyInfonetError } from '@/mesh/friendlyError';

describe('friendlyInfonetError', () => {
  it('maps transport and wormhole codes to a warmup message', () => {
    for (const code of [
      'wormhole_required_for_gate_compose',
      'hidden transport required for infonet posting',
      'dm send requires private transport',
    ]) {
      expect(friendlyInfonetError(code)).toMatch(/private connection is still starting/);
    }
  });

  it('maps control plane status codes', () => {
    expect(friendlyInfonetError('control_plane_request_failed:403')).toMatch(/only available on the computer/);
    expect(friendlyInfonetError(new Error('Failed to fetch'))).toMatch(/Could not reach/);
    expect(friendlyInfonetError('control_plane_rate_limited')).toMatch(/Wait a few seconds/);
  });

  it('warns about changed contact keys', () => {
    expect(friendlyInfonetError('contact trust state does not allow gate keys: mismatch')).toMatch(
      /security keys changed/,
    );
    expect(friendlyInfonetError('remote prekey changed — verify before sending')).toMatch(/safety codes/);
  });

  it('keeps unknown machine codes for support but wraps them in a sentence', () => {
    expect(friendlyInfonetError('weird_new_failure', 'Could not post.')).toBe('Could not post. (weird_new_failure)');
  });

  it('passes ordinary sentences through and falls back on empty input', () => {
    expect(friendlyInfonetError('Write a message first.')).toBe('Write a message first.');
    expect(friendlyInfonetError('', 'Nope.')).toBe('Nope.');
    expect(friendlyInfonetError(undefined)).toBe('Something went wrong. Try again.');
  });
});
