"use client";

import React, { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X, Shield, Globe, Radar, Satellite, Ship, Radio } from "lucide-react";

const STORAGE_KEY = "shadowbroker_onboarding_complete";

const FREE_SOURCES = [
    { name: "ADS-B Exchange", desc: "Military & general aviation", icon: <Radar size={12} /> },
    { name: "USGS Earthquakes", desc: "Global seismic data", icon: <Globe size={12} /> },
    { name: "CelesTrak", desc: "2,000+ satellite orbits", icon: <Satellite size={12} /> },
    { name: "GDELT Project", desc: "Global conflict events", icon: <Globe size={12} /> },
    { name: "RainViewer", desc: "Weather radar overlay", icon: <Globe size={12} /> },
    { name: "OpenMHz", desc: "Radio scanner feeds", icon: <Radio size={12} /> },
    { name: "RSS Feeds", desc: "NPR, BBC, Reuters, AP", icon: <Globe size={12} /> },
    { name: "Yahoo Finance", desc: "Defense stocks & oil", icon: <Globe size={12} /> },
    { name: "AIS Stream", desc: "Global vessel tracking", icon: <Ship size={12} /> },
];

interface OnboardingModalProps {
    onClose: () => void;
    onOpenSettings: () => void;
}

const OnboardingModal = React.memo(function OnboardingModal({ onClose, onOpenSettings: _ }: OnboardingModalProps) {
    const [step, setStep] = useState(0);

    const handleDismiss = () => {
        localStorage.setItem(STORAGE_KEY, "true");
        onClose();
    };

    return (
        <AnimatePresence>
            {/* Backdrop */}
            <motion.div
                key="onboarding-backdrop"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="fixed inset-0 bg-black/80 backdrop-blur-sm z-[10000]"
                onClick={handleDismiss}
            />

            {/* Modal */}
            <motion.div
                key="onboarding-modal"
                initial={{ opacity: 0, scale: 0.9, y: 20 }}
                animate={{ opacity: 1, scale: 1, y: 0 }}
                exit={{ opacity: 0, scale: 0.9, y: 20 }}
                transition={{ type: "spring", damping: 25, stiffness: 300 }}
                className="fixed inset-0 z-[10001] flex items-center justify-center pointer-events-none"
            >
                <div
                    className="w-[580px] max-h-[85vh] bg-[var(--bg-secondary)]/98 border border-cyan-900/50 rounded-xl shadow-[0_0_80px_rgba(0,200,255,0.08)] pointer-events-auto flex flex-col overflow-hidden"
                    onClick={(e) => e.stopPropagation()}
                >
                    {/* Header */}
                    <div className="p-6 pb-4 border-b border-[var(--border-primary)]/80">
                        <div className="flex items-center justify-between">
                            <div className="flex items-center gap-3">
                                <div className="w-10 h-10 rounded-lg bg-cyan-500/10 border border-cyan-500/30 flex items-center justify-center">
                                    <Shield size={20} className="text-cyan-400" />
                                </div>
                                <div>
                                    <h2 className="text-sm font-bold tracking-[0.2em] text-[var(--text-primary)] font-mono">MISSION BRIEFING</h2>
                                    <span className="text-[9px] text-[var(--text-muted)] font-mono tracking-widest">FIRST-TIME SETUP</span>
                                </div>
                            </div>
                            <button
                                onClick={handleDismiss}
                                className="w-8 h-8 rounded-lg border border-[var(--border-primary)] hover:border-red-500/50 flex items-center justify-center text-[var(--text-muted)] hover:text-red-400 transition-all hover:bg-red-950/20"
                            >
                                <X size={14} />
                            </button>
                        </div>
                    </div>

                    {/* Step Indicators */}
                    <div className="flex gap-2 px-6 pt-4">
                        {["Welcome", "Data Sources"].map((label, i) => (
                            <button
                                key={label}
                                onClick={() => setStep(i)}
                                className={`flex-1 py-1.5 text-[9px] font-mono tracking-widest rounded border transition-all ${
                                    step === i
                                        ? "border-cyan-500/50 text-cyan-400 bg-cyan-950/20"
                                        : "border-[var(--border-primary)] text-[var(--text-muted)] hover:border-[var(--border-secondary)] hover:text-[var(--text-secondary)]"
                                }`}
                            >
                                {label.toUpperCase()}
                            </button>
                        ))}
                    </div>

                    {/* Content */}
                    <div className="flex-1 overflow-y-auto styled-scrollbar p-6">
                        {step === 0 && (
                            <div className="space-y-4">
                                <div className="text-center py-4">
                                    <div className="text-lg font-bold tracking-[0.3em] text-[var(--text-primary)] font-mono mb-2">
                                        O P E N S O U R C E <span className="text-cyan-400">D A T A</span>
                                    </div>
                                    <p className="text-[11px] text-[var(--text-secondary)] font-mono leading-relaxed max-w-md mx-auto">
                                        Real-time OSINT dashboard aggregating 12+ live intelligence sources.
                                        Flights, ships, satellites, earthquakes, conflicts, and more — all on one map.
                                    </p>
                                </div>

                                <div className="bg-green-950/20 border border-green-500/20 rounded-lg p-4">
                                    <div className="flex items-start gap-2">
                                        <Globe size={14} className="text-green-500 mt-0.5 flex-shrink-0" />
                                        <div>
                                            <p className="text-[11px] text-green-400 font-mono font-bold mb-1">Ready to Use</p>
                                            <p className="text-[10px] text-[var(--text-secondary)] font-mono leading-relaxed">
                                                All data sources are pre-configured. Enable layers from the left panel to start exploring — no setup required.
                                            </p>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        )}

                        {step === 1 && (
                            <div className="space-y-3">
                                <p className="text-[10px] text-[var(--text-secondary)] font-mono mb-3">
                                    These data sources activate automatically when you enable their layer.
                                </p>
                                <div className="grid grid-cols-2 gap-2">
                                    {FREE_SOURCES.map((src) => (
                                        <div key={src.name} className="rounded-lg border border-[var(--border-primary)]/60 bg-[var(--bg-secondary)]/30 p-3 hover:border-[var(--border-secondary)] transition-colors">
                                            <div className="flex items-center gap-2 mb-1">
                                                <span className="text-green-500">{src.icon}</span>
                                                <span className="text-[10px] font-mono text-[var(--text-primary)] font-medium">{src.name}</span>
                                            </div>
                                            <p className="text-[9px] text-[var(--text-muted)] font-mono">{src.desc}</p>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}
                    </div>

                    {/* Footer */}
                    <div className="p-4 border-t border-[var(--border-primary)]/80 flex items-center justify-between">
                        <button
                            onClick={() => setStep(Math.max(0, step - 1))}
                            className={`px-4 py-2 rounded border text-[10px] font-mono tracking-widest transition-all ${
                                step === 0
                                    ? "border-[var(--border-primary)] text-[var(--text-muted)] cursor-not-allowed"
                                    : "border-[var(--border-primary)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:border-[var(--border-secondary)]"
                            }`}
                            disabled={step === 0}
                        >
                            PREV
                        </button>

                        <div className="flex gap-1.5">
                            {[0, 1].map((i) => (
                                <div key={i} className={`w-1.5 h-1.5 rounded-full transition-colors ${step === i ? "bg-cyan-400" : "bg-[var(--border-primary)]"}`} />
                            ))}
                        </div>

                        {step < 1 ? (
                            <button
                                onClick={() => setStep(step + 1)}
                                className="px-4 py-2 rounded border border-cyan-500/40 text-cyan-400 hover:bg-cyan-500/10 text-[10px] font-mono tracking-widest transition-all"
                            >
                                NEXT
                            </button>
                        ) : (
                            <button
                                onClick={handleDismiss}
                                className="px-4 py-2 rounded bg-cyan-500/20 border border-cyan-500/40 text-cyan-400 hover:bg-cyan-500/30 text-[10px] font-mono tracking-widest transition-all"
                            >
                                LAUNCH
                            </button>
                        )}
                    </div>
                </div>
            </motion.div>
        </AnimatePresence>
    );
});

export function useOnboarding() {
    const [showOnboarding, setShowOnboarding] = useState(false);

    useEffect(() => {
        const done = localStorage.getItem(STORAGE_KEY);
        if (!done) {
            setShowOnboarding(true);
        }
    }, []);

    return { showOnboarding, setShowOnboarding };
}

export default OnboardingModal;
