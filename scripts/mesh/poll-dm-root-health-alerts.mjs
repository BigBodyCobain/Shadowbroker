#!/usr/bin/env node

import fs from 'node:fs/promises';
import path from 'node:path';

const HELP_TEXT = `
ShadowBroker DM root health poller

Usage:
  node scripts/mesh/poll-dm-root-health-alerts.mjs [--once] [--base-url URL] [--alerts-path PATH]

Environment:
  SB_DM_ROOT_BASE_URL=http://127.0.0.1:8000
  SB_DM_ROOT_ALERTS_PATH=/api/wormhole/dm/root-health/alerts
  SB_DM_ROOT_AUTH_HEADER=X-Admin-Key: change-me
  SB_DM_ROOT_AUTH_COOKIE=operator_session=...
  SB_DM_ROOT_INTERVAL_S=60
  SB_DM_ROOT_TIMEOUT_MS=10000
  SB_DM_ROOT_STATE_FILE=data/dm_root_health_bridge_state.json
  SB_DM_ROOT_WARNING_WEBHOOK_URL=https://hooks.slack.example/services/...
  SB_DM_ROOT_CRITICAL_WEBHOOK_URL=https://events.pagerduty.example/v2/enqueue

Flags:
  --once              Poll one time and exit with status 0/1/2
  --base-url URL      Override SB_DM_ROOT_BASE_URL
  --alerts-path PATH  Override SB_DM_ROOT_ALERTS_PATH
  --help              Show this text

Exit codes for --once:
  0 = ok
  1 = warning
  2 = critical or fetch failure
`.trim();

function parseArgs(argv) {
  const parsed = {};
  for (let index = 0; index < argv.length; index += 1) {
    const current = String(argv[index] || '').trim();
    if (!current) continue;
    if (current === '--once') {
      parsed.once = true;
      continue;
    }
    if (current === '--help' || current === '-h') {
      parsed.help = true;
      continue;
    }
    if ((current === '--base-url' || current === '--alerts-path') && index + 1 < argv.length) {
      parsed[current.slice(2).replace(/-([a-z])/g, (_match, letter) => letter.toUpperCase())] =
        String(argv[index + 1] || '').trim();
      index += 1;
    }
  }
  return parsed;
}

