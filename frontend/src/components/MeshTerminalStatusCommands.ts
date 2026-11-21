import { useCallback } from 'react';

const API = '';

export interface MeshTerminalStatusCommandsCtx {
  addError: (t: string) => void;
  addLines: (lines: any[]) => void;
  addOutput: (t: string) => void;
  addSystem: (t: string) => void;
  setInfonetNodeStatus: (v: any) => void;
  setInfonetNodeStatusError: (v: string) => void;
  fetchInfonetNodeStatusSnapshot: (force?: boolean) => Promise<any>;
  shortNodeHash: (v: any, n?: number) => string;
  buildNodeRuntimeLines: (data: any) => any[];
}
export function useMeshTerminalStatusCommands(ctx: MeshTerminalStatusCommandsCtx) {
  const { addError, addLines, addOutput, addSystem, setInfonetNodeStatus, setInfonetNodeStatusError, fetchInfonetNodeStatusSnapshot, shortNodeHash, buildNodeRuntimeLines } = ctx;

  const cmdNode = useCallback(async () => {
    try {
      const data = await fetchInfonetNodeStatusSnapshot(true);
      setInfonetNodeStatus(data);
      setInfonetNodeStatusError('');
      addSystem('');
      addSystem('  PARTICIPANT NODE');
      addOutput(`    Network:     ${data.network_id || 'sb-testnet-0'}`);
      addOutput(`    Head:        ${shortNodeHash(data.head_hash, 18)}`);
      addOutput(`    Valid:       ${data.valid ? 'YES' : 'NO'} — ${data.validation || '?'}`);
      addLines(buildNodeRuntimeLines(data));
    } catch {
      setInfonetNodeStatusError('node runtime unavailable');
      addError('Failed to reach participant-node runtime');
    }
  }, [addError, addLines, addOutput, addSystem]);

  const cmdSignals = useCallback(
    async (n: number = 10) => {
      try {
        const limit = Math.min(Math.max(n, 1), 50);
        const res = await fetch(`${API}/api/mesh/signals?limit=${limit}`);
        const data = await res.json();
        const sigs = Array.isArray(data?.signals) ? data.signals.slice(0, limit) : [];
        if (!sigs.length) {
          addSystem('  No signals in buffer');
          return;
        }
        addSystem('');
        addSystem(`  RECENT SIGNALS (${sigs.length})`);
        for (const s of sigs) {
          const src = (s.source || '?').toUpperCase().padEnd(6);
          const call = (s.callsign || '???').padEnd(12);
          const pos = `${s.lat?.toFixed(2)},${s.lng?.toFixed(2)}`;
          const extra = s.status || s.comment || '';
          addOutput(`    ${src} ${call} ${pos.padEnd(14)} ${extra.slice(0, 30)}`);
        }
        addSystem('');
      } catch {
        addError('Failed to fetch signals');
      }
    },
    [addOutput, addError, addSystem],
  );

  const cmdLog = useCallback(
    async (n: number = 5) => {
      try {
        const res = await fetch(`${API}/api/mesh/log`);
        const data = await res.json();
        const entries = (data.log || []).slice(0, n);
        if (!entries.length) {
          addSystem('  Routing log is empty');
          return;
        }
        addSystem('');
        addSystem(`  MESH ROUTING LOG (${entries.length})`);
        for (const e of entries) {
          addOutput(
            `    ${e.sender} -> ${e.destination} via ${e.routed_via || 'FAILED'} [${e.priority}]`,
          );
          if (e.route_reason) addLines([{ text: `      ${e.route_reason}`, type: 'dim' }]);
        }
        addSystem('');
      } catch {
        addError('Failed to fetch routing log');
      }
    },
    [addOutput, addError, addSystem, addLines],
  );

  const cmdNearest = useCallback(
    async (lat: string, lng: string) => {
      if (!lat || !lng) {
        addError('Usage: nearest <lat> <lng>');
        return;
      }
      try {
        const res = await fetch(`${API}/api/sigint/nearest-sdr?lat=${lat}&lng=${lng}`);
        const data = await res.json();
        const sdrs = data.results || [];
        if (!sdrs.length) {
          addSystem('  No KiwiSDR receivers found');
          return;
        }
        addSystem('');
        addSystem('  NEAREST KIWISDR RECEIVERS');
        for (const s of sdrs) {
          addOutput(`    ${s.name}`);
          addLines([{ text: `      ${s.location || '?'} — ${s.distance_deg} deg`, type: 'dim' }]);
          if (s.url) addLines([{ text: `      ${s.url}`, type: 'dim' }]);
        }
        addSystem('');
      } catch {
        addError('Failed to query SDR network');
      }
    },
    [addOutput, addError, addSystem, addLines],
  );

  return { cmdNode, cmdSignals, cmdLog, cmdNearest };
}
