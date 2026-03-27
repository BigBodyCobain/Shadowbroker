import type {
  DesktopApiKeyPayload,
  DesktopControlCommand,
  DesktopGateComposePayload,
  DesktopGateDecryptBatchPayload,
  DesktopGateDecryptPayload,
  DesktopGatePersonaActivatePayload,
  DesktopGatePersonaCreatePayload,
  DesktopGateRequestPayload,
  DesktopGateRotatePayload,
  DesktopNewsFeedPayload,
  DesktopPrivacySettingsPayload,
  DesktopWormholeSettingsPayload,
  LocalControlInvokeRequest,
} from '@/lib/desktopControlContract';

export type DesktopControlHttpRequest = {
  path: string;
  method: string;
  payload?:
    | DesktopWormholeSettingsPayload
    | DesktopPrivacySettingsPayload
    | DesktopApiKeyPayload
    | DesktopNewsFeedPayload[]
    | DesktopGateRequestPayload
    | DesktopGatePersonaCreatePayload
    | DesktopGatePersonaActivatePayload
    | DesktopGateRotatePayload
    | DesktopGateComposePayload
    | DesktopGateDecryptPayload
    | DesktopGateDecryptBatchPayload;
};

function parseJsonBody(bodyText?: string): unknown {
  if (!bodyText) return undefined;
  try {
    return JSON.parse(bodyText);
  } catch {
    return undefined;
  }
}

export function commandToHttpRequest(
  command: DesktopControlCommand,
  payload?: unknown,
): DesktopControlHttpRequest {
  switch (command) {
    case 'wormhole.status':
      return { path: '/api/wormhole/status', method: 'GET' };
    case 'wormhole.connect':
      return { path: '/api/wormhole/connect', method: 'POST' };
    case 'wormhole.disconnect':
      return { path: '/api/wormhole/disconnect', method: 'POST' };
    case 'wormhole.restart':
      return { path: '/api/wormhole/restart', method: 'POST' };
    case 'wormhole.gate.enter':
      return {
        path: '/api/wormhole/gate/enter',
        method: 'POST',
        payload: payload as DesktopGateRequestPayload,
      };
    case 'wormhole.gate.leave':
      return {
        path: '/api/wormhole/gate/leave',
        method: 'POST',
        payload: payload as DesktopGateRequestPayload,
      };
    case 'wormhole.gate.personas.get':
      return {
        path: `/api/wormhole/gate/${encodeURIComponent((payload as DesktopGateRequestPayload).gate_id)}/personas`,
        method: 'GET',
      };
    case 'wormhole.gate.persona.create':
      return {
        path: '/api/wormhole/gate/persona/create',
        method: 'POST',
        payload: payload as DesktopGatePersonaCreatePayload,
      };
    case 'wormhole.gate.persona.activate':
      return {
        path: '/api/wormhole/gate/persona/activate',
        method: 'POST',
        payload: payload as DesktopGatePersonaActivatePayload,
      };
    case 'wormhole.gate.persona.clear':
      return {
        path: '/api/wormhole/gate/persona/clear',
        method: 'POST',
        payload: payload as DesktopGateRequestPayload,
      };
    case 'wormhole.gate.key.get':
      return {
        path: `/api/wormhole/gate/${encodeURIComponent((payload as DesktopGateRequestPayload).gate_id)}/key`,
        method: 'GET',
      };
    case 'wormhole.gate.key.rotate':
      return {
        path: '/api/wormhole/gate/key/rotate',
        method: 'POST',
        payload: payload as DesktopGateRotatePayload,
      };
    case 'wormhole.gate.proof':
      return {
        path: '/api/wormhole/gate/proof',
        method: 'POST',
        payload: payload as DesktopGateRequestPayload,
      };
    case 'wormhole.gate.message.compose':
      return {
        path: '/api/wormhole/gate/message/compose',
        method: 'POST',
        payload: payload as DesktopGateComposePayload,
      };
    case 'wormhole.gate.message.post':
      return {
        path: '/api/wormhole/gate/message/post',
        method: 'POST',
        payload: payload as DesktopGateComposePayload,
      };
    case 'wormhole.gate.message.decrypt':
      return {
        path: '/api/wormhole/gate/message/decrypt',
        method: 'POST',
        payload: payload as DesktopGateDecryptPayload,
      };
    case 'wormhole.gate.messages.decrypt':
      return {
        path: '/api/wormhole/gate/messages/decrypt',
        method: 'POST',
        payload: payload as DesktopGateDecryptBatchPayload,
      };
    case 'settings.wormhole.get':
      return { path: '/api/settings/wormhole', method: 'GET' };
    case 'settings.wormhole.set':
      return { path: '/api/settings/wormhole', method: 'PUT', payload: payload as DesktopWormholeSettingsPayload };
    case 'settings.privacy.get':
      return { path: '/api/settings/privacy-profile', method: 'GET' };
    case 'settings.privacy.set':
      return {
        path: '/api/settings/privacy-profile',
        method: 'PUT',
        payload: payload as DesktopPrivacySettingsPayload,
      };
    case 'settings.api_keys.get':
      return { path: '/api/settings/api-keys', method: 'GET' };
    case 'settings.api_keys.set':
      return { path: '/api/settings/api-keys', method: 'PUT', payload: payload as DesktopApiKeyPayload };
    case 'settings.news.get':
      return { path: '/api/settings/news-feeds', method: 'GET' };
    case 'settings.news.set':
      return { path: '/api/settings/news-feeds', method: 'PUT', payload: payload as DesktopNewsFeedPayload[] };
    case 'settings.news.reset':
      return { path: '/api/settings/news-feeds/reset', method: 'POST' };
    case 'system.update':
      return { path: '/api/system/update', method: 'POST' };
    default: {
      const exhaustive: never = command;
      throw new Error(`desktop_control_command_unsupported:${exhaustive}`);
    }
  }
}

