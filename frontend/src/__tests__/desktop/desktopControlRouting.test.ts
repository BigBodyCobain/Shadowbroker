import { describe, expect, it } from 'vitest';
import {
  commandToHttpRequest,
  httpRequestToInvokeRequest,
} from '@/lib/desktopControlRouting';

describe('desktopControlRouting', () => {
  it('maps invoke commands to HTTP requests', () => {
    expect(commandToHttpRequest('wormhole.connect')).toEqual({
      path: '/api/wormhole/connect',
      method: 'POST',
    });
    expect(commandToHttpRequest('wormhole.gate.key.get', { gate_id: 'infonet' })).toEqual({
      path: '/api/wormhole/gate/infonet/key',
      method: 'GET',
    });
    expect(commandToHttpRequest('settings.news.reset')).toEqual({
      path: '/api/settings/news-feeds/reset',
      method: 'POST',
    });
    expect(commandToHttpRequest('wormhole.gate.proof', { gate_id: 'infonet' })).toEqual({
      path: '/api/wormhole/gate/proof',
      method: 'POST',
      payload: { gate_id: 'infonet' },
    });
    expect(
      commandToHttpRequest('wormhole.gate.message.post', {
        gate_id: 'ops',
        plaintext: 'hello',
      }),
    ).toEqual({
      path: '/api/wormhole/gate/message/post',
      method: 'POST',
      payload: { gate_id: 'ops', plaintext: 'hello' },
    });
  });

  it('maps HTTP settings writes back to invoke requests', () => {
    expect(
      httpRequestToInvokeRequest(
        '/api/settings/privacy-profile',
        'PUT',
        JSON.stringify({ profile: 'high' }),
      ),
    ).toEqual({
      command: 'settings.privacy.set',
      payload: { profile: 'high' },
    });
    expect(
      httpRequestToInvokeRequest(
        '/api/wormhole/gate/key/rotate',
        'POST',
        JSON.stringify({ gate_id: 'infonet', reason: 'operator_reset' }),
      ),
    ).toEqual({
      command: 'wormhole.gate.key.rotate',
      payload: { gate_id: 'infonet', reason: 'operator_reset' },
    });
    expect(
      httpRequestToInvokeRequest(
        '/api/wormhole/gate/proof',
        'POST',
        JSON.stringify({ gate_id: 'infonet' }),
      ),
    ).toEqual({
      command: 'wormhole.gate.proof',
      payload: { gate_id: 'infonet' },
    });
    expect(
      httpRequestToInvokeRequest(
        '/api/wormhole/gate/messages/decrypt',
        'POST',
        JSON.stringify({
          messages: [
            {
              gate_id: 'infonet',
              epoch: 3,
              ciphertext: 'ct',
              nonce: 'n',
              sender_ref: 'ref',
            },
          ],
        }),
      ),
    ).toEqual({
      command: 'wormhole.gate.messages.decrypt',
      payload: {
        messages: [
          {
            gate_id: 'infonet',
            epoch: 3,
            ciphertext: 'ct',
            nonce: 'n',
            sender_ref: 'ref',
          },
        ],
      },
    });
  });

  it('returns null for unsupported paths', () => {
    expect(httpRequestToInvokeRequest('/api/mesh/status', 'GET')).toBeNull();
  });
});
