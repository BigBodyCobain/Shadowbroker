import type { GateCatalogEntry } from '@/mesh/gateCatalogSnapshot';
import type { Gate } from './types';

export function gateCatalogEntryToGate(entry: GateCatalogEntry): Gate {
  return {
    gate_id: String(entry.gate_id || '').trim().toLowerCase(),
    display_name: entry.display_name || entry.gate_id,
    description: entry.description,
    creator: '',
    rules: entry.rules || {},
    message_count: entry.message_count ?? 0,
    fixed: entry.fixed,
  };
}

export interface GateCompatConsentPromptState {
  gateId: string;
  action: 'compose' | 'post' | 'decrypt';
  reason: string;
}

export interface MeshMqttRuntime {
  enabled?: boolean;
  running?: boolean;
  connected?: boolean;
  broker?: string;
  port?: number;
  username?: string;
  client_id?: string;
  message_log_size?: number;
  signal_log_size?: number;
  last_error?: string;
  last_connected_at?: number;
  last_disconnected_at?: number;
}

export interface MeshMqttSettings {
  enabled: boolean;
  broker: string;
  port: number;
  username: string;
  uses_default_credentials?: boolean;
  has_password: boolean;
  has_psk: boolean;
  include_default_roots: boolean;
  extra_roots: string;
  extra_topics: string;
  runtime?: MeshMqttRuntime;
}

export interface MeshMqttForm {
  broker: string;
  port: string;
  username: string;
  password: string;
  psk: string;
  include_default_roots: boolean;
  extra_roots: string;
  extra_topics: string;
}

export const PUBLIC_MESH_ADDRESS_KEY = 'sb_public_meshtastic_address';

export function normalizePublicMeshAddress(value: string): string {
  const raw = String(value || '').trim().toLowerCase();
  const body = raw.startsWith('!') ? raw.slice(1) : raw;
  if (!/^[0-9a-f]{8}$/.test(body)) return '';
  return `!${body}`;
}

export function readStoredPublicMeshAddress(): string {
  if (typeof window === 'undefined') return '';
  try {
    return normalizePublicMeshAddress(window.localStorage.getItem(PUBLIC_MESH_ADDRESS_KEY) || '');
  } catch {
    return '';
  }
}

export function writeStoredPublicMeshAddress(address: string): void {
  if (typeof window === 'undefined') return;
  const normalized = normalizePublicMeshAddress(address);
  if (!normalized) return;
  try {
    window.localStorage.setItem(PUBLIC_MESH_ADDRESS_KEY, normalized);
  } catch {
    /* ignore */
  }
}

export function clearStoredPublicMeshAddress(): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.removeItem(PUBLIC_MESH_ADDRESS_KEY);
  } catch {
    /* ignore */
  }
}

export function createPublicMeshAddress(): string {
  if (typeof window !== 'undefined' && window.crypto?.getRandomValues) {
    const value = new Uint32Array(1);
    window.crypto.getRandomValues(value);
    if (value[0]) return `!${value[0].toString(16).padStart(8, '0')}`;
  }
  const fallback = Math.floor((Date.now() ^ Math.floor(Math.random() * 0xffffffff)) >>> 0);
  return `!${fallback.toString(16).padStart(8, '0')}`;
}

export function errorMessage(err: unknown, fallback: string = 'unknown error'): string {
  if (err instanceof Error && err.message) return err.message;
  if (typeof err === 'string' && err.trim()) return err.trim();
  if (typeof err === 'object' && err !== null && 'message' in err) {
    const message = String((err as { message?: unknown }).message || '').trim();
    if (message) return message;
  }
  return fallback;
}

export function describeMeshChatControlError(raw: string): string {
  const message = String(raw || '').trim();
  if (!message) return 'Meshtastic Chat could not update the local control plane.';
  if (
    message === 'control_plane_request_failed:530' ||
    message === 'HTTP 530' ||
    message.includes('control_plane_request_failed:530')
  ) {
    return 'The local control plane did not complete the lane switch. Check that the backend is running and reachable, then try Mesh again.';
  }
  if (
    message === 'control_plane_request_failed:502' ||
    message === 'HTTP 502' ||
    /Backend unavailable/i.test(message)
  ) {
    return 'The frontend cannot reach the backend right now. Start or restart the backend, then try Mesh again.';
  }
  if (message === 'admin_session_required' || /local operator access only/i.test(message)) {
    return 'This control action needs a local operator session. Open Settings or Node controls once so the app can authorize local changes, then try Mesh again.';
  }
  if (message.startsWith('{') || message.startsWith('<')) {
    return 'Meshtastic Chat could not update the local control plane. Check the backend log for the upstream error.';
  }
  return message;
}

export function describeGateCompatConsentRequired(): string {
  return 'Local gate runtime is unavailable for this room.';
}

export function describeGateLocalRuntimeRequired(detail: string, gateId: string = ''): string {
  const normalized = String(detail || '').trim();
  if (normalized === 'gate_compat_fallback_consent_required') {
    return describeGateCompatConsentRequired();
  }
  if (!normalized.startsWith('gate_local_runtime_required:')) {
    return normalized;
  }
  const reason = normalized.slice('gate_local_runtime_required:'.length);
  const normalizedGate = String(gateId || '').trim().toLowerCase();
  if (!reason || reason === 'browser_local_gate_crypto_unavailable') {
    return 'Local gate runtime is unavailable for this room. Use native desktop or resync local gate state.';
  }
  if (reason === 'browser_gate_worker_unavailable') {
    return 'This runtime cannot keep gate crypto local. Use native desktop or resync local gate state.';
  }
  if (reason.startsWith('browser_gate_state_resync_required:')) {
    return normalizedGate
      ? `Local ${normalizedGate} state needs a resync on this device. Use native desktop or resync local gate state.`
      : 'Local gate state needs a resync on this device. Use native desktop or resync local gate state.';
  }
  if (
    reason.startsWith('browser_gate_state_mapping_missing_group:') ||
    reason === 'browser_gate_state_active_member_missing'
  ) {
    return 'Local gate state is incomplete on this device. Use native desktop or resync local gate state.';
  }
  if (reason === 'worker_gate_wrap_key_missing') {
    return 'Secure local gate storage is unavailable in this browser. Use native desktop or resync local gate state.';
  }
  if (reason === 'gate_mls_decrypt_failed') {
    return 'Local gate decrypt failed on this device. Use native desktop or resync local gate state.';
  }
  return 'Local gate runtime is unavailable for this room. Use native desktop or resync local gate state.';
}

// ─── Controller Hook ────────────────────────────────────────────────────────
