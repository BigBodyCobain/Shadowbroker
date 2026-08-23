const { execFileSync } = require('node:child_process');
const { copyFileSync, existsSync, mkdirSync, writeFileSync } = require('node:fs');
const { join, resolve } = require('node:path');

const frontendRoot = resolve(__dirname, '..');
const repositoryRoot = resolve(frontendRoot, '..');
const publicRoot = join(frontendRoot, 'public');
const wellKnownRoot = join(publicRoot, '.well-known');

function git(args, fallback) {
  try {
    return execFileSync('git', args, { cwd: repositoryRoot, encoding: 'utf8' }).trim();
  } catch {
    return fallback;
  }
}

const manifestPath = join(repositoryRoot, 'qdev-project.json');
const adoptionPath = join(frontendRoot, 'contracts', 'avds-adoption.json');
const declaredSourceRevision = process.env.SHADOWBROKER_SOURCE_REVISION?.trim();
const declaredSourceDirty = process.env.SHADOWBROKER_SOURCE_DIRTY?.trim();
const declaredRuntimeRevision = process.env.SHADOWBROKER_RUNTIME_REVISION?.trim();
const sourceRevision = declaredSourceRevision || git(['rev-parse', 'HEAD'], 'unknown');
const sourceDirty = declaredSourceDirty == null
  ? Boolean(git(['status', '--porcelain'], 'dirty'))
  : declaredSourceDirty !== 'false';
const runtimeRevision = declaredRuntimeRevision || null;
const builtAt = new Date().toISOString();

for (const path of [manifestPath, adoptionPath]) {
  if (!existsSync(path)) throw new Error(`Missing public contract input: ${path}`);
}

mkdirSync(wellKnownRoot, { recursive: true });

copyFileSync(manifestPath, join(wellKnownRoot, 'qdev-project.json'));
copyFileSync(adoptionPath, join(wellKnownRoot, 'avds-adoption.json'));

writeFileSync(
  join(publicRoot, 'release.json'),
  `${JSON.stringify({
    schemaVersion: 'shadowbroker-release-v1',
    product: 'shadowbroker',
    lifecycle: 'experimental',
    sourceRevision,
    sourceDirty,
    runtimeRevision,
    builtAt,
    evidenceLayer: runtimeRevision && !sourceDirty ? 'runtime-candidate' : 'local-candidate',
    publicVerificationRequired: true,
  }, null, 2)}\n`,
);

console.log(`Generated public contracts for ${sourceRevision}${sourceDirty ? ' (dirty candidate)' : ''}.`);
