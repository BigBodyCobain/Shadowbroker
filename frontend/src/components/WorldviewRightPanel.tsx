'use client';

import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Plus, Minus } from 'lucide-react';
import type { MapEffects } from '@/types/dashboard';

const WorldviewRightPanel = React.memo(function WorldviewRightPanel({
  effects,
  setEffects,
  setUiVisible,
}: {
  effects: MapEffects;
  setEffects: (e: MapEffects) => void;
  setUiVisible: (v: boolean) => void;
}) {
  const [isMinimized, setIsMinimized] = useState(true);
  const [currentTime, setCurrentTime] = useState({ date: 'XXXX-XX-XX', time: '00:00:00' });

  useEffect(() => {
    const updateTime = () => {
      const now = new Date();
      setCurrentTime({
        date: now.toISOString().slice(0, 10),
        time: now.toISOString().slice(11, 19),
      });
    };
    updateTime();
    const interval = setInterval(updateTime, 1000);
    return () => clearInterval(interval);
  }, []);

  return (
    <motion.div
      initial={{ opacity: 0, x: -50 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 1 }}
      className={`w-full bg-[#0a0a0a]/90 backdrop-blur-sm border border-cyan-900/40 z-10 flex flex-col font-mono pointer-events-auto overflow-hidden transition-all duration-300 flex-shrink-0 ${isMinimized ? 'h-[50px]' : 'h-[320px]'}`}
    >
      {/* Record / Orbit Tracker Header */}
      <div className="flex items-center gap-3 mb-6 border border-cyan-900/40 bg-[#0a0a0a]/90 backdrop-blur-sm px-4 py-2 rounded-sm relative pointer-events-auto">
        <div className="absolute -top-1 -left-1 w-2 h-2 border-t border-l border-[var(--text-muted)]/50"></div>
        <div className="absolute -bottom-1 -right-1 w-2 h-2 border-b border-r border-[var(--text-muted)]/50"></div>
        <div className="w-2 h-2 bg-red-500 rounded-full animate-pulse"></div>
        <div className="text-[10px] font-mono text-[var(--text-secondary)] tracking-wider">
          REC {currentTime.date} {currentTime.time}
          <br />
          ORB: 47696 PASS: DESC-284
        </div>
      </div>

      {/* Right side controls box */}
      <div className="bg-[#0a0a0a]/90 backdrop-blur-sm border border-cyan-900/40 pointer-events-auto border-r-2 border-r-cyan-900/40 flex flex-col relative overflow-hidden h-full">
        {/* Header / Toggle */}
        <div
          className="flex items-center justify-between px-3 py-2.5 cursor-pointer hover:bg-cyan-950/30 transition-colors border-b border-cyan-900/40"
          onClick={() => setIsMinimized(!isMinimized)}
        >
          <span className="text-[12px] text-cyan-400 font-mono tracking-widest font-bold">
            DISPLAY CONFIG
          </span>
          {isMinimized ? (
            <Plus size={16} className="text-cyan-400" />
          ) : (
            <Minus size={16} className="text-cyan-400" />
          )}
        </div>

        <AnimatePresence>
          {!isMinimized && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              className="overflow-y-auto styled-scrollbar"
            >
              <div className="flex flex-col gap-6 p-4 pt-4">
                {/* Bloom Toggle */}
                <div
                  className={`flex items-center justify-between group cursor-pointer border rounded px-4 py-3 transition-colors ${effects.bloom ? 'border-yellow-900/50 bg-yellow-950/10' : 'border-[var(--border-primary)]'}`}
                  onClick={() => setEffects({ ...effects, bloom: !effects.bloom })}
                >
                  <div className="flex items-center gap-3">
                    <span
                      className={`text-[14px] ${effects.bloom ? 'text-yellow-500' : 'text-[var(--text-muted)]'}`}
                    >
                      ✧
                    </span>
                    <span
                      className={`text-xs font-mono tracking-widest ${effects.bloom ? 'text-[var(--text-primary)]' : 'text-[var(--text-muted)]'}`}
                    >
                      BLOOM
                    </span>
                  </div>
                  <span className="text-[9px] font-mono tracking-wider text-[var(--text-muted)]">
                    {effects.bloom ? 'ON' : 'OFF'}
                  </span>
                </div>

                {/* Sharpen Slider */}
                <div className="flex flex-col gap-3 group border border-[var(--border-primary)]/50 bg-[var(--bg-secondary)]/10 rounded px-4 py-3 pb-4 relative overflow-hidden">
                  <div className="absolute left-0 top-0 bottom-0 w-1 bg-cyan-500"></div>
                  <div className="flex items-center gap-2">
                    <span className="w-3 h-3 rounded-full border border-cyan-400 flex items-center justify-center relative">
                      <span className="w-1.5 h-1.5 bg-cyan-400 rounded-full"></span>
                    </span>
                    <span className="text-xs font-mono tracking-widest text-cyan-400 font-bold">
                      SHARPEN
                    </span>
                  </div>
                  <div className="flex items-center justify-between gap-3 mt-1">
                    <div className="h-0.5 bg-[var(--border-primary)] flex-1 relative rounded-full">
                      <div className="absolute left-0 top-0 bottom-0 w-[49%] bg-cyan-500 shadow-[0_0_10px_rgba(34,211,238,0.5)]"></div>
                      <div className="absolute left-[49%] top-1/2 -translate-y-1/2 w-2 h-2 bg-white rounded-full"></div>
                    </div>
                    <span className="text-[9px] font-mono text-cyan-400">49%</span>
                  </div>
                </div>

                {/* HUD Dropdown */}
                <div className="flex flex-col gap-2 relative">
                  <div className="flex items-center gap-3 border border-[var(--border-primary)] rounded px-4 py-3 text-[var(--text-muted)] cursor-default">
                    <span className="w-3 h-3 border border-[var(--border-secondary)] rounded-full flex items-center justify-center"></span>
                    <span className="text-xs font-mono tracking-widest">HUD</span>
                  </div>

                  <div className="flex items-center justify-between border border-[var(--border-primary)] rounded px-4 py-2 mt-1 bg-[var(--bg-primary)]/50">
                    <span className="text-[10px] text-[var(--text-muted)] font-mono">LAYOUT</span>
                    <span className="text-xs text-[var(--text-primary)] tracking-widest border-b border-dashed border-[var(--border-secondary)] pb-0.5 cursor-pointer flex items-center gap-2">
                      Tactical
                    </span>
                  </div>
                </div>

                <button
                  className="w-full border border-red-900/30 bg-red-950/10 rounded py-3 mt-2 text-[10px] font-mono tracking-widest text-red-500 hover:text-white hover:bg-red-900 hover:border-red-600 transition-all font-bold"
                  onClick={() => setUiVisible(false)}
                >
                  CLEAR UI (TACTICAL MODE)
                </button>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  );
});

export default WorldviewRightPanel;
