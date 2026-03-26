"use client";

import React, { useMemo, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ChevronDown, ChevronUp, Plus, Eye, EyeOff, Trash2, Copy, Download, Database, Upload, X } from "lucide-react";
import type { CustomIntelDataset } from "@/types/dashboard";
import { deriveDatasetMaxWeight, getCustomIntelWeightColor, getDatasetLatestDateLabel } from "@/lib/customIntelStore";

interface CustomIntelDatasetsPanelProps {
  datasets: CustomIntelDataset[];
  layerActive: boolean;
  onAddDataset: () => void;
  onToggleDatasetVisibility: (datasetId: string) => void;
  onDeleteDataset: (datasetId: string) => void;
  onDeleteEvent: (datasetId: string, eventId: string) => void;
  onCopyMasterJson: () => Promise<void>;
  onExportMasterJson: () => void;
  onImportMasterJson: (raw: string, mode: "merge" | "replace") => Promise<void>;
}

function resolveEventId(storyId: string, eventId: string | undefined, index: number): string {
  return eventId && eventId.trim().length > 0 ? eventId : `${storyId}-${index}`;
}

const CustomIntelDatasetsPanel = React.memo(function CustomIntelDatasetsPanel({
  datasets,
  layerActive,
  onAddDataset,
  onToggleDatasetVisibility,
  onDeleteDataset,
  onDeleteEvent,
  onCopyMasterJson,
  onExportMasterJson,
  onImportMasterJson,
}: CustomIntelDatasetsPanelProps) {
  const [minimized, setMinimized] = useState(false);
  const [expandedDatasets, setExpandedDatasets] = useState<Record<string, boolean>>({});
  const [feedback, setFeedback] = useState<string | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [importRaw, setImportRaw] = useState("");

  const totals = useMemo(() => {
    const stories = datasets.reduce((sum, d) => sum + d.stories.length, 0);
    const events = datasets.reduce((sum, d) => sum + d.eventCount, 0);
    return { stories, events };
  }, [datasets]);

  const setTransientFeedback = (msg: string) => {
    setFeedback(msg);
    window.setTimeout(() => setFeedback(null), 2200);
  };

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
            <Database size={14} /> CUSTOM INTEL DATASETS
          </h2>
          <button className="text-cyan-500 hover:text-[var(--text-primary)] transition-colors">
            {minimized ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
          </button>
        </div>

        {!minimized && (
          <div className="mt-1 text-[9px] text-cyan-500/80 font-bold flex items-center justify-between">
            <span className="px-1 border border-cyan-500/30">{totals.stories} STORIES · {totals.events} EVENTS</span>
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
            <div className="flex items-center gap-2">
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onAddDataset();
                }}
                className="flex-1 px-2 py-1.5 rounded border border-cyan-500/40 bg-cyan-950/25 text-cyan-300 hover:text-cyan-200 hover:border-cyan-400 text-[9px] tracking-wider flex items-center justify-center gap-1"
              >
                <Plus size={11} /> ADD INTEL DATASET
              </button>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  setImportRaw("");
                  setImportOpen(true);
                }}
                className="px-2 py-1.5 rounded border border-[var(--border-primary)] text-[var(--text-muted)] hover:text-cyan-300 hover:border-cyan-500/40 text-[9px]"
                title="Import Master JSON"
              >
                <Upload size={11} />
              </button>
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
                className="px-2 py-1.5 rounded border border-[var(--border-primary)] text-[var(--text-muted)] hover:text-cyan-300 hover:border-cyan-500/40 text-[9px]"
                title="Copy Master JSON"
              >
                <Copy size={11} />
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
                className="px-2 py-1.5 rounded border border-[var(--border-primary)] text-[var(--text-muted)] hover:text-cyan-300 hover:border-cyan-500/40 text-[9px]"
                title="Export Master JSON"
              >
                <Download size={11} />
              </button>
            </div>

            {feedback && (
              <div className="text-[9px] text-cyan-300 border border-cyan-500/30 bg-cyan-950/20 rounded px-2 py-1">
                {feedback}
              </div>
            )}

            {datasets.length === 0 ? (
              <div className="text-[9px] text-[var(--text-muted)] border border-[var(--border-primary)] rounded px-2 py-2">
                No Custom Intel datasets loaded.
              </div>
            ) : (
              datasets.map((dataset) => {
                const severity = deriveDatasetMaxWeight(dataset);
                const severityColor = getCustomIntelWeightColor(severity);
                const expanded = Boolean(expandedDatasets[dataset.datasetId]);

                return (
                  <div key={dataset.datasetId} className="rounded border border-[var(--border-primary)] bg-[var(--bg-secondary)]/40">
                    <div className="p-2 flex items-start justify-between gap-2">
                      <button
                        onClick={() => setExpandedDatasets((prev) => ({ ...prev, [dataset.datasetId]: !expanded }))}
                        className="text-left flex-1"
                      >
                        <div className="text-[10px] font-bold text-[var(--text-primary)] leading-tight">{dataset.title}</div>
                        <div className="mt-1 text-[8px] text-[var(--text-muted)] tracking-wider">
                          {dataset.story_id ? `${dataset.story_id} · ` : ""}{dataset.stories.length} stories · {dataset.eventCount} events · latest {getDatasetLatestDateLabel(dataset)}
                        </div>
                      </button>

                      <div className="flex items-center gap-1">
                        <span
                          className={`text-[8px] px-1.5 py-0.5 rounded border ${severityColor.text}`}
                          style={{ borderColor: `${severityColor.stroke}80`, backgroundColor: `${severityColor.fill}22` }}
                          title="Highest event weight"
                        >
                          W{severity}
                        </span>
                        <button
                          onClick={() => onToggleDatasetVisibility(dataset.datasetId)}
                          className="w-6 h-6 rounded border border-[var(--border-primary)] flex items-center justify-center text-[var(--text-muted)] hover:text-cyan-300"
                          title={dataset.visible ? "Hide dataset" : "Show dataset"}
                        >
                          {dataset.visible ? <Eye size={12} /> : <EyeOff size={12} />}
                        </button>
                        <button
                          onClick={() => {
                            if (window.confirm("Delete this dataset? This cannot be undone.")) {
                              onDeleteDataset(dataset.datasetId);
                            }
                          }}
                          className="w-6 h-6 rounded border border-[var(--border-primary)] flex items-center justify-center text-[var(--text-muted)] hover:text-red-400 hover:border-red-500/40"
                          title="Delete dataset"
                        >
                          <Trash2 size={12} />
                        </button>
                      </div>
                    </div>

                    <AnimatePresence>
                      {expanded && (
                        <motion.div
                          initial={{ height: 0, opacity: 0 }}
                          animate={{ height: "auto", opacity: 1 }}
                          exit={{ height: 0, opacity: 0 }}
                          className="overflow-hidden border-t border-[var(--border-primary)]/60"
                        >
                          <div className="p-2 flex flex-col gap-1 max-h-[170px] overflow-y-auto styled-scrollbar">
                            {dataset.stories.map((story) => (
                              <div key={story.story_id} className="rounded border border-[var(--border-primary)]/70 p-1.5">
                                <div className="text-[9px] text-cyan-300 font-bold mb-1">{story.title}</div>
                                <div className="flex flex-col gap-1">
                                  {story.events.map((event, idx) => {
                                    const eventId = resolveEventId(story.story_id, event.id, idx);
                                    const weight = typeof event.weight === "number" ? event.weight : 1;
                                    const wc = getCustomIntelWeightColor(weight);
                                    return (
                                      <div key={eventId} className="flex items-start justify-between gap-2 text-[8px]">
                                        <div className="min-w-0">
                                          <div className="text-[var(--text-primary)] truncate">{event.name || "Unnamed Event"}</div>
                                          <div className="text-[var(--text-muted)] truncate">{event.date || event.start_date || "No date"} · {event.location_label || "Unknown location"}</div>
                                        </div>
                                        <div className="flex items-center gap-1">
                                          <span
                                            className={`px-1 rounded border ${wc.text}`}
                                            style={{ borderColor: `${wc.stroke}88`, backgroundColor: `${wc.fill}22` }}
                                          >
                                            W{Math.max(1, Math.min(5, Math.round(weight)))}
                                          </span>
                                          <button
                                            onClick={() => {
                                              if (window.confirm("Delete this event?")) {
                                                onDeleteEvent(dataset.datasetId, eventId);
                                              }
                                            }}
                                            className="w-5 h-5 rounded border border-[var(--border-primary)] text-[var(--text-muted)] hover:text-red-400 hover:border-red-500/40 flex items-center justify-center"
                                            title="Delete event"
                                          >
                                            <Trash2 size={10} />
                                          </button>
                                        </div>
                                      </div>
                                    );
                                  })}
                                </div>
                              </div>
                            ))}
                          </div>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </div>
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
                    <X size={12} />
                  </button>
                </div>
                <div className="p-4 flex flex-col gap-3">
                  <textarea
                    value={importRaw}
                    onChange={(e) => setImportRaw(e.target.value)}
                    placeholder='Paste exported CustomIntelStore JSON...'
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
