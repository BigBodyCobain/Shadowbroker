"use client";

import React, { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ChevronDown, ChevronUp } from "lucide-react";

const WorldviewRightPanel = React.memo(function WorldviewRightPanel({ effects, setEffects, setUiVisible }: { effects: any; setEffects: any; setUiVisible: any }) {
    const [isMinimized, setIsMinimized] = useState(true);
    const [currentTime, setCurrentTime] = useState({ date: "XXXX-XX-XX", time: "00:00:00" });

    useEffect(() => {
        const updateTime = () => {
            const now = new Date();
            setCurrentTime({
                date: now.toISOString().slice(0, 10),
                time: now.toISOString().slice(11, 19)
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
            className={`w-full bg-black/40 backdrop-blur-md border border-gray-800 rounded-xl z-10 flex flex-col font-mono shadow-[0_4px_30px_rgba(0,0,0,0.5)] pointer-events-auto overflow-hidden transition-all duration-300 flex-shrink-0 ${isMinimized ? 'h-[50px]' : 'h-[320px]'}`}
        >
            {/* Record / Orbit Tracker Header */}
            <div className="flex items-center gap-3 mb-6 border border-gray-800 bg-black/40 backdrop-blur-md px-4 py-2 rounded-sm relative shadow-[0_4px_30px_rgba(0,0,0,0.5)] pointer-events-auto">
                <div className="absolute -top-1 -left-1 w-2 h-2 border-t border-l border-gray-500/50"></div>
                <div className="absolute -bottom-1 -right-1 w-2 h-2 border-b border-r border-gray-500/50"></div>
                <div className="w-2 h-2 bg-red-500 rounded-full animate-pulse"></div>
                <div className="text-[10px] font-mono text-gray-400 tracking-wider">
                    REC {currentTime.date} {currentTime.time}
                    <br />
                    ORB: 47696 PASS: DESC-284
                </div>
            </div>

            {/* Right side controls box */}
            <div className="bg-black/40 backdrop-blur-md border border-gray-800 rounded-xl pointer-events-auto border-r-2 border-r-cyan-900 flex flex-col relative overflow-hidden h-full">

                {/* Header / Toggle */}
                <div
                    className="flex justify-between items-center p-4 cursor-pointer hover:bg-gray-900/50 transition-colors border-b border-gray-800/50"
                    onClick={() => setIsMinimized(!isMinimized)}
                >
                    <span className="text-[10px] text-gray-500 font-mono tracking-widest">DISPLAY CONFIG</span>
                    <button className="text-gray-500 hover:text-white transition-colors">
                        {isMinimized ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
                    </button>
                </div>

                <AnimatePresence>
                    {!isMinimized && (
                        <motion.div
                            initial={{ height: 0, opacity: 0 }}
                            animate={{ height: "auto", opacity: 1 }}
                            exit={{ height: 0, opacity: 0 }}
                            className="overflow-y-auto styled-scrollbar"
                        >
                            <div className="flex flex-col gap-6 p-4 pt-4">

                                {/* Bloom Toggle */}
                                <div
                                    className={`flex items-center justify-between group cursor-pointer border rounded px-4 py-3 transition-colors ${effects.bloom ? 'border-yellow-900/50 bg-yellow-950/10' : 'border-gray-800'}`}
                                    onClick={() => setEffects({ ...effects, bloom: !effects.bloom })}
                                >
                                    <div className="flex items-center gap-3">
                                        <span className={`text-[14px] ${effects.bloom ? 'text-yellow-500' : 'text-gray-600'}`}>✧</span>
                                        <span className={`text-xs font-mono tracking-widest ${effects.bloom ? 'text-white' : 'text-gray-500'}`}>BLOOM</span>
                                    </div>
                                    <span className="text-[9px] font-mono tracking-wider text-gray-500">{effects.bloom ? 'ON' : 'OFF'}</span>
                                </div>

                                {/* Sharpen Slider */}
                                <div className="flex flex-col gap-3 group border border-cyan-900/50 bg-cyan-950/10 rounded px-4 py-3 pb-4 relative overflow-hidden">
                                    <div className="absolute left-0 top-0 bottom-0 w-1 bg-cyan-500"></div>
                                    <div className="flex items-center gap-2">
                                        <span className="w-3 h-3 rounded-full border border-cyan-400 flex items-center justify-center relative">
                                            <span className="w-1.5 h-1.5 bg-cyan-400 rounded-full"></span>
                                        </span>
                                        <span className="text-xs font-mono tracking-widest text-cyan-400 font-bold">SHARPEN</span>
                                    </div>
                                    <div className="flex items-center justify-between gap-3 mt-1">
                                        <div className="h-0.5 bg-gray-800 flex-1 relative rounded-full">
                                            <div className="absolute left-0 top-0 bottom-0 w-[49%] bg-cyan-500 shadow-[0_0_10px_rgba(34,211,238,0.5)]"></div>
                                            <div className="absolute left-[49%] top-1/2 -translate-y-1/2 w-2 h-2 bg-white rounded-full"></div>
                                        </div>
                                        <span className="text-[9px] font-mono text-cyan-400">49%</span>
                                    </div>
                                </div>

                                {/* HUD Dropdown */}
                                <div className="flex flex-col gap-2 relative">
                                    <div className="flex items-center gap-3 border border-gray-800 rounded px-4 py-3 text-gray-500 cursor-default">
                                        <span className="w-3 h-3 border border-gray-500 rounded-full flex items-center justify-center"></span>
                                        <span className="text-xs font-mono tracking-widest">HUD</span>
                                    </div>

                                    <div className="flex items-center justify-between border border-gray-800 rounded px-4 py-2 mt-1 bg-black/50">
                                        <span className="text-[10px] text-gray-500 font-mono">LAYOUT</span>
                                        <span className="text-xs text-white tracking-widest border-b border-dashed border-gray-600 pb-0.5 cursor-pointer flex items-center gap-2">
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
