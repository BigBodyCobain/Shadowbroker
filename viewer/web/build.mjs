#!/usr/bin/env node
/**
 * Build the public viewer.
 *
 * The viewer is the full app's frontend with the owner-only parts taken out,
 * built as a plain static site. Nothing in frontend/ is edited. Instead:
 *
 *   1. frontend/ is copied to viewer/web/.build/ (no API routes, no proxy);
 *   2. viewer/web/overlay/ is copied on top: the viewer's own page, layout,
 *      data loader, network guard and inert stand-ins for owner-only modules;
 *   3. the cuts in viewer/web/cuts.json are applied. Each cut must match
 *      exactly as many times as it says, so if the app changes underneath it
 *      the build stops instead of quietly shipping a control;
 *   4. Next builds the copy as a static export into viewer/web/dist/;
 *   5. check-dist.mjs inspects the result and fails the build if any
 *      owner-only route or secret name made it into the public files.
 *
 * Usage:
 *   node viewer/web/build.mjs                 # build + checks
 *   NEXT_PUBLIC_SB_DATA_BASE=https://data.example.org node viewer/web/build.mjs
 *   NEXT_PUBLIC_SB_BASE_PATH=/map ...        publish under a sub-folder of another site
 *   NEXT_PUBLIC_SB_STALE_AFTER_S=1500 ...    data older than this is shown as stale (default 240)
 *   node viewer/web/build.mjs --prepare-only  # stop after step 3
 */

import { spawnSync } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { computeClosure } from './closure.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(here, '..', '..');
const frontend = path.join(repo, 'frontend');
const buildDir = path.join(here, '.build');
const overlayDir = path.join(here, 'overlay');
const distDir = path.join(here, 'dist');
const prepareOnly = process.argv.includes('--prepare-only');

const nodeModules = path.resolve(process.env.SB_VIEWER_NODE_MODULES || path.join(frontend, 'node_modules'));

/** Copied from frontend/ into the build folder. */
const COPY = [
  'src',
  'public',
  'package.json',
  'tsconfig.json',
  'tsconfig.build.json',
  'postcss.config.mjs',
  'tailwind.config.ts',
];

/** Removed from the copy: the server side of the app and its tests. */
const REMOVE = ['src/app/api', 'src/proxy.ts', 'src/__tests__'];

function fail(message) {
  console.error(`\n[viewer build] ${message}`);
  process.exit(1);
}

function rmrf(target) {
  fs.rmSync(target, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
}

function copyTree(from, to) {
  fs.cpSync(from, to, {
    recursive: true,
    force: true,
    filter: (src) => {
      const base = path.basename(src);
      return base !== 'node_modules' && base !== '.next' && base !== 'out' && !/\.test\.tsx?$/.test(base);
    },
  });
}

function applyCuts() {
  const cuts = JSON.parse(fs.readFileSync(path.join(here, 'cuts.json'), 'utf8')).cuts;
  for (const cut of cuts) {
    const file = path.join(buildDir, cut.file);
    if (!fs.existsSync(file)) fail(`cut "${cut.why}": ${cut.file} no longer exists`);
    let text = fs.readFileSync(file, 'utf8').replace(/\r\n/g, '\n');
    const expected = cut.count ?? 1;
    const found = text.split(cut.find).length - 1;
    if (found !== expected) {
      fail(
        `cut "${cut.why}" in ${cut.file}: expected ${expected} match(es), found ${found}.\n` +
          'The app changed under this cut. Update viewer/web/cuts.json before building.',
      );
    }
    text = text.split(cut.find).join(cut.replace);
    if (cut.prepend) {
      // An import goes after a leading 'use client' directive, never before it.
      const directive = /^(['"])use client\1;?\s*\n/.exec(text);
      text = directive
        ? `${directive[0]}${cut.prepend}\n${text.slice(directive[0].length)}`
        : `${cut.prepend}\n${text}`;
    }
    fs.writeFileSync(file, text);
  }
  console.log(`[viewer build] applied ${cuts.length} cut(s)`);
}

/**
 * An overlay file either replaces an app file of the same path, or is one of
 * the viewer's own new files. If the app renames a file that the overlay
 * replaces, the stand-in would silently stop applying, so stop the build.
 */
const OVERLAY_NEW = [/^src\/viewer\//, /^next\.config\.ts$/];

function checkOverlay() {
  const walk = (dir, out = []) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) walk(full, out);
      else out.push(path.relative(overlayDir, full).split(path.sep).join('/'));
    }
    return out;
  };
  for (const rel of walk(overlayDir)) {
    if (OVERLAY_NEW.some((pattern) => pattern.test(rel))) continue;
    if (!fs.existsSync(path.join(frontend, rel))) {
      fail(
        `overlay file ${rel} replaces nothing: frontend/${rel} does not exist.
` +
          'The app moved or renamed it. Point the overlay at the new path.',
      );
    }
  }
}

/**
 * Delete every source file the viewer's page does not reach. What is left is
 * exactly the code that ships, so owner-only modules cannot ride along, and
 * type checking only covers code that is actually in the viewer.
 */
function pruneUnreachable() {
  const src = path.join(buildDir, 'src');
  const keep = computeClosure(src);
  let removed = 0;
  const walk = (dir) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        walk(full);
        if (fs.readdirSync(full).length === 0) fs.rmdirSync(full);
      } else if (/\.(tsx?|jsx?|mjs)$/.test(entry.name) && !entry.name.endsWith('.d.ts') && !keep.has(full)) {
        fs.unlinkSync(full);
        removed += 1;
      }
    }
  };
  walk(src);
  console.log(`[viewer build] kept ${keep.size} reachable source files, removed ${removed}`);
}

