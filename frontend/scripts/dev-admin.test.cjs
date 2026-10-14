const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { ensureDevAdminKey } = require('./dev-admin.cjs');

test('development credentials persist, match across processes and preserve other settings', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'sb-dev-admin-'));
  const original = process.env.ADMIN_KEY;
  delete process.env.ADMIN_KEY;
  const frontend = path.join(root, 'frontend');
  const backend = path.join(root, 'backend');
  fs.mkdirSync(frontend);
  fs.mkdirSync(backend);
  fs.writeFileSync(path.join(backend, '.env'), 'OTHER=preserved\nADMIN_KEY=\n');
  try {
    const key = ensureDevAdminKey(frontend);
    assert.equal(key.length, 64);
    assert.equal(ensureDevAdminKey(frontend), key);
    assert.match(fs.readFileSync(path.join(backend, '.env'), 'utf8'), /OTHER=preserved/);
    fs.writeFileSync(path.join(frontend, '.env.local'), 'ADMIN_KEY=' + 'x'.repeat(32));
    assert.throws(() => ensureDevAdminKey(frontend), /differ/);
  } finally {
    if (original === undefined) delete process.env.ADMIN_KEY; else process.env.ADMIN_KEY = original;
    // root is an absolute mkdtemp result inside the system temporary directory.
    fs.rmSync(root, { recursive: true, force: true });
  }
});
