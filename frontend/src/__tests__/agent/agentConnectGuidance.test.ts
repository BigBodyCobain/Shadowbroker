/**
 * Regression coverage for the "Connect AI Agent" snippet.
 *
 * - The snippet told agents to use search_telemetry as the default entry point, but the backend
 *   rejects it (and the other EXPENSIVE_COMMANDS) unless confirm_expensive=true. Agents following
 *   the snippet hit the gate. Guidance must match backend routing: route_query / find_entity first.
 * - Operators pasted the secret into agent chats, where it leaked into history and was never set as
 *   an environment variable. The snippet must say how to install and verify it.
 * - The product name "OpenClaw" is retired from user-facing text (env vars and API paths keep it).
 */
import { describe, expect, it } from 'vitest';
import * as fs from 'fs';
import * as path from 'path';

const SRC = path.resolve(__dirname, '../..');
const REPO = path.resolve(SRC, '../..');
const panel = fs.readFileSync(path.join(SRC, 'components/AIIntelPanel.tsx'), 'utf-8');

function backendExpensiveCommands(): string[] {
  const routing = fs.readFileSync(path.join(REPO, 'backend/services/openclaw_routing.py'), 'utf-8');
  const block = routing.match(/EXPENSIVE_COMMANDS\s*=\s*frozenset\(\{([\s\S]*?)\}\)/);
  expect(block, 'EXPENSIVE_COMMANDS not found in backend routing').not.toBeNull();
  return [...block![1].matchAll(/"([a-z_]+)"/g)].map((m) => m[1]);
}

describe('Connect AI Agent snippet', () => {
  it('names every backend-gated expensive command and the confirm_expensive flag', () => {
    const expensiveLine = panel.split('\n').find((l) => l.includes('# EXPENSIVE:')) ?? '';
    for (const cmd of backendExpensiveCommands()) {
      expect(expensiveLine, `${cmd} missing from the EXPENSIVE line`).toContain(cmd);
    }
    expect(panel).toContain('confirm_expensive=true');
  });

  it('does not recommend search_telemetry as the default entry point', () => {
    expect(panel).not.toMatch(/search_telemetry as the Google-style entry point/);
    expect(panel).not.toMatch(/Prefer compact lookups first: get_summary, search_telemetry/);
    expect(panel).toContain('route_query');
    expect(panel).toContain('find_entity');
  });

  it('explains installing the secret as an environment variable, verifying it, and not pasting it into chat', () => {
    expect(panel).toContain('# SETUP');
    expect(panel).toContain('verify_hmac.py');
    expect(panel).toMatch(/Do NOT paste them into a chat channel/);
    expect(panel).toMatch(/Don&apos;t paste the secret into a chat/);
  });

  it('describes the agent by connection mode instead of always "remote"', () => {
    expect(panel).not.toContain('You are a remote OpenClaw agent');
    expect(panel).toContain('connected to ShadowBroker on the same machine');
    expect(panel).toContain('connected to ShadowBroker over the network');
  });

  it('includes the analyst directive for unattended investigations', () => {
    expect(panel).toContain('# ANALYST DIRECTIVE');
    expect(panel).toMatch(/probably noise/);
  });
});

describe('OpenClaw name retired from user-facing UI', () => {
  const USER_FACING = [
    'components/AIIntelPanel.tsx',
    'components/InfonetTerminal/AIQueryView.tsx',
    'components/MaplibreViewer/popups/CorrelationPopup.tsx',
    'components/MeshChat/AgentShellPanel.tsx',
    'components/OnboardingModal.tsx',
    'components/SettingsPanel.tsx',
    'components/WorldviewLeftPanel.tsx',
    'i18n/translations/en.json',
    'i18n/translations/fr.json',
    'i18n/translations/zh-CN.json',
    'i18n/translations/fa.json',
  ];

  it.each(USER_FACING)('%s has no user-facing OpenClaw text', (rel) => {
    const lines = fs.readFileSync(path.join(SRC, rel), 'utf-8').split('\n');
    const offenders = lines
      .map((line, i) => ({ line, n: i + 1 }))
      // Keep compatibility identifiers: env vars, API paths, the skill folder, backend field/source
      // values ('openclaw', openclaw_enabled) and code identifiers (openclawEnabled).
      .filter(({ line }) =>
        /openclaw/i.test(
          line.replace(/OPENCLAW_[A-Z_]+|openclaw[-_][\w/.-]*|\/api\/[\w/-]*|'openclaw'|openclaw[A-Z]\w*/g, ''),
        ),
      )
      .map(({ line, n }) => `${rel}:${n}: ${line.trim().slice(0, 100)}`);
    expect(offenders).toEqual([]);
  });
});
