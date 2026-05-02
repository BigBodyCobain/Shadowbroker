#!/usr/bin/env node

import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';

const PROTOCOL_VERSION = 'infonet/2';
const NETWORK_ID = 'sb-testnet-0';
const NODE_ID_PREFIX = '!sb_';
const NODE_ID_HEX_LEN = 32;
const MANIFEST_WITNESS_EVENT_TYPE = 'stable_dm_root_manifest_witness';
const MANIFEST_WITNESS_TYPE = 'stable_dm_root_manifest_witness';
const EXTERNAL_WITNESS_IMPORT_TYPE = 'stable_dm_root_manifest_external_witness_import';
const EXTERNAL_WITNESS_IDENTITY_TYPE = 'stable_dm_root_manifest_external_witness_identity';
const ROOT_DISTRIBUTION_PATH = '/api/wormhole/dm/root-distribution';

const HELP_TEXT = `
ShadowBroker external root witness package publisher

Usage:
  node scripts/mesh/publish-external-root-witness-package.mjs --init-witness PATH
  node scripts/mesh/publish-external-root-witness-package.mjs --descriptor-only --witness-file PATH [--output PATH]
  node scripts/mesh/publish-external-root-witness-package.mjs --witness-file PATH [--output PATH]

Environment:
  SB_DM_ROOT_BASE_URL=http://127.0.0.1:8000
  SB_DM_ROOT_DISTRIBUTION_PATH=/api/wormhole/dm/root-distribution
  SB_DM_ROOT_AUTH_HEADER=X-Admin-Key: change-me
  SB_DM_ROOT_AUTH_COOKIE=operator_session=...
  SB_DM_ROOT_TIMEOUT_MS=10000
  SB_DM_ROOT_WITNESS_IDENTITY_FILE=./ops/witness-a.identity.json
  SB_DM_ROOT_WITNESS_OUTPUT=./ops/root_witness_import.json
  SB_DM_ROOT_WITNESS_LABEL=witness-a
  SB_DM_ROOT_WITNESS_SOURCE_SCOPE=https_publish
  SB_DM_ROOT_WITNESS_SOURCE_LABEL=witness-a
  SB_DM_ROOT_WITNESS_INDEPENDENCE_GROUP=independent_witness_a

Flags:
  --init-witness PATH       Generate a new external witness identity file and exit
  --witness-file PATH       Load the external witness identity file to publish from
  --descriptor-only         Emit descriptors only, without manifest_fingerprint or signed receipts
  --stdout                  Print the generated package to stdout
  --output PATH             Write the generated package JSON to PATH
  --base-url URL            Override SB_DM_ROOT_BASE_URL
  --distribution-path PATH  Override SB_DM_ROOT_DISTRIBUTION_PATH
  --label VALUE             Override witness descriptor label
  --source-scope VALUE      Override source_scope in the published import package
  --source-label VALUE      Override source_label in the published import package
  --independence-group VAL  Override witness independence group
  --help                    Show this text

Typical flow:
  1. Run --init-witness once on the external witness host.
  2. Publish a descriptor-only package so the backend can import the external descriptor and republish the manifest.
  3. Publish a full signed receipt package after the current manifest policy includes this external witness.
`.trim();

function parseArgs(argv) {
  const parsed = {};
  for (let index = 0; index < argv.length; index += 1) {
    const current = String(argv[index] || '').trim();
    if (!current) continue;
    if (current === '--descriptor-only' || current === '--stdout') {
      parsed[current.slice(2).replace(/-([a-z])/g, (_match, letter) => letter.toUpperCase())] = true;
      continue;
    }
    if (current === '--help' || current === '-h') {
      parsed.help = true;
      continue;
    }
    if (
      (
        current === '--init-witness' ||
        current === '--witness-file' ||
        current === '--output' ||
        current === '--base-url' ||
        current === '--distribution-path' ||
        current === '--label' ||
        current === '--source-scope' ||
        current === '--source-label' ||
        current === '--independence-group'
      ) &&
      index + 1 < argv.length
    ) {
      parsed[current.slice(2).replace(/-([a-z])/g, (_match, letter) => letter.toUpperCase())] =
        String(argv[index + 1] || '').trim();
      index += 1;
    }
  }
  return parsed;
}

