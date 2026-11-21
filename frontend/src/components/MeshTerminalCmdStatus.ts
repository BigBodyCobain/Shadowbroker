import { useCallback } from 'react';
import { fetchWormholeStatus } from '@/mesh/wormholeIdentityClient';
import { hasSovereignty } from '@/mesh/identity';
import {
  formatLegacyCompatibilitySeenAt,
  summarizeLegacyCompatibility,
  formatGateCompatSeenAt,
  getGateCompatTelemetrySnapshot,
  summarizeGateCompatTelemetry,
  describeBrowserGateLocalRuntimeStatus,
  getBrowserGateLocalRuntimeStatus,
} from '@/mesh/infonetNodeMeshClient';

const API = '';

export function useMeshTerminalCmdStatus(ctx: any) {
  const {
    addOutput, addError, addSystem, addLines,
    nodeIdentity, privateLaneDetail, privateLaneLabel,
    fetchInfonetNodeStatusSnapshot, setInfonetNodeStatus, setInfonetNodeStatusError, buildNodeRuntimeLines,
  } = ctx;

  const cmdStatus = useCallback(async () => {
    try {
      const [meshRes, wormholeStatus] = await Promise.all([
        fetch(`${API}/api/mesh/status`),
        fetchWormholeStatus().catch(() => null),
      ]);
      const data = (await meshRes.json()) as any;
      const aprs = Number(data.signal_counts?.aprs || 0);
      const mesh = Number(data.signal_counts?.meshtastic || 0);
      const js8 = Number(data.signal_counts?.js8call || 0);
      addSystem('');
      addSystem('  NETWORK STATUS');
      addOutput(`    APRS-IS      ${String(aprs).padStart(4)} signals`);
      addOutput(`    Meshtastic   ${String(mesh).padStart(4)} signals`);
      addOutput(`    JS8Call      ${String(js8).padStart(4)} signals`);
      addSystem(
        `    Total        ${String(Number(data.signal_counts?.total || aprs + mesh + js8)).padStart(4)} active`,
      );
      addSystem('');

      // Infonet status
      try {
        const iData = await fetchInfonetNodeStatusSnapshot(true);
        setInfonetNodeStatus(iData);
        setInfonetNodeStatusError('');
        addSystem('  INFONET');
        addOutput(`    Network:     ${iData.network_id || 'sb-testnet-0'}`);
        addOutput(
          `    Events:      ${iData.total_events ?? 0} total | ${iData.known_nodes ?? 0} agents`,
        );
        addOutput(`    Head:        ${iData.head_hash || 'genesis'}`);
        addOutput(`    Valid:       ${iData.valid ? 'YES' : 'NO'}`);
        addLines(buildNodeRuntimeLines(iData));
      } catch {
        setInfonetNodeStatusError('node runtime unavailable');
        addOutput('    Infonet:     offline');
      }
      addSystem('');

      addSystem('  IDENTITY LANES');
      if (nodeIdentity && hasSovereignty()) {
        addOutput(`    Public Agent:   ${nodeIdentity.nodeId}`);
        addOutput('    Public Mesh:    READY');
      } else {
        addLines([
          {
            text: "    Public Agent:   not connected — type 'connect' to create one",
            type: 'dim',
          },
        ]);
      }
      addOutput(`    Wormhole Lane:  ${privateLaneLabel}`);
      addLines([{ text: `    ${privateLaneDetail}`, type: 'dim' }]);
      const legacyCompatibilityItems = summarizeLegacyCompatibility(
        wormholeStatus?.legacy_compatibility,
      );
      if (legacyCompatibilityItems.length) {
        addSystem('');
        addSystem('  LEGACY SUNSET');
        for (const item of legacyCompatibilityItems) {
          addOutput(
            `    ${item.label.padEnd(21)} ${item.blocked ? 'BLOCKED ' : 'ALLOWING'} seen ${item.count}${
              item.blockedCount > 0 ? ` / blocked ${item.blockedCount}` : ''
            }`,
          );
          addLines([
            {
              text: `      target ${item.targetVersion} / ${item.targetDate} â€” ${
                item.lastSeenAt > 0
                  ? `last seen ${formatLegacyCompatibilitySeenAt(item.lastSeenAt)}`
                  : 'never observed'
              }`,
              type: 'dim',
            },
          ]);
          if (item.recentTargets.length) {
            addLines([
              {
                text: `      recent ${item.recentTargets.join(' â€¢ ')}`,
                type: 'dim',
              },
            ]);
          }
        }
      }
      const gateCompatTelemetry = getGateCompatTelemetrySnapshot();
      const gateCompatTopReasons = summarizeGateCompatTelemetry(gateCompatTelemetry, 3);
      const gateLocalRuntimeStatus = getBrowserGateLocalRuntimeStatus();
      addSystem('');
      addSystem('  GATE COMPAT');
      addOutput(`    Local Runtime: ${describeBrowserGateLocalRuntimeStatus(gateLocalRuntimeStatus)}`);
      addOutput(
        `    Required:    ${gateCompatTelemetry.totalRequired}   Used: ${gateCompatTelemetry.totalUsed}`,
      );
      if (gateCompatTopReasons.length) {
        for (const item of gateCompatTopReasons) {
          addOutput(
            `    ${item.label.slice(0, 21).padEnd(21)} need ${item.requiredCount}${
              item.usedCount > 0 ? ` / used ${item.usedCount}` : ''
            }`,
          );
          addLines([
            {
              text: `      ${
                item.lastAt > 0
                  ? `last seen ${formatGateCompatSeenAt(item.lastAt)}`
                  : 'never observed'
              }${item.recentGates.length ? ` • rooms ${item.recentGates.join(' • ')}` : ''}`,
              type: 'dim',
            },
          ]);
        }
      } else {
        addLines([
          {
            text: '      no browser gate compat issues recorded for this profile',
            type: 'dim',
          },
        ]);
      }
      addSystem('');
    } catch {
      addError('Failed to reach backend');
    }
  }, [addOutput, addError, addSystem, addLines, nodeIdentity, privateLaneDetail, privateLaneLabel]);

  return { cmdStatus };
}
