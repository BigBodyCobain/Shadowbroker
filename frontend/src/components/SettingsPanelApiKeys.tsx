'use client';

import React from 'react';
import { AnimatePresence, motion } from '@/lib/motion';
import { ChevronDown, ChevronUp, Copy, ExternalLink, Key, Save, Shield } from 'lucide-react';
import { CATEGORY_COLORS, type ApiEntry, type EnvMeta } from './SettingsPanel.shared';

interface SettingsPanelApiKeysCtx {
  envMeta: EnvMeta | null;
  apis: ApiEntry[];
  grouped: Record<string, ApiEntry[]>;
  expandedCategories: Set<string>;
  toggleCategory: (cat: string) => void;
  fetchKeys: () => Promise<any>;
  adminSessionReady: boolean;
  showOperatorTools: boolean;
  apiKeyInputs: Record<string, string>;
  apiKeyEditing: Record<string, boolean>;
  apiKeySaving: string | null;
  apiKeyMsg: { type: 'ok' | 'err'; text: string } | null;
  setApiKeyInputs: React.Dispatch<React.SetStateAction<Record<string, string>>>;
  setApiKeyEditing: React.Dispatch<React.SetStateAction<Record<string, boolean>>>;
  saveApiKey: (envKey: string | null) => Promise<void>;
  CATEGORY_COLORS?: Record<string, string>;
}

