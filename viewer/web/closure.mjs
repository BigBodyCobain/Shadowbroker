#!/usr/bin/env node
/**
 * List the source files the viewer actually pulls in.
 *
 * Walks imports from the viewer's page and layout inside the prepared build
 * copy (viewer/web/.build). Useful when reviewing what borrowed code ships:
 *
 *   node viewer/web/closure.mjs            # every file in the viewer
 *   node viewer/web/closure.mjs --api      # only files that mention /api/ routes
 */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));

const EXT = ['', '.ts', '.tsx', '.js', '.jsx', '.mjs', '.json', '/index.ts', '/index.tsx', '/index.js'];
const IMPORT =
  /(?:import|export)\s+(?:[^'"`;]*?\s+from\s+)?['"]([^'"]+)['"]|import\(\s*['"]([^'"]+)['"]\s*\)|require\(\s*['"]([^'"]+)['"]\s*\)|new URL\(\s*['"]([^'"]+)['"]\s*,\s*import\.meta\.url/g;

function resolve(src, from, spec) {
  let base;
  if (spec.startsWith('@/')) base = path.join(src, spec.slice(2));
  else if (spec.startsWith('.')) base = path.resolve(path.dirname(from), spec);
  else return null; // package
  for (const ext of EXT) {
    const candidate = path.normalize(base + ext);
    if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) return candidate;
  }
  return null;
}

/** Absolute paths of every source file reachable from the viewer's page and layout. */
export function computeClosure(src) {
  const seen = new Set();
  const queue = [path.join(src, 'app', 'page.tsx'), path.join(src, 'app', 'layout.tsx')];
  while (queue.length) {
    const file = queue.pop();
    if (seen.has(file)) continue;
    seen.add(file);
    if (!/\.(tsx?|jsx?|mjs)$/.test(file)) continue;
    const text = fs.readFileSync(file, 'utf8');
    for (const match of text.matchAll(IMPORT)) {
      const target = resolve(src, file, match[1] || match[2] || match[3] || match[4]);
      if (target && !seen.has(target)) queue.push(target);
    }
  }
  return seen;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const src = path.join(here, '.build', 'src');
  const onlyApi = process.argv.includes('--api');
  const files = [...computeClosure(src)].map((f) => path.relative(src, f).split(path.sep).join('/')).sort();
  for (const rel of files) {
    if (!onlyApi) {
      console.log(rel);
      continue;
    }
    const text = fs.readFileSync(path.join(src, rel), 'utf8');
    const routes = [...new Set([...text.matchAll(/\/api\/[A-Za-z0-9_\-./${}]*/g)].map((m) => m[0]))];
    if (routes.length) console.log(`${rel}\n    ${routes.join('\n    ')}`);
  }
  if (!onlyApi) console.error(`${files.length} files`);
}
