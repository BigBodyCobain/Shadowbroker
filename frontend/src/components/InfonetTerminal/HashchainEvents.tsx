'use client';

import React from 'react';
import { Calendar } from 'lucide-react';

const ROADMAP_ITEMS = [
  {
    title: 'Obfuscated lane hardening',
    detail: 'Continue tightening identity boundaries, transport posture, and secure comms behavior without overstating guarantees.',
    status: 'ONGOING',
    type: 'PRIVACY',
  },
  {
    title: 'Participant-node federation',
    detail: 'Keep improving bootstrap, sync clarity, and real multi-node propagation for the public testnet.',
    status: 'TESTNET',
    type: 'NETWORK',
  },
  {
    title: 'Fixed-gate polish',
    detail: 'Wire the existing Wormhole gates cleanly, keep gate creation disabled, and focus on smooth participation.',
    status: 'IN PROGRESS',
    type: 'GATES',
  },
];

export default function HashchainEvents() {
  return (
    <div className="border border-gray-800 bg-gray-900/10 p-3 w-64 hidden lg:block shrink-0 h-fit">
      <h3 className="text-cyan-400 font-bold mb-3 flex items-center text-xs tracking-widest uppercase border-b border-gray-800 pb-2">
        <Calendar size={14} className="mr-2" /> Privacy Roadmap
      </h3>
      <div className="space-y-3">
        {ROADMAP_ITEMS.map((item, i) => (
          <div key={i} className="group cursor-pointer">
            <div className="flex justify-between items-center mb-0.5">
              <span className="text-sm text-green-400 uppercase tracking-widest border border-gray-800 px-1">
                {item.type}
              </span>
              <span className="text-sm font-bold text-cyan-400">
                {item.status}
              </span>
            </div>
            <p className="text-xs text-gray-300 group-hover:text-white transition-colors mt-1">
              {item.title}
            </p>
            <div className="text-sm text-gray-500 mt-1 leading-relaxed">
              {item.detail}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
