import { useCallback } from 'react';
const API = '';
export function useMeshTerminalInboxCommand(ctx: any) {
  const { addError, addLines, addOutput, addSystem } = ctx;
  const handleInboxCommand = async (cmd: string, args: string[], d: any) => {
    switch (cmd) {
            case 'inbox': {
              if (!nodeIdentity || !hasSovereignty()) {
                addError("Not connected. Type 'connect' to activate your Agent identity.");
                return;
              }
              addSystem('  Checking dead drop...');
              try {
                const claims = await buildMailboxClaims(getContacts());
                const data = await pollDmMailboxes(API, nodeIdentity, claims);
                const msgs = data.messages || [];
                if (msgs.length === 0) {
                  addSystem('  No pending messages.');
                  addSystem('');
                  return;
                }
                addSystem(`  ${msgs.length} message${msgs.length > 1 ? 's' : ''} retrieved:`);
                addSystem('');
                for (const m of msgs) {
                  const age = Math.floor((Date.now() / 1000 - m.timestamp) / 60);
                  const ageStr = age < 60 ? `${age}m ago` : `${Math.floor(age / 60)}h ago`;
                  try {
                    // Get sender's DH key
                    const contacts = getContacts();
                    let senderDH = contacts[m.sender_id]?.dhPubKey;
                    if (!senderDH) {
                      const contact = contacts[m.sender_id];
                      const keyData = await fetchDmPublicKey(
                        API,
                        m.sender_id,
                        contact?.invitePinnedPrekeyLookupHandle,
                      );
                      if (keyData?.dh_pub_key) {
                        senderDH = keyData.dh_pub_key as string;
                        addContact(m.sender_id, senderDH!, undefined, keyData.dh_algo);
                        updateContact(m.sender_id, {
                          dhAlgo: keyData.dh_algo || contact?.dhAlgo,
                          remotePrekeyLookupMode:
                            String(keyData.lookup_mode || '').trim().toLowerCase() ||
                            contact?.remotePrekeyLookupMode,
                        });
                      }
                    }
                    if (!senderDH) {
                      addOutput(`  [${m.sender_id}] ${ageStr} — (cannot decrypt: no key)`);
                      continue;
                    }
                    let plaintext = '';
                    try {
                      plaintext = await ratchetDecryptDM(m.sender_id, m.ciphertext);
                    } catch {
                      const sharedKey = await deriveSharedKey(senderDH);
                      plaintext = await decryptDM(m.ciphertext, sharedKey);
                    }
                    addOutput(`  [${m.sender_id}] ${ageStr}`);
                    addLines([{ text: `    ${plaintext}`, type: 'output' }]);
                  } catch {
                    addOutput(`  [${m.sender_id}] ${ageStr} — (decryption failed)`);
                  }
                  addSystem('');
                }
                // Clear badge
                if (onDmCount) onDmCount(0);
              } catch {
                addError('Failed to check inbox');
              }
              return;
            }
      default: return;
    }
  };

  const { doSend, doMeshSend, startInteractiveSend, doDMSend } = useMeshTerminalSendFlow({
    addError, addLines, addSystem, nodeIdentity, setSendStep,
  } as any);

  const handleSendCommand = async (args: string[]) => {
            if (!nodeIdentity || !hasSovereignty()) {
              if (isDeclined()) {
                addError("Read-only mode. Type 'connect' to activate your Agent identity.");
              } else {
                addLines([...SOVEREIGNTY_DECLARATION]);
                setSovereigntyPending(true);
              }
              setBusy(false);
              return;
            }
            if (args.length >= 2) {
              await doSend(args[0], args.slice(1).join(' '));
            } else {
              startInteractiveSend();
            }
  };

  const handleWhoamiCommand = async () => {
            addSystem('');
            addSystem('  IDENTITY LANES');
            if (nodeIdentity && hasSovereignty()) {
              addOutput(`    Public Agent: ${nodeIdentity.nodeId}`);
              addOutput(`    Public Key: ${nodeIdentity.publicKey.slice(0, 24)}...`);
              addSystem('    Status: ACTIVE — public mesh and perimeter sends sign with this key');
            } else if (isDeclined()) {
              addSystem('    Public Agent: READ-ONLY (declined)');
              addLines([{ text: "    Type 'connect' to create a public Agent.", type: 'dim' }]);
            } else {
              addLines([
                {
                  text: "    Public Agent: not connected — type 'connect' to create one.",
                  type: 'dim',
                },
              ]);
            }
            addOutput(`    Wormhole Lane: ${privateLaneLabel}`);
            addLines([{ text: `    ${privateLaneDetail}`, type: 'dim' }]);
            addSystem('');
  };

  const handleConnectCommand = async () => {
            if (nodeIdentity && hasSovereignty()) {
              addSystem(`  Public Agent already active as ${nodeIdentity.nodeId}. Type 'whoami' for lane status.`);
            } else {
              addLines([...SOVEREIGNTY_DECLARATION]);
              setSovereigntyPending(true);
            }
  };
  const handleRepCommand = async (args: string[]) => {
            const targetId = args[0];
            if (!targetId) { addError('Usage: rep <node_id>  (e.g. rep !sb_a3f2c891)'); return; }
            try {
              const res = await fetch(`${API}/api/mesh/reputation?node_id=${encodeURIComponent(targetId)}`);
              const data = await res.json();
              if (data.ok === false) { addError(data.detail); return; }
              addSystem('');
              addSystem(`  REPUTATION: ${data.node_id}`);
              addOutput(`    Overall: ${data.overall}`);
              addOutput('    Sources:');
              for (const [src, val] of Object.entries(data.breakdown || {})) {
                addOutput(`      ${String(src).padEnd(20)} ${Number(val).toFixed(1)}`);
              }
              addSystem('');
            } catch { addError('Failed to fetch reputation'); }
  };
  const handleMyrepCommand = async () => {
            if (!nodeIdentity) { addError('No identity. Run /whoami or connect first.'); return; }
            try {
              const res = await fetch(`${API}/api/mesh/reputation?node_id=${encodeURIComponent(nodeIdentity.nodeId)}`);
              const data = await res.json();
              if (data.ok === false) { addError(data.detail); return; }
              addSystem('');
              addSystem(`  YOUR REPUTATION: ${data.node_id}`);
              addOutput(`    Overall: ${data.overall}`);
              for (const [src, val] of Object.entries(data.breakdown || {})) {
                addOutput(`      ${String(src).padEnd(20)} ${Number(val).toFixed(1)}`);
              }
              addSystem('');
            } catch { addError('Failed to fetch reputation'); }
  };
  const handleThresholdCommand = (args: string[]) => {
            const n = parseInt(args[0]);
            if (isNaN(n) || n < 0) {
              const current = typeof window !== 'undefined' ? localStorage.getItem('sb_mesh_rep_threshold') || '0' : '0';
              addSystem(`  Current DM threshold: ${current} (min rep to receive messages)`);
              addLines([{ text: '  Usage: threshold <n>  (e.g. threshold 5)', type: 'dim' }]);
              return;
            }
            localStorage.setItem('sb_mesh_rep_threshold', String(n));
            addSystem(`  DM threshold set to ${n}. Only nodes with rep >= ${n} can message you.`);
  };

  return { handleInboxCommand };
}
