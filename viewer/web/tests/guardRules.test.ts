/**
 * Tests for the public viewer's network rule.
 * Run: node --test viewer/web/tests/guardRules.test.ts   (Node 23.6+ runs TypeScript directly)
 */

import assert from 'node:assert/strict';
import { test } from 'node:test';
import { classifyRequest, type GuardContext } from '../overlay/src/viewer/guardRules.ts';

const PAGE = 'https://live.example.org';
const HOSTS = ['tiles.openfreemap.org', 'en.wikipedia.org'];

function ctx(dataBase: string): GuardContext {
  return { pageOrigin: PAGE, dataBase: new URL(dataBase, `${PAGE}/`), allowedHosts: HOSTS };
}
const SAME = ctx('/live-data');
const SPLIT = ctx('https://data.example.org/v1');

function kind(url: string, method = 'GET', context: GuardContext = SAME): string {
  return classifyRequest(new URL(url, `${PAGE}/`), method, context).kind;
}

test('own static files: reads only', () => {
  assert.equal(kind('/_next/static/chunks/main.js'), 'network');
  assert.equal(kind('/data/submarine-cables.json'), 'network');
  assert.equal(kind('/anything', 'POST'), 'refuse');
  assert.equal(kind('/anything', 'PUT'), 'refuse');
  assert.equal(kind('/anything', 'DELETE'), 'refuse');
});

test('data files: reads only, on either kind of data host', () => {
  assert.equal(kind('/live-data/manifest.json'), 'network');
  assert.equal(kind('/live-data/k/sigint.json?v=abc'), 'network');
  assert.equal(kind('/live-data/manifest.json', 'POST'), 'refuse');
  assert.equal(kind('https://data.example.org/v1/fast.json', 'GET', SPLIT), 'network');
  assert.equal(kind('https://data.example.org/v1/fast.json', 'PUT', SPLIT), 'refuse');
  // Same host, outside the data folder.
  assert.equal(kind('https://data.example.org/other/fast.json', 'GET', SPLIT), 'refuse');
  assert.equal(kind('https://data.example.org/v10/fast.json', 'GET', SPLIT), 'refuse');
  assert.equal(kind('https://data.example.org/v1/../admin', 'GET', SPLIT), 'refuse');
});

test('every write to an app route is refused', () => {
  const writes = [
    '/api/mesh/send',
    '/api/mesh/meshtastic/send',
    '/api/sigint/transmit',
    '/api/settings/api-keys',
    '/api/layers',
    '/api/wormhole/join',
    '/api/infonet/append',
    '/api/system/update',
    '/api/ai/pins',
    '/api/viewport',
    '/api/cyber-threats',
  ];
  for (const path of writes) {
    for (const method of ['POST', 'PUT', 'PATCH', 'DELETE']) {
      assert.equal(kind(path, method), 'refuse', `${method} ${path}`);
    }
  }
});

test('app reads are refused unless the viewer can answer them itself', () => {
  assert.equal(kind('/api/cyber-threats'), 'local');
  assert.equal(kind('/api/scm-suppliers'), 'local');
  assert.equal(kind('/api/wikipedia/summary?title=Boeing_747'), 'local');
  for (const path of [
    '/api/settings/api-keys',
    '/api/settings/api-keys/meta',
    '/api/health',
    '/api/live-data/fast',
    '/api/mesh/messages',
    '/api/ai/pins',
    '/api/cctv/media?url=https%3A%2F%2Fexample.org%2Fx.jpg',
    '/api/geocode/search?q=paris',
    '/api/cyber-threats/extra',
    '/api',
  ]) {
    assert.equal(kind(path), 'refuse', path);
  }
});

test('odd spellings of app routes do not slip through as static files', () => {
  assert.equal(kind('/API/mesh/send'), 'refuse');
  assert.equal(kind('//api/mesh/send'.replace('//', '/x/../')), 'refuse');
  assert.equal(kind('/live-data/../api/settings/api-keys'), 'refuse');
  assert.equal(kind('/live-data/%2e%2e/api/settings/api-keys'), 'refuse');
  assert.equal(kind(`${PAGE}//api/health`), 'refuse');
});

