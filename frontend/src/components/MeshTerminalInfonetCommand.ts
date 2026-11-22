// @ts-nocheck
import { useCallback } from 'react';
const API = '';
export function useMeshTerminalInfonetCommand(ctx: any) {
  const { addError, addLines, addOutput, addSystem, nodeIdentity } = ctx;
  const handleInfonetCommand = async (cmd: string, args: string[], d: any) => {
    switch (cmd) {
            case 'infonet': {
              // infonet — Infonet protocol status
              try {
                const data = await fetchInfonetNodeStatusSnapshot(true);
                setInfonetNodeStatus(data);
                setInfonetNodeStatusError('');
                addSystem('');
                addSystem('  INFONET STATUS');
                addOutput(`    Network:     ${data.network_id || 'sb-testnet-0'}`);
                addOutput(
                  `    Events:      ${data.total_events ?? 0} total (${data.active_events ?? 0} active)`,
                );
                addOutput(`    Head Hash:   ${data.head_hash || 'genesis'}`);
                addOutput(`    Known Nodes: ${data.known_nodes ?? 0}`);
                addOutput(`    Chain Size:  ${data.chain_size_kb ?? 0} KB`);
                addOutput(`    Unsigned:    ${data.unsigned_events ?? 0}`);
                addOutput(
                  `    Valid:       ${data.valid ? 'YES' : 'NO'} — ${data.validation || '?'}`,
                );
                addLines(buildNodeRuntimeLines(data));
                const types = data.event_types || {};
                if (Object.keys(types).length > 0) {
                  addSystem('    Event Breakdown:');
                  for (const [t, count] of Object.entries(types)) {
                    addOutput(`      ${String(t).padEnd(16)} ${count}`);
                  }
                }
                addSystem('');
              } catch {
                setInfonetNodeStatusError('node runtime unavailable');
                addError('Failed to reach Infonet');
              }
              return;
            }
            case 'node':
              await cmdNode();
              return;
            case 'merkle':
              await cmdMerkle();
              return;
            case 'sync':
              await cmdSync(parseInt(args[0]) || 100);
              return;
            case 'peers': {
              const sub = args[0]?.toLowerCase();
              const current = getInfonetPeers();
              if (!sub) {
                addSystem('');
                addSystem(`  INFONET PEERS (${current.length})`);
                for (const peer of current) {
                  addOutput(`    ${peer}`);
                }
                addLines([
                  {
                    text: "    note: this is the manual browser sync list; backend participant-node peers come from the local peer store and show up in 'node'",
                    type: 'dim',
                  },
                ]);
                addSystem('');
                return;
              }
              if (sub === 'add') {
                const url = args[1];
                if (!url) {
                  addError('Usage: peers add <url>');
                  return;
                }
                const next = Array.from(new Set([...current, url]));
                setInfonetPeers(next.filter((p) => p !== API));
                addSystem(`  Added peer: ${url}`);
                return;
              }
              if (sub === 'remove') {
                const url = args[1];
                if (!url) {
                  addError('Usage: peers remove <url>');
                  return;
                }
                const next = current.filter((p) => p !== url);
                setInfonetPeers(next.filter((p) => p !== API));
                addSystem(`  Removed peer: ${url}`);
                return;
              }
              if (sub === 'clear') {
                setInfonetPeers([]);
                addSystem('  Cleared stored peers.');
                return;
              }
              addError('Usage: peers [add|remove|clear] <url>');
              return;
            }
            case 'messages': {
              // messages [gate] — browse Infonet messages
              const msgGate = args[0] || '';
              try {
                const msgs = msgGate
                  ? await fetchGateMessageSnapshot(msgGate, 20)
                  : ((await fetch(`${API}/api/mesh/infonet/messages?limit=20`).then((res) =>
                      res.json(),
                    )).messages || []).map((message: InfonetMessageRecord) =>
                      normalizeInfonetMessageRecord(message),
                    );
                addSystem('');
                if (!msgs.length) {
                  addSystem(
                    msgGate ? `  No messages in gate '${msgGate}'` : '  No messages on Infonet yet',
                  );
                } else {
                  addSystem(
                    msgGate
                      ? `  MESSAGES IN g/${msgGate} (${msgs.length})`
                      : `  RECENT MESSAGES (${msgs.length})`,
                  );
                  for (const m of msgs) {
                    if (m.system_seed) {
                      addSystem(`    ${m.fixed_gate ? 'FIXED GATE NOTICE' : 'GATE NOTICE'} [${m.gate || msgGate || 'infonet'}]`);
                      addLines([{ text: `      ${await describeGateMessagePreview(m)}`, type: 'dim' }]);
                      continue;
                    }
                    const age = Math.floor((Date.now() / 1000 - m.timestamp) / 60);
                    const ageStr = age < 60 ? `${age}m` : `${Math.floor(age / 60)}h`;
                    const gateStr = m.gate ? ` [${m.gate}]` : '';
                    const ephStr = m.ephemeral ? ' (ephemeral)' : '';
                    const encState = gateEnvelopeState(m);
                    const encLabel =
                      encState === 'decrypted'
                        ? ' [enc:open]'
                        : encState === 'locked'
                          ? ' [enc:locked]'
                          : '';
                    addOutput(`    ${m.node_id || ''} ${ageStr} ago${gateStr}${ephStr}${encLabel}`);
                    addLines([{ text: `      ${await describeGateMessagePreview(m)}`, type: 'dim' }]);
                    if (isEncryptedGateEnvelope(m)) {
                      const metaBits = [];
                      if (Number(m.epoch ?? 0) > 0) {
                        metaBits.push(`epoch=${Number(m.epoch ?? 0)}`);
                      }
                      if (m.sender_ref) {
                        metaBits.push(`sender_ref=${String(m.sender_ref)}`);
                      }
                      if (metaBits.length) {
                        addLines([{ text: `      ${metaBits.join(' ')}`, type: 'dim' }]);
                      }
                    }
                    addLines([{ text: `      id: ${m.event_id.slice(0, 16)}...`, type: 'dim' }]);
                  }
                }
                addSystem('');
              } catch {
                addError('Failed to fetch messages');
              }
              return;
            }
            case 'event': {
              // event <event_id> — look up an Infonet event
              const evtId = args[0];
              if (!evtId) {
                addError('Usage: event <event_id>');
                return;
              }
              try {
                const res = await fetch(`${API}/api/mesh/infonet/event/${encodeURIComponent(evtId)}`);
                const data = await res.json();
                if (data.ok === false) {
                  addError(data.detail);
                  return;
                }
                addSystem('');
                addSystem(`  INFONET EVENT`);
                addOutput(`    ID:        ${data.event_id}`);
                addOutput(`    Type:      ${data.event_type}`);
                addOutput(`    Node:      ${data.node_id}`);
                addOutput(`    Seq:       ${data.sequence}`);
                addOutput(`    Prev Hash: ${(data.prev_hash || '').slice(0, 16)}...`);
                addOutput(`    Network:   ${data.network_id || '?'}`);
                const ts = new Date(data.timestamp * 1000).toLocaleString();
                addOutput(`    Time:      ${ts}`);
                if (data.signature) {
                  addOutput(`    Signature: ${data.signature.slice(0, 32)}...`);
                }
                addSystem('    Payload:');
                const payload = data.payload || {};
                for (const [k, v] of Object.entries(payload)) {
                  if (k.startsWith('_')) continue;
                  addLines([{ text: `      ${k}: ${String(v).slice(0, 60)}`, type: 'dim' }]);
                }
                addSystem('');
              } catch {
                addError('Failed to fetch event');
              }
              return;
            }
            case 'ledger': {
              // ledger [node_id] — view a node's Infonet activity
              const ledgerTarget = args[0] || (nodeIdentity?.nodeId ?? '');
              if (!ledgerTarget) {
                addError("Usage: ledger <node_id>  (or just 'ledger' for your own)");
                return;
              }
              try {
                const res = await fetch(
                  `${API}/api/mesh/infonet/node/${encodeURIComponent(ledgerTarget)}?limit=20`,
                );
                const data = await res.json();
                const events = data.events || [];
                addSystem('');
                if (!events.length) {
                  addSystem(`  No Infonet activity for ${ledgerTarget}`);
                } else {
                  addSystem(`  INFONET ACTIVITY: ${ledgerTarget} (${events.length} events)`);
                  for (const e of events) {
                    const age = Math.floor((Date.now() / 1000 - e.timestamp) / 60);
                    const ageStr =
                      age < 60
                        ? `${age}m`
                        : age < 1440
                          ? `${Math.floor(age / 60)}h`
                          : `${Math.floor(age / 1440)}d`;
                    const payload = e.payload || {};
                    let detail = '';
                    if (e.event_type === 'message' || e.event_type === 'gate_message') {
                      detail = (payload.message || '').slice(0, 40);
                    } else if (e.event_type === 'vote') {
                      detail = `${payload.vote > 0 ? '+1' : '-1'} on ${payload.target_id}`;
                    } else if (e.event_type === 'gate_create') {
                      detail = `created g/${payload.gate_id}`;
                    } else if (e.event_type === 'prediction') {
                      detail = `${payload.side} on ${(payload.market_title || '').slice(0, 30)}`;
                    } else if (e.event_type === 'stake') {
                      detail = `${payload.side} ${payload.amount} on ${payload.message_id}`;
                    } else if (e.event_type === 'key_rotate') {
                      detail = `rotated from ${String(payload.old_node_id || '').slice(0, 12)}`;
                    } else if (e.event_type === 'key_revoke') {
                      const until = payload.grace_until
                        ? new Date(Number(payload.grace_until) * 1000).toLocaleString()
                        : 'unknown';
                      detail = `revoked key (grace until ${until})`;
                    }
                    addOutput(`    [${e.event_type.padEnd(14)}] ${ageStr} ago  ${detail}`);
                  }
                }
                addSystem('');
              } catch {
                addError('Failed to fetch node activity');
              }
              return;
            }
            case 'rotate':
              await cmdRotate();
              return;
            case 'revoke':
              await cmdRevoke(args);
              return;
            // ─── Encrypted DM Commands ───────────────────────────
      default: return;
    }
  };

  return { handleInfonetCommand };
}
