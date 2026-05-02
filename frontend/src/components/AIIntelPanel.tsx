'use client';

import React, { useState, useEffect, useCallback } from 'react';
import ReactDOM from 'react-dom';
import { getBackendEndpoint } from '@/lib/backendEndpoint';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Brain,
  MapPin,
  Trash2,
  Minus,
  Plus,
  Crosshair,
  Navigation,
  RefreshCw,
  X,
  Link2,
  Copy,
  Check,
  Shield,
  Eye,
  EyeOff,
  AlertTriangle,
  Zap,
  ChevronDown,
  ChevronRight,
  Globe,
  Rss,
} from 'lucide-react';
import { API_BASE } from '@/lib/api';
import type { AIIntelPin, AIIntelLayer, SatelliteScene } from '@/types/aiIntel';
import ConfirmDialog from '@/components/ui/ConfirmDialog';
import {
  createLayer as apiCreateLayer,
  updateLayer as apiUpdateLayer,
  deleteLayer as apiDeleteLayer,
  refreshLayerFeed as apiRefreshLayerFeed,
  fetchSatelliteImages,
} from '@/lib/aiIntelClient';

interface AIIntelPanelProps {
  onFlyTo?: (lat: number, lng: number) => void;
  isMinimized?: boolean;
  onMinimizedChange?: (minimized: boolean) => void;
  pinPlacementMode?: boolean;
  onPinPlacementModeChange?: (active: boolean) => void;
}

/* ─── Agent Identity (Ed25519 keypair — future MLS upgrade) ───────── */

function WormholeIdentitySection() {
  const [identity, setIdentity] = React.useState<{
    bootstrapped: boolean;
    node_id: string;
    public_key: string;
  } | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [bootstrapping, setBootstrapping] = React.useState(false);

  const fetchIdentity = React.useCallback(async () => {
    try {
      setLoading(true);
      const res = await fetch(`${API_BASE}/api/ai/agent-identity`);
      if (res.ok) {
        const data = await res.json();
        setIdentity(data);
      }
    } catch { /* ignore */ }
    finally { setLoading(false); }
  }, []);

  React.useEffect(() => { fetchIdentity(); }, [fetchIdentity]);

  const handleBootstrap = async (force: boolean = false) => {
    if (force && !confirm('Regenerate agent identity? The old keypair will be permanently destroyed.')) return;
    setBootstrapping(true);
    try {
      const res = await fetch(`${API_BASE}/api/ai/agent-identity/bootstrap`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ force }),
      });
      if (res.ok) {
        const data = await res.json();
        setIdentity(data);
      }
    } catch { /* ignore */ }
    finally { setBootstrapping(false); }
  };

  const handleRevoke = async () => {
    if (!confirm('Permanently revoke agent identity? This cannot be undone.')) return;
    try {
      await fetch(`${API_BASE}/api/ai/agent-identity`, { method: 'DELETE' });
      setIdentity({ bootstrapped: false, node_id: '', public_key: '' });
    } catch { /* ignore */ }
  };

  if (loading) {
    return (
      <div className="bg-cyan-950/20 border border-cyan-700/30 px-4 py-3">
        <div className="text-[11px] font-mono text-gray-500 tracking-widest uppercase flex items-center gap-2">
          <Link2 size={12} />
          Agent Identity
          <span className="text-cyan-400 animate-pulse">loading...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-cyan-950/20 border border-cyan-700/30 px-4 py-3.5">
      <div className="text-[11px] font-mono text-gray-500 tracking-widest uppercase flex items-center gap-2 mb-2.5">
        <Link2 size={12} />
        Agent Identity (Ed25519)
        <span className="ml-auto text-[9px] text-cyan-600 bg-cyan-900/30 px-1.5 py-0.5 border border-cyan-700/30">
          HMAC AUTH
        </span>
      </div>

      {identity?.bootstrapped ? (
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
            <span className="text-xs font-mono text-emerald-300">Identity Active</span>
          </div>
          <div className="bg-black/40 border border-cyan-800/30 px-3 py-2 text-xs font-mono text-cyan-300">
            <div className="flex items-center justify-between">
              <span className="text-gray-500">Node ID:</span>
              <span className="text-cyan-300 select-all">{identity.node_id}</span>
            </div>
            <div className="flex items-center justify-between mt-1">
              <span className="text-gray-500">Public Key:</span>
              <span className="text-cyan-400/60 text-[10px]">
                {identity.public_key ? identity.public_key.substring(0, 12) + '...' : 'N/A'}
              </span>
            </div>
          </div>
          <p className="text-[10px] font-mono text-gray-500 leading-relaxed">
            Agent has its own Ed25519 identity, separate from the operator. Commands currently
            travel via HMAC-authenticated HTTP (not E2EE). Private key never leaves this server.
          </p>
          <div className="flex gap-2 mt-1">
            <button
              onClick={() => handleBootstrap(true)}
              disabled={bootstrapping}
              className="text-[10px] font-mono px-2.5 py-1 bg-cyan-900/30 border border-cyan-700/40 text-cyan-400 hover:bg-cyan-800/40 hover:text-cyan-300 transition-colors disabled:opacity-50"
              title="Regenerate agent identity"
            >
              {bootstrapping ? 'Regenerating...' : 'Regenerate'}
            </button>
            <button
              onClick={handleRevoke}
              className="text-[10px] font-mono px-2.5 py-1 bg-red-900/20 border border-red-700/40 text-red-400 hover:bg-red-800/30 hover:text-red-300 transition-colors"
              title="Revoke agent identity"
            >
              <Trash2 size={10} className="inline mr-1" />
              Revoke
            </button>
          </div>
        </div>
      ) : (
        <div className="space-y-2">
          <p className="text-xs font-mono text-gray-400 leading-relaxed">
            Generate an Ed25519 identity for your agent. This keypair is used for
            mesh signing. Commands currently travel via HMAC-authenticated HTTP.
          </p>
          <button
            onClick={() => handleBootstrap(false)}
            disabled={bootstrapping}
            className="text-xs font-mono px-3 py-1.5 bg-cyan-600/20 border border-cyan-500/40 text-cyan-400 hover:bg-cyan-600/40 hover:text-cyan-200 transition-colors disabled:opacity-50"
            title="Bootstrap agent identity"
          >
            {bootstrapping ? 'Bootstrapping...' : 'Bootstrap Agent Identity'}
          </button>
        </div>
      )}
    </div>
  );
}

/* ─── Command Channel Status ───────────────────────────────────────── */