function nowSeconds() {
  return Math.floor(Date.now() / 1000);
}

function stableJson(value) {
  if (Array.isArray(value)) {
    return `[${value.map((item) => stableJson(item)).join(',')}]`;
  }
  if (value && typeof value === 'object') {
    const entries = Object.entries(value)
      .filter(([, entryValue]) => entryValue !== undefined)
      .sort(([left], [right]) => left.localeCompare(right));
    return `{${entries
      .map(([key, entryValue]) => `${JSON.stringify(key)}:${stableJson(entryValue)}`)
      .join(',')}}`;
  }
  return JSON.stringify(value);
}

function safeInt(value, fallback = 0) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return fallback;
  return Math.trunc(numeric);
}

function normalizeUrl(baseUrl, routePath) {
  const base = String(baseUrl || 'http://127.0.0.1:8000').trim().replace(/\/+$/, '');
  const pathValue = String(routePath || ROOT_DISTRIBUTION_PATH).trim();
  if (!pathValue) {
    return `${base}${ROOT_DISTRIBUTION_PATH}`;
  }
  return pathValue.startsWith('http://') || pathValue.startsWith('https://')
    ? pathValue
    : `${base}/${pathValue.replace(/^\/+/, '')}`;
}

function parseHeader(rawValue) {
  const raw = String(rawValue || '').trim();
  if (!raw) return null;
  const separator = raw.indexOf(':');
  if (separator <= 0) return null;
  const name = raw.slice(0, separator).trim();
  const value = raw.slice(separator + 1).trim();
  if (!name || !value) return null;
  return [name, value];
}

function toBase64Url(input) {
  return Buffer.from(input)
    .toString('base64')
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/g, '');
}

function fromBase64(value) {
  return Buffer.from(String(value || '').trim(), 'base64');
}

function deriveNodeId(publicKeyBase64) {
  const digest = crypto.createHash('sha256').update(fromBase64(publicKeyBase64)).digest('hex');
  return `${NODE_ID_PREFIX}${digest.slice(0, NODE_ID_HEX_LEN)}`;
}

function buildWitnessDescriptor(identity, overrides = {}) {
  return {
    scope: 'root_witness',
    label: String(overrides.label || identity.label || '').trim(),
    node_id: String(identity.node_id || '').trim(),
    public_key: String(identity.public_key || '').trim(),
    public_key_algo: 'Ed25519',
    management_scope: 'external',
    independence_group: String(
      overrides.independenceGroup || identity.independence_group || 'external_witness'
    )
      .trim()
      .toLowerCase(),
  };
}

function witnessPolicyFingerprint(policy) {
  const normalizedWitnesses = Array.isArray(policy?.witnesses)
    ? policy.witnesses.map((item) => ({
        scope: String(item?.scope || 'root_witness'),
        label: String(item?.label || ''),
        node_id: String(item?.node_id || '').trim(),
        public_key: String(item?.public_key || '').trim(),
        public_key_algo: String(item?.public_key_algo || 'Ed25519'),
        management_scope: String(item?.management_scope || 'local').trim().toLowerCase(),
        independence_group: String(item?.independence_group || '')
          .trim()
          .toLowerCase(),
      }))
    : [];
  const canonical = {
    type: String(policy?.type || 'stable_dm_root_manifest_witness_policy'),
    policy_version: safeInt(policy?.policy_version, 1),
    threshold: safeInt(policy?.threshold, 0),
    witnesses: normalizedWitnesses,
  };
  return crypto.createHash('sha256').update(stableJson(canonical), 'utf8').digest('hex');
}

