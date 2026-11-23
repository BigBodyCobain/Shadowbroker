'use client';

import React, { useEffect, useMemo, useState } from 'react';
import { Bot, Check, Copy, Download, ShieldCheck, X } from 'lucide-react';
import { VIEWER_DATA_BASE } from './config';

/**
 * "View and vet" screen for the public agent skill.
 *
 * Nobody should hand an AI agent instructions they have not read. This shows
 * every file of the skill, in full and as plain text, exactly as an agent
 * would receive it, with a fingerprint for each so it can be compared with
 * the source. The files are copied into the site at build time; the build
 * refuses hidden or invisible characters in them.
 */

type SkillFile = { name: string; role: string; bytes: number; lines: number; sha256: string };
type SkillManifest = {
  name: string;
  source: string;
  checks: string[];
  files: SkillFile[];
};

const SKILL_BASE = '/skill';

const FACTS: { good: boolean; text: string }[] = [
  { good: true, text: 'Reads the same public data files this page uses. Nothing else.' },
  { good: true, text: 'Needs no account, no API key and no ShadowBroker install.' },
  { good: true, text: 'Is plain text instructions plus one Python file that uses only the standard library.' },
  { good: false, text: 'Cannot send, post, message, pin or change anything. Those commands refuse without making a request.' },
  { good: false, text: 'Does not look up people. It covers vehicles, places and events.' },
];

function useEscape(onClose: () => void) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
}

export function SkillButton({ onOpen }: { onOpen: () => void }) {
  return (
    <button
      type="button"
      onClick={onOpen}
      className="mt-2 flex w-full items-center gap-2.5 rounded-lg border border-violet-400/30 bg-violet-500/10 px-3 py-2 text-left transition-colors hover:border-violet-300/70 hover:bg-violet-500/15"
    >
      <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-violet-400/15 text-violet-300">
        <Bot size={16} aria-hidden="true" />
      </span>
      <span className="flex min-w-0 flex-col">
        <span className="text-[10.5px] font-mono font-bold tracking-[0.14em] uppercase text-[var(--text-primary)]">
          AI agent skill
        </span>
        <span className="truncate text-[11px] text-[var(--text-muted)]">Read every line before you install it</span>
      </span>
    </button>
  );
}

