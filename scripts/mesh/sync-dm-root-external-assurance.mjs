#!/usr/bin/env node

import fs from 'node:fs/promises';
import path from 'node:path';
import { spawn } from 'node:child_process';

const HELP_TEXT = `
ShadowBroker DM root external assurance sync

Usage:
  node scripts/mesh/sync-dm-root-external-assurance.mjs [--base-url URL] [--witness-file PATH] [--publish-transparency]

Environment:
  SB_DM_ROOT_BASE_URL=http://127.0.0.1:8000
  SB_DM_ROOT_AUTH_HEADER=X-Admin-Key: change-me
  SB_DM_ROOT_AUTH_COOKIE=operator_session=...
  SB_DM_ROOT_TIMEOUT_MS=10000
  SB_DM_ROOT_WITNESS_IDENTITY_FILE=./ops/witness-a.identity.json
  SB_DM_ROOT_WITNESS_LABEL=witness-a
  SB_DM_ROOT_WITNESS_SOURCE_SCOPE=https_publish
  SB_DM_ROOT_WITNESS_SOURCE_LABEL=witness-a
  SB_DM_ROOT_WITNESS_INDEPENDENCE_GROUP=independent_witness_a
  SB_DM_ROOT_TRANSPARENCY_PUBLISH_PATH=./published/root_transparency_ledger.json
  SB_DM_ROOT_TRANSPARENCY_MAX_RECORDS=64

What it does:
  1. Creates an external witness identity if the configured file is missing.
  2. Imports a descriptor-only witness package if the external witness is not yet declared in policy.
  3. Imports a full signed witness receipt package once the current manifest policy allows it.
  4. Optionally publishes the transparency ledger to a chosen file path.
  5. Prints the final DM root health summary.

Flags:
  --base-url URL           Override SB_DM_ROOT_BASE_URL
  --witness-file PATH      Override SB_DM_ROOT_WITNESS_IDENTITY_FILE
  --publish-transparency   Publish the transparency ledger using SB_DM_ROOT_TRANSPARENCY_PUBLISH_PATH
  --help                   Show this text
`.trim();

