export const DESKTOP_CONTROL_COMMANDS = [
  'wormhole.status',
  'wormhole.connect',
  'wormhole.disconnect',
  'wormhole.restart',
  'wormhole.gate.enter',
  'wormhole.gate.leave',
  'wormhole.gate.personas.get',
  'wormhole.gate.persona.create',
  'wormhole.gate.persona.activate',
  'wormhole.gate.persona.clear',
  'wormhole.gate.key.get',
  'wormhole.gate.key.rotate',
  'wormhole.gate.proof',
  'wormhole.gate.message.compose',
  'wormhole.gate.message.post',
  'wormhole.gate.message.decrypt',
  'wormhole.gate.messages.decrypt',
  'settings.wormhole.get',
  'settings.wormhole.set',
  'settings.privacy.get',
  'settings.privacy.set',
  'settings.api_keys.get',
  'settings.api_keys.set',
  'settings.news.get',
  'settings.news.set',
  'settings.news.reset',
  'system.update',
] as const;

export type DesktopControlCommand = (typeof DESKTOP_CONTROL_COMMANDS)[number];
export type DesktopControlCapability =
  | 'wormhole_gate_persona'
  | 'wormhole_gate_key'
  | 'wormhole_gate_content'
  | 'wormhole_runtime'
  | 'settings';
export type DesktopControlSessionProfile =
  | 'full_app'
  | 'gate_observe'
  | 'gate_operator'
  | 'wormhole_runtime'
  | 'settings_only';
export type DesktopControlAuditOutcome =
  | 'allowed'
  | 'profile_warn'
  | 'profile_denied'
  | 'capability_denied'
  | 'capability_mismatch'
  | 'shim_refused';

export interface DesktopWormholeSettingsPayload {
  enabled: boolean;
  transport: string;
  socks_proxy: string;
  socks_dns: boolean;
  anonymous_mode: boolean;
}

export interface DesktopGateRequestPayload {
  gate_id: string;
  rotate?: boolean;
}

export interface DesktopGatePersonaCreatePayload {
  gate_id: string;
  label: string;
}

export interface DesktopGatePersonaActivatePayload {
  gate_id: string;
  persona_id: string;
}

export interface DesktopGateRotatePayload {
  gate_id: string;
  reason: string;
}

export interface DesktopGateComposePayload {
  gate_id: string;
  plaintext: string;
}

export interface DesktopGateDecryptPayload {
  gate_id: string;
  epoch: number;
  ciphertext: string;
  nonce: string;
  sender_ref: string;
}

export interface DesktopGateDecryptBatchPayload {
  messages: DesktopGateDecryptPayload[];
}

export interface DesktopPrivacySettingsPayload {
  profile: string;
}

export interface DesktopApiKeyPayload {
  env_key: string;
  value: string;
}

export interface DesktopNewsFeedPayload {
  name: string;
  url: string;
  weight: number;
}

export interface DesktopControlPayloadMap {
  'wormhole.status': undefined;
  'wormhole.connect': undefined;
  'wormhole.disconnect': undefined;
  'wormhole.restart': undefined;
  'wormhole.gate.enter': DesktopGateRequestPayload;
  'wormhole.gate.leave': DesktopGateRequestPayload;
  'wormhole.gate.personas.get': DesktopGateRequestPayload;
  'wormhole.gate.persona.create': DesktopGatePersonaCreatePayload;
  'wormhole.gate.persona.activate': DesktopGatePersonaActivatePayload;
  'wormhole.gate.persona.clear': DesktopGateRequestPayload;
  'wormhole.gate.key.get': DesktopGateRequestPayload;
  'wormhole.gate.key.rotate': DesktopGateRotatePayload;
  'wormhole.gate.proof': DesktopGateRequestPayload;
  'wormhole.gate.message.compose': DesktopGateComposePayload;
  'wormhole.gate.message.post': DesktopGateComposePayload;
  'wormhole.gate.message.decrypt': DesktopGateDecryptPayload;
  'wormhole.gate.messages.decrypt': DesktopGateDecryptBatchPayload;
  'settings.wormhole.get': undefined;
  'settings.wormhole.set': DesktopWormholeSettingsPayload;
  'settings.privacy.get': undefined;
  'settings.privacy.set': DesktopPrivacySettingsPayload;
  'settings.api_keys.get': undefined;
  'settings.api_keys.set': DesktopApiKeyPayload;
  'settings.news.get': undefined;
  'settings.news.set': DesktopNewsFeedPayload[];
  'settings.news.reset': undefined;
  'system.update': undefined;
}

export type DesktopControlResponseMap = {
  [K in DesktopControlCommand]: unknown;
};

