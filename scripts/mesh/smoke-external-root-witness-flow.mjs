#!/usr/bin/env node

import fs from 'node:fs/promises';
import path from 'node:path';
import { spawn } from 'node:child_process';

const HELP_TEXT = `
ShadowBroker external root witness flow smoke

Usage:
  node scripts/mesh/smoke-external-root-witness-flow.mjs [--keep] [--workspace PATH] [--base-url URL]

Environment:
  SB_DM_ROOT_BASE_URL=http://127.0.0.1:8000
  SB_DM_ROOT_AUTH_HEADER=X-Admin-Key: change-me
  SB_DM_ROOT_AUTH_COOKIE=operator_session=...
  SB_DM_ROOT_TIMEOUT_MS=10000
  SB_DM_ROOT_SMOKE_WORKSPACE=.smoke/external-root-witness-flow
  SB_DM_ROOT_WITNESS_LABEL=witness-a
  SB_DM_ROOT_WITNESS_SOURCE_SCOPE=https_publish
  SB_DM_ROOT_WITNESS_SOURCE_LABEL=witness-a
  SB_DM_ROOT_WITNESS_INDEPENDENCE_GROUP=independent_witness_a

What it does:
  1. Generate a fresh external witness identity.
  2. Publish and import a descriptor-only package.
  3. Trigger root-distribution republish and verify the new witness is in policy.
  4. Publish and import a full signed witness receipt package.
  5. Verify external witness receipts are current in root-distribution.

Flags:
  --keep              Keep the smoke workspace instead of deleting it
  --workspace PATH    Override SB_DM_ROOT_SMOKE_WORKSPACE
  --base-url URL      Override SB_DM_ROOT_BASE_URL
  --help              Show this text
`.trim();

