'use client';

import React, { useState } from 'react';
import { Shield, RefreshCw, Trash2, Lock, Globe, MessageSquare, DoorOpen, User, Coins } from 'lucide-react';

type Domain = 'ROOT' | 'TRANSPORT' | 'DM_ALIAS' | 'GATE_SESSION' | 'GATE_PERSONA' | 'COIN';

interface DomainConfig {
  name: string;
  icon: React.ReactNode;
  visibility: 'NEVER PUBLIC' | 'PUBLIC' | 'SEMI-OBFUSCATED' | 'GATE-SCOPED' | 'NEVER LINKED';
  color: string;
}

const DOMAINS: Record<Domain, DomainConfig> = {
  ROOT: { name: 'ROOT', icon: <Lock size={14} />, visibility: 'NEVER PUBLIC', color: 'text-red-500' },
  TRANSPORT: { name: 'TRANSPORT', icon: <Globe size={14} />, visibility: 'PUBLIC', color: 'text-green-400' },
  DM_ALIAS: { name: 'DM_ALIAS', icon: <MessageSquare size={14} />, visibility: 'SEMI-OBFUSCATED', color: 'text-cyan-400' },
  GATE_SESSION: { name: 'GATE_SESSION', icon: <DoorOpen size={14} />, visibility: 'GATE-SCOPED', color: 'text-cyan-400' },
  GATE_PERSONA: { name: 'GATE_PERSONA', icon: <User size={14} />, visibility: 'GATE-SCOPED', color: 'text-cyan-400' },
  COIN: { name: 'COIN', icon: <Coins size={14} />, visibility: 'NEVER LINKED', color: 'text-red-400' },
};

export default function IdentityHUD({ currentDomain = 'TRANSPORT' }: { currentDomain?: Domain }) {
  const [isExpanded, setIsExpanded] = useState(false);
  const domain = DOMAINS[currentDomain];

  return (
    <div className="absolute bottom-4 right-4 z-[3] flex flex-col items-end">
      {isExpanded && (
        <div className="mb-2 w-64 bg-[#0a0a0a] border border-gray-800 p-3 shadow-[0_0_20px_rgba(6,182,212,0.1)]">
          <div className="flex justify-between items-center mb-3 border-b border-gray-800 pb-2">
            <span className="text-sm text-gray-500 uppercase tracking-widest font-bold">Identity Domains</span>
            <button onClick={() => setIsExpanded(false)} className="text-gray-500 hover:text-white">&times;</button>
          </div>

          <div className="space-y-2">
            {(Object.keys(DOMAINS) as Domain[]).map((key) => {
              const d = DOMAINS[key];
              const isActive = key === currentDomain;
              return (
                <div key={key} className={`p-2 border ${isActive ? 'border-cyan-500 bg-cyan-500/5' : 'border-gray-800 bg-gray-900/20'} flex items-center justify-between group`}>
                  <div className="flex items-center gap-2">
                    <span className={isActive ? 'text-cyan-400' : 'text-gray-600'}>{d.icon}</span>
                    <div>
                      <p className={`text-sm font-bold tracking-tighter ${isActive ? 'text-white' : 'text-gray-500'}`}>{d.name}</p>
                      <p className="text-[12px] text-gray-600 uppercase">{d.visibility}</p>
                    </div>
                  </div>
                  {isActive && (
                    <div className="flex gap-1">
                      <button title="Rotate Identity" className="p-1 text-gray-600 hover:text-cyan-400 transition-colors">
                        <RefreshCw size={10} />
                      </button>
                      <button title="Purge Domain Data" className="p-1 text-gray-600 hover:text-red-400 transition-colors">
                        <Trash2 size={10} />
                      </button>
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          <div className="mt-3 pt-2 border-t border-gray-800">
            <p className="text-[12px] text-red-500/70 uppercase leading-tight">
              CRITICAL: CROSS-DOMAIN LINKAGE IS PROTOCOL-FORBIDDEN.
              ROTATING IDENTITY PURGES ALL LOCAL SESSION CACHE.
            </p>
          </div>
        </div>
      )}

      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className={`flex items-center gap-3 px-4 py-2 border ${isExpanded ? 'border-cyan-500 bg-cyan-900/20' : 'border-gray-800 bg-gray-900/80'} backdrop-blur-md transition-all hover:border-cyan-400 group`}
      >
        <div className="flex flex-col items-end">
          <span className="text-sm text-gray-500 uppercase tracking-widest leading-none mb-1">Active Domain</span>
          <span className={`text-xs font-bold tracking-widest ${domain.color} flex items-center gap-1`}>
            {domain.icon} {domain.name}
          </span>
        </div>
        <div className="h-8 w-[1px] bg-gray-800 group-hover:bg-cyan-500/50 transition-colors" />
        <Shield size={18} className={isExpanded ? 'text-cyan-400' : 'text-gray-500 group-hover:text-cyan-400'} />
      </button>
    </div>
  );
}
