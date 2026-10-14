#!/usr/bin/env node

const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const scriptDir = __dirname;
const tauriDir = path.resolve(scriptDir, '..');
const repoRoot = path.resolve(tauriDir, '..', '..');
const backendDir = path.join(repoRoot, 'backend');
const privacyCoreDir = path.join(repoRoot, 'privacy-core');
const outputDir = path.join(tauriDir, 'src-tauri', 'backend-runtime');
const venvMarkerPath = path.join(backendDir, '.venv-dir');
const releaseAttestationPath = path.join(backendDir, 'data', 'release_attestation.json');
const stagedReleaseAttestationPath = path.join(
  outputDir,
  'data',
  'release_attestation.json',
);
const runtimeLayoutVersion = 2;
const windowsEmbeddedPython = Object.freeze({
  version: '3.11.9',
  major: 3,
  minor: 11,
  arch: 'x64',
  archiveName: 'python-3.11.9-embed-amd64.zip',
  sha256: '009d6bf7e3b2ddca3d784fa09f90fe54336d5b60f0e0f305c37f400bf83cfd3b',
});

const excludedNames = new Set([
  '.env',
  '.pytest_cache',
  '.ruff_cache',
  '__pycache__',
  'backend.egg-info',
  'build',
  'data',
  'tests',
  'timemachine',
]);

const excludedFiles = new Set([
  '.env.example',
  '.venv-dir',
  'ais_cache.json',
  'carrier_cache.json',
  'cctv.db',
  'dm_token_pepper.key',
  'pytest.ini',
]);

const conventionalVenvNames = new Set(['venv', '.venv', 'venv-repair', '.venv-repair']);

function selectedVenvDirName() {
  let venvDir = 'venv';
  try {
    const persisted = fs.readFileSync(venvMarkerPath, 'utf8').trim();
    if (persisted) {
      venvDir = persisted;
    }
  } catch {}

  if (path.isAbsolute(venvDir) || path.basename(venvDir) !== venvDir) {
    throw new Error(`Invalid backend venv directory marker: ${venvDir}`);
  }
  return venvDir;
}

function backendPythonPath() {
  if (process.env.SHADOWBROKER_BACKEND_PYTHON) {
    return path.resolve(process.env.SHADOWBROKER_BACKEND_PYTHON);
  }
  const venvDir = selectedVenvDirName();
  if (process.platform === 'win32') {
    return path.join(backendDir, venvDir, 'Scripts', 'python.exe');
  }
  return path.join(backendDir, venvDir, 'bin', 'python3');
}

function shouldCopyBackendPath(
  srcPath,
  platform = process.platform,
  venvDirName = selectedVenvDirName(),
) {
  const relativePath = path.relative(backendDir, srcPath);
  if (!relativePath) return true;

  const parts = relativePath.split(path.sep);
  if (
    platform === 'win32' &&
    (parts[0] === venvDirName || conventionalVenvNames.has(parts[0]))
  ) {
    return false;
  }

  return parts.every((part, index) => {
    const isLeaf = index === parts.length - 1;
    if (excludedNames.has(part)) return false;
    if (isLeaf && excludedFiles.has(part)) return false;
    if (/^test_.*\.py$/i.test(part)) return false;
    return true;
  });
}

function shouldCopySitePackagePath(sitePackagesRoot, srcPath) {
  const relativePath = path.relative(sitePackagesRoot, srcPath);
  if (!relativePath) return true;

  const parts = relativePath.split(path.sep);
  if (parts.includes('__pycache__')) return false;
  if (parts.some((part) => /^backend-.*\.dist-info$/i.test(part))) return false;
  const leaf = parts.at(-1);
  if (/\.(?:egg-link|pth|pyc)$/i.test(leaf)) return false;
  if (leaf.toLowerCase() === 'direct_url.json') return false;
  return true;
}

