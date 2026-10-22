'use client';

import React from 'react';
import { MessageSquare } from 'lucide-react';

export default function TrendingPosts() {
  return (
    <div className="border border-gray-800 bg-gray-900/10 p-3 w-64 hidden lg:block shrink-0 h-fit">
      <h3 className="text-cyan-400 font-bold mb-3 flex items-center text-xs tracking-widest uppercase border-b border-gray-800 pb-2">
        <MessageSquare size={14} className="mr-2" /> Gates
      </h3>
      <div className="space-y-3">
        <div className="text-sm text-gray-500 leading-relaxed">
          <p className="text-amber-400/80 font-bold mb-1">TEST-NET ACTIVE</p>
          <p>Gates are chatrooms on the Infonet mesh. Posts are encrypted for members who hold the room key; which room you post in, and when, is still visible.</p>
          <p className="mt-2">Type <span className="text-green-400 font-bold">gates</span> or <span className="text-green-400 font-bold">g/</span> to browse available rooms.</p>
        </div>
        <div className="mt-3 pt-3 border-t border-gray-800">
          <p className="text-red-500 font-bold text-xs mb-1">SHADOWBROKER ADVISORY</p>
          <p className="text-[11px] text-red-400/70 leading-relaxed">
            This is a <span className="text-red-400 font-bold">testnet</span>. Message content is encrypted, but the code is <span className="text-red-400 font-bold">unaudited</span> and activity metadata is visible. Don&apos;t share anything that would hurt you if it leaked.
          </p>
        </div>
      </div>
    </div>
  );
}
