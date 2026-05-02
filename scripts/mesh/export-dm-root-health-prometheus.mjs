#!/usr/bin/env node

import fs from 'node:fs/promises';
import path from 'node:path';

const HELP_TEXT = `
ShadowBroker DM root health Prometheus exporter

Usage:
  node scripts/mesh/export-dm-root-health-prometheus.mjs [--stdout] [--output PATH] [--base-url URL] [--health-path PATH]

Environment:
  SB_DM_ROOT_BASE_URL=http://127.0.0.1:8000
  SB_DM_ROOT_HEALTH_PATH=/api/wormhole/dm/root-health
  SB_DM_ROOT_AUTH_HEADER=X-Admin-Key: change-me
  SB_DM_ROOT_AUTH_COOKIE=operator_session=...
  SB_DM_ROOT_TIMEOUT_MS=10000
  SB_DM_ROOT_PROMETHEUS_OUTPUT=/var/lib/node_exporter/textfile_collector/shadowbroker_dm_root.prom

Flags:
  --stdout            Print Prometheus metrics to stdout
  --output PATH       Override SB_DM_ROOT_PROMETHEUS_OUTPUT
  --base-url URL      Override SB_DM_ROOT_BASE_URL
  --health-path PATH  Override SB_DM_ROOT_HEALTH_PATH
  --help              Show this text

Exit codes:
  0 = export succeeded
  2 = fetch or payload validation failed
`.trim();

function parseArgs(argv) {
  const parsed = {};
  for (let index = 0; index < argv.length; index += 1) {
    const current = String(argv[index] || '').trim();
    if (!current) continue;
    if (current === '--stdout') {
      parsed.stdout = true;
      continue;
    }
    if (current === '--help' || current === '-h') {
      parsed.help = true;
      continue;
    }
    if (
      (current === '--output' || current === '--base-url' || current === '--health-path') &&
      index + 1 < argv.length
    ) {
      parsed[current.slice(2).replace(/-([a-z])/g, (_match, letter) => letter.toUpperCase())] =
        String(argv[index + 1] || '').trim();
      index += 1;
    }
  }
  return parsed;
}

