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
 *   node viewer/web/build.mjs --prepare-only  # stop after step 3
 */

import { spawnSync } from 'node:child_process';
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
// No secret may be visible to the build: Next inlines NEXT_PUBLIC_* values.
for (const name of Object.keys(env)) {
  if (name.startsWith('NEXT_PUBLIC_') && name !== 'NEXT_PUBLIC_SB_DATA_BASE') delete env[name];
}

// Run Next's entry script with this Node directly: no shell, no path quoting.
const next = path.join(nodeModules, 'next', 'dist', 'bin', 'next');
run(process.execPath, [next, 'build', '--webpack'], { cwd: buildDir, env });

rmrf(distDir);
fs.cpSync(path.join(buildDir, 'out'), distDir, { recursive: true });
console.log(`[viewer build] static site written to ${path.relative(repo, distDir)}`);

run(process.execPath, [path.join(here, 'check-dist.mjs'), distDir]);
