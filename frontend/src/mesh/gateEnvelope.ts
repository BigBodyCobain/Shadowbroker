export interface GateEnvelopeMessageLike {
  event_type?: string;
  gate?: string;
  message?: string;
  ciphertext?: string;
  epoch?: number;
  nonce?: string;
  sender_ref?: string;
  format?: string;
  decrypted_message?: string;
  payload?: {
    gate?: string;
    ciphertext?: string;
    nonce?: string;
    sender_ref?: string;
    format?: string;
  };
}

export type GateEnvelopeState = 'plaintext' | 'decrypted' | 'locked';

function _field(message: GateEnvelopeMessageLike, key: 'gate' | 'ciphertext' | 'nonce' | 'sender_ref' | 'format'): string {
  const payload = message.payload;
  const nested = payload && typeof payload === 'object' ? payload[key] : '';
  const direct = message[key];
  return String((direct ?? nested ?? '') || '');
}

export function isEncryptedGateEnvelope(message: GateEnvelopeMessageLike): boolean {
  return (
    String(message.event_type ?? '') === 'gate_message' &&
    !!_field(message, 'ciphertext').trim() &&
    (_field(message, 'format') || 'mls1') === 'mls1'
  );
}

export function gateEnvelopeDisplayText(message: GateEnvelopeMessageLike): string {
  if (!isEncryptedGateEnvelope(message)) {
    return String(message.message ?? '');
  }
  const decrypted = String(message.decrypted_message ?? '').trim();
  return decrypted || 'ENCRYPTED GATE MESSAGE - KEY UNAVAILABLE';
}

export function gateEnvelopeState(message: GateEnvelopeMessageLike): GateEnvelopeState {
  if (!isEncryptedGateEnvelope(message)) {
    return 'plaintext';
  }
  return String(message.decrypted_message ?? '').trim() ? 'decrypted' : 'locked';
}
