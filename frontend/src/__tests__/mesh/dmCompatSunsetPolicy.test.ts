// @ts-nocheck
import * as fs from 'node:fs';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

function readSource(relativePath: string): string {
  const here = path.dirname(fileURLToPath(import.meta.url));
  return fs.readFileSync(path.resolve(here, relativePath), 'utf-8');
}

describe('Sprint 6 DM compatibility sunset policy', () => {
  it('keeps receive-side MeshChat request parsing off ambient legacy agent-id lookup', () => {
    const controller = readSource('../../components/MeshChat/useMeshChatController.ts');
    const dmPolling = readSource('../../components/MeshChat/useDmPolling.ts');
    const receiveSide = controller + '\n' + dmPolling;

    expect(receiveSide).toMatch(
      /fetchDmPublicKey\(\s*API_BASE,\s*m\.sender_id,\s*senderContact\?\.invitePinnedPrekeyLookupHandle/s,
    );
    expect(receiveSide).not.toMatch(
      /fetchDmPublicKey\(\s*API_BASE,\s*m\.sender_id,[\s\S]{0,200}allowLegacyAgentId:\s*true/s,
    );
  });

  it('keeps MessagesView receive-side contact parsing off ambient legacy agent-id lookup', () => {
    const messagesView = readSource('../../components/InfonetTerminal/MessagesView.tsx');

    expect(messagesView).toMatch(
      /fetchDmPublicKey\(\s*API_BASE,\s*senderId,\s*existingContact\?\.invitePinnedPrekeyLookupHandle/s,
    );
    expect(messagesView).not.toMatch(
      /fetchDmPublicKey\(\s*API_BASE,\s*senderId,[\s\S]{0,200}allowLegacyAgentId:\s*true/s,
    );
  });

  it('keeps MeshTerminal legacy lookup limited to explicit migration commands', () => {
    const terminal = readSource('../../components/MeshTerminal.tsx');
    const dmCommand = readSource('../../components/MeshTerminalDmCommand.ts');
    const sendFlow = readSource('../../components/MeshTerminalSendFlow.ts');
    const terminalSurface = terminal + '\n' + dmCommand + '\n' + sendFlow;

    expect(terminalSurface).not.toMatch(
      /fetchDmPublicKey\(\s*API,\s*message\.sender_id,[\s\S]{0,200}allowLegacyAgentId:/s,
    );
    expect(terminalSurface).not.toMatch(
      /fetchDmPublicKey\(\s*API,\s*m\.sender_id,[\s\S]{0,200}allowLegacyAgentId:/s,
    );

    const legacyLookupMatches = terminalSurface.match(/allowLegacyAgentId:\s*true/g) || [];
    expect(legacyLookupMatches).toHaveLength(1);
    expect(terminalSurface).toContain("only for legacy migration");
  });
});
