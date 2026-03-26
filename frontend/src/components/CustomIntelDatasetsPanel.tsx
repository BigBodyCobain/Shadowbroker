"use client";

import React, { useMemo, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ChevronDown, ChevronUp, Plus, Trash2, AlertTriangle, Clock, Download } from "lucide-react";
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
  onExportMasterJson: () => void;
}

const CustomIntelDatasetsPanel = React.memo(function CustomIntelDatasetsPanel({
  events,
  layerActive,
  onAddDataset,
  onDeleteEvent,
  onExportMasterJson,
}: CustomIntelDatasetsPanelProps) {
  const [minimized, setMinimized] = useState(false);
  const [expandedSources, setExpandedSources] = useState<Record<string, boolean>>({});
  const [feedback, setFeedback] = useState<string | null>(null);

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
            <div className="flex items-center justify-between gap-2">
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onAddDataset();
                }}
                className="px-2 py-1.5 rounded border border-cyan-500/40 bg-cyan-950/25 text-cyan-300 hover:text-cyan-200 hover:border-cyan-400 text-[9px] tracking-wider flex items-center gap-1"
              >
                <Plus size={11} /> ADD INTEL DATASET
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
                className="h-[28px] w-[28px] rounded border border-[var(--border-primary)] text-[var(--text-muted)] hover:text-cyan-300 hover:border-cyan-500/40 flex items-center justify-center transition-colors"
                title="Export Master JSON"
                aria-label="Export Master JSON"
              >
                <Download size={12} />
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
    </motion.div>
  );
});

export default CustomIntelDatasetsPanel;
