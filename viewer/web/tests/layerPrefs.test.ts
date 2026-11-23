/**
 * Tests for which layer switches the viewer saves and restores.
 * Run: node --test viewer/web/tests/layerPrefs.test.ts
 */

import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  VIEWER_LAYER_REV,
  layersOnLoad,
  layersToStore,
  withHiddenOff,
} from '../overlay/src/viewer/layerPrefs.ts';

const HIDDEN = new Set(['sar', 'ai_intel']);
const DEFAULTS = { flights: true, cctv: false, sigint_aprs: true, sar: true, ai_intel: true };

test('hidden layers are shown as off', () => {
  const shown = withHiddenOff(DEFAULTS, HIDDEN);
  assert.equal(shown.sar, false);
  assert.equal(shown.ai_intel, false);
  assert.equal(shown.flights, true);
});

test('hidden layers are never saved', () => {
  const stored = layersToStore(withHiddenOff(DEFAULTS, HIDDEN), HIDDEN) as Record<string, boolean>;
  assert.equal('sar' in stored, false);
  assert.equal('ai_intel' in stored, false);
  assert.equal(stored.flights, true);
  assert.equal(stored.sigint_aprs, true);
});

test('a forced "off" saved by an older build goes back to the default', () => {
  const saved = { ...DEFAULTS, sigint_aprs: false, flights: false };
  const loaded = layersOnLoad(DEFAULTS, saved, HIDDEN, 0, ['sigint_aprs']);
  assert.equal(loaded.sigint_aprs, true, 'restored to default');
  assert.equal(loaded.flights, false, "the visitor's own choice is kept");
  assert.equal(loaded.sar, false, 'still hidden');
});

test('after the one-time restore, a visitor who switches the layer off keeps it off', () => {
  const saved = { ...DEFAULTS, sigint_aprs: false };
  const loaded = layersOnLoad(DEFAULTS, saved, HIDDEN, VIEWER_LAYER_REV, ['sigint_aprs']);
  assert.equal(loaded.sigint_aprs, false);
});

test('a layer that is hidden stays off even if it is on the restore list', () => {
  const loaded = layersOnLoad(DEFAULTS, { ...DEFAULTS }, HIDDEN, 0, ['sar']);
  assert.equal(loaded.sar, false);
});