/**
 * Copy the public agent skill into the site so visitors can read every line
 * of it before giving it to an agent ("view and vet").
 *
 * The files are published byte for byte with a SHA-256 fingerprint each. The
 * build stops if one contains anything a reader could not see: invisible or
 * direction-changing characters, stray control characters, or (in the
 * instructions) an HTML comment that a Markdown viewer would hide.
 */
const SKILL_FILES = [
  { name: 'SKILL.md', role: 'instructions' },
  { name: 'sb_public.py', role: 'code' },
  { name: 'sb_camera.py', role: 'code' },
  { name: 'skill.yaml', role: 'manifest' },
];
// Control characters, soft hyphen, zero-width and direction marks, variation
// selectors, and the "tag" block used to smuggle invisible text.
const HIDDEN_CHARS =
  /[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F\u00AD\u061C\u180E\u200B-\u200F\u202A-\u202E\u2060-\u2064\u2066-\u2069\uFEFF\uFFF9-\uFFFB\uFE00-\uFE0E\u{E0000}-\u{E007F}\u{E0100}-\u{E01EF}]/u;

function publishSkill() {
  const skillDir = path.join(repo, 'openclaw-skills', 'shadowbroker-public');
  if (!fs.existsSync(skillDir)) return;
  const outDir = path.join(buildDir, 'public', 'skill');
  fs.mkdirSync(outDir, { recursive: true });
  const files = [];
  for (const { name, role } of SKILL_FILES) {
    const text = fs.readFileSync(path.join(skillDir, name), 'utf8').replace(/\r\n/g, '\n');
    const hidden = HIDDEN_CHARS.exec(text);
    if (hidden) {
      const line = text.slice(0, hidden.index).split('\n').length;
      fail(`skill file ${name} has a hidden character (U+${hidden[0].codePointAt(0).toString(16).toUpperCase()}) on line ${line}`);
    }
    if (name.endsWith('.md') && text.includes('<!--')) {
      fail(`skill file ${name} contains an HTML comment, which a Markdown viewer would hide from a reader`);
    }
    const bytes = Buffer.from(text, 'utf8');
    fs.writeFileSync(path.join(outDir, name), bytes);
    files.push({
      name,
      role,
      bytes: bytes.length,
      lines: text.split('\n').length - (text.endsWith('\n') ? 1 : 0),
      sha256: crypto.createHash('sha256').update(bytes).digest('hex'),
    });
  }
  const manifest = {
    name: 'shadowbroker-public',
    source: 'https://github.com/BigBodyCobain/Shadowbroker/tree/main/openclaw-skills/shadowbroker-public',
    checks: [
      'Shown byte for byte as published (line endings normalised to LF)',
      'No invisible, zero-width or direction-changing characters',
      'No hidden comments in the instructions',
    ],
    files,
  };
  fs.writeFileSync(path.join(outDir, 'manifest.json'), `${JSON.stringify(manifest, null, 2)}\n`);
  console.log(`[viewer build] published agent skill for viewing (${files.length} files)`);
}

function linkNodeModules() {
  if (!fs.existsSync(path.join(nodeModules, 'next', 'package.json'))) {
    fail(`no installed packages at ${nodeModules}. Run "npm ci" in frontend/ first.`);
  }
  const link = path.join(buildDir, 'node_modules');
  fs.symlinkSync(nodeModules, link, 'junction');
}

function unlinkNodeModules() {
  // Remove the link itself first so cleaning never walks into real packages.
  const link = path.join(buildDir, 'node_modules');
  try {
    if (fs.lstatSync(link)) {
      try {
        fs.rmdirSync(link);
      } catch {
        fs.unlinkSync(link);
      }
    }
  } catch {
    /* not there */
  }
}

function prepare() {
  unlinkNodeModules();
  fs.mkdirSync(buildDir, { recursive: true });
  // Empty the folder rather than delete it: a shell sitting in it would block that.
  for (const entry of fs.readdirSync(buildDir)) rmrf(path.join(buildDir, entry));
  for (const entry of COPY) {
    const from = path.join(frontend, entry);
    if (!fs.existsSync(from)) fail(`frontend/${entry} is missing`);
    copyTree(from, path.join(buildDir, entry));
  }
  for (const entry of REMOVE) rmrf(path.join(buildDir, entry));
  checkOverlay();
  copyTree(overlayDir, buildDir);
  applyCuts();
  pruneUnreachable();

  // MapLibre's worker must be served as its own file.
  const worker = path.join(nodeModules, 'maplibre-gl', 'dist', 'maplibre-gl-worker.mjs');
  if (fs.existsSync(worker)) fs.copyFileSync(worker, path.join(buildDir, 'public', 'maplibre-gl-worker.mjs'));

  publishSkill();
  linkNodeModules();
  console.log(`[viewer build] prepared ${path.relative(repo, buildDir)}`);
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, { stdio: 'inherit', ...options });
  if (result.status !== 0) fail(`${command} ${args.join(' ')} exited with ${result.status}`);
}

