'use client';



import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';

import { Terminal } from 'lucide-react';

import { Terminal as XTerm } from '@xterm/xterm';

import { FitAddon } from '@xterm/addon-fit';

import '@xterm/xterm/css/xterm.css';

import { mintAgentShellWsToken, resolveAgentShellWsUrl } from '@/lib/agentShellWs';



const SHELL_FONT_PX = 14;

const CWD_STORAGE_KEY = 'sb_agent_shell_cwd';

const INTRO_ACK_KEY = 'sb_agent_shell_intro_ack';



type Props = {

  active: boolean;

  expanded: boolean;

  onExpandedChange: (expanded: boolean) => void;

};



function readStoredCwd(): string {

  if (typeof window === 'undefined') return '';

  try {

    return window.localStorage.getItem(CWD_STORAGE_KEY) || '';

  } catch {

    return '';

  }

}



function readIntroAcknowledged(): boolean {

  if (typeof window === 'undefined') return false;

  try {

    return window.localStorage.getItem(INTRO_ACK_KEY) === '1';

  } catch {

    return false;

  }

}



function ShellIntro({ onAcknowledge }: { onAcknowledge: () => void }) {

  return (

    <div className="flex-1 min-h-0 flex flex-col items-center justify-center px-5 py-8 text-center border-l-2 border-cyan-800/20 bg-[#04070b]">

      <div className="w-full max-w-sm border border-cyan-900/40 bg-cyan-950/10 px-5 py-6">

        <div className="inline-flex items-center justify-center w-10 h-10 border border-cyan-700/40 bg-black/30 text-cyan-300 mb-4">

          <Terminal size={18} />

        </div>

        <div className="text-sm font-mono tracking-[0.22em] text-cyan-300 mb-3">OPERATOR SHELL</div>

        <p className="text-[13px] font-mono text-[var(--text-secondary)] leading-[1.75] text-left">

          Connect your own agent CLIs here — OpenClaw, Codex, Gemini, or whatever you run locally.

        </p>

        <p className="mt-3 text-[13px] font-mono text-[var(--text-secondary)] leading-[1.75] text-left">

          The session opens in your Shadowbroker workspace by default. Use it for repo scripts, mesh

          tools, or any terminal workflow you already rely on.

        </p>

        <button

          type="button"

          onClick={onAcknowledge}

          className="mt-5 w-full px-4 py-2.5 text-sm font-mono tracking-[0.18em] text-cyan-200 border border-cyan-600/50 bg-cyan-950/30 hover:bg-cyan-950/50 hover:border-cyan-400/60 transition-colors"

        >

          OPEN SHELL

        </button>

      </div>

    </div>

  );

}



