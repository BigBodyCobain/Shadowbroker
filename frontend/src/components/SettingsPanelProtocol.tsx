'use client';

import React from 'react';
import { AnimatePresence, motion } from '@/lib/motion';
import { Shield, ExternalLink, Key, Copy, Check, ChevronDown, ChevronUp, Radar, Save } from 'lucide-react';

export function SettingsPanelProtocol({ ctx }: { ctx: Record<string, any> }) {
            <ctx.div ctx.className="flex-1 ctx.min-ctx.h-0 ctx.flex ctx.flex-ctx.col ctx.overflow-ctx.y-ctx.auto ctx.styled-ctx.scrollbar">
              <ctx.div ctx.className="mx-4 ctx.mt-4 ctx.p-3 ctx.border ctx.border-ctx.cyan-900/30 ctx.bg-ctx.cyan-950/12">
                <ctx.div ctx.className="flex ctx.items-ctx.center ctx.justify-ctx.between ctx.gap-3">
                  <ctx.div>
                    <ctx.div ctx.className="text-ctx.sm ctx.text-ctx.cyan-300 ctx.font-ctx.mono ctx.tracking-[0.18em]">
                      WORMHOLE KEY SETUP
                    </ctx.div>
                    <ctx.div ctx.className="mt-2 ctx.text-ctx.sm ctx.text-[ctx.var(--ctx.text-ctx.secondary)] ctx.font-ctx.mono ctx.leading-ctx.relaxed">
                      ctx.One ctx.click ctx.enters ctx.Wormhole ctx.on ctx.the ctx.recommended ctx.path ctx.for ctx.gates ctx.and ctx.the ctx.obfuscated
                      ctx.inbox. ctx.Manual ctx.transport ctx.tuning ctx.stays ctx.hidden ctx.unless ctx.you ctx.ask ctx.for ctx.it.
                    </ctx.div>
                  </ctx.div>
                  <ctx.div ctx.className="text-ctx.right">
                    <ctx.div ctx.className="text-[12px] ctx.text-[ctx.var(--ctx.text-ctx.muted)] ctx.font-ctx.mono ctx.tracking-[0.2em]">
                      STATUS
                    </ctx.div>
                    <ctx.div ctx.className="mt-1 ctx.text-[11px] ctx.font-ctx.mono ctx.text-ctx.cyan-200">
                      {ctx.wormholeStatus?.ready
                        ? 'ACTIVE'
                        : ctx.wormholeEnabled
                          ? 'TURN ON CONNECT'
                          : 'OFF'}
                    </ctx.div>
                  </ctx.div>
                </ctx.div>
                <ctx.div ctx.className="mt-3 ctx.grid ctx.gap-2 ctx.text-[13px] ctx.font-ctx.mono ctx.text-[ctx.var(--ctx.text-ctx.muted)] ctx.leading-ctx.relaxed">
                  <ctx.div>1. ctx.Press <ctx.span ctx.className="text-ctx.green-300">GET WORMHOLE KEY</ctx.span>.</ctx.div>
                  <ctx.div>2. ctx.We ctx.handle ctx.the ctx.recommended ctx.setup ctx.path ctx.in ctx.the ctx.background.</ctx.div>
                  <ctx.div>3. ctx.Wait ctx.for <ctx.span ctx.className="text-ctx.green-300">ACTIVE</ctx.span>.</ctx.div>
                  <ctx.div>4. ctx.We ctx.send ctx.you ctx.straight ctx.back ctx.into ctx.gates.</ctx.div>
                </ctx.div>
                {ctx.wormholeGuideNotice && (
                  <ctx.div ctx.className="mt-3 ctx.border ctx.border-ctx.fuchsia-500/25 ctx.bg-ctx.fuchsia-950/12 ctx.px-3 ctx.py-2 ctx.text-ctx.sm ctx.font-ctx.mono ctx.text-ctx.fuchsia-200/90 ctx.leading-ctx.relaxed">
                    {ctx.wormholeGuideNotice}
                  </ctx.div>
                )}
                {ctx.adminSessionMsg === 'BACKEND ADMIN KEY NOT CONFIGURED' && (
                  <ctx.div ctx.className="mt-3 ctx.border ctx.border-ctx.cyan-500/20 ctx.bg-ctx.cyan-950/10 ctx.px-3 ctx.py-2 ctx.text-ctx.sm ctx.font-ctx.mono ctx.text-ctx.cyan-200/85 ctx.leading-ctx.relaxed">
                    ctx.Operator ctx.key ctx.is ctx.only ctx.needed ctx.for ctx.protected ctx.Settings ctx.tabs. ctx.Wormhole ctx.join ctx.below ctx.now
                    ctx.works ctx.without ctx.it.
                  </ctx.div>
                )}
                <ctx.div ctx.className="mt-3 ctx.flex ctx.flex-ctx.wrap ctx.gap-2">
                  <ctx.button
                    ctx.onClick={ctx.quickStartWormhole}
                    ctx.disabled={ctx.wormholeSaving || ctx.wormholeQuickState === 'active'}
                    ctx.className="px-3 ctx.py-1.5 ctx.border ctx.border-ctx.green-500/40 ctx.bg-ctx.green-950/20 ctx.text-[13px] ctx.font-ctx.mono ctx.tracking-[0.18em] ctx.text-ctx.green-300 ctx.hover:ctx.bg-ctx.green-950/30 ctx.disabled:ctx.opacity-40"
                  >
                    {ctx.wormholeQuickButtonLabel}
                  </ctx.button>
                  <ctx.button
                    ctx.onClick={() => ctx.setShowAdvancedWormhole((prev) => !prev)}
                    ctx.className="px-3 ctx.py-1.5 ctx.border ctx.border-ctx.cyan-500/35 ctx.bg-ctx.cyan-950/18 ctx.text-[13px] ctx.font-ctx.mono ctx.tracking-[0.18em] ctx.text-ctx.cyan-200 ctx.hover:ctx.bg-ctx.cyan-950/28"
                  >
                    {ctx.showAdvancedWormhole ? 'HIDE MANUAL SETUP' : 'MANUAL SETUP'}
                  </ctx.button>
                </ctx.div>
                {ctx.wormholeMsg && (
                  <ctx.div
                    ctx.className={`ctx.mt-3 ctx.px-3 ctx.py-2 ctx.text-ctx.sm ctx.font-ctx.mono ctx.leading-ctx.relaxed ${ctx.wormholeMsg.type === 'ok' ? 'text-ctx.green-300 ctx.bg-ctx.green-950/18 ctx.border ctx.border-ctx.green-900/30' : 'text-ctx.red-300 ctx.bg-ctx.red-950/18 ctx.border ctx.border-ctx.red-900/30'}`}
                  >
                    {ctx.wormholeMsg.text}
                  </ctx.div>
                )}
                {ctx.wormholeNodeId && (
                  <ctx.div ctx.className="mt-3 ctx.border ctx.border-ctx.cyan-500/20 ctx.bg-ctx.black/30 ctx.px-3 ctx.py-2">
                    <ctx.div ctx.className="text-[13px] ctx.font-ctx.mono ctx.tracking-[0.18em] ctx.text-[ctx.var(--ctx.text-ctx.muted)] ctx.mb-1">
                      YOUR WORMHOLE IDENTITY
                    </ctx.div>
                    <ctx.div ctx.className="flex ctx.items-ctx.center ctx.gap-2">
                      <ctx.code ctx.className="flex-1 ctx.text-[11px] ctx.font-ctx.mono ctx.text-ctx.cyan-300 ctx.break-ctx.all ctx.select-ctx.all">
                        {ctx.wormholeNodeId}
                      </ctx.code>
                      <ctx.button
                        ctx.onClick={ctx.async () => {
                          ctx.try {
                            ctx.await navigator.clipboard.writeText(ctx.wormholeNodeId);
                            ctx.setWormholeKeyCopied(true);
                            setTimeout(() => ctx.setWormholeKeyCopied(false), 2000);
                          } ctx.catch { /* ctx.clipboard ctx.not ctx.available */ }
                        }}
                        ctx.className="shrink-0 ctx.px-2 ctx.py-1 ctx.border ctx.border-ctx.cyan-500/30 ctx.text-ctx.cyan-400 ctx.hover:ctx.bg-ctx.cyan-950/30 ctx.transition-ctx.colors ctx.text-[13px] ctx.font-ctx.mono ctx.flex ctx.items-ctx.center ctx.gap-1"
                        ctx.title="Copy ctx.identity ctx.to ctx.clipboard"
                      >
                        {ctx.wormholeKeyCopied ? <Check ctx.size={10} /> : <Copy ctx.size={10} />}
                        {ctx.wormholeKeyCopied ? 'COPIED' : 'COPY'}
                      </ctx.button>
                    </ctx.div>
                  </ctx.div>
                )}
              </ctx.div>

              <ctx.div ctx.className={`ctx.mx-4 ctx.mt-4 ctx.p-3 ctx.border ${ctx.dmRootCardTone}`}>
                <ctx.div ctx.className="flex ctx.items-ctx.start ctx.justify-ctx.between ctx.gap-3">
                  <ctx.div>
                    <ctx.div ctx.className="text-ctx.sm ctx.font-ctx.mono ctx.tracking-[0.18em]">DM ROOT HEALTH</ctx.div>
                    <ctx.div ctx.className="mt-2 ctx.text-ctx.sm ctx.font-ctx.mono ctx.leading-ctx.relaxed ctx.text-[ctx.var(--ctx.text-ctx.secondary)]">
                      ctx.External ctx.witness ctx.freshness, ctx.transparency ctx.readback, ctx.and ctx.the next ctx.operator
                      ctx.action ctx.for ctx.strong DM ctx.trust.
                    </ctx.div>
                  </ctx.div>
                  <ctx.div ctx.className="flex ctx.items-ctx.center ctx.gap-2">
                    <ctx.span
                      ctx.className={`ctx.px-2 ctx.py-1 ctx.border ctx.text-[11px] ctx.font-ctx.mono ctx.tracking-[0.18em] ${ctx.dmRootCardTone}`}
                    >
                      {!ctx.showOperatorTools
                        ? 'HIDDEN'
                        : ctx.dmRootHealth
                          ? ctx.dmRootMonitorLabel(ctx.dmRootHealth.monitoring?.state)
                          : ctx.dmRootHealthBusy
                            ? 'LOADING'
                            : ctx.dmRootHealthMsg
                              ? 'BLOCKED'
                              : 'UNKNOWN'}
                    </ctx.span>
                    {ctx.showOperatorTools && (ctx.nativeProtected || ctx.adminSessionReady) && (
                      <ctx.button
                        ctx.onClick={() => ctx.void ctx.fetchDmRootHealth()}
                        ctx.disabled={ctx.dmRootHealthBusy}
                        ctx.className="px-2 ctx.py-1 ctx.border ctx.border-ctx.cyan-500/30 ctx.text-[12px] ctx.font-ctx.mono ctx.tracking-[0.18em] ctx.text-ctx.cyan-200 ctx.hover:ctx.bg-ctx.cyan-950/20 ctx.disabled:ctx.opacity-50"
                      >
                        <ctx.span ctx.className="inline-ctx.flex ctx.items-ctx.center ctx.gap-1">
                          <ctx.RotateCcw ctx.size={11} />
                          REFRESH
                        </ctx.span>
                      </ctx.button>
                    )}
                  </ctx.div>
                </ctx.div>

                {!ctx.showOperatorTools ? (
                  <ctx.div ctx.className="mt-3 ctx.border ctx.border-ctx.cyan-500/20 ctx.bg-ctx.black/20 ctx.px-3 ctx.py-3 ctx.text-ctx.sm ctx.font-ctx.mono ctx.text-[ctx.var(--ctx.text-ctx.muted)] ctx.leading-ctx.relaxed">
                    ctx.Wormhole ctx.join ctx.stays ctx.visible ctx.without ctx.operator ctx.tools. ctx.Open ctx.operator ctx.tools ctx.to ctx.see
                    ctx.external ctx.witness ctx.freshness, ctx.transparency ctx.readback, ctx.and ctx.remediation ctx.guidance.
                    <ctx.div ctx.className="mt-3">
                      <ctx.button
                        ctx.onClick={() => ctx.setShowOperatorTools(true)}
                        ctx.className="px-3 ctx.py-1.5 ctx.border ctx.border-ctx.cyan-500/35 ctx.bg-ctx.cyan-950/18 ctx.text-[13px] ctx.font-ctx.mono ctx.tracking-[0.18em] ctx.text-ctx.cyan-200 ctx.hover:ctx.bg-ctx.cyan-950/28"
                      >
                        SHOW TOOLS
                      </ctx.button>
                    </ctx.div>
                  </ctx.div>
                ) : !ctx.nativeProtected && !ctx.adminSessionReady ? (
                  <ctx.div ctx.className="mt-3 ctx.border ctx.border-ctx.yellow-500/25 ctx.bg-ctx.yellow-950/12 ctx.px-3 ctx.py-3 ctx.text-ctx.sm ctx.font-ctx.mono ctx.text-ctx.yellow-200/90 ctx.leading-ctx.relaxed">
                    ctx.Unlock ctx.operator ctx.tools ctx.above ctx.to ctx.load ctx.live DM ctx.root ctx.health, ctx.external ctx.witness
                    ctx.freshness, ctx.and ctx.transparency ctx.monitoring ctx.status.
                  </ctx.div>
                ) : ctx.dmRootHealthBusy && !ctx.dmRootHealth ? (
                  <ctx.div ctx.className="mt-3 ctx.border ctx.border-ctx.cyan-500/20 ctx.bg-ctx.black/20 ctx.px-3 ctx.py-3 ctx.text-ctx.sm ctx.font-ctx.mono ctx.text-ctx.cyan-200/80">
                    ctx.Loading ctx.current DM ctx.root ctx.health...
                  </ctx.div>
                ) : ctx.dmRootHealth ? (
                  <ctx.div ctx.className="mt-3 ctx.grid ctx.gap-2">
                    <ctx.div ctx.className="grid ctx.grid-ctx.cols-2 ctx.gap-2">
                      <ctx.div ctx.className="border ctx.border-[ctx.var(--ctx.border-ctx.primary)]/50 ctx.bg-ctx.black/20 ctx.px-3 ctx.py-2">
                        <ctx.div ctx.className="text-[12px] ctx.font-ctx.mono ctx.tracking-[0.18em] ctx.text-[ctx.var(--ctx.text-ctx.muted)]">
                          SUMMARY
                        </ctx.div>
                        <ctx.div ctx.className="mt-1 ctx.text-[13px] ctx.font-ctx.mono ctx.text-[ctx.var(--ctx.text-ctx.secondary)]">
                          {String(ctx.dmRootHealth.state || '').replaceAll('_', ' ').toUpperCase()}
                        </ctx.div>
                        <ctx.div ctx.className="mt-1 ctx.text-[12px] ctx.font-ctx.mono ctx.text-[ctx.var(--ctx.text-ctx.muted)] ctx.leading-ctx.relaxed">
                          {ctx.dmRootHealth.detail}
                        </ctx.div>
                      </ctx.div>
                      <ctx.div ctx.className="border ctx.border-[ctx.var(--ctx.border-ctx.primary)]/50 ctx.bg-ctx.black/20 ctx.px-3 ctx.py-2">
                        <ctx.div ctx.className="text-[12px] ctx.font-ctx.mono ctx.tracking-[0.18em] ctx.text-[ctx.var(--ctx.text-ctx.muted)]">
                          STRONG TRUST
                        </ctx.div>
                        <ctx.div
                          ctx.className={`ctx.mt-1 ctx.text-[13px] ctx.font-ctx.mono ${
                            ctx.dmRootHealth.strong_trust_blocked ? 'text-ctx.red-300' : 'text-ctx.green-300'
                          }`}
                        >
                          {ctx.dmRootHealth.strong_trust_blocked ? 'BLOCKED' : 'CURRENT'}
                        </ctx.div>
                        <ctx.div ctx.className="mt-1 ctx.text-[12px] ctx.font-ctx.mono ctx.text-[ctx.var(--ctx.text-ctx.muted)]">
                          {ctx.dmRootHealth.monitoring?.status_line || 'Operator ctx.monitoring ctx.active.'}
                        </ctx.div>
                      </ctx.div>
                    </ctx.div>

                    <ctx.div ctx.className="grid ctx.grid-ctx.cols-2 ctx.gap-2">
                      <ctx.div ctx.className="border ctx.border-[ctx.var(--ctx.border-ctx.primary)]/50 ctx.bg-ctx.black/20 ctx.px-3 ctx.py-2">
                        <ctx.div ctx.className="flex ctx.items-ctx.center ctx.justify-ctx.between ctx.gap-2">
                          <ctx.div ctx.className="text-[12px] ctx.font-ctx.mono ctx.tracking-[0.18em] ctx.text-[ctx.var(--ctx.text-ctx.muted)]">
                            WITNESS
                          </ctx.div>
                          <ctx.span
                            ctx.className={`ctx.px-1.5 ctx.py-0.5 ctx.border ctx.text-[11px] ctx.font-ctx.mono ctx.tracking-ctx.widest ${ctx.dmRootUrgencyTone(
                              ctx.dmRootHealth.witness.health_state === 'error'
                                ? 'page'
                                : ctx.dmRootHealth.witness.health_state === 'warning'
                                  ? 'ticket'
                                  : 'watch',
                            )}`}
                          >
                            {String(ctx.dmRootHealth.witness.state || '').replaceAll('_', ' ').toUpperCase()}
                          </ctx.span>
                        </ctx.div>
                        <ctx.div ctx.className="mt-2 ctx.text-[12px] ctx.font-ctx.mono ctx.text-[ctx.var(--ctx.text-ctx.muted)]">
                          ctx.Age {ctx.formatAgeWindow(ctx.dmRootHealth.witness.age_s, ctx.dmRootHealth.witness.freshness_window_s)}
                        </ctx.div>
                        <ctx.div ctx.className="mt-1 ctx.text-[12px] ctx.font-ctx.mono ctx.text-[ctx.var(--ctx.text-ctx.muted)]">
                          {ctx.dmRootHealth.witness.source_label ||
                            ctx.dmRootHealth.witness.source_ref ||
                            ctx.dmRootHealth.witness.detail ||
                            'Configured ctx.witness ctx.source ctx.unavailable.'}
                        </ctx.div>
                      </ctx.div>

                      <ctx.div ctx.className="border ctx.border-[ctx.var(--ctx.border-ctx.primary)]/50 ctx.bg-ctx.black/20 ctx.px-3 ctx.py-2">
                        <ctx.div ctx.className="flex ctx.items-ctx.center ctx.justify-ctx.between ctx.gap-2">
                          <ctx.div ctx.className="text-[12px] ctx.font-ctx.mono ctx.tracking-[0.18em] ctx.text-[ctx.var(--ctx.text-ctx.muted)]">
                            TRANSPARENCY
                          </ctx.div>
                          <ctx.span
                            ctx.className={`ctx.px-1.5 ctx.py-0.5 ctx.border ctx.text-[11px] ctx.font-ctx.mono ctx.tracking-ctx.widest ${ctx.dmRootUrgencyTone(
                              ctx.dmRootHealth.transparency.health_state === 'error'
                                ? 'page'
                                : ctx.dmRootHealth.transparency.health_state === 'warning'
                                  ? 'ticket'
                                  : 'watch',
                            )}`}
                          >
                            {String(ctx.dmRootHealth.transparency.state || '').replaceAll('_', ' ').toUpperCase()}
                          </ctx.span>
                        </ctx.div>
                        <ctx.div ctx.className="mt-2 ctx.text-[12px] ctx.font-ctx.mono ctx.text-[ctx.var(--ctx.text-ctx.muted)]">
                          ctx.Age{' '}
                          {ctx.formatAgeWindow(
                            ctx.dmRootHealth.transparency.age_s,
                            ctx.dmRootHealth.transparency.freshness_window_s,
                          )}
                        </ctx.div>
                        <ctx.div ctx.className="mt-1 ctx.text-[12px] ctx.font-ctx.mono ctx.text-[ctx.var(--ctx.text-ctx.muted)]">
                          {ctx.dmRootHealth.transparency.source_ref ||
                            ctx.dmRootHealth.transparency.export_path ||
                            ctx.dmRootHealth.transparency.detail ||
                            'Configured ctx.ledger ctx.readback ctx.unavailable.'}
                        </ctx.div>
                      </ctx.div>
                    </ctx.div>

                    {ctx.dmRootHealth.alerts.length > 0 && (
                      <ctx.div ctx.className="border ctx.border-[ctx.var(--ctx.border-ctx.primary)]/50 ctx.bg-ctx.black/20 ctx.px-3 ctx.py-2">
                        <ctx.div ctx.className="text-[12px] ctx.font-ctx.mono ctx.tracking-[0.18em] ctx.text-[ctx.var(--ctx.text-ctx.muted)]">
                          ACTIVE ALERTS
                        </ctx.div>
                        <ctx.div ctx.className="mt-2 ctx.grid ctx.gap-2">
                          {ctx.dmRootHealth.alerts.slice(0, 2).map((alert) => (
                            <ctx.div
                              ctx.key={`${alert.code}-${alert.target}`}
                              ctx.className={`ctx.border ctx.px-2 ctx.py-2 ctx.text-[12px] ctx.font-ctx.mono ctx.leading-ctx.relaxed ${
                                alert.blocking
                                  ? 'border-ctx.red-500/30 ctx.bg-ctx.red-950/12 ctx.text-ctx.red-200'
                                  : 'border-ctx.yellow-500/30 ctx.bg-ctx.yellow-950/12 ctx.text-ctx.yellow-200'
                              }`}
                            >
                              <ctx.div ctx.className="tracking-[0.16em]">
                                {alert.code.replaceAll('_', ' ').toUpperCase()}
                              </ctx.div>
                              <ctx.div ctx.className="mt-1 ctx.text-[ctx.var(--ctx.text-ctx.secondary)]">{alert.detail}</ctx.div>
                            </ctx.div>
                          ))}
                        </ctx.div>
                      </ctx.div>
                    )}

                    <ctx.div ctx.className="border ctx.border-[ctx.var(--ctx.border-ctx.primary)]/50 ctx.bg-ctx.black/20 ctx.px-3 ctx.py-2">
                      <ctx.div ctx.className="flex ctx.items-ctx.center ctx.justify-ctx.between ctx.gap-2">
                        <ctx.div ctx.className="text-[12px] ctx.font-ctx.mono ctx.tracking-[0.18em] ctx.text-[ctx.var(--ctx.text-ctx.muted)]">
                          NEXT ACTION
                        </ctx.div>
                        <ctx.span
                          ctx.className={`ctx.px-1.5 ctx.py-0.5 ctx.border ctx.text-[11px] ctx.font-ctx.mono ctx.tracking-ctx.widest ${ctx.dmRootUrgencyTone(
                            ctx.dmRootHealth.runbook?.urgency,
                          )}`}
                        >
                          {String(ctx.dmRootHealth.runbook?.urgency || 'none').toUpperCase()}
                        </ctx.span>
                      </ctx.div>
                      <ctx.div ctx.className="mt-2 ctx.text-[13px] ctx.font-ctx.mono ctx.text-[ctx.var(--ctx.text-ctx.secondary)]">
                        {(
                          ctx.dmRootHealth.runbook?.next_action_detail &&
                          'title' ctx.in ctx.dmRootHealth.runbook.next_action_detail &&
                          ctx.dmRootHealth.runbook.next_action_detail.title
                        ) ||
                          ctx.dmRootHealth.runbook?.next_action ||
                          'No ctx.action ctx.required.'}
                      </ctx.div>
                      <ctx.div ctx.className="mt-1 ctx.text-[12px] ctx.font-ctx.mono ctx.text-[ctx.var(--ctx.text-ctx.muted)] ctx.leading-ctx.relaxed">
                        {(
                          ctx.dmRootHealth.runbook?.next_action_detail &&
                          'summary' ctx.in ctx.dmRootHealth.runbook.next_action_detail &&
                          ctx.dmRootHealth.runbook.next_action_detail.summary
                        ) ||
                          ctx.dmRootHealth.monitoring?.status_line ||
                          'Current ctx.external ctx.assurance ctx.is ctx.within ctx.policy.'}
                      </ctx.div>
                    </ctx.div>
                  </ctx.div>
                ) : (
                  <ctx.div ctx.className="mt-3 ctx.border ctx.border-ctx.red-500/25 ctx.bg-ctx.red-950/12 ctx.px-3 ctx.py-3 ctx.text-ctx.sm ctx.font-ctx.mono ctx.text-ctx.red-200/90 ctx.leading-ctx.relaxed">
                    {ctx.dmRootHealthMsg || 'Could ctx.not ctx.load DM ctx.root ctx.health.'}
                  </ctx.div>
                )}
              </ctx.div>

              {ctx.showAdvancedWormhole && (
                <>
              {/* ctx.Privacy ctx.Mode */}
              <ctx.div ctx.className="mx-4 ctx.mt-4 ctx.p-3 ctx.border ctx.border-ctx.green-900/30 ctx.bg-ctx.green-950/10">
                <ctx.div ctx.className="flex ctx.items-ctx.center ctx.justify-ctx.between ctx.gap-2">
                  <ctx.div ctx.className="flex ctx.items-ctx.center ctx.gap-2">
                    <Shield ctx.size={12} ctx.className="text-ctx.green-500 ctx.mt-0.5 ctx.flex-ctx.shrink-0" />
                    <ctx.span ctx.className="text-ctx.sm ctx.text-[ctx.var(--ctx.text-ctx.secondary)] ctx.font-ctx.mono ctx.tracking-ctx.widest">
                      HIGH PRIVACY MODE (OPT-IN)
                    </ctx.span>
                  </ctx.div>
                  <ctx.button
                    ctx.onClick={() => {
                      ctx.const next = ctx.privacyProfile !== 'high';
                      ctx.setHighPrivacy(next);
                    }}
                    ctx.className={`ctx.px-2 ctx.py-1 ctx.border ctx.text-[13px] ctx.font-ctx.mono ctx.tracking-ctx.widest ctx.transition-ctx.colors ${ctx.privacyProfile === 'high' ? 'border-ctx.green-500/40 ctx.text-ctx.green-400 ctx.bg-ctx.green-950/20' : 'border-[ctx.var(--ctx.border-ctx.primary)] ctx.text-[ctx.var(--ctx.text-ctx.muted)] ctx.hover:ctx.text-[ctx.var(--ctx.text-ctx.secondary)]'}`}
                  >
                    {ctx.privacyProfile === 'high' ? 'ON' : 'OFF'}
                  </ctx.button>
                </ctx.div>
                <ctx.p ctx.className="text-ctx.sm ctx.text-[ctx.var(--ctx.text-ctx.muted)] ctx.font-ctx.mono ctx.leading-ctx.relaxed ctx.mt-2">
                  ctx.Enables ctx.High ctx.Privacy ctx.profile: ctx.session-ctx.only ctx.identity, ctx.stronger ctx.jitter, ctx.sharded
                  ctx.transport (ctx.when ctx.available), ctx.and ctx.stricter ctx.sync ctx.behavior. ctx.High ctx.Privacy ctx.requires
                  ctx.the ctx.local ctx.agent ctx.for ctx.mesh ctx.traffic ctx.and ctx.refuses ctx.clearnet ctx.fallback ctx.for ctx.obfuscated
                  ctx.sends. ctx.This ctx.does ctx.not ctx.make ctx.you ctx.anonymous ctx.or ctx.fully ctx.hidden.
                </ctx.p>
                {ctx.privacyProfile === 'high' && (
                  <ctx.div ctx.className="mt-2 ctx.p-2 ctx.border ctx.border-ctx.yellow-500/30 ctx.bg-ctx.yellow-950/10 ctx.text-ctx.sm ctx.text-ctx.yellow-200/90 ctx.font-ctx.mono ctx.leading-ctx.relaxed">
                    ctx.Recommendation: ctx.use ctx.a ctx.reputable VPN ctx.or ctx.hidden ctx.transport. ctx.A VPN ctx.can ctx.help ctx.hide
                    ctx.your IP ctx.from ctx.the ctx.backend ctx.and ctx.peers, ctx.but ctx.it ctx.does ctx.not ctx.eliminate ctx.metadata,
                    ctx.endpoint ctx.compromise, ctx.or ctx.traffic ctx.analysis ctx.risks.
                  </ctx.div>
                )}
              </ctx.div>

              {/* ctx.Session ctx.Identity ctx.Mode */}
              <ctx.div ctx.className="mx-4 ctx.mt-3 ctx.p-3 ctx.border ctx.border-ctx.green-900/30 ctx.bg-ctx.green-950/10">
                <ctx.div ctx.className="flex ctx.items-ctx.center ctx.justify-ctx.between ctx.gap-2">
                  <ctx.div ctx.className="flex ctx.items-ctx.center ctx.gap-2">
                    <Shield ctx.size={12} ctx.className="text-ctx.green-500 ctx.mt-0.5 ctx.flex-ctx.shrink-0" />
                    <ctx.span ctx.className="text-ctx.sm ctx.text-[ctx.var(--ctx.text-ctx.secondary)] ctx.font-ctx.mono ctx.tracking-ctx.widest">
                      EPHEMERAL SESSION ID (RECOMMENDED)
                    </ctx.span>
                  </ctx.div>
                  <ctx.button
	                      ctx.onClick={() => {
	                        ctx.const next = !ctx.sessionMode;
	                        ctx.setSessionMode(next);
	                        ctx.setSessionModePreference(next);
	                        ctx.migratePrivacySensitiveBrowserState();
	                        ctx.if (next) ctx.clearSessionIdentity();
	                      }}
                    ctx.className={`ctx.px-2 ctx.py-1 ctx.border ctx.text-[13px] ctx.font-ctx.mono ctx.tracking-ctx.widest ctx.transition-ctx.colors ${ctx.sessionMode ? 'border-ctx.green-500/40 ctx.text-ctx.green-400 ctx.bg-ctx.green-950/20' : 'border-[ctx.var(--ctx.border-ctx.primary)] ctx.text-[ctx.var(--ctx.text-ctx.muted)] ctx.hover:ctx.text-[ctx.var(--ctx.text-ctx.secondary)]'}`}
                  >
                    {ctx.sessionMode ? 'ON' : 'OFF'}
                  </ctx.button>
                </ctx.div>
                <ctx.p ctx.className="text-ctx.sm ctx.text-[ctx.var(--ctx.text-ctx.muted)] ctx.font-ctx.mono ctx.leading-ctx.relaxed ctx.mt-2">
                  ctx.When ctx.enabled, ctx.agent ctx.keys ctx.are ctx.stored ctx.in ctx.session ctx.storage ctx.and ctx.reset ctx.on ctx.browser
                  ctx.close. ctx.Your ctx.identity ctx.will ctx.not ctx.persist ctx.across ctx.restarts.
                </ctx.p>
                <ctx.div ctx.className="mt-3 ctx.flex ctx.items-ctx.center ctx.justify-ctx.between ctx.gap-3 ctx.border ctx.border-[ctx.var(--ctx.border-ctx.primary)] ctx.bg-ctx.black/20 ctx.px-3 ctx.py-2">
                  <ctx.div ctx.className="min-ctx.w-0">
                    <ctx.div ctx.className="text-ctx.sm ctx.font-ctx.mono ctx.tracking-ctx.widest ctx.text-[ctx.var(--ctx.text-ctx.secondary)]">
                      WIPE LOCAL MESH TRACES
                    </ctx.div>
                    <ctx.p ctx.className="mt-1 ctx.text-ctx.sm ctx.font-ctx.mono ctx.leading-ctx.relaxed ctx.text-[ctx.var(--ctx.text-ctx.muted)]">
                      ctx.Clears ctx.browser-ctx.held ctx.mesh ctx.identities, DM ctx.ratchet ctx.state, ctx.cached ctx.contacts, ctx.and
                      ctx.privacy-ctx.sensitive ctx.browser ctx.storage. ctx.The ctx.local ctx.agent ctx.is ctx.not ctx.shut ctx.down.
                    </ctx.p>
                  </ctx.div>
                  <ctx.button
                    ctx.onClick={() => {
                      ctx.void ctx.wipeLocalMeshTraces();
                    }}
                    ctx.disabled={ctx.browserWipeBusy}
                    ctx.className={`ctx.shrink-0 ctx.px-2 ctx.py-1 ctx.border ctx.text-[13px] ctx.font-ctx.mono ctx.tracking-ctx.widest ctx.transition-ctx.colors ${
                      ctx.browserWipeBusy
                        ? 'border-[ctx.var(--ctx.border-ctx.primary)] ctx.text-[ctx.var(--ctx.text-ctx.muted)] ctx.opacity-60 ctx.cursor-ctx.not-ctx.allowed'
                        : 'border-ctx.yellow-500/40 ctx.text-ctx.yellow-300 ctx.bg-ctx.yellow-950/20 ctx.hover:ctx.text-ctx.yellow-200'
                    }`}
                  >
                    {ctx.browserWipeBusy ? 'WIPING' : 'WIPE NOW'}
                  </ctx.button>
                </ctx.div>
                {ctx.browserWipeMsg && (
                  <ctx.div
                    ctx.className={`ctx.mt-2 ctx.text-ctx.sm ctx.font-ctx.mono ctx.leading-ctx.relaxed ${
                      ctx.browserWipeMsg.type === 'ok' ? 'text-ctx.green-300' : 'text-ctx.red-300'
                    }`}
                  >
                    {ctx.browserWipeMsg.text}
                  </ctx.div>
                )}
              </ctx.div>

              {/* ctx.Wormhole ctx.Mode */}
              <ctx.div ctx.className="mx-4 ctx.mt-3 ctx.p-3 ctx.border ctx.border-ctx.green-900/30 ctx.bg-ctx.green-950/10">
                <ctx.div ctx.className="flex ctx.items-ctx.center ctx.justify-ctx.between ctx.gap-2">
                  <ctx.div ctx.className="flex ctx.items-ctx.center ctx.gap-2">
                    <Shield ctx.size={12} ctx.className="text-ctx.green-500 ctx.mt-0.5 ctx.flex-ctx.shrink-0" />
                    <ctx.span ctx.className="text-ctx.sm ctx.text-[ctx.var(--ctx.text-ctx.secondary)] ctx.font-ctx.mono ctx.tracking-ctx.widest">
                      LOCAL MESH AGENT (OPT-IN)
                    </ctx.span>
                  </ctx.div>
                  <ctx.button
                    ctx.onClick={ctx.toggleWormhole}
                    ctx.disabled={ctx.wormholeSaving}
                    ctx.className={`ctx.px-2 ctx.py-1 ctx.border ctx.text-[13px] ctx.font-ctx.mono ctx.tracking-ctx.widest ctx.transition-ctx.colors ${ctx.wormholeEnabled ? 'border-ctx.green-500/40 ctx.text-ctx.green-400 ctx.bg-ctx.green-950/20' : 'border-[ctx.var(--ctx.border-ctx.primary)] ctx.text-[ctx.var(--ctx.text-ctx.muted)] ctx.hover:ctx.text-[ctx.var(--ctx.text-ctx.secondary)]'} ${ctx.wormholeSaving ? 'opacity-60 ctx.cursor-ctx.not-ctx.allowed' : ''}`}
                  >
                    {ctx.wormholeEnabled ? 'ON' : 'OFF'}
                  </ctx.button>
                </ctx.div>
                <ctx.p ctx.className="text-ctx.sm ctx.text-[ctx.var(--ctx.text-ctx.muted)] ctx.font-ctx.mono ctx.leading-ctx.relaxed ctx.mt-2">
                  ctx.Runs ctx.a ctx.local ctx.mesh ctx.agent ctx.that ctx.handles ctx.traffic ctx.directly, ctx.removing ctx.the ctx.backend
                  ctx.as ctx.a ctx.central ctx.observer. ctx.Experimental — ctx.does ctx.not ctx.guarantee ctx.privacy ctx.or ctx.anonymity.
                </ctx.p>
                <ctx.div ctx.className="mt-2 ctx.grid ctx.grid-ctx.cols-1 ctx.gap-2">
                  <ctx.div ctx.className="flex ctx.items-ctx.center ctx.justify-ctx.between ctx.gap-2">
                    <ctx.span ctx.className="text-[13px] ctx.font-ctx.mono ctx.text-[ctx.var(--ctx.text-ctx.muted)] ctx.tracking-ctx.widest">
                      TRANSPORT
                    </ctx.span>
                    <ctx.select
                      ctx.value={ctx.wormholeTransport}
                      ctx.onChange={(e) => {
                        ctx.setWormholeTransport(e.target.value);
                        ctx.setWormholeDirty(true);
                      }}
                      ctx.className="bg-[ctx.var(--ctx.bg-ctx.primary)]/60 ctx.border ctx.border-[ctx.var(--ctx.border-ctx.primary)] ctx.px-2 ctx.py-1 ctx.text-[13px] ctx.font-ctx.mono ctx.text-[ctx.var(--ctx.text-ctx.secondary)]"
                    >
                      <ctx.option ctx.value="direct">DIRECT</ctx.option>
                      <ctx.option ctx.value="tor">TOR (SOCKS5)</ctx.option>
                      <ctx.option ctx.value="i2p">I2P (SOCKS5)</ctx.option>
                      <ctx.option ctx.value="mixnet">MIXNET (SOCKS5)</ctx.option>
                    </ctx.select>
                  </ctx.div>
                  {(ctx.wormholeTransport === 'tor' ||
                    ctx.wormholeTransport === 'i2p' ||
                    ctx.wormholeTransport === 'mixnet') && (
                    <>
                      <ctx.input
                        ctx.type="text"
                        ctx.value={ctx.wormholeSocksProxy}
                        ctx.onChange={(e) => {
                          ctx.setWormholeSocksProxy(e.target.value);
                          ctx.setWormholeDirty(true);
                        }}
                        ctx.placeholder="SOCKS5 ctx.proxy (e.g. 127.0.0.1:9050)"
                        ctx.className="w-ctx.full ctx.bg-ctx.black/30 ctx.border ctx.border-[ctx.var(--ctx.border-ctx.primary)]/40 ctx.px-2 ctx.py-1 ctx.text-ctx.sm ctx.font-ctx.mono ctx.text-[ctx.var(--ctx.text-ctx.muted)] ctx.outline-ctx.none ctx.focus:ctx.border-ctx.cyan-500/50"
                      />
                      <ctx.div ctx.className="flex ctx.flex-ctx.wrap ctx.gap-1">
                        <ctx.button
                          ctx.onClick={() => {
                            ctx.setWormholeTransport('tor');
                            ctx.setWormholeSocksProxy('127.0.0.1:9050');
                            ctx.setWormholeDirty(true);
                          }}
                          ctx.className="px-2 ctx.py-1 ctx.border ctx.border-ctx.purple-500/30 ctx.text-ctx.purple-300 ctx.text-[12px] ctx.font-ctx.mono ctx.tracking-ctx.widest ctx.hover:ctx.bg-ctx.purple-950/20"
                        >
                          TOR 9050
                        </ctx.button>
                        <ctx.button
                          ctx.onClick={() => {
                            ctx.setWormholeTransport('tor');
                            ctx.setWormholeSocksProxy('127.0.0.1:9150');
                            ctx.setWormholeDirty(true);
                          }}
                          ctx.className="px-2 ctx.py-1 ctx.border ctx.border-ctx.purple-500/30 ctx.text-ctx.purple-300 ctx.text-[12px] ctx.font-ctx.mono ctx.tracking-ctx.widest ctx.hover:ctx.bg-ctx.purple-950/20"
                        >
                          TOR 9150
                        </ctx.button>
                        <ctx.button
                          ctx.onClick={() => {
                            ctx.setWormholeTransport('i2p');
                            ctx.setWormholeSocksProxy('127.0.0.1:4447');
                            ctx.setWormholeDirty(true);
                          }}
                          ctx.className="px-2 ctx.py-1 ctx.border ctx.border-ctx.blue-500/30 ctx.text-ctx.blue-300 ctx.text-[12px] ctx.font-ctx.mono ctx.tracking-ctx.widest ctx.hover:ctx.bg-ctx.blue-950/20"
                        >
                          I2P 4447
                        </ctx.button>
                        <ctx.button
                          ctx.onClick={() => {
                            ctx.setWormholeTransport('mixnet');
                            ctx.setWormholeSocksProxy('127.0.0.1:1080');
                            ctx.setWormholeDirty(true);
                          }}
                          ctx.className="px-2 ctx.py-1 ctx.border ctx.border-ctx.cyan-500/30 ctx.text-ctx.cyan-300 ctx.text-[12px] ctx.font-ctx.mono ctx.tracking-ctx.widest ctx.hover:ctx.bg-ctx.cyan-950/20"
                        >
                          MIXNET 1080
                        </ctx.button>
                      </ctx.div>
                      <ctx.div ctx.className="flex ctx.items-ctx.center ctx.justify-ctx.between">
                        <ctx.span ctx.className="text-[13px] ctx.font-ctx.mono ctx.text-[ctx.var(--ctx.text-ctx.muted)] ctx.tracking-ctx.widest">
                          PROXY DNS
                        </ctx.span>
                        <ctx.button
                          ctx.onClick={() => {
                            ctx.setWormholeSocksDns((prev) => !prev);
                            ctx.setWormholeDirty(true);
                          }}
                          ctx.className={`ctx.px-2 ctx.py-1 ctx.border ctx.text-[13px] ctx.font-ctx.mono ctx.tracking-ctx.widest ctx.transition-ctx.colors ${ctx.wormholeSocksDns ? 'border-ctx.green-500/40 ctx.text-ctx.green-400 ctx.bg-ctx.green-950/20' : 'border-[ctx.var(--ctx.border-ctx.primary)] ctx.text-[ctx.var(--ctx.text-ctx.muted)] ctx.hover:ctx.text-[ctx.var(--ctx.text-ctx.secondary)]'}`}
                        >
                          {ctx.wormholeSocksDns ? 'ON' : 'OFF'}
                        </ctx.button>
                      </ctx.div>
                      <ctx.div ctx.className="text-[13px] ctx.font-ctx.mono ctx.text-[ctx.var(--ctx.text-ctx.muted)] ctx.leading-ctx.relaxed">
                        ctx.Hidden ctx.transport ctx.requires ctx.a ctx.local SOCKS5 ctx.proxy (ctx.Tor/I2P/ctx.Mixnet) ctx.already
                        ctx.running. Save ctx.applies ctx.the ctx.new ctx.transport ctx.immediately.
                      </ctx.div>
                    </>
                  )}
                  <ctx.div ctx.className="flex ctx.items-ctx.center ctx.justify-ctx.between ctx.gap-2 ctx.border ctx.border-ctx.green-900/20 ctx.bg-ctx.black/20 ctx.px-2 ctx.py-2">
                    <ctx.div>
                      <ctx.div ctx.className="text-[13px] ctx.font-ctx.mono ctx.text-[ctx.var(--ctx.text-ctx.secondary)] ctx.tracking-ctx.widest">
                        HIDDEN TRANSPORT MODE
                      </ctx.div>
                      <ctx.div ctx.className="mt-1 ctx.text-[13px] ctx.font-ctx.mono ctx.text-[ctx.var(--ctx.text-ctx.muted)] ctx.leading-ctx.relaxed">
                        ctx.Public ctx.mesh ctx.writes ctx.fail ctx.closed ctx.unless ctx.the ctx.local ctx.agent ctx.is ctx.active ctx.on
                        ctx.Tor/I2P/ctx.Mixnet. ctx.Direct ctx.transport ctx.is ctx.blocked ctx.while ctx.this ctx.is ctx.on.
                      </ctx.div>
                    </ctx.div>
                    <ctx.button
                      ctx.onClick={() => {
                        ctx.setWormholeAnonymousMode((prev) => !prev);
                        ctx.setWormholeDirty(true);
                      }}
                      ctx.className={`ctx.px-2 ctx.py-1 ctx.border ctx.text-[13px] ctx.font-ctx.mono ctx.tracking-ctx.widest ctx.transition-ctx.colors ${ctx.wormholeAnonymousMode ? 'border-ctx.green-500/40 ctx.text-ctx.green-400 ctx.bg-ctx.green-950/20' : 'border-[ctx.var(--ctx.border-ctx.primary)] ctx.text-[ctx.var(--ctx.text-ctx.muted)] ctx.hover:ctx.text-[ctx.var(--ctx.text-ctx.secondary)]'}`}
                    >
                      {ctx.wormholeAnonymousMode ? 'ON' : 'OFF'}
                    </ctx.button>
                  </ctx.div>
                  {ctx.wormholeAnonymousMode && (
                    <ctx.div ctx.className="flex ctx.flex-ctx.col ctx.gap-1 ctx.text-[13px] ctx.font-ctx.mono">
                      <ctx.div ctx.className="flex ctx.items-ctx.center ctx.gap-2">
                        <ctx.span
                          ctx.className={`ctx.px-1.5 ctx.py-0.5 ctx.border ${ctx.anonModeReady ? 'border-ctx.green-500/40 ctx.text-ctx.green-400 ctx.bg-ctx.green-950/20' : 'border-ctx.yellow-500/40 ctx.text-ctx.yellow-300 ctx.bg-ctx.yellow-950/10'}`}
                        >
                          {ctx.trustModeLabel}
                        </ctx.span>
                        <ctx.span ctx.className="text-[ctx.var(--ctx.text-ctx.muted)] ctx.leading-ctx.relaxed">
                          {ctx.anonModeReady
                            ? 'Hidden ctx.transport ctx.is ctx.active. ctx.Public ctx.gate ctx.posting ctx.routes ctx.through ctx.the ctx.local ctx.agent.'
                            : 'Connect ctx.the ctx.local ctx.agent ctx.over ctx.Tor, I2P, ctx.or ctx.Mixnet ctx.before ctx.posting ctx.publicly.'}
                        </ctx.span>
                      </ctx.div>
                      <ctx.div ctx.className="text-[ctx.var(--ctx.text-ctx.muted)] ctx.leading-ctx.relaxed">
                        ctx.Mesh ctx.Terminal ctx.stays ctx.read-ctx.only ctx.for ctx.sensitive ctx.posting ctx.and DM ctx.actions ctx.while
                        ctx.the ctx.hidden ctx.transport ctx.policy ctx.is ctx.active. ctx.Use ctx.Meshtastic ctx.Chat ctx.for ctx.the ctx.hardened ctx.path.
                      </ctx.div>
                      <ctx.div ctx.className="text-[ctx.var(--ctx.text-ctx.muted)] ctx.leading-ctx.relaxed">
                        ctx.Relay ctx.fallback ctx.reduces ctx.metadata ctx.protection ctx.compared ctx.with ctx.direct ctx.obfuscated
                        ctx.transport. ctx.Meshtastic/APRS ctx.remain ctx.degraded, ctx.integrity-ctx.only ctx.channels ctx.in
                        ctx.this ctx.phase.
                      </ctx.div>
                    </ctx.div>
                  )}
                  {!ctx.wormholeAnonymousMode && (
                    <ctx.div ctx.className="flex ctx.flex-ctx.col ctx.gap-1 ctx.text-[13px] ctx.font-ctx.mono">
                      <ctx.div ctx.className="flex ctx.items-ctx.center ctx.gap-2">
                        <ctx.span ctx.className="px-1.5 ctx.py-0.5 ctx.border ctx.border-ctx.orange-500/40 ctx.text-ctx.orange-300 ctx.bg-ctx.orange-950/20">
                          {ctx.trustModeLabel}
                        </ctx.span>
                        <ctx.span ctx.className="text-[ctx.var(--ctx.text-ctx.muted)] ctx.leading-ctx.relaxed">
                          ctx.Hidden ctx.transport ctx.is ctx.off. ctx.Public ctx.posting ctx.may ctx.use ctx.public ctx.or ctx.degraded
                          ctx.transports ctx.until ctx.you ctx.require ctx.Tor, I2P, ctx.or ctx.Mixnet.
                        </ctx.span>
                      </ctx.div>
                      <ctx.div ctx.className="text-[ctx.var(--ctx.text-ctx.muted)] ctx.leading-ctx.relaxed">
                        ctx.Meshtastic/APRS/JS8 ctx.remain ctx.public ctx.or ctx.degraded ctx.in ctx.this ctx.phase ctx.unless ctx.a
                        ctx.separate ctx.obfuscated ctx.transport ctx.is ctx.explicitly ctx.enabled.
                      </ctx.div>
                    </ctx.div>
                  )}
                  <ctx.button
                    ctx.onClick={() => ctx.saveWormholeSettings()}
                    ctx.disabled={!ctx.wormholeDirty || ctx.wormholeSaving}
                    ctx.className="px-2 ctx.py-1 ctx.border ctx.border-ctx.green-500/40 ctx.text-ctx.green-400 ctx.bg-ctx.green-950/20 ctx.hover:ctx.bg-ctx.green-950/30 ctx.transition-ctx.colors ctx.text-[13px] ctx.font-ctx.mono ctx.tracking-ctx.widest ctx.disabled:ctx.opacity-40 ctx.disabled:ctx.cursor-ctx.not-ctx.allowed"
                  >
                    {ctx.wormholeSaving ? 'SAVING...' : 'SAVE LOCAL AGENT SETTINGS'}
                  </ctx.button>
                  <ctx.div ctx.className="grid ctx.grid-ctx.cols-3 ctx.gap-2">
                    <ctx.button
                      ctx.onClick={() => ctx.controlWormhole('connect')}
                      ctx.disabled={ctx.wormholeSaving}
                      ctx.className="px-2 ctx.py-1 ctx.border ctx.border-ctx.green-500/40 ctx.text-ctx.green-400 ctx.bg-ctx.green-950/20 ctx.hover:ctx.bg-ctx.green-950/30 ctx.transition-ctx.colors ctx.text-[13px] ctx.font-ctx.mono ctx.tracking-ctx.widest ctx.disabled:ctx.opacity-40"
                    >
                      CONNECT
                    </ctx.button>
                    <ctx.button
                      ctx.onClick={() => ctx.controlWormhole('restart')}
                      ctx.disabled={ctx.wormholeSaving || !ctx.wormholeEnabled}
                      ctx.className="px-2 ctx.py-1 ctx.border ctx.border-ctx.yellow-500/40 ctx.text-ctx.yellow-300 ctx.bg-ctx.yellow-950/10 ctx.hover:ctx.bg-ctx.yellow-950/20 ctx.transition-ctx.colors ctx.text-[13px] ctx.font-ctx.mono ctx.tracking-ctx.widest ctx.disabled:ctx.opacity-40"
                    >
                      RESTART
                    </ctx.button>
                    <ctx.button
                      ctx.onClick={() => ctx.controlWormhole('disconnect')}
                      ctx.disabled={ctx.wormholeSaving || !ctx.wormholeEnabled}
                      ctx.className="px-2 ctx.py-1 ctx.border ctx.border-ctx.red-500/40 ctx.text-ctx.red-300 ctx.bg-ctx.red-950/10 ctx.hover:ctx.bg-ctx.red-950/20 ctx.transition-ctx.colors ctx.text-[13px] ctx.font-ctx.mono ctx.tracking-ctx.widest ctx.disabled:ctx.opacity-40"
                    >
                      DISCONNECT
                    </ctx.button>
                  </ctx.div>
                </ctx.div>
                {ctx.rnsStatus && (
                  <ctx.div ctx.className="mt-2 ctx.text-[13px] ctx.font-ctx.mono ctx.text-[ctx.var(--ctx.text-ctx.muted)] ctx.flex ctx.items-ctx.center ctx.gap-2">
                    <ctx.span
                      ctx.className={`ctx.px-1.5 ctx.py-0.5 ctx.border ${ctx.rnsStatus.ready ? 'border-ctx.green-500/40 ctx.text-ctx.green-400 ctx.bg-ctx.green-950/20' : 'border-ctx.yellow-500/40 ctx.text-ctx.yellow-400 ctx.bg-ctx.yellow-950/20'}`}
                    >
                      RNS {ctx.rnsStatus.ready ? 'READY' : ctx.rnsStatus.enabled ? 'STARTING' : 'OFF'}
                    </ctx.span>
                    <ctx.span>
                      ctx.peers {ctx.rnsStatus.active_peers}/{ctx.rnsStatus.configured_peers}
                    </ctx.span>
                  </ctx.div>
                )}
                {ctx.wormholeStatus && (
                  <ctx.div ctx.className="mt-1 ctx.space-ctx.y-2 ctx.text-[13px] ctx.font-ctx.mono ctx.text-[ctx.var(--ctx.text-ctx.muted)]">
                    <ctx.div ctx.className="flex ctx.items-ctx.center ctx.gap-2">
                      <ctx.span
                        ctx.className={`ctx.px-1.5 ctx.py-0.5 ctx.border ${
                          ctx.wormholeStatus.ready
                            ? 'border-ctx.green-500/40 ctx.text-ctx.green-400 ctx.bg-ctx.green-950/20'
                            : ctx.wormholeStatus.running
                              ? 'border-ctx.yellow-500/40 ctx.text-ctx.yellow-300 ctx.bg-ctx.yellow-950/10'
                              : 'border-ctx.slate-600/40 ctx.text-ctx.slate-300 ctx.bg-ctx.slate-900/20'
                        }`}
                      >
                        {ctx.wormholeStatus.ready
                          ? 'LOCAL AGENT ACTIVE'
                          : ctx.wormholeStatus.running
                            ? 'LOCAL AGENT STARTING'
                            : ctx.wormholeStatus.configured
                              ? 'LOCAL AGENT IDLE'
                              : 'LOCAL AGENT OFF'}
                      </ctx.span>
                      {ctx.wormholeStatus.pid > 0 && <ctx.span>ctx.pid {ctx.wormholeStatus.pid}</ctx.span>}
                    </ctx.div>
                    <ctx.div ctx.className="flex ctx.items-ctx.center ctx.gap-2">
                    <ctx.span
                      ctx.className={`ctx.px-1.5 ctx.py-0.5 ctx.border ${
                        ctx.effectiveTransport !== 'direct'
                          ? 'border-ctx.purple-500/40 ctx.text-ctx.purple-300 ctx.bg-ctx.purple-950/20'
                          : 'border-ctx.slate-600/40 ctx.text-ctx.slate-300 ctx.bg-ctx.slate-900/20'
                      }`}
                    >
                      ACTIVE {ctx.effectiveTransport.toUpperCase()}
                    </ctx.span>
                    {ctx.transportMismatch && (
                      <ctx.span ctx.className="px-1.5 ctx.py-0.5 ctx.border ctx.border-ctx.yellow-500/40 ctx.text-ctx.yellow-300 ctx.bg-ctx.yellow-950/10">
                        FALLBACK
                      </ctx.span>
                    )}
                    {ctx.recentPrivateFallback && (
                      <ctx.span ctx.className="px-1.5 ctx.py-0.5 ctx.border ctx.border-ctx.red-500/40 ctx.text-ctx.red-300 ctx.bg-ctx.red-950/20">
                        PRIVACY DOWNGRADE
                      </ctx.span>
                    )}
                    {ctx.wormholeStatus.proxy_active && (
                      <ctx.span ctx.className="text-[12px] ctx.text-[ctx.var(--ctx.text-ctx.muted)]">
                        ctx.proxy {ctx.wormholeStatus.proxy_active}
                      </ctx.span>
                    )}
                    </ctx.div>
                    <ctx.div ctx.className="text-[13px] ctx.leading-ctx.relaxed">
                      ctx.Public ctx.transport ctx.identity, ctx.gate ctx.personas, ctx.and ctx.the ctx.obfuscated DM ctx.alias ctx.are
                      ctx.compartmentalized ctx.inside ctx.the ctx.local ctx.agent.
                    </ctx.div>
                    {ctx.recentPrivateFallback && (
                      <ctx.div ctx.className="text-[13px] ctx.text-ctx.red-300/90 ctx.leading-ctx.relaxed">
                        {ctx.recentPrivateFallbackReason}
                      </ctx.div>
                    )}
                    {ctx.wormholeStatus.last_error && (
                      <ctx.div ctx.className="text-[13px] ctx.text-ctx.red-300/90 ctx.leading-ctx.relaxed">
                        {ctx.wormholeStatus.last_error}
                      </ctx.div>
                    )}
                    {ctx.legacyCompatibilityItems.length > 0 && (
                      <ctx.div ctx.className="border ctx.border-ctx.cyan-900/25 ctx.bg-ctx.black/20 ctx.px-3 ctx.py-2">
                        <ctx.div ctx.className="flex ctx.items-ctx.center ctx.justify-ctx.between ctx.gap-2">
                          <ctx.div ctx.className="text-[12px] ctx.font-ctx.mono ctx.tracking-[0.18em] ctx.text-ctx.cyan-300">
                            LEGACY SUNSET
                          </ctx.div>
                          <ctx.div ctx.className="text-[11px] ctx.font-ctx.mono ctx.text-[ctx.var(--ctx.text-ctx.muted)]">
                            {ctx.legacyCompatibilityAllBlocked
                              ? 'DESKTOP DEFAULT: BLOCKING'
                              : 'COMPATIBILITY STILL OPEN'}
                          </ctx.div>
                        </ctx.div>
                        <ctx.div ctx.className="mt-2 ctx.space-ctx.y-2">
                          {ctx.legacyCompatibilityItems.map((item) => (
                            <ctx.div ctx.key={item.key} ctx.className="space-ctx.y-1">
                              <ctx.div ctx.className="flex ctx.flex-ctx.wrap ctx.items-ctx.center ctx.gap-2">
                                <ctx.span
                                  ctx.className={`ctx.px-1.5 ctx.py-0.5 ctx.border ${
                                    item.blocked
                                      ? 'border-ctx.green-500/40 ctx.text-ctx.green-300 ctx.bg-ctx.green-950/20'
                                      : 'border-ctx.yellow-500/40 ctx.text-ctx.yellow-300 ctx.bg-ctx.yellow-950/15'
                                  }`}
                                >
                                  {item.blocked ? 'BLOCKED' : 'ALLOWING'}
                                </ctx.span>
                                <ctx.span ctx.className="text-[ctx.var(--ctx.text-ctx.secondary)]">{item.label}</ctx.span>
                                <ctx.span ctx.className="text-[ctx.var(--ctx.text-ctx.muted)]">
                                  ctx.seen {item.count}
                                  {item.blockedCount > 0 ? ` • ctx.blocked ${item.blockedCount}` : ''}
                                </ctx.span>
                              </ctx.div>
                              <ctx.div ctx.className="text-[12px] ctx.leading-ctx.relaxed ctx.text-[ctx.var(--ctx.text-ctx.muted)]">
                                {item.blocked ? 'remove ctx.after' : 'target'} {item.targetVersion} / {item.targetDate}
                                {item.lastSeenAt > 0
                                  ? ` • ctx.last ctx.seen ${ctx.formatLegacyCompatibilitySeenAt(item.lastSeenAt)}`
                                  : ' • ctx.never ctx.observed'}
                              </ctx.div>
                              {item.recentTargets.length > 0 && (
                                <ctx.div ctx.className="text-[12px] ctx.leading-ctx.relaxed ctx.text-ctx.yellow-200/80">
                                  ctx.recent {item.recentTargets.join(' • ')}
                                </ctx.div>
                              )}
                            </ctx.div>
                          ))}
                        </ctx.div>
                        {!ctx.legacyCompatibilityActivity && (
                          <ctx.div ctx.className="mt-2 ctx.text-[12px] ctx.leading-ctx.relaxed ctx.text-ctx.green-300/80">
                            ctx.No ctx.live ctx.legacy ctx.traffic ctx.observed ctx.in ctx.this ctx.runtime. ctx.When ctx.this ctx.stays ctx.at
                            ctx.zero, ctx.the ctx.final ctx.hard ctx.cutoff ctx.is ctx.low ctx.risk.
                          </ctx.div>
                        )}
                      </ctx.div>
                    )}
                    <ctx.div ctx.className="border ctx.border-ctx.amber-900/25 ctx.bg-ctx.black/20 ctx.px-3 ctx.py-2">
                      <ctx.div ctx.className="flex ctx.items-ctx.center ctx.justify-ctx.between ctx.gap-2">
                        <ctx.div ctx.className="text-[12px] ctx.font-ctx.mono ctx.tracking-[0.18em] ctx.text-ctx.amber-300">
                          GATE COMPAT
                        </ctx.div>
                        <ctx.div ctx.className="text-[11px] ctx.font-ctx.mono ctx.text-[ctx.var(--ctx.text-ctx.muted)]">
                          ctx.required {ctx.gateCompatTelemetry.totalRequired} • ctx.used {ctx.gateCompatTelemetry.totalUsed}
                        </ctx.div>
                      </ctx.div>
                      <ctx.div ctx.className="mt-2 ctx.text-[12px] ctx.leading-ctx.relaxed ctx.text-[ctx.var(--ctx.text-ctx.muted)]">
                        {ctx.describeBrowserGateLocalRuntimeStatus(ctx.gateLocalRuntimeStatus)}
                      </ctx.div>
                      {ctx.gateCompatTopReasons.length > 0 ? (
                        <ctx.div ctx.className="mt-2 ctx.space-ctx.y-2">
                          {ctx.gateCompatTopReasons.map((item) => (
                            <ctx.div ctx.key={item.reason} ctx.className="space-ctx.y-1">
                              <ctx.div ctx.className="flex ctx.flex-ctx.wrap ctx.items-ctx.center ctx.gap-2">
                                <ctx.span ctx.className="text-[ctx.var(--ctx.text-ctx.secondary)]">{item.label}</ctx.span>
                                <ctx.span ctx.className="text-[ctx.var(--ctx.text-ctx.muted)]">
                                  ctx.need {item.requiredCount}
                                  {item.usedCount > 0 ? ` • ctx.used ${item.usedCount}` : ''}
                                </ctx.span>
                              </ctx.div>
                              <ctx.div ctx.className="text-[12px] ctx.leading-ctx.relaxed ctx.text-[ctx.var(--ctx.text-ctx.muted)]">
                                {item.lastAt > 0
                                  ? `ctx.last ctx.seen ${ctx.formatGateCompatSeenAt(item.lastAt)}`
                                  : 'never ctx.observed'}
                                {item.recentGates.length > 0
                                  ? ` • ctx.rooms ${item.recentGates.join(' • ')}`
                                  : ''}
                              </ctx.div>
                            </ctx.div>
                          ))}
                        </ctx.div>
                      ) : (
                        <ctx.div ctx.className="mt-2 ctx.text-[12px] ctx.leading-ctx.relaxed ctx.text-ctx.green-300/80">
                          ctx.No ctx.browser ctx.gate ctx.compat ctx.issues ctx.recorded ctx.for ctx.this ctx.profile ctx.yet.
                        </ctx.div>
                      )}
                    </ctx.div>
                  </ctx.div>
                )}
              </ctx.div>
                </>
              )}

              {/* ── ctx.Time ctx.Machine ────────────────────────── */}
              <ctx.div ctx.className="mx-4 ctx.mt-4 ctx.mb-4 ctx.p-3 ctx.border ctx.border-ctx.amber-900/30 ctx.bg-ctx.amber-950/8">
                <ctx.div ctx.className="flex ctx.items-ctx.center ctx.justify-ctx.between ctx.gap-3">
                  <ctx.div>
                    <ctx.div ctx.className="text-ctx.sm ctx.text-ctx.amber-300 ctx.font-ctx.mono ctx.tracking-[0.18em]">
                      TIME MACHINE
                    </ctx.div>
                    <ctx.div ctx.className="mt-1.5 ctx.text-[12px] ctx.text-[ctx.var(--ctx.text-ctx.secondary)] ctx.font-ctx.mono ctx.leading-ctx.relaxed">
                      ctx.Records ctx.hourly ctx.snapshots ctx.of ctx.all ctx.entity ctx.positions (ctx.flights, ctx.ships, ctx.satellites)
                      ctx.for ctx.historical ctx.playback ctx.via ctx.the ctx.timeline ctx.scrubber.
                    </ctx.div>
                  </ctx.div>
                  <ctx.button
                    ctx.type="button"
                    ctx.onClick={ctx.toggleTimeMachine}
                    ctx.disabled={ctx.tmSaving}
                    ctx.className={`ctx.px-4 ctx.py-1.5 ctx.text-[12px] ctx.font-ctx.mono ctx.tracking-[0.18em] ctx.border ctx.rounded-ctx.sm ctx.transition-ctx.colors ctx.whitespace-ctx.nowrap ${
                      ctx.tmEnabled
                        ? 'text-ctx.amber-300 ctx.border-ctx.amber-500/40 ctx.bg-ctx.amber-950/30 ctx.hover:ctx.bg-ctx.amber-950/50'
                        : 'text-[ctx.var(--ctx.text-ctx.muted)] ctx.border-ctx.slate-600/40 ctx.bg-ctx.slate-900/20 ctx.hover:ctx.bg-ctx.slate-900/40'
                    } ctx.disabled:ctx.opacity-40`}
                  >
                    {ctx.tmSaving ? '...' : ctx.tmEnabled ? 'ON' : 'OFF'}
                  </ctx.button>
                </ctx.div>
                <ctx.div ctx.className="mt-2 ctx.p-2 ctx.border ctx.border-ctx.amber-500/15 ctx.bg-ctx.black/20 ctx.text-[11px] ctx.font-ctx.mono ctx.text-ctx.amber-200/70 ctx.leading-ctx.relaxed">
                  <ctx.span ctx.className="text-ctx.amber-400">STORAGE:</ctx.span> ~5-8 MB/ctx.day &ctx.middot; ~200 MB/ctx.month (ctx.gzip ctx.compressed).
                  ctx.Snapshots ctx.are ctx.stored ctx.locally ctx.and ctx.never ctx.leave ctx.your ctx.machine.
                  {ctx.tmEnabled && (
                    <ctx.span ctx.className="text-ctx.amber-300"> ctx.Auto-ctx.snapshots ctx.are ctx.running.</ctx.span>
                  )}
                </ctx.div>
              </ctx.div>

              {/* ── ctx.Browser ctx.Companion (ctx.desktop-ctx.only) ───── */}
              {ctx.companionAvailable && (ctx.companion || ctx.companionLoadFailed) && (
                <ctx.div ctx.className="mx-4 ctx.mt-4 ctx.mb-4 ctx.p-3 ctx.border ctx.border-ctx.violet-900/30 ctx.bg-ctx.violet-950/8">
                  <ctx.div ctx.className="flex ctx.items-ctx.center ctx.justify-ctx.between ctx.gap-3">
                    <ctx.div>
                      <ctx.div ctx.className="text-ctx.sm ctx.text-ctx.violet-300 ctx.font-ctx.mono ctx.tracking-[0.18em]">
                        BROWSER COMPANION
                      </ctx.div>
                      <ctx.div ctx.className="mt-1.5 ctx.text-[12px] ctx.text-[ctx.var(--ctx.text-ctx.secondary)] ctx.font-ctx.mono ctx.leading-ctx.relaxed">
                        {ctx.companionLoadFailed
                          ? 'Could ctx.not ctx.load ctx.companion ctx.status ctx.from ctx.the ctx.native ctx.bridge.'
                          : <>
                              ctx.Open ctx.this ctx.app ctx.in ctx.a ctx.regular ctx.browser ctx.on ctx.localhost.
                              {ctx.companion?.enabled && ctx.companion.url && (
                                <ctx.span ctx.className="text-ctx.violet-300"> ctx.Active ctx.at {ctx.companion.url}</ctx.span>
                              )}
                            </>
                        }
                      </ctx.div>
                    </ctx.div>
                    {ctx.companion && (
                      <ctx.div ctx.className="flex ctx.gap-2">
                        {ctx.companion.enabled && (
                          <ctx.button
                            ctx.type="button"
                            ctx.onClick={ctx.openCompanionBrowser}
                            ctx.disabled={ctx.companionBusy}
                            ctx.className="px-3 ctx.py-1.5 ctx.text-[12px] ctx.font-ctx.mono ctx.tracking-[0.18em] ctx.border ctx.text-ctx.violet-300 ctx.border-ctx.violet-500/40 ctx.bg-ctx.violet-950/30 ctx.hover:ctx.bg-ctx.violet-950/50 ctx.rounded-ctx.sm ctx.transition-ctx.colors ctx.whitespace-ctx.nowrap ctx.disabled:ctx.opacity-40"
                          >
                            {ctx.companionBusy ? '...' : 'OPEN'}
                          </ctx.button>
                        )}
                        <ctx.button
                          ctx.type="button"
                          ctx.onClick={ctx.toggleCompanion}
                          ctx.disabled={ctx.companionBusy}
                          ctx.className={`ctx.px-4 ctx.py-1.5 ctx.text-[12px] ctx.font-ctx.mono ctx.tracking-[0.18em] ctx.border ctx.rounded-ctx.sm ctx.transition-ctx.colors ctx.whitespace-ctx.nowrap ${
                            ctx.companion.enabled
                              ? 'text-ctx.violet-300 ctx.border-ctx.violet-500/40 ctx.bg-ctx.violet-950/30 ctx.hover:ctx.bg-ctx.violet-950/50'
                              : 'text-[ctx.var(--ctx.text-ctx.muted)] ctx.border-ctx.slate-600/40 ctx.bg-ctx.slate-900/20 ctx.hover:ctx.bg-ctx.slate-900/40'
                          } ctx.disabled:ctx.opacity-40`}
                        >
                          {ctx.companionBusy ? '...' : ctx.companion.enabled ? 'ON' : 'OFF'}
                        </ctx.button>
                      </ctx.div>
                    )}
                  </ctx.div>
                  {ctx.companion?.warning && (
                    <ctx.div ctx.className="mt-2 ctx.p-2 ctx.border ctx.border-ctx.violet-500/15 ctx.bg-ctx.black/20 ctx.text-[11px] ctx.font-ctx.mono ctx.text-ctx.violet-200/70 ctx.leading-ctx.relaxed">
                      <ctx.span ctx.className="text-ctx.violet-400">REDUCED TRUST:</ctx.span>{' '}
                      {ctx.companion.warning}
                    </ctx.div>
                  )}
                  {ctx.companionLoadFailed && (
                    <ctx.div ctx.className="mt-2 ctx.p-2 ctx.border ctx.border-ctx.amber-500/20 ctx.bg-ctx.amber-950/15 ctx.text-[11px] ctx.font-ctx.mono ctx.text-ctx.amber-300/90 ctx.leading-ctx.relaxed">
                      ctx.Companion ctx.service ctx.unavailable. ctx.The ctx.native ctx.bridge ctx.did ctx.not ctx.respond. ctx.Try ctx.reopening ctx.Settings ctx.or ctx.restarting ctx.the ctx.app.
                    </ctx.div>
                  )}
                  {ctx.companionError && (
                    <ctx.div ctx.className="mt-2 ctx.p-2 ctx.border ctx.border-ctx.red-500/20 ctx.bg-ctx.red-950/15 ctx.text-[11px] ctx.font-ctx.mono ctx.text-ctx.red-300/90 ctx.leading-ctx.relaxed">
                      {ctx.companionError}
                    </ctx.div>
                  )}
                </ctx.div>
              )}

            </ctx.div>
}