prepare();
if (prepareOnly) process.exit(0);

const env = {
  ...process.env,
  NEXT_TELEMETRY_DISABLED: '1',
  NEXT_PUBLIC_SB_DATA_BASE: process.env.NEXT_PUBLIC_SB_DATA_BASE || '/live-data',
};
// No secret may be visible to the build: Next inlines NEXT_PUBLIC_* values,
// so only the names below get through.
const PUBLIC_SETTINGS = new Set([
  'NEXT_PUBLIC_SB_DATA_BASE',
  'NEXT_PUBLIC_SB_BASE_PATH',
  'NEXT_PUBLIC_SB_STALE_AFTER_S',
  'NEXT_PUBLIC_SB_CHAT_URL',
  'NEXT_PUBLIC_SB_CHAT_KEY',
  'NEXT_PUBLIC_SB_CHAT_PROVIDERS',
]);
for (const name of Object.keys(env)) {
  if (name.startsWith('NEXT_PUBLIC_') && !PUBLIC_SETTINGS.has(name)) delete env[name];
}

// Publishing in a sub-folder ("/map"): lower-case folder names only, no trailing slash.
if (env.NEXT_PUBLIC_SB_BASE_PATH && !/^(\/[a-z0-9][a-z0-9-]*)+$/.test(env.NEXT_PUBLIC_SB_BASE_PATH)) {
  fail(`NEXT_PUBLIC_SB_BASE_PATH must look like /map, got "${env.NEXT_PUBLIC_SB_BASE_PATH}"`);
}
if (env.NEXT_PUBLIC_SB_STALE_AFTER_S && !/^[1-9][0-9]{1,5}$/.test(env.NEXT_PUBLIC_SB_STALE_AFTER_S)) {
  fail(`NEXT_PUBLIC_SB_STALE_AFTER_S must be a number of seconds, got "${env.NEXT_PUBLIC_SB_STALE_AFTER_S}"`);
}

// Optional chat settings from viewer/web/chat.config.json (see viewer/chat/README.md).
const chatConfigPath = path.join(here, 'chat.config.json');
if (fs.existsSync(chatConfigPath)) {
  const chat = JSON.parse(fs.readFileSync(chatConfigPath, 'utf8'));
  env.NEXT_PUBLIC_SB_CHAT_URL = String(chat.url || '');
  env.NEXT_PUBLIC_SB_CHAT_KEY = String(chat.anonKey || '');
  env.NEXT_PUBLIC_SB_CHAT_PROVIDERS = (chat.providers || []).join(',');
}
checkChatKey(env.NEXT_PUBLIC_SB_CHAT_URL || '', env.NEXT_PUBLIC_SB_CHAT_KEY || '');

/**
 * The chat key is compiled into the public site, so it must be the project's
 * public ("anon" / publishable) key. A service or secret key would hand every
 * visitor full control of the chat database: refuse to build with one.
 */
function checkChatKey(url, key) {
  if (!url && !key) return;
  if (!url || !key) fail('chat needs both a url and an anonKey, or neither');
  let parsedUrl;
  try {
    parsedUrl = new URL(url);
  } catch {
    fail('the chat url is not a valid address');
  }
  const local = parsedUrl.hostname === '127.0.0.1' || parsedUrl.hostname === 'localhost';
  if (parsedUrl.protocol !== 'https:' && !local) fail('the chat url must be https');
  if (/^sb_secret_/i.test(key)) fail('the chat key is a SECRET key. Use the publishable (anon) key.');
  const parts = key.split('.');
  if (parts.length === 3) {
    let role = '';
    try {
      role = JSON.parse(Buffer.from(parts[1], 'base64url').toString('utf8')).role || '';
    } catch {
      fail('the chat key is not a readable token');
    }
    if (role !== 'anon') fail(`the chat key has role "${role}". Only the public "anon" key may be used.`);
  } else if (!/^sb_publishable_/i.test(key)) {
    fail('the chat key is neither an anon token nor a publishable key');
  }
}

// Run Next's entry script with this Node directly: no shell, no path quoting.
const next = path.join(nodeModules, 'next', 'dist', 'bin', 'next');
run(process.execPath, [next, 'build', '--webpack'], { cwd: buildDir, env });

rmrf(distDir);
fs.cpSync(path.join(buildDir, 'out'), distDir, { recursive: true });
console.log(`[viewer build] static site written to ${path.relative(repo, distDir)}`);

run(process.execPath, [path.join(here, 'check-dist.mjs'), distDir]);
