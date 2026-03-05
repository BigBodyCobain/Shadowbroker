"use client";

import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ArrowUpRight, ArrowDownRight, TrendingUp, Droplet, ChevronDown, ChevronUp } from 'lucide-react';

const MarketsPanel = React.memo(function MarketsPanel({ data }: { data: any }) {
    const [isMinimized, setIsMinimized] = useState(true);

    const stocks = data?.stocks || {};
    const oil = data?.oil || {};

    return (
        <motion.div
            initial={{ y: -50, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            transition={{ duration: 0.8, delay: 0.2 }}
            className="w-full bg-black/40 backdrop-blur-md border border-gray-800 rounded-xl z-10 flex flex-col font-mono text-sm shadow-[0_4px_30px_rgba(0,0,0,0.5)] pointer-events-auto flex-shrink-0"
        >
            {/* Header Toggle */}
            <div
                className="flex justify-between items-center p-3 cursor-pointer hover:bg-gray-900/50 transition-colors border-b border-gray-800/50"
                onClick={() => setIsMinimized(!isMinimized)}
            >
                <span className="text-[10px] text-gray-500 font-mono tracking-widest">GLOBAL MARKETS</span>
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
                        className="overflow-y-auto styled-scrollbar flex flex-col gap-4 p-4 pt-3 max-h-[400px]"
                    >
                        <div className="border-b border-gray-800 pb-3">
                            <h2 className="text-xs font-bold tracking-widest text-cyan-400 flex items-center gap-2 mb-2">
                                <TrendingUp className="text-cyan-500" size={14} /> DEFENSE SEC TICKERS
                            </h2>
                            <div className="mt-3 flex flex-col gap-2">
                                {Object.entries(stocks).map(([ticker, info]: [string, any]) => (
                                    <div key={ticker} className="flex items-center justify-between border border-cyan-500/10 bg-cyan-950/10 p-1.5 rounded-sm relative group overflow-hidden">
                                        <span className="font-bold text-cyan-300 z-10 text-[10px]">[{ticker}]</span>
                                        <div className="flex items-center gap-3 text-right z-10">
                                            <span className="text-gray-200 font-bold text-xs">${info.price.toFixed(2)}</span>
                                            <span className={`flex items-center gap-0.5 w-12 justify-end text-[9px] ${info.up ? 'text-cyan-400' : 'text-red-400'}`}>
                                                {info.up ? <ArrowUpRight size={10} /> : <ArrowDownRight size={10} />}
                                                {Math.abs(info.change_percent).toFixed(2)}%
                                            </span>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </div>

                        <div>
                            <h2 className="text-xs font-bold tracking-widest text-cyan-400 flex items-center gap-2 mb-2">
                                <Droplet className="text-cyan-500" size={14} /> COMMODITY INDEX
                            </h2>
                            <div className="mt-2 flex flex-col gap-2">
                                {Object.entries(oil).map(([name, info]: [string, any]) => (
                                    <div key={name} className="flex flex-col border border-cyan-500/10 bg-cyan-950/10 p-1.5 rounded-sm justify-between">
                                        <span className="font-bold text-cyan-500 text-[9px] uppercase mb-0.5">{name}</span>
                                        <div className="flex items-center justify-between">
                                            <span className="text-gray-200 font-bold text-[11px]">${info.price.toFixed(2)}</span>
                                            <span className={`flex items-center gap-0.5 text-[9px] ${info.up ? 'text-cyan-400' : 'text-red-400'}`}>
                                                {info.up ? <ArrowUpRight size={10} /> : <ArrowDownRight size={10} />}
                                                {Math.abs(info.change_percent).toFixed(2)}%
                                            </span>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </div>
                    </motion.div>
                )}
            </AnimatePresence>
        </motion.div>
    );
});

export default MarketsPanel;
