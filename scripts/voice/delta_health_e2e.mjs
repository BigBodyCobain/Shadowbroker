#!/usr/bin/env node
/**
 * Acceptance #36 (voice-agent plan §7.E) — Delta-mode health E2E.
 *
 * Post-U0 observable: with the `tracked_flights` / `correlations`
 * `_mark_fresh` stamps in place, a polling session that echoes the store's
 * per-layer versions back via `lv=` must be answered `X-SB-Mode: delta`
 * for the overwhelming majority of fast polls (pre-fix this was 0% because
 * the missing stamps forced the all-keys fallback to a full snapshot —
 * routers/data.py returns a snapshot when ANY requested delta key lacks a
 * version).
 *
 * Usage:
 *   node scripts/voice/delta_health_e2e.mjs [--base http://127.0.0.1:8000]
 *                                            [--polls 30] [--interval-ms 2000]
 *                                            [--min-rate 0.8]
 *
 * Exit 0 when the delta rate meets --min-rate, exit 1 otherwise.
 * This is the automated headless variant of the plan's "5-minute browser
 * session" — same protocol (initial snapshot → lv echo → delta), no UI.
 */

const args = process.argv.slice(2);
function argOf(name, dflt) {
  const i = args.indexOf(name);
  return i >= 0 && args[i + 1] ? args[i + 1] : dflt;
}

const BASE = String(argOf('--base', 'http://127.0.0.1:8000')).replace(/\/$/, '');
const POLLS = Math.max(2, parseInt(argOf('--polls', '30'), 10));
const INTERVAL_MS = Math.max(250, parseInt(argOf('--interval-ms', '2000'), 10));
const MIN_RATE = Math.min(1, Math.max(0, parseFloat(argOf('--min-rate', '0.8'))));

function encodeLv(layerVersions) {
  return Object.entries(layerVersions)
    .map(([k, v]) => `${encodeURIComponent(k)}:${encodeURIComponent(String(v))}`)
    .join(',');
}

async function poll(url) {
  const res = await fetch(url, { headers: { accept: 'application/json' } });
  if (!res.ok) throw new Error(`${url} -> HTTP ${res.status}`);
  const modeHeader = res.headers.get('x-sb-mode') || '(none)';
  const body = await res.json();
  return { modeHeader, mode: String(body.mode || 'snapshot'), body };
}

async function main() {
  console.log(`Delta-health E2E against ${BASE}`);
  console.log(`polls=${POLLS} interval=${INTERVAL_MS}ms min-rate=${Math.round(MIN_RATE * 100)}%\n`);

  // 1. Startup snapshot (initial=true is the capped first-paint payload).
  const first = await poll(`${BASE}/api/live-data/fast?initial=true`);
  console.log(`initial: mode=${first.mode} header=${first.modeHeader}`);
  let layerVersions = first.body.layer_versions;
  if (!layerVersions || typeof layerVersions !== 'object') {
    console.error('FAIL: initial snapshot carried no layer_versions — cannot enter delta mode.');
    process.exit(1);
  }

  // 2. Echo versions back; the server should answer delta while nothing
  //    invalidates the ring (and snapshot only on genuine skew/miss).
  let delta = 0;
  let snapshot = 0;
  const rows = [];
  for (let i = 0; i < POLLS; i++) {
    await new Promise((r) => setTimeout(r, INTERVAL_MS));
    let p;
    try {
      p = await poll(`${BASE}/api/live-data/fast?lv=${encodeLv(layerVersions)}`);
    } catch (err) {
      console.error(`poll ${i + 1}: ${err.message}`);
      snapshot += 1;
      rows.push({ i: i + 1, mode: 'error' });
      continue;
    }
    if (p.body.layer_versions && typeof p.body.layer_versions === 'object') {
      layerVersions = p.body.layer_versions;
    }
    if (p.mode === 'delta') delta += 1;
    else snapshot += 1;
    rows.push({ i: i + 1, mode: p.mode });
    console.log(`poll ${String(i + 1).padStart(3)}: mode=${p.mode} header=${p.modeHeader}`);
  }

  const rate = delta / (delta + snapshot);
  console.log(`\nResult: ${delta} delta / ${snapshot} snapshot — rate ${(rate * 100).toFixed(1)}% (floor ${Math.round(MIN_RATE * 100)}%)`);
  if (rate < MIN_RATE) {
    console.error('FAIL: delta rate below floor. If tracked_flights/correlations lost their');
    console.error('_mark_fresh stamps, routers/data.py silently degrades EVERY fast poll');
    console.error('to a full snapshot — check backend/tests/test_freshness_stamps.py.');
    process.exit(1);
  }
  console.log('PASS: delta-mode health confirmed.');
}

main().catch((err) => {
  console.error(`FATAL: ${err.message}`);
  process.exit(1);
});
