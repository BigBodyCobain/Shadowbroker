// @ts-nocheck
import { useEffect } from 'react';
import { hasSovereignty, getDHPubKey, generateDHKeys, getNodeIdentity } from '@/mesh/meshIdentity';
import { ensureRegisteredDmKey } from '@/mesh/meshDmClient';
import { fetchWormholeSettings, fetchWormholeStatus } from '@/mesh/wormholeIdentityClient';
import { fetchInfonetNodeStatusSnapshot } from '@/mesh/controlPlaneStatusClient';
import { formatNodeMode, describeBootstrapState, describeSyncOutcome } from './MeshTerminal.shared';
import { SOVEREIGNTY_DECLARATION } from './MeshTerminal.shared';

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

  // Auto-run status on first open
  useEffect(() => {
    if (isOpen && !hasBooted) {
      setHasBooted(true);
      (async () => {
        const identity = getNodeIdentity();
        const isConnected = identity && hasSovereignty();
        const bootLines: TermLine[] = [];
        let bootPrivateLaneLabel = 'OFF / PUBLIC ONLY';
        let bootPrivateLaneDetail =
          'Wormhole is off. Public mesh works; encrypted gates and obfuscated inbox stay locked.';

        // 1. Always show network status first
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
            fetchWormholeSettings(),
            fetchWormholeStatus().catch(() => null),
          ]);
          const wormholeOn = Boolean(settings?.enabled);
          const wormholeReady = Boolean(wormholeStatus?.ready);
          const rnsReady = Boolean(wormholeStatus?.rns_ready);
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
          {
            text: `  Public mesh lane: ${isConnected ? `PUBLIC AGENT ${identity.nodeId}` : 'NO PUBLIC AGENT YET'}`,
            type: 'system' as const,
          },
          { text: `  Wormhole obfuscated lane: ${bootPrivateLaneLabel}`, type: 'system' as const },
          { text: `  ${bootPrivateLaneDetail}`, type: 'dim' as const },
          {
            text: '  Public mesh uses your Agent identity. Gates and the obfuscated inbox require Wormhole.',
            type: 'dim' as const,
          },
          { text: '', type: 'dim' as const },
        );

        // 2. Fetch live status
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
              {
                text: `    APRS ${aprs} | Meshtastic ${mesh} | JS8Call ${js8}`,
                type: 'output' as const,
              },
            );
          } else {
            bootLines.push({ text: '  Connected. Bridges warming up...', type: 'system' as const });
          }
        } catch {
          bootLines.push({
            text: '  Could not reach backend. Is it running?',
            type: 'error' as const,
          });
        }

        // 3. Fetch Infonet status
        if (backendOk) {
          try {
            const data = await fetchInfonetNodeStatusSnapshot(true);
            setInfonetNodeStatus(data);
            setInfonetNodeStatusError('');
            bootLines.push({
              text: `  Infonet: ${data.network_id || 'sb-testnet-0'} | ${data.total_events ?? 0} events | ${data.known_nodes ?? 0} known nodes`,
              type: 'system' as const,
            });
            bootLines.push({
              text: `  Node mode: ${formatNodeMode(data.node_mode)} | ${Number(data.bootstrap?.sync_peer_count || 0)} sync peers | ${Number(data.bootstrap?.push_peer_count || 0)} push peers`,
              type: 'system' as const,
            });
            bootLines.push({
              text: `  Bootstrap: ${describeBootstrapState(data)}`,
              type: data.bootstrap?.last_bootstrap_error ? 'error' : ('dim' as const),
            });
            bootLines.push({
              text: `  Sync loop: ${describeSyncOutcome(data)}`,
              type: 'dim' as const,
            });
          } catch {
            setInfonetNodeStatusError('node runtime unavailable');
            bootLines.push({ text: '  Infonet: offline', type: 'dim' as const });
          }
        }

        bootLines.push({ text: '', type: 'dim' as const });

        // 4. Agent identity — connected vs not
        if (isConnected) {
          // Ensure DH keys exist (backfill for pre-DM users)
          let dhPub = getDHPubKey();
          if (!dhPub) {
            try {
              dhPub = await generateDHKeys();
            } catch (err) {
              console.error('[mesh] DM key bootstrap failed during terminal init', err);
              bootLines.push(
                {
                  text: '  DM obfuscated inbox degraded: unable to generate local DH keys.',
                  type: 'error' as const,
                },
                {
                  text: '  Encrypted DM features may be unavailable until browser storage access is restored.',
                  type: 'dim' as const,
                },
                { text: '', type: 'dim' as const },
              );
            }
          }
          // Register DH key with backend
          if (backendOk && dhPub) {
            try {
              await ensureRegisteredDmKey(API, identity, { force: true });
            } catch {
              /* non-critical */
            }
          }
          bootLines.push(
            { text: `  Public Agent: ${identity.nodeId}`, type: 'header' as const },
            { text: '  Status: ACTIVE for public mesh and perimeter comms', type: 'system' as const },
            { text: '', type: 'dim' as const },
            { text: '  Commands:', type: 'system' as const },
            { text: '    signals    Live radio intercepts', type: 'output' as const },
            { text: '    apps       Terminal intel surfaces', type: 'output' as const },
            { text: '    send       Transmit a signed message', type: 'output' as const },
            { text: '    dm         Encrypted private messages', type: 'output' as const },
            { text: '    dossier    Multi-source brief by name/place/org', type: 'output' as const },
            {
              text: '    markets    Prediction markets (Polymarket/Kalshi)',
              type: 'output' as const,
            },
            { text: '    gates      Community channels', type: 'output' as const },
            { text: '    help       All commands', type: 'output' as const },
            { text: '', type: 'dim' as const },
          );
        } else {
          // Show sovereignty declaration inline
          bootLines.push(...SOVEREIGNTY_DECLARATION);
          setSovereigntyPending(true);
        }

        setLines((prev) => [...prev, ...bootLines]);
      })();
    }
  }, [isOpen, hasBooted]);

  // Load existing identity on mount
  useEffect(() => {
    const existing = getNodeIdentity();
    if (existing) setNodeIdentity(existing);
    void hydrateWormholeContacts()
      .then(() => {
        setContactsRevision((value) => value + 1);
      })
      .catch((err) => {
        console.warn('[mesh] contact hydration failed in MeshTerminal', err);
      });
  }, []);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const refreshIdentity = () => {
      const next = getNodeIdentity();
      setNodeIdentity((prev) => {
        const prevId = prev?.nodeId || '';
        const nextId = next?.nodeId || '';
        const prevKey = prev?.publicKey || '';
        const nextKey = next?.publicKey || '';
        return prevId === nextId && prevKey === nextKey ? prev : next;
      });
      void hydrateWormholeContacts(true)
        .then(() => {
          setContactsRevision((value) => value + 1);
        })
        .catch((err) => {
          console.warn('[mesh] contact refresh failed in MeshTerminal', err);
        });
    };
    window.addEventListener('sb:identity-state-changed', refreshIdentity);
    window.addEventListener('storage', refreshIdentity);
    window.addEventListener('focus', refreshIdentity);
    return () => {
      window.removeEventListener('sb:identity-state-changed', refreshIdentity);
      window.removeEventListener('storage', refreshIdentity);
      window.removeEventListener('focus', refreshIdentity);
    };
  }, []);

  // DM unread count polling (jittered cadence around 15s when connected)
  useEffect(() => {
    if (!isOpen || !nodeIdentity || !hasSovereignty() || !getDMNotify() || surfacePanel === 'inbox') return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const tick = async () => {
      if (cancelled) return;
      try {
        const claims = await buildMailboxClaims(getContacts());
        const data = await countDmMailboxes(API, nodeIdentity, claims);
        if (!cancelled && onDmCount) onDmCount(data.count || 0);
      } catch {
        /* ignore */
      }
      if (!cancelled) {
        timer = setTimeout(() => void tick(), jitteredPollDelay(15_000));
      }
    };
    void tick(); // immediate first poll
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [isOpen, nodeIdentity, onDmCount, surfacePanel]);

  // Escape to close
  useEffect(() => {
    if (!isOpen) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [isOpen, onClose]);
}
