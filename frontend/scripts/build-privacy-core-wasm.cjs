const { execFileSync } = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs');

const frontendDir = path.resolve(__dirname, '..');
const repoRoot = path.resolve(frontendDir, '..');
const privacyCoreManifest = path.join(repoRoot, 'privacy-core', 'Cargo.toml');
const outDir = path.join(frontendDir, 'src', 'mesh', 'privacyCoreWasm');
const wasmPath = path.join(
  repoRoot,
  'privacy-core',
  'target',
  'wasm32-unknown-unknown',
  'release',
  'privacy_core.wasm',
);

function run(bin, args) {
  execFileSync(bin, args, {
    cwd: repoRoot,
    stdio: 'inherit',
  });
}

fs.mkdirSync(outDir, { recursive: true });

run('rustup', ['target', 'add', 'wasm32-unknown-unknown']);
run('cargo', ['build', '--target', 'wasm32-unknown-unknown', '--release', '--manifest-path', privacyCoreManifest]);
run('wasm-bindgen', ['--target', 'web', '--out-dir', outDir, wasmPath]);