function parseArgs(argv) {
  const parsed = {};
  for (let index = 0; index < argv.length; index += 1) {
    const current = String(argv[index] || '').trim();
    if (!current) continue;
    if (current === '--keep') {
      parsed.keep = true;
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
  const pathValue = String(routePath || '').trim();
  if (!pathValue) {
    return base;
  }
  return `${base}/${pathValue.replace(/^\/+/, '')}`;
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
    String(args.workspace || process.env.SB_DM_ROOT_SMOKE_WORKSPACE || '.smoke/external-root-witness-flow').trim(),
  );
  const baseUrl = String(args.baseUrl || process.env.SB_DM_ROOT_BASE_URL || 'http://127.0.0.1:8000').trim();
  const timeoutMs = Math.max(1000, safeInt(process.env.SB_DM_ROOT_TIMEOUT_MS, 10000));
  const authHeader = process.env.SB_DM_ROOT_AUTH_HEADER || '';
  const authCookie = process.env.SB_DM_ROOT_AUTH_COOKIE || '';
  const label = String(process.env.SB_DM_ROOT_WITNESS_LABEL || 'witness-a').trim();
  const sourceScope = String(process.env.SB_DM_ROOT_WITNESS_SOURCE_SCOPE || 'https_publish').trim();
  const sourceLabel = String(process.env.SB_DM_ROOT_WITNESS_SOURCE_LABEL || label).trim();
  const independenceGroup = String(
    process.env.SB_DM_ROOT_WITNESS_INDEPENDENCE_GROUP || 'independent_witness_a',
  )
    .trim()
    .toLowerCase();

  const identityPath = path.join(workspace, 'witness.identity.json');
  const descriptorPath = path.join(workspace, 'root_witness_descriptor.json');
  const receiptPath = path.join(workspace, 'root_witness_receipt.json');
  const publisherScript = path.resolve(rootDir, 'scripts/mesh/publish-external-root-witness-package.mjs');

  await fs.mkdir(workspace, { recursive: true });

  const childEnv = {
    ...process.env,
    SB_DM_ROOT_BASE_URL: baseUrl,
    SB_DM_ROOT_AUTH_HEADER: authHeader,
    SB_DM_ROOT_AUTH_COOKIE: authCookie,
    SB_DM_ROOT_TIMEOUT_MS: String(timeoutMs),
    SB_DM_ROOT_WITNESS_LABEL: label,
    SB_DM_ROOT_WITNESS_SOURCE_SCOPE: sourceScope,
    SB_DM_ROOT_WITNESS_SOURCE_LABEL: sourceLabel,
    SB_DM_ROOT_WITNESS_INDEPENDENCE_GROUP: independenceGroup,
  };

  try {
    console.log('1/5 init external witness identity');
    await spawnNodeScript(publisherScript, ['--init-witness', identityPath], childEnv);

    console.log('2/5 publish and import descriptor-only package');
    await spawnNodeScript(
      publisherScript,
      ['--descriptor-only', '--witness-file', identityPath, '--output', descriptorPath],
      childEnv,
    );
    const descriptorImport = await requestJson({
      method: 'POST',
      url: normalizeUrl(baseUrl, '/api/wormhole/dm/root-witnesses/import-config'),
      authHeader,
      authCookie,
      timeoutMs,
      body: { path: descriptorPath },
    });
    assert(descriptorImport?.ok === true, 'descriptor-only import failed');

    console.log('3/5 trigger republish and verify the external witness is declared in policy');
    const identity = JSON.parse(await fs.readFile(identityPath, 'utf8'));
    const distributionAfterDescriptor = await requestJson({
      method: 'GET',
      url: normalizeUrl(baseUrl, '/api/wormhole/dm/root-distribution'),
      authHeader,
      authCookie,
      timeoutMs,
    });
    const policyWitnesses = Array.isArray(distributionAfterDescriptor?.witness_policy?.witnesses)
      ? distributionAfterDescriptor.witness_policy.witnesses
      : [];
    const declared = policyWitnesses.some(
      (item) =>
        String(item?.node_id || '').trim() === String(identity?.node_id || '').trim() &&
        String(item?.public_key || '').trim() === String(identity?.public_key || '').trim(),
    );
    assert(declared, 'external witness was not declared in the republished manifest policy');

    console.log('4/5 publish and import the full signed external witness receipt package');
    await spawnNodeScript(
      publisherScript,
      ['--witness-file', identityPath, '--output', receiptPath],
      childEnv,
    );
    const receiptImport = await requestJson({
      method: 'POST',
      url: normalizeUrl(baseUrl, '/api/wormhole/dm/root-witnesses/import-config'),
      authHeader,
      authCookie,
      timeoutMs,
      body: { path: receiptPath },
    });
    assert(receiptImport?.ok === true, 'external witness receipt import failed');

    console.log('5/5 verify current root-distribution state');
    const distributionFinal = await requestJson({
      method: 'GET',
      url: normalizeUrl(baseUrl, '/api/wormhole/dm/root-distribution'),
      authHeader,
      authCookie,
      timeoutMs,
    });
    assert(Boolean(distributionFinal?.external_witness_receipts_current), 'external witness receipts did not become current');
    assert(safeInt(distributionFinal?.external_witness_receipt_count, 0) >= 1, 'external witness receipt count did not increase');

    const health = await requestJson({
      method: 'GET',
      url: normalizeUrl(baseUrl, '/api/wormhole/dm/root-health'),
      authHeader,
      authCookie,
      timeoutMs,
    });

    const summary = {
      ok: true,
      workspace,
      manifest_fingerprint: String(distributionFinal?.manifest_fingerprint || '').trim().toLowerCase(),
      witness_policy_fingerprint: String(distributionFinal?.witness_policy_fingerprint || '').trim().toLowerCase(),
      external_witness_receipt_count: safeInt(distributionFinal?.external_witness_receipt_count, 0),
      witness_count: safeInt(distributionFinal?.witness_count, 0),
      witness_domain_count: safeInt(distributionFinal?.witness_domain_count, 0),
      witness_independent_quorum_met: Boolean(distributionFinal?.witness_independent_quorum_met),
      witness_operator_state: String(distributionFinal?.external_witness_operator_state || '').trim(),
      health_summary_state: String(health?.state || '').trim(),
      health_state: String(health?.health_state || '').trim(),
      health_next_action: String(health?.next_action || '').trim(),
    };
    console.log(JSON.stringify(summary, null, 2));
  } finally {
    if (!args.keep) {
      await fs.rm(workspace, { recursive: true, force: true });
    }
  }
}

await main().catch((error) => {
  console.error(String(error?.message || error || 'external witness flow smoke failed').trim());
  process.exit(2);
});
