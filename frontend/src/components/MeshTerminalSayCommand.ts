import { useCallback } from 'react';
import { prepareWormholeInteractiveLane } from '@/mesh/wormholeIdentityClient';
import { describeNativeControlError } from '@/lib/desktopControlContract';
const API='';
export function useMeshTerminalSayCommand(ctx:any){
  const {addError,addSystem,addOutput,addLines,nodeIdentity,hasSovereignty,postGateMessage,invalidateGateCatalogSnapshot,invalidateGateDetailSnapshot,invalidateGateThreadPreviewSnapshot,addGateResyncAction, gateAccessGranted, requestGateAccess, wormholeSecureRequired, wormholeReadyState, setWormholeSecureRequired, setWormholeReadyState}=ctx;
  const handleSayCommand = async (args: string[]) => {
          if (!gateAccessGranted) {
            requestGateAccess(`say ${args.join(' ')}`.trim());
            return;
          }
          // say <gate_id> <message>
          if (!wormholeSecureRequired || !wormholeReadyState) {
            addSystem('  Preparing Wormhole in the background for gate posting...');
            try {
              const prepared = await prepareWormholeInteractiveLane({ bootstrapIdentity: true });
              setWormholeSecureRequired(Boolean(prepared.settingsEnabled));
              setWormholeReadyState(Boolean(prepared.ready));
            } catch (err) {
              addError(
                describeNativeControlError(err) ||
                  (err instanceof Error ? err.message : 'Failed to prepare Wormhole.'),
              );
              return;
            }
          }
            const gateId = args[0];
            const gateMsg = args.slice(1).join(' ');
            if (!gateId || !gateMsg) {
              addError('Usage: say <gate_id> <message>');
              return;
          }
            try {
              const data = await postGateMessage(gateId, gateMsg);
              invalidateGateCatalogSnapshot();
              invalidateGateDetailSnapshot(gateId);
              invalidateGateThreadPreviewSnapshot(gateId);
              addSystem(`  ${data.detail || `Posted to g/${gateId}`}`);
            } catch (err) {
              const detail = err instanceof Error && err.message ? err.message : '';
              if (!addGateResyncAction(err, gateId)) {
                addError(describeNativeControlError(err) || detail || 'Failed to post to gate');
              }
            }
          return;
  };

  return {handleSayCommand};
}
