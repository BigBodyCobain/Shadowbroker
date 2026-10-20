#!/usr/bin/env node

const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const scriptDir = __dirname;
const tauriDir = path.resolve(scriptDir, '..');
const repoRoot = path.resolve(tauriDir, '..', '..');
const frontendDir = path.join(repoRoot, 'frontend');
const buildRoot = path.join(repoRoot, '.desktop-export-build');
const buildFrontendDir = path.join(buildRoot, 'frontend');
const buildOutDir = path.join(buildFrontendDir, 'out');
const liveOutDir = path.join(frontendDir, 'out');
const excludedPaths = [
  'node_modules',
  '.next',
  'out',
  'src/app/api',
  'src/proxy.ts',
];

function normalizeRelativePath(target) {
  return target.split(path.sep).join('/');
}

function shouldCopy(srcPath) {
  const relativePath = path.relative(frontendDir, srcPath);
  if (!relativePath) {
    return true;
  }

  const normalized = normalizeRelativePath(relativePath);
  return !excludedPaths.some(
    (excluded) => normalized === excluded || normalized.startsWith(`${excluded}/`),
  );
}

function prepareBuildTree() {
  fs.rmSync(buildRoot, { recursive: true, force: true });
  fs.cpSync(frontendDir, buildFrontendDir, {
    recursive: true,
    filter: shouldCopy,
  });

  const stagedLayoutPath = path.join(buildFrontendDir, 'src', 'app', 'layout.tsx');
  if (fs.existsSync(stagedLayoutPath)) {
    const layoutSource = fs.readFileSync(stagedLayoutPath, 'utf8');
    // CRLF compatibility: on Windows checkouts without ``core.autocrlf=input``
    // (the default) layout.tsx has CRLF line endings, but the original regexes
    // only matched LF. The strip silently no-op'd, ``force-dynamic`` stayed,
    // and Next's static-export refused to render ``/_not-found`` ("Page with
    // `dynamic = \"force-dynamic\"` couldn't be exported"). Use ``\r?\n`` so
    // the strip works regardless of line-ending normalization.
    fs.writeFileSync(
      stagedLayoutPath,
      layoutSource
        .replace(/\r?\n\/\/ The dashboard is a live local runtime[\s\S]*?client polling ever hydrates\.\r?\n/g, '\n')
        .replace(/\r?\nexport const dynamic = ['"]force-dynamic['"];\r?\n/g, '\n')
        .replace(/\r?\nexport const revalidate = 0;\r?\n/g, '\n'),
    );
  }

  const liveNodeModules = path.join(frontendDir, 'node_modules');
  const stagedNodeModules = path.join(buildFrontendDir, 'node_modules');
  if (!fs.existsSync(liveNodeModules)) {
    throw new Error(`Missing frontend/node_modules at ${liveNodeModules}`);
  }
  fs.symlinkSync(liveNodeModules, stagedNodeModules, 'junction');
}

function runExportBuild() {
  const env = {
    ...process.env,
    NEXT_OUTPUT: 'export',
  };

  const result =
    process.platform === 'win32'
      ? spawnSync(
          process.env.ComSpec || 'cmd.exe',
          ['/d', '/s', '/c', 'npm.cmd run build -- --webpack'],
          {
            cwd: buildFrontendDir,
            env,
            stdio: 'inherit',
          },
        )
      : spawnSync('npm', ['run', 'build', '--', '--webpack'], {
          cwd: buildFrontendDir,
          env,
          stdio: 'inherit',
        });

  if (result.error) {
    throw result.error;
  }
  if (typeof result.status === 'number' && result.status !== 0) {
    throw new Error(`Frontend export build failed with exit code ${result.status}.`);
  }
}

function syncBuildOutput() {
  if (!fs.existsSync(buildOutDir)) {
    throw new Error(`Desktop export did not produce ${buildOutDir}`);
  }
  fs.rmSync(liveOutDir, { recursive: true, force: true });
  fs.cpSync(buildOutDir, liveOutDir, {
    recursive: true,
  });
}

try {
  prepareBuildTree();
  runExportBuild();
  syncBuildOutput();
} finally {
  fs.rmSync(buildRoot, { recursive: true, force: true });
}