export function controlCommandCapability(
  command: DesktopControlCommand,
): DesktopControlCapability {
  switch (command) {
    case 'wormhole.status':
    case 'wormhole.connect':
    case 'wormhole.disconnect':
    case 'wormhole.restart':
      return 'wormhole_runtime';
    case 'wormhole.gate.enter':
    case 'wormhole.gate.leave':
    case 'wormhole.gate.personas.get':
    case 'wormhole.gate.persona.create':
    case 'wormhole.gate.persona.activate':
    case 'wormhole.gate.persona.clear':
      return 'wormhole_gate_persona';
    case 'wormhole.gate.key.get':
    case 'wormhole.gate.key.rotate':
      return 'wormhole_gate_key';
    case 'wormhole.gate.proof':
    case 'wormhole.gate.message.compose':
    case 'wormhole.gate.message.post':
    case 'wormhole.gate.message.decrypt':
    case 'wormhole.gate.messages.decrypt':
      return 'wormhole_gate_content';
    case 'settings.wormhole.get':
    case 'settings.wormhole.set':
    case 'settings.privacy.get':
    case 'settings.privacy.set':
    case 'settings.api_keys.get':
    case 'settings.api_keys.set':
    case 'settings.news.get':
    case 'settings.news.set':
    case 'settings.news.reset':
    case 'system.update':
      return 'settings';
  }
}

export function sessionProfileCapabilities(
  profile: DesktopControlSessionProfile,
): DesktopControlCapability[] {
  switch (profile) {
    case 'full_app':
      return [
        'wormhole_gate_persona',
        'wormhole_gate_key',
        'wormhole_gate_content',
        'wormhole_runtime',
        'settings',
      ];
    case 'gate_observe':
      return ['wormhole_gate_content'];
    case 'gate_operator':
      return ['wormhole_gate_persona', 'wormhole_gate_key', 'wormhole_gate_content'];
    case 'wormhole_runtime':
      return ['wormhole_runtime'];
    case 'settings_only':
      return ['settings'];
  }
}

export type LocalControlInvokeMeta = {
  capability?: DesktopControlCapability;
  sessionProfileHint?: DesktopControlSessionProfile;
  enforceProfileHint?: boolean;
};

export type DesktopControlAuditEvent = {
  command: DesktopControlCommand;
  expectedCapability: DesktopControlCapability;
  declaredCapability?: DesktopControlCapability;
  targetRef?: string;
  sessionProfile?: DesktopControlSessionProfile;
  sessionProfileHint?: DesktopControlSessionProfile;
  enforceProfileHint?: boolean;
  profileAllows: boolean;
  allowedCapabilitiesConfigured: boolean;
  enforced: boolean;
  outcome: DesktopControlAuditOutcome;
};

export type DesktopControlAuditRecord = DesktopControlAuditEvent & {
  recordedAt: number;
};

export type DesktopControlAuditReport = {
  totalEvents: number;
  totalRecorded: number;
  recent: DesktopControlAuditRecord[];
  byOutcome: Partial<Record<DesktopControlAuditOutcome, number>>;
  lastProfileMismatch?: DesktopControlAuditRecord;
  lastDenied?: DesktopControlAuditRecord;
};

export type LocalControlInvokeRequest<C extends DesktopControlCommand = DesktopControlCommand> =
  DesktopControlPayloadMap[C] extends undefined
    ? { command: C; payload?: undefined; meta?: LocalControlInvokeMeta }
    : { command: C; payload: DesktopControlPayloadMap[C]; meta?: LocalControlInvokeMeta };

export function isDesktopControlCommand(value: string): value is DesktopControlCommand {
  return (DESKTOP_CONTROL_COMMANDS as readonly string[]).includes(value);
}

export function describeNativeControlError(err: unknown): string | null {
  const msg =
    typeof err === 'object' && err !== null && 'message' in err
      ? String((err as { message?: string }).message || '')
      : typeof err === 'string'
        ? err
        : '';
  if (msg.includes('native_control_profile_mismatch')) {
    return 'Denied — current native session profile does not include the required access';
  }
  if (msg.includes('native_control_capability_denied')) {
    return 'Denied — this capability is not in the allowed set for this native session';
  }
  if (msg.includes('native_control_capability_mismatch')) {
    return 'Denied — declared capability does not match the command being invoked';
  }
  if (msg.includes('desktop_runtime_shim_enforcement_inactive')) {
    return 'Denied — this command requires a native runtime with session-profile enforcement';
  }
  return null;
}

export function extractGateTargetRef(
  command: DesktopControlCommand,
  payload: unknown,
): string | undefined {
  if (!payload || typeof payload !== 'object') return undefined;
  const gateId = (payload as Record<string, unknown>).gate_id;
  if (typeof gateId !== 'string' || !gateId) return undefined;
  switch (command) {
    case 'wormhole.gate.enter':
    case 'wormhole.gate.leave':
    case 'wormhole.gate.personas.get':
    case 'wormhole.gate.persona.create':
    case 'wormhole.gate.persona.activate':
    case 'wormhole.gate.persona.clear':
    case 'wormhole.gate.key.get':
    case 'wormhole.gate.key.rotate':
    case 'wormhole.gate.proof':
    case 'wormhole.gate.message.compose':
    case 'wormhole.gate.message.post':
    case 'wormhole.gate.message.decrypt':
      return gateId;
    default:
      return undefined;
  }
}
