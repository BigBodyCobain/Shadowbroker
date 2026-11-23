#!/usr/bin/env node
/**
 * Local preview of the public viewer. Not for production.
 *
 * Serves viewer/web/dist as the site and a data folder (the bridge's --out)
 * under /live-data, the way a static host plus a data host would.
 *
 *   node viewer/web/serve.mjs [--port 4173] [--data viewer/web/.data]
 */

import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
const arg = (name, fallback) => {
  const i = args.indexOf(name);
  return i >= 0 && args[i + 1] ? args[i + 1] : fallback;
};
const port = Number(arg('--port', process.env.PORT || '4173'));
const siteDir = path.resolve(arg('--site', path.join(here, 'dist')));
const dataDir = path.resolve(arg('--data', path.join(here, '.data')));

const TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.geojson': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.webp': 'image/webp',
  '.ico': 'image/x-icon',
  '.woff2': 'font/woff2',
  '.txt': 'text/plain; charset=utf-8',
};

function send(res, status, body, headers = {}) {
  res.writeHead(status, headers);
  res.end(body);
}

function serveFile(res, root, relPath, cacheControl) {
  const full = path.normalize(path.join(root, relPath));
  if (!full.startsWith(root)) return send(res, 403, 'Forbidden');
  fs.stat(full, (err, stat) => {
    if (err || !stat.isFile()) return send(res, 404, 'Not found');
    res.writeHead(200, {
      'Content-Type': TYPES[path.extname(full).toLowerCase()] || 'application/octet-stream',
      'Content-Length': stat.size,
      'Cache-Control': cacheControl,
    });
    fs.createReadStream(full).pipe(res);
  });
}

http
  .createServer((req, res) => {
    if (req.method !== 'GET' && req.method !== 'HEAD') return send(res, 405, 'Read-only');
    const url = new URL(req.url, 'http://localhost');
    let pathname = decodeURIComponent(url.pathname);
    if (pathname.startsWith('/live-data/')) {
      // The manifest must always be fresh; versioned data files may be cached.
      const rel = pathname.slice('/live-data/'.length);
      return serveFile(res, dataDir, rel, rel === 'manifest.json' ? 'no-store' : 'public, max-age=60');
    }
    if (pathname.endsWith('/')) pathname += 'index.html';
    return serveFile(res, siteDir, pathname.slice(1), 'no-cache');
  })
  .listen(port, '127.0.0.1', () => {
    console.log(`viewer preview on http://127.0.0.1:${port}  (site: ${siteDir}, data: ${dataDir})`);
  });