function manifestFingerprintForEnvelope(manifest) {
  const canonical = {
    type: String(manifest?.type || 'stable_dm_root_manifest'),
    event_type: String(manifest?.event_type || 'stable_dm_root_manifest'),
    node_id: String(manifest?.node_id || '').trim(),
    public_key: String(manifest?.public_key || '').trim(),
    public_key_algo: String(manifest?.public_key_algo || 'Ed25519'),
    protocol_version: String(manifest?.protocol_version || PROTOCOL_VERSION),
    sequence: safeInt(manifest?.sequence, 0),
    payload: manifest?.payload && typeof manifest.payload === 'object' ? { ...manifest.payload } : {},
    signature: String(manifest?.signature || '').trim(),
  };
  return crypto.createHash('sha256').update(stableJson(canonical), 'utf8').digest('hex');
}

function buildSignaturePayload({ eventType, nodeId, sequence, payload }) {
  return [
    PROTOCOL_VERSION,
    NETWORK_ID,
    eventType,
    String(nodeId || '').trim(),
    String(safeInt(sequence, 0)),
    stableJson(payload && typeof payload === 'object' ? payload : {}),
  ].join('|');
}

function buildWitnessPayload(manifest) {
  const payload = manifest?.payload && typeof manifest.payload === 'object' ? { ...manifest.payload } : {};
  const witnessPolicy = payload?.witness_policy && typeof payload.witness_policy === 'object' ? payload.witness_policy : {};
  return {
    manifest_type: String(manifest?.type || 'stable_dm_root_manifest'),
    manifest_event_type: String(manifest?.event_type || 'stable_dm_root_manifest'),
    manifest_fingerprint: manifestFingerprintForEnvelope(manifest),
    root_fingerprint: String(payload?.root_fingerprint || '').trim().toLowerCase(),
    root_node_id: String(payload?.root_node_id || '').trim(),
    generation: safeInt(payload?.generation, 0),
    issued_at: safeInt(payload?.issued_at, 0),
    expires_at: safeInt(payload?.expires_at, 0),
    policy_version: safeInt(payload?.policy_version, 1),
    witness_policy_fingerprint: witnessPolicyFingerprint(witnessPolicy),
    witness_threshold: safeInt(witnessPolicy?.threshold, 0),
  };
}

function createPrivateKeyFromIdentity(identity) {
  const privateKeyRaw = fromBase64(identity.private_key);
  const publicKeyRaw = fromBase64(identity.public_key);
  if (privateKeyRaw.length !== 32 || publicKeyRaw.length !== 32) {
    throw new Error('external witness identity keys must be raw Ed25519 base64');
  }
  return crypto.createPrivateKey({
    key: {
      crv: 'Ed25519',
      d: toBase64Url(privateKeyRaw),
      kty: 'OKP',
      x: toBase64Url(publicKeyRaw),
    },
    format: 'jwk',
  });
}

function generateWitnessIdentity(overrides = {}) {
  const { privateKey, publicKey } = crypto.generateKeyPairSync('ed25519');
  const privateJwk = privateKey.export({ format: 'jwk' });
  const publicJwk = publicKey.export({ format: 'jwk' });
  const publicKeyRaw = Buffer.from(String(publicJwk.x || '').replace(/-/g, '+').replace(/_/g, '/'), 'base64');
  const privateKeyRaw = Buffer.from(String(privateJwk.d || '').replace(/-/g, '+').replace(/_/g, '/'), 'base64');
  const publicKeyBase64 = publicKeyRaw.toString('base64');
  return {
    type: EXTERNAL_WITNESS_IDENTITY_TYPE,
    schema_version: 1,
    created_at: nowSeconds(),
    updated_at: nowSeconds(),
    node_id: deriveNodeId(publicKeyBase64),
    public_key: publicKeyBase64,
    public_key_algo: 'Ed25519',
    private_key: privateKeyRaw.toString('base64'),
    label: String(overrides.label || 'external-witness').trim(),
    management_scope: 'external',
    independence_group: String(overrides.independenceGroup || 'external_witness').trim().toLowerCase(),
    sequence: 0,
  };
}

async function readJsonFile(filePath) {
  const raw = await fs.readFile(path.resolve(filePath), 'utf8');
  return JSON.parse(raw);
}