function normalizeUrl(baseUrl, healthPath) {
  const base = String(baseUrl || 'http://127.0.0.1:8000').trim().replace(/\/+$/, '');
  const pathValue = String(healthPath || '/api/wormhole/dm/root-health').trim();
  if (!pathValue) {
    return `${base}/api/wormhole/dm/root-health`;
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

function safeInt(value, fallback = 0) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return fallback;
  return Math.trunc(numeric);
}

function boolGauge(value) {
  return value ? 1 : 0;
}

function metricEscape(value) {
  return String(value ?? '')
    .replace(/\\/g, '\\\\')
    .replace(/\n/g, '\\n')
    .replace(/"/g, '\\"');
}

function labelsText(labels) {
  const entries = Object.entries(labels || {}).filter(([, value]) => String(value ?? '').length > 0);
  if (!entries.length) return '';
  return `{${entries.map(([key, value]) => `${key}="${metricEscape(value)}"`).join(',')}}`;
}

function appendMetric(lines, name, help, type, value, labels = undefined) {
  lines.push(`# HELP ${name} ${help}`);
  lines.push(`# TYPE ${name} ${type}`);
  lines.push(`${name}${labelsText(labels)} ${value}`);
}

function stateCode(value, mapping, fallback) {
  const key = String(value || '').trim().toLowerCase();
  if (Object.prototype.hasOwnProperty.call(mapping, key)) {
    return mapping[key];
  }
  return fallback;
}

function buildMetrics(payload, errorDetail = '') {
  const checkedAt = safeInt(payload?.checked_at || Math.floor(Date.now() / 1000), Math.floor(Date.now() / 1000));
  const summaryState = String(payload?.state || '').trim().toLowerCase();
  const healthState = String(payload?.health_state || '').trim().toLowerCase();
  const monitorState = String(payload?.monitoring?.state || '').trim().toLowerCase();
  const witnessState = String(payload?.witness?.state || '').trim().toLowerCase();
  const transparencyState = String(payload?.transparency?.state || '').trim().toLowerCase();
  const nextAction = String(payload?.next_action || '').trim();
  const alerts = Array.isArray(payload?.alerts) ? payload.alerts.filter((item) => item && typeof item === 'object') : [];

  const summaryStateCode = stateCode(
    summaryState,
    { local_cached_only: 0, current_external: 1, stale_external: 2 },
    -1,
  );
  const healthStateCode = stateCode(
    healthState,
    { ok: 0, warning: 1, stale: 2, error: 3 },
    -1,
  );
  const monitorStateCode = stateCode(
    monitorState,
    { ok: 0, warning: 1, critical: 2 },
    -1,
  );
  const witnessStateCode = stateCode(
    witnessState,
    { not_configured: 0, descriptors_only: 1, current: 2, stale: 3, error: 4 },
    -1,
  );
  const transparencyStateCode = stateCode(
    transparencyState,
    { not_configured: 0, current: 1, stale: 2, error: 3 },
    -1,
  );

  const lines = [];
  appendMetric(
    lines,
    'shadowbroker_dm_root_health_scrape_success',
    'Whether the DM root health scrape succeeded.',
    'gauge',
    errorDetail ? 0 : 1,
  );
  appendMetric(
    lines,
    'shadowbroker_dm_root_checked_at_unixtime',
    'Unix timestamp for the most recent DM root health check represented in this export.',
    'gauge',
    checkedAt,
  );
  appendMetric(
    lines,
    'shadowbroker_dm_root_summary_state_code',
    'DM root operator summary state (0=local_cached_only, 1=current_external, 2=stale_external, -1=unknown).',
    'gauge',
    summaryStateCode,
  );
  appendMetric(
    lines,
    'shadowbroker_dm_root_health_state_code',
    'DM root rolled-up health state (0=ok, 1=warning, 2=stale, 3=error, -1=unknown).',
    'gauge',
    healthStateCode,
  );
  appendMetric(
    lines,
    'shadowbroker_dm_root_monitor_state_code',
    'Monitoring severity for DM root health (0=ok, 1=warning, 2=critical, -1=unknown).',
    'gauge',
    monitorStateCode,
  );
  appendMetric(
    lines,
    'shadowbroker_dm_root_strong_trust_blocked',
    'Whether strong DM trust is currently blocked by external assurance state.',
    'gauge',
    boolGauge(Boolean(payload?.strong_trust_blocked)),
  );
  appendMetric(
    lines,
    'shadowbroker_dm_root_external_assurance_current',
    'Whether configured external witness and transparency assurances are both current.',
    'gauge',
    boolGauge(Boolean(payload?.external_assurance_current)),
  );
  appendMetric(
    lines,
    'shadowbroker_dm_root_requires_attention',
    'Whether DM root external assurance currently requires operator attention.',
    'gauge',
    boolGauge(Boolean(payload?.requires_attention)),
  );
  appendMetric(
    lines,
    'shadowbroker_dm_root_independent_quorum_met',
    'Whether the current witness state satisfies independent quorum.',
    'gauge',
    boolGauge(Boolean(payload?.independent_quorum_met)),
  );
  appendMetric(
    lines,
    'shadowbroker_dm_root_alert_count',
    'Number of active DM root health alerts.',
    'gauge',
    safeInt(payload?.alert_count, 0),
  );
  appendMetric(
    lines,
    'shadowbroker_dm_root_blocking_alert_count',
    'Number of active blocking DM root health alerts.',
    'gauge',
    safeInt(payload?.blocking_alert_count, 0),
  );
  appendMetric(
    lines,
    'shadowbroker_dm_root_warning_alert_count',
    'Number of active warning-level DM root health alerts.',
    'gauge',
    safeInt(payload?.warning_alert_count, 0),
  );
  appendMetric(
    lines,
    'shadowbroker_dm_root_witness_state_code',
    'Witness operator state (0=not_configured, 1=descriptors_only, 2=current, 3=stale, 4=error, -1=unknown).',
    'gauge',
    witnessStateCode,
  );
  appendMetric(
    lines,
    'shadowbroker_dm_root_witness_health_state_code',
    'Witness health state (0=ok, 1=warning, 2=stale, 3=error, -1=unknown).',
    'gauge',
    stateCode(String(payload?.witness?.health_state || '').trim().toLowerCase(), { ok: 0, warning: 1, stale: 2, error: 3 }, -1),
  );
  appendMetric(
    lines,
    'shadowbroker_dm_root_witness_age_seconds',
    'Age in seconds of the current external witness package.',
    'gauge',
    safeInt(payload?.witness?.age_s, 0),
  );
  appendMetric(
    lines,
    'shadowbroker_dm_root_witness_warning_window_seconds',
    'Configured warning threshold for external witness freshness.',
    'gauge',
    safeInt(payload?.witness?.warning_window_s, 0),
  );
  appendMetric(
    lines,
    'shadowbroker_dm_root_witness_freshness_window_seconds',
    'Configured maximum freshness window for external witness material.',
    'gauge',
    safeInt(payload?.witness?.freshness_window_s, 0),
  );
  appendMetric(
    lines,
    'shadowbroker_dm_root_witness_reacquire_required',
    'Whether external witness receipt reacquisition is currently required.',
    'gauge',
    boolGauge(Boolean(payload?.witness?.reacquire_required)),
  );
  appendMetric(
    lines,
    'shadowbroker_dm_root_witness_manifest_matches_current',
    'Whether the external witness material matches the current manifest fingerprint.',
    'gauge',
    boolGauge(Boolean(payload?.witness?.manifest_matches_current)),
  );
  appendMetric(
    lines,
    'shadowbroker_dm_root_witness_independent_quorum_met',
    'Whether the witness side independently satisfies quorum.',
    'gauge',
    boolGauge(Boolean(payload?.witness?.independent_quorum_met)),
  );
  appendMetric(
    lines,
    'shadowbroker_dm_root_transparency_state_code',
    'Transparency operator state (0=not_configured, 1=current, 2=stale, 3=error, -1=unknown).',
    'gauge',
    transparencyStateCode,
  );
  appendMetric(
    lines,
    'shadowbroker_dm_root_transparency_health_state_code',
    'Transparency health state (0=ok, 1=warning, 2=stale, 3=error, -1=unknown).',
    'gauge',
    stateCode(String(payload?.transparency?.health_state || '').trim().toLowerCase(), { ok: 0, warning: 1, stale: 2, error: 3 }, -1),
  );
  appendMetric(
    lines,
    'shadowbroker_dm_root_transparency_age_seconds',
    'Age in seconds of the current external transparency ledger readback.',
    'gauge',
    safeInt(payload?.transparency?.age_s, 0),
  );
  appendMetric(
    lines,
    'shadowbroker_dm_root_transparency_warning_window_seconds',
    'Configured warning threshold for external transparency freshness.',
    'gauge',
    safeInt(payload?.transparency?.warning_window_s, 0),
  );
  appendMetric(
    lines,
    'shadowbroker_dm_root_transparency_freshness_window_seconds',
    'Configured maximum freshness window for external transparency readback.',
    'gauge',
    safeInt(payload?.transparency?.freshness_window_s, 0),
  );
  appendMetric(
    lines,
    'shadowbroker_dm_root_transparency_verification_required',
    'Whether transparency verification refresh is currently required.',
    'gauge',
    boolGauge(Boolean(payload?.transparency?.verification_required)),
  );

  appendMetric(
    lines,
    'shadowbroker_dm_root_summary_info',
    'State labels for the current DM root operator summary.',
    'gauge',
    1,
    {
      summary_state: summaryState || 'unknown',
      health_state: healthState || 'unknown',
      monitor_state: monitorState || 'unknown',
      witness_state: witnessState || 'unknown',
      transparency_state: transparencyState || 'unknown',
    },
  );
  if (nextAction) {
    appendMetric(
      lines,
      'shadowbroker_dm_root_next_action_info',
      'Suggested next DM root operator action.',
      'gauge',
      1,
      { action: nextAction },
    );
  }
  if (errorDetail) {
    appendMetric(
      lines,
      'shadowbroker_dm_root_health_scrape_error_info',
      'Reason for the most recent DM root health scrape failure.',
      'gauge',
      1,
      { reason: errorDetail },
    );
  }
  for (const alert of alerts) {
    const code = String(alert?.code || '').trim();
    if (!code) continue;
    appendMetric(
      lines,
      'shadowbroker_dm_root_alert_active',
      'Active DM root health alerts.',
      'gauge',
      1,
      {
        code,
        severity: String(alert?.severity || '').trim().toLowerCase() || 'unknown',
        target: String(alert?.target || '').trim().toLowerCase() || 'dm_root',
        blocking: boolGauge(Boolean(alert?.blocking)).toString(),
      },
    );
  }
  return `${lines.join('\n')}\n`;
}

async function fetchHealth(config) {
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
      throw new Error(detail || 'dm_root_health_failed');
    }
    return payload;
  } finally {
    globalThis.clearTimeout(timeout);
  }
}

