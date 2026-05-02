#!/usr/bin/env node

import path from 'node:path';
import { spawn } from 'node:child_process';

const HELP_TEXT = `
ShadowBroker DM root deployment smoke

Usage:
  node scripts/mesh/smoke-dm-root-deployment-flow.mjs [--keep] [--workspace PATH] [--base-url URL] [--require-current-external]

Environment:
  SB_DM_ROOT_BASE_URL=http://127.0.0.1:8000
  SB_DM_ROOT_AUTH_HEADER=X-Admin-Key: change-me
  SB_DM_ROOT_AUTH_COOKIE=operator_session=...
  SB_DM_ROOT_TIMEOUT_MS=10000
  SB_DM_ROOT_DEPLOYMENT_SMOKE_WORKSPACE=.smoke/dm-root-deployment

What it does:
  1. Runs the external witness bootstrap smoke.
  2. Runs the transparency publication smoke.
  3. Fetches /api/wormhole/dm/root-health.
  4. Prints one rolled-up result for the current deployment state.

Flags:
  --keep                      Keep the smoke workspace instead of deleting it
  --workspace PATH            Override SB_DM_ROOT_DEPLOYMENT_SMOKE_WORKSPACE
  --base-url URL              Override SB_DM_ROOT_BASE_URL
  --require-current-external  Fail unless root-health ends in current_external with strong trust unblocked
  --help                      Show this text
`.trim();

function parseArgs(argv) {
  const parsed = {};
  for (let index = 0; index < argv.length; index += 1) {
    const current = String(argv[index] || '').trim();
    if (!current) continue;
    if (current === '--keep' || current === '--require-current-external') {
      parsed[current.slice(2).replace(/-([a-z])/g, (_match, letter) => letter.toUpperCase())] = true;
      continue;
    }
    if (current === '--help' || current === '-h') {
      parsed.help = true;
      continue;
    }
    if ((current === '--workspace' || current === '--base-url') && index + 1 < argv.length) {
      parsed[current.slice(2).replace(/-([a-z])/g, (_match, letter) => letter.toUpperCase())] =
        String(argv[index + 1] || '').trim();
      index += 1;
    }
  }
  return parsed;
}

function normalizeUrl(baseUrl, routePath) {
  const base = String(baseUrl || 'http://127.0.0.1:8000').trim().replace(/\/+$/, '');
  return `${base}/${String(routePath || '').replace(/^\/+/, '')}`;
}

function parseHeader(rawValue) {
  const raw = String(rawValue || '').trim();
  if (!raw) return null;
  const separator = raw.indexOf(':');
  if (separator <= 0) return null;
  const name = raw.slice(0, separator).trim();
  const value = raw.slice(separator + 1).trim();
  if (!name || !value) return null;
  return [name, value];
}

function safeInt(value, fallback = 0) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return fallback;
  return Math.trunc(numeric);
}

async function requestJson({ method, url, authHeader, authCookie, timeoutMs }) {
  const headers = { Accept: 'application/json' };
  const parsedAuth = parseHeader(authHeader);
  if (parsedAuth) {
    headers[parsedAuth[0]] = parsedAuth[1];
  }
  if (authCookie) {
    headers.Cookie = authCookie;
  }
  const controller = new AbortController();
  const timeout = globalThis.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, {
      method,
      headers,
      signal: controller.signal,
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || payload?.ok === false) {
      const detail = String(payload?.detail || payload?.message || `http_${response.status}`).trim();
      throw new Error(detail || `${method.toLowerCase()}_${url}_failed`);
    }
    return payload;
  } finally {
    globalThis.clearTimeout(timeout);
  }
}

async function spawnNodeScript(scriptPath, args, env) {
  await new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [scriptPath, ...args], {
      stdio: 'inherit',
      env,
    });
    child.on('error', reject);
    child.on('exit', (code) => {
      if (code === 0) {
        resolve();
        return;
      }
      reject(new Error(`${path.basename(scriptPath)} exited ${code ?? 1}`));
    });
  });
}