export default function SkillModal({ onClose }: { onClose: () => void }) {
  useEscape(onClose);
  const [manifest, setManifest] = useState<SkillManifest | null>(null);
  const [texts, setTexts] = useState<Record<string, string>>({});
  const [active, setActive] = useState<string>('SKILL.md');
  const [problem, setProblem] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const res = await fetch(`${SKILL_BASE}/manifest.json`, { cache: 'no-store' });
        if (!res.ok) throw new Error('missing');
        const m = (await res.json()) as SkillManifest;
        const loaded: Record<string, string> = {};
        for (const file of m.files) {
          const r = await fetch(`${SKILL_BASE}/${file.name}`, { cache: 'no-store' });
          if (!r.ok) throw new Error(file.name);
          loaded[file.name] = await r.text();
        }
        if (cancelled) return;
        setManifest(m);
        setTexts(loaded);
        if (m.files[0]) setActive(m.files[0].name);
      } catch {
        if (!cancelled) setProblem('The skill files could not be loaded. You can still read them at the source link.');
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const feedUrl = useMemo(() => {
    if (typeof window === 'undefined') return VIEWER_DATA_BASE;
    return new URL(VIEWER_DATA_BASE, window.location.href).href.replace(/\/+$/, '');
  }, []);

  const file = manifest?.files.find((f) => f.name === active) || null;
  const text = file ? texts[file.name] || '' : '';

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked: the text is still selectable */
    }
  };

  return (
    <div
      className="fixed inset-0 z-[9500] flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
      role="dialog"
      aria-modal="true"
      aria-label="AI agent skill: view and vet"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="sb-panel flex max-h-[92vh] w-full max-w-[980px] flex-col px-6 py-5 pointer-events-auto">
        <div className="flex items-start gap-3">
          <Bot size={18} className="mt-0.5 shrink-0 text-violet-300" aria-hidden="true" />
          <div className="min-w-0">
            <h2 className="sb-title text-[15px] text-violet-200">SHADOWBROKER AGENT SKILL</h2>
            <p className="sb-prose mt-1 text-[12.5px] text-[var(--text-muted)]">
              Give your own AI agent read-only access to this map&apos;s data. Read it first: every file is below, in
              full, exactly as your agent would receive it.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="ml-auto rounded-md p-1 text-cyan-400 transition-colors hover:text-cyan-200"
          >
            <X size={16} />
          </button>
        </div>

        <div className="mt-4 grid min-h-0 flex-1 grid-cols-1 gap-4 overflow-y-auto styled-scrollbar lg:grid-cols-[300px_1fr] lg:overflow-hidden">
          {/* What it is, and how to check it */}
          <div className="space-y-4 text-[12.5px] lg:overflow-y-auto lg:pr-1 styled-scrollbar">
            <ul className="space-y-2">
              {FACTS.map((fact) => (
                <li key={fact.text} className="flex gap-2">
                  <span className={`mt-0.5 shrink-0 ${fact.good ? 'text-emerald-300' : 'text-amber-300'}`} aria-hidden="true">
                    {fact.good ? <Check size={13} /> : <X size={13} />}
                  </span>
                  <span className="sb-prose text-[var(--text-primary)]">{fact.text}</span>
                </li>
              ))}
            </ul>

            <div className="rounded-lg border border-[var(--border-primary)] p-3">
              <div className="flex items-center gap-1.5 text-[10.5px] font-mono font-bold tracking-[0.14em] text-emerald-300">
                <ShieldCheck size={13} aria-hidden="true" /> HOW TO CHECK IT
              </div>
              <ol className="sb-prose mt-2 list-decimal space-y-1.5 pl-4 text-[12px] text-[var(--text-primary)]">
                <li>Read the instructions tab. It is short, and it is all your agent is told.</li>
                <li>Skim the code tab. It only downloads files from one address and searches them.</li>
                <li>
                  Compare each file&apos;s fingerprint with{' '}
                  {manifest ? (
                    <a href={manifest.source} target="_blank" rel="noopener noreferrer" className="text-cyan-300 hover:text-cyan-100">
                      the source on GitHub ↗
                    </a>
                  ) : (
                    'the source on GitHub'
                  )}
                  .
                </li>
              </ol>
              {manifest && manifest.checks.length > 0 && (
                <ul className="mt-2.5 space-y-1 border-t border-[var(--border-primary)] pt-2 text-[11px] text-[var(--text-muted)]">
                  {manifest.checks.map((c) => (
                    <li key={c}>✓ {c}</li>
                  ))}
                </ul>
              )}
            </div>

            <div>
              <div className="text-[10.5px] font-mono font-bold tracking-[0.14em] text-[var(--text-secondary)]">TO USE IT</div>
              <ol className="sb-prose mt-1.5 list-decimal space-y-1.5 pl-4 text-[12px] text-[var(--text-primary)]">
                <li>Download the files into your agent&apos;s skills folder.</li>
                <li>
                  Set one setting, the address of this site&apos;s data:
                  <code className="mt-1 block break-all rounded bg-black/40 px-2 py-1 font-mono text-[10.5px] text-cyan-200">
                    SHADOWBROKER_PUBLIC_URL={feedUrl}
                  </code>
                </li>
                <li>Ask your agent, for example: &quot;where is N189AM?&quot;</li>
              </ol>
            </div>
          </div>

          {/* The files themselves */}
          <div className="flex min-h-[320px] min-w-0 flex-col lg:min-h-0">
            {problem && <div className="text-[12px] text-amber-300">{problem}</div>}
            {!manifest && !problem && <div className="text-[12px] text-[var(--text-muted)]">Loading the skill files…</div>}
            {manifest && (
              <>
                <div role="tablist" aria-label="Skill files" className="flex flex-wrap gap-1.5">
                  {manifest.files.map((f) => (
                    <button
                      key={f.name}
                      type="button"
                      role="tab"
                      aria-selected={f.name === active}
                      onClick={() => setActive(f.name)}
                      className={`rounded-md border px-2.5 py-1 font-mono text-[11px] transition-colors ${
                        f.name === active
                          ? 'border-violet-300/70 bg-violet-500/15 text-violet-100'
                          : 'border-[var(--border-primary)] text-[var(--text-muted)] hover:text-[var(--text-primary)]'
                      }`}
                    >
                      {f.name}
                      <span className="ml-1.5 text-[10px] opacity-70">{f.role}</span>
                    </button>
                  ))}
                </div>
                {file && (
                  <>
                    <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10.5px] font-mono text-[var(--text-muted)]">
                      <span>
                        {file.lines.toLocaleString()} lines · {(file.bytes / 1024).toFixed(1)} KB
                      </span>
                      <span className="break-all" title="SHA-256 fingerprint of this exact file">
                        sha256 {file.sha256}
                      </span>
                      <span className="ml-auto flex gap-1.5">
                        <button type="button" onClick={() => void copy()} className="sb-chip flex items-center gap-1 px-2 py-1 text-cyan-300 hover:text-cyan-100">
                          {copied ? <Check size={11} /> : <Copy size={11} />}
                          {copied ? 'Copied' : 'Copy'}
                        </button>
                        <a href={`${SKILL_BASE}/${file.name}`} download={file.name} className="sb-chip flex items-center gap-1 px-2 py-1 text-cyan-300 hover:text-cyan-100">
                          <Download size={11} /> Download
                        </a>
                      </span>
                    </div>
                    {/* Raw text on purpose: nothing is rendered, hidden or collapsed. */}
                    <pre
                      tabIndex={0}
                      aria-label={`Full text of ${file.name}`}
                      className="styled-scrollbar mt-2 min-h-0 flex-1 overflow-auto whitespace-pre rounded-lg border border-[var(--border-primary)] bg-black/45 p-3 font-mono text-[11.5px] leading-[1.55] text-[var(--text-primary)]"
                    >
                      {text}
                    </pre>
                  </>
                )}
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
