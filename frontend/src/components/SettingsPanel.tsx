"use client";

import React, { useState, useEffect, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Settings, Eye, EyeOff, Copy, Check, ExternalLink, Key, Shield, X, Save, ChevronDown, ChevronUp } from "lucide-react";

interface ApiEntry {
    id: string;
    name: string;
    description: string;
    category: string;
    url: string | null;
    required: boolean;
    has_key: boolean;
    env_key: string | null;
    value_obfuscated: string | null;
    value_plain: string | null;
}

// Category colors for the tactical UI
const CATEGORY_COLORS: Record<string, string> = {
    Aviation: "text-cyan-400 border-cyan-500/30 bg-cyan-950/20",
    Maritime: "text-blue-400 border-blue-500/30 bg-blue-950/20",
    Geophysical: "text-orange-400 border-orange-500/30 bg-orange-950/20",
    Space: "text-purple-400 border-purple-500/30 bg-purple-950/20",
    Intelligence: "text-red-400 border-red-500/30 bg-red-950/20",
    Geolocation: "text-green-400 border-green-500/30 bg-green-950/20",
    Weather: "text-yellow-400 border-yellow-500/30 bg-yellow-950/20",
    Markets: "text-emerald-400 border-emerald-500/30 bg-emerald-950/20",
    SIGINT: "text-rose-400 border-rose-500/30 bg-rose-950/20",
};