function assert(condition, detail) {
  if (!condition) {
    throw new Error(detail);
  }
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    console.log(HELP_TEXT);
    return;
  }

  const rootDir = process.cwd();
  const workspace = path.resolve(
    String(args.workspace || process.env.SB_DM_ROOT_DEPLOYMENT_SMOKE_WORKSPACE || '.smoke/dm-root-deployment').trim(),
  );
  const baseUrl = String(args.baseUrl || process.env.SB_DM_ROOT_BASE_URL || 'http://127.0.0.1:8000').trim();
  const timeoutMs = Math.max(1000, safeInt(process.env.SB_DM_ROOT_TIMEOUT_MS, 10000));
  const authHeader = process.env.SB_DM_ROOT_AUTH_HEADER || '';
  const authCookie = process.env.SB_DM_ROOT_AUTH_COOKIE || '';

  const witnessSmokeScript = path.resolve(rootDir, 'scripts/mesh/smoke-external-root-witness-flow.mjs');
  const transparencySmokeScript = path.resolve(rootDir, 'scripts/mesh/smoke-root-transparency-publication-flow.mjs');
  const witnessWorkspace = path.join(workspace, 'witness');
  const transparencyWorkspace = path.join(workspace, 'transparency');

  const childEnv = {
    ...process.env,
    SB_DM_ROOT_BASE_URL: baseUrl,
    SB_DM_ROOT_AUTH_HEADER: authHeader,
    SB_DM_ROOT_AUTH_COOKIE: authCookie,
    SB_DM_ROOT_TIMEOUT_MS: String(timeoutMs),
  };

  console.log('1/3 run external witness bootstrap smoke');
  await spawnNodeScript(
    witnessSmokeScript,
    ['--workspace', witnessWorkspace, '--base-url', baseUrl, ...(args.keep ? ['--keep'] : [])],
    childEnv,
  );

  console.log('2/3 run transparency publication smoke');
  await spawnNodeScript(
    transparencySmokeScript,
    ['--workspace', transparencyWorkspace, '--base-url', baseUrl, ...(args.keep ? ['--keep'] : [])],
    childEnv,
  );

  console.log('3/3 fetch rolled-up DM root health');
  const health = await requestJson({
    method: 'GET',
    url: normalizeUrl(baseUrl, '/api/wormhole/dm/root-health'),
    authHeader,
    authCookie,
    timeoutMs,
  });

  if (args.requireCurrentExternal) {
    assert(String(health?.state || '').trim() === 'current_external', 'dm root health did not reach current_external');
    assert(String(health?.health_state || '').trim() === 'ok', 'dm root health did not reach ok');
    assert(!Boolean(health?.strong_trust_blocked), 'strong DM trust is still blocked');
  }

  const summary = {
    ok: true,
    workspace,
    require_current_external: Boolean(args.requireCurrentExternal),
    state: String(health?.state || '').trim(),
    health_state: String(health?.health_state || '').trim(),
    strong_trust_blocked: Boolean(health?.strong_trust_blocked),
    external_assurance_current: Boolean(health?.external_assurance_current),
    requires_attention: Boolean(health?.requires_attention),
    monitoring_state: String(health?.monitoring?.state || '').trim(),
    monitoring_status_line: String(health?.monitoring?.status_line || '').trim(),
    next_action: String(health?.next_action || '').trim(),
    witness_state: String(health?.witness?.state || '').trim(),
    witness_health_state: String(health?.witness?.health_state || '').trim(),
    transparency_state: String(health?.transparency?.state || '').trim(),
    transparency_health_state: String(health?.transparency?.health_state || '').trim(),
  };
  console.log(JSON.stringify(summary, null, 2));
}

await main().catch((error) => {
  console.error(String(error?.message || error || 'dm root deployment smoke failed').trim());
  process.exit(2);
});
