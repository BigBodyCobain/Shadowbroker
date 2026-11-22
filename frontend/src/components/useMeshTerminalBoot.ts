import { useEffect } from 'react';
import { hasSovereignty, getDHPubKey, generateDHKeys, getNodeIdentity } from '@/mesh/meshIdentity';
import { ensureRegisteredDmKey } from '@/mesh/meshDmClient';
import { fetchWormholeStatus } from '@/mesh/wormholeIdentityClient';
import { fetchWormholeSettings } from '@/mesh/wormholeClient';
import { fetchInfonetNodeStatusSnapshot } from '@/mesh/controlPlaneStatusClient';
import { formatNodeMode, describeBootstrapState, describeSyncOutcome, SOVEREIGNTY_DECLARATION, type TermLine } from './MeshTerminal.shared';

const API = '';

export interface MeshTerminalBootCtx {
  isOpen: boolean;
  hasBooted: boolean;
  setHasBooted: (v: boolean) => void;
  setLines: (v: any) => void;
  setInfonetNodeStatus: (v: any) => void;
  setInfonetNodeStatusError: (v: string) => void;
  setSovereigntyPending: (v: boolean) => void;
}

export function useMeshTerminalBoot(ctx: MeshTerminalBootCtx) {
  const { isOpen, hasBooted, setHasBooted, setLines, setInfonetNodeStatus, setInfonetNodeStatusError, setSovereigntyPending } = ctx;

  useEffect(() => {
    if (isOpen && !hasBooted) {
      setHasBooted(true);
      void (async () => {
        const identity = getNodeIdentity();
        const isConnected = identity && hasSovereignty();
        const bootLines: TermLine[] = [];
        let bootPrivateLaneLabel = 'OFF / PUBLIC ONLY';
        let bootPrivateLaneDetail =
          'Wormhole is off. Public mesh works; encrypted gates and obfuscated inbox stay locked.';

        bootLines.push(
          { text: '  Live networks:', type: 'dim' as const },
          { text: '    APRS-IS      Amateur radio operators worldwide', type: 'output' as const },
          { text: '    Meshtastic   LoRa mesh network (off-grid comms)', type: 'output' as const },
          { text: '    JS8Call      HF weak-signal digital mode', type: 'output' as const },
          { text: '    Infonet      ShadowBroker decentralized protocol', type: 'system' as const },
          { text: '', type: 'dim' as const },
        );

        try {
          const [settings, wormholeStatus] = await Promise.all([
            fetchWormholeSettings().catch(() => null),
            fetchWormholeStatus().catch(() => null),
          ]);
          const wormholeOn = Boolean((settings as any)?.enabled);
          const wormholeReady = Boolean((wormholeStatus as any)?.ready);
          const rnsReady = Boolean((wormholeStatus as any)?.rns_ready);
          bootPrivateLaneLabel = !wormholeOn
            ? 'OFF / PUBLIC ONLY'
            : wormholeReady && rnsReady
              ? 'OBFUSCATED / STRONG'
              : 'EXPERIMENTAL / OBFUSCATED';
          bootPrivateLaneDetail = !wormholeOn
            ? 'Wormhole is off. Public mesh works; encrypted gates and obfuscated inbox stay locked.'
            : wormholeReady && rnsReady
              ? 'Wormhole and Reticulum are both ready for the strongest current obfuscated lane.'
              : wormholeReady
                ? 'Wormhole is live for encrypted gates and the obfuscated inbox while stronger transport warms.'
                : 'Wormhole is required for gates and obfuscated inbox, but it is not ready yet.';
        } catch {
          /* ignore */
        }

        bootLines.push(
          { text: `  Public mesh lane: ${isConnected ? `PUBLIC AGENT ${identity!.nodeId}` : 'NO PUBLIC AGENT YET'}`, type: 'system' as const },
          { text: `  Wormhole obfuscated lane: ${bootPrivateLaneLabel}`, type: 'system' as const },
          { text: `  ${bootPrivateLaneDetail}`, type: 'dim' as const },
          { text: '  Public mesh uses your Agent identity. Gates and the obfuscated inbox require Wormhole.', type: 'dim' as const },
          { text: '', type: 'dim' as const },
        );

        let backendOk = false;
        try {
          const res = await fetch(`${API}/api/mesh/status`);
          const data = (await res.json()) as any;
          backendOk = true;
          const aprs = Number(data.signal_counts?.aprs || 0);
          const mesh = Number(data.signal_counts?.meshtastic || 0);
          const js8 = Number(data.signal_counts?.js8call || 0);
          const total = Number(data.signal_counts?.total || aprs + mesh + js8);
          if (total > 0) {
            bootLines.push(
              { text: `  Connected. ${total} active signals:`, type: 'system' as const },
              { text: `    APRS ${aprs} | Meshtastic ${mesh} | JS8Call ${js8}`, type: 'output' as const },
            );
          } else {
            bootLines.push({ text: '  Connected. Bridges warming up...', type: 'system' as const });
          }
        } catch {
          bootLines.push({ text: '  Could not reach backend. Is it running?', type: 'error' as const });
        }

        if (backendOk) {
          try {
            const data = await fetchInfonetNodeStatusSnapshot(true);
            setInfonetNodeStatus(data);
            setInfonetNodeStatusError('');
            bootLines.push(
              { text: `  Infonet: ${(data as any).network_id || 'sb-testnet-0'} | ${(data as any).total_events ?? 0} events | ${(data as any).known_nodes ?? 0} known nodes`, type: 'system' as const },
              { text: `  Node mode: ${formatNodeMode((data as any).node_mode)} | ${Number((data as any).bootstrap?.sync_peer_count || 0)} sync peers | ${Number((data as any).bootstrap?.push_peer_count || 0)} push peers`, type: 'system' as const },
              { text: `  Bootstrap: ${describeBootstrapState(data as any)}`, type: (data as any).bootstrap?.last_bootstrap_error ? 'error' : ('dim' as const) },
              { text: `  Sync loop: ${describeSyncOutcome(data as any)}`, type: 'dim' as const },
            );
          } catch {
            setInfonetNodeStatusError('node runtime unavailable');
            bootLines.push({ text: '  Infonet: offline', type: 'dim' as const });
          }
        }

        bootLines.push({ text: '', type: 'dim' as const });

        if (isConnected) {
          let dhPub = getDHPubKey();
          if (!dhPub) {
            try { dhPub = await generateDHKeys(); } catch (err) {
              console.error('[mesh] DM key bootstrap failed during terminal init', err);
              bootLines.push(
                { text: '  DM obfuscated inbox degraded: unable to generate local DH keys.', type: 'error' as const },
                { text: '  Encrypted DM features may be unavailable until browser storage access is restored.', type: 'dim' as const },
                { text: '', type: 'dim' as const },
              );
            }
          }
          if (backendOk && dhPub) {
            try { await ensureRegisteredDmKey(API, identity!, { force: true }); } catch { /* non-critical */ }
          }
          bootLines.push(
            { text: `  Public Agent: ${identity!.nodeId}`, type: 'header' as const },
            { text: '  Status: ACTIVE for public mesh and perimeter comms', type: 'system' as const },
            { text: '', type: 'dim' as const },
            { text: '  Commands:', type: 'system' as const },
            { text: '    signals    Live radio intercepts', type: 'output' as const },
            { text: '    apps       Terminal intel surfaces', type: 'output' as const },
            { text: '    send       Transmit a signed message', type: 'output' as const },
            { text: '    dm         Encrypted private messages', type: 'output' as const },
            { text: '    dossier    Multi-source brief by name/place/org', type: 'output' as const },
            { text: '    markets    Prediction markets (Polymarket/Kalshi)', type: 'output' as const },
            { text: '    gates      Community channels', type: 'output' as const },
            { text: '    help       All commands', type: 'output' as const },
            { text: '', type: 'dim' as const },
          );
        } else {
          bootLines.push(...SOVEREIGNTY_DECLARATION);
          setSovereigntyPending(true);
        }

        setLines((prev: TermLine[]) => [...prev, ...bootLines]);
      })();
    }
  }, [isOpen, hasBooted, setHasBooted, setInfonetNodeStatus, setInfonetNodeStatusError, setLines, setSovereigntyPending]);
}