function ChannelStatusSection() {
  const [channelInfo, setChannelInfo] = React.useState<{
    ok: boolean;
    tier: number;
    reason: string;
    transport: string;
    forward_secrecy: boolean;
    sealed_sender: boolean;
    pending_commands: number;
    completed_commands: number;
    pending_tasks: number;
    stats: Record<string, number>;
  } | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [taskType, setTaskType] = React.useState('alert');
  const [taskPayload, setTaskPayload] = React.useState('');
  const [pushing, setPushing] = React.useState(false);

  const fetchStatus = React.useCallback(async () => {
    try {
      setLoading(true);
      const res = await fetch(`${API_BASE}/api/ai/channel/status`);
      if (res.ok) setChannelInfo(await res.json());
    } catch { /* ignore */ }
    finally { setLoading(false); }
  }, []);

  React.useEffect(() => { fetchStatus(); }, [fetchStatus]);

  const handlePushTask = async () => {
    if (!taskPayload.trim()) return;
    setPushing(true);
    try {
      let payload: Record<string, unknown>;
      try {
        payload = JSON.parse(taskPayload);
      } catch {
        payload = { message: taskPayload };
      }
      await fetch(`${API_BASE}/api/ai/channel/task`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task_type: taskType, payload }),
      });
      setTaskPayload('');
      fetchStatus();
    } catch { /* ignore */ }
    finally { setPushing(false); }
  };

  if (loading) {
    return (
      <div className="bg-emerald-950/20 border border-emerald-700/30 px-4 py-3">
        <div className="text-[11px] font-mono text-gray-500 tracking-widest uppercase flex items-center gap-2">
          <Zap size={12} />
          Command Channel
          <span className="text-emerald-400 animate-pulse">loading...</span>
        </div>
      </div>
    );
  }

  const tier = channelInfo?.tier ?? 1;
  const tierLabel = 'HMAC Direct';
  const tierColor = 'amber';

  return (
    <div className="bg-emerald-950/20 border border-emerald-700/30 px-4 py-3.5">
      <div className="text-[11px] font-mono text-gray-500 tracking-widest uppercase flex items-center gap-2 mb-2.5">
        <Zap size={12} />
        Command Channel
        <span className={`ml-auto text-[9px] text-${tierColor}-400 bg-${tierColor}-900/30 px-1.5 py-0.5 border border-${tierColor}-700/30`}>
          TIER {tier}
        </span>
      </div>

      {/* Tier Status */}
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full bg-${tierColor}-400 ${channelInfo?.ok ? 'animate-pulse' : ''}`} />
          <span className={`text-xs font-mono text-${tierColor}-300`}>{tierLabel}</span>
          <span className="text-[10px] font-mono text-gray-600 ml-auto">{channelInfo?.transport}</span>
        </div>

        {/* Security badges */}
        <div className="flex gap-1.5 flex-wrap">
          {channelInfo?.forward_secrecy && (
            <span className="text-[9px] font-mono px-1.5 py-0.5 bg-emerald-900/30 border border-emerald-700/30 text-emerald-400">
              FORWARD SECRECY
            </span>
          )}
          {channelInfo?.sealed_sender && (
            <span className="text-[9px] font-mono px-1.5 py-0.5 bg-emerald-900/30 border border-emerald-700/30 text-emerald-400">
              SEALED SENDER
            </span>
          )}
          <span className="text-[9px] font-mono px-1.5 py-0.5 bg-gray-800/50 border border-gray-700/30 text-gray-400">
            BIDIRECTIONAL
          </span>
        </div>

        {/* Queue stats */}
        <div className="bg-black/40 border border-emerald-800/30 px-3 py-2 text-xs font-mono">
          <div className="grid grid-cols-3 gap-2">
            <div>
              <span className="text-gray-500 text-[10px]">Pending</span>
              <div className="text-emerald-300">{channelInfo?.pending_commands ?? 0}</div>
            </div>
            <div>
              <span className="text-gray-500 text-[10px]">Completed</span>
              <div className="text-emerald-300">{channelInfo?.completed_commands ?? 0}</div>
            </div>
            <div>
              <span className="text-gray-500 text-[10px]">Tasks Queued</span>
              <div className="text-amber-300">{channelInfo?.pending_tasks ?? 0}</div>
            </div>
          </div>
        </div>

        <p className="text-[10px] font-mono text-gray-500 leading-relaxed">
          Commands authenticated via HMAC-SHA256 with body-integrity binding over HTTP.
          Wire privacy relies on TLS. End-to-end encryption is not yet available for this channel.
        </p>

        {/* Push task */}
        <div className="border-t border-emerald-800/20 pt-2 mt-1">
          <div className="text-[10px] font-mono text-gray-500 mb-1.5 uppercase tracking-wider">Push Task to Agent</div>
          <div className="flex gap-1.5">
            <select
              value={taskType}
              onChange={e => setTaskType(e.target.value)}
              className="bg-black/60 border border-emerald-800/40 text-emerald-300 text-[10px] font-mono px-1.5 py-1 w-20"
              title="Task type"
            >
              <option value="alert">alert</option>
              <option value="request">request</option>
              <option value="sync">sync</option>
              <option value="custom">custom</option>
            </select>
            <input
              type="text"
              value={taskPayload}
              onChange={e => setTaskPayload(e.target.value)}
              placeholder='{"message":"..."} or plain text'
              className="flex-1 bg-black/60 border border-emerald-800/40 text-emerald-200 text-[10px] font-mono px-2 py-1 placeholder:text-gray-600"
              onKeyDown={e => e.key === 'Enter' && handlePushTask()}
              title="Task payload"
            />
            <button
              onClick={handlePushTask}
              disabled={pushing || !taskPayload.trim()}
              className="text-[10px] font-mono px-2 py-1 bg-emerald-900/30 border border-emerald-700/40 text-emerald-400 hover:bg-emerald-800/40 hover:text-emerald-300 transition-colors disabled:opacity-50"
              title="Push task to agent"
            >
              {pushing ? '...' : 'Push'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ─── Connect OpenClaw Modal Body ─────────────────────────────────── */

interface ConnectModalBodyProps {
  apiEndpoint: string;
  handleCopy: (text: string) => void;
  copied: boolean;
}

function ConnectModalBody({ apiEndpoint, handleCopy, copied }: ConnectModalBodyProps) {
  const [riskAccepted, setRiskAccepted] = React.useState(false);
  const [accessTier, setAccessTier] = React.useState<'restricted' | 'full'>('restricted');
  const [connectionMode, setConnectionMode] = React.useState<'local' | 'remote'>('local');
  const [hmacSecret, setHmacSecret] = React.useState('');
  const [hmacLoading, setHmacLoading] = React.useState(false);
  const [tierSaving, setTierSaving] = React.useState(false);
  const [showAdvanced, setShowAdvanced] = React.useState(false);
  const [showResetConfirm, setShowResetConfirm] = React.useState(false);
  const [resetting, setResetting] = React.useState(false);
  const [regenerating, setRegenerating] = React.useState(false);
  const [showSecret, setShowSecret] = React.useState(false);
  const [snippetCopied, setSnippetCopied] = React.useState(false);

  // Node state
  const [nodeEnabled, setNodeEnabled] = React.useState(false);
  const [nodeLoading, setNodeLoading] = React.useState(true);
  const [nodeToggling, setNodeToggling] = React.useState(false);
  const [nodeId, setNodeId] = React.useState('');
  const [nodeConfirmed, setNodeConfirmed] = React.useState(false);

  const [remoteUrl, setRemoteUrl] = React.useState('');

  // Tor state
  const [torStarting, setTorStarting] = React.useState(false);
  const [torError, setTorError] = React.useState('');
  const [torOnion, setTorOnion] = React.useState('');

  // Fetch connect-info + node status on mount
  React.useEffect(() => {
    (async () => {
      try {
        setHmacLoading(true);
        const res = await fetch(`${API_BASE}/api/ai/connect-info?reveal=true`);
        if (res.ok) {
          const data = await res.json();
          setHmacSecret(data.hmac_secret || '');
          setAccessTier(data.access_tier === 'full' ? 'full' : 'restricted');
        }
      } catch { /* ignore */ }
      finally { setHmacLoading(false); }
    })();
    (async () => {
      try {
        setNodeLoading(true);
        const res = await fetch(`${API_BASE}/api/settings/node`);
        if (res.ok) {
          const data = await res.json();
          setNodeEnabled(!!data.node_enabled || !!data.enabled);
        }
      } catch { /* ignore */ }
      finally { setNodeLoading(false); }
    })();
    (async () => {
      try {
        const res = await fetch(`${API_BASE}/api/ai/agent-identity`);
        if (res.ok) {
          const data = await res.json();
          if (data.bootstrapped) setNodeId(data.node_id || '');
        }
      } catch { /* ignore */ }
    })();
    // Fetch Tor status
    (async () => {
      try {
        const res = await fetch(`${API_BASE}/api/settings/tor`);
        if (res.ok) {
          const data = await res.json();
          if (data.onion_address) {
            setTorOnion(data.onion_address);
            setRemoteUrl(data.onion_address);
          }
        }
      } catch { /* ignore */ }
    })();
  }, []);

  // One-click remote setup: start node + bootstrap identity + start Tor + get address
  const handleRemoteSetup = async () => {
    setTorStarting(true);
    setTorError('');
    try {
      // 1. Enable mesh node
      await fetch(`${API_BASE}/api/settings/node`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: true }),
      });
      setNodeEnabled(true);
      setNodeConfirmed(true);

      // 2. Bootstrap agent identity (gets node_id)
      const idRes = await fetch(`${API_BASE}/api/ai/agent-identity/bootstrap`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ force: false }),
      });
      if (idRes.ok) {
        const idData = await idRes.json();
        if (idData.node_id) setNodeId(idData.node_id);
      }

      // 3. Start Tor hidden service
      const torRes = await fetch(`${API_BASE}/api/settings/tor/start`, { method: 'POST' });
      const torData = await torRes.json();
      if (torData.ok && torData.onion_address) {
        setTorOnion(torData.onion_address);
        setRemoteUrl(torData.onion_address);
      } else {
        setTorError(torData.detail || 'Failed to start Tor');
      }
    } catch {
      setTorError('Failed to connect to backend');
    }
    finally { setTorStarting(false); }
  };

  const handleResetAll = async () => {
    setResetting(true);
    setShowResetConfirm(false);
    try {
      const res = await fetch(`${API_BASE}/api/settings/agent/reset-all`, { method: 'POST' });
      const data = await res.json();
      if (data.ok) {
        // Update local state with new credentials
        if (data.new_hmac_secret) setHmacSecret(data.new_hmac_secret);
        if (data.new_onion) {
          setTorOnion(data.new_onion);
          setRemoteUrl(data.new_onion);
        }
        if (data.new_node_id) setNodeId(data.new_node_id);
      }
    } catch { /* ignore */ }
    finally { setResetting(false); }
  };

  const handleTierChange = async (tier: 'restricted' | 'full') => {
    setAccessTier(tier);
    setTierSaving(true);
    try {
      await fetch(`${API_BASE}/api/ai/connect-info/access-tier`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tier }),
      });
    } catch { /* ignore */ }
    finally { setTierSaving(false); }
  };

  const handleRegenerate = async () => {
    setRegenerating(true);
    try {
      const res = await fetch(`${API_BASE}/api/ai/connect-info/regenerate`, { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        setHmacSecret(data.hmac_secret || '');
      }
    } catch { /* ignore */ }
    finally { setRegenerating(false); }
  };

  const handleNodeToggle = async (enable: boolean) => {
    setNodeToggling(true);
    try {
      const res = await fetch(`${API_BASE}/api/settings/node`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: enable }),
      });
      if (res.ok) {
        setNodeEnabled(enable);
        // Auto-bootstrap agent identity when enabling node
        if (enable && !nodeId) {
          try {
            const idRes = await fetch(`${API_BASE}/api/ai/agent-identity/bootstrap`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ force: false }),
            });
            if (idRes.ok) {
              const idData = await idRes.json();
              setNodeId(idData.node_id || '');
            }
          } catch { /* ignore */ }
        }
      }
    } catch { /* ignore */ }
    finally { setNodeToggling(false); }
  };

  const maskedSecret = hmacSecret
    ? hmacSecret.slice(0, 6) + '\u2022'.repeat(8) + hmacSecret.slice(-4)
    : '\u2022'.repeat(16);

  // Resolve the endpoint URL
  const resolvedUrl = connectionMode === 'local'
    ? 'http://localhost:8000'
    : remoteUrl.trim() || '';

  // Connection snippet — display is masked, copy has real key
  const buildSnippet = (key: string) => {
    const lines: string[] = [];
    if (resolvedUrl) lines.push(`SHADOWBROKER_URL=${resolvedUrl}`);
    lines.push(`SHADOWBROKER_KEY=${key}`);
    lines.push(`SHADOWBROKER_ACCESS=${accessTier}`);
    if (connectionMode === 'remote' && nodeId) lines.push(`SHADOWBROKER_NODE_ID=${nodeId}`);
    lines.push('');
    lines.push('# OPERATING DIRECTIVE:');
    lines.push('# You are a remote OpenClaw agent connected to ShadowBroker.');
    lines.push('# ShadowBroker is a live intelligence and telemetry platform, not a narrow single-purpose API.');
    lines.push('# Treat the platform as having broad live telemetry unless a focused check proves otherwise.');
    lines.push("# Do not claim a layer, entity type, or capability is unavailable until you verify it from live data.");
    lines.push("# If something is absent, say 'not found in current telemetry' or 'not present in the current dataset' rather than saying ShadowBroker cannot track it.");
    lines.push('# Full access means you MAY place pins, create layers, inject data, set watches, and trigger displays, but do not perform write actions unless the user asks or the task clearly requires it.');
    lines.push('# For ordinary questions, prefer read commands and concise answers grounded in live results.');

    // Tool manifest — first thing the agent should hit
    if (resolvedUrl) {
      lines.push('');
      lines.push('# FIRST: Load your tools from this endpoint:');
      lines.push(`# GET ${resolvedUrl}/api/ai/tools`);
      lines.push('# Returns structured tool definitions (names, params, types, examples).');
      lines.push('# Load these as your available tool/function definitions on connect.');
      lines.push('# Prefer compact lookups first: get_summary, search_telemetry, find_flights, find_ships, search_news, entities_near, get_layer_slice.');
      lines.push('# Reserve get_telemetry, get_slow_telemetry, and get_report for rare full-context pulls.');
      lines.push('# BATCH COMMANDS: POST /api/ai/channel/batch with {"commands": [{"cmd": "...", "args": {...}}, ...]} (max 20).');
      lines.push('# Batch executes all commands concurrently in one HTTP round-trip. Use it whenever you need 2+ lookups.');
      lines.push('# Example: batch entities_near + search_news + get_correlations in one call instead of 3 sequential calls.');
      lines.push('# INCREMENTAL UPDATES: get_layer_slice supports since_version. Pass the version from the previous response to skip unchanged data (instant 0-byte response when nothing changed).');
      lines.push("# get_summary is full layer discovery: use it to learn every live telemetry layer before concluding something is unavailable.");
      lines.push('# get_layer_slice is uncapped by default. Pass limit_per_layer only when you intentionally want a smaller slice.');
      lines.push("# UAP sightings, wastewater, and tracked_flights/VIP aircraft are real layers when populated. Verify with get_summary/get_layer_slice before claiming they don't exist.");
      lines.push("# fishing_activity is the fishing-vessel activity layer. Aliases like gfw and global_fishing_watch should be treated as fishing_activity.");
      lines.push("# Use search_telemetry as the Google-style entry point whenever the user gives you a person, place, company, owner, nickname, or natural-language phrase and you do not already know the source layer.");
      lines.push("# Example: 'Where is Jerry Jones yacht?' -> search_telemetry('Jerry Jones') first, then refine with find_ships only after you identify the ship match.");
      lines.push("# For fuzzy natural-language lookups like 'Patriots jet' or 'Jerry Jones yacht', inspect the ranked search_telemetry candidates before making a hard claim.");
      lines.push("# search_telemetry returns ranked candidates grouped by entity type, so use the groups to narrow aircraft vs ships vs events before answering.");
      lines.push("# For AF1/AF2 or other VIP aircraft, use find_flights first when the domain is obvious, then get_layer_slice(['tracked_flights']) if you need raw layer context.");
      lines.push("# If one domain-specific command returns 0, do not conclude the entity is absent. Fall back to search_telemetry before any layer pull.");
      lines.push("# If search_telemetry returns several plausible matches, summarize the top candidates instead of pretending one uncertain hit is definitive.");
      lines.push("# If a user asks 'what is near here', use entities_near before pulling large datasets.");
      lines.push("# If a user asks about a topic or incident, use search_news before downloading the full slow feed.");
    }

    // SAR (Synthetic Aperture Radar) ground-change layer
    lines.push('');
    lines.push('# SAR GROUND-CHANGE LAYER:');
    lines.push('# ShadowBroker has a full SAR (Synthetic Aperture Radar) layer that detects ground changes through cloud cover, at night, anywhere on Earth.');
    lines.push('# Two modes — both free:');
    lines.push('#   Mode A (Catalog): Free Sentinel-1 scene metadata from Alaska Satellite Facility. No account needed. Shows radar passes over AOIs and next-pass timing.');
    lines.push('#   Mode B (Anomalies): Pre-processed ground-change alerts from NASA OPERA (DISP deformation, DSWx water, DIST-ALERT vegetation), Copernicus EGMS, GFM floods, UNOSAT/EMS damage. Requires free Earthdata token.');
    lines.push('# SAR commands (all routed through /api/ai/channel/command):');
    lines.push('#   sar_status — check Mode A/B status. ALWAYS call this first when the user asks about SAR/radar/deformation/floods. If Mode B is off, the response includes signup URLs to paste to the user.');
    lines.push('#   sar_anomalies_recent(kind?, limit?) — latest anomalies. Kinds: ground_deformation, surface_water_change, flood_extent, vegetation_disturbance, damage_assessment, coherence_change.');
    lines.push('#   sar_anomalies_near(lat, lon, radius_km?, kind?, limit?) — anomalies within radius of a point.');
    lines.push('#   sar_scene_search(aoi_id?, limit?) — Sentinel-1 scene catalog (Mode A, always works when AOIs exist).');
    lines.push('#   sar_coverage_for_aoi(aoi_id?) — per-AOI coverage and rough next-pass estimate.');
    lines.push('#   sar_aoi_list — list all operator-defined Areas of Interest.');
    lines.push('#   sar_aoi_add(id, name, center_lat, center_lon, radius_km?, category?, description?) — create/update an AOI (write command).');
    lines.push('#   sar_aoi_remove(aoi_id) — delete an AOI (write command).');
    lines.push('#   sar_pin_click(anomaly_id) — fetch the full detail payload for a specific anomaly (same data as the map popup). Returns {anomaly, aoi, recent_scenes}.');
    lines.push('#   sar_focus_aoi(aoi_id, zoom?) — fly the operator\'s map to an AOI center. The frontend picks this up in real time.');
    lines.push('#   sar_pin_from_anomaly(anomaly_id, label?) — promote a SAR anomaly to a persistent AI Intel pin on the map (write command).');
    lines.push('#   sar_watch_anomaly(aoi_id, kind?) — set up a watchdog that fires when matching anomalies appear in an AOI (write command).');
    lines.push('# SAR rules: (1) Call sar_status first. (2) If Mode B is off, paste the help URLs — never tell the user to "search for it". (3) Anomalies have evidence_hash — preserve it when promoting to pins. (4) AOI categories: watchlist, conflict, infrastructure, natural_hazard, border, maritime.');

    // Analysis zones — agent-placed map overlays with written assessments
    lines.push('');
    lines.push('# ANALYSIS ZONES (agent-authored map notes):');
    lines.push('# The old regex-based "contradiction detector" has been REMOVED. It pattern-matched denial keywords against outages and produced constant false positives.');
    lines.push('# Instead, you — the agent — place colored square overlays on the map with a written assessment that the operator can read by clicking the zone.');
    lines.push('# Think of these as sticky notes: "I noticed X in this area, here is what I think it means."  The operator can delete any zone by clicking the trash icon in the popup.');
    lines.push('# Analysis zone commands (all routed through /api/ai/channel/command):');
    lines.push('#   list_analysis_zones — list all currently active zones (read).');
    lines.push('#   place_analysis_zone(lat, lng, title, body, category?, severity?, drivers?, cell_size_deg?, ttl_hours?) — drop a new zone (write).');
    lines.push('#     category: contradiction | analysis | warning | observation | hypothesis  (default: analysis)');
    lines.push('#     severity: high | medium | low  (default: medium — controls fill opacity, not an alarm level)');
    lines.push('#     drivers: up to 5 short bullet strings shown as "KEY INDICATORS" in the popup.');
    lines.push('#     body: your full written assessment (up to ~2000 chars), shown verbatim in the "AGENT ASSESSMENT" section — newlines preserved.');
    lines.push('#     cell_size_deg: square size in degrees (default 2.0 ≈ ~220km). Use smaller (0.3-0.8) for city-scale, larger (3-5) for regional.');
    lines.push('#     ttl_hours: optional auto-expiry. Omit for permanent until user deletes.');
    lines.push('#   delete_analysis_zone(zone_id) — remove a specific zone you placed (write).');
    lines.push('#   clear_analysis_zones — wipe all zones (write, use sparingly).');
    lines.push('# Analysis zone rules:');
    lines.push('#   (1) Only place zones when you have something genuinely worth noting. Do NOT spam the map.');
    lines.push('#   (2) Write the body as a short intelligence note in YOUR voice — what you observed, what it might mean, what you are NOT sure about. 2-6 sentences is ideal.');
    lines.push('#   (3) Use category="contradiction" (amber) when official statements conflict with telemetry; "warning" (red) for active threats; "observation" (blue) for neutral notes; "hypothesis" (purple) for speculative reads; "analysis" (cyan, default) for general assessments.');
    lines.push('#   (4) Prefer placing zones in response to operator questions or emerging events you spot while reviewing telemetry, not on a fixed schedule.');
    lines.push('#   (5) Zones persist across restarts. If yours become stale, clean them up with delete_analysis_zone.');

    // SSE endpoint (preferred for remote — works over Tor, keeps circuit warm)
    if (resolvedUrl) {
      lines.push('');
      lines.push('# Real-time push (SSE stream — works over Tor, keeps circuit warm):');
      lines.push(`# GET ${resolvedUrl}/api/ai/channel/sse  (keep open, receives events)`);
      lines.push(`# POST ${resolvedUrl}/api/ai/channel/command  (send commands)`);
      lines.push('# Command replies are returned immediately from POST /api/ai/channel/command.');
      lines.push('# Use SSE for pushed alerts/tasks. Use /api/ai/channel/poll only as a fallback if SSE is unavailable.');
      lines.push('# Suggested lookup flow:');
      lines.push('# 1. get_summary (discover available layers + counts)');
      lines.push('# 2. Batch your focused lookups: POST /api/ai/channel/batch with multiple commands in one call');
      lines.push('#    e.g. {"commands": [{"cmd":"find_flights","args":{"callsign":"AF1"}}, {"cmd":"search_news","args":{"query":"military"}}]}');
      lines.push('# 3. For repeat polling, use get_layer_slice with since_version to skip unchanged data');
      lines.push('# 4. Only pull full telemetry (get_telemetry/get_report) if focused commands were insufficient');
      lines.push('# 5. Use write commands only when the user explicitly wants an action on the map/system');
    }

    if (connectionMode === 'remote' && resolvedUrl.includes('.onion')) {
      lines.push('');
      lines.push('# .onion requires Tor on the agent machine too:');
      lines.push('# 1. Install Tor:  sudo apt install tor  (or brew install tor)');
      lines.push('# 2. Tor starts a SOCKS5 proxy on localhost:9050');
      lines.push('# 3. Route requests through it:  pip install PySocks requests[socks]');
      lines.push('#    proxies = {"http": "socks5h://127.0.0.1:9050", "https": "socks5h://127.0.0.1:9050"}');
      lines.push('#    requests.get(SHADOWBROKER_URL + "/api/health", proxies=proxies)');
    }
    return lines.join('\n');
  };
  const displaySnippet = buildSnippet(maskedSecret);
  const copySnippet = buildSnippet(hmacSecret);

  const handleCopySnippet = () => {
    navigator.clipboard.writeText(copySnippet);
    setSnippetCopied(true);
    setTimeout(() => setSnippetCopied(false), 2000);
  };

  // Remote mode requires node confirmed + a reachable URL
  const remoteReady = connectionMode === 'local' || (nodeConfirmed && resolvedUrl.length > 0);

  return (
    <div className="px-6 py-5 space-y-5">

      {/* ── Risk acceptance ──────────────────────────────── */}
      {!riskAccepted && (
        <div className="bg-amber-950/40 border border-amber-600/50 px-4 py-3.5">
          <div className="flex items-start gap-3">
            <AlertTriangle size={18} className="text-amber-400 shrink-0 mt-0.5" />
            <div>
              <div className="text-xs font-mono text-amber-300 font-bold tracking-wider uppercase mb-1.5">
                Heads Up
              </div>
              <p className="text-xs font-mono text-amber-200/80 leading-relaxed">
                Connecting an AI agent gives it access to your ShadowBroker data.
                You control what it can do (read-only or full access). You&apos;re
                responsible for what your agent does with it.
              </p>
              <button
                onClick={() => setRiskAccepted(true)}
                className="mt-3 px-4 py-2 text-xs font-mono tracking-wider bg-amber-600/30 border border-amber-500/50 text-amber-300 hover:bg-amber-600/50 hover:text-amber-200 transition-colors"
              >
                I UNDERSTAND, CONTINUE
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Main flow ────────────────────────────────────── */}
      {riskAccepted && (
        <>
          {/* Step 1: Where is your agent? */}
          <div>
            <div className="text-[11px] font-mono text-violet-400 tracking-widest mb-2.5 uppercase font-bold">
              Step 1 &mdash; Where is your agent?
            </div>
            <div className="grid grid-cols-2 gap-2">
              <button
                onClick={() => setConnectionMode('local')}
                className={`text-left px-4 py-3 border transition-all ${
                  connectionMode === 'local'
                    ? 'bg-cyan-950/40 border-cyan-500/50'
                    : 'bg-black/30 border-gray-700/40 hover:border-gray-600/60'
                }`}
                title="Agent running on this machine"
              >
                <div className={`text-sm font-mono font-bold ${connectionMode === 'local' ? 'text-cyan-300' : 'text-gray-400'}`}>
                  Local
                </div>
                <p className="text-[10px] font-mono text-gray-500 mt-1">
                  Same machine as ShadowBroker
                </p>
              </button>
              <button
                onClick={() => setConnectionMode('remote')}
                className={`text-left px-4 py-3 border transition-all ${
                  connectionMode === 'remote'
                    ? 'bg-violet-950/40 border-violet-500/50'
                    : 'bg-black/30 border-gray-700/40 hover:border-gray-600/60'
                }`}
                title="Agent running on another computer"
              >
                <div className={`text-sm font-mono font-bold ${connectionMode === 'remote' ? 'text-violet-300' : 'text-gray-400'}`}>
                  Remote
                </div>
                <p className="text-[10px] font-mono text-gray-500 mt-1">
                  Different machine over network
                </p>
              </button>
            </div>
          </div>

          {/* Step 2 (Remote): Generate private link — one button does everything */}
          {connectionMode === 'remote' && (
            <div>
              <div className="text-[11px] font-mono text-violet-400 tracking-widest mb-2.5 uppercase font-bold">
                Step 2 &mdash; Generate your private link
              </div>

              {torOnion && remoteReady ? (
                /* Already have an address — show it */
                <div className="bg-emerald-950/30 border border-emerald-600/40 px-4 py-3 space-y-2">
                  <div className="flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                    <span className="text-xs font-mono text-emerald-300">Private link active</span>
                  </div>
                  <div className="text-xs font-mono text-emerald-200 select-all break-all">{torOnion}</div>
                  <p className="text-[10px] font-mono text-gray-500">
                    This .onion address is persistent and stays the same across restarts.
                  </p>
                </div>
              ) : (
                /* Need to generate */
                <div className="space-y-2.5">
                  {!torStarting && (
                    <button
                      onClick={handleRemoteSetup}
                      className="w-full py-3 text-sm font-mono tracking-wider border border-emerald-500/50 bg-emerald-600/20 text-emerald-300 hover:bg-emerald-600/40 hover:text-emerald-100 transition-colors"
                    >
                      GENERATE PRIVATE LINK
                    </button>
                  )}
                  {torStarting && (
                    <div className="w-full py-3 text-sm font-mono tracking-wider border border-violet-500/50 bg-violet-600/20 text-violet-300 text-center animate-pulse">
                      SETTING UP SECURE CONNECTION...
                    </div>
                  )}
                  {torError && (
                    <div className="bg-red-950/30 border border-red-700/40 px-4 py-2.5 text-[10px] font-mono text-red-300">
                      {torError}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Step N: Access Level */}
          <div>
            <div className="text-[11px] font-mono text-violet-400 tracking-widest mb-2.5 uppercase font-bold">
              Step {connectionMode === 'local' ? '2' : '3'} &mdash; What can it do?
              {tierSaving && <span className="text-violet-300 animate-pulse ml-1">saving...</span>}
            </div>
            <div className="grid grid-cols-2 gap-2">
              <button
                onClick={() => handleTierChange('restricted')}
                className={`text-left px-4 py-3 border transition-all ${
                  accessTier === 'restricted'
                    ? 'bg-emerald-950/40 border-emerald-500/50'
                    : 'bg-black/30 border-gray-700/40 hover:border-gray-600/60'
                }`}
                title="Read-only access"
              >
                <div className="flex items-center gap-2 mb-1">
                  <Shield size={14} className={accessTier === 'restricted' ? 'text-emerald-400' : 'text-gray-500'} />
                  <span className={`text-sm font-mono font-bold ${accessTier === 'restricted' ? 'text-emerald-300' : 'text-gray-400'}`}>
                    Read Only
                  </span>
                </div>
                <p className="text-[10px] font-mono text-gray-500 leading-relaxed">
                  Can see your data but can&apos;t change anything
                </p>
              </button>
              <button
                onClick={() => handleTierChange('full')}
                className={`text-left px-4 py-3 border transition-all ${
                  accessTier === 'full'
                    ? 'bg-red-950/30 border-red-500/50'
                    : 'bg-black/30 border-gray-700/40 hover:border-gray-600/60'
                }`}
                title="Full read+write access"
              >
                <div className="flex items-center gap-2 mb-1">
                  <Zap size={14} className={accessTier === 'full' ? 'text-red-400' : 'text-gray-500'} />
                  <span className={`text-sm font-mono font-bold ${accessTier === 'full' ? 'text-red-300' : 'text-gray-400'}`}>
                    Full Access
                  </span>
                </div>
                <p className="text-[10px] font-mono text-gray-500 leading-relaxed">
                  Can place pins, inject data, post to mesh
                </p>
              </button>
            </div>
          </div>

          {/* Step N+1: Connection Credentials */}
          <div>
            <div className="text-[11px] font-mono text-violet-400 tracking-widest mb-2.5 uppercase font-bold">
              Step {connectionMode === 'local' ? '3' : '4'} &mdash; Copy this into your agent
            </div>

            {!remoteReady ? (
              <div className="bg-black/40 border border-amber-700/40 px-4 py-3 text-xs font-mono text-amber-400/80 flex items-center gap-2">
                <AlertTriangle size={12} />
                Start the mesh node above first
              </div>
            ) : (
              <>
                <p className="text-[10px] font-mono text-gray-500 mb-2">
                  {connectionMode === 'local'
                    ? 'Paste these as environment variables or add them to your agent\u2019s config.'
                    : 'Give these to your agent. The key is masked below \u2014 COPY sends the real key to your clipboard.'}
                </p>
                <div className="relative">
                  <pre className="bg-black/60 border border-violet-800/40 px-4 py-3 pr-20 text-xs font-mono text-violet-300 whitespace-pre-wrap break-all leading-relaxed">
                    {hmacLoading ? 'Loading...' : displaySnippet}
                  </pre>
                  <button
                    onClick={handleCopySnippet}
                    className="absolute top-2 right-2 px-2.5 py-1.5 bg-violet-600/40 border border-violet-500/50 text-violet-300 hover:bg-violet-600/60 hover:text-violet-100 transition-colors text-[10px] font-mono tracking-wider flex items-center gap-1.5"
                    title="Copy connection config (copies real key to clipboard)"
                  >
                    {snippetCopied ? <><Check size={12} /> COPIED</> : <><Copy size={12} /> COPY</>}
                  </button>
                </div>
              </>
            )}
          </div>

          {/* Done indicator */}
          {remoteReady && (
            <div className="bg-emerald-950/30 border border-emerald-600/40 px-4 py-3 flex items-center gap-3">
              <Check size={16} className="text-emerald-400 shrink-0" />
              <p className="text-xs font-mono text-emerald-300">
                {connectionMode === 'local'
                  ? 'Done. Your agent authenticates via HMAC-signed requests to localhost. Use WebSocket or SSE for persistent real-time comms.'
                  : 'Done. Your agent registers with this node. Open GET /api/ai/channel/sse for real-time push over a single Tor circuit.'}
              </p>
            </div>
          )}

          {/* ── Advanced (collapsed) ─────────────────────── */}
          <div className="border-t border-gray-800/50 pt-3">
            <button
              onClick={() => setShowAdvanced(!showAdvanced)}
              className="flex items-center gap-2 text-[11px] font-mono text-gray-500 tracking-widest uppercase hover:text-gray-400 transition-colors w-full"
            >
              {showAdvanced ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
              Advanced
            </button>

            {showAdvanced && (
              <div className="mt-4 space-y-4">
                {/* HMAC Key Management */}
                <div>
                  <div className="text-[11px] font-mono text-gray-500 tracking-widest mb-2 uppercase">
                    HMAC Key
                  </div>
                  <div className="flex items-center gap-2">
                    <code className="flex-1 bg-black/60 border border-violet-800/40 px-3 py-2 text-xs font-mono text-violet-300 overflow-hidden text-ellipsis">
                      {showSecret ? hmacSecret : maskedSecret}
                    </code>
                    <button
                      onClick={() => setShowSecret(!showSecret)}
                      className="p-2 bg-violet-600/20 border border-violet-500/40 text-violet-400 hover:bg-violet-600/40 transition-colors shrink-0"
                      title={showSecret ? 'Hide' : 'Reveal'}
                    >
                      {showSecret ? <EyeOff size={14} /> : <Eye size={14} />}
                    </button>
                    <button
                      onClick={() => handleCopy(hmacSecret)}
                      className="p-2 bg-violet-600/20 border border-violet-500/40 text-violet-400 hover:bg-violet-600/40 transition-colors shrink-0"
                      title="Copy key"
                    >
                      {copied ? <Check size={14} /> : <Copy size={14} />}
                    </button>
                    <button
                      onClick={handleRegenerate}
                      disabled={regenerating}
                      className="p-2 bg-red-900/20 border border-red-700/40 text-red-400 hover:bg-red-800/30 transition-colors disabled:opacity-50 shrink-0"
                      title="Regenerate (invalidates old key)"
                    >
                      <RefreshCw size={14} className={regenerating ? 'animate-spin' : ''} />
                    </button>
                  </div>
                  <p className="text-[10px] font-mono text-gray-600 mt-1">
                    Regenerating creates a new key and immediately invalidates the old one.
                  </p>
                </div>

                {/* Node Control */}
                <div className="bg-violet-950/20 border border-violet-700/30 px-4 py-3">
                  <div className="text-[11px] font-mono text-gray-500 tracking-widest mb-2 uppercase">
                    Mesh Node
                  </div>
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className={`w-2 h-2 rounded-full ${nodeEnabled ? 'bg-emerald-400 animate-pulse' : 'bg-gray-600'}`} />
                      <span className={`text-xs font-mono ${nodeEnabled ? 'text-emerald-300' : 'text-gray-500'}`}>
                        {nodeLoading ? 'Checking...' : nodeEnabled ? 'Active' : 'Inactive'}
                      </span>
                    </div>
                    {!nodeLoading && (
                      <button
                        onClick={() => handleNodeToggle(!nodeEnabled)}
                        disabled={nodeToggling}
                        className={`text-[10px] font-mono px-2.5 py-1 border transition-colors disabled:opacity-50 ${
                          nodeEnabled
                            ? 'bg-red-900/20 border-red-700/40 text-red-400 hover:bg-red-800/30'
                            : 'bg-emerald-900/20 border-emerald-700/40 text-emerald-400 hover:bg-emerald-800/30'
                        }`}
                      >
                        {nodeToggling ? '...' : nodeEnabled ? 'Stop Node' : 'Start Node'}
                      </button>
                    )}
                  </div>
                  {nodeId && (
                    <div className="mt-2 text-[10px] font-mono text-gray-500">
                      Node ID: <span className="text-violet-400/70 select-all">{nodeId}</span>
                    </div>
                  )}
                </div>

                {/* Agent Identity */}
                <WormholeIdentitySection />

                {/* Command Channel */}
                <ChannelStatusSection />

                {/* API Endpoint */}
                <div>
                  <div className="text-[11px] font-mono text-gray-500 tracking-widest mb-2 uppercase">API Endpoint</div>
                  <div className="flex items-center gap-2">
                    <code className="flex-1 bg-black/60 border border-violet-800/40 px-3 py-2 text-xs font-mono text-violet-300 select-all">
                      {apiEndpoint}
                    </code>
                    <button
                      onClick={() => handleCopy(apiEndpoint)}
                      className="p-2 bg-violet-600/20 border border-violet-500/40 text-violet-400 hover:bg-violet-600/40 transition-colors shrink-0"
                      title="Copy endpoint"
                    >
                      {copied ? <Check size={14} /> : <Copy size={14} />}
                    </button>
                  </div>
                </div>

                {/* Nuclear Reset */}
                <div className="border-t border-red-900/30 pt-4">
                  <button
                    onClick={() => setShowResetConfirm(true)}
                    disabled={resetting}
                    className="w-full py-2.5 text-[11px] font-mono tracking-wider border border-red-700/40 bg-red-950/20 text-red-400 hover:bg-red-900/30 hover:text-red-300 transition-colors disabled:opacity-50"
                  >
                    {resetting ? 'RESETTING...' : 'RESET ALL CREDENTIALS'}
                  </button>
                  <p className="text-[10px] font-mono text-gray-600 mt-1.5 leading-relaxed">
                    Generates a new HMAC key, .onion address, and node identity. Your agent will be fully disconnected and will need new credentials.
                  </p>
                </div>
              </div>
            )}
          </div>

          {/* Reset confirmation dialog */}
          <ConfirmDialog
            open={showResetConfirm}
            title="Reset All Agent Credentials"
            message={`This will:\n\n• Generate a new HMAC key (old one dies instantly)\n• Destroy your .onion address and create a new one\n• Revoke the current node identity\n\nYour agent will be completely disconnected. You will need to send it new credentials.\n\nThis cannot be undone.`}
            confirmLabel={resetting ? 'RESETTING...' : 'RESET EVERYTHING'}
            cancelLabel="CANCEL"
            danger={true}
            onConfirm={handleResetAll}
            onCancel={() => setShowResetConfirm(false)}
          />
        </>
      )}
    </div>
  );
}

export default function AIIntelPanel({
  onFlyTo,
  isMinimized: isMinimizedProp,
  onMinimizedChange,
  pinPlacementMode,
  onPinPlacementModeChange,
}: AIIntelPanelProps) {
  const [internalMinimized, setInternalMinimized] = useState(true);
  const isMinimized = isMinimizedProp !== undefined ? isMinimizedProp : internalMinimized;
  const setIsMinimized = (val: boolean | ((prev: boolean) => boolean)) => {
    const newVal = typeof val === 'function' ? val(isMinimized) : val;
    setInternalMinimized(newVal);
    onMinimizedChange?.(newVal);
  };

  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Confirm dialog state
  const [confirmDialog, setConfirmDialog] = useState<{
    title: string;
    message: string;
    confirmLabel?: string;
    onConfirm: () => void;
  } | null>(null);

  // Layers + pins
  const [layers, setLayers] = useState<AIIntelLayer[]>([]);
  const [pins, setPins] = useState<AIIntelPin[]>([]);
  const [expandedLayers, setExpandedLayers] = useState<Set<string>>(new Set());
  const [newLayerName, setNewLayerName] = useState('');
  const [newLayerFeedUrl, setNewLayerFeedUrl] = useState('');
  const [showNewLayer, setShowNewLayer] = useState(false);

  // Near Me
  const [nearMeRadius, setNearMeRadius] = useState(100);
  const [nearMeResults, setNearMeResults] = useState<any>(null);

  // Satellite imagery search
  const [satLat, setSatLat] = useState('');
  const [satLng, setSatLng] = useState('');
  const [satScenes, setSatScenes] = useState<SatelliteScene[]>([]);
  const [satSearching, setSatSearching] = useState(false);
  const [satLocationQuery, setSatLocationQuery] = useState('');
  const [satGeocoding, setSatGeocoding] = useState(false);

  // Connect panel
  const [showConnect, setShowConnect] = useState(false);
  const [copied, setCopied] = useState(false);

  const apiEndpoint = getBackendEndpoint();

  const handleCopy = useCallback((text: string) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, []);

  const totalPins = pins.length;

  // ── Data fetching ───────────────────────────────────────────────
  const refreshData = useCallback(async () => {
    try {
      const [layerResp, pinResp] = await Promise.all([
        fetch(`${API_BASE}/api/ai/layers`),
        fetch(`${API_BASE}/api/ai/pins?limit=500`),
      ]);
      if (layerResp.ok) {
        const ld = await layerResp.json();
        setLayers(ld.layers || []);
      }
      if (pinResp.ok) {
        const pd = await pinResp.json();
        setPins(pd.pins || []);
      }
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'AI Intel unavailable');
    }
  }, []);

  useEffect(() => {
    void refreshData();
    const tid = setInterval(refreshData, 30_000);
    return () => clearInterval(tid);
  }, [refreshData]);

  // ── Layer actions ───────────────────────────────────────────────
  const handleCreateLayer = async () => {
    const name = newLayerName.trim();
    if (!name) return;
    setBusy(true);
    try {
      const feedUrl = newLayerFeedUrl.trim();
      await apiCreateLayer({
        name,
        source: feedUrl ? 'feed' : 'user',
        ...(feedUrl ? { feed_url: feedUrl } : {}),
      });
      setNewLayerName('');
      setNewLayerFeedUrl('');
      setShowNewLayer(false);
      await refreshData();
    } catch {}
    setBusy(false);
  };

  const handleToggleLayerVisibility = async (layerId: string, currentlyVisible: boolean) => {
    try {
      await apiUpdateLayer(layerId, { visible: !currentlyVisible });
      await refreshData();
    } catch {}
  };

  const handleDeleteLayer = (layerId: string) => {
    const layer = layers.find((l) => l.id === layerId);
    const layerPinCount = pins.filter((p) => p.layer_id === layerId).length;
    const name = layer?.name || 'this layer';
    const msg =
      layerPinCount > 0
        ? `Delete "${name}" and all ${layerPinCount} pin${layerPinCount === 1 ? '' : 's'} in it?\n\nThis cannot be undone.`
        : `Delete layer "${name}"?`;
    setConfirmDialog({
      title: 'DELETE LAYER',
      message: msg,
      confirmLabel: 'DELETE',
      onConfirm: async () => {
        setConfirmDialog(null);
        setBusy(true);
        try {
          await apiDeleteLayer(layerId);
          await refreshData();
        } catch {}
        setBusy(false);
      },
    });
  };

  const handleRefreshFeed = async (layerId: string) => {
    setBusy(true);
    try {
      await apiRefreshLayerFeed(layerId);
      await refreshData();
    } catch {}
    setBusy(false);
  };

  const toggleLayerExpanded = (layerId: string) => {
    setExpandedLayers(prev => {
      const next = new Set(prev);
      if (next.has(layerId)) next.delete(layerId);
      else next.add(layerId);
      return next;
    });
  };

  // ── Pin actions ─────────────────────────────────────────────────
  const deletePin = (pinId: string) => {
    const target = pins.find((p) => p.id === pinId);
    const label = target?.label || 'this pin';
    setConfirmDialog({
      title: 'DELETE PIN',
      message: `Delete pin "${label}"?\n\nThis cannot be undone.`,
      confirmLabel: 'DELETE',
      onConfirm: async () => {
        setConfirmDialog(null);
        try {
          await fetch(`${API_BASE}/api/ai/pins/${pinId}`, { method: 'DELETE' });
          await refreshData();
        } catch {}
      },
    });
  };

  // ── Near Me ──────────────────────────────────────────────────────
  const fetchNearMe = async () => {
    if (!navigator.geolocation) {
      setError('Geolocation not available');
      return;
    }
    setBusy(true);
    try {
      const pos = await new Promise<GeolocationPosition>((resolve, reject) =>
        navigator.geolocation.getCurrentPosition(resolve, reject, { timeout: 10000 }),
      );
      const { latitude: lat, longitude: lng } = pos.coords;
      const resp = await fetch(
        `${API_BASE}/api/ai/news-near?lat=${lat}&lng=${lng}&radius=${nearMeRadius}`,
      );
      if (!resp.ok) throw new Error(`${resp.status}`);
      setNearMeResults(await resp.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Near Me failed');
    }
    setBusy(false);
  };

  // ── Satellite imagery search ─────────────────────────────────────
  const handleLocationLookup = async () => {
    const q = satLocationQuery.trim();
    if (!q) return;
    setSatGeocoding(true);
    try {
      const resp = await fetch(`${API_BASE}/api/geocode/search?q=${encodeURIComponent(q)}&limit=1`);
      if (!resp.ok) throw new Error(`${resp.status}`);
      const data = await resp.json();
      const first = data.results?.[0];
      if (first && typeof first.lat === 'number' && typeof first.lng === 'number') {
        setSatLat(first.lat.toFixed(5));
        setSatLng(first.lng.toFixed(5));
        // Auto-search imagery at the resolved location
        setSatSearching(true);
        setSatScenes([]);
        try {
          const imgs = await fetchSatelliteImages(first.lat, first.lng, 3);
          setSatScenes(imgs.scenes || []);
          if (!imgs.scenes?.length) setError('No scenes found for this location');
        } catch (err) {
          setError(err instanceof Error ? err.message : 'Satellite search failed');
        }
        setSatSearching(false);
      } else {
        setError(`Location "${q}" not found`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Geocoding failed');
    }
    setSatGeocoding(false);
  };

  const handleSatSearch = async () => {
    const lat = parseFloat(satLat);
    const lng = parseFloat(satLng);
    if (isNaN(lat) || isNaN(lng)) {
      setError('Enter valid lat/lng coordinates');
      return;
    }
    setSatSearching(true);
    setSatScenes([]);
    setError(null);
    try {
      const resp = await fetchSatelliteImages(lat, lng, 3);
      setSatScenes(resp.scenes || []);
      if (!resp.scenes?.length) setError('No scenes found for this location');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Satellite search failed');
    }
    setSatSearching(false);
  };

  // ── Render ───────────────────────────────────────────────────────
  return (
    <div className="flex flex-col select-none">
      {/* Header */}
      <div
        onClick={() => setIsMinimized(!isMinimized)}
        className="flex items-center justify-between px-3 py-2.5 cursor-pointer hover:bg-violet-950/40 transition-colors border-b border-violet-500/30 bg-violet-950/20"
      >
        <div className="flex items-center gap-2">
          <Brain size={16} className="text-violet-400" />
          <span className="text-[12px] text-violet-400 font-mono tracking-widest font-bold">
            AI INTEL
          </span>
          {totalPins > 0 && (
            <span className="text-[11px] font-mono px-1.5 py-0.5 bg-violet-500/20 border border-violet-500/40 text-violet-300">
              {totalPins}
            </span>
          )}
          {error && (
            <span className="text-[11px] font-mono px-1.5 py-0.5 bg-red-500/20 text-red-400">
              OFFLINE
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {isMinimized ? (
            <Plus size={16} className="text-violet-400" />
          ) : (
            <Minus size={16} className="text-violet-400" />
          )}
        </div>
      </div>

      <AnimatePresence>
        {!isMinimized && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden border-x border-b border-violet-500/20 bg-[var(--bg-elevated)]"
          >
            <div className="p-3 space-y-3 max-h-[60vh] overflow-y-auto styled-scrollbar">

              {/* ── Connect OpenClaw Button ──────────────────────── */}
              <button
                onClick={(e) => { e.stopPropagation(); setShowConnect(true); }}
                className="w-full flex items-center justify-center gap-2 py-2 text-[12px] font-mono tracking-wider border transition-all bg-violet-600/15 border-violet-500/30 text-violet-400 hover:bg-violet-600/25 hover:text-violet-300 hover:border-violet-500/50"
                title="Connect your OpenClaw AI agent"
              >
                <Link2 size={14} />
                CONNECT OPENCLAW
              </button>

              {/* ── Pin Placement Button ─────────────────────────── */}
              <button
                type="button"
                onClick={() => onPinPlacementModeChange?.(!pinPlacementMode)}
                className={`w-full flex items-center justify-center gap-2 py-2 text-[12px] font-mono tracking-wider border transition-all ${
                  pinPlacementMode
                    ? 'bg-amber-600/25 border-amber-500/50 text-amber-300 animate-pulse'
                    : 'bg-violet-600/10 border-violet-500/20 text-violet-300 hover:bg-violet-600/20 hover:border-violet-500/40'
                }`}
              >
                <Crosshair size={14} />
                {pinPlacementMode ? 'CLICK MAP TO PLACE PIN...' : 'PLACE PIN ON MAP'}
              </button>

              {/* ── Pin Layers ──────────────────────────────────── */}
              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5">
                    <MapPin size={12} className="text-violet-400" />
                    <span className="text-[11px] font-mono text-violet-400 tracking-widest">
                      PIN LAYERS
                    </span>
                    <span className="text-[10px] font-mono text-[var(--text-muted)]">
                      ({layers.length})
                    </span>
                  </div>
                  <button
                    type="button"
                    onClick={() => setShowNewLayer(!showNewLayer)}
                    className="text-[10px] font-mono text-violet-400/70 hover:text-violet-300 transition-colors flex items-center gap-1"
                  >
                    <Plus size={10} /> NEW
                  </button>
                </div>

                {/* New layer form */}
                {showNewLayer && (
                  <div className="space-y-1">
                    <div className="flex gap-1">
                      <input
                        type="text"
                        value={newLayerName}
                        onChange={(e) => setNewLayerName(e.target.value)}
                        onKeyDown={(e) => e.key === 'Enter' && handleCreateLayer()}
                        placeholder="Layer name..."
                        autoFocus
                        className="flex-1 px-2 py-1.5 text-[12px] font-mono bg-[var(--bg-primary)] border border-violet-500/30 text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:border-violet-500/50 outline-none"
                      />
                      <button
                        type="button"
                        onClick={handleCreateLayer}
                        disabled={busy || !newLayerName.trim()}
                        className="px-3 py-1.5 text-[11px] font-mono bg-violet-600/30 border border-violet-500/50 text-violet-300 hover:bg-violet-600/50 transition-colors disabled:opacity-40"
                      >
                        ADD
                      </button>
                    </div>
                    <div className="flex items-center gap-1">
                      <Rss size={10} className="text-emerald-400/50 flex-shrink-0" />
                      <input
                        type="text"
                        value={newLayerFeedUrl}
                        onChange={(e) => setNewLayerFeedUrl(e.target.value)}
                        onKeyDown={(e) => e.key === 'Enter' && handleCreateLayer()}
                        placeholder="Feed URL (optional GeoJSON/JSON)..."
                        className="flex-1 px-2 py-1 text-[11px] font-mono bg-[var(--bg-primary)] border border-emerald-500/20 text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:border-emerald-500/40 outline-none"
                      />
                    </div>
                  </div>
                )}

                {/* Layer list */}
                {layers.length === 0 && !showNewLayer && (
                  <div className="text-[11px] font-mono text-[var(--text-muted)] px-2 py-3 text-center border border-dashed border-[var(--border-primary)]">
                    No layers yet. Create one or let OpenClaw add them.
                  </div>
                )}

                <div className="space-y-0.5">
                  {layers.map((layer) => {
                    const isExpanded = expandedLayers.has(layer.id);
                    const layerPins = pins.filter((p) => p.layer_id === layer.id);
                    return (
                      <div key={layer.id} className="border border-[var(--border-primary)]">
                        {/* Layer header */}
                        <div className="flex items-center gap-1.5 px-2 py-1.5 hover:bg-violet-500/5 transition-colors">
                          {/* Expand/collapse */}
                          <button
                            type="button"
                            onClick={() => toggleLayerExpanded(layer.id)}
                            className="text-[var(--text-muted)] hover:text-violet-400 transition-colors"
                          >
                            {isExpanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                          </button>

                          {/* Color dot */}
                          <div
                            className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                            style={{ backgroundColor: layer.color }}
                          />

                          {/* Name + count */}
                          <button
                            type="button"
                            onClick={() => toggleLayerExpanded(layer.id)}
                            className="flex-1 text-left min-w-0"
                          >
                            <span className="text-[11px] font-mono text-[var(--text-primary)] truncate block">
                              {layer.name}
                            </span>
                          </button>
                          <span className="text-[9px] font-mono text-[var(--text-muted)]">
                            {layer.pin_count}
                          </span>

                          {/* Source badge */}
                          {layer.source === 'openclaw' && (
                            <span className="text-[11px] font-mono text-violet-400/60 px-1 border border-violet-500/20 rounded-sm">
                              AI
                            </span>
                          )}

                          {/* Feed badge + refresh */}
                          {layer.feed_url && (
                            <>
                              <span
                                className="text-[11px] font-mono text-emerald-400/60 px-1 border border-emerald-500/20 rounded-sm flex items-center gap-0.5"
                                title={`Feed: ${layer.feed_url}\nInterval: ${layer.feed_interval}s${layer.feed_last_fetched ? `\nLast: ${new Date(layer.feed_last_fetched * 1000).toLocaleTimeString()}` : ''}`}
                              >
                                <Rss size={8} />
                                FEED
                              </span>
                              <button
                                type="button"
                                onClick={(e) => { e.stopPropagation(); handleRefreshFeed(layer.id); }}
                                className="text-emerald-400/40 hover:text-emerald-400 transition-colors"
                                title="Refresh feed now"
                              >
                                <RefreshCw size={10} />
                              </button>
                            </>
                          )}

                          {/* Visibility toggle */}
                          <button
                            type="button"
                            onClick={() => handleToggleLayerVisibility(layer.id, layer.visible)}
                            className="text-[var(--text-muted)] hover:text-violet-400 transition-colors"
                            title={layer.visible ? 'Hide layer' : 'Show layer'}
                          >
                            {layer.visible ? <Eye size={12} /> : <EyeOff size={12} />}
                          </button>

                          {/* Delete */}
                          <button
                            type="button"
                            onClick={() => handleDeleteLayer(layer.id)}
                            className="text-red-400/40 hover:text-red-400 transition-colors"
                            title="Delete layer and all its pins"
                          >
                            <Trash2 size={10} />
                          </button>
                        </div>

                        {/* Expanded: show pins */}
                        {isExpanded && layerPins.length > 0 && (
                          <div className="border-t border-[var(--border-primary)] bg-black/20">
                            {layerPins.slice(0, 30).map((pin) => (
                              <div
                                key={pin.id}
                                className="flex items-center justify-between px-3 py-1 hover:bg-violet-500/5 transition-colors group cursor-pointer"
                                onClick={() => onFlyTo?.(pin.lat, pin.lng)}
                              >
                                <div className="flex items-center gap-1.5 min-w-0">
                                  <div
                                    className="w-1.5 h-1.5 rounded-full flex-shrink-0"
                                    style={{ backgroundColor: pin.color }}
                                  />
                                  <span className="text-[10px] font-mono text-[var(--text-secondary)] truncate">
                                    {pin.label}
                                  </span>
                                  {pin.entity_attachment && (
                                    <span className="text-[11px] font-mono text-cyan-400/60 px-1 border border-cyan-500/20 rounded-sm">
                                      TRACKING
                                    </span>
                                  )}
                                  {pin.source === 'openclaw' && (
                                    <span className="text-[11px] font-mono text-violet-400/50">AI</span>
                                  )}
                                </div>
                                <button
                                  type="button"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    deletePin(pin.id);
                                  }}
                                  className="opacity-0 group-hover:opacity-100 text-red-400/50 hover:text-red-400 transition-all"
                                  title="Delete pin"
                                >
                                  <X size={10} />
                                </button>
                              </div>
                            ))}
                            {layerPins.length > 30 && (
                              <div className="text-[9px] font-mono text-[var(--text-muted)] text-center py-1 border-t border-[var(--border-primary)]">
                                + {layerPins.length - 30} more
                              </div>
                            )}
                          </div>
                        )}
                        {isExpanded && layerPins.length === 0 && (
                          <div className="border-t border-[var(--border-primary)] bg-black/20 px-3 py-2">
                            <span className="text-[10px] font-mono text-[var(--text-muted)]">
                              No pins in this layer
                            </span>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>

                {/* Ungrouped pins (no layer_id) */}
                {pins.filter(p => !p.layer_id).length > 0 && (
                  <div className="border border-[var(--border-primary)] mt-1">
                    <div className="px-2 py-1.5 text-[10px] font-mono text-[var(--text-muted)] tracking-widest">
                      UNGROUPED ({pins.filter(p => !p.layer_id).length})
                    </div>
                    <div className="border-t border-[var(--border-primary)] bg-black/20">
                      {pins.filter(p => !p.layer_id).slice(0, 20).map((pin) => (
                        <div
                          key={pin.id}
                          className="flex items-center justify-between px-3 py-1 hover:bg-violet-500/5 transition-colors group cursor-pointer"
                          onClick={() => onFlyTo?.(pin.lat, pin.lng)}
                        >
                          <div className="flex items-center gap-1.5 min-w-0">
                            <div
                              className="w-1.5 h-1.5 rounded-full flex-shrink-0"
                              style={{ backgroundColor: pin.color }}
                            />
                            <span className="text-[10px] font-mono text-[var(--text-secondary)] truncate">
                              {pin.label}
                            </span>
                          </div>
                          <button
                            type="button"
                            onClick={(e) => { e.stopPropagation(); deletePin(pin.id); }}
                            className="opacity-0 group-hover:opacity-100 text-red-400/50 hover:text-red-400 transition-all"
                            title="Delete pin"
                          >
                            <X size={10} />
                          </button>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              {/* ── Near Me ─────────────────────────────────────── */}
              <div className="space-y-1.5">
                <div className="flex items-center gap-1.5">
                  <Navigation size={12} className="text-emerald-400" />
                  <span className="text-[11px] font-mono text-emerald-400 tracking-widest">NEAR ME</span>
                </div>
                <div className="flex gap-1">
                  {[50, 100, 500, 1000].map((r) => (
                    <button
                      key={r}
                      type="button"
                      onClick={() => setNearMeRadius(r)}
                      className={`flex-1 px-1 py-1 text-[10px] font-mono border transition-colors ${
                        nearMeRadius === r
                          ? 'border-emerald-500/50 bg-emerald-500/20 text-emerald-300'
                          : 'border-[var(--border-primary)] text-[var(--text-muted)] hover:text-emerald-400'
                      }`}
                    >
                      {r}mi
                    </button>
                  ))}
                </div>
                <button
                  type="button"
                  onClick={fetchNearMe}
                  disabled={busy}
                  className="w-full py-2 text-[11px] font-mono tracking-wider bg-emerald-600/20 border border-emerald-500/40 text-emerald-300 hover:bg-emerald-600/40 transition-colors disabled:opacity-40 flex items-center justify-center gap-1.5"
                >
                  <Navigation size={12} />
                  SCAN NEARBY ({nearMeRadius}mi)
                </button>
                {nearMeResults && (
                  <div className="space-y-0.5 max-h-32 overflow-y-auto">
                    {(nearMeResults.gdelt || []).slice(0, 3).map((g: any, i: number) => (
                      <div key={i} className="text-[10px] font-mono text-amber-300 px-2 py-1 bg-amber-500/10 border border-amber-500/20">
                        {g.name} ({g.count} events) -- {g.distance_miles}mi
                      </div>
                    ))}
                    {(nearMeResults.news || []).slice(0, 3).map((n: any, i: number) => (
                      <div key={i} className="text-[10px] font-mono text-sky-300 px-2 py-1 bg-sky-500/10 border border-sky-500/20">
                        {n.title?.slice(0, 60)} -- {n.distance_miles}mi
                      </div>
                    ))}
                    {!nearMeResults.gdelt?.length && !nearMeResults.news?.length && (
                      <div className="text-[10px] font-mono text-emerald-400/50 px-2">
                        All clear -- nothing notable within {nearMeRadius}mi
                      </div>
                    )}
                  </div>
                )}
              </div>

              {/* ── Satellite Imagery ──────────────────────────── */}
              <div className="space-y-1.5">
                <div className="flex items-center gap-1.5">
                  <Globe size={12} className="text-sky-400" />
                  <span className="text-[11px] font-mono text-sky-400 tracking-widest">SATELLITE IMAGERY</span>
                </div>
                {/* Location lookup (place name) */}
                <div className="flex gap-1">
                  <input
                    type="text"
                    value={satLocationQuery}
                    onChange={(e) => setSatLocationQuery(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handleLocationLookup()}
                    placeholder="Search location (e.g. Tehran, Kyiv)..."
                    className="flex-1 px-2 py-1.5 text-[11px] font-mono bg-[var(--bg-primary)] border border-sky-500/20 text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:border-sky-500/50 outline-none"
                  />
                  <button
                    type="button"
                    onClick={handleLocationLookup}
                    disabled={satGeocoding || !satLocationQuery.trim()}
                    className="px-2 py-1.5 text-[11px] font-mono bg-sky-600/20 border border-sky-500/40 text-sky-300 hover:bg-sky-600/40 transition-colors disabled:opacity-40"
                    title="Look up location and search imagery"
                  >
                    {satGeocoding ? '...' : 'GO'}
                  </button>
                </div>
                <div className="text-[9px] font-mono text-[var(--text-muted)] text-center">
                  — or enter coordinates —
                </div>
                <div className="flex gap-1">
                  <input
                    type="text"
                    value={satLat}
                    onChange={(e) => setSatLat(e.target.value)}
                    placeholder="Lat"
                    className="flex-1 px-2 py-1.5 text-[11px] font-mono bg-[var(--bg-primary)] border border-sky-500/20 text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:border-sky-500/50 outline-none"
                  />
                  <input
                    type="text"
                    value={satLng}
                    onChange={(e) => setSatLng(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handleSatSearch()}
                    placeholder="Lng"
                    className="flex-1 px-2 py-1.5 text-[11px] font-mono bg-[var(--bg-primary)] border border-sky-500/20 text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:border-sky-500/50 outline-none"
                  />
                </div>
                <button
                  type="button"
                  onClick={handleSatSearch}
                  disabled={satSearching || !satLat.trim() || !satLng.trim()}
                  className="w-full py-2 text-[11px] font-mono tracking-wider bg-sky-600/20 border border-sky-500/40 text-sky-300 hover:bg-sky-600/40 transition-colors disabled:opacity-40 flex items-center justify-center gap-1.5"
                >
                  <Globe size={12} />
                  {satSearching ? 'SEARCHING...' : 'SEARCH SENTINEL-2'}
                </button>

                {/* Error message (inline) */}
                {error && !satSearching && satScenes.length === 0 && (
                  <div className="text-[10px] font-mono text-red-400/80 bg-red-500/10 border border-red-500/20 px-2 py-1.5">
                    {error}
                  </div>
                )}

                {/* Results */}
                {satScenes.length > 0 && (
                  <div className="space-y-1.5 max-h-64 overflow-y-auto">
                    {satScenes.map((scene) => (
                      <div
                        key={scene.scene_id}
                        className="border border-sky-500/20 bg-black/30 overflow-hidden"
                      >
                        {/* Thumbnail */}
                        {scene.thumbnail_url && (
                          <a href={scene.fullres_url || scene.thumbnail_url} target="_blank" rel="noopener noreferrer">
                            <img
                              src={scene.thumbnail_url}
                              alt={scene.scene_id}
                              className="w-full h-24 object-cover hover:opacity-80 transition-opacity"
                              loading="lazy"
                            />
                          </a>
                        )}
                        {/* Info bar */}
                        <div className="flex items-center justify-between px-2 py-1.5">
                          <div className="min-w-0">
                            <div className="text-[10px] font-mono text-sky-300 truncate">
                              {scene.platform} — {scene.datetime ? new Date(scene.datetime).toLocaleDateString() : 'N/A'}
                            </div>
                            <div className="text-[9px] font-mono text-[var(--text-muted)]">
                              Cloud: {scene.cloud_cover != null ? `${Math.round(scene.cloud_cover)}%` : 'N/A'}
                            </div>
                          </div>
                          <div className="flex items-center gap-1 flex-shrink-0">
                            {scene.bbox && scene.bbox.length >= 4 && (
                              <button
                                type="button"
                                onClick={() => {
                                  const centerLat = (scene.bbox[1] + scene.bbox[3]) / 2;
                                  const centerLng = (scene.bbox[0] + scene.bbox[2]) / 2;
                                  onFlyTo?.(centerLat, centerLng);
                                }}
                                className="px-2 py-0.5 text-[9px] font-mono bg-sky-600/30 border border-sky-500/40 text-sky-300 hover:bg-sky-600/50 transition-colors"
                              >
                                SHOW ON MAP
                              </button>
                            )}
                            {scene.fullres_url && (
                              <a
                                href={scene.fullres_url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="px-2 py-0.5 text-[9px] font-mono bg-violet-600/20 border border-violet-500/30 text-violet-300 hover:bg-violet-600/40 transition-colors"
                              >
                                FULL RES
                              </a>
                            )}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* ── Refresh ─────────────────────────────────────── */}
              <button
                type="button"
                onClick={refreshData}
                className="w-full py-1.5 text-[10px] font-mono tracking-wider border border-[var(--border-primary)] text-[var(--text-muted)] hover:text-violet-400 hover:border-violet-500/40 transition-colors flex items-center justify-center gap-1"
                title="Refresh AI Intel"
              >
                <RefreshCw size={10} /> REFRESH
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ── Connect OpenClaw Modal (Portal) ──────────────────── */}
      {showConnect && ReactDOM.createPortal(
        <div
          className="fixed inset-0 z-[9999] flex items-center justify-center"
          onClick={() => setShowConnect(false)}
        >
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" />
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 20 }}
            transition={{ duration: 0.2, ease: 'easeOut' }}
            className="relative w-[560px] max-w-[90vw] max-h-[85vh] overflow-y-auto bg-[#0c0c14] border border-violet-500/40 shadow-2xl shadow-violet-900/30"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-6 py-4 border-b border-violet-500/30 bg-violet-950/20 sticky top-0 z-10">
              <div className="flex items-center gap-3">
                <Link2 size={18} className="text-violet-400" />
                <span className="text-sm font-mono text-violet-400 tracking-widest font-bold uppercase">Connect OpenClaw Agent</span>
              </div>
              <button
                onClick={() => setShowConnect(false)}
                className="text-gray-500 hover:text-white transition-colors p-1"
                title="Close"
              >
                <X size={18} />
              </button>
            </div>
            <ConnectModalBody apiEndpoint={apiEndpoint} handleCopy={handleCopy} copied={copied} />
          </motion.div>
        </div>,
        document.body,
      )}

      {/* In-app confirmation dialog */}
      <ConfirmDialog
        open={!!confirmDialog}
        title={confirmDialog?.title || ''}
        message={confirmDialog?.message || ''}
        confirmLabel={confirmDialog?.confirmLabel}
        danger
        onConfirm={() => confirmDialog?.onConfirm()}
        onCancel={() => setConfirmDialog(null)}
      />
    </div>
  );
}
