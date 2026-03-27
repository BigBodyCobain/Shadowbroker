const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const nextDir = path.join(root, '.next');

function dirSize(p) {
  let total = 0;
  if (!fs.existsSync(p)) return 0;
  const stats = fs.statSync(p);
  if (stats.isFile()) return stats.size;
  for (const entry of fs.readdirSync(p)) {
    total += dirSize(path.join(p, entry));
  }
  return total;
}

const total = dirSize(nextDir);
const staticSize = dirSize(path.join(nextDir, 'static'));
const serverSize = dirSize(path.join(nextDir, 'server'));

const toKb = (b) => Math.round(b / 1024);

console.log('Bundle size report');
console.log(`.next total:  ${toKb(total)} KB`);
console.log(`.next/static: ${toKb(staticSize)} KB`);
console.log(`.next/server: ${toKb(serverSize)} KB`);

const limitKb = process.env.BUNDLE_SIZE_LIMIT_KB ? Number(process.env.BUNDLE_SIZE_LIMIT_KB) : null;
if (limitKb && toKb(total) > limitKb) {
  console.error(`Bundle size exceeds limit: ${toKb(total)} KB > ${limitKb} KB`);
  process.exit(1);
}
