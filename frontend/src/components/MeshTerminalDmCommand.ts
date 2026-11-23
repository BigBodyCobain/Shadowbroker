import { useCallback } from 'react';
import {
  hasSovereignty, addContact, updateContact, blockContact, unblockContact,
  getDMNotify, setDMNotify, nextSequence, signEvent, getPublicKeyAlgo,
} from '@/mesh/meshIdentity';
import { fetchDmPublicKey } from '@/mesh/meshDmClient';
import { PROTOCOL_VERSION } from '@/mesh/meshProtocol';
import { validateEventPayload } from '@/mesh/meshSchema';
import { runWormholeDmSelftest } from '@/mesh/wormholeIdentityClient';

const API = '';

export function useMeshTerminalDmCommand(ctx: any) {
  const { addError, addLines, addOutput, addSystem, nodeIdentity, doDMSend, onDmCount, setDmDest, setDmStep } = ctx;

  const handleDmCommand = useCallback(async (_cmd: string, args: string[], _d?: any) => {
    const sub = args[0]?.toLowerCase();

    if (sub === 'selftest' || sub === 'test') {
      addSystem('  Running local DM selftest...');
      try {
        const data = await runWormholeDmSelftest(args.slice(1).join(' '));
        const steps = data.steps || [];
        const checks = data.privacy_checks || [];
        const failedSteps = steps.filter((step: any) => !step.ok);
        const failedChecks = checks.filter((check: any) => !check.ok);
        if (data.ok) addSystem('  DM SELFTEST PASSED');
        else addError(`DM selftest failed: ${failedSteps.length} step(s), ${failedChecks.length} privacy check(s) failed.`);
        addOutput(`    Mode:       ${data.mode}`);
        addOutput(`    Transport:  ${data.transport_tier}`);
        addOutput(`    Run ID:     ${data.run_id}`);
        addOutput(`    Steps:      ${steps.filter((s: any) => s.ok).length}/${steps.length}`);
        addOutput(`    Warnings:   ${steps.filter((s: any) => !s.ok && !s.required).length}`);
        addOutput(`    Privacy:    ${checks.filter((c: any) => c.ok).length}/${checks.length}`);
        if (data.artifacts?.ciphertext_sha256) {
          addLines([{ text: `    Ciphertext: ${data.artifacts.ciphertext_sha256.slice(0, 24)}...`, type: 'dim' }]);
        }
        for (const check of checks) {
          addLines([{ text: `    [${check.ok ? 'OK' : 'FAIL'}] ${check.name}: ${check.detail || ''}`, type: check.ok ? 'output' : 'error' }]);
        }
        const limits = ((data as any).unproven_by_this_test || []).slice(0, 3);
        if (limits.length) {
          addSystem('  Still unproven by this local test:');
          for (const limit of limits) addLines([{ text: `    - ${limit}`, type: 'dim' }]);
        }
      } catch (err) {
        const msg = typeof err === 'object' && err !== null && 'message' in err ? String((err as any).message) : 'selftest failed';
        addError(`DM selftest failed: ${msg}`);
      }
      addSystem('');
      return;
    }

    if (!nodeIdentity || !hasSovereignty()) {
      addError("Not connected. Type 'connect' to activate your Agent identity.");
      return;
    }

    if (sub === 'add') {
      const targetId = args[1];
      if (!targetId) { addError('Usage: dm add <agent_id> [alias]'); return; }
      try {
        const data = await fetchDmPublicKey(API, targetId, undefined, { allowLegacyAgentId: true } as any);
        if (!data?.dh_pub_key) { addError('Agent not found or has no DM keys.'); return; }
        const alias = args[2] || undefined;
        addContact(targetId, data.dh_pub_key, alias, (data as any).dh_algo);
        updateContact(targetId, { remotePrekeyLookupMode: String((data as any).lookup_mode || '').trim().toLowerCase() } as any);
        addSystem(`  Contact added: ${targetId}${alias ? ` (${alias})` : ''}`);
        if (String((data as any).lookup_mode || '').trim().toLowerCase() === 'legacy_agent_id') {
          addLines([{ text: "  Legacy lookup only. Import or re-import a signed invite to replace stable-ID lookup.", type: 'dim' }]);
        }
      } catch {
        addError('Failed to fetch agent key');
      }
      return;
    }

    if (sub === 'block' || sub === 'unblock') {
      const targetId = args[1];
      const action = sub as 'block' | 'unblock';
      if (!targetId) { addError(`Usage: dm ${action} <agent_id>`); return; }
      if (action === 'block') blockContact(targetId); else unblockContact(targetId);
      try {
        const sequence = nextSequence();
        const blockPayload = { blocked_id: targetId, action, transport_lock: 'private_strong' };
        const v = validateEventPayload('dm_block', blockPayload);
        if (!v.ok) { addError(`Invalid payload: ${v.reason}`); return; }
        const signature = await signEvent('dm_block', nodeIdentity.nodeId, sequence, blockPayload);
        await fetch(`${API}/api/mesh/dm/block`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            agent_id: nodeIdentity.nodeId, blocked_id: targetId, action,
            transport_lock: 'private_strong',
            public_key: nodeIdentity.publicKey, public_key_algo: getPublicKeyAlgo(),
            signature, sequence, protocol_version: PROTOCOL_VERSION,
          }),
        });
      } catch { /* local block/unblock still works */ }
      addSystem(action === 'block' ? `  Blocked ${targetId}. Their messages will be dropped.` : `  Unblocked ${targetId}.`);
      return;
    }

    if (sub === 'notify') {
      const val = args[1]?.toLowerCase();
      if (val === 'on') { setDMNotify(true); addSystem('  DM notifications ON.'); }
      else if (val === 'off') { setDMNotify(false); addSystem('  DM notifications OFF.'); if (onDmCount) onDmCount(0); }
      else { addSystem(`  DM notifications: ${getDMNotify() ? 'ON' : 'OFF'}`); addLines([{ text: '  Usage: dm notify on|off', type: 'dim' }]); }
      return;
    }

    if (sub && sub.startsWith('!sb_')) {
      const msg = args.slice(1).join(' ');
      if (!msg) {
        setDmDest(sub); setDmStep('msg');
        addSystem(''); addSystem(`  DM to ${sub}`); addLines([{ text: '  Type your private message:', type: 'dim' }]); addSystem('');
        return;
      }
      await doDMSend(sub, msg);
      return;
    }

    if (!sub) {
      addSystem(''); addSystem('  ENCRYPTED DM'); addLines([{ text: '  Enter recipient Agent ID (e.g. !sb_a3f2c891):', type: 'dim' }]); addSystem('');
      setDmStep('dest');
      return;
    }

    addError('Usage: dm [agent_id] [msg] | dm add/block/unblock/notify');
  }, [addError, addLines, addOutput, addSystem, doDMSend, nodeIdentity, onDmCount, setDmDest, setDmStep]);

  return { handleDmCommand };
}
