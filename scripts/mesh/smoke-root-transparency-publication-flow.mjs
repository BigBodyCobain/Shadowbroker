#!/usr/bin/env node

import fs from 'node:fs/promises';
import path from 'node:path';

const HELP_TEXT = `
ShadowBroker root transparency publication smoke

Usage:
  node scripts/mesh/smoke-root-transparency-publication-flow.mjs [--keep] [--workspace PATH] [--base-url URL]

Environment:
  SB_DM_ROOT_BASE_URL=http://127.0.0.1:8000
  SB_DM_ROOT_AUTH_HEADER=X-Admin-Key: change-me
  SB_DM_ROOT_AUTH_COOKIE=operator_session=...
  SB_DM_ROOT_TIMEOUT_MS=10000
  SB_DM_ROOT_TRANSPARENCY_SMOKE_WORKSPACE=.smoke/root-transparency-publication
  SB_DM_ROOT_TRANSPARENCY_MAX_RECORDS=64

What it does:
  1. Fetch the current root transparency record.
  2. Publish the transparency ledger to a chosen local file through the operator endpoint.
  3. Read the published ledger back through the published-ledger endpoint.
  4. Verify binding and chain fingerprints match the live transparency state.

Flags:
  --keep              Keep the smoke workspace instead of deleting it
  --workspace PATH    Override SB_DM_ROOT_TRANSPARENCY_SMOKE_WORKSPACE
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

  const workspace = path.resolve(
    String(
      args.workspace || process.env.SB_DM_ROOT_TRANSPARENCY_SMOKE_WORKSPACE || '.smoke/root-transparency-publication',
    ).trim(),
  );
  const baseUrl = String(args.baseUrl || process.env.SB_DM_ROOT_BASE_URL || 'http://127.0.0.1:8000').trim();
  const timeoutMs = Math.max(1000, safeInt(process.env.SB_DM_ROOT_TIMEOUT_MS, 10000));
  const authHeader = process.env.SB_DM_ROOT_AUTH_HEADER || '';
  const authCookie = process.env.SB_DM_ROOT_AUTH_COOKIE || '';
  const maxRecords = Math.max(1, safeInt(process.env.SB_DM_ROOT_TRANSPARENCY_MAX_RECORDS, 64));
  const ledgerPath = path.join(workspace, 'root_transparency_ledger.json');

  await fs.mkdir(workspace, { recursive: true });

  try {
    console.log('1/4 fetch current root transparency state');
    const current = await requestJson({
      method: 'GET',
      url: normalizeUrl(baseUrl, '/api/wormhole/dm/root-transparency'),
      authHeader,
      authCookie,
      timeoutMs,
    });
    assert(Boolean(current?.record_fingerprint), 'current root transparency record fingerprint missing');
    assert(Boolean(current?.binding_fingerprint), 'current root transparency binding fingerprint missing');

    console.log('2/4 publish transparency ledger to a local file through the operator endpoint');
    const published = await requestJson({
      method: 'POST',
      url: normalizeUrl(baseUrl, '/api/wormhole/dm/root-transparency/ledger/publish'),
      authHeader,
      authCookie,
      timeoutMs,
      body: { path: ledgerPath, max_records: maxRecords },
    });
    assert(Boolean(published?.path), 'published transparency ledger path missing');
    assert(Boolean(published?.chain_fingerprint), 'published transparency chain fingerprint missing');

    console.log('3/4 read the published ledger back through the published-ledger endpoint');
    const publishedReadback = await requestJson({
      method: 'GET',
      url: `${normalizeUrl(baseUrl, '/api/wormhole/dm/root-transparency/ledger/published')}?path=${encodeURIComponent(ledgerPath)}`,
      authHeader,
      authCookie,
      timeoutMs,
    });
    assert(Boolean(publishedReadback?.chain_fingerprint), 'published ledger readback chain fingerprint missing');
    assert(Boolean(publishedReadback?.head_binding_fingerprint), 'published ledger readback head binding missing');

    console.log('4/4 verify the exported ledger matches live transparency state');
    assert(
      String(publishedReadback.chain_fingerprint || '').trim().toLowerCase() ===
        String(published.chain_fingerprint || '').trim().toLowerCase(),
      'published ledger chain fingerprint mismatch',
    );
    assert(
      String(publishedReadback.head_binding_fingerprint || '').trim().toLowerCase() ===
        String(current.binding_fingerprint || '').trim().toLowerCase(),
      'published ledger binding fingerprint does not match current transparency binding',
    );
    assert(
      String(publishedReadback.current_record_fingerprint || '').trim().toLowerCase() ===
        String(current.record_fingerprint || '').trim().toLowerCase(),
      'published ledger head record does not match current transparency record',
    );

    const ledgerStat = await fs.stat(ledgerPath);
    const summary = {
      ok: true,
      workspace,
      ledger_path: ledgerPath,
      ledger_size_bytes: ledgerStat.size,
      record_fingerprint: String(current.record_fingerprint || '').trim().toLowerCase(),
      binding_fingerprint: String(current.binding_fingerprint || '').trim().toLowerCase(),
      chain_fingerprint: String(publishedReadback.chain_fingerprint || '').trim().toLowerCase(),
      record_count: safeInt(publishedReadback.record_count, 0),
    };
    console.log(JSON.stringify(summary, null, 2));
  } finally {
    if (!args.keep) {
      await fs.rm(workspace, { recursive: true, force: true });
    }
  }
}

await main().catch((error) => {
  console.error(String(error?.message || error || 'root transparency publication smoke failed').trim());
  process.exit(2);
});
