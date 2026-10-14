const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

const {
  assertPortableWindowsBundle,
  configureEmbeddedPythonPath,
  shouldCopyBackendPath,
  shouldCopySitePackagePath,
} = require('./build-backend-runtime.cjs');

const repoRoot = path.resolve(__dirname, '..', '..', '..');
const backendDir = path.join(repoRoot, 'backend');

test('Windows staging never copies a virtualenv or its marker', () => {
  assert.equal(
    shouldCopyBackendPath(path.join(backendDir, 'venv', 'pyvenv.cfg'), 'win32', 'venv'),
    false,
  );
  assert.equal(
    shouldCopyBackendPath(path.join(backendDir, '.venv', 'Scripts', 'python.exe'), 'win32'),
    false,
  );
  assert.equal(
    shouldCopyBackendPath(path.join(backendDir, '.venv-dir'), 'win32', 'custom-venv'),
    false,
  );
  assert.equal(
    shouldCopyBackendPath(path.join(backendDir, 'services', 'config.py'), 'win32', 'venv'),
    true,
  );
});

test('site-packages staging strips host-bound path files and editable metadata', () => {
  const sitePackages = path.join('C:', 'build', 'site-packages');
  assert.equal(
    shouldCopySitePackagePath(sitePackages, path.join(sitePackages, 'host-path.pth')),
    false,
  );
  assert.equal(
    shouldCopySitePackagePath(
      sitePackages,
      path.join(sitePackages, 'backend-0.9.84.dist-info', 'METADATA'),
    ),
    false,
  );
  assert.equal(
    shouldCopySitePackagePath(sitePackages, path.join(sitePackages, 'fastapi', '__init__.py')),
    true,
  );
});

test('embedded Python search paths are relative to the packaged runtime', () => {
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'sb-python-pth-test-'));
  try {
    const pthPath = path.join(temp, 'python311._pth');
    fs.writeFileSync(pthPath, 'C:\\Users\\developer\\Python311\\python311.zip\n', 'utf8');

    configureEmbeddedPythonPath(temp);

    const configured = fs.readFileSync(pthPath, 'utf8');
    assert.doesNotMatch(configured, /[A-Za-z]:\\/);
    assert.match(configured, /^python311\.zip$/m);
    assert.match(configured, /^Lib\\site-packages$/m);
    assert.match(configured, /^\.\.$/m);
    assert.match(configured, /^import site$/m);
  } finally {
    fs.rmSync(temp, { recursive: true, force: true });
  }
});

test('bundle validation rejects pyvenv.cfg and developer home paths', () => {
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'sb-python-portability-test-'));
  const buildInfo = {
    prefix: 'C:\\Users\\developer\\Shadowbroker\\backend\\venv',
    base_prefix: 'C:\\Users\\developer\\Python311',
  };

  try {
    fs.writeFileSync(path.join(temp, 'safe.txt'), 'portable runtime\n', 'utf8');
    assert.doesNotThrow(() => assertPortableWindowsBundle(temp, buildInfo));

    fs.writeFileSync(
      path.join(temp, 'pyvenv.cfg'),
      'home = C:\\Users\\developer\\Python311\n',
      'utf8',
    );
    assert.throws(
      () => assertPortableWindowsBundle(temp, buildInfo),
      /Non-portable virtualenv metadata/,
    );

    fs.rmSync(path.join(temp, 'pyvenv.cfg'));
    fs.writeFileSync(
      path.join(temp, 'leak.txt'),
      `executable = ${buildInfo.base_prefix}\\python.exe\n`,
      'utf8',
    );
    assert.throws(
      () => assertPortableWindowsBundle(temp, buildInfo),
      /Build-machine path leaked/,
    );
  } finally {
    fs.rmSync(temp, { recursive: true, force: true });
  }
});