function ensureRuntimePrereqs() {
  if (!fs.existsSync(path.join(backendDir, 'main.py'))) {
    throw new Error(`Missing backend/main.py at ${backendDir}`);
  }
  if (!fs.existsSync(backendPythonPath())) {
    throw new Error(
      `Missing backend build interpreter at ${backendPythonPath()}. ` +
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

function readBuildPythonInfo() {
  const python = backendPythonPath();
  const code = [
    'import json, platform, sys, sysconfig',
    "print(json.dumps({'major': sys.version_info.major, 'minor': sys.version_info.minor, " +
      "'micro': sys.version_info.micro, 'machine': platform.machine(), " +
      "'prefix': sys.prefix, 'base_prefix': sys.base_prefix, " +
      "'purelib': sysconfig.get_paths()['purelib']}))",
  ].join('; ');
  const result = spawnSync(python, ['-I', '-c', code], {
    cwd: backendDir,
    encoding: 'utf8',
  });
  if (result.error || result.status !== 0) {
    throw new Error(`Failed to inspect backend build interpreter: ${result.stderr || result.error}`);
  }
  return JSON.parse(result.stdout.trim());
}

function privacyCoreArtifactName() {
  if (process.platform === 'win32') return 'privacy_core.dll';
  if (process.platform === 'darwin') return 'libprivacy_core.dylib';
  return 'libprivacy_core.so';
}

function privacyCoreArtifactPath() {
  return path.join(privacyCoreDir, 'target', 'release', privacyCoreArtifactName());
}

function ensurePrivacyCoreArtifact() {
  const artifact = privacyCoreArtifactPath();
  if (fs.existsSync(artifact)) {
    return artifact;
  }
  console.log('privacy-core release library missing; building it for desktop packaging...');
  const result = spawnSync(
    'cargo',
    ['build', '--release', '--manifest-path', path.join(privacyCoreDir, 'Cargo.toml')],
    {
      cwd: repoRoot,
      env: process.env,
      stdio: 'inherit',
    },
  );
  if (result.error || result.status !== 0) {
    throw new Error(
      'Failed to build privacy-core release library. Install Rust/Cargo and rerun the desktop build.',
    );
  }
  if (!fs.existsSync(artifact)) {
    throw new Error(`privacy-core build completed but artifact is missing: ${artifact}`);
  }
  return artifact;
}

function sha256File(filePath) {
  const hash = crypto.createHash('sha256');
  hash.update(fs.readFileSync(filePath));
  return hash.digest('hex');
}

async function downloadFile(url, destination) {
  const response = await fetch(url, { redirect: 'follow' });
  if (!response.ok) {
    throw new Error(`Failed to download ${url}: HTTP ${response.status}`);
  }
  const temporary = `${destination}.partial-${process.pid}`;
  fs.writeFileSync(temporary, Buffer.from(await response.arrayBuffer()));
  fs.renameSync(temporary, destination);
}

async function windowsEmbeddedPythonArchive() {
  const configured = process.env.SHADOWBROKER_PYTHON_EMBED_ZIP;
  const cacheDir = path.join(os.tmpdir(), 'shadowbroker-python-embed');
  const archivePath = configured
    ? path.resolve(configured)
    : path.join(cacheDir, windowsEmbeddedPython.archiveName);

  if (!fs.existsSync(archivePath)) {
    if (configured) {
      throw new Error(`SHADOWBROKER_PYTHON_EMBED_ZIP does not exist: ${archivePath}`);
    }
    fs.mkdirSync(cacheDir, { recursive: true });
    const url =
      `https://www.python.org/ftp/python/${windowsEmbeddedPython.version}/` +
      windowsEmbeddedPython.archiveName;
    console.log(`Downloading verified embedded Python ${windowsEmbeddedPython.version}...`);
    await downloadFile(url, archivePath);
  }

  const actualHash = sha256File(archivePath);
  if (actualHash !== windowsEmbeddedPython.sha256) {
    throw new Error(
      `Embedded Python archive SHA-256 mismatch for ${archivePath}: ` +
      `expected ${windowsEmbeddedPython.sha256}, got ${actualHash}`,
    );
  }
  return archivePath;
}

function extractZipWithPowerShell(archivePath, destination) {
  fs.mkdirSync(destination, { recursive: true });
  const env = {
    ...process.env,
    SHADOWBROKER_EMBED_ARCHIVE: archivePath,
    SHADOWBROKER_EMBED_DESTINATION: destination,
  };
  const result = spawnSync(
    'powershell.exe',
    [
      '-NoProfile',
      '-NonInteractive',
      '-Command',
      "$ErrorActionPreference='Stop'; Expand-Archive -LiteralPath $env:SHADOWBROKER_EMBED_ARCHIVE -DestinationPath $env:SHADOWBROKER_EMBED_DESTINATION -Force",
    ],
    { env, encoding: 'utf8' },
  );
  if (result.error || result.status !== 0) {
    throw new Error(`Failed to extract embedded Python: ${result.stderr || result.error}`);
  }
}

function configureEmbeddedPythonPath(pythonRoot) {
  const pthPath = path.join(
    pythonRoot,
    `python${windowsEmbeddedPython.major}${windowsEmbeddedPython.minor}._pth`,
  );
  if (!fs.existsSync(pthPath)) {
    throw new Error(`Embedded Python path file is missing: ${pthPath}`);
  }
  fs.writeFileSync(
    pthPath,
    [
      `python${windowsEmbeddedPython.major}${windowsEmbeddedPython.minor}.zip`,
      '.',
      'Lib',
      'Lib\\site-packages',
      '..',
      'import site',
      '',
    ].join('\n'),
    'utf8',
  );
}

async function stageWindowsEmbeddedPython() {
  if (process.arch !== windowsEmbeddedPython.arch) {
    throw new Error(
      `Windows desktop packaging currently supports ${windowsEmbeddedPython.arch}, not ${process.arch}`,
    );
  }

  const buildInfo = readBuildPythonInfo();
  if (
    buildInfo.major !== windowsEmbeddedPython.major ||
    buildInfo.minor !== windowsEmbeddedPython.minor
  ) {
    throw new Error(
      `Backend venv uses Python ${buildInfo.major}.${buildInfo.minor}; ` +
      `desktop packaging requires Python ${windowsEmbeddedPython.major}.${windowsEmbeddedPython.minor}.x ` +
      'so compiled extension modules match the embedded runtime.',
    );
  }
  if (!fs.existsSync(buildInfo.purelib)) {
    throw new Error(`Backend site-packages directory is missing: ${buildInfo.purelib}`);
  }

  const pythonRoot = path.join(outputDir, 'python');
  const archivePath = await windowsEmbeddedPythonArchive();
  extractZipWithPowerShell(archivePath, pythonRoot);
  configureEmbeddedPythonPath(pythonRoot);

  const stagedSitePackages = path.join(pythonRoot, 'Lib', 'site-packages');
  fs.mkdirSync(stagedSitePackages, { recursive: true });
  fs.cpSync(buildInfo.purelib, stagedSitePackages, {
    recursive: true,
    filter: (srcPath) => shouldCopySitePackagePath(buildInfo.purelib, srcPath),
  });

  fs.writeFileSync(
    path.join(outputDir, '.runtime-layout.json'),
    `${JSON.stringify(
      {
        layout: 'embedded-python',
        layoutVersion: runtimeLayoutVersion,
        python: 'python/python.exe',
        pythonVersion: windowsEmbeddedPython.version,
      },
      null,
      2,
    )}\n`,
    'utf8',
  );
  return buildInfo;
}

function walkFiles(root) {
  const files = [];
  for (const entry of fs.readdirSync(root, { withFileTypes: true })) {
    const entryPath = path.join(root, entry.name);
    if (entry.isDirectory()) {
      files.push(...walkFiles(entryPath));
    } else {
      files.push(entryPath);
    }
  }
  return files;
}

function assertPortableWindowsBundle(root, buildInfo) {
  const forbiddenPaths = [repoRoot, backendDir, buildInfo.prefix, buildInfo.base_prefix]
    .filter(Boolean)
    .map((value) => path.resolve(value).toLowerCase());

  for (const filePath of walkFiles(root)) {
    const leaf = path.basename(filePath).toLowerCase();
    if (leaf === 'pyvenv.cfg' || /\.(?:egg-link|pth)$/i.test(leaf)) {
      throw new Error(`Non-portable virtualenv metadata was staged: ${filePath}`);
    }

    const stat = fs.statSync(filePath);
    if (stat.size > 2 * 1024 * 1024) continue;
    const bytes = fs.readFileSync(filePath);
    if (bytes.includes(0)) continue;
    const text = bytes.toString('utf8').toLowerCase();
    const leakedPath = forbiddenPaths.find((value) => text.includes(value));
    if (leakedPath) {
      throw new Error(`Build-machine path leaked into staged runtime: ${filePath}`);
    }
  }
}

function verifyRelocatableWindowsRuntime() {
  const probeDir = `${outputDir}-portability-probe-${process.pid}`;
  if (fs.existsSync(probeDir)) {
    throw new Error(`Portability probe path already exists: ${probeDir}`);
  }

  fs.renameSync(outputDir, probeDir);
  let result;
  try {
    const env = { ...process.env };
    delete env.PYTHONHOME;
    delete env.PYTHONPATH;
    result = spawnSync(
      path.join(probeDir, 'python', 'python.exe'),
      [
        '-I',
        '-c',
        [
          'import sys',
          'import fastapi, uvicorn, cryptography, numpy, orjson, pydantic',
          'assert sys.prefix == sys.base_prefix',
          'print(sys.executable)',
        ].join('; '),
      ],
      { cwd: probeDir, env, encoding: 'utf8' },
    );
  } finally {
    fs.renameSync(probeDir, outputDir);
  }

  if (result.error || result.status !== 0) {
    throw new Error(`Relocated embedded Python smoke test failed: ${result.stderr || result.error}`);
  }
}

async function stageBackendRuntime() {
  fs.rmSync(outputDir, { recursive: true, force: true });
  fs.cpSync(backendDir, outputDir, {
    recursive: true,
    filter: shouldCopyBackendPath,
  });

  let buildInfo = null;
  if (process.platform === 'win32') {
    buildInfo = await stageWindowsEmbeddedPython();
  }

  stagePrivacyCoreArtifact();
  stageReleaseAttestation();
  stageStartScripts();

  if (process.platform === 'win32') {
    assertPortableWindowsBundle(outputDir, buildInfo);
    verifyRelocatableWindowsRuntime();
  }
}

function stageStartScripts() {
  const scripts = ['start.bat', 'start.sh'];
  for (const name of scripts) {
    const src = path.join(repoRoot, name);
    if (!fs.existsSync(src)) {
      console.warn(`backend-runtime staged without ${name} (not at repo root)`);
      continue;
    }
    const dst = path.join(outputDir, name);
    fs.copyFileSync(src, dst);
    if (name.endsWith('.sh') && process.platform !== 'win32') {
      try {
        fs.chmodSync(dst, 0o755);
      } catch {
        /* best-effort; not fatal on filesystems that don't honor chmod */
      }
    }
  }
}

function stagePrivacyCoreArtifact() {
  const artifact = ensurePrivacyCoreArtifact();
  const stagedPath = path.join(outputDir, path.basename(artifact));
  fs.copyFileSync(artifact, stagedPath);
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
  fs.writeFileSync(
    versionPath,
    `${pkg.version || '0.0.0'}-runtime-${runtimeLayoutVersion}\n`,
    'utf8',
  );
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

async function main() {
  ensureRuntimePrereqs();
  await stageBackendRuntime();
  writeBundleVersion();
  console.log(`backend-runtime staged: ${fileCount(outputDir)} files`);
}

if (require.main === module) {
  main().catch((error) => {
    console.error(error instanceof Error ? error.message : error);
    process.exitCode = 1;
  });
}

module.exports = {
  assertPortableWindowsBundle,
  configureEmbeddedPythonPath,
  shouldCopyBackendPath,
  shouldCopySitePackagePath,
  windowsEmbeddedPython,
};
