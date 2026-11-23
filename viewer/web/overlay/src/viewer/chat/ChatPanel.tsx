'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { MessagesSquare, Minus, Plus, Send, Flag, LogOut } from 'lucide-react';
import { VIEWER_CHAT } from '../config';
import {
  ChatError,
  MESSAGE_MAX,
  chatConfigured,
  claimUsername,
  completeOAuthReturn,
  fetchMessages,
  fetchUsername,
  freshSession,
  loadSession,
  postMessage,
  reportMessage,
  signInWithPassword,
  signOut,
  signUpWithPassword,
  startOAuth,
  type ChatMessage,
  type ChatSession,
  type OAuthProvider,
} from './chatClient';

const POLL_MS = 5000;
const KEEP_MESSAGES = 200;

const PROVIDER_LABEL: Record<OAuthProvider, string> = { google: 'Google', facebook: 'Facebook' };

function timeLabel(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function errorText(error: unknown): string {
  return error instanceof ChatError ? error.message : 'Something went wrong. Try again.';
}

const inputClass =
  'w-full rounded-md border border-[var(--border-primary)] bg-black/30 px-2.5 py-1.5 text-[12px] font-mono text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-cyan-500/60';
const buttonClass =
  'sb-chip flex items-center justify-center gap-1.5 px-3 py-1.5 text-[10.5px] font-mono tracking-[0.14em] uppercase text-cyan-300 hover:text-cyan-100 disabled:opacity-50 disabled:cursor-not-allowed';

/**
 * Public chat room. Reading is open to everyone; posting needs a sign-in
 * (Google, Facebook, or email and password) and a chosen username. All of
 * it lives on the separate chat service, never on the ShadowBroker engine.
 */
export default function ChatPanel() {
  const [expanded, setExpanded] = useState(true);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [session, setSession] = useState<ChatSession | null>(null);
  const [username, setUsername] = useState<string | null>(null);
  const [view, setView] = useState<'room' | 'signin'>('room');
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [wantedName, setWantedName] = useState('');
  const [reported, setReported] = useState<Set<number>>(new Set());
  const listRef = useRef<HTMLDivElement>(null);
  const lastIdRef = useRef<number | null>(null);
  const sessionRef = useRef<ChatSession | null>(null);
  sessionRef.current = session;

  const adopt = useCallback(async (next: ChatSession | null) => {
    setSession(next);
    setUsername(null);
    if (!next) return;
    try {
      setUsername(await fetchUsername(next));
    } catch (error) {
      setNotice(errorText(error));
    }
  }, []);

  // Restore a saved session, or finish a provider sign-in that just returned.
  useEffect(() => {
    if (!chatConfigured()) return;
    let cancelled = false;
    void (async () => {
      try {
        const returned = await completeOAuthReturn();
        const current = returned ?? (await freshSession(loadSession()));
        if (!cancelled) await adopt(current);
      } catch (error) {
        if (!cancelled) setNotice(errorText(error));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [adopt]);

  const appendMessages = useCallback((incoming: ChatMessage[]) => {
    if (incoming.length === 0) return;
    setMessages((prev) => {
      const seen = new Set(prev.map((m) => m.id));
      const merged = [...prev, ...incoming.filter((m) => !seen.has(m.id))].sort((a, b) => a.id - b.id);
      lastIdRef.current = merged.length ? merged[merged.length - 1].id : lastIdRef.current;
      return merged.slice(-KEEP_MESSAGES);
    });
  }, []);

  // Load and refresh messages while the panel is open and the tab is visible.
  useEffect(() => {
    if (!chatConfigured() || !expanded) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const tick = async () => {
      if (stopped) return;
      if (!document.hidden) {
        try {
          appendMessages(await fetchMessages(lastIdRef.current, sessionRef.current?.accessToken));
        } catch {
          /* shown as an empty room; retried on the next tick */
        }
      }
      timer = setTimeout(tick, POLL_MS);
    };
    void tick();
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
    };
  }, [appendMessages, expanded]);

  // Stay pinned to the newest message.
  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, expanded, view]);

  const run = async (work: () => Promise<void>) => {
    if (busy) return;
    setBusy(true);
    setNotice(null);
    try {
      await work();
    } catch (error) {
      setNotice(errorText(error));
    } finally {
      setBusy(false);
    }
  };

  const withSession = async (): Promise<ChatSession> => {
    const current = await freshSession(sessionRef.current);
    if (!current) {
      setSession(null);
      setUsername(null);
      throw new ChatError('Please sign in again.');
    }
    if (current !== sessionRef.current) setSession(current);
    return current;
  };

  const handleSend = () =>
    run(async () => {
      const text = draft.trim();
      if (!text) return;
      const saved = await postMessage(await withSession(), text);
      setDraft('');
      appendMessages([saved]);
    });

  const handleSignIn = () =>
    run(async () => {
      await adopt(await signInWithPassword(email.trim(), password));
      setPassword('');
      setView('room');
    });

  const handleSignUp = () =>
    run(async () => {
      if (password.length < 8) throw new ChatError('Use a password of at least 8 characters.');
      const created = await signUpWithPassword(email.trim(), password);
      setPassword('');
      if (created) {
        await adopt(created);
        setView('room');
      } else {
        setNotice('Check your email for a confirmation link, then sign in here.');
      }
    });

  const handleClaim = () =>
    run(async () => {
      setUsername(await claimUsername(await withSession(), wantedName));
    });

  const handleSignOut = () =>
    run(async () => {
      await signOut(sessionRef.current);
      setSession(null);
      setUsername(null);
    });

  const handleReport = (id: number) =>
    run(async () => {
      await reportMessage(await withSession(), id);
      setReported((prev) => new Set(prev).add(id));
    });

  if (!chatConfigured()) return null;

  return (
    <div
      className={`sb-panel pointer-events-auto flex flex-col overflow-hidden ${expanded ? 'flex-[2.4_1_0%] min-h-[260px]' : 'flex-shrink-0'}`}
    >
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        className="flex items-center gap-2 px-3 py-2.5 text-left hover:bg-cyan-950/30 transition-colors"
      >
        <MessagesSquare size={15} className="text-cyan-400 shrink-0" aria-hidden="true" />
        <span className="sb-title text-cyan-300">CHAT</span>
        {username && (
          <span className="ml-1 truncate text-[10px] font-mono tracking-wider text-[var(--text-muted)]">
            as {username}
          </span>
        )}
        <span className="ml-auto text-cyan-400">{expanded ? <Minus size={15} /> : <Plus size={15} />}</span>
      </button>

      {expanded && view === 'room' && (
        <>
          <div
            ref={listRef}
            className="flex-1 min-h-0 overflow-y-auto styled-scrollbar border-t border-[var(--border-primary)] px-3 py-2 space-y-1.5"
            aria-live="polite"
          >
            {messages.length === 0 && (
              <div className="py-6 text-center text-[11.5px] text-[var(--text-muted)]">
                No messages yet. Say something.
              </div>
            )}
            {messages.map((m) => (
              <div key={m.id} className="group text-[12.5px] leading-snug">
                <span className="font-mono text-[10px] text-[var(--text-muted)]">{timeLabel(m.created_at)} </span>
                <span className="font-mono font-bold text-cyan-300">{m.username}</span>
                <span className="text-[var(--text-muted)]">: </span>
                {/* Plain text only: React escapes it, and links are not made clickable. */}
                <span className="sb-prose text-[var(--text-primary)] break-words">{m.body}</span>
                {username && m.username !== username && (
                  <button
                    type="button"
                    onClick={() => void handleReport(m.id)}
                    disabled={reported.has(m.id)}
                    title={reported.has(m.id) ? 'Reported' : 'Report this message'}
                    aria-label={reported.has(m.id) ? 'Reported' : `Report message from ${m.username}`}
                    className="ml-1.5 align-middle text-[var(--text-muted)] opacity-0 group-hover:opacity-100 focus:opacity-100 hover:text-amber-300 disabled:text-amber-400 disabled:opacity-100"
                  >
                    <Flag size={10} />
                  </button>
                )}
              </div>
            ))}
          </div>

          <div className="border-t border-[var(--border-primary)] px-3 py-2.5 space-y-2">
            {notice && (
              <div role="status" className="text-[11px] text-amber-300">
                {notice}
              </div>
            )}

            {!session && (
              <button type="button" className={`${buttonClass} w-full`} onClick={() => { setNotice(null); setView('signin'); }}>
                Sign in to chat
              </button>
            )}

            {session && !username && (
              <form
                className="space-y-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  void handleClaim();
                }}
              >
                <label className="block text-[11px] text-[var(--text-muted)]" htmlFor="sb-chat-name">
                  Pick a username. It is public and cannot be changed.
                </label>
                <div className="flex gap-2">
                  <input
                    id="sb-chat-name"
                    className={inputClass}
                    value={wantedName}
                    onChange={(e) => setWantedName(e.target.value)}
                    placeholder="3 to 20 letters, numbers, _"
                    maxLength={20}
                    autoComplete="off"
                  />
                  <button type="submit" className={buttonClass} disabled={busy}>
                    Save
                  </button>
                </div>
              </form>
            )}

            {session && username && (
              <form
                className="flex gap-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  void handleSend();
                }}
              >
                <input
                  className={inputClass}
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  placeholder="Message everyone…"
                  maxLength={MESSAGE_MAX}
                  aria-label="Message"
                  autoComplete="off"
                />
                <button type="submit" className={buttonClass} disabled={busy || !draft.trim()} aria-label="Send">
                  <Send size={12} />
                </button>
              </form>
            )}

            <div className="flex items-center gap-2 text-[10px] text-[var(--text-muted)]">
              <span>Public room. Be decent, no spam.</span>
              {session && (
                <button
                  type="button"
                  onClick={() => void handleSignOut()}
                  className="ml-auto flex items-center gap-1 hover:text-cyan-200"
                >
                  <LogOut size={10} /> Sign out
                </button>
              )}
            </div>
          </div>
        </>
      )}

      {expanded && view === 'signin' && (
        <div className="flex-1 min-h-0 overflow-y-auto styled-scrollbar border-t border-[var(--border-primary)] px-3 py-3 space-y-2.5">
          {VIEWER_CHAT.providers.map((provider) => (
            <button key={provider} type="button" className={`${buttonClass} w-full`} onClick={() => startOAuth(provider)}>
              Continue with {PROVIDER_LABEL[provider]}
            </button>
          ))}
          {VIEWER_CHAT.providers.length > 0 && (
            <div className="text-center text-[10px] font-mono tracking-[0.14em] text-[var(--text-muted)]">OR</div>
          )}
          <form
            className="space-y-2"
            onSubmit={(e) => {
              e.preventDefault();
              void handleSignIn();
            }}
          >
            <input
              className={inputClass}
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="Email"
              aria-label="Email"
              autoComplete="email"
              required
            />
            <input
              className={inputClass}
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Password"
              aria-label="Password"
              autoComplete="current-password"
              required
            />
            <div className="flex gap-2">
              <button type="submit" className={`${buttonClass} flex-1`} disabled={busy}>
                Sign in
              </button>
              <button type="button" className={`${buttonClass} flex-1`} disabled={busy} onClick={() => void handleSignUp()}>
                Create account
              </button>
            </div>
          </form>
          {notice && (
            <div role="status" className="text-[11px] text-amber-300">
              {notice}
            </div>
          )}
          <p className="text-[10.5px] leading-relaxed text-[var(--text-muted)]">
            Sign-in is handled by a separate login service. This site never sees or stores your password. Only your
            chosen username is shown to others.
          </p>
          <button type="button" className="text-[10.5px] text-cyan-300 hover:text-cyan-100" onClick={() => { setNotice(null); setView('room'); }}>
            ← Back to the room
          </button>
        </div>
      )}
    </div>
  );
}
