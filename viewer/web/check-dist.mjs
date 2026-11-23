#!/usr/bin/env node
/**
 * Inspect a built public viewer and fail if anything private is in it.
 *
 * Checks, all on the finished files a visitor would download:
 *   1. no secret *name* from backend/.env.example (API keys, tokens, passwords);
 *   2. no key-shaped string (common API key formats, private key blocks);
 *   3. every app route (/api/...) still mentioned in the code is on the short
 *      list in api-allowlist.json. Routes that send, post, change settings or
 *      spend credits are never on that list, so their code must be gone;
 *   4. the network guard and the Content-Security-Policy are present, and the
 *      policy has no wildcard connect source.
 *
 * Usage: node viewer/web/check-dist.mjs [distDir] [--list-api]
 */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(here, '..', '..');
const args = process.argv.slice(2);
const listApi = args.includes('--list-api');
const distDir = path.resolve(args.find((a) => !a.startsWith('--')) || path.join(here, 'dist'));

const TEXT_EXT = new Set(['.js', '.mjs', '.html', '.css', '.json', '.txt', '.map', '.svg', '.xml', '.webmanifest']);

function walk(dir, out = []) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(full, out);
    else out.push(full);
  }
  return out;
}

function secretNames() {
  const names = new Set();
  const example = path.join(repo, 'backend', '.env.example');
  if (fs.existsSync(example)) {
    for (const line of fs.readFileSync(example, 'utf8').split(/\r?\n/)) {
      const m = /^\s*#?\s*([A-Z][A-Z0-9_]{3,})\s*=/.exec(line);
      if (m && /(KEY|TOKEN|SECRET|PASSWORD|PASSCODE|CREDENTIAL)/.test(m[1])) names.add(m[1]);
    }
  }
  // Always checked, even if .env.example drops them.
  for (const name of ['ADMIN_KEY', 'OPENSKY_CLIENT_SECRET', 'AIS_API_KEY', 'SHODAN_API_KEY', 'CARTO_API_KEY']) {
    names.add(name);
  }
  return [...names];
}

const KEY_SHAPES = [
  ['OpenAI/Anthropic-style key', /\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{24,}\b/g],
  ['AWS access key', /\bAKIA[0-9A-Z]{16}\b/g],
  ['Google API key', /\bAIza[0-9A-Za-z_-]{35}\b/g],
  ['GitHub token', /\bgh[pousr]_[A-Za-z0-9]{30,}\b/g],
  ['Slack token', /\bxox[abprs]-[A-Za-z0-9-]{10,}\b/g],
  // Assembled from parts so this file does not itself look like a key block.
  ['private key block', new RegExp(`-----BEGIN [A-Z ]*${'PRIVATE'} ${'KEY'}-----`, 'g')],
  ['bearer token literal', /\bBearer\s+[A-Za-z0-9._-]{24,}\b/g],
  ['key in URL', /[?&](?:api[_-]?key|apikey|access[_-]?token|token|secret)=[A-Za-z0-9._-]{12,}/gi],
];

const API_PATH = /\/api\/[A-Za-z0-9_\-./]*/g;

function normalizeApi(p) {
  return p.replace(/\/+$/, '').replace(/\.$/, '') || '/api';
}

const problems = [];
const apiSeen = new Map(); // path -> first file

if (!fs.existsSync(distDir)) {
  console.error(`[check-dist] ${distDir} does not exist. Build first.`);
  process.exit(2);
}

const names = secretNames();
const files = walk(distDir);
let scanned = 0;
let guardPresent = false;
let cspContent = null;

for (const file of files) {
  if (!TEXT_EXT.has(path.extname(file).toLowerCase())) continue;
  scanned += 1;
  const rel = path.relative(distDir, file).replace(/\\/g, '/');
  const text = fs.readFileSync(file, 'utf8');

  for (const name of names) {
    if (text.includes(name)) problems.push(`secret name ${name} appears in ${rel}`);
  }
  for (const [label, pattern] of KEY_SHAPES) {
    pattern.lastIndex = 0;
    if (pattern.test(text)) problems.push(`${label} pattern appears in ${rel}`);
  }
  for (const match of text.matchAll(API_PATH)) {
    const p = normalizeApi(match[0]);
    if (!apiSeen.has(p)) apiSeen.set(p, rel);
  }
  if (text.includes('__sbViewerGuard')) guardPresent = true;
  if (rel === 'index.html') {
    const m = /<meta[^>]+http-equiv="Content-Security-Policy"[^>]+content="([^"]+)"/i.exec(text);
    if (m) cspContent = m[1].replace(/&#x27;/g, "'").replace(/&amp;/g, '&');
  }
}

if (listApi) {
  for (const p of [...apiSeen.keys()].sort()) console.log(p);
  process.exit(0);
}

const allow = new Set(JSON.parse(fs.readFileSync(path.join(here, 'api-allowlist.json'), 'utf8')).paths);
for (const [p, rel] of [...apiSeen.entries()].sort()) {
  if (!allow.has(p)) problems.push(`app route ${p} is still in the public build (${rel})`);
}

if (!guardPresent) problems.push('network guard is missing from the build');
if (!cspContent) {
  problems.push('index.html has no Content-Security-Policy meta tag');
} else {
  const connect = /connect-src ([^;]+)/.exec(cspContent)?.[1] || '';
  if (!connect) problems.push('Content-Security-Policy has no connect-src');
  if (/(^|\s)(\*|https:|http:|wss?:)(\s|$)/.test(connect)) {
    problems.push(`Content-Security-Policy connect-src is too broad: ${connect}`);
  }
  if (/'unsafe-eval'/.test(cspContent)) problems.push("Content-Security-Policy allows 'unsafe-eval'");
}

if (problems.length > 0) {
  console.error(`[check-dist] FAILED: ${problems.length} problem(s) in ${path.relative(repo, distDir)}`);
  for (const p of problems) console.error(`  - ${p}`);
  process.exit(1);
}
console.log(
  `[check-dist] OK: ${scanned} text files, ${names.length} secret names, ${apiSeen.size} app route mention(s), all allowed.`,
);
