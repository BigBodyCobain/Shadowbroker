// @ts-nocheck
import { useCallback } from 'react';
const API = '';
export function useMeshTerminalDmCommand(ctx: any) {
  const { addError, addLines, addOutput, addSystem, nodeIdentity, hasSovereignty } = ctx;
  const handleDmCommand = async (cmd: string, args: string[], d: any) => {
    switch (cmd) {
            case 'dm': {
              const sub = args[0]?.toLowerCase();

              if (sub === 'selftest' || sub === 'test') {
                addSystem('  Running local DM selftest...');
                try {
                  const data = await runWormholeDmSelftest(args.slice(1).join(' '));
                  const failedSteps = (data.steps || []).filter((step) => !step.ok);
                  const failedChecks = (data.privacy_checks || []).filter((check) => !check.ok);
                  if (data.ok) {
                    addSystem('  DM SELFTEST PASSED');
                  } else {
                    addError(
                      `DM selftest failed: ${failedSteps.length} step(s), ${failedChecks.length} privacy check(s) failed.`,
                    );
                  }
                  addOutput(`    Mode:       ${data.mode}`);
                  addOutput(`    Transport:  ${data.transport_tier}`);
                  addOutput(`    Run ID:     ${data.run_id}`);
                  addOutput(
                    `    Steps:      ${(data.steps || []).filter((step) => step.ok).length}/${(data.steps || []).length}`,
                  );
                  addOutput(
                    `    Warnings:   ${(data.steps || []).filter((step) => !step.ok && !step.required).length}`,
                  );
                  addOutput(
                    `    Privacy:    ${(data.privacy_checks || []).filter((check) => check.ok).length}/${(data.privacy_checks || []).length}`,
                  );
                  if (data.artifacts?.ciphertext_sha256) {
                    addLines([
                      {
                        text: `    Ciphertext: ${data.artifacts.ciphertext_sha256.slice(0, 24)}...`,
                        type: 'dim',
                      },
                    ]);
                  }
                  for (const check of data.privacy_checks || []) {
                    addLines([
                      {
                        text: `    [${check.ok ? 'OK' : 'FAIL'}] ${check.name}: ${check.detail || ''}`,
                        type: check.ok ? 'output' : 'error',
                      },
                    ]);
                  }
                  const limits = (data.unproven_by_this_test || []).slice(0, 3);
                  if (limits.length) {
                    addSystem('  Still unproven by this local test:');
                    for (const limit of limits) {
                      addLines([{ text: `    - ${limit}`, type: 'dim' }]);
                    }
                  }
                } catch (err) {
                  const msg =
                    typeof err === 'object' && err !== null && 'message' in err
                      ? String((err as { message?: string }).message)
                      : 'selftest failed';
                  addError(`DM selftest failed: ${msg}`);
                }
                addSystem('');
                return;
              }

              if (!nodeIdentity || !hasSovereignty()) {
                addError("Not connected. Type 'connect' to activate your Agent identity.");
                return;
              }

              // dm add <agent_id> [alias]
              if (sub === 'add') {
                const targetId = args[1];
                if (!targetId) {
                  addError('Usage: dm add <agent_id> [alias]');
                  return;
                }
                try {
                  const data = await fetchDmPublicKey(API, targetId, undefined, {
                    allowLegacyAgentId: true,
                  });
                  if (!data?.dh_pub_key) {
                    addError('Agent not found or has no DM keys.');
                    return;
                  }
                  const alias = args[2] || undefined;
                  addContact(targetId, data.dh_pub_key, alias, data.dh_algo);
                  updateContact(targetId, {
                    remotePrekeyLookupMode: String(data.lookup_mode || '').trim().toLowerCase(),
                  });
                  addSystem(`  Contact added: ${targetId}${alias ? ` (${alias})` : ''}`);
                  if (String(data.lookup_mode || '').trim().toLowerCase() === 'legacy_agent_id') {
                    addLines([
                      {
                        text: "  Legacy lookup only. Import or re-import a signed invite to replace stable-ID lookup.",
                        type: 'dim',
                      },
                    ]);
                  }
                } catch {
                  addError('Failed to fetch agent key');
                }
                return;
              }

              // dm block <agent_id>
              if (sub === 'block') {
                const targetId = args[1];
                if (!targetId) {
                  addError('Usage: dm block <agent_id>');
                  return;
                }
                blockContact(targetId);
                try {
                  const sequence = nextSequence();
                  const blockPayload = {
                    blocked_id: targetId,
                    action: 'block',
                    transport_lock: 'private_strong',
                  };
                  const v = validateEventPayload('dm_block', blockPayload);
                  if (!v.ok) {
                    addError(`Invalid payload: ${v.reason}`);
                    return;
                  }
                  const signature = await signEvent(
                    'dm_block',
                    nodeIdentity.nodeId,
                    sequence,
                    blockPayload,
                  );
                  await fetch(`${API}/api/mesh/dm/block`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                      agent_id: nodeIdentity.nodeId,
                      blocked_id: targetId,
                      action: 'block',
                      transport_lock: 'private_strong',
                      public_key: nodeIdentity.publicKey,
                      public_key_algo: getPublicKeyAlgo(),
                      signature,
                      sequence,
                      protocol_version: PROTOCOL_VERSION,
                    }),
                  });
                } catch {
                  /* local block still works */
                }
                addSystem(`  Blocked ${targetId}. Their messages will be dropped.`);
                return;
              }

              // dm unblock <agent_id>
              if (sub === 'unblock') {
                const targetId = args[1];
                if (!targetId) {
                  addError('Usage: dm unblock <agent_id>');
                  return;
                }
                unblockContact(targetId);
                try {
                  const sequence = nextSequence();
                  const blockPayload = {
                    blocked_id: targetId,
                    action: 'unblock',
                    transport_lock: 'private_strong',
                  };
                  const v = validateEventPayload('dm_block', blockPayload);
                  if (!v.ok) {
                    addError(`Invalid payload: ${v.reason}`);
                    return;
                  }
                  const signature = await signEvent(
                    'dm_block',
                    nodeIdentity.nodeId,
                    sequence,
                    blockPayload,
                  );
                  await fetch(`${API}/api/mesh/dm/block`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                      agent_id: nodeIdentity.nodeId,
                      blocked_id: targetId,
                      action: 'unblock',
                      transport_lock: 'private_strong',
                      public_key: nodeIdentity.publicKey,
                      public_key_algo: getPublicKeyAlgo(),
                      signature,
                      sequence,
                      protocol_version: PROTOCOL_VERSION,
                    }),
                  });
                } catch {
                  /* local unblock still works */
                }
                addSystem(`  Unblocked ${targetId}.`);
                return;
              }

              // dm notify on|off
              if (sub === 'notify') {
                const val = args[1]?.toLowerCase();
                if (val === 'on') {
                  setDMNotify(true);
                  addSystem('  DM notifications ON.');
                } else if (val === 'off') {
                  setDMNotify(false);
                  addSystem('  DM notifications OFF.');
                  if (onDmCount) onDmCount(0);
                } else {
                  addSystem(`  DM notifications: ${getDMNotify() ? 'ON' : 'OFF'}`);
                  addLines([{ text: '  Usage: dm notify on|off', type: 'dim' }]);
                }
                return;
              }

              // dm <agent_id> <message> — direct one-liner send
              if (sub && sub.startsWith('!sb_')) {
                const msg = args.slice(1).join(' ');
                if (!msg) {
                  // Start interactive DM with this recipient
                  setDmDest(sub);
                  setDmStep('msg');
                  addSystem('');
                  addSystem(`  DM to ${sub}`);
                  addLines([{ text: '  Type your private message:', type: 'dim' }]);
                  addSystem('');
                  return;
                }
                await doDMSend(sub, msg);
                return;
              }

              // bare "dm" — interactive flow
              if (!sub) {
                addSystem('');
                addSystem('  ENCRYPTED DM');
                addLines([{ text: '  Enter recipient Agent ID (e.g. !sb_a3f2c891):', type: 'dim' }]);
                addSystem('');
                setDmStep('dest');
                return;
              }

              addError('Usage: dm [agent_id] [msg] | dm add/block/unblock/notify');
              return;
            }
      default: return;
    }
  };

  return { handleDmCommand };
}