function normalizeUrl(baseUrl, alertsPath) {
  const base = String(baseUrl || 'http://127.0.0.1:8000').trim().replace(/\/+$/, '');
  const pathValue = String(alertsPath || '/api/wormhole/dm/root-health/alerts').trim();
  if (!pathValue) {
    return `${base}/api/wormhole/dm/root-health/alerts`;
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

function severityFromPayload(payload) {
  const state = String(payload?.state || '').trim().toLowerCase();
  if (state === 'critical') return 'critical';
  if (state === 'warning') return 'warning';
  if (state === 'ok') return 'ok';
  if (payload?.page_required) return 'critical';
  if (payload?.ticket_required) return 'warning';
  return 'critical';
}

function buildFingerprint(payload) {
  return JSON.stringify({
    severity: severityFromPayload(payload),
    state: String(payload?.state || '').trim().toLowerCase(),
    page_required: Boolean(payload?.page_required),
    ticket_required: Boolean(payload?.ticket_required),
    active_alert_codes: Array.isArray(payload?.active_alert_codes) ? payload.active_alert_codes : [],
    next_action: String(payload?.next_action || '').trim(),
    alert_count: Number(payload?.alert_count || 0),
    blocking_alert_count: Number(payload?.blocking_alert_count || 0),
    warning_alert_count: Number(payload?.warning_alert_count || 0),
  });
}

function buildSummary(payload) {
  const severity = severityFromPayload(payload);
  const activeAlertCodes = Array.isArray(payload?.active_alert_codes)
    ? payload.active_alert_codes.map((value) => String(value || '').trim()).filter(Boolean)
    : [];
  return {
    severity,
    state: String(payload?.state || '').trim().toLowerCase() || 'critical',
    checkedAt: Number(payload?.checked_at || 0),
    pageRequired: Boolean(payload?.page_required),
    ticketRequired: Boolean(payload?.ticket_required),
    recommendedCheckIntervalS: Number(payload?.recommended_check_interval_s || 60),
    nextAction: String(payload?.next_action || '').trim(),
    primaryAlert: String(payload?.primary_alert || '').trim(),
    activeAlertCodes,
    alertCount: Number(payload?.alert_count || 0),
    blockingAlertCount: Number(payload?.blocking_alert_count || 0),
    warningAlertCount: Number(payload?.warning_alert_count || 0),
    fingerprint: buildFingerprint(payload),
    raw: payload,
  };
}

function failureSummary(detail) {
  const message = String(detail || '').trim() || 'dm_root_health_poll_failed';
  return {
    severity: 'critical',
    state: 'critical',
    checkedAt: Math.floor(Date.now() / 1000),
    pageRequired: true,
    ticketRequired: true,
    recommendedCheckIntervalS: 60,
    nextAction: 'check_root_health_endpoint',
    primaryAlert: message,
    activeAlertCodes: ['dm_root_health_poll_failed'],
    alertCount: 1,
    blockingAlertCount: 1,
    warningAlertCount: 0,
    fingerprint: JSON.stringify({ severity: 'critical', error: message }),
    raw: {
      ok: false,
      state: 'critical',
      primary_alert: message,
      active_alert_codes: ['dm_root_health_poll_failed'],
      next_action: 'check_root_health_endpoint',
      page_required: true,
      ticket_required: true,
      recommended_check_interval_s: 60,
    },
  };
}

async function loadStateFile(stateFile) {
  if (!stateFile) return {};
  try {
    const raw = await fs.readFile(stateFile, 'utf8');
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
}

async function writeStateFile(stateFile, value) {
  if (!stateFile) return;
  const targetPath = path.resolve(stateFile);
  await fs.mkdir(path.dirname(targetPath), { recursive: true });
  await fs.writeFile(targetPath, JSON.stringify(value, null, 2));
}

async function fetchAlerts(config) {
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
      throw new Error(detail || 'dm_root_health_alerts_failed');
    }
    return buildSummary(payload);
  } finally {
    globalThis.clearTimeout(timeout);
  }
}

async function postWebhook(targetUrl, summary, config) {
  if (!targetUrl) {
    return { delivered: false, reason: 'no_target' };
  }
  const headers = {
    'Content-Type': 'application/json',
    Accept: 'application/json',
  };
  const payload = {
    source: 'shadowbroker_dm_root_health_bridge',
    sent_at: new Date().toISOString(),
    severity: summary.severity,
    monitoring_state: summary.state,
    page_required: summary.pageRequired,
    ticket_required: summary.ticketRequired,
    primary_alert: summary.primaryAlert,
    next_action: summary.nextAction,
    active_alert_codes: summary.activeAlertCodes,
    alert_count: summary.alertCount,
    blocking_alert_count: summary.blockingAlertCount,
    warning_alert_count: summary.warningAlertCount,
    checked_at: summary.checkedAt,
    raw: summary.raw,
  };
  const controller = new AbortController();
  const timeout = globalThis.setTimeout(() => controller.abort(), config.timeoutMs);
  try {
    const response = await fetch(targetUrl, {
      method: 'POST',
      headers,
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    if (!response.ok) {
      throw new Error(`webhook_http_${response.status}`);
    }
    return { delivered: true, reason: 'sent' };
  } finally {
    globalThis.clearTimeout(timeout);
  }
}

async function maybeDeliverWebhook(summary, config) {
  if (summary.severity === 'ok') {
    return { delivered: false, reason: 'ok_state' };
  }
  const state = await loadStateFile(config.stateFile);
  if (
    String(state.last_fingerprint || '') === summary.fingerprint &&
    String(state.last_severity || '') === summary.severity
  ) {
    return { delivered: false, reason: 'duplicate' };
  }
  const targetUrl =
    summary.severity === 'critical' ? config.criticalWebhookUrl : config.warningWebhookUrl;
  const delivered = await postWebhook(targetUrl, summary, config);
  if (delivered.delivered) {
    await writeStateFile(config.stateFile, {
      last_checked_at: summary.checkedAt,
      last_severity: summary.severity,
      last_fingerprint: summary.fingerprint,
      last_target: targetUrl,
    });
  }
  return delivered;
}

function printSummary(summary, webhookResult) {
  const prefix = summary.severity.toUpperCase().padEnd(8, ' ');
  const alerts = summary.activeAlertCodes.length > 0 ? summary.activeAlertCodes.join(',') : 'none';
  const nextAction = summary.nextAction || 'none';
  const webhookNote = webhookResult?.reason ? ` webhook=${webhookResult.reason}` : '';
  console.log(
    `[${prefix}] state=${summary.state} page=${summary.pageRequired} ticket=${summary.ticketRequired} ` +
      `alerts=${alerts} next_action=${nextAction}${webhookNote}`,
  );
}

function exitCodeForSeverity(severity) {
  if (severity === 'ok') return 0;
  if (severity === 'warning') return 1;
  return 2;
}

async function sleep(ms) {
  return new Promise((resolve) => {
    globalThis.setTimeout(resolve, ms);
  });
}

async function pollOnce(config) {
  try {
    const summary = await fetchAlerts(config);
    const webhookResult = await maybeDeliverWebhook(summary, config);
    printSummary(summary, webhookResult);
    return summary;
  } catch (error) {
    const summary = failureSummary(error instanceof Error ? error.message : 'dm_root_health_poll_failed');
    const webhookResult = await maybeDeliverWebhook(summary, config).catch(() => ({
      delivered: false,
      reason: 'webhook_failed',
    }));
    printSummary(summary, webhookResult);
    return summary;
  }
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    console.log(HELP_TEXT);
    return;
  }

  const config = {
    once: Boolean(args.once),
    url: normalizeUrl(args.baseUrl || process.env.SB_DM_ROOT_BASE_URL, args.alertsPath || process.env.SB_DM_ROOT_ALERTS_PATH),
    authHeader: process.env.SB_DM_ROOT_AUTH_HEADER || '',
    authCookie: process.env.SB_DM_ROOT_AUTH_COOKIE || '',
    intervalMs: Math.max(5, Number(process.env.SB_DM_ROOT_INTERVAL_S || 60)) * 1000,
    timeoutMs: Math.max(1000, Number(process.env.SB_DM_ROOT_TIMEOUT_MS || 10000)),
    stateFile: process.env.SB_DM_ROOT_STATE_FILE || '',
    warningWebhookUrl: process.env.SB_DM_ROOT_WARNING_WEBHOOK_URL || '',
    criticalWebhookUrl: process.env.SB_DM_ROOT_CRITICAL_WEBHOOK_URL || '',
  };

  if (config.once) {
    const summary = await pollOnce(config);
    process.exitCode = exitCodeForSeverity(summary.severity);
    return;
  }

  while (true) {
    const summary = await pollOnce(config);
    const nextDelayMs = Math.max(
      5000,
      Number(summary.recommendedCheckIntervalS || config.intervalMs / 1000) * 1000,
    );
    await sleep(nextDelayMs || config.intervalMs);
  }
}

await main();
