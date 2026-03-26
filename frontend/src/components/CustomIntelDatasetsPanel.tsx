"use client";

import React, { useMemo, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ChevronDown, ChevronUp, Plus, Trash2, AlertTriangle, Clock, Upload } from "lucide-react";
import type { CustomIntelMasterEvent } from "@/types/dashboard";
import {
  getCustomIntelLevelLabel,
  getCustomIntelWeightColor,
  getEventDisplayTime,
  getShortLocationLabel,
  normalizeWeight,
} from "@/lib/customIntelStore";

interface CustomIntelDatasetsPanelProps {
  events: CustomIntelMasterEvent[];
  layerActive: boolean;
  onAddDataset: () => void;
  onDeleteEvent: (masterEventId: string) => void;
  onCopyMasterJson: () => Promise<void>;
  onExportMasterJson: () => void;
  onImportMasterJson: (raw: string, mode: "merge" | "replace") => Promise<void>;
}

const CustomIntelDatasetsPanel = React.memo(function CustomIntelDatasetsPanel({
  events,
  layerActive,
  onAddDataset,
  onDeleteEvent,
  onCopyMasterJson,
  onExportMasterJson,
  onImportMasterJson,
}: CustomIntelDatasetsPanelProps) {
  const [minimized, setMinimized] = useState(false);
  const [expandedSources, setExpandedSources] = useState<Record<string, boolean>>({});
  const [feedback, setFeedback] = useState<string | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [importRaw, setImportRaw] = useState("");

  const setTransientFeedback = (msg: string) => {
    setFeedback(msg);
    window.setTimeout(() => setFeedback(null), 2200);
  };

  const visibleEvents = useMemo(() => events.filter((e) => !!e.geo && Number.isFinite(e.geo.lat) && Number.isFinite(e.geo.lng)), [events]);

  return (
    <motion.div
      initial={{ y: 20, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={{ duration: 0.45 }}
      className={`w-full bg-[var(--bg-primary)]/40 backdrop-blur-md border border-[var(--border-primary)] rounded-xl flex flex-col z-10 font-mono shadow-[0_4px_30px_rgba(0,0,0,0.45)] pointer-events-auto overflow-hidden transition-all duration-300 ${minimized ? "h-[52px] flex-shrink-0" : "max-h-[320px]"}`}
    >
      <div
        className="p-3 border-b border-[var(--border-primary)]/50 cursor-pointer hover:bg-[var(--bg-secondary)]/50 transition-colors"
        onClick={() => setMinimized(!minimized)}
      >
        <div className="flex items-center justify-between">
          <h2 className="text-xs tracking-widest font-bold text-cyan-400 flex items-center gap-2">
            <AlertTriangle size={14} /> CUSTOM INTEL FEED
          </h2>
          <button className="text-cyan-500 hover:text-[var(--text-primary)] transition-colors">
            {minimized ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
          </button>
        </div>

        {!minimized && (
          <div className="mt-1 text-[9px] text-cyan-500/80 font-bold flex items-center justify-between">
            <span className="px-1 border border-cyan-500/30">{visibleEvents.length} EVENTS</span>
            <span className={layerActive ? "text-cyan-300" : "text-[var(--text-muted)]"}>{layerActive ? "MAP: ON" : "MAP: OFF"}</span>
          </div>
        )}
      </div>

      <AnimatePresence>
        {!minimized && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="p-3 flex flex-col gap-2 overflow-y-auto styled-scrollbar"
          >
            <button
              onClick={(e) => {
                e.stopPropagation();
                onAddDataset();
              }}
              className="w-full px-2 py-1.5 rounded border border-cyan-500/40 bg-cyan-950/25 text-cyan-300 hover:text-cyan-200 hover:border-cyan-400 text-[9px] tracking-wider flex items-center justify-center gap-1"
            >
              <Plus size={11} /> ADD INTEL DATASET
            </button>

            <button
              onClick={(e) => {
                e.stopPropagation();
                setImportRaw("");
                setImportOpen(true);
              }}
              className="w-full px-2 py-1.5 rounded border border-[var(--border-primary)] text-[var(--text-muted)] hover:text-cyan-300 hover:border-cyan-500/40 text-[9px] tracking-wider flex items-center justify-center gap-1"
            >
              <Upload size={11} /> IMPORT MASTER JSON
            </button>

            <div className="grid grid-cols-2 gap-2">
              <button
                onClick={async (e) => {
                  e.stopPropagation();
                  try {
                    await onCopyMasterJson();
                    setTransientFeedback("Master JSON copied");
                  } catch {
                    setTransientFeedback("Clipboard failed");
                  }
                }}
                className="px-2 py-1.5 rounded border border-[var(--border-primary)] text-[var(--text-muted)] hover:text-cyan-300 hover:border-cyan-500/40 text-[9px] tracking-wider"
              >
                COPY MASTER JSON
              </button>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  try {
                    onExportMasterJson();
                    setTransientFeedback("Master JSON exported");
                  } catch {
                    setTransientFeedback("Export failed");
                  }
                }}
                className="px-2 py-1.5 rounded border border-[var(--border-primary)] text-[var(--text-muted)] hover:text-cyan-300 hover:border-cyan-500/40 text-[9px] tracking-wider"
              >
                EXPORT MASTER JSON
              </button>
            </div>

            {feedback && (
              <div className="text-[9px] text-cyan-300 border border-cyan-500/30 bg-cyan-950/20 rounded px-2 py-1">
                {feedback}
              </div>
            )}

            {visibleEvents.length === 0 ? (
              <div className="text-[9px] text-[var(--text-muted)] border border-[var(--border-primary)] rounded px-2 py-2">
                No Custom Intel events loaded.
              </div>
            ) : (
              visibleEvents.map((event) => {
                const weight = normalizeWeight(event.weight);
                const wc = getCustomIntelWeightColor(weight);
                const levelLabel = getCustomIntelLevelLabel(weight);
                const shortLocation = getShortLocationLabel(event.location_label);
                const displayTime = getEventDisplayTime(event);
                const sourceCount = event.sources?.length ?? 0;
                const isSourcesOpen = !!expandedSources[event.masterEventId];

                return (
                  <motion.div
                    key={event.masterEventId}
                    initial={{ opacity: 0, x: -10 }}
                    animate={{ opacity: 1, x: 0 }}
                    className="p-2 rounded-sm border-l-[2px] border-r border-t border-b bg-[var(--bg-secondary)]/30 flex flex-col gap-1 relative group shrink-0"
                    style={{ borderLeftColor: wc.stroke, borderColor: `${wc.stroke}44` }}
                  >
                    <div className="flex items-center justify-between text-[8px] text-[var(--text-secondary)] uppercase tracking-widest">
                      <span className="font-bold flex items-center gap-1 text-cyan-600 truncate max-w-[65%]">
                        &gt;_ {event.type || event.story_title}
                      </span>
                      <span className="flex items-center gap-1"><Clock size={9} />[{displayTime}]</span>
                    </div>

                    <div className="text-[11px] text-[var(--text-primary)] font-bold leading-tight">{event.name || "Unnamed Event"}</div>

                    <div className="text-[9px] text-[var(--text-secondary)] leading-tight">
                      <span className="text-[var(--text-muted)]">Location:</span> {shortLocation}
                    </div>

                    <div className="flex justify-between items-end mt-1 relative z-10">
                      <span
                        className={`text-[8px] font-bold px-1 rounded-sm border ${wc.text}`}
                        style={{ borderColor: `${wc.stroke}88`, backgroundColor: `${wc.fill}22` }}
                      >
                        LVL: {levelLabel}
                      </span>
                      <span className="text-[8px] text-[var(--text-muted)] font-mono tracking-tighter">
                        {event.geo.lat.toFixed(2)}, {event.geo.lng.toFixed(2)}
                      </span>
                    </div>

                    <div className="flex justify-between items-center mt-1">
                      <div className="flex items-center gap-2">
                        {sourceCount > 0 && (
                          <button
                            onClick={() => setExpandedSources((prev) => ({ ...prev, [event.masterEventId]: !isSourcesOpen }))}
                            className="text-[8px] font-bold text-cyan-500 bg-[var(--bg-secondary)]/50 hover:text-[var(--text-primary)] hover:bg-[var(--hover-accent)] border border-cyan-500/30 px-1.5 py-0.5 rounded-sm transition-colors"
                          >
                            {isSourcesOpen ? "[- SOURCES]" : `[+${sourceCount} SOURCES]`}
                          </button>
                        )}
                      </div>

                      <button
                        onClick={() => {
                          if (window.confirm("Delete this event from Custom Intel?")) {
                            onDeleteEvent(event.masterEventId);
                          }
                        }}
                        className="w-5 h-5 rounded border border-[var(--border-primary)] text-[var(--text-muted)] hover:text-red-400 hover:border-red-500/40 flex items-center justify-center"
                        title="Delete event"
                      >
                        <Trash2 size={10} />
                      </button>
                    </div>

                    <AnimatePresence>
                      {isSourcesOpen && sourceCount > 0 && (
                        <motion.div
                          initial={{ height: 0, opacity: 0 }}
                          animate={{ height: "auto", opacity: 1 }}
                          exit={{ height: 0, opacity: 0 }}
                          className="mt-1 pt-1 border-t border-cyan-500/20 flex flex-col gap-1 overflow-hidden"
                        >
                          {event.sources?.map((source, idx) => (
                            <a
                              key={`${source.name}-${idx}`}
                              href={source.url}
                              target="_blank"
                              rel="noreferrer noopener nofollow"
                              className="text-[9px] text-cyan-400 hover:text-cyan-300 underline truncate block"
                              title={source.url}
                            >
                              {source.name || source.url}
                            </a>
                          ))}
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </motion.div>
                );
              })
            )}
          </motion.div>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {importOpen && (
          <>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="fixed inset-0 bg-black/70 backdrop-blur-sm z-[9998]"
              onClick={() => setImportOpen(false)}
            />
            <motion.div
              initial={{ opacity: 0, scale: 0.96, y: 8 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.96, y: 8 }}
              transition={{ type: "spring", damping: 25, stiffness: 300 }}
              className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-[520px] max-w-[92vw] z-[9999]"
            >
              <div className="bg-[var(--bg-secondary)]/98 border border-cyan-900/50 rounded-xl shadow-[0_0_60px_rgba(0,180,255,0.12)] overflow-hidden">
                <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--border-primary)]/70 bg-[var(--bg-primary)]/40">
                  <div className="text-[10px] font-mono tracking-[0.18em] text-[var(--text-primary)]">IMPORT MASTER JSON</div>
                  <button
                    onClick={() => setImportOpen(false)}
                    className="w-7 h-7 rounded-lg border border-[var(--border-primary)] hover:border-red-500/50 flex items-center justify-center text-[var(--text-muted)] hover:text-red-400 transition-colors"
                  >
                    ×
                  </button>
                </div>
                <div className="p-4 flex flex-col gap-3">
                  <textarea
                    value={importRaw}
                    onChange={(e) => setImportRaw(e.target.value)}
                    placeholder="Paste exported CustomIntelStore JSON..."
                    className="w-full h-[180px] bg-[var(--bg-primary)]/50 border border-[var(--border-primary)] rounded-lg px-3 py-2 text-[10px] text-[var(--text-primary)] font-mono leading-relaxed resize-y outline-none focus:border-cyan-500/60 styled-scrollbar"
                  />
                  <div className="flex items-center justify-between gap-2">
                    <label className="text-[9px] text-[var(--text-muted)] border border-[var(--border-primary)] rounded px-2 py-1 cursor-pointer hover:text-cyan-300 hover:border-cyan-500/40">
                      Upload .json
                      <input
                        type="file"
                        accept="application/json,.json"
                        className="hidden"
                        onChange={async (e) => {
                          const f = e.target.files?.[0];
                          if (!f) return;
                          const text = await f.text();
                          setImportRaw(text);
                          e.currentTarget.value = "";
                        }}
                      />
                    </label>
                    <div className="text-[8px] text-[var(--text-muted)]">Choose merge or replace</div>
                  </div>
                  <div className="flex items-center justify-end gap-2">
                    <button
                      onClick={() => setImportOpen(false)}
                      className="px-3 py-1.5 rounded border border-[var(--border-primary)] text-[9px] font-mono tracking-wider text-[var(--text-muted)] hover:text-cyan-300 hover:border-cyan-500/40"
                    >
                      CANCEL
                    </button>
                    <button
                      onClick={async () => {
                        try {
                          await onImportMasterJson(importRaw, "merge");
                          setImportOpen(false);
                          setTransientFeedback("Imported (merge)");
                        } catch {
                          setTransientFeedback("Import failed");
                        }
                      }}
                      className="px-3 py-1.5 rounded border border-cyan-500/40 bg-cyan-950/30 text-[9px] font-mono tracking-wider text-cyan-300 hover:text-cyan-200 hover:border-cyan-400"
                    >
                      MERGE
                    </button>
                    <button
                      onClick={async () => {
                        if (!window.confirm("Replace current master store?")) return;
                        try {
                          await onImportMasterJson(importRaw, "replace");
                          setImportOpen(false);
                          setTransientFeedback("Imported (replace)");
                        } catch {
                          setTransientFeedback("Import failed");
                        }
                      }}
                      className="px-3 py-1.5 rounded border border-orange-500/40 bg-orange-950/30 text-[9px] font-mono tracking-wider text-orange-300 hover:text-orange-200 hover:border-orange-400"
                    >
                      REPLACE
                    </button>
                  </div>
                </div>
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </motion.div>
  );
});

export default CustomIntelDatasetsPanel;
