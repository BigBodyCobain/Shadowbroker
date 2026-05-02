#!/usr/bin/env node

const { spawn } = require('node:child_process');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const forwardedArgs = process.argv
  .slice(2)
  .map((arg) => (process.platform === 'win32' && arg === '--clean' ? '-Clean' : arg));

const buildScript = process.platform === 'win32'
  ? path.join(root, 'tauri-skeleton', 'build.ps1')
  : path.join(root, 'tauri-skeleton', 'build.sh');

const command = process.platform === 'win32' ? 'powershell' : 'bash';
const args = process.platform === 'win32'
  ? ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', buildScript, ...forwardedArgs]
  : [buildScript, ...forwardedArgs];

const child = spawn(command, args, {
  cwd: root,
  stdio: 'inherit',
});

child.on('exit', (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code ?? 1);
});
