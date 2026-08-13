'use client';

// Investigation Workspace — the investigation-first surface.
//
// A full-screen analytical overlay combining an investigation list with a
// detailed workspace (overview, timeline, entities, evidence, hypotheses,
// AI-style briefing). Facts and inferences are kept visually distinct and
// confidence is always explainable. Reuses the main map via onFocusLocation.

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import * as api from '@/lib/investigationsApi';
import { ApiError } from '@/lib/investigationsApi';
import type {
  Briefing,
  Classification,
  Evidence,
  Investigation,
  InvestigationBundle,
} from '@/types/investigation';
import {
  ClassificationBadge,
  ConfidenceMeter,
  EmptyState,
  ErrorState,
  LoadingState,
  Section,
  SeverityPill,
  StatusPill,
  fmtTime,
} from './primitives';

type Tab = 'overview' | 'timeline' | 'entities' | 'evidence' | 'hypotheses' | 'briefing';

const TABS: { id: Tab; label: string }[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'timeline', label: 'Timeline' },
  { id: 'entities', label: 'Entities' },
  { id: 'evidence', label: 'Evidence' },
  { id: 'hypotheses', label: 'Hypotheses' },
  { id: 'briefing', label: 'Briefing' },
];

export interface InvestigationsWorkspaceProps {
  onClose: () => void;
  onFocusLocation?: (lat: number, lng: number) => void;
}