export function SettingsPanelApiKeys({ ctx }: { ctx: SettingsPanelApiKeysCtx }) {
  const {
    envMeta, apis, grouped, expandedCategories, toggleCategory,
    fetchKeys, adminSessionReady, showOperatorTools,
    apiKeyInputs, apiKeyEditing, apiKeySaving, apiKeyMsg,
    setApiKeyInputs, setApiKeyEditing, saveApiKey,
    CATEGORY_COLORS: catColors,
  } = ctx;
  const CC = catColors || CATEGORY_COLORS;
            <>
              {/* Info Banner */}
              <div className="mx-4 mt-4 p-3 border border-cyan-900/30 bg-cyan-950/10 space-y-2">
                <div className="flex items-start gap-2">
                  <Shield size={12} className="text-cyan-500 mt-0.5 flex-shrink-0" />
                  <p className="text-sm sb-prose text-[#c3d2e6] leading-relaxed">
                    API keys are saved locally by this backend. Values are write-only: the app
                    stores the key and shows CONFIGURED, but it never reads the secret back into
                    the browser. Keys marked with{' '}
                    <Key size={13} className="inline -mt-0.5 text-yellow-500" aria-label="key" /> unlock the richest live
                    aircraft and vessel feeds.
                  </p>
                </div>
                <div className="pl-5 text-[12px] font-mono text-cyan-200/80 leading-relaxed">
                  Configured keys stay hidden for shared dashboards. Unlock operator tools, then
                  use ROTATE only when you intentionally want to replace a working credential.
                </div>
                {envMeta && (
                  <div className="pl-5 text-[12px] font-mono text-[var(--text-muted)] leading-relaxed space-y-0.5">
                    <div>
                      <span className="text-cyan-500/70">local key store:</span>{' '}
                      <span className="text-cyan-300 break-all select-all">
                        {envMeta.operator_keys_env_path || envMeta.env_path}
                      </span>{' '}
                      {envMeta.operator_keys_env_path_exists || envMeta.env_path_exists ? (
                        <span className="text-green-400/80">[exists]</span>
                      ) : (
                        <span className="text-amber-400/80">[will be created on first save]</span>
                      )}
                      {envMeta.env_path_exists && !envMeta.env_path_writable && (
                        <span className="text-red-400/90"> [NOT WRITABLE — edit by hand]</span>
                      )}
                    </div>
                    {envMeta.env_example_path_exists && (
                      <div>
                        <span className="text-cyan-500/70">template:</span>{' '}
                        <span className="text-cyan-300/80 break-all select-all">
                          {envMeta.env_example_path}
                        </span>{' '}
                        <span className="text-[var(--text-muted)]">
                          (copy to .env and fill in your keys; comments above each entry list the registration URL)
                        </span>
                      </div>
                    )}
                  </div>
                )}
                {apiKeyMsg && (
                  <div
                    className={`pl-5 text-sm font-mono ${
                      apiKeyMsg.type === 'ok' ? 'text-green-300' : 'text-red-300'
                    }`}
                  >
                    {apiKeyMsg.text}
                  </div>
                )}
              </div>

              {/* API List */}
              <div className="flex-1 overflow-y-auto styled-scrollbar p-4 space-y-3 flex flex-col">
                {apis.length === 0 && (
                  <div className="mt-2 w-full rounded-2xl border border-[var(--border-primary)] bg-[rgba(3,8,18,0.5)] px-6 py-8 text-center">
                    <div className="mx-auto mb-4 w-10 h-10 rounded-xl border border-cyan-500/30 bg-cyan-500/10 flex items-center justify-center">
                      <Key size={18} className="text-cyan-400" />
                    </div>
                    <div className="sb-title text-cyan-300">API keys are locked</div>
                    <p className="sb-prose mt-2 text-[13px] text-[#a9bbd2]">
                      Keys are stored on your backend and shown only to the operator. Unlock operator
                      tools above with your <span className="font-mono text-cyan-300">ADMIN_KEY</span> to
                      view or edit them.
                    </p>
                    <button
                      type="button"
                      onClick={() => void fetchKeys()}
                      className="mt-5 px-4 py-2 rounded-lg border border-cyan-700/50 text-[11px] font-mono tracking-widest text-cyan-300 hover:text-cyan-200 hover:border-cyan-500/60 hover:bg-cyan-950/40 transition-colors"
                    >
                      RELOAD KEY LIST
                    </button>
                  </div>
                )}
                {apis.length === 0 && (
                  <ul className="mt-4 grid gap-2 text-left">
                    {[
                      ['GENERAL', 'Data-source API keys and credentials'],
                      ['FEEDS', 'News and RSS sources for the intel rail'],
                      ['SENTINEL', 'Copernicus imagery access'],
                      ['SAR', 'Radar scenes and AOI defaults'],
                      ['INFONET', 'Mesh, Wormhole and node identity'],
                    ].map(([tab, desc]) => (
                      <li key={tab} className="flex items-baseline gap-3 rounded-xl border border-[var(--border-primary)]/60 bg-[rgba(var(--sb-glass-hi),0.25)] px-3.5 py-2.5">
                        <span className="w-[84px] shrink-0 text-[10.5px] font-mono tracking-[0.16em] text-cyan-300">{tab}</span>
                        <span className="sb-prose text-[12.5px] text-[var(--text-muted)]">{desc}</span>
                      </li>
                    ))}
                  </ul>
                )}
                {apis.length === 0 && (
                  <p className="mt-auto pt-8 text-center text-[11px] font-mono tracking-[0.14em] text-[var(--text-muted)]">
                    SETTINGS AND SECRETS STAY ON YOUR LOCAL BACKEND
                  </p>
                )}
                {Object.entries(grouped).map(([category, categoryApis]) => {
                  const colorClass =
                    CATEGORY_COLORS[category] || 'text-gray-400 border-gray-700 bg-gray-900/20';
                  const isExpanded = expandedCategories.has(category);
                  return (
                    <div
                      key={category}
                      className="border border-[var(--border-primary)]/60 overflow-hidden"
                    >
                      <button
                        onClick={() => toggleCategory(category)}
                        className="w-full flex items-center justify-between px-4 py-2.5 bg-[var(--bg-secondary)]/50 hover:bg-[var(--bg-secondary)]/80 transition-colors"
                      >
                        <div className="flex items-center gap-2">
                          <span
                            className={`text-[13px] font-mono tracking-widest font-bold px-2 py-0.5 border ${colorClass}`}
                          >
                            {category.toUpperCase()}
                          </span>
                          <span className="text-sm text-[var(--text-muted)] font-mono">
                            {categoryApis.length}{' '}
                            {categoryApis.length === 1 ? 'service' : 'services'}
                          </span>
                        </div>
                        {isExpanded ? (
                          <ChevronUp size={12} className="text-[var(--text-muted)]" />
                        ) : (
                          <ChevronDown size={12} className="text-[var(--text-muted)]" />
                        )}
                      </button>
                      <AnimatePresence>
                        {isExpanded && (
                          <motion.div
                            initial={{ height: 0, opacity: 0 }}
                            animate={{ height: 'auto', opacity: 1 }}
                            exit={{ height: 0, opacity: 0 }}
                            transition={{ duration: 0.2 }}
                          >
                            {categoryApis.map((api) => (
                              <div
                                key={api.id}
                                className="border-t border-[var(--border-primary)]/40 px-4 py-3 hover:bg-[var(--bg-secondary)]/30 transition-colors"
                              >
                                <div className="flex items-center justify-between mb-1">
                                  <div className="flex items-center gap-2">
                                    {api.required && (
                                      <Key size={10} className="text-yellow-500" />
                                    )}
                                    <span className="text-xs font-mono text-[var(--text-primary)] font-medium">
                                      {api.name}
                                    </span>
                                  </div>
                                  <div className="flex items-center gap-1.5">
                                    {api.has_key ? (
                                      api.is_set ? (
                                        <span className="text-[12px] font-mono px-1.5 py-0.5 border border-green-500/30 text-green-400 bg-green-950/20">
                                          KEY SET
                                        </span>
                                      ) : (
                                        <span className="text-[12px] font-mono px-1.5 py-0.5 border border-yellow-500/30 text-yellow-400 bg-yellow-950/20">
                                          MISSING
                                        </span>
                                      )
                                    ) : (
                                      <span className="text-[12px] font-mono px-1.5 py-0.5 border border-[var(--border-primary)] text-[var(--text-muted)]">
                                        PUBLIC
                                      </span>
                                    )}
                                    {api.url && (
                                      <a
                                        href={api.url}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        className="text-[var(--text-muted)] hover:text-cyan-400 transition-colors"
                                        onClick={(e) => e.stopPropagation()}
                                      >
                                        <ExternalLink size={10} />
                                      </a>
                                    )}
                                  </div>
                                </div>
                                <p className="text-sm text-[var(--text-muted)] font-mono leading-relaxed mb-2">
                                  {api.description}
                                </p>
                                {api.has_key && (
                                  <div className="mt-2 space-y-2 text-[12px] font-mono">
                                    {api.is_set ? (
                                      <div className="space-y-2">
                                        <div className="flex items-start justify-between gap-2">
                                          <div className="min-w-0 flex items-center gap-2">
                                            <span className="px-2 py-0.5 border border-green-500/40 bg-green-950/20 text-green-300 tracking-wider">
                                              CONFIGURED
                                            </span>
                                            <span className="text-[var(--text-muted)] leading-relaxed">
                                              Secret hidden. Stored write-only on this backend as{' '}
                                              <span className="text-cyan-300 select-all break-all">
                                                {api.env_key}
                                              </span>
                                              .
                                            </span>
                                          </div>
                                          {api.env_key && (
                                            <button
                                              type="button"
                                              onClick={() => {
                                                if (!(nativeProtected || adminSessionReady)) {
                                                  setApiKeyMsg({
                                                    type: 'err',
                                                    text: 'Unlock operator tools before rotating a configured key.',
                                                  });
                                                  return;
                                                }
                                                setApiKeyMsg(null);
                                                setApiKeyEditing((prev) => ({
                                                  ...prev,
                                                  [api.env_key as string]: !prev[api.env_key as string],
                                                }));
                                              }}
                                              className={`shrink-0 px-2 py-1 border text-[11px] tracking-widest transition-colors ${
                                                nativeProtected || adminSessionReady
                                                  ? 'border-yellow-500/40 text-yellow-300 hover:bg-yellow-500/10'
                                                  : 'border-[var(--border-primary)] text-[var(--text-muted)] hover:border-yellow-500/30 hover:text-yellow-300/80'
                                              }`}
                                            >
                                              {apiKeyEditing[api.env_key] ? 'CANCEL' : 'ROTATE'}
                                            </button>
                                          )}
                                        </div>
                                        {!(nativeProtected || adminSessionReady) && (
                                          <div className="text-[11px] text-yellow-300/70 leading-relaxed">
                                            Operator tools are locked. Viewers can see source status
                                            but cannot replace saved credentials.
                                          </div>
                                        )}
                                      </div>
                                    ) : (
                                      <div className="flex items-center gap-2">
                                        <span className="px-2 py-0.5 border border-amber-500/40 bg-amber-950/20 text-amber-300 tracking-wider">
                                          NOT CONFIGURED
                                        </span>
                                        <span className="text-[var(--text-muted)]">
                                          Save {api.env_key} here to enable this source.
                                        </span>
                                      </div>
                                    )}
                                    {(!api.is_set || (api.env_key && apiKeyEditing[api.env_key])) && (
                                      <div className="flex items-center gap-2">
                                        <input
                                          type="password"
                                          value={api.env_key ? apiKeyInputs[api.env_key] || '' : ''}
                                          onChange={(event) => {
                                            if (!api.env_key) return;
                                            setApiKeyInputs((prev) => ({
                                              ...prev,
                                              [api.env_key as string]: event.target.value,
                                            }));
                                          }}
                                          placeholder={
                                            api.is_set
                                              ? 'Enter replacement key...'
                                              : `Enter ${api.env_key}...`
                                          }
                                          className="min-w-0 flex-1 bg-[var(--bg-primary)] border border-[var(--border-primary)] px-2 py-1.5 text-sm text-[var(--text-primary)] outline-none focus:border-cyan-500/70 placeholder:text-[var(--text-muted)]/50"
                                          autoComplete="off"
                                        />
                                        <button
                                          onClick={() => void saveApiKey(api.env_key)}
                                          disabled={
                                            !api.env_key ||
                                            apiKeySaving === api.env_key ||
                                            !String(
                                              api.env_key ? apiKeyInputs[api.env_key] || '' : '',
                                            ).trim()
                                          }
                                          className="h-8 px-3 border border-cyan-500/40 bg-cyan-950/20 text-cyan-300 hover:bg-cyan-500/15 disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-1.5 tracking-widest"
                                        >
                                          <Save size={12} />
                                          {apiKeySaving === api.env_key ? 'SAVING' : 'SAVE'}
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
              <div className={`p-4 border-t border-[var(--border-primary)]/80 ${apis.length === 0 ? 'hidden' : ''}`}>
                <div className="flex items-center justify-between text-[13px] text-[var(--text-muted)] font-mono">
                  {apis.length === 0 ? null : (
                    <>
                      <span>{apis.length} REGISTERED APIS</span>
                      <span>{apis.filter((a) => a.has_key && a.is_set).length} KEYS CONFIGURED</span>
                    </>
                  )}
                </div>
              </div>
            </>
}
