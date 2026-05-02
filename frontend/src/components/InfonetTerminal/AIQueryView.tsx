'use client';

import React, { useState, useRef, useEffect, useCallback } from 'react';
import { ArrowLeft, Send, MapPin, Loader2, Brain, Trash2, Sparkles, Link2, Copy, Check, X } from 'lucide-react';
import { getBackendEndpoint } from '@/lib/backendEndpoint';

interface AIMessage {
  role: 'user' | 'ai' | 'system';
  content: string;
  timestamp: number;
  pins?: { lat: number; lng: number; label: string }[];
}

interface AIQueryViewProps {
  onBack: () => void;
}

const EXAMPLE_QUERIES = [
  'What military flights are active right now?',
  'Show me recent earthquakes over magnitude 4',
  'What ships are near the Taiwan Strait?',
  'Give me a threat level assessment',
  'What are the top prediction market movers?',
  'Are there any correlation alerts?',
  'Show me satellite imagery of Tehran',
  'Get news from Ukraine',
  'What SIGINT activity is happening?',
  'Place a pin on every military base near Denver',
];

export default function AIQueryView({ onBack }: AIQueryViewProps) {
  const [messages, setMessages] = useState<AIMessage[]>([
    {
      role: 'system',
      content: `🌍📡 SHADOWBROKER AI CO-PILOT ONLINE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Connected to ShadowBroker OSINT platform.
I can query telemetry, place pins on the map,
search satellite imagery, aggregate news,
and access all 30+ data layers.

Type a question or command to get started.
Use "help" to see capabilities.`,
      timestamp: Date.now(),
    },
  ]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [showConnect, setShowConnect] = useState(false);
  const [copied, setCopied] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const apiEndpoint = getBackendEndpoint();

  const handleCopy = useCallback((text: string) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const processQuery = useCallback(async (query: string) => {
    const lowerQuery = query.toLowerCase().trim();

    // Handle built-in commands
    if (lowerQuery === 'help') {
      return {
        content: `🌍🔍 AVAILABLE COMMANDS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━
TELEMETRY QUERIES:
  • "military flights"   — Active military aircraft
  • "ships"              — Tracked vessels
  • "satellites"         — Orbital assets
  • "earthquakes"        — Recent seismic activity
  • "threat level"       — Current threat assessment
  • "prediction markets" — Market consensus data
  • "sigint"             — RF signal intelligence totals
  • "correlations"       — Cross-layer alerts

INTELLIGENCE:
  • "report"      — Full intelligence report
  • "summary"     — Quick telemetry summary
  • "news summary" — AI news brief with top stories & trends
  • "correlations" — Explain cross-layer correlation alerts
  • "news [place]" — News near a location
  • "satellite images [place]" — Sentinel-2 imagery

PIN COMMANDS:
  • "pin [lat] [lng] [label]" — Place a pin
  • "clear pins"              — Clear all AI pins
  • "list pins"               — Show current pins

TIME MACHINE:
  • "snapshot"         — Take a telemetry snapshot
  • "snapshots"        — List available snapshots
  • "timemachine config" — View snapshot settings

SYSTEM:
  • "status"  — AI system status
  • "clear"   — Clear chat history
  • "help"    — This message`,
      };
    }

    if (lowerQuery === 'clear') {
      setMessages([{
        role: 'system',
        content: '🌍✅ Chat cleared. Ready for queries.',
        timestamp: Date.now(),
      }]);
      return null;
    }

    // API queries
    try {
      const base = '/api/ai';

      if (lowerQuery === 'status') {
        const resp = await fetch(`${base}/status`);
        const data = await resp.json();
        return {
          content: `🌍✅ SHADOWBROKER AI STATUS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━
Status: ${data.status || 'ONLINE'}
Capabilities: ${(data.capabilities || []).join(', ')}
Pin Count: ${data.pin_count ?? 'N/A'}
Version: ${data.version || '1.0'}`,
        };
      }

      if (lowerQuery === 'summary' || lowerQuery === 'quick summary') {
        const resp = await fetch(`${base}/summary`);
        const data = await resp.json();
        const counts = data.layer_counts || {};
        const lines = Object.entries(counts)
          .filter(([, v]) => (v as number) > 0)
          .map(([k, v]) => `  • ${k}: ${v}`)
          .join('\n');
        return {
          content: `🌍📡 TELEMETRY SUMMARY:
━━━━━━━━━━━━━━━━━━━━━━━━━━━
${lines || '  No active telemetry data.'}

Threat Level: ${data.threat_level || 'N/A'}
SIGINT Totals: ${JSON.stringify(data.sigint_totals || {}, null, 0)}`,
        };
      }

      if (lowerQuery === 'report' || lowerQuery === 'intelligence report') {
        const resp = await fetch(`${base}/report`);
        const data = await resp.json();
        return {
          content: `🌍🛰️ INTELLIGENCE REPORT:
━━━━━━━━━━━━━━━━━━━━━━━━━━━
${data.report || JSON.stringify(data, null, 2)}`,
        };
      }

      if (lowerQuery.startsWith('pin ')) {
        const parts = lowerQuery.replace('pin ', '').split(/\s+/);
        if (parts.length >= 3) {
          const lat = parseFloat(parts[0]);
          const lng = parseFloat(parts[1]);
          const label = parts.slice(2).join(' ');
          if (!isNaN(lat) && !isNaN(lng)) {
            const resp = await fetch(`${base}/pins`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ lat, lng, label, category: 'research' }),
            });
            const data = await resp.json();
            return {
              content: `🌍📌 SHADOWBROKER PINNING:
Pin placed successfully!
  📍 ${lat.toFixed(4)}°, ${lng.toFixed(4)}°
  🏷️ ${label}
  🆔 ${data.pin_id || 'assigned'}`,
              pins: [{ lat, lng, label }],
            };
          }
        }
        return { content: '❌ Usage: pin [latitude] [longitude] [label]' };
      }

      if (lowerQuery === 'list pins' || lowerQuery === 'pins') {
        const resp = await fetch(`${base}/pins`);
        const data = await resp.json();
        const pinList = (data.pins || [])
          .slice(0, 20)
          .map((p: { label: string; lat: number; lng: number; category: string }) =>
            `  📍 ${p.label} (${p.lat.toFixed(2)}°, ${p.lng.toFixed(2)}°) [${p.category}]`
          )
          .join('\n');
        return {
          content: `🌍📌 AI INTEL PINS (${data.count || 0}):
━━━━━━━━━━━━━━━━━━━━━━━━━━━
${pinList || '  No pins placed yet.'}`,
        };
      }

      if (lowerQuery === 'clear pins') {
        await fetch(`${base}/pins`, { method: 'DELETE' });
        return { content: '🌍❌ SHADOWBROKER CLEARING:\nAll AI intel pins cleared.' };
      }

      if (lowerQuery === 'snapshot' || lowerQuery === 'take snapshot') {
        const resp = await fetch(`${base}/timemachine/snapshot`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({}),
        });
        const data = await resp.json();
        return {
          content: `🌍🕰️ SHADOWBROKER TIMEMACHINE:
Snapshot taken!
  🆔 ${data.snapshot_id}
  🕐 ${data.timestamp}
  📊 Layers: ${(data.layers || []).join(', ')}`,
        };
      }

      if (lowerQuery === 'snapshots' || lowerQuery === 'list snapshots') {
        const resp = await fetch(`${base}/timemachine/snapshots`);
        const data = await resp.json();
        const snapList = (data.snapshots || [])
          .slice(0, 10)
          .map((s: { id: string; timestamp: string; layers: string[] }) =>
            `  🗂️ ${s.id} — ${s.timestamp} (${s.layers.length} layers)`
          )
          .join('\n');
        return {
          content: `🌍🕰️ TIME MACHINE SNAPSHOTS (${data.count || 0}):
━━━━━━━━━━━━━━━━━━━━━━━━━━━
${snapList || '  No snapshots taken yet.'}`,
        };
      }

      if (lowerQuery === 'timemachine config' || lowerQuery === 'tm config') {
        const resp = await fetch(`${base}/timemachine/config`);
        const data = await resp.json();
        const cfg = data.config || {};
        return {
          content: `🌍🕰️ TIME MACHINE CONFIG:
━━━━━━━━━━━━━━━━━━━━━━━━━━━
Preset: ${cfg.preset || 'active'}

High-Frequency (${cfg.profiles?.high_freq?.interval_minutes || 15}min):
  ${(cfg.profiles?.high_freq?.layers || []).join(', ')}

Standard (${cfg.profiles?.standard?.interval_minutes || 120}min):
  ${(cfg.profiles?.standard?.layers || []).join(', ')}

Available presets: paranoid (5min), active (15min), casual (1hr), minimal (6hr)`,
        };
      }

      if (lowerQuery === 'news summary' || lowerQuery === 'news brief' || lowerQuery === 'ai brief') {
        const resp = await fetch(`${base}/news/summary`);
        const data = await resp.json();
        const topStories = (data.top_stories || [])
          .slice(0, 5)
          .map((s: { risk_score: number; title: string; source: string }) =>
            `  [${s.risk_score}/10] ${s.title} — ${s.source}`
          )
          .join('\n');
        const keywords = (data.keywords || [])
          .slice(0, 8)
          .map((kw: { word: string; count: number }) => `${kw.word}(${kw.count})`)
          .join(', ');
        const td = data.threat_distribution || {};
        return {
          content: `🌍📰 AI INTELLIGENCE BRIEF:
━━━━━━━━━━━━━━━━━━━━━━━━━━━
${data.summary || 'No data available.'}

TOP STORIES:
${topStories || '  None available.'}

TRENDING: ${keywords || 'N/A'}

THREAT DISTRIBUTION:
  🔴 CRITICAL: ${td.CRITICAL || 0}  🟠 HIGH: ${td.HIGH || 0}  🟡 ELEVATED: ${td.ELEVATED || 0}
  🔵 MODERATE: ${td.MODERATE || 0}  🟢 LOW: ${td.LOW || 0}`,
        };
      }

      if (lowerQuery === 'correlations' || lowerQuery === 'explain correlations' || lowerQuery === 'correlation alerts') {
        const resp = await fetch(`${base}/correlations/explain`);
        const data = await resp.json();
        if (!data.count) {
          return { content: '🌍⚡ CORRELATIONS:\nNo cross-layer correlation alerts are currently active.' };
        }
        const alerts = (data.explanations || [])
          .slice(0, 8)
          .map((e: { label: string; severity_text: string; driver_summary: string; implications: string[]; recommended_action: string; lat: number; lng: number }) =>
            `━━━━━━━━━━━━━━━━━━━━━━━━━━━
📍 ${e.label}
   Location: ${e.lat.toFixed(2)}°, ${e.lng.toFixed(2)}°
   Severity: ${e.severity_text}
   Indicators: ${e.driver_summary}
   Assessment: ${e.implications?.[0] || 'N/A'}
   Action: ${e.recommended_action}`
          )
          .join('\n');
        return {
          content: `🌍⚡ CORRELATION ANALYSIS (${data.count} alerts):
${data.summary || ''}

${alerts}`,
        };
      }

      // Generic fallback — try summary
      return {
        content: `🌍🔍 SHADOWBROKER SEARCHING:
Processing query: "${query}"

I can directly execute these commands:
  • summary / report / status
  • pin [lat] [lng] [label]
  • list pins / clear pins
  • snapshot / snapshots / timemachine config
  • help

For complex queries (natural language research, web search,
multi-step investigations), connect OpenClaw with an LLM
provider to unlock full agent capabilities.

Type "help" for the full command list.`,
      };
    } catch (error) {
      return {
        content: `🌍⚠️ SHADOWBROKER WARNING:
Query failed: ${error instanceof Error ? error.message : 'Unknown error'}
Make sure the ShadowBroker backend is running on localhost:8000.`,
      };
    }
  }, []);

  const handleSubmit = useCallback(async () => {
    const query = input.trim();
    if (!query || isLoading) return;

    setInput('');
    setMessages(prev => [...prev, { role: 'user', content: query, timestamp: Date.now() }]);
    setIsLoading(true);

    const result = await processQuery(query);
    if (result) {
      setMessages(prev => [...prev, {
        role: 'ai',
        content: result.content,
        timestamp: Date.now(),
        pins: result.pins,
      }]);
    }

    setIsLoading(false);
  }, [input, isLoading, processQuery]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <div className="h-full flex flex-col bg-[#0a0a0a] text-gray-300">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-purple-900/40 bg-purple-950/10 shrink-0">
        <div className="flex items-center gap-3">
          <button
            onClick={onBack}
            className="text-gray-500 hover:text-gray-300 transition-colors"
            title="Back to terminal"
          >
            <ArrowLeft size={18} />
          </button>
          <Brain size={18} className="text-purple-400" />
          <span className="text-sm tracking-[0.2em] text-purple-400 uppercase font-bold">
            AI Co-Pilot
          </span>
          <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse shadow-[0_0_6px_rgba(34,197,94,0.6)]" />
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowConnect(!showConnect)}
            className={`flex items-center gap-1.5 px-2.5 py-1 text-xs font-bold tracking-wider uppercase transition-all rounded-sm ${
              showConnect
                ? 'bg-purple-900/40 border border-purple-500/50 text-purple-300'
                : 'bg-purple-900/20 border border-purple-800/30 text-purple-500 hover:bg-purple-900/30 hover:text-purple-300 hover:border-purple-600/40'
            }`}
            title="Connect your OpenClaw agent"
          >
            <Link2 size={13} />
            Connect OpenClaw
          </button>
          <button
            onClick={() => setMessages([{
              role: 'system',
              content: '🌍✅ Chat cleared. Ready for queries.',
              timestamp: Date.now(),
            }])}
            className="text-gray-600 hover:text-red-400 transition-colors"
            title="Clear chat"
          >
            <Trash2 size={14} />
          </button>
        </div>
      </div>

      {/* Connect OpenClaw Panel */}
      {showConnect && (
        <div className="border-b border-purple-900/40 bg-purple-950/15 px-4 py-4 shrink-0 overflow-y-auto max-h-[60vh]">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <Link2 size={14} className="text-purple-400" />
              <span className="text-sm font-bold tracking-wider text-purple-400 uppercase">Connect Your OpenClaw Agent</span>
            </div>
            <button onClick={() => setShowConnect(false)} className="text-gray-600 hover:text-gray-300 transition-colors">
              <X size={14} />
            </button>
          </div>

          <div className="space-y-3 text-sm font-mono">
            {/* API Endpoint */}
            <div>
              <div className="text-[11px] text-gray-500 uppercase tracking-widest mb-1">Your ShadowBroker API Endpoint</div>
              <div className="flex items-center gap-2">
                <code className="flex-1 bg-black/60 border border-purple-800/40 px-3 py-2 text-purple-300 text-sm rounded-sm select-all">
                  {apiEndpoint}
                </code>
                <button
                  onClick={() => handleCopy(apiEndpoint)}
                  className="p-2 bg-purple-900/30 border border-purple-800/40 text-purple-400 hover:bg-purple-900/50 hover:text-purple-200 transition-colors rounded-sm"
                  title="Copy endpoint"
                >
                  {copied ? <Check size={14} /> : <Copy size={14} />}
                </button>
              </div>
            </div>

            {/* Setup Instructions */}
            <div>
              <div className="text-[11px] text-gray-500 uppercase tracking-widest mb-1">Setup Instructions</div>
              <div className="bg-black/60 border border-gray-800/40 rounded-sm p-3 space-y-2 text-[13px] leading-relaxed">
                <p className="text-cyan-400 font-bold">Step 1: Install the ShadowBroker Skill</p>
                <p className="text-gray-400">Copy the <code className="text-purple-300 bg-purple-900/30 px-1">openclaw-skills/shadowbroker/</code> folder into your OpenClaw&apos;s skills directory.</p>

                <p className="text-cyan-400 font-bold mt-2">Step 2: Configure the API Endpoint</p>
                <p className="text-gray-400">Tell your OpenClaw agent to connect to:</p>
                <code className="block bg-purple-950/40 border border-purple-800/30 px-2 py-1 text-purple-300 text-[13px] rounded-sm">
                  SHADOWBROKER_URL={apiEndpoint}
                </code>

                <p className="text-cyan-400 font-bold mt-2">Step 3: Tell Your Agent</p>
                <p className="text-gray-400">Paste this into your OpenClaw&apos;s system prompt or instructions:</p>
                <div className="relative">
                  <pre className="bg-purple-950/40 border border-purple-800/30 px-2 py-2 text-[12px] text-purple-200 rounded-sm overflow-x-auto whitespace-pre-wrap">{`You have a skill called "shadowbroker" that connects you to a real-time global OSINT intelligence platform. Use it to:
- Query military flights, ships, satellites, SIGINT, earthquakes, and 30+ data layers
- Place intelligence pins on a live map
- Fetch satellite imagery from Sentinel-2
- Aggregate news by region via GDELT
- Take telemetry snapshots (Time Machine)
- Participate in the Wormhole encrypted mesh network
- Send/receive InfoNet messages via decentralized feed

API: ${apiEndpoint}
Skill docs: openclaw-skills/shadowbroker/SKILL.md`}</pre>
                  <button
                    onClick={() => handleCopy(`You have a skill called "shadowbroker" that connects you to a real-time global OSINT intelligence platform. Use it to:\n- Query military flights, ships, satellites, SIGINT, earthquakes, and 30+ data layers\n- Place intelligence pins on a live map\n- Fetch satellite imagery from Sentinel-2\n- Aggregate news by region via GDELT\n- Take telemetry snapshots (Time Machine)\n- Participate in the Wormhole encrypted mesh network\n- Send/receive InfoNet messages via decentralized feed\n\nAPI: ${apiEndpoint}\nSkill docs: openclaw-skills/shadowbroker/SKILL.md`)}
                    className="absolute top-1 right-1 p-1 bg-purple-900/50 text-purple-400 hover:text-purple-200 transition-colors rounded-sm"
                    title="Copy instructions"
                  >
                    {copied ? <Check size={12} /> : <Copy size={12} />}
                  </button>
                </div>
              </div>
            </div>

            {/* Available Capabilities */}
            <div>
              <div className="text-[11px] text-gray-500 uppercase tracking-widest mb-1">Available Capabilities</div>
              <div className="grid grid-cols-2 gap-1">
                {[
                  ['📡', 'Telemetry Queries'],
                  ['📌', 'Pin Placement'],
                  ['🛰️', 'Satellite Imagery'],
                  ['📰', 'News Aggregation'],
                  ['🕰️', 'Time Machine'],
                  ['🔗', 'Wormhole Network'],
                  ['📻', 'Meshtastic Radio'],
                  ['💉', 'Data Injection'],
                  ['⚡', 'Correlation Analysis'],
                  ['🚨', 'Alert Dispatch'],
                ].map(([emoji, label]) => (
                  <div key={label} className="flex items-center gap-1.5 text-[12px] text-gray-400 bg-black/30 border border-gray-800/30 px-2 py-1 rounded-sm">
                    <span>{emoji}</span>
                    <span>{label}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
        {messages.map((msg, i) => (
          <div
            key={i}
            className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`max-w-[85%] px-3 py-2.5 text-[13px] leading-relaxed whitespace-pre-wrap ${
                msg.role === 'user'
                  ? 'bg-purple-900/30 border border-purple-700/40 text-purple-100'
                  : msg.role === 'system'
                  ? 'bg-cyan-950/20 border border-cyan-900/30 text-cyan-300'
                  : 'bg-gray-900/40 border border-gray-800/40 text-gray-300'
              }`}
            >
              {msg.content}
              {msg.pins && msg.pins.length > 0 && (
                <div className="mt-2 pt-2 border-t border-gray-700/30 flex items-center gap-1.5 text-green-400 text-sm">
                  <MapPin size={12} />
                  <span>{msg.pins.length} pin(s) placed on map</span>
                </div>
              )}
            </div>
          </div>
        ))}
        {isLoading && (
          <div className="flex justify-start">
            <div className="bg-gray-900/40 border border-gray-800/40 px-3 py-2.5 flex items-center gap-2 text-sm text-gray-500">
              <Loader2 size={14} className="animate-spin" />
              <span>Processing query...</span>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Quick suggestions */}
      {messages.length <= 2 && (
        <div className="px-4 pb-2 flex flex-wrap gap-1.5">
          {EXAMPLE_QUERIES.slice(0, 4).map((q, i) => (
            <button
              key={i}
              onClick={() => { setInput(q); inputRef.current?.focus(); }}
              className="text-xs px-2.5 py-1 bg-purple-900/15 border border-purple-800/30 text-purple-400 hover:bg-purple-900/30 hover:text-purple-300 transition-colors flex items-center gap-1.5 rounded-sm"
            >
              <Sparkles size={10} />
              {q}
            </button>
          ))}
        </div>
      )}

      {/* Input */}
      <div className="shrink-0 px-4 py-3 border-t border-purple-900/30 bg-purple-950/5">
        <div className="flex items-center gap-2">
          <div className="flex-1 flex items-center bg-gray-900/40 border border-gray-700/40 focus-within:border-purple-700/60 transition-colors rounded-sm">
            <span className="text-purple-500 text-sm px-2.5 select-none">❯</span>
            <input
              ref={inputRef}
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask anything... (type 'help' for commands)"
              className="flex-1 bg-transparent border-none outline-none text-white text-sm py-2.5 pr-2 placeholder-gray-600 focus:ring-0"
              disabled={isLoading}
              spellCheck={false}
              autoComplete="off"
            />
          </div>
          <button
            onClick={handleSubmit}
            disabled={isLoading || !input.trim()}
            className="p-2 bg-purple-900/30 border border-purple-700/40 text-purple-400 hover:bg-purple-900/50 hover:text-purple-300 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
          >
            <Send size={14} />
          </button>
        </div>
      </div>
    </div>
  );
}
