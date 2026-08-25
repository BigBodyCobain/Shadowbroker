/**
 * voiceTypes — TS contracts for the voice agent consumed by all frontend code;
 * the backend implements to these (voice-agent plan §5.5 / §4.3).
 *
 * Cost math is server-authoritative: the client renders VoiceUsageEvent
 * snapshots only and enforces nothing locally except disabling input on
 * level === 'cap'.
 */

export type VoicePhase =
  | 'opt-in-required'
  | 'lean-unavailable'
  | 'idle'
  | 'connecting'
  | 'listening'
  | 'thinking'
  | 'speaking'
  | 'error'
  | 'quota-capped';

export interface VoiceStatusResponse {
  ok: true;
  /** voice_outbound_effective() — requested AND acknowledged. */
  effectiveEnable: boolean;
  opt_in_state: 'not_requested' | 'requested_not_acknowledged' | 'enabled';
  flags: { enableSet: boolean; acknowledgeSet: boolean };
  provider: {
    resolved: 'openai_realtime' | 'compatible_ws' | 'local_text' | null;
    requestedMode: string;
    openaiKeySet: boolean;
    compatKeySet: boolean;
    compatBaseUrlSet: boolean;
    chatModelConfigured: boolean;
  };
  /** Verbatim-honest degradation reason, shown as-is. */
  degradedReason: string | null;
  reasons: string[];
  mode: 'full' | 'mesh_lean';
  costDefaults: { warnUsd: number | 'off'; capUsd: number | 'off'; dailyBudgetUsd: number | 'off' };
  dailySpend: {
    date: string;
    usdSpent: number;
    budgetUsd: number | 'off';
    remainingUsd: number | 'off';
    ledgerQuarantined: boolean;
  };
  activeSessions: number;
  maxConcurrent: number;
}

export interface VoiceSessionGrant {
  session_id: string;
  channel: { type: 'ws'; url: string };
  model_label: string;
  rates_recognized: boolean;
  expires_at: string;
}

export interface VoiceTurn {
  id: string;
  role: 'operator' | 'agent';
  kind: 'speech' | 'text' | 'tool';
  text: string;
  ts: number;
  tool?: {
    name: string;
    args_summary: string;
    ok: boolean;
    /** Verbatim failure detail — only rendered when ok is false. */
    detail: string;
  };
}

export interface HudSummary {
  generated_at: string;
  layers_version: number;
  headline: string;
  bullets: string[];
  freshness: Array<{ layer: string; age_s: number | null; disposition: 'live' | 'aging' | 'stale' | 'unknown' }>;
  grounding_scope: string;
}

export interface VoiceUsageEvent {
  total_usd: number;
  display: string;
  level: 'ok' | 'warn' | 'cap';
  note: string | null;
  incomplete?: boolean;
  /** Tier-2 estimate: provider did not report usage — billed from audio seconds. */
  estimated?: boolean;
  /** False ⇒ worst-case rate table billed; surfaces the `*` + tooltip (§5.5). */
  ratesRecognized?: boolean;
}