async function writeJsonFile(filePath, value) {
  const target = path.resolve(filePath);
  await fs.mkdir(path.dirname(target), { recursive: true });
  await fs.writeFile(target, `${JSON.stringify(value, null, 2)}\n`, 'utf8');
}

async function loadWitnessIdentity(filePath) {
  const parsed = await readJsonFile(filePath);
  if (!parsed || typeof parsed !== 'object') {
    throw new Error('external witness identity file root must be an object');
  }
  const identity = { ...parsed };
  if (String(identity.type || EXTERNAL_WITNESS_IDENTITY_TYPE) !== EXTERNAL_WITNESS_IDENTITY_TYPE) {
    throw new Error('external witness identity type invalid');
  }
  if (safeInt(identity.schema_version, 0) <= 0) {
    throw new Error('external witness identity schema_version required');
  }
  if (String(identity.public_key_algo || 'Ed25519') !== 'Ed25519') {
    throw new Error('external witness identity public_key_algo must be Ed25519');
  }
  if (!String(identity.public_key || '').trim() || !String(identity.private_key || '').trim()) {
    throw new Error('external witness identity keys required');
  }
  const derivedNodeId = deriveNodeId(identity.public_key);
  if (!String(identity.node_id || '').trim()) {
    identity.node_id = derivedNodeId;
  }
  if (String(identity.node_id || '').trim() !== derivedNodeId) {
    throw new Error('external witness identity node_id does not match public_key');
  }
  identity.sequence = Math.max(0, safeInt(identity.sequence, 0));
  identity.label = String(identity.label || '').trim();
  identity.independence_group = String(identity.independence_group || 'external_witness')
    .trim()
    .toLowerCase();
  return identity;
}

