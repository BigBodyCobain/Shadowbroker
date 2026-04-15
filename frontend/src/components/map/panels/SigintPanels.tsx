import { useCallback, useEffect, useRef, useState } from 'react';
import { Send } from 'lucide-react';
import { API_BASE } from '@/lib/api';
import {
  derivePublicMeshAddress,
  getNodeIdentity,
  hasSovereignty,
  signEvent,
  nextSequence,
  getPublicKeyAlgo,
} from '@/mesh/meshIdentity';
import { PROTOCOL_VERSION } from '@/mesh/meshProtocol';
import { validateEventPayload } from '@/mesh/meshSchema';

const MESH_NODE_ID_RE = /^![0-9a-f]{8}$/i;

function isMeshtasticNodeId(value: string | undefined | null): boolean {
  return !!value && MESH_NODE_ID_RE.test(value.trim());
}

/** Inline send-message form for SIGINT popups — routes via MeshRouter */
export function SigintSendForm({
  destination,
  source,
  region,
  channel,
}: {
  destination: string;
  source: string;
  region?: string;
  channel?: string;
}) {
  const [msg, setMsg] = useState('');
  const [status, setStatus] = useState<'idle' | 'sending' | 'sent' | 'error'>('idle');
  const [detail, setDetail] = useState('');
  const [warningAck, setWarningAck] = useState(false);
  const [publicMeshAddress, setPublicMeshAddress] = useState('');

  const isMesh = source === 'meshtastic';
  const isDirectMesh = isMesh && isMeshtasticNodeId(destination);

  useEffect(() => {
    let cancelled = false;
    if (!isMesh) {
      setPublicMeshAddress('');
      return;
    }
    const identity = getNodeIdentity();
    if (!identity?.nodeId || !globalThis.crypto?.subtle) {
      setPublicMeshAddress('');
      return;
    }
    derivePublicMeshAddress(identity.nodeId)
      .then((addr) => {
        if (!cancelled) setPublicMeshAddress(addr);
      })
      .catch(() => {
        if (!cancelled) setPublicMeshAddress('');
      });
    return () => {
      cancelled = true;
    };
  }, [isMesh]);

  const handleSend = async () => {
    if (!msg.trim()) return;
    if (isMesh && !warningAck) {
      setStatus('error');
      setDetail('acknowledge public-mesh notice first');
      return;
    }
    setStatus('sending');
    try {
      const identity = getNodeIdentity();
      if (!identity || !hasSovereignty()) {
        setStatus('error');
        setDetail('identity required');
        return;
      }
      const sequence = nextSequence();
      const payload = {
        message: msg.trim(),
        destination,
        channel: channel || 'LongFast',
        priority: 'normal',
        ephemeral: false,
        transport_lock: isMesh ? 'meshtastic' : '',
      };
      const v = validateEventPayload('message', payload);
      if (!v.ok) {
        setStatus('error');
        setDetail(`invalid payload: ${v.reason}`);
        return;
      }
      const signature = await signEvent('message', identity.nodeId, sequence, payload);
      const res = await fetch(`${API_BASE}/api/mesh/send`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          destination,
          message: msg.trim(),
          sender_id: identity.nodeId,
          node_id: identity.nodeId,
          public_key: identity.publicKey,
          public_key_algo: getPublicKeyAlgo(),
          signature,
          sequence,
          protocol_version: PROTOCOL_VERSION,
          channel: channel || 'LongFast',
          priority: 'normal',
          ephemeral: false,
          ...(isMesh ? { transport_lock: 'meshtastic' } : {}),
          ...(region ? { credentials: { mesh_region: region } } : {}),
        }),
      });
      const data = await res.json();
      if (data.ok) {
        setStatus('sent');
        setDetail(data.routed_via || 'sent');
        setMsg('');
      } else {
        setStatus('error');
        setDetail(data.route_reason || data.detail || 'Failed');
      }
    } catch {
      setStatus('error');
      setDetail('Network error');
    }
    setTimeout(() => setStatus('idle'), 4000);
  };

  const label = isMesh
    ? isDirectMesh
      ? `PUBLIC DIRECT TO ${destination.toUpperCase()}`
      : `PUBLIC BROADCAST TO ${(channel || 'LongFast').toUpperCase()} (${(region || '?').toUpperCase()})`
    : 'SEND MESSAGE via MESH ROUTER';
  const placeholder = isMesh
    ? isDirectMesh
      ? `Public direct message to ${destination}...`
      : `Broadcast to ${channel || 'LongFast'}...`
    : `Message ${destination}...`;

  return (
    <div className="mt-2 pt-1.5 border-t border-[var(--border-primary)]/30">
      <div className="text-[8px] text-[#666] tracking-widest mb-1">{label}</div>
      {isMesh && (
        <div className="mb-1.5 rounded border border-amber-500/30 bg-amber-950/20 px-2 py-1.5">
          <div className="text-[8px] text-amber-300 tracking-widest">
            PUBLIC MESH NOTICE
          </div>
          <div className="text-[8px] text-amber-200/80 mt-0.5 leading-relaxed">
            These Meshtastic messages are public/degraded, not private. They may be intercepted,
            relayed, logged, or fail to deliver.
          </div>
          {publicMeshAddress && (
            <div className="text-[8px] text-amber-100/70 mt-1 font-mono">
              YOUR PUBLIC MESH ADDRESS: {publicMeshAddress.toUpperCase()}
            </div>
          )}
          <label className="mt-1 flex items-start gap-1.5 text-[8px] text-amber-100/80 cursor-pointer">
            <input
              type="checkbox"
              checked={warningAck}
              onChange={(e) => setWarningAck(e.target.checked)}
              className="mt-[1px]"
            />
            <span>I understand this message is public and not private.</span>
          </label>
        </div>
      )}
      <div className="flex gap-1">
        <input
          type="text"
          value={msg}
          onChange={(e) => setMsg(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSend()}
          placeholder={placeholder}
          maxLength={200}
          className={`flex-1 bg-[#0a0e1a] border border-[var(--border-primary)] rounded px-2 py-1 text-[10px] text-white font-mono placeholder:text-[#444] focus:outline-none ${
            isMesh ? 'focus:border-green-500/50' : 'focus:border-cyan-500/50'
          }`}
        />
        <button
          onClick={handleSend}
          disabled={status === 'sending' || !msg.trim() || (isMesh && !warningAck)}
          className={`px-2 py-1 rounded disabled:opacity-30 disabled:cursor-not-allowed transition-colors ${
            isMesh
              ? 'bg-green-950/60 border border-green-500/30 hover:bg-green-900/60 hover:border-green-400 text-green-400'
              : 'bg-cyan-950/60 border border-cyan-500/30 hover:bg-cyan-900/60 hover:border-cyan-400 text-cyan-400'
          }`}
          title={
            isMesh
              ? isDirectMesh
                ? `Send public direct message to ${destination}`
                : `Broadcast to ${channel} channel`
              : 'Send via auto-routed mesh'
          }
        >
          <Send size={10} />
        </button>
      </div>
      {status === 'sent' && (
        <div className="text-[8px] text-green-400 mt-0.5">Routed via {detail}</div>
      )}
      {status === 'error' && <div className="text-[8px] text-red-400 mt-0.5">{detail}</div>}
      {status === 'sending' && (
        <div className="text-[8px] text-cyan-400 mt-0.5 animate-pulse">Routing...</div>
      )}
    </div>
  );
}