export default function InvestigationsWorkspace({ onClose, onFocusLocation }: InvestigationsWorkspaceProps) {
  const [list, setList] = useState<Investigation[] | null>(null);
  const [listError, setListError] = useState<string>('');
  const [selectedId, setSelectedId] = useState<string>('');
  const [creating, setCreating] = useState(false);

  const loadList = useCallback(async () => {
    setListError('');
    try {
      const res = await api.listInvestigations();
      setList(res.investigations);
      setSelectedId((cur) => cur || (res.investigations[0]?.id ?? ''));
    } catch (e) {
      setListError(e instanceof ApiError ? e.message : 'Failed to load investigations');
      setList([]);
    }
  }, []);

  useEffect(() => {
    loadList();
  }, [loadList]);

  // Close on Escape.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-[2000] flex flex-col bg-black/95 text-slate-200 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label="Investigation workspace"
    >
      {/* Header */}
      <header className="flex items-center justify-between border-b border-cyan-500/30 px-4 py-2">
        <div className="flex items-center gap-3">
          <h1 className="text-sm font-bold uppercase tracking-[0.25em] text-cyan-300">
            Investigations
          </h1>
          <span className="text-[10px] uppercase tracking-wider text-slate-500">
            Question → Evidence → Correlation → Hypothesis
          </span>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded border border-cyan-500/40 px-3 py-1 text-xs uppercase tracking-wider text-cyan-300 hover:bg-cyan-950/40"
          aria-label="Close investigations"
        >
          ✕ Close
        </button>
      </header>

      <div className="flex min-h-0 flex-1">
        {/* Left rail: list */}
        <aside className="flex w-72 shrink-0 flex-col border-r border-cyan-500/20 bg-black/60">
          <div className="border-b border-cyan-500/20 p-2">
            <button
              type="button"
              onClick={() => setCreating(true)}
              className="w-full rounded border border-cyan-500/50 bg-cyan-950/30 px-2 py-1.5 text-xs font-semibold uppercase tracking-wider text-cyan-200 hover:bg-cyan-900/40"
            >
              + New investigation
            </button>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">
            {listError ? (
              <div className="p-2">
                <ErrorState message={listError} onRetry={loadList} />
              </div>
            ) : list === null ? (
              <LoadingState />
            ) : list.length === 0 ? (
              <div className="p-2">
                <EmptyState label="No investigations yet. Create one to begin." />
              </div>
            ) : (
              <ul>
                {list.map((inv) => (
                  <li key={inv.id}>
                    <button
                      type="button"
                      onClick={() => setSelectedId(inv.id)}
                      className={`flex w-full flex-col gap-1 border-b border-slate-800/60 px-3 py-2 text-left hover:bg-cyan-950/20 ${
                        selectedId === inv.id ? 'bg-cyan-950/30' : ''
                      }`}
                    >
                      <span className="truncate text-sm text-slate-100">{inv.title}</span>
                      <span className="flex items-center gap-2">
                        <StatusPill value={inv.status} />
                        <span className="text-[10px] text-slate-500">
                          {inv.entity_ids.length}E · {inv.event_ids.length}Ev
                        </span>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </aside>

        {/* Main detail */}
        <main className="min-h-0 flex-1 overflow-y-auto">
          {creating ? (
            <CreateForm
              onCancel={() => setCreating(false)}
              onCreated={(inv) => {
                setCreating(false);
                setList((cur) => [inv, ...(cur || [])]);
                setSelectedId(inv.id);
              }}
            />
          ) : selectedId ? (
            <InvestigationDetail
              key={selectedId}
              id={selectedId}
              onFocusLocation={onFocusLocation}
              onChanged={loadList}
              onDeleted={() => {
                setSelectedId('');
                loadList();
              }}
            />
          ) : (
            <div className="p-8">
              <EmptyState label="Select an investigation, or create a new one." />
            </div>
          )}
        </main>
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------- //
function CreateForm({
  onCancel,
  onCreated,
}: {
  onCancel: () => void;
  onCreated: (inv: Investigation) => void;
}) {
  const [title, setTitle] = useState('');
  const [question, setQuestion] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim()) return;
    setBusy(true);
    setError('');
    try {
      const inv = await api.createInvestigation({ title: title.trim(), question: question.trim() });
      onCreated(inv);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to create');
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="mx-auto max-w-lg p-6">
      <h2 className="mb-4 text-sm font-semibold uppercase tracking-widest text-cyan-400">
        New investigation
      </h2>
      <label className="mb-1 block text-[11px] uppercase tracking-wide text-slate-400">Title</label>
      <input
        autoFocus
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="e.g. Black Sea Activity — Aug 13"
        className="mb-3 w-full rounded border border-cyan-500/30 bg-black/60 px-2 py-1.5 text-sm text-slate-100 outline-none focus:border-cyan-400"
      />
      <label className="mb-1 block text-[11px] uppercase tracking-wide text-slate-400">
        Central question
      </label>
      <textarea
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
        placeholder="What happened, where, when, who/what is involved, how do we know?"
        rows={3}
        className="mb-3 w-full rounded border border-cyan-500/30 bg-black/60 px-2 py-1.5 text-sm text-slate-100 outline-none focus:border-cyan-400"
      />
      {error && <p className="mb-3 text-xs text-red-400">{error}</p>}
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={busy || !title.trim()}
          className="rounded border border-cyan-500/50 bg-cyan-950/40 px-3 py-1.5 text-xs font-semibold uppercase tracking-wider text-cyan-200 hover:bg-cyan-900/50 disabled:opacity-40"
        >
          {busy ? 'Creating…' : 'Create'}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded border border-slate-600/50 px-3 py-1.5 text-xs uppercase tracking-wider text-slate-400 hover:bg-slate-800/40"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}

// --------------------------------------------------------------------------- //
function InvestigationDetail({
  id,
  onFocusLocation,
  onChanged,
  onDeleted,
}: {
  id: string;
  onFocusLocation?: (lat: number, lng: number) => void;
  onChanged: () => void;
  onDeleted: () => void;
}) {
  const [bundle, setBundle] = useState<InvestigationBundle | null>(null);
  const [error, setError] = useState('');
  const [tab, setTab] = useState<Tab>('overview');

  const load = useCallback(async () => {
    setError('');
    try {
      setBundle(await api.getInvestigation(id));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Failed to load investigation');
    }
  }, [id]);

  // After a mutation, refresh both the detail bundle and the sidebar list
  // (so its per-investigation entity/event counts stay in sync).
  const refresh = useCallback(async () => {
    await load();
    onChanged();
  }, [load, onChanged]);

  useEffect(() => {
    load();
  }, [load]);

  if (error) return <div className="p-6"><ErrorState message={error} onRetry={load} /></div>;
  if (!bundle) return <LoadingState label="Loading investigation…" />;

  const inv = bundle.investigation;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* Detail header */}
      <div className="border-b border-cyan-500/20 px-5 py-3">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-bold text-slate-100">{inv.title}</h2>
              <StatusPill value={inv.status} />
            </div>
            {inv.question && (
              <p className="mt-1 max-w-2xl text-sm text-slate-400">
                <span className="text-cyan-500">Q:</span> {inv.question}
              </p>
            )}
          </div>
          <button
            type="button"
            onClick={async () => {
              if (!confirm('Delete this investigation and all its evidence/hypotheses?')) return;
              try {
                await api.deleteInvestigation(id);
                onDeleted();
              } catch {
                /* surfaced via reload */
              }
            }}
            className="rounded border border-red-500/40 px-2 py-1 text-[11px] uppercase tracking-wide text-red-300 hover:bg-red-950/40"
          >
            Delete
          </button>
        </div>
        {/* Summary strip */}
        <div className="mt-3 flex flex-wrap gap-2 text-[11px]">
          <Metric label="Entities" value={bundle.counts.entities} />
          <Metric label="Events" value={bundle.counts.events} />
          <Metric label="Evidence" value={bundle.counts.evidence} />
          <Metric label="Hypotheses" value={bundle.counts.hypotheses} />
          <Metric label="Notes" value={bundle.counts.notes} />
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-cyan-500/20 px-4">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            className={`border-b-2 px-3 py-2 text-xs font-semibold uppercase tracking-wider ${
              tab === t.id
                ? 'border-cyan-400 text-cyan-200'
                : 'border-transparent text-slate-500 hover:text-slate-300'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab body */}
      <div className="min-h-0 flex-1 overflow-y-auto p-5">
        {tab === 'overview' && <OverviewTab bundle={bundle} />}
        {tab === 'timeline' && <TimelineTab bundle={bundle} onFocusLocation={onFocusLocation} />}
        {tab === 'entities' && <EntitiesTab bundle={bundle} onFocusLocation={onFocusLocation} />}
        {tab === 'evidence' && <EvidenceTab id={id} bundle={bundle} onChanged={refresh} />}
        {tab === 'hypotheses' && <HypothesesTab id={id} bundle={bundle} onChanged={refresh} />}
        {tab === 'briefing' && <BriefingTab id={id} />}
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <span className="rounded border border-slate-700/60 bg-black/40 px-2 py-1">
      <span className="font-mono font-bold text-cyan-200">{value}</span>{' '}
      <span className="uppercase tracking-wide text-slate-500">{label}</span>
    </span>
  );
}

function OverviewTab({ bundle }: { bundle: InvestigationBundle }) {
  const facts = bundle.evidence.filter((e) => e.classification === 'raw_observation' || e.classification === 'derived_event');
  const inferences = bundle.evidence.filter((e) => e.classification === 'analysis' || e.classification === 'hypothesis');
  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
      <div>
        <Section title="Facts (observations & derived events)">
          {facts.length === 0 ? (
            <EmptyState label="No factual evidence yet." />
          ) : (
            <ul className="space-y-2">
              {facts.map((e) => (
                <EvidenceRow key={e.id} e={e} />
              ))}
            </ul>
          )}
        </Section>
        <Section title="Key entities">
          {bundle.entities.length === 0 ? (
            <EmptyState label="No entities attached." />
          ) : (
            <ul className="flex flex-wrap gap-2">
              {bundle.entities.map((en) => (
                <li key={en.id} className="rounded border border-cyan-500/30 bg-black/40 px-2 py-1 text-xs">
                  <span className="text-[10px] uppercase tracking-wide text-cyan-500">{en.type}</span>{' '}
                  <span className="text-slate-200">{en.label}</span>
                </li>
              ))}
            </ul>
          )}
        </Section>
      </div>
      <div>
        <Section title="Analysis & inference">
          {inferences.length === 0 ? (
            <EmptyState label="No analysis yet." />
          ) : (
            <ul className="space-y-2">
              {inferences.map((e) => (
                <EvidenceRow key={e.id} e={e} />
              ))}
            </ul>
          )}
        </Section>
        <Section title="Hypotheses">
          {bundle.hypotheses.length === 0 ? (
            <EmptyState label="No hypotheses yet." />
          ) : (
            <ul className="space-y-3">
              {bundle.hypotheses.map((h) => (
                <li key={h.id} className="rounded border border-dashed border-violet-400/40 bg-violet-950/20 p-3">
                  <div className="mb-1 flex items-center gap-2">
                    <ClassificationBadge value="hypothesis" />
                    <span className="text-[10px] uppercase tracking-wide text-slate-500">{h.status}</span>
                  </div>
                  <p className="mb-2 text-sm text-slate-200">{h.statement}</p>
                  <ConfidenceMeter confidence={h.confidence} />
                </li>
              ))}
            </ul>
          )}
        </Section>
      </div>
    </div>
  );
}

function EvidenceRow({ e }: { e: Evidence }) {
  return (
    <li className="rounded border border-slate-700/60 bg-black/30 p-2">
      <div className="mb-1 flex items-center gap-2">
        <ClassificationBadge value={e.classification} />
        <span className="text-sm text-slate-200">{e.title}</span>
      </div>
      {e.description && <p className="text-xs text-slate-400">{e.description}</p>}
      {(e.provenance?.source_name || e.provenance?.source_url) && (
        <p className="mt-1 text-[10px] text-slate-500">
          Source: {e.provenance.source_name || 'unknown'}
          {e.provenance.source_url ? ` · ${e.provenance.source_url}` : ''}
          {e.provenance.method ? ` · ${e.provenance.method}` : ''}
        </p>
      )}
    </li>
  );
}

function TimelineTab({
  bundle,
  onFocusLocation,
}: {
  bundle: InvestigationBundle;
  onFocusLocation?: (lat: number, lng: number) => void;
}) {
  if (bundle.timeline.length === 0) return <EmptyState label="No timeline items yet." />;
  return (
    <ol className="relative ml-3 border-l border-cyan-500/30">
      {bundle.timeline.map((item, i) => (
        <li key={`${item.ref_id}-${i}`} className="mb-4 ml-4">
          <span className="absolute -left-[5px] mt-1 h-2 w-2 rounded-full bg-cyan-400" aria-hidden />
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-[11px] text-cyan-500">{fmtTime(item.ts)}</span>
            <ClassificationBadge value={item.classification} />
            {item.severity && <SeverityPill value={item.severity} />}
            <span className="text-sm text-slate-200">{item.title}</span>
          </div>
          {item.summary && <p className="mt-0.5 text-xs text-slate-400">{item.summary}</p>}
          {item.lat != null && item.lng != null && onFocusLocation && (
            <button
              type="button"
              onClick={() => onFocusLocation(item.lat as number, item.lng as number)}
              className="mt-1 text-[10px] uppercase tracking-wide text-cyan-500 hover:text-cyan-300"
            >
              ▸ Show on map
            </button>
          )}
        </li>
      ))}
    </ol>
  );
}

function EntitiesTab({
  bundle,
  onFocusLocation,
}: {
  bundle: InvestigationBundle;
  onFocusLocation?: (lat: number, lng: number) => void;
}) {
  if (bundle.entities.length === 0) return <EmptyState label="No entities attached to this investigation." />;
  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
      {bundle.entities.map((en) => (
        <div key={en.id} className="rounded border border-cyan-500/30 bg-black/40 p-3">
          <div className="mb-1 flex items-center justify-between">
            <span className="text-[10px] uppercase tracking-wider text-cyan-500">{en.type}</span>
            {en.lat != null && en.lng != null && onFocusLocation && (
              <button
                type="button"
                onClick={() => onFocusLocation(en.lat as number, en.lng as number)}
                className="text-[10px] uppercase tracking-wide text-cyan-500 hover:text-cyan-300"
              >
                map ▸
              </button>
            )}
          </div>
          <p className="text-sm font-semibold text-slate-100">{en.label}</p>
          {en.canonical_key && <p className="text-[11px] text-slate-500">{en.canonical_key}</p>}
          <p className="mt-1 text-[10px] text-slate-600">Last seen {fmtTime(en.last_seen)}</p>
        </div>
      ))}
    </div>
  );
}

function EvidenceTab({
  id,
  bundle,
  onChanged,
}: {
  id: string;
  bundle: InvestigationBundle;
  onChanged: () => void;
}) {
  const [adding, setAdding] = useState(false);
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [classification, setClassification] = useState('raw_observation');
  const [sourceName, setSourceName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim()) return;
    setBusy(true);
    setError('');
    try {
      await api.addEvidence(id, {
        title: title.trim(),
        description: description.trim(),
        classification,
        kind: classification === 'analysis' ? 'correlation' : 'observation',
        provenance: sourceName ? { source_name: sourceName.trim() } : undefined,
      });
      setTitle('');
      setDescription('');
      setSourceName('');
      setAdding(false);
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to add evidence');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <Section
        title="Evidence"
        action={
          <button
            type="button"
            onClick={() => setAdding((a) => !a)}
            className="text-[11px] uppercase tracking-wide text-cyan-400 hover:text-cyan-200"
          >
            {adding ? 'Cancel' : '+ Add evidence'}
          </button>
        }
      >
        {adding && (
          <form onSubmit={submit} className="mb-4 space-y-2 rounded border border-cyan-500/30 bg-black/40 p-3">
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Evidence title"
              className="w-full rounded border border-cyan-500/30 bg-black/60 px-2 py-1 text-sm text-slate-100 outline-none focus:border-cyan-400"
            />
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Description"
              rows={2}
              className="w-full rounded border border-cyan-500/30 bg-black/60 px-2 py-1 text-sm text-slate-100 outline-none focus:border-cyan-400"
            />
            <div className="flex gap-2">
              <select
                value={classification}
                onChange={(e) => setClassification(e.target.value)}
                className="rounded border border-cyan-500/30 bg-black/60 px-2 py-1 text-xs text-slate-100"
                aria-label="Classification"
              >
                <option value="raw_observation">Raw observation (fact)</option>
                <option value="derived_event">Derived event (fact)</option>
                <option value="analysis">Analysis (inference)</option>
              </select>
              <input
                value={sourceName}
                onChange={(e) => setSourceName(e.target.value)}
                placeholder="Source (e.g. OpenSky)"
                className="flex-1 rounded border border-cyan-500/30 bg-black/60 px-2 py-1 text-xs text-slate-100 outline-none focus:border-cyan-400"
              />
            </div>
            {error && <p className="text-xs text-red-400">{error}</p>}
            <button
              type="submit"
              disabled={busy || !title.trim()}
              className="rounded border border-cyan-500/50 bg-cyan-950/40 px-3 py-1 text-xs uppercase tracking-wide text-cyan-200 hover:bg-cyan-900/50 disabled:opacity-40"
            >
              {busy ? 'Adding…' : 'Add evidence'}
            </button>
          </form>
        )}
        {bundle.evidence.length === 0 ? (
          <EmptyState label="No evidence attached. Add raw observations to ground the investigation in fact." />
        ) : (
          <ul className="space-y-2">
            {bundle.evidence.map((e) => (
              <EvidenceRow key={e.id} e={e} />
            ))}
          </ul>
        )}
      </Section>
    </div>
  );
}

function HypothesesTab({
  id,
  bundle,
  onChanged,
}: {
  id: string;
  bundle: InvestigationBundle;
  onChanged: () => void;
}) {
  const [statement, setStatement] = useState('');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const toggle = (evId: string) =>
    setSelected((s) => {
      const n = new Set(s);
      if (n.has(evId)) n.delete(evId);
      else n.add(evId);
      return n;
    });

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!statement.trim()) return;
    setBusy(true);
    setError('');
    try {
      await api.createHypothesis(id, {
        statement: statement.trim(),
        supporting_evidence_ids: Array.from(selected),
      });
      setStatement('');
      setSelected(new Set());
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to create hypothesis');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
      <Section title="Hypotheses (inferences — never facts)">
        {bundle.hypotheses.length === 0 ? (
          <EmptyState label="No hypotheses yet." />
        ) : (
          <ul className="space-y-3">
            {bundle.hypotheses.map((h) => (
              <li key={h.id} className="rounded border border-dashed border-violet-400/50 bg-violet-950/20 p-3">
                <div className="mb-1 flex items-center gap-2">
                  <ClassificationBadge value="hypothesis" />
                  <span className="text-[10px] uppercase tracking-wide text-slate-500">{h.status}</span>
                </div>
                <p className="mb-2 text-sm text-slate-200">{h.statement}</p>
                <ConfidenceMeter confidence={h.confidence} />
              </li>
            ))}
          </ul>
        )}
      </Section>
      <Section title="Propose a hypothesis">
        <form onSubmit={submit} className="space-y-2 rounded border border-violet-400/30 bg-black/40 p-3">
          <textarea
            value={statement}
            onChange={(e) => setStatement(e.target.value)}
            placeholder="e.g. The movement may be associated with coordinated activity nearby."
            rows={3}
            className="w-full rounded border border-violet-400/30 bg-black/60 px-2 py-1.5 text-sm text-slate-100 outline-none focus:border-violet-300"
          />
          <p className="text-[11px] uppercase tracking-wide text-slate-500">
            Link supporting evidence (confidence is derived from it):
          </p>
          <div className="max-h-40 space-y-1 overflow-y-auto">
            {bundle.evidence.length === 0 ? (
              <p className="text-xs text-slate-600">No evidence to link yet.</p>
            ) : (
              bundle.evidence.map((ev) => (
                <label key={ev.id} className="flex cursor-pointer items-center gap-2 text-xs text-slate-300">
                  <input type="checkbox" checked={selected.has(ev.id)} onChange={() => toggle(ev.id)} />
                  <ClassificationBadge value={ev.classification} />
                  <span className="truncate">{ev.title}</span>
                </label>
              ))
            )}
          </div>
          {error && <p className="text-xs text-red-400">{error}</p>}
          <button
            type="submit"
            disabled={busy || !statement.trim()}
            className="rounded border border-violet-400/50 bg-violet-950/40 px-3 py-1 text-xs uppercase tracking-wide text-violet-200 hover:bg-violet-900/50 disabled:opacity-40"
          >
            {busy ? 'Creating…' : 'Create hypothesis'}
          </button>
        </form>
      </Section>
    </div>
  );
}

function BriefingTab({ id }: { id: string }) {
  const [briefing, setBriefing] = useState<Briefing | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const generate = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      setBriefing(await api.getBriefing(id));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Failed to generate briefing');
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    generate();
  }, [generate]);

  const next = useMemo(() => briefing?.recommended_next_steps ?? [], [briefing]);

  if (loading) return <LoadingState label="Generating briefing…" />;
  if (error) return <ErrorState message={error} onRetry={generate} />;
  if (!briefing) return <EmptyState label="No briefing available." />;

  return (
    <div className="mx-auto max-w-3xl">
      <Section title="Executive summary">
        <div className="flex flex-wrap gap-2 text-[11px]">
          <Metric label="Entities" value={briefing.summary.entities} />
          <Metric label="Facts" value={briefing.summary.facts} />
          <Metric label="Inferences" value={briefing.summary.inferences} />
          <Metric label="Hypotheses" value={briefing.summary.hypotheses} />
        </div>
        <p className="mt-2 text-sm text-slate-300">{briefing.summary.question}</p>
      </Section>

      <Section title="Key facts">
        {briefing.key_facts.length === 0 ? (
          <EmptyState label="No factual evidence recorded." />
        ) : (
          <ul className="space-y-1">
            {briefing.key_facts.map((f) => (
              <li key={f.id} className="flex items-center gap-2 text-sm text-slate-200">
                <ClassificationBadge value={f.classification as Classification} />
                <span>{f.title}</span>
                {f.source && <span className="text-[10px] text-slate-500">· {f.source}</span>}
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="Hypotheses & confidence">
        {briefing.hypotheses.length === 0 ? (
          <EmptyState label="No hypotheses formed." />
        ) : (
          <ul className="space-y-3">
            {briefing.hypotheses.map((h, i) => (
              <li key={i} className="rounded border border-dashed border-violet-400/40 bg-violet-950/20 p-3">
                <div className="mb-1 flex items-center gap-2">
                  <ClassificationBadge value="hypothesis" />
                  <span className="text-[10px] uppercase tracking-wide text-slate-500">{h.status}</span>
                </div>
                <p className="mb-2 text-sm text-slate-200">{h.statement}</p>
                <ConfidenceMeter confidence={h.confidence} />
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="Recommended next steps">
        {next.length === 0 ? (
          <EmptyState label="None." />
        ) : (
          <ol className="list-decimal space-y-1 pl-5 text-sm text-slate-300">
            {next.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ol>
        )}
      </Section>

      <p className="mt-4 rounded border border-amber-500/30 bg-amber-950/20 p-2 text-[11px] text-amber-300">
        {briefing.caveat}
      </p>
    </div>
  );
}