export function httpRequestToInvokeRequest(
  path: string,
  method: string,
  bodyText?: string,
): LocalControlInvokeRequest | null {
  const payload = parseJsonBody(bodyText);
  const upperMethod = method.toUpperCase();
  if (upperMethod === 'GET' && path === '/api/wormhole/status') {
    return { command: 'wormhole.status', payload: undefined };
  }
  if (upperMethod === 'POST' && path === '/api/wormhole/connect') {
    return { command: 'wormhole.connect', payload: undefined };
  }
  if (upperMethod === 'POST' && path === '/api/wormhole/disconnect') {
    return { command: 'wormhole.disconnect', payload: undefined };
  }
  if (upperMethod === 'POST' && path === '/api/wormhole/restart') {
    return { command: 'wormhole.restart', payload: undefined };
  }
  if (upperMethod === 'POST' && path === '/api/wormhole/gate/enter') {
    return { command: 'wormhole.gate.enter', payload: payload as DesktopGateRequestPayload };
  }
  if (upperMethod === 'POST' && path === '/api/wormhole/gate/leave') {
    return { command: 'wormhole.gate.leave', payload: payload as DesktopGateRequestPayload };
  }
  if (upperMethod === 'GET' && /^\/api\/wormhole\/gate\/[^/]+\/personas$/.test(path)) {
    const gateId = decodeURIComponent(path.split('/')[4] || '');
    return { command: 'wormhole.gate.personas.get', payload: { gate_id: gateId } };
  }
  if (upperMethod === 'POST' && path === '/api/wormhole/gate/persona/create') {
    return { command: 'wormhole.gate.persona.create', payload: payload as DesktopGatePersonaCreatePayload };
  }
  if (upperMethod === 'POST' && path === '/api/wormhole/gate/persona/activate') {
    return { command: 'wormhole.gate.persona.activate', payload: payload as DesktopGatePersonaActivatePayload };
  }
  if (upperMethod === 'POST' && path === '/api/wormhole/gate/persona/clear') {
    return { command: 'wormhole.gate.persona.clear', payload: payload as DesktopGateRequestPayload };
  }
  if (upperMethod === 'GET' && /^\/api\/wormhole\/gate\/[^/]+\/key$/.test(path)) {
    const gateId = decodeURIComponent(path.split('/')[4] || '');
    return { command: 'wormhole.gate.key.get', payload: { gate_id: gateId } };
  }
  if (upperMethod === 'POST' && path === '/api/wormhole/gate/key/rotate') {
    return { command: 'wormhole.gate.key.rotate', payload: payload as DesktopGateRotatePayload };
  }
  if (upperMethod === 'POST' && path === '/api/wormhole/gate/proof') {
    return { command: 'wormhole.gate.proof', payload: payload as DesktopGateRequestPayload };
  }
  if (upperMethod === 'POST' && path === '/api/wormhole/gate/message/compose') {
    return { command: 'wormhole.gate.message.compose', payload: payload as DesktopGateComposePayload };
  }
  if (upperMethod === 'POST' && path === '/api/wormhole/gate/message/post') {
    return { command: 'wormhole.gate.message.post', payload: payload as DesktopGateComposePayload };
  }
  if (upperMethod === 'POST' && path === '/api/wormhole/gate/message/decrypt') {
    return { command: 'wormhole.gate.message.decrypt', payload: payload as DesktopGateDecryptPayload };
  }
  if (upperMethod === 'POST' && path === '/api/wormhole/gate/messages/decrypt') {
    return {
      command: 'wormhole.gate.messages.decrypt',
      payload: payload as DesktopGateDecryptBatchPayload,
    };
  }
  if (upperMethod === 'GET' && path === '/api/settings/wormhole') {
    return { command: 'settings.wormhole.get', payload: undefined };
  }
  if (upperMethod === 'PUT' && path === '/api/settings/wormhole') {
    return { command: 'settings.wormhole.set', payload: payload as DesktopWormholeSettingsPayload };
  }
  if (upperMethod === 'GET' && path === '/api/settings/privacy-profile') {
    return { command: 'settings.privacy.get', payload: undefined };
  }
  if (upperMethod === 'PUT' && path === '/api/settings/privacy-profile') {
    return { command: 'settings.privacy.set', payload: payload as DesktopPrivacySettingsPayload };
  }
  if (upperMethod === 'GET' && path === '/api/settings/api-keys') {
    return { command: 'settings.api_keys.get', payload: undefined };
  }
  if (upperMethod === 'PUT' && path === '/api/settings/api-keys') {
    return { command: 'settings.api_keys.set', payload: payload as DesktopApiKeyPayload };
  }
  if (upperMethod === 'GET' && path === '/api/settings/news-feeds') {
    return { command: 'settings.news.get', payload: undefined };
  }
  if (upperMethod === 'PUT' && path === '/api/settings/news-feeds') {
    return { command: 'settings.news.set', payload: payload as DesktopNewsFeedPayload[] };
  }
  if (upperMethod === 'POST' && path === '/api/settings/news-feeds/reset') {
    return { command: 'settings.news.reset', payload: undefined };
  }
  if (upperMethod === 'POST' && path === '/api/system/update') {
    return { command: 'system.update', payload: undefined };
  }
  return null;
}