async function writeMetrics(outputPath, text) {
  const resolved = path.resolve(outputPath);
  await fs.mkdir(path.dirname(resolved), { recursive: true });
  const tempPath = `${resolved}.tmp`;
  await fs.writeFile(tempPath, text, 'utf8');
  await fs.rename(tempPath, resolved);
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    console.log(HELP_TEXT);
    return;
  }

  const config = {
    url: normalizeUrl(args.baseUrl || process.env.SB_DM_ROOT_BASE_URL, args.healthPath || process.env.SB_DM_ROOT_HEALTH_PATH),
    authHeader: process.env.SB_DM_ROOT_AUTH_HEADER || '',
    authCookie: process.env.SB_DM_ROOT_AUTH_COOKIE || '',
    timeoutMs: Math.max(1000, safeInt(process.env.SB_DM_ROOT_TIMEOUT_MS, 10000)),
    output: String(args.output || process.env.SB_DM_ROOT_PROMETHEUS_OUTPUT || '').trim(),
    stdout: Boolean(args.stdout),
  };

  let metricsText = '';
  let exitCode = 0;
  try {
    const payload = await fetchHealth(config);
    metricsText = buildMetrics(payload);
  } catch (error) {
    const detail = String(error?.message || 'dm_root_health_fetch_failed').trim() || 'dm_root_health_fetch_failed';
    metricsText = buildMetrics(
      {
        checked_at: Math.floor(Date.now() / 1000),
        state: 'stale_external',
        health_state: 'error',
        monitoring: { state: 'critical' },
        strong_trust_blocked: true,
        requires_attention: true,
        alert_count: 1,
        blocking_alert_count: 1,
        warning_alert_count: 0,
        alerts: [
          {
            code: 'dm_root_health_scrape_failed',
            severity: 'error',
            target: 'dm_root',
            blocking: true,
          },
        ],
        witness: {},
        transparency: {},
      },
      detail,
    );
    exitCode = 2;
  }

  if (config.output) {
    await writeMetrics(config.output, metricsText);
  }
  if (config.stdout || !config.output) {
    process.stdout.write(metricsText);
  }
  if (exitCode) {
    process.exit(exitCode);
  }
}

await main();
