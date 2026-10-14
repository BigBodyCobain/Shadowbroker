const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { parseEnv } = require('node:util');

function ensureDevAdminKey(frontendDir) {
  if (process.env.ADMIN_KEY) {
    if (process.env.ADMIN_KEY.length < 32) throw new Error('ADMIN_KEY must contain at least 32 characters.');
    return process.env.ADMIN_KEY;
  }
  const files = [
    path.join(frontendDir, '.env.local'),
    path.resolve(frontendDir, '..', 'backend', '.env'),
  ];
  const contents = files.map((file) => fs.existsSync(file) ? fs.readFileSync(file, 'utf8') : '');
  const keys = contents.map((content) => (parseEnv(content).ADMIN_KEY || '').trim());
  if (keys[0] && keys[1] && keys[0] !== keys[1]) {
    throw new Error('Frontend and backend ADMIN_KEY differ. Configure the same key in both files.');
  }
  const key = keys.find(Boolean) || crypto.randomBytes(32).toString('hex');
  if (key.length < 32) throw new Error('ADMIN_KEY must contain at least 32 characters.');
  files.forEach((file, index) => {
    if (keys[index]) return;
    const content = contents[index];
    const updated = /^ADMIN_KEY=.*$/m.test(content)
      ? content.replace(/^ADMIN_KEY=.*$/gm, 'ADMIN_KEY=' + key)
      : content + (content.endsWith('\n') || !content ? '' : '\n') + 'ADMIN_KEY=' + key + '\n';
    fs.writeFileSync(file, updated, { mode: 0o600 });
  });
  return key;
}

module.exports = { ensureDevAdminKey };
