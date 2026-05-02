import type { WormholeGateKeyStatus, WormholeIdentity } from '@/mesh/wormholeIdentityClient';
import type { Contact, NodeIdentity } from '@/mesh/meshIdentity';
import type { SenderRecoveryState } from '@/mesh/requestSenderRecovery';

// ─── Domain types ────────────────────────────────────────────────────────────

export interface Gate {
  gate_id: string;
  display_name: string;
  description?: string;
  welcome?: string;
  creator: string;
  rules: { min_overall_rep?: number };
  message_count: number;
  fixed?: boolean;
  sort_order?: number;
}

export interface InfoNetMessage {
  event_id: string;
  event_type?: string;
  node_id?: string;
  message?: string;
  reply_to?: string;
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
    envelope_hash?: string;
    reply_to?: string;
  };
  destination?: string;
  channel?: string;
  priority?: string;
  gate?: string;
  timestamp: number;
  sequence?: number;
  signature?: string;
  public_key?: string;
  public_key_algo?: string;
  protocol_version?: string;
  ephemeral?: boolean;
  system_seed?: boolean;
  fixed_gate?: boolean;
  gate_envelope?: string;
  envelope_hash?: string;
}

export interface MeshtasticMessage {
  from: string;
  to?: string;
  text: string;
  region: string;
  root?: string;
  channel: string;
  timestamp: number | string;
}

export interface DMMessage {
  sender_id: string;
  ciphertext: string;
  timestamp: number;
  msg_id: string;
  delivery_class?: 'request' | 'shared';
  transport?: 'reticulum' | 'relay';
  request_contract_version?: string;
  sender_recovery_required?: boolean;
  sender_recovery_state?: SenderRecoveryState;
  plaintext?: string;
  sender_seal?: string;
  seal_verified?: boolean;
  seal_resolution_failed?: boolean;
}

export interface AccessRequest {
  sender_id: string;
  timestamp: number;
  dh_pub_key?: string;
  dh_algo?: string;
  geo_hint?: string;
  request_contract_version?: string;
  sender_recovery_required?: boolean;
  sender_recovery_state?: SenderRecoveryState;
}

export interface SenderPopup {
  userId: string;
  x: number;
  y: number;
  tab: Tab;
  publicKey?: string;
  publicKeyAlgo?: string;
}

export interface GateReplyContext {
  eventId: string;
  gateId: string;
  nodeId: string;
}

export type Tab = 'infonet' | 'meshtastic' | 'dms';
export type DMView = 'contacts' | 'inbox' | 'chat' | 'muted';
export type DmTransportMode = 'reticulum' | 'relay' | 'ready' | 'hidden' | 'degraded' | 'blocked';

// ─── Constants ───────────────────────────────────────────────────────────────

export const DEFAULT_MESH_ROOTS = [
  'US',
  'EU_868',
  'EU_433',
  'CN',
  'JP',
  'KR',
  'TW',
  'RU',
  'IN',
  'ANZ',
  'ANZ_433',
  'NZ_865',
  'TH',
  'UA_868',
  'UA_433',
  'MY_433',
  'MY_919',
  'SG_923',
  'LORA_24',
  'EU',
  'AU',
  'UA',
  'BR',
  'AF',
  'ME',
  'SEA',
  'SA',
  'PL',
] as const;

export const MSG_COLORS = ['text-cyan-300', 'text-[#ff69b4]', 'text-yellow-300', 'text-gray-200'];

export const DM_UNREAD_POLL_EXPANDED_MS = 15_000;
export const DM_UNREAD_POLL_EXPANDED_JITTER_MS = 2_500;
export const DM_UNREAD_POLL_COLLAPSED_MS = 60_000;
export const DM_UNREAD_POLL_COLLAPSED_JITTER_MS = 10_000;
export const GATE_MESSAGES_POLL_MS = 30_000;
export const GATE_MESSAGES_POLL_JITTER_MS = 6_000;
export const GATE_ACTIVITY_REFRESH_MS = 7_000;
export const GATE_ACTIVITY_REFRESH_JITTER_MS = 2_500;
export const DM_MESSAGES_POLL_MS = 10_000;
export const DM_MESSAGES_POLL_JITTER_MS = 2_000;
export const DM_DECOY_POLL_MS = 210_000;
export const DM_DECOY_POLL_JITTER_MS = 90_000;
export const ACCESS_REQUEST_BATCH_DELAY_MS = 1_400;
export const ACCESS_REQUEST_BATCH_JITTER_MS = 900;
export const SHARED_ALIAS_ROTATE_MS = 6 * 60 * 60 * 1000;
export const SHARED_ALIAS_GRACE_MS = 45_000;

export const GATE_DECRYPT_CACHE_MAX = 256;
export const INFO_VERIFICATION_CACHE_MAX = 512;

// ─── Props ───────────────────────────────────────────────────────────────────

export interface MeshChatProps {
  onFlyTo?: (lat: number, lng: number) => void;
  expanded?: boolean;
  onExpandedChange?: (expanded: boolean) => void;
  onSettingsClick?: () => void;
  onTerminalToggle?: () => void;
  launchRequest?: { tab: Tab; gate?: string; peerId?: string; showSas?: boolean; nonce: number } | null;
}

// Re-export upstream types for convenience
export type { Contact, NodeIdentity, WormholeGateKeyStatus, WormholeIdentity, SenderRecoveryState };
