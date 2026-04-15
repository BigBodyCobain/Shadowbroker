import type { NativeControlHandlerMap } from '../types';

export function createSettingsHandlers(): Pick<
  NativeControlHandlerMap,
  | 'settings.wormhole.get'
  | 'settings.wormhole.set'
  | 'settings.privacy.get'
  | 'settings.privacy.set'
  | 'settings.api_keys.get'
  | 'settings.api_keys.set'
  | 'settings.news.get'
  | 'settings.news.set'
  | 'settings.news.reset'
> {
  return {
    'settings.wormhole.get': async (_payload, _ctx, exec) => exec('/api/settings/wormhole'),
    'settings.wormhole.set': async (payload, _ctx, exec) =>
      exec('/api/settings/wormhole', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      }),
    'settings.privacy.get': async (_payload, _ctx, exec) =>
      exec('/api/settings/privacy-profile'),
    'settings.privacy.set': async (payload, _ctx, exec) =>
      exec('/api/settings/privacy-profile', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      }),
    'settings.api_keys.get': async (_payload, _ctx, exec) => exec('/api/settings/api-keys'),
    'settings.api_keys.set': async (payload, _ctx, exec) =>
      exec('/api/settings/api-keys', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      }),
    'settings.news.get': async (_payload, _ctx, exec) => exec('/api/settings/news-feeds'),
    'settings.news.set': async (payload, _ctx, exec) =>
      exec('/api/settings/news-feeds', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      }),
    'settings.news.reset': async (_payload, _ctx, exec) =>
      exec('/api/settings/news-feeds/reset', {
        method: 'POST',
      }),
  };
}
