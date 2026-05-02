#!/usr/bin/env node

const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

if (process.argv.length < 3) {
  throw new Error('Usage: write-release-manifest.cjs <bundle_dir>');
}
const bundleDir = path.resolve(process.argv[2]);
const tauriConfigPath = path.resolve(__dirname, '..', 'src-tauri', 'tauri.conf.json');
const updateBaseUrl = (
  process.env.SHADOWBROKER_UPDATE_BASE_URL ||
  'https://github.com/BigBodyCobain/Shadowbroker/releases/latest/download'
).replace(/\/+$/, '');

const releaseSuffixes = [
  '.AppImage',
  '.app.tar.gz',
  '.deb',
  '.dmg',
  '.exe',
  '.msi',
  '.pkg',
  '.rpm',
  '.sig',
  '.tar.gz',
  '.zip',
  'latest.json',
];

function collectFiles(dir) {
  const files = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      files.push(...collectFiles(fullPath));
    } else if (entry.isFile()) {
      files.push(fullPath);
    }
  }
  return files;
}

function sha256File(filePath) {
  const hash = crypto.createHash('sha256');
  hash.update(fs.readFileSync(filePath));
  return hash.digest('hex');
}

function readReleaseVersion() {
  try {
    const config = JSON.parse(fs.readFileSync(tauriConfigPath, 'utf8'));
    return String(config.version || '').trim() || '0.0.0';
  } catch {
    return '0.0.0';
  }
}

function updaterPlatformForArtifact(relativePath) {
  if (/\.msi$/i.test(relativePath) || /\.exe$/i.test(relativePath)) {
    return 'windows-x86_64';
  }
  if (/\.app\.tar\.gz$/i.test(relativePath) || /\.dmg$/i.test(relativePath)) {
    return 'darwin-x86_64';
  }
  if (/\.AppImage$/i.test(relativePath) || /\.deb$/i.test(relativePath) || /\.rpm$/i.test(relativePath)) {
    return 'linux-x86_64';
  }
  return null;
}

function updaterArtifactPriority(relativePath) {
  if (/\.msi$/i.test(relativePath)) return 0;
  if (/setup\.exe$/i.test(relativePath) || /\.exe$/i.test(relativePath)) return 1;
  if (/\.app\.tar\.gz$/i.test(relativePath)) return 0;
  if (/\.AppImage$/i.test(relativePath)) return 0;
  return 10;
}

function writeUpdaterManifest(files) {
  const signedArtifacts = files
    .filter((filePath) => filePath.endsWith('.sig'))
    .map((signaturePath) => {
      const artifactPath = signaturePath.slice(0, -4);
      if (!fs.existsSync(artifactPath)) return null;
      const relativePath = path.relative(bundleDir, artifactPath).replaceAll(path.sep, '/');
      const platform = updaterPlatformForArtifact(relativePath);
      if (!platform) return null;
      return {
        platform,
        relativePath,
        signature: fs.readFileSync(signaturePath, 'utf8').trim(),
      };
    })
    .filter(Boolean)
    .sort((a, b) => updaterArtifactPriority(a.relativePath) - updaterArtifactPriority(b.relativePath));

  const platforms = {};
  for (const artifact of signedArtifacts) {
    if (platforms[artifact.platform]) continue;
    platforms[artifact.platform] = {
      signature: artifact.signature,
      url: `${updateBaseUrl}/${encodeURIComponent(path.basename(artifact.relativePath))}`,
    };
  }

  if (Object.keys(platforms).length === 0) return false;

  const latest = {
    version: readReleaseVersion(),
    notes: `ShadowBroker ${readReleaseVersion()}`,
    pub_date: new Date().toISOString(),
    platforms,
  };

  fs.writeFileSync(path.join(bundleDir, 'latest.json'), `${JSON.stringify(latest, null, 2)}\n`);
  return true;
}

fs.mkdirSync(bundleDir, { recursive: true });

let files = collectFiles(bundleDir);
const wroteUpdaterManifest = writeUpdaterManifest(files);
if (wroteUpdaterManifest) {
  files = collectFiles(bundleDir);
}
const artifacts = files.filter((file) => releaseSuffixes.some((suffix) => file.endsWith(suffix)));
const releaseFiles = (artifacts.length > 0 ? artifacts : files).sort();

const manifest = releaseFiles.map((filePath) => ({
  path: path.relative(bundleDir, filePath).replaceAll(path.sep, '/'),
  size_bytes: fs.statSync(filePath).size,
  sha256: sha256File(filePath),
}));

fs.writeFileSync(
  path.join(bundleDir, 'SHA256SUMS.txt'),
  manifest.map((item) => `${item.sha256}  ${item.path}`).join('\n') + (manifest.length ? '\n' : ''),
);
fs.writeFileSync(
  path.join(bundleDir, 'release-manifest.json'),
  `${JSON.stringify({ artifacts: manifest }, null, 2)}\n`,
);

console.log(`Wrote release manifest for ${manifest.length} artifacts in ${bundleDir}`);
if (wroteUpdaterManifest) {
  console.log(`Wrote Tauri updater manifest: ${path.join(bundleDir, 'latest.json')}`);
}
for (const item of manifest) {
  console.log(`  - ${item.path} (${item.size_bytes} bytes)`);
}
