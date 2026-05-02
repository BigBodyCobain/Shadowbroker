import { describe, expect, it } from 'vitest';

import {
  describeNativeControlError,
  extractNativeGateResyncTarget,
  extractGateTargetRef,
} from '../../lib/desktopControlContract';

describe('extractGateTargetRef', () => {
  it('extracts gate_id from gate key rotation payload', () => {
    expect(
      extractGateTargetRef('wormhole.gate.key.rotate', { gate_id: 'infonet', reason: 'test' }),
    ).toBe('infonet');
  });

  it('extracts gate_id from gate message compose payload', () => {
    expect(
      extractGateTargetRef('wormhole.gate.message.compose', { gate_id: 'ops', plaintext: 'hi' }),
    ).toBe('ops');
  });

  it('extracts gate_id from gate proof payload', () => {
    expect(extractGateTargetRef('wormhole.gate.proof', { gate_id: 'alpha' })).toBe('alpha');
  });

  it('extracts gate_id from gate state resync payload', () => {
    expect(extractGateTargetRef('wormhole.gate.state.resync', { gate_id: 'alpha' })).toBe(
      'alpha',
    );
  });

  it('extracts gate_id from gate message post payload', () => {
    expect(
      extractGateTargetRef('wormhole.gate.message.post', { gate_id: 'ops', plaintext: 'hi' }),
    ).toBe('ops');
  });

  it('extracts gate_id from gate persona list payload', () => {
    expect(
      extractGateTargetRef('wormhole.gate.personas.get', { gate_id: 'alpha' }),
    ).toBe('alpha');
  });

  it('returns undefined for non-gate commands', () => {
    expect(extractGateTargetRef('wormhole.status', undefined)).toBeUndefined();
    expect(extractGateTargetRef('settings.news.get', undefined)).toBeUndefined();
  });

  it('returns undefined when payload has no gate_id', () => {
    expect(extractGateTargetRef('wormhole.gate.key.rotate', { reason: 'test' })).toBeUndefined();
    expect(extractGateTargetRef('wormhole.gate.key.rotate', null)).toBeUndefined();
    expect(extractGateTargetRef('wormhole.gate.key.rotate', 'not-an-object')).toBeUndefined();
  });

  it('returns undefined when gate_id is empty string', () => {
    expect(extractGateTargetRef('wormhole.gate.key.get', { gate_id: '' })).toBeUndefined();
  });
});

describe('describeNativeControlError', () => {
  it('describes profile mismatch errors', () => {
    const err = new Error('native_control_profile_mismatch:settings_only:wormhole_gate_key');
    const msg = describeNativeControlError(err);
    expect(msg).toContain('Denied');
    expect(msg).toContain('session profile');
  });

  it('describes capability denied errors', () => {
    const err = new Error('native_control_capability_denied:wormhole_gate_key');
    const msg = describeNativeControlError(err);
    expect(msg).toContain('Denied');
    expect(msg).toContain('capability');
  });

  it('describes capability mismatch errors', () => {
    const err = new Error('native_control_capability_mismatch:wormhole_gate_content:wormhole_gate_key');
    const msg = describeNativeControlError(err);
    expect(msg).toContain('Denied');
    expect(msg).toContain('capability');
  });

  it('describes shim enforcement inactivity errors', () => {
    const err = new Error('desktop_runtime_shim_enforcement_inactive');
    const msg = describeNativeControlError(err);
    expect(msg).toContain('Denied');
    expect(msg).toContain('native runtime');
  });

  it('returns null for unrelated errors', () => {
    expect(describeNativeControlError(new Error('network_error'))).toBeNull();
    expect(describeNativeControlError('some string')).toBeNull();
    expect(describeNativeControlError(null)).toBeNull();
    expect(describeNativeControlError(undefined)).toBeNull();
  });

  it('describes native gate resync requirement errors', () => {
    expect(
      describeNativeControlError('native_gate_state_resync_required:ops'),
    ).toContain('gate resync');
  });

  it('handles plain string errors', () => {
    expect(
      describeNativeControlError('native_control_profile_mismatch:foo'),
    ).toContain('Denied');
  });
});

describe('extractNativeGateResyncTarget', () => {
  it('extracts the gate id from native resync-required errors', () => {
    expect(extractNativeGateResyncTarget('native_gate_state_resync_required:ops')).toBe('ops');
    expect(extractNativeGateResyncTarget(new Error('native_gate_state_resync_required:infonet'))).toBe(
      'infonet',
    );
  });

  it('returns null for unrelated errors', () => {
    expect(extractNativeGateResyncTarget(new Error('network_error'))).toBeNull();
    expect(extractNativeGateResyncTarget('native_control_profile_mismatch:foo')).toBeNull();
    expect(extractNativeGateResyncTarget(null)).toBeNull();
  });
});