test('an app route on the data path is still an app route when both share an origin', () => {
  const weird = ctx('/api/live');
  assert.equal(kind('/api/live/manifest.json', 'GET', weird), 'refuse');
});

test('outside hosts: only listed ones, exact match, https, reads', () => {
  assert.equal(kind('https://tiles.openfreemap.org/styles/dark'), 'network');
  assert.equal(kind('https://en.wikipedia.org/api/rest_v1/page/summary/X'), 'network');
  assert.equal(kind('https://tiles.openfreemap.org/styles/dark', 'POST'), 'refuse');
  assert.equal(kind('http://tiles.openfreemap.org/styles/dark'), 'refuse');
  assert.equal(kind('https://evil.tiles.openfreemap.org/x'), 'refuse');
  assert.equal(kind('https://tiles.openfreemap.org.evil.example/x'), 'refuse');
  assert.equal(kind('https://example.com/collect?d=1'), 'refuse');
  assert.equal(kind('https://mqtt.meshtastic.org/'), 'refuse');
  assert.equal(kind('http://127.0.0.1:8000/api/mesh/send', 'POST'), 'refuse');
  assert.equal(kind('http://localhost:8011/api/live-data/fast'), 'refuse');
});

test('non-web schemes and credentialed URLs are refused', () => {
  assert.equal(kind('ws://127.0.0.1:8000/api/ai/channel/ws'), 'refuse');
  assert.equal(kind('wss://live.example.org/socket'), 'refuse');
  assert.equal(kind('ftp://example.org/x'), 'refuse');
  assert.equal(kind('javascript:alert(1)'), 'refuse');
  assert.equal(kind('https://user:pw@tiles.openfreemap.org/x'), 'refuse');
  assert.equal(kind('data:application/json,{}'), 'network');
  assert.equal(kind('blob:https://live.example.org/abc'), 'network');
});

const CHAT = { ...SPLIT, chatBase: new URL('https://abc.supabase.co') };

test('chat service: sign-in and posting only, on its own paths', () => {
  assert.equal(kind('https://abc.supabase.co/rest/v1/messages?select=id', 'GET', CHAT), 'network');
  assert.equal(kind('https://abc.supabase.co/rest/v1/messages', 'POST', CHAT), 'network');
  assert.equal(kind('https://abc.supabase.co/auth/v1/token?grant_type=password', 'POST', CHAT), 'network');
  // No edits or deletes from the browser, and nothing outside the two paths.
  assert.equal(kind('https://abc.supabase.co/rest/v1/messages?id=eq.1', 'DELETE', CHAT), 'refuse');
  assert.equal(kind('https://abc.supabase.co/rest/v1/profiles?id=eq.1', 'PATCH', CHAT), 'refuse');
  assert.equal(kind('https://abc.supabase.co/storage/v1/object/x', 'POST', CHAT), 'refuse');
  assert.equal(kind('https://abc.supabase.co/functions/v1/anything', 'POST', CHAT), 'refuse');
  assert.equal(kind('https://abc.supabase.co/rest/v1/../../storage/v1/object/x', 'POST', CHAT), 'refuse');
  // Look-alike hosts and plain http are not the chat service.
  assert.equal(kind('https://abc.supabase.co.evil.example/rest/v1/messages', 'POST', CHAT), 'refuse');
  assert.equal(kind('https://other.supabase.co/rest/v1/messages', 'POST', CHAT), 'refuse');
  assert.equal(kind('http://abc.supabase.co/rest/v1/messages', 'POST', CHAT), 'refuse');
});

test('chat does not loosen any other rule', () => {
  assert.equal(kind('/api/mesh/send', 'POST', CHAT), 'refuse');
  assert.equal(kind('/api/settings/api-keys', 'GET', CHAT), 'refuse');
  assert.equal(kind('https://data.example.org/v1/fast.json', 'POST', CHAT), 'refuse');
  assert.equal(kind('https://example.com/collect', 'POST', CHAT), 'refuse');
  assert.equal(kind('http://127.0.0.1:8011/api/live-data/fast', 'GET', CHAT), 'refuse');
  // Without a chat service configured, its host is just another outside host.
  assert.equal(kind('https://abc.supabase.co/rest/v1/messages', 'POST', SPLIT), 'refuse');
});
