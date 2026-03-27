import type { NativeControlHandlerMap } from '../types';

export function createWormholeHandlers(): Pick<
  NativeControlHandlerMap,
  | 'wormhole.status'
  | 'wormhole.connect'
  | 'wormhole.disconnect'
  | 'wormhole.restart'
  | 'wormhole.gate.enter'
  | 'wormhole.gate.leave'
  | 'wormhole.gate.proof'
  | 'wormhole.gate.personas.get'
  | 'wormhole.gate.persona.create'
  | 'wormhole.gate.persona.activate'
  | 'wormhole.gate.persona.clear'
  | 'wormhole.gate.key.get'
  | 'wormhole.gate.key.rotate'
  | 'wormhole.gate.message.compose'
  | 'wormhole.gate.message.decrypt'
  | 'wormhole.gate.message.post'
  | 'wormhole.gate.messages.decrypt'
> {
  return {
    'wormhole.status': async (_payload, _ctx, exec) => exec('/api/wormhole/status'),
    'wormhole.connect': async (_payload, _ctx, exec) =>
      exec('/api/wormhole/connect', { method: 'POST' }),
    'wormhole.disconnect': async (_payload, _ctx, exec) =>
      exec('/api/wormhole/disconnect', { method: 'POST' }),
    'wormhole.restart': async (_payload, _ctx, exec) =>
      exec('/api/wormhole/restart', { method: 'POST' }),
    'wormhole.gate.personas.get': async (payload, _ctx, exec) =>
      exec(`/api/wormhole/gate/${encodeURIComponent(String(payload?.gate_id || ''))}/personas`),
    'wormhole.gate.persona.create': async (payload, _ctx, exec) =>
      exec('/api/wormhole/gate/persona/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      }),
    'wormhole.gate.persona.activate': async (payload, _ctx, exec) =>
      exec('/api/wormhole/gate/persona/activate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      }),
    'wormhole.gate.persona.clear': async (payload, _ctx, exec) =>
      exec('/api/wormhole/gate/persona/clear', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      }),
    'wormhole.gate.key.get': async (payload, _ctx, exec) =>
      exec(`/api/wormhole/gate/${encodeURIComponent(String(payload?.gate_id || ''))}/key`),
    'wormhole.gate.key.rotate': async (payload, _ctx, exec) =>
      exec('/api/wormhole/gate/key/rotate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      }),
    'wormhole.gate.message.compose': async (payload, _ctx, exec) =>
      exec('/api/wormhole/gate/message/compose', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      }),
    'wormhole.gate.message.decrypt': async (payload, _ctx, exec) =>
      exec('/api/wormhole/gate/message/decrypt', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      }),
    'wormhole.gate.enter': async (payload, _ctx, exec) =>
      exec('/api/wormhole/gate/enter', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      }),
    'wormhole.gate.leave': async (payload, _ctx, exec) =>
      exec('/api/wormhole/gate/leave', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      }),
    'wormhole.gate.proof': async (payload, _ctx, exec) =>
      exec('/api/wormhole/gate/proof', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      }),
    'wormhole.gate.message.post': async (payload, _ctx, exec) =>
      exec('/api/wormhole/gate/message/post', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      }),
    'wormhole.gate.messages.decrypt': async (payload, _ctx, exec) =>
      exec('/api/wormhole/gate/messages/decrypt', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      }),
  };
}