/** Mini feed showing recent Meshtastic text messages + channel population stats */
export function MeshtasticChannelFeed({ region, channel }: { region: string; channel: string }) {
  interface MeshtasticMessage {
    from?: string;
    to?: string;
    text?: string;
    timestamp?: string | number;
  }
  interface ChannelStats {
    total_nodes?: number;
    total_live?: number;
    total_api?: number;
    regions?: Record<string, { channels?: Record<string, number> }>;
    roots?: Record<string, { channels?: Record<string, number> }>;
    known_roots?: string[];
  }

  const [messages, setMessages] = useState<MeshtasticMessage[]>([]);
  const [channelStats, setChannelStats] = useState<ChannelStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [publicMeshAddress, setPublicMeshAddress] = useState('');
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    let cancelled = false;
    const identity = getNodeIdentity();
    if (!identity?.nodeId || !globalThis.crypto?.subtle) {
      setPublicMeshAddress('');
      return;
    }
    derivePublicMeshAddress(identity.nodeId)
      .then((addr) => {
        if (!cancelled) setPublicMeshAddress(addr);
      })
      .catch(() => {
        if (!cancelled) setPublicMeshAddress('');
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const fetchData = useCallback(async () => {
    try {
      const params = new URLSearchParams({ limit: '20' });
      if (region) params.set('region', region);
      if (channel) params.set('channel', channel);
      const [msgRes, statsRes] = await Promise.all([
        fetch(`${API_BASE}/api/mesh/messages?${params}`),
        fetch(`${API_BASE}/api/mesh/channels`),
      ]);
      if (msgRes.ok) setMessages(await msgRes.json());
      if (statsRes.ok) setChannelStats(await statsRes.json());
    } catch {
      /* ignore */
    }
    setLoading(false);
  }, [region, channel]);

  useEffect(() => {
    fetchData();
    intervalRef.current = setInterval(fetchData, 15000);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [fetchData]);

  // Extract stats for this Meshtastic root/region
  const regionData = channelStats?.roots?.[region] || channelStats?.regions?.[region];
  const regionChannels = regionData?.channels || {};
  const sortedChannels = Object.entries(regionChannels).sort((a, b) => b[1] - a[1]);

  if (loading)
    return <div className="text-[8px] text-cyan-400/50 animate-pulse mt-1">Loading...</div>;

  return (
    <div className="mt-1.5 pt-1 border-t border-green-500/20">
      {/* Channel population — which channels are active in this region */}
      {sortedChannels.length > 0 && (
        <div className="mb-1.5">
          <div className="text-[8px] text-green-400/60 tracking-widest mb-0.5">
            ACTIVE CHANNELS — {region}
          </div>
          <div className="flex flex-wrap gap-1">
            {sortedChannels.map(([ch, count]) => (
              <span
                key={ch}
                className={`font-mono text-[8px] px-1.5 py-0.5 rounded border ${
                  ch === channel
                    ? 'bg-green-900/50 text-green-300 border-green-500/40'
                    : 'bg-slate-800/50 text-slate-400 border-slate-600/30'
                }`}
              >
                {ch} <span className="text-white/60">{count}</span>
              </span>
            ))}
          </div>
          {(channelStats?.total_nodes ?? 0) > 0 && (
            <div className="text-[8px] text-[#555] mt-0.5">
              {channelStats?.total_live} live + {channelStats?.total_api?.toLocaleString()} map nodes
              globally
            </div>
          )}
        </div>
      )}

      {/* Message feed */}
      {messages.length > 0 ? (
        <>
          <div className="text-[8px] text-green-400/60 tracking-widest mb-1">
            MESSAGES — {channel} ({region})
          </div>
          <div className="max-h-[140px] overflow-y-auto space-y-0.5 scrollbar-thin">
            {messages.map((m: MeshtasticMessage, i: number) => {
              const directedToYou =
                !!publicMeshAddress &&
                typeof m.to === 'string' &&
                m.to.toLowerCase() === publicMeshAddress.toLowerCase();
              const sentByYou =
                !!publicMeshAddress &&
                typeof m.from === 'string' &&
                m.from.toLowerCase() === publicMeshAddress.toLowerCase();
              return (
              <div
                key={i}
                className={`text-[9px] font-mono py-0.5 px-1 rounded hover:bg-green-950/20 ${
                  directedToYou ? 'bg-amber-950/20 border border-amber-500/20' : ''
                }`}
              >
                <span className="text-green-400">{m.from || '???'}</span>
                {m.to && m.to !== 'broadcast' && (
                  <span className="text-slate-500 ml-1">→ {m.to}</span>
                )}
                {sentByYou && (
                  <span className="text-cyan-400 ml-1">YOU</span>
                )}
                {directedToYou && (
                  <span className="text-amber-300 ml-1">TO YOU</span>
                )}
                <span className="text-white/70 ml-1.5">{m.text}</span>
                {m.timestamp && (
                  <span className="text-[#444] ml-1">
                    {new Date(m.timestamp).toLocaleTimeString([], {
                      hour: '2-digit',
                      minute: '2-digit',
                    })}
                  </span>
                )}
              </div>
              );
            })}
          </div>
        </>
      ) : (
        <div className="text-[8px] text-[#555]">No recent messages on {channel}</div>
      )}
    </div>
  );
}
