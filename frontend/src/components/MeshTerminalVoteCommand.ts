import { useCallback } from 'react';
import { nextSequence, signEvent, getPublicKeyAlgo } from '@/mesh/meshIdentity';
import { PROTOCOL_VERSION } from '@/mesh/meshProtocol';
import { validateEventPayload } from '@/mesh/meshSchema';
const API='';
export function useMeshTerminalVoteCommand(ctx:any){
  const {addError,addSystem,addOutput,addLines,nodeIdentity,hasSovereignty, activeGateComposeId, expandedGateId, voteDirections, voteScopeKey, setVoteDirections}=ctx;
  const handleVoteCommand = async (args: string[]) => {
            // vote <agent_id> up|down [gate]
            if (!nodeIdentity || !hasSovereignty()) {
              addError("Not connected. Type 'connect' to activate your Agent identity.");
              return;
            }
            const vTarget = args[0];
            const vDir = args[1]?.toLowerCase();
            const voteGate =
              String(args[2] || activeGateComposeId || expandedGateId || '').trim().toLowerCase();
            if (!vTarget || !vDir || !['up', 'down'].includes(vDir)) {
              addError('Usage: vote <node_id> up|down [gate]');
              return;
            }
            try {
              const voteVal = vDir === 'up' ? 1 : -1;
              const existingVote = voteDirections[voteScopeKey(vTarget, voteGate)];
              if (existingVote === voteVal) {
                addSystem(
                  `  Vote already set to ${voteVal > 0 ? 'up' : 'down'} on ${vTarget}${voteGate ? ` in g/${voteGate}` : ''}.`,
                );
                return;
              }
              const sequence = nextSequence();
              const votePayload = { target_id: vTarget, vote: voteVal, gate: voteGate };
              const v = validateEventPayload('vote', votePayload);
              if (!v.ok) {
                addError(`Invalid payload: ${v.reason}`);
                return;
              }
              const signature = await signEvent('vote', nodeIdentity.nodeId, sequence, votePayload);
              const res = await fetch(`${API}/api/mesh/vote`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                  voter_id: nodeIdentity.nodeId,
                  voter_pubkey: nodeIdentity.publicKey,
                  target_id: vTarget,
                  vote: voteVal,
                  gate: voteGate || undefined,
                  public_key_algo: getPublicKeyAlgo(),
                  voter_sig: signature,
                  sequence,
                  protocol_version: PROTOCOL_VERSION,
                }),
              });
              const data = await res.json();
              if (data.ok) {
                setVoteDirections((prev) => ({
                  ...prev,
                  [voteScopeKey(vTarget, voteGate)]: voteVal,
                }));
                addSystem(`  ${data.detail}`);
              } else {
                addError(data.detail);
              }
            } catch {
              addError('Failed to cast vote');
            }
            return;
  };

  return {handleVoteCommand};
}