export default function AgentShellPanel({ active, expanded, onExpandedChange }: Props) {

  const hostRef = useRef<HTMLDivElement>(null);

  const termRef = useRef<XTerm | null>(null);

  const fitRef = useRef<FitAddon | null>(null);

  const wsRef = useRef<WebSocket | null>(null);

  const [introAcknowledged, setIntroAcknowledged] = useState(false);

  const [status, setStatus] = useState<'idle' | 'connecting' | 'open' | 'error'>('idle');

  const [statusDetail, setStatusDetail] = useState('');

  const [cwd, setCwd] = useState('');



  const shellReady = active && introAcknowledged;



  useEffect(() => {

    setIntroAcknowledged(readIntroAcknowledged());

  }, [active]);



  const acknowledgeIntro = useCallback(() => {

    try {

      window.localStorage.setItem(INTRO_ACK_KEY, '1');

    } catch {

      // still allow in-session access if storage is blocked

    }

    setIntroAcknowledged(true);

  }, []);



  const disconnect = useCallback(() => {

    wsRef.current?.close();

    wsRef.current = null;

    termRef.current?.dispose();

    termRef.current = null;

    fitRef.current = null;

    setStatus('idle');

  }, []);



  const fitTerminal = useCallback(() => {

    const fit = fitRef.current;

    const term = termRef.current;

    const ws = wsRef.current;

    if (!fit || !term) return;

    fit.fit();

    if (ws?.readyState === WebSocket.OPEN) {

      ws.send(

        JSON.stringify({

          type: 'resize',

          cols: term.cols,

          rows: term.rows,

        }),

      );

    }

  }, []);



  const connect = useCallback(() => {

    if (!hostRef.current) return;

    if (wsRef.current) {

      wsRef.current.close();

      wsRef.current = null;

    }

    if (termRef.current) {

      termRef.current.dispose();

      termRef.current = null;

      fitRef.current = null;

    }



    const term = new XTerm({

      fontFamily: 'var(--font-roboto-mono), ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',

      fontSize: SHELL_FONT_PX,

      lineHeight: 1.35,

      cursorBlink: true,

      theme: {

        background: '#04070b',

        foreground: '#d9f7ff',

        cursor: '#22d3ee',

        selectionBackground: '#0e7490',

      },

      scrollback: 5000,

    });

    const fit = new FitAddon();

    term.loadAddon(fit);

    term.open(hostRef.current);

    fit.fit();

    termRef.current = term;

    fitRef.current = fit;



    const storedCwd = readStoredCwd();

    setCwd(storedCwd);

    setStatus('connecting');

    setStatusDetail('');



    void (async () => {
      const wsToken = await mintAgentShellWsToken();
      const ws = new WebSocket(resolveAgentShellWsUrl(storedCwd, wsToken ?? undefined));
      ws.binaryType = 'arraybuffer';

      wsRef.current = ws;



    ws.onopen = () => {

      setStatus('open');

      fit.fit();

      ws.send(

        JSON.stringify({

          type: 'resize',

          cols: term.cols,

          rows: term.rows,

        }),

      );

      term.focus();

    };



    ws.onmessage = (event) => {

      if (typeof event.data === 'string') {

        try {

          const payload = JSON.parse(event.data) as { type?: string; message?: string };

          if (payload.type === 'error') {

            setStatus('error');

            setStatusDetail(payload.message || 'Shell unavailable');

            term.writeln(`\r\n\x1b[31m${payload.message || 'Shell unavailable'}\x1b[0m`);

            return;

          }

        } catch {

          term.write(event.data);

          return;

        }

      }

      if (event.data instanceof ArrayBuffer) {

        term.write(new Uint8Array(event.data));

      }

    };



    ws.onerror = () => {

      setStatus('error');

      setStatusDetail('Could not connect to the local agent shell endpoint.');

      term.writeln('\r\n\x1b[31mCould not connect to the local agent shell endpoint.\x1b[0m');

    };



    ws.onclose = (event) => {

      if (event.code === 4403) {

        setStatus('error');

        setStatusDetail('Local operator access only — reload the dashboard on localhost and retry.');

        term.writeln('\r\n\x1b[31mShell blocked: local operator access only.\x1b[0m');

        return;

      }

      setStatus((prev) => (prev === 'error' ? prev : 'idle'));

      if (event.code !== 1000) {

        term.writeln(`\r\n\x1b[90m[session closed: ${event.code}]\x1b[0m`);

      }

    };



    term.onData((data) => {

      if (ws.readyState === WebSocket.OPEN) {

        ws.send(new TextEncoder().encode(data));

      }

    });
    })();
  }, []);



  useLayoutEffect(() => {

    if (!shellReady) {

      disconnect();

      return;

    }

    let cancelled = false;

    const start = () => {

      if (cancelled || !hostRef.current) return;

      if (!wsRef.current || wsRef.current.readyState === WebSocket.CLOSED) {

        connect();

      } else {

        fitTerminal();

      }

    };

    const frame = requestAnimationFrame(() => requestAnimationFrame(start));

    return () => {

      cancelled = true;

      cancelAnimationFrame(frame);

    };

  }, [shellReady, connect, disconnect, fitTerminal]);



  useEffect(() => {

    if (!shellReady) return;

    const host = hostRef.current;

    if (!host) return;

    const ro = new ResizeObserver(() => fitTerminal());

    ro.observe(host);

    const timer = window.setTimeout(() => fitTerminal(), expanded ? 240 : 32);

    return () => {

      ro.disconnect();

      window.clearTimeout(timer);

    };

  }, [shellReady, expanded, fitTerminal]);



  useEffect(() => {

    if (!shellReady) return;

    const onResize = () => fitTerminal();

    window.addEventListener('resize', onResize);

    return () => window.removeEventListener('resize', onResize);

  }, [shellReady, fitTerminal]);



  if (!active) {

    return (

      <div className="flex-1 min-h-0 flex flex-col items-center justify-center px-4 py-6 text-center border-l-2 border-cyan-800/20">

        <Terminal size={16} className="text-cyan-400 mb-2" />

        <div className="text-sm font-mono tracking-[0.2em] text-cyan-300">LOCAL SHELL</div>

        <div className="mt-2 text-[13px] font-mono text-[var(--text-secondary)] leading-relaxed">

          Expand Meshtastic Chat to open your operator shell.

        </div>

      </div>

    );

  }



  if (!introAcknowledged) {

    return <ShellIntro onAcknowledge={acknowledgeIntro} />;

  }



  return (

    <div className="flex-1 min-h-0 flex flex-col border-l-2 border-cyan-800/25 bg-[#04070b]">

      <div className="flex items-center justify-between gap-2 border-b border-cyan-900/40 px-2 py-1.5 shrink-0">

        <div className="min-w-0 text-[12px] font-mono tracking-[0.14em] text-cyan-300/90 truncate">

          {cwd ? cwd : 'operator shell'}

        </div>

        <div className="flex items-center gap-1 shrink-0">

          {!expanded ? (

            <button

              type="button"

              onClick={() => onExpandedChange(true)}

              className="px-2 py-0.5 text-[11px] font-mono tracking-[0.12em] text-cyan-300 border border-cyan-800/40 hover:bg-cyan-950/30"

            >

              EXPAND

            </button>

          ) : (

            <button

              type="button"

              onClick={() => onExpandedChange(false)}

              className="px-2 py-0.5 text-[11px] font-mono tracking-[0.12em] text-cyan-300 border border-cyan-800/40 hover:bg-cyan-950/30"

            >

              SNAP

            </button>

          )}

          <button

            type="button"

            onClick={connect}

            className="px-2 py-0.5 text-[11px] font-mono tracking-[0.12em] text-slate-400 border border-slate-700/40 hover:bg-white/5"

          >

            RECONNECT

          </button>

        </div>

      </div>



      {status === 'error' && statusDetail && (

        <div className="px-2 py-1 text-[12px] font-mono text-amber-300/90 border-b border-amber-900/30 bg-amber-950/10 shrink-0">

          {statusDetail}

        </div>

      )}



      {status === 'connecting' && (

        <div className="px-2 py-1 text-[11px] font-mono text-slate-500 border-b border-cyan-900/20 shrink-0">

          Connecting…

        </div>

      )}



      <div

        ref={hostRef}

        className="flex-1 min-h-[220px] min-w-0 px-1 py-1 overflow-hidden [&_.xterm]:h-full [&_.xterm]:w-full [&_.xterm-viewport]:!overflow-y-auto"

      />

    </div>

  );

}


