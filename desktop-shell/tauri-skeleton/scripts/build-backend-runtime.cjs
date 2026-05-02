#!/usr/bin/env node

const fs = require('node:fs');
const path = require('node:path');

const scriptDir = __dirname;
const tauriDir = path.resolve(scriptDir, '..');
const repoRoot = path.resolve(tauriDir, '..', '..');
const backendDir = path.join(repoRoot, 'backend');
const outputDir = path.join(tauriDir, 'src-tauri', 'backend-runtime');
const venvMarkerPath = path.join(backendDir, '.venv-dir');
const releaseAttestationPath = path.join(backendDir, 'data', 'release_attestation.json');
const stagedReleaseAttestationPath = path.join(
  outputDir,
  'data',
  'release_attestation.json',
);

const excludedNames = new Set([
  '.env',
  '.pytest_cache',
  '__pycache__',
  'backend.egg-info',
  'build',
  'data',
  'tests',
]);

const excludedFiles = new Set([
  'pytest.ini',
]);

function backendPythonPath() {
  let venvDir = 'venv';
  try {
    const persisted = fs.readFileSync(venvMarkerPath, 'utf8').trim();
    if (persisted) {
      venvDir = persisted;
    }
  } catch {}

  if (process.platform === 'win32') {
    return path.join(backendDir, venvDir, 'Scripts', 'python.exe');
  }
  return path.join(backendDir, venvDir, 'bin', 'python3');
}

function shouldCopy(srcPath) {
  const relativePath = path.relative(backendDir, srcPath);
  if (!relativePath) return true;

  const parts = relativePath.split(path.sep);
  return parts.every((part, index) => {
    const isLeaf = index === parts.length - 1;
    if (excludedNames.has(part)) return false;
    if (isLeaf && excludedFiles.has(part)) return false;
    if (/^test_.*\.py$/i.test(part)) return false;
    return true;
  });
}

function ensureRuntimePrereqs() {
  if (!fs.existsSync(path.join(backendDir, 'main.py'))) {
    throw new Error(`Missing backend/main.py at ${backendDir}`);
  }
  if (!fs.existsSync(backendPythonPath())) {
    throw new Error(
      `Missing bundled backend Python runtime at ${backendPythonPath()}. ` +
      'Create the backend venv before packaging the desktop app.',
    );
  }
  if (!fs.existsSync(path.join(backendDir, 'node_modules', 'ws'))) {
    throw new Error(
      `Missing backend/node_modules/ws at ${path.join(backendDir, 'node_modules', 'ws')}. ` +
      'Install backend Node dependencies before packaging the desktop app.',
    );
  }
}

function stageBackendRuntime() {
  fs.rmSync(outputDir, { recursive: true, force: true });
  fs.cpSync(backendDir, outputDir, {
    recursive: true,
    filter: shouldCopy,
  });
  stageReleaseAttestation();
}

function stageReleaseAttestation() {
  if (!fs.existsSync(releaseAttestationPath)) {
    console.warn(`backend-runtime staged without release attestation: ${releaseAttestationPath}`);
    return;
  }
  fs.mkdirSync(path.dirname(stagedReleaseAttestationPath), { recursive: true });
  fs.copyFileSync(releaseAttestationPath, stagedReleaseAttestationPath);
}

function writeBundleVersion() {
  const versionPath = path.join(outputDir, '.bundle-version');
  const pkg = JSON.parse(
    fs.readFileSync(path.join(repoRoot, 'desktop-shell', 'package.json'), 'utf8'),
  );
  fs.writeFileSync(versionPath, `${pkg.version || '0.0.0'}\n`, 'utf8');
}

function fileCount(root) {
  let count = 0;
  for (const entry of fs.readdirSync(root, { withFileTypes: true })) {
    const fullPath = path.join(root, entry.name);
    if (entry.isDirectory()) {
      count += fileCount(fullPath);
    } else {
      count += 1;
    }
  }
  return count;
}

ensureRuntimePrereqs();
stageBackendRuntime();
writeBundleVersion();
console.log(`backend-runtime staged: ${fileCount(outputDir)} files`);