async function fetchDistribution(config) {
  const headers = { Accept: 'application/json' };
  const authHeader = parseHeader(config.authHeader);
  if (authHeader) {
    headers[authHeader[0]] = authHeader[1];
  }
  if (config.authCookie) {
    headers.Cookie = config.authCookie;
  }
  const controller = new AbortController();
  const timeout = globalThis.setTimeout(() => controller.abort(), config.timeoutMs);
  try {
    const response = await fetch(config.url, {
      method: 'GET',
      headers,
      signal: controller.signal,
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || payload?.ok === false) {
      const detail = String(payload?.detail || payload?.message || `http_${response.status}`).trim();
      throw new Error(detail || 'root_distribution_fetch_failed');
    }
    return payload;
  } finally {
    globalThis.clearTimeout(timeout);
  }
}

function buildImportPackage({ identity, descriptor, sourceScope, sourceLabel, descriptorOnly, distribution }) {
  const packageBase = {
    type: EXTERNAL_WITNESS_IMPORT_TYPE,
    schema_version: 1,
    source_scope: String(sourceScope || 'external_publish').trim().toLowerCase(),
    source_label: String(sourceLabel || descriptor.label || identity.label || '').trim(),
    exported_at: nowSeconds(),
    descriptors: [descriptor],
  };
  if (descriptorOnly) {
    return packageBase;
  }

  const manifest = distribution?.manifest && typeof distribution.manifest === 'object' ? distribution.manifest : null;
  if (!manifest) {
    throw new Error('current root-distribution manifest required');
  }
  const manifestFingerprint =
    String(distribution?.manifest_fingerprint || '').trim().toLowerCase() || manifestFingerprintForEnvelope(manifest);
  const policyWitnesses = Array.isArray(distribution?.witness_policy?.witnesses)
    ? distribution.witness_policy.witnesses
    : Array.isArray(manifest?.payload?.witness_policy?.witnesses)
    ? manifest.payload.witness_policy.witnesses
    : [];
  const declaredWitness = policyWitnesses.find(
    (item) =>
      String(item?.node_id || '').trim() === identity.node_id &&
      String(item?.public_key || '').trim() === identity.public_key,
  );
  if (!declaredWitness) {
    throw new Error(
      'external witness is not declared in the current manifest policy; import a descriptor-only package and let the backend republish before generating receipts',
    );
  }

  const nextSequence = Math.max(1, safeInt(identity.sequence, 0) + 1);
  const witnessPayload = buildWitnessPayload(manifest);
  const signaturePayload = buildSignaturePayload({
    eventType: MANIFEST_WITNESS_EVENT_TYPE,
    nodeId: identity.node_id,
    sequence: nextSequence,
    payload: witnessPayload,
  });
  const signature = crypto.sign(null, Buffer.from(signaturePayload, 'utf8'), createPrivateKeyFromIdentity(identity)).toString('hex');

  identity.sequence = nextSequence;
  identity.updated_at = nowSeconds();

  return {
    ...packageBase,
    manifest_fingerprint: manifestFingerprint,
    witnesses: [
      {
        type: MANIFEST_WITNESS_TYPE,
        event_type: MANIFEST_WITNESS_EVENT_TYPE,
        node_id: identity.node_id,
        public_key: identity.public_key,
        public_key_algo: 'Ed25519',
        protocol_version: PROTOCOL_VERSION,
        sequence: nextSequence,
        payload: witnessPayload,
        signature,
        identity_scope: 'root_witness',
      },
    ],
  };
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    console.log(HELP_TEXT);
    return;
  }

  const label = String(args.label || process.env.SB_DM_ROOT_WITNESS_LABEL || 'external-witness').trim();
  const independenceGroup = String(
    args.independenceGroup || process.env.SB_DM_ROOT_WITNESS_INDEPENDENCE_GROUP || 'external_witness',
  )
    .trim()
    .toLowerCase();

  if (args.initWitness) {
    const identity = generateWitnessIdentity({ label, independenceGroup });
    await writeJsonFile(args.initWitness, identity);
    console.log(`external witness identity written to ${path.resolve(args.initWitness)}`);
    return;
  }

  const witnessFile = String(args.witnessFile || process.env.SB_DM_ROOT_WITNESS_IDENTITY_FILE || '').trim();
  if (!witnessFile) {
    console.error('external witness identity file required; use --witness-file PATH or --init-witness PATH');
    process.exit(2);
  }

  const identity = await loadWitnessIdentity(witnessFile);
  if (label) {
    identity.label = label;
  }
  if (independenceGroup) {
    identity.independence_group = independenceGroup;
  }
  const descriptor = buildWitnessDescriptor(identity, {
    label,
    independenceGroup,
  });

  const descriptorOnly = Boolean(args.descriptorOnly);
  const sourceScope = String(args.sourceScope || process.env.SB_DM_ROOT_WITNESS_SOURCE_SCOPE || 'external_publish').trim();
  const sourceLabel = String(args.sourceLabel || process.env.SB_DM_ROOT_WITNESS_SOURCE_LABEL || descriptor.label).trim();

  let distribution = null;
  if (!descriptorOnly) {
    distribution = await fetchDistribution({
      url: normalizeUrl(args.baseUrl || process.env.SB_DM_ROOT_BASE_URL, args.distributionPath || process.env.SB_DM_ROOT_DISTRIBUTION_PATH),
      authHeader: process.env.SB_DM_ROOT_AUTH_HEADER || '',
      authCookie: process.env.SB_DM_ROOT_AUTH_COOKIE || '',
      timeoutMs: Math.max(1000, safeInt(process.env.SB_DM_ROOT_TIMEOUT_MS, 10000)),
    });
  }

  const packageDocument = buildImportPackage({
    identity,
    descriptor,
    sourceScope,
    sourceLabel,
    descriptorOnly,
    distribution,
  });

  await writeJsonFile(witnessFile, identity);

  const outputPath = String(args.output || process.env.SB_DM_ROOT_WITNESS_OUTPUT || '').trim();
  if (outputPath) {
    await writeJsonFile(outputPath, packageDocument);
  }
  if (args.stdout || !outputPath) {
    process.stdout.write(`${JSON.stringify(packageDocument, null, 2)}\n`);
  }
}

await main().catch((error) => {
  console.error(String(error?.message || error || 'external witness package publish failed').trim());
  process.exit(2);
});
