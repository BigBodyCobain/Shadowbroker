import { useCallback } from 'react';
import { getDesktopNativeControlAuditReport } from '@/lib/desktopBridge';
import { describeNativeControlError } from '@/lib/desktopControlContract';
import { fetchGateDetailSnapshot } from '@/mesh/gateCatalogSnapshot';
import {
  clearWormholeGatePersona,
  createWormholeGatePersona,
  fetchWormholeGateKeyStatus,
  prepareWormholeInteractiveLane,
  resyncWormholeGateState,
  rotateWormholeGateKey,
} from '@/mesh/wormholeIdentityClient';

export function useMeshTerminalGateCommand(ctx: any) {
  const {
    addError, addLines, addOutput, addSystem,
    gateAccessGranted, requestGateAccess,
    wormholeSecureRequired, wormholeReadyState,
    setWormholeSecureRequired, setWormholeReadyState,
    anonymousModeEnabled, anonymousModeReady,
    addGateResyncAction,
  } = ctx;

  const handleGateCommand = useCallback(async (args: string[], _d?: any) => {
    const needsWormholePrep = ['create', 'mask', 'anon', 'rekey', 'resync'].includes(String(args[0] || ''));
    if (needsWormholePrep && !gateAccessGranted) {
      requestGateAccess(`gate ${args.join(' ')}`.trim());
      return;
    }

    if (args[0] === 'create') {
      addError('Gate creation is disabled. This testnet uses a fixed private launch catalog.');
    } else if (args[0] === 'audit') {
      const requested = Number.parseInt(String(args[1] || '5'), 10);
      const limit = Number.isFinite(requested) && requested > 0 ? Math.min(requested, 10) : 5;
      const report = getDesktopNativeControlAuditReport(limit);
      addSystem('');
      if (!report || report.totalEvents === 0) {
        addSystem('  NATIVE CONTROL AUDIT');
        addOutput('    No native session-profile audit events have been recorded yet.');
        addSystem('');
        return;
      }
      addSystem(
        `  NATIVE CONTROL AUDIT (${report.totalRecorded || report.totalEvents} recorded${report.totalRecorded > report.totalEvents ? `, ${report.totalEvents} shown` : ''})`,
      );
      addOutput(
        `    Outcomes:    allowed ${report.byOutcome.allowed || 0} | profile_warn ${report.byOutcome.profile_warn || 0} | denied ${(report.byOutcome.profile_denied || 0) + (report.byOutcome.capability_denied || 0) + (report.byOutcome.shim_refused || 0)}`,
      );
      if (report.lastProfileMismatch) {
        addOutput(
          `    Last drift:  ${report.lastProfileMismatch.command}${report.lastProfileMismatch.targetRef ? ` [${report.lastProfileMismatch.targetRef}]` : ''} -> ${report.lastProfileMismatch.outcome} (${report.lastProfileMismatch.sessionProfile || 'unscoped'})`,
        );
      }
      report.recent.forEach((entry: any, index: number) => {
        addOutput(
          `    ${String(index + 1).padStart(2, '0')}. ${entry.command}${entry.targetRef ? ` [${entry.targetRef}]` : ''}  ${entry.outcome}  profile=${entry.sessionProfile || 'unscoped'}  cap=${entry.expectedCapability}`,
        );
      });
      addSystem('');
    } else if (args[0] === 'mask') {
      const gateId = args[1];
      if (!gateId) { addError('Usage: gate mask <id>'); return; }
      if (!wormholeSecureRequired || !wormholeReadyState) {
        addSystem('  Preparing Wormhole in the background for gate unlock...');
        try {
          const prepared = await prepareWormholeInteractiveLane({ bootstrapIdentity: true });
          setWormholeSecureRequired(Boolean(prepared.settingsEnabled));
          setWormholeReadyState(Boolean(prepared.ready));
        } catch (err) {
          addError(describeNativeControlError(err) || (err instanceof Error ? err.message : 'Failed to prepare Wormhole.'));
          return;
        }
      }
      if (anonymousModeEnabled && !anonymousModeReady) {
        addError('Hidden transport required for anonymous gate personas.');
        return;
      }
      try {
        const created = await createWormholeGatePersona(gateId, `persona-${Date.now().toString().slice(-4)}`);
        if (!created.ok) { addError((created as any).detail || 'failed to create gate face'); return; }
        addSystem('');
        addSystem(`  GATE FACE READY: ${gateId}`);
        addOutput(`    Face:       ${created.identity?.label || (created.identity as any)?.persona_id || created.identity?.node_id || 'unknown'}`);
        addOutput('    Status:     encrypted gate content unlocked for this face');
        addSystem('');
      } catch (err) {
        addError(describeNativeControlError(err) || (err instanceof Error && err.message) || 'Failed to create gate face');
      }
    } else if (args[0] === 'anon') {
      const gateId = args[1];
      if (!gateId) { addError('Usage: gate anon <id>'); return; }
      try {
        const cleared = await clearWormholeGatePersona(gateId);
        if (!cleared.ok) { addError((cleared as any).detail || 'failed to return to anonymous mode'); return; }
        addSystem('');
        addSystem(`  ANONYMOUS SESSION RESTORED: ${gateId}`);
        addOutput('    Status:     rotating anonymous gate key active for this room');
        addSystem('');
      } catch (err) {
        addError(describeNativeControlError(err) || 'Failed to switch to anonymous mode');
      }
    } else if (args[0] === 'rekey') {
      const gateId = args[1];
      const reason = args.slice(2).join('_') || 'operator_reset';
      if (!gateId) { addError('Usage: gate rekey <id> [reason]'); return; }
      try {
        const rotated = await rotateWormholeGateKey(gateId, reason);
        if (!rotated.ok) { addError((rotated as any).detail || 'failed to rotate gate key'); return; }
        addSystem('');
        addSystem(`  GATE KEY ROTATED: ${(rotated as any).gate_id}`);
        addOutput(`    Epoch:      ${(rotated as any).current_epoch}`);
        addOutput(`    Key:        ${String((rotated as any).key_commitment || '').slice(0, 16)}...`);
        addOutput(`    Reason:     ${(rotated as any).last_rotation_reason || reason}`);
        addSystem('');
      } catch (err) {
        addError(describeNativeControlError(err) || 'Failed to rotate gate key');
      }
    } else if (args[0] === 'resync') {
      const gateId = String(args[1] || '').trim().toLowerCase();
      if (!gateId) { addError('Usage: gate resync <id>'); return; }
      try {
        const resynced = await resyncWormholeGateState(gateId);
        if (!resynced.ok) { addError((resynced as any).detail || 'failed to resync gate state'); return; }
        addSystem('');
        addSystem(`  GATE STATE RESYNCED: ${(resynced as any).gate_id || gateId}`);
        addOutput(`    Epoch:      ${(resynced as any).epoch || 0}`);
        if ((resynced as any).active_identity_scope) addOutput(`    Scope:      ${(resynced as any).active_identity_scope}`);
        if ((resynced as any).active_persona_id) addOutput(`    Persona:    ${(resynced as any).active_persona_id}`);
        if ((resynced as any).active_node_id) addOutput(`    Node:       ${String((resynced as any).active_node_id).slice(0, 16)}...`);
        addSystem('');
      } catch (err) {
        if (!addGateResyncAction(err, gateId)) {
          addError(describeNativeControlError(err) || 'Failed to resync gate state');
        }
      }
    } else if (args[0]) {
      try {
        const gateId = String(args[0] || '').trim().toLowerCase();
        const [gateRes, keyStatus] = await Promise.all([
          fetchGateDetailSnapshot(gateId),
          fetchWormholeGateKeyStatus(gateId).catch(() => null),
        ]);
        const data = gateRes as any;
        if (data.ok === false) { addError(data.detail || 'Failed to load gate details'); return; }
        addSystem('');
        addSystem(`  GATE: ${data.gate_id}`);
        addOutput(`    Name:     ${data.display_name || data.gate_id}`);
        if (data.description) addOutput(`    Brief:    ${data.description}`);
        if (data.welcome) addOutput(`    Welcome:  ${data.welcome}`);
        addOutput(`    Creator:  ${data.creator_node_id}`);
        addOutput(`    Messages: ${data.message_count || 0}`);
        const rules = data.rules || {};
        addOutput(`    Min Rep:  ${rules.min_overall_rep || 'none'}`);
        addOutput(`    Catalog:  ${data.fixed ? 'fixed launch gate' : 'dynamic gate'}`);
        if (keyStatus && (keyStatus as any).ok) {
          const ks = keyStatus as any;
          addOutput(`    Epoch:     ${ks.current_epoch || 0}`);
          addOutput(`    Key:       ${String(ks.key_commitment || '').slice(0, 16) || 'pending'}${ks.key_commitment ? '...' : ''}`);
          addOutput(`    Access:    ${ks.has_local_access ? ks.identity_scope || 'member' : 'locked'}`);
          if (ks.identity_scope === 'anonymous' && !ks.has_local_access) {
            addLines([
              { text: '    Anonymous gate session is active, but this install has not synced local gate access yet.', type: 'dim' },
              { text: `    Retry the room or switch to: gate mask ${gateId}`, type: 'dim' },
            ]);
          }
          if (ks.rekey_recommended) {
            addOutput(`    Rekey:     advised (${String(ks.rekey_recommended_reason || 'review').replace(/_/g, ' ')})`);
          }
        }
        addSystem('');
      } catch {
        addError('Failed to fetch gate details');
      }
    } else {
      addError('Usage: gate <id> | gate mask <id> | gate anon <id> | gate rekey <id> [reason] | gate resync <id> | gate audit [limit]');
    }
  }, [addError, addLines, addOutput, addSystem, gateAccessGranted, requestGateAccess, wormholeSecureRequired, wormholeReadyState, setWormholeSecureRequired, setWormholeReadyState, anonymousModeEnabled, anonymousModeReady, addGateResyncAction]);

  return { handleGateCommand };
}