const SettingsPanel = React.memo(function SettingsPanel({ isOpen, onClose }: { isOpen: boolean; onClose: () => void }) {
    const [apis, setApis] = useState<ApiEntry[]>([]);
    const [revealedKeys, setRevealedKeys] = useState<Set<string>>(new Set());
    const [copiedId, setCopiedId] = useState<string | null>(null);
    const [editingId, setEditingId] = useState<string | null>(null);
    const [editValue, setEditValue] = useState("");
    const [saving, setSaving] = useState(false);
    const [expandedCategories, setExpandedCategories] = useState<Set<string>>(new Set(["Aviation", "Maritime"]));

    const fetchKeys = useCallback(async () => {
        try {
            const res = await fetch("http://localhost:8000/api/settings/api-keys");
            if (res.ok) {
                const data = await res.json();
                setApis(data);
            }
        } catch (e) {
            console.error("Failed to fetch API keys", e);
        }
    }, []);

    useEffect(() => {
        if (isOpen) fetchKeys();
    }, [isOpen, fetchKeys]);

    const toggleReveal = (id: string) => {
        setRevealedKeys(prev => {
            const next = new Set(prev);
            if (next.has(id)) next.delete(id);
            else next.add(id);
            return next;
        });
    };

    const copyToClipboard = async (id: string, value: string) => {
        try {
            await navigator.clipboard.writeText(value);
            setCopiedId(id);
            setTimeout(() => setCopiedId(null), 2000);
        } catch {
            // Clipboard API may fail in some contexts
        }
    };

    const startEditing = (api: ApiEntry) => {
        setEditingId(api.id);
        setEditValue(api.value_plain || "");
    };

    const saveKey = async (api: ApiEntry) => {
        if (!api.env_key) return;
        setSaving(true);
        try {
            const res = await fetch("http://localhost:8000/api/settings/api-keys", {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ env_key: api.env_key, value: editValue }),
            });
            if (res.ok) {
                setEditingId(null);
                fetchKeys(); // Refresh to get new obfuscated value
            }
        } catch (e) {
            console.error("Failed to save API key", e);
        } finally {
            setSaving(false);
        }
    };

    const toggleCategory = (cat: string) => {
        setExpandedCategories(prev => {
            const next = new Set(prev);
            if (next.has(cat)) next.delete(cat);
            else next.add(cat);
            return next;
        });
    };

    // Group APIs by category
    const grouped = apis.reduce<Record<string, ApiEntry[]>>((acc, api) => {
        if (!acc[api.category]) acc[api.category] = [];
        acc[api.category].push(api);
        return acc;
    }, {});

    return (
        <AnimatePresence>
            {isOpen && (
                <>
                    {/* Backdrop */}
                    <motion.div
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        className="fixed inset-0 bg-black/70 backdrop-blur-sm z-[9998]"
                        onClick={onClose}
                    />

                    {/* Settings Panel */}
                    <motion.div
                        initial={{ opacity: 0, x: -300 }}
                        animate={{ opacity: 1, x: 0 }}
                        exit={{ opacity: 0, x: -300 }}
                        transition={{ type: "spring", damping: 25, stiffness: 300 }}
                        className="fixed left-0 top-0 bottom-0 w-[480px] bg-gray-950/95 backdrop-blur-xl border-r border-cyan-900/50 z-[9999] flex flex-col shadow-[4px_0_40px_rgba(0,0,0,0.8)]"
                    >
                        {/* Header */}
                        <div className="flex items-center justify-between p-6 border-b border-gray-800/80">
                            <div className="flex items-center gap-3">
                                <div className="w-8 h-8 rounded-lg bg-cyan-500/10 border border-cyan-500/30 flex items-center justify-center">
                                    <Settings size={16} className="text-cyan-400" />
                                </div>
                                <div>
                                    <h2 className="text-sm font-bold tracking-[0.2em] text-white font-mono">SYSTEM CONFIG</h2>
                                    <span className="text-[9px] text-gray-500 font-mono tracking-widest">API KEY REGISTRY</span>
                                </div>
                            </div>
                            <button
                                onClick={onClose}
                                className="w-8 h-8 rounded-lg border border-gray-700 hover:border-red-500/50 flex items-center justify-center text-gray-500 hover:text-red-400 transition-all hover:bg-red-950/20"
                            >
                                <X size={14} />
                            </button>
                        </div>

                        {/* Info Banner */}
                        <div className="mx-4 mt-4 p-3 rounded-lg border border-cyan-900/30 bg-cyan-950/10">
                            <div className="flex items-start gap-2">
                                <Shield size={12} className="text-cyan-500 mt-0.5 flex-shrink-0" />
                                <p className="text-[10px] text-gray-400 font-mono leading-relaxed">
                                    API keys are stored locally in the backend <span className="text-cyan-400">.env</span> file. Keys marked with <Key size={8} className="inline text-yellow-500" /> are required for full functionality. Public APIs need no key.
                                </p>
                            </div>
                        </div>

                        {/* API List */}
                        <div className="flex-1 overflow-y-auto styled-scrollbar p-4 space-y-3">
                            {Object.entries(grouped).map(([category, categoryApis]) => {
                                const colorClass = CATEGORY_COLORS[category] || "text-gray-400 border-gray-700 bg-gray-900/20";
                                const isExpanded = expandedCategories.has(category);

                                return (
                                    <div key={category} className="rounded-lg border border-gray-800/60 overflow-hidden">
                                        {/* Category Header */}
                                        <button
                                            onClick={() => toggleCategory(category)}
                                            className="w-full flex items-center justify-between px-4 py-2.5 bg-gray-900/50 hover:bg-gray-900/80 transition-colors"
                                        >
                                            <div className="flex items-center gap-2">
                                                <span className={`text-[9px] font-mono tracking-widest font-bold px-2 py-0.5 rounded border ${colorClass}`}>
                                                    {category.toUpperCase()}
                                                </span>
                                                <span className="text-[10px] text-gray-500 font-mono">
                                                    {categoryApis.length} {categoryApis.length === 1 ? 'service' : 'services'}
                                                </span>
                                            </div>
                                            {isExpanded ? <ChevronUp size={12} className="text-gray-500" /> : <ChevronDown size={12} className="text-gray-500" />}
                                        </button>

                                        {/* APIs in Category */}
                                        <AnimatePresence>
                                            {isExpanded && (
                                                <motion.div
                                                    initial={{ height: 0, opacity: 0 }}
                                                    animate={{ height: "auto", opacity: 1 }}
                                                    exit={{ height: 0, opacity: 0 }}
                                                    transition={{ duration: 0.2 }}
                                                >
                                                    {categoryApis.map((api) => (
                                                        <div key={api.id} className="border-t border-gray-800/40 px-4 py-3 hover:bg-gray-900/30 transition-colors">
                                                            {/* API Name + Status */}
                                                            <div className="flex items-center justify-between mb-1">
                                                                <div className="flex items-center gap-2">
                                                                    {api.required && <Key size={10} className="text-yellow-500" />}
                                                                    <span className="text-xs font-mono text-white font-medium">{api.name}</span>
                                                                </div>
                                                                <div className="flex items-center gap-1.5">
                                                                    {api.has_key ? (
                                                                        <span className="text-[8px] font-mono px-1.5 py-0.5 rounded border border-green-500/30 text-green-400 bg-green-950/20">
                                                                            KEY SET
                                                                        </span>
                                                                    ) : (
                                                                        <span className="text-[8px] font-mono px-1.5 py-0.5 rounded border border-gray-700 text-gray-500">
                                                                            PUBLIC
                                                                        </span>
                                                                    )}
                                                                    {api.url && (
                                                                        <a
                                                                            href={api.url}
                                                                            target="_blank"
                                                                            rel="noopener noreferrer"
                                                                            className="text-gray-600 hover:text-cyan-400 transition-colors"
                                                                            onClick={(e) => e.stopPropagation()}
                                                                        >
                                                                            <ExternalLink size={10} />
                                                                        </a>
                                                                    )}
                                                                </div>
                                                            </div>

                                                            {/* Description */}
                                                            <p className="text-[10px] text-gray-500 font-mono leading-relaxed mb-2">
                                                                {api.description}
                                                            </p>

                                                            {/* Key Field (only for APIs with keys) */}
                                                            {api.has_key && (
                                                                <div className="mt-2">
                                                                    {editingId === api.id ? (
                                                                        /* Edit Mode */
                                                                        <div className="flex gap-2">
                                                                            <input
                                                                                type="text"
                                                                                value={editValue}
                                                                                onChange={(e) => setEditValue(e.target.value)}
                                                                                className="flex-1 bg-black/60 border border-cyan-900/50 rounded px-2 py-1.5 text-[11px] font-mono text-cyan-300 outline-none focus:border-cyan-500/70 transition-colors"
                                                                                placeholder="Enter API key..."
                                                                                autoFocus
                                                                            />
                                                                            <button
                                                                                onClick={() => saveKey(api)}
                                                                                disabled={saving}
                                                                                className="px-3 py-1.5 rounded bg-cyan-500/20 border border-cyan-500/40 text-cyan-400 hover:bg-cyan-500/30 transition-colors text-[10px] font-mono flex items-center gap-1"
                                                                            >
                                                                                <Save size={10} />
                                                                                {saving ? "..." : "SAVE"}
                                                                            </button>
                                                                            <button
                                                                                onClick={() => setEditingId(null)}
                                                                                className="px-2 py-1.5 rounded border border-gray-700 text-gray-500 hover:text-white hover:border-gray-600 transition-colors text-[10px] font-mono"
                                                                            >
                                                                                ESC
                                                                            </button>
                                                                        </div>
                                                                    ) : (
                                                                        /* Display Mode */
                                                                        <div className="flex items-center gap-1.5">
                                                                            <div
                                                                                className="flex-1 bg-black/40 border border-gray-800 rounded px-2.5 py-1.5 font-mono text-[11px] cursor-pointer hover:border-gray-700 transition-colors select-none"
                                                                                onClick={() => startEditing(api)}
                                                                            >
                                                                                <span className={revealedKeys.has(api.id) ? "text-cyan-300" : "text-gray-500 tracking-wider"}>
                                                                                    {revealedKeys.has(api.id) ? api.value_plain : api.value_obfuscated}
                                                                                </span>
                                                                            </div>

                                                                            {/* Eye Toggle */}
                                                                            <button
                                                                                onClick={() => toggleReveal(api.id)}
                                                                                className={`w-7 h-7 rounded flex items-center justify-center border transition-all ${revealedKeys.has(api.id)
                                                                                        ? "border-cyan-500/40 text-cyan-400 bg-cyan-950/30"
                                                                                        : "border-gray-700 text-gray-600 hover:text-gray-400 hover:border-gray-600"
                                                                                    }`}
                                                                                title={revealedKeys.has(api.id) ? "Hide key" : "Reveal key"}
                                                                            >
                                                                                {revealedKeys.has(api.id) ? <EyeOff size={12} /> : <Eye size={12} />}
                                                                            </button>

                                                                            {/* Copy */}
                                                                            <button
                                                                                onClick={() => copyToClipboard(api.id, api.value_plain || "")}
                                                                                className={`w-7 h-7 rounded flex items-center justify-center border transition-all ${copiedId === api.id
                                                                                        ? "border-green-500/40 text-green-400 bg-green-950/30"
                                                                                        : "border-gray-700 text-gray-600 hover:text-gray-400 hover:border-gray-600"
                                                                                    }`}
                                                                                title="Copy to clipboard"
                                                                            >
                                                                                {copiedId === api.id ? <Check size={12} /> : <Copy size={12} />}
                                                                            </button>
                                                                        </div>
                                                                    )}
                                                                </div>
                                                            )}
                                                        </div>
                                                    ))}
                                                </motion.div>
                                            )}
                                        </AnimatePresence>
                                    </div>
                                );
                            })}
                        </div>

                        {/* Footer */}
                        <div className="p-4 border-t border-gray-800/80">
                            <div className="flex items-center justify-between text-[9px] text-gray-600 font-mono">
                                <span>{apis.length} REGISTERED APIs</span>
                                <span>{apis.filter(a => a.has_key).length} KEYS CONFIGURED</span>
                            </div>
                        </div>
                    </motion.div>
                </>
            )}
        </AnimatePresence>
    );
});

export default SettingsPanel;
