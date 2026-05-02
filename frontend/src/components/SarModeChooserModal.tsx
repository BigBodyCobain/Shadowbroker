'use client';

import React, { useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { X, ExternalLink, Radar, Check, Zap, Globe } from 'lucide-react';
import { API_BASE } from '@/lib/api';

export const SAR_CHOICE_KEY = 'shadowbroker_sar_mode_choice';
export type SarChoice = 'a_only' | 'b_active' | null;

interface SarModeChooserModalProps {
  onClose: () => void;
  /** Called after the user makes a persistent choice.  The parent uses
   *  this to flip the layer toggle on without prompting again. */
  onChoiceMade: (choice: SarChoice) => void;
}

const MODE_B_EXTRAS = [
  {
    title: 'Ground Deformation (mm-scale)',
    desc: 'NASA OPERA DISP + Copernicus EGMS — detects subsidence, landslides, building collapse, dam stress.',
  },
  {
    title: 'Surface Water Change',
    desc: 'OPERA DSWx — daily flood extent polygons from Sentinel-1, even through cloud cover.',
  },
  {
    title: 'Vegetation Disturbance',
    desc: 'OPERA DIST-ALERT — deforestation, burn scars, blast craters.',
  },
  {
    title: 'Damage Assessments',
    desc: 'UNOSAT + Copernicus EMS — hand-verified damage polygons from active disaster/conflict zones.',
  },
  {
    title: 'Global Flood Monitoring (no account)',
    desc: 'GFM daily Sentinel-1 flood masks — activates with any Mode B setup.',
  },
];

const SIGNUP_STEPS = [
  {
    n: 1,
    label: 'Create a free NASA Earthdata Login',
    url: 'https://urs.earthdata.nasa.gov/users/new',
    why: 'Takes about 1 minute. Used only to authorize OPERA product downloads.',
  },
  {
    n: 2,
    label: 'Generate an Earthdata user token',
    url: 'https://urs.earthdata.nasa.gov/profile',
    why: 'After login → "Generate Token". Copy the token string (NOT your password).',
  },
  {
    n: 3,
    label: 'Paste the token below and click "Activate Mode B"',
    url: '',
    why: 'Stored only on this node, in backend/data/sar_runtime.json. You can revoke it anytime.',
  },
];

const SarModeChooserModal = React.memo(function SarModeChooserModal({
  onClose,
  onChoiceMade,
}: SarModeChooserModalProps) {
  const [view, setView] = useState<'chooser' | 'signup'>('chooser');
  const [earthdataToken, setEarthdataToken] = useState('');
  const [earthdataUser, setEarthdataUser] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string>('');
  const [mounted, setMounted] = useState(false);

  // Portal target — document.body.  We wait until mount so SSR doesn't
  // try to touch `document`.  Without the portal, the modal renders inside
  // the left HUD container which has a CSS transform on an ancestor,
  // breaking `position: fixed` and clipping it to a 320px-wide scrollable
  // strip (which is why focusing the input made it "disappear").
  useEffect(() => {
    setMounted(true);
  }, []);

  const pickAOnly = () => {
    try {
      localStorage.setItem(SAR_CHOICE_KEY, 'a_only');
    } catch {
      // localStorage unavailable — still close the modal
    }
    onChoiceMade('a_only');
    onClose();
  };

  const submitModeB = async () => {
    if (earthdataToken.trim().length < 8) {
      setError('Earthdata token looks too short. Paste the full token string.');
      return;
    }
    setSubmitting(true);
    setError('');
    try {
      const res = await fetch(`${API_BASE}/api/sar/mode-b/enable`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          earthdata_user: earthdataUser.trim(),
          earthdata_token: earthdataToken.trim(),
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        // FastAPI validation errors come back as {detail: [{msg, loc, ...}]},
        // plain auth errors come back as {detail: "string"}.  Normalize both.
        let msg = `HTTP ${res.status}`;
        const d = body?.detail;
        if (typeof d === 'string') {
          msg = d;
        } else if (Array.isArray(d) && d.length > 0) {
          msg = d
            .map((item) => {
              if (typeof item === 'string') return item;
              const loc = Array.isArray(item?.loc)
                ? item.loc.slice(1).join('.')
                : '';
              return loc
                ? `${loc}: ${item?.msg || 'invalid'}`
                : item?.msg || JSON.stringify(item);
            })
            .join('; ');
        } else if (d && typeof d === 'object') {
          msg = JSON.stringify(d);
        }
        throw new Error(msg);
      }
      try {
        localStorage.setItem(SAR_CHOICE_KEY, 'b_active');
      } catch {
        // ignore
      }
      onChoiceMade('b_active');
      onClose();
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : 'Failed to activate Mode B. Check the backend logs.',
      );
    } finally {
      setSubmitting(false);
    }
  };

  if (!mounted) return null;

  return createPortal(
    <AnimatePresence>
      <motion.div
        key="sar-backdrop"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        // Only close if BOTH mousedown and mouseup land on the backdrop
        // itself.  Otherwise a drag-select inside the token input that
        // ends outside the modal box would fire a click on the backdrop
        // and dismiss the modal.
        onMouseDown={(e) => {
          if (e.target === e.currentTarget) {
            (e.currentTarget as HTMLElement).dataset.downOnBackdrop = '1';
          } else {
            (e.currentTarget as HTMLElement).dataset.downOnBackdrop = '';
          }
        }}
        onMouseUp={(e) => {
          const el = e.currentTarget as HTMLElement;
          const wasDown = el.dataset.downOnBackdrop === '1';
          el.dataset.downOnBackdrop = '';
          if (wasDown && e.target === e.currentTarget) {
            onClose();
          }
        }}
        style={{ direction: 'ltr' }}
        className="fixed inset-0 z-[9999] bg-black/80 backdrop-blur-sm flex items-center justify-center p-4"
      >
        <motion.div
          key="sar-modal"
          initial={{ scale: 0.94, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          exit={{ scale: 0.94, opacity: 0 }}
          transition={{ type: 'spring', damping: 22, stiffness: 260 }}
          onClick={(e) => e.stopPropagation()}
          className="relative w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-lg border border-cyan-500/40 bg-zinc-950/95 text-cyan-100 shadow-[0_0_40px_rgba(0,200,255,0.25)]"
        >
          {/* Header */}
          <div className="sticky top-0 z-10 flex items-center justify-between gap-3 border-b border-cyan-500/30 bg-zinc-950/95 px-5 py-3">
            <div className="flex items-center gap-2">
              <Radar size={18} className="text-cyan-400" />
              <span className="text-sm font-semibold tracking-wide">
                SAR GROUND-CHANGE LAYER
              </span>
            </div>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close"
              className="rounded p-1 text-cyan-300 hover:bg-cyan-500/10"
            >
              <X size={16} />
            </button>
          </div>

          {view === 'chooser' && (
            <div className="p-5 space-y-5">
              <div className="text-sm text-cyan-200/90">
                SAR (synthetic aperture radar) detects ground changes through cloud
                cover, at night, anywhere on Earth. ShadowBroker offers two modes —
                both free. Pick one.
              </div>

              {/* Mode A */}
              <div className="rounded border border-cyan-400/30 bg-cyan-500/5 p-4">
                <div className="flex items-center gap-2 mb-1">
                  <Globe size={14} className="text-cyan-300" />
                  <span className="text-sm font-semibold text-cyan-200">
                    MODE A — Catalog only (default)
                  </span>
                </div>
                <div className="text-xs text-cyan-200/70 mb-3">
                  Free Sentinel-1 scene metadata from Alaska Satellite Facility. No
                  account, no downloads, no credentials. Tells you when radar
                  passes happened over your AOIs and when the next pass is coming.
                </div>
                <button
                  type="button"
                  onClick={pickAOnly}
                  className="w-full rounded border border-cyan-400/60 bg-cyan-500/10 px-4 py-2 text-xs font-semibold text-cyan-100 hover:bg-cyan-500/20 transition"
                >
                  <Check size={12} className="inline mr-1" />
                  Mode A is fine — don&apos;t ask again
                </button>
              </div>

              {/* Mode B */}
              <div className="rounded border border-amber-400/40 bg-amber-500/5 p-4">
                <div className="flex items-center gap-2 mb-1">
                  <Zap size={14} className="text-amber-300" />
                  <span className="text-sm font-semibold text-amber-200">
                    MODE B — Full ground-change alerts
                  </span>
                </div>
                <div className="text-xs text-amber-200/80 mb-3">
                  Adds pre-computed anomalies from NASA OPERA, Copernicus EGMS,
                  GFM, EMS, and UNOSAT. Requires a free NASA Earthdata account
                  (~1 minute).
                </div>
                <ul className="text-xs text-amber-100/80 space-y-1 mb-3">
                  {MODE_B_EXTRAS.map((x) => (
                    <li key={x.title} className="flex gap-2">
                      <span className="text-amber-400 mt-0.5">+</span>
                      <span>
                        <span className="font-semibold text-amber-200">
                          {x.title}:
                        </span>{' '}
                        <span className="text-amber-100/70">{x.desc}</span>
                      </span>
                    </li>
                  ))}
                </ul>
                <button
                  type="button"
                  onClick={() => setView('signup')}
                  className="w-full rounded border border-amber-400/60 bg-amber-500/10 px-4 py-2 text-xs font-semibold text-amber-100 hover:bg-amber-500/20 transition"
                >
                  Set up Mode B (free, ~1 min) →
                </button>
              </div>
            </div>
          )}

          {view === 'signup' && (
            <div className="p-5 space-y-4">
              <button
                type="button"
                onClick={() => setView('chooser')}
                className="text-xs text-cyan-400/80 hover:text-cyan-300"
              >
                ← back
              </button>

              <div className="text-sm font-semibold text-amber-200">
                Activate Mode B
              </div>

              <ol className="space-y-3">
                {SIGNUP_STEPS.map((s) => (
                  <li
                    key={s.n}
                    className="rounded border border-amber-400/25 bg-amber-500/5 p-3"
                  >
                    <div className="flex items-start gap-3">
                      <span className="flex-shrink-0 w-6 h-6 rounded-full bg-amber-500/20 border border-amber-400/40 text-amber-200 text-xs font-bold flex items-center justify-center">
                        {s.n}
                      </span>
                      <div className="flex-1 text-xs">
                        <div className="font-semibold text-amber-100">
                          {s.label}
                        </div>
                        <div className="text-amber-100/70 mt-0.5">{s.why}</div>
                        {s.url && (
                          <a
                            href={s.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="mt-1 inline-flex items-center gap-1 text-amber-300 hover:text-amber-200 underline"
                          >
                            {s.url}
                            <ExternalLink size={10} />
                          </a>
                        )}
                      </div>
                    </div>
                  </li>
                ))}
              </ol>

              <div className="space-y-2 pt-1">
                <label
                  htmlFor="sar-earthdata-user"
                  className="block text-xs text-amber-200/80"
                >
                  Earthdata username (optional)
                </label>
                <input
                  id="sar-earthdata-user"
                  name="sar-earthdata-user"
                  type="text"
                  value={earthdataUser}
                  onChange={(e) => setEarthdataUser(e.target.value)}
                  placeholder="yourname"
                  autoComplete="off"
                  autoCorrect="off"
                  autoCapitalize="off"
                  spellCheck={false}
                  data-lpignore="true"
                  data-1p-ignore="true"
                  data-form-type="other"
                  className="w-full rounded border border-amber-400/30 bg-zinc-900 px-3 py-2 text-xs text-amber-100 placeholder:text-amber-100/30 focus:border-amber-400/70 focus:outline-none"
                />

                <label
                  htmlFor="sar-earthdata-token"
                  className="block text-xs text-amber-200/80 mt-2"
                >
                  Earthdata user token (required)
                </label>
                <input
                  id="sar-earthdata-token"
                  name="sar-earthdata-token"
                  type="text"
                  value={earthdataToken}
                  onChange={(e) => setEarthdataToken(e.target.value)}
                  placeholder="eyJ0eXAiOiJKV1QiLCJhbGciOi..."
                  autoComplete="off"
                  autoCorrect="off"
                  autoCapitalize="off"
                  spellCheck={false}
                  data-lpignore="true"
                  data-1p-ignore="true"
                  data-form-type="other"
                  className="w-full rounded border border-amber-400/30 bg-zinc-900 px-3 py-2 text-xs text-amber-100 placeholder:text-amber-100/30 focus:border-amber-400/70 focus:outline-none font-mono tracking-tight"
                />
                <div className="text-[10px] text-amber-100/50">
                  Stored locally on this node only. Never shared. Revoke anytime
                  in Settings → SAR.
                </div>
              </div>

              {error && (
                <div className="rounded border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-200">
                  {error}
                </div>
              )}

              <button
                type="button"
                onClick={submitModeB}
                disabled={submitting || earthdataToken.trim().length < 8}
                className="w-full rounded border border-amber-400/60 bg-amber-500/20 px-4 py-2 text-xs font-semibold text-amber-100 hover:bg-amber-500/30 disabled:opacity-40 disabled:cursor-not-allowed transition"
              >
                {submitting ? 'Activating…' : 'Activate Mode B'}
              </button>
            </div>
          )}
        </motion.div>
      </motion.div>
    </AnimatePresence>,
    document.body,
  );
});

export default SarModeChooserModal;
