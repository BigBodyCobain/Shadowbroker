import { describe, expect, it } from 'vitest';

import {
  gateEnvelopeDisplayText,
  gateEnvelopeState,
  isEncryptedGateEnvelope,
} from '@/mesh/gateEnvelope';
import { normalizePayload } from '@/mesh/meshProtocol';
import { validateEventPayload } from '@/mesh/meshSchema';

describe('gate envelope protocol', () => {
  it('normalizes encrypted gate-message payloads', () => {
    expect(
      normalizePayload('gate_message', {
        gate: 'Finance',
        epoch: '2',
        ciphertext: 'opaque',
        nonce: 'nonce-2',
        sender_ref: 'persona-fin-1',
      }),
    ).toEqual({
      gate: 'finance',
      epoch: 2,
      ciphertext: 'opaque',
      nonce: 'nonce-2',
      sender_ref: 'persona-fin-1',
      format: 'g1',
    });
  });

  it('accepts encrypted gate-message envelopes and rejects plaintext ones', () => {
    expect(
      validateEventPayload('gate_message', {
        gate: 'finance',
        epoch: 2,
        ciphertext: 'opaque',
        nonce: 'nonce-2',
        sender_ref: 'persona-fin-1',
        format: 'g1',
      }),
    ).toEqual({ ok: true });

    expect(
      validateEventPayload('gate_message', {
        gate: 'finance',
        message: 'plaintext',
      }),
    ).toEqual({ ok: false, reason: 'Payload is not normalized' });
  });
});

describe('gate envelope display', () => {
  it('detects encrypted gate messages and shows placeholders honestly', () => {
    const encrypted = {
      event_type: 'gate_message',
      gate: 'finance',
      epoch: 2,
      ciphertext: 'opaque',
      nonce: 'nonce-2',
      sender_ref: 'persona-fin-1',
    };

    expect(isEncryptedGateEnvelope(encrypted)).toBe(true);
    expect(gateEnvelopeState(encrypted)).toBe('locked');
    expect(gateEnvelopeDisplayText(encrypted)).toBe('ENCRYPTED GATE MESSAGE - KEY UNAVAILABLE');
    expect(
      gateEnvelopeState({
        ...encrypted,
        decrypted_message: 'decoded text',
      }),
    ).toBe('decrypted');
    expect(
      gateEnvelopeDisplayText({
        ...encrypted,
        decrypted_message: 'decoded text',
      }),
    ).toBe('decoded text');
    expect(
      gateEnvelopeState({
        event_type: 'gate_notice',
        message: 'legacy plaintext',
      }),
    ).toBe('plaintext');
    expect(
      gateEnvelopeDisplayText({
        event_type: 'gate_notice',
        message: 'legacy plaintext',
      }),
    ).toBe('legacy plaintext');
  });
});