function parseArgs(argv) {
  const parsed = {};
  for (let index = 0; index < argv.length; index += 1) {
    const current = String(argv[index] || '').trim();
    if (!current) continue;
    if (current === '--publish-transparency') {
      parsed.publishTransparency = true;
      continue;
    }
    if (current === '--help' || current === '-h') {
      parsed.help = true;
      continue;
    }
    if ((current === '--base-url' || current === '--witness-file') && index + 1 < argv.length) {
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

async function requestJson({ method, url, authHeader, authCookie, timeoutMs, body }) {
  const headers = { Accept: 'application/json' };
  const parsedAuth = parseHeader(authHeader);
  if (parsedAuth) {
    headers[parsedAuth[0]] = parsedAuth[1];
  }
  if (authCookie) {
    headers.Cookie = authCookie;
  }
  if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
  }
  const controller = new AbortController();
  const timeout = globalThis.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
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

async function spawnNode(scriptPath, args, env, { expectJson = false } = {}) {
  return await new Promise((resolve, reject) => {
    let stdout = '';
    let stderr = '';
    const child = spawn(process.execPath, [scriptPath, ...args], {
      env,
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    child.stdout.on('data', (chunk) => {
      stdout += String(chunk || '');
      process.stdout.write(chunk);
    });
    child.stderr.on('data', (chunk) => {
      stderr += String(chunk || '');
      process.stderr.write(chunk);
    });
    child.on('error', reject);
    child.on('exit', (code) => {
      if (code !== 0) {
        reject(new Error(stderr.trim() || `${path.basename(scriptPath)} exited ${code ?? 1}`));
        return;
      }
      if (!expectJson) {
        resolve(undefined);
        return;
      }
      try {
        resolve(JSON.parse(stdout));
      } catch {
        reject(new Error(`failed to parse JSON output from ${path.basename(scriptPath)}`));
      }
    });
  });
}

function witnessDeclaredInPolicy(distribution, identity) {
  const witnesses = Array.isArray(distribution?.witness_policy?.witnesses)
    ? distribution.witness_policy.witnesses
    : [];
  return witnesses.some(
    (item) =>
      String(item?.node_id || '').trim() === String(identity?.node_id || '').trim() &&
      String(item?.public_key || '').trim() === String(identity?.public_key || '').trim(),
  );
}

async function readJsonFile(filePath) {
  const raw = await fs.readFile(path.resolve(filePath), 'utf8');
  return JSON.parse(raw);
}

async function exists(filePath) {
  try {
    await fs.access(path.resolve(filePath));
    return true;
  } catch {
    return false;
  }
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    console.log(HELP_TEXT);
    return;
  }

  const rootDir = process.cwd();
  const publisherScript = path.resolve(rootDir, 'scripts/mesh/publish-external-root-witness-package.mjs');
  const baseUrl = String(args.baseUrl || process.env.SB_DM_ROOT_BASE_URL || 'http://127.0.0.1:8000').trim();
  const witnessFile = String(args.witnessFile || process.env.SB_DM_ROOT_WITNESS_IDENTITY_FILE || '').trim();
  const timeoutMs = Math.max(1000, safeInt(process.env.SB_DM_ROOT_TIMEOUT_MS, 10000));
  const authHeader = process.env.SB_DM_ROOT_AUTH_HEADER || '';
  const authCookie = process.env.SB_DM_ROOT_AUTH_COOKIE || '';
  const transparencyPublishPath = String(process.env.SB_DM_ROOT_TRANSPARENCY_PUBLISH_PATH || '').trim();
  const transparencyMaxRecords = Math.max(1, safeInt(process.env.SB_DM_ROOT_TRANSPARENCY_MAX_RECORDS, 64));

  if (!witnessFile) {
    throw new Error('witness identity file required via --witness-file or SB_DM_ROOT_WITNESS_IDENTITY_FILE');
  }

  const childEnv = {
    ...process.env,
    SB_DM_ROOT_BASE_URL: baseUrl,
    SB_DM_ROOT_AUTH_HEADER: authHeader,
    SB_DM_ROOT_AUTH_COOKIE: authCookie,
    SB_DM_ROOT_TIMEOUT_MS: String(timeoutMs),
  };

  const actions = [];

  if (!(await exists(witnessFile))) {
    console.log('creating external witness identity');
    await spawnNode(publisherScript, ['--init-witness', witnessFile], childEnv);
    actions.push('witness_identity_created');
  }

  const identity = await readJsonFile(witnessFile);

  let distribution = await requestJson({
    method: 'GET',
    url: normalizeUrl(baseUrl, '/api/wormhole/dm/root-distribution'),
    authHeader,
    authCookie,
    timeoutMs,
  });

  if (!witnessDeclaredInPolicy(distribution, identity)) {
    console.log('importing descriptor-only external witness package');
    const descriptorMaterial = await spawnNode(
      publisherScript,
      ['--descriptor-only', '--witness-file', witnessFile, '--stdout'],
      childEnv,
      { expectJson: true },
    );
    await requestJson({
      method: 'POST',
      url: normalizeUrl(baseUrl, '/api/wormhole/dm/root-witnesses/import'),
      authHeader,
      authCookie,
      timeoutMs,
      body: { material: descriptorMaterial },
    });
    actions.push('descriptor_imported');
    distribution = await requestJson({
      method: 'GET',
      url: normalizeUrl(baseUrl, '/api/wormhole/dm/root-distribution'),
      authHeader,
      authCookie,
      timeoutMs,
    });
  }

  if (witnessDeclaredInPolicy(distribution, identity) && !Boolean(distribution?.external_witness_receipts_current)) {
    console.log('importing full external witness receipt package');
    const receiptMaterial = await spawnNode(
      publisherScript,
      ['--witness-file', witnessFile, '--stdout'],
      childEnv,
      { expectJson: true },
    );
    await requestJson({
      method: 'POST',
      url: normalizeUrl(baseUrl, '/api/wormhole/dm/root-witnesses/import'),
      authHeader,
      authCookie,
      timeoutMs,
      body: { material: receiptMaterial },
    });
    actions.push('receipt_imported');
    distribution = await requestJson({
      method: 'GET',
      url: normalizeUrl(baseUrl, '/api/wormhole/dm/root-distribution'),
      authHeader,
      authCookie,
      timeoutMs,
    });
  }

  let transparency = null;
  if (args.publishTransparency) {
    if (!transparencyPublishPath) {
      throw new Error('SB_DM_ROOT_TRANSPARENCY_PUBLISH_PATH required when --publish-transparency is used');
    }
    console.log('publishing transparency ledger');
    transparency = await requestJson({
      method: 'POST',
      url: normalizeUrl(baseUrl, '/api/wormhole/dm/root-transparency/ledger/publish'),
      authHeader,
      authCookie,
      timeoutMs,
      body: {
        path: transparencyPublishPath,
        max_records: transparencyMaxRecords,
      },
    });
    actions.push('transparency_published');
  }

  const health = await requestJson({
    method: 'GET',
    url: normalizeUrl(baseUrl, '/api/wormhole/dm/root-health'),
    authHeader,
    authCookie,
    timeoutMs,
  });

  const summary = {
    ok: true,
    actions,
    state: String(health?.state || '').trim(),
    health_state: String(health?.health_state || '').trim(),
    strong_trust_blocked: Boolean(health?.strong_trust_blocked),
    external_assurance_current: Boolean(health?.external_assurance_current),
    requires_attention: Boolean(health?.requires_attention),
    next_action: String(health?.next_action || '').trim(),
    witness: {
      state: String(health?.witness?.state || '').trim(),
      health_state: String(health?.witness?.health_state || '').trim(),
      source_ref: String(health?.witness?.source_ref || '').trim(),
      age_s: safeInt(health?.witness?.age_s, 0),
      reacquire_required: Boolean(health?.witness?.reacquire_required),
      independent_quorum_met: Boolean(health?.witness?.independent_quorum_met),
    },
    transparency: {
      state: String(health?.transparency?.state || '').trim(),
      health_state: String(health?.transparency?.health_state || '').trim(),
      source_ref: String(health?.transparency?.source_ref || '').trim(),
      age_s: safeInt(health?.transparency?.age_s, 0),
      verification_required: Boolean(health?.transparency?.verification_required),
    },
    distribution: {
      manifest_fingerprint: String(distribution?.manifest_fingerprint || '').trim().toLowerCase(),
      witness_policy_fingerprint: String(distribution?.witness_policy_fingerprint || '').trim().toLowerCase(),
      external_witness_receipt_count: safeInt(distribution?.external_witness_receipt_count, 0),
      external_witness_receipts_current: Boolean(distribution?.external_witness_receipts_current),
      witness_count: safeInt(distribution?.witness_count, 0),
      witness_domain_count: safeInt(distribution?.witness_domain_count, 0),
    },
  };
  if (transparency) {
    summary.transparency_publish = {
      path: String(transparency?.path || '').trim(),
      chain_fingerprint: String(transparency?.chain_fingerprint || '').trim().toLowerCase(),
      head_binding_fingerprint: String(transparency?.head_binding_fingerprint || '').trim().toLowerCase(),
      record_count: safeInt(transparency?.record_count, 0),
    };
  }
  console.log(JSON.stringify(summary, null, 2));
}

await main().catch((error) => {
  console.error(String(error?.message || error || 'dm root external assurance sync failed').trim());
  process.exit(2);
});
