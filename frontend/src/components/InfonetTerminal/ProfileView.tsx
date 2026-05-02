'use client';

import React, { useEffect, useState } from 'react';
import { ChevronLeft, User, Eye, EyeOff, Wallet, Activity, ShieldCheck, AlertCircle } from 'lucide-react';
import QRCode from 'qrcode';

import { API_BASE } from '@/lib/api';
import { exportWormholeDmInvite } from '@/mesh/wormholeIdentityClient';

interface ProfileViewProps {
  onBack: () => void;
  persona: string;
  isCitizen: boolean;
  nodeId?: string | null;
  publicKey?: string | null;
}

interface ReputationSummary {
  overall: number;
  upvotes: number;
  downvotes: number;
}

interface OracleProfileSummary {
  oracle_rep: number;
  oracle_rep_total: number;
  oracle_rep_locked: number;
  predictions_won: number;
  predictions_lost: number;
  win_rate: number;
}

const EMPTY_REPUTATION: ReputationSummary = {
  overall: 0,
  upvotes: 0,
  downvotes: 0,
};

const EMPTY_ORACLE_PROFILE: OracleProfileSummary = {
  oracle_rep: 0,
  oracle_rep_total: 0,
  oracle_rep_locked: 0,
  predictions_won: 0,
  predictions_lost: 0,
  win_rate: 0,
};

export default function ProfileView({ onBack, persona, isCitizen, nodeId, publicKey }: ProfileViewProps) {
  const [showWallet, setShowWallet] = useState(false);
  const [showBalance, setShowBalance] = useState(true);
  const [showTransactions, setShowTransactions] = useState(false);
  const [reputation, setReputation] = useState<ReputationSummary>(EMPTY_REPUTATION);
  const [oracleProfile, setOracleProfile] = useState<OracleProfileSummary>(EMPTY_ORACLE_PROFILE);
  const [dmInviteBusy, setDmInviteBusy] = useState(false);
  const [dmInviteBlob, setDmInviteBlob] = useState('');
  const [dmInviteQrSrc, setDmInviteQrSrc] = useState('');
  const [dmInviteFingerprint, setDmInviteFingerprint] = useState('');
  const [dmInviteStatus, setDmInviteStatus] = useState<{ type: 'ok' | 'err'; text: string } | null>(null);

  useEffect(() => {
    let active = true;

    const loadProfileStats = async () => {
      if (!nodeId) {
        setReputation(EMPTY_REPUTATION);
        setOracleProfile(EMPTY_ORACLE_PROFILE);
        return;
      }

      const [repResult, oracleResult] = await Promise.allSettled([
        fetch(`${API_BASE}/api/mesh/reputation?node_id=${encodeURIComponent(nodeId)}`, { cache: 'no-store' }),
        fetch(`${API_BASE}/api/mesh/oracle/profile?node_id=${encodeURIComponent(nodeId)}`, { cache: 'no-store' }),
      ]);

      if (!active) {
        return;
      }

      if (repResult.status === 'fulfilled' && repResult.value.ok) {
        try {
          const data = await repResult.value.json();
          if (active) {
            setReputation({
              overall: Number(data?.overall || 0),
              upvotes: Number(data?.upvotes || 0),
              downvotes: Number(data?.downvotes || 0),
            });
          }
        } catch {
          if (active) {
            setReputation(EMPTY_REPUTATION);
          }
        }
      } else if (active) {
        setReputation(EMPTY_REPUTATION);
      }

      if (oracleResult.status === 'fulfilled' && oracleResult.value.ok) {
        try {
          const data = await oracleResult.value.json();
          if (active) {
            setOracleProfile({
              oracle_rep: Number(data?.oracle_rep || 0),
              oracle_rep_total: Number(data?.oracle_rep_total || 0),
              oracle_rep_locked: Number(data?.oracle_rep_locked || 0),
              predictions_won: Number(data?.predictions_won || 0),
              predictions_lost: Number(data?.predictions_lost || 0),
              win_rate: Number(data?.win_rate || 0),
            });
          }
        } catch {
          if (active) {
            setOracleProfile(EMPTY_ORACLE_PROFILE);
          }
        }
      } else if (active) {
        setOracleProfile(EMPTY_ORACLE_PROFILE);
      }
    };

    void loadProfileStats();

    return () => {
      active = false;
    };
  }, [nodeId]);

  useEffect(() => {
    let active = true;
    if (!dmInviteBlob) {
      setDmInviteQrSrc('');
      return () => {
        active = false;
      };
    }

    void QRCode.toDataURL(dmInviteBlob, {
      errorCorrectionLevel: 'M',
      margin: 1,
      width: 320,
      color: {
        dark: '#34d399',
        light: '#05080d',
      },
    })
      .then((dataUrl) => {
        if (active) {
          setDmInviteQrSrc(dataUrl);
        }
      })
      .catch(() => {
        if (active) {
          setDmInviteQrSrc('');
        }
      });

    return () => {
      active = false;
    };
  }, [dmInviteBlob]);

  const displayNodeId = nodeId?.trim() || 'NOT PROVISIONED';
  const displayPersona = persona?.trim() || 'unassigned';
  const creditsReference = publicKey?.trim() || 'Not provisioned';
  const creditsBalance = 0;
  const transactions: Array<{
    id: string;
    date: string;
    type: string;
    amount: string;
    from?: string;
    to?: string;
    status: string;
  }> = [];

  const overallRep = reputation.overall;
  const repProgress = Math.max(0, Math.min(100, overallRep));
  const upvotes = reputation.upvotes;
  const downvotes = reputation.downvotes;
  const oracleRep = oracleProfile.oracle_rep;
  const oracleRepTotal = oracleProfile.oracle_rep_total;
  const oracleRepLocked = oracleProfile.oracle_rep_locked;
  const oracleProgress = oracleRepTotal > 0 ? Math.max(0, Math.min(100, (oracleRep / oracleRepTotal) * 100)) : 0;

  const handleGenerateDmInvite = async () => {
    setDmInviteBusy(true);
    setDmInviteStatus(null);
    try {
      const exported = await exportWormholeDmInvite();
      setDmInviteBlob(JSON.stringify(exported, null, 2));
      setDmInviteFingerprint(String(exported.trust_fingerprint || ''));
      setDmInviteStatus({
        type: 'ok',
        text: 'Signed DM invite generated. Share it only over a trusted out-of-band channel.',
      });
    } catch (error) {
      setDmInviteStatus({
        type: 'err',
        text: error instanceof Error ? error.message : 'dm_invite_export_failed',
      });
    } finally {
      setDmInviteBusy(false);
    }
  };

  const handleCopyDmInvite = async () => {
    if (!dmInviteBlob || !navigator?.clipboard?.writeText) {
      return;
    }
    try {
      await navigator.clipboard.writeText(dmInviteBlob);
      setDmInviteStatus({
        type: 'ok',
        text: 'Signed DM invite copied to clipboard.',
      });
    } catch (error) {
      setDmInviteStatus({
        type: 'err',
        text: error instanceof Error ? error.message : 'clipboard_write_failed',
      });
    }
  };

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden">
      <div className="border-b border-gray-800 pb-4 mb-4 shrink-0">
        <button
          onClick={onBack}
          className="flex items-center text-cyan-500 hover:text-cyan-400 transition-all uppercase text-xs tracking-widest border border-cyan-900/50 px-3 py-1 bg-cyan-900/10 hover:bg-cyan-900/30 hover:border-cyan-500/50 mb-4"
        >
          <ChevronLeft size={14} className="mr-1" />
          RETURN TO MAIN
        </button>
        <h1 className="text-2xl font-bold text-cyan-400 uppercase tracking-widest flex items-center">
          <User className="mr-2 text-cyan-400" />
          {isCitizen ? 'CITIZEN' : 'SOVEREIGN'} PROFILE
        </h1>
        <p className="text-gray-500 text-sm mt-1">Identity, reputation, and credits ledger.</p>
      </div>

      <div className="flex-1 overflow-y-auto pr-2 space-y-6 pb-4">
        <div className="border border-gray-800 bg-gray-900/20 p-4">
          <h2 className="text-cyan-400 font-bold mb-4 border-b border-gray-800 pb-2 flex items-center">
            <User size={16} className="mr-2" /> IDENTITY
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <p className="text-gray-500 text-xs uppercase tracking-widest">Agent ID</p>
              <p className="text-sm text-cyan-400 font-mono">{displayNodeId}</p>
              <p className="text-gray-500 text-xs uppercase tracking-widest mt-3">Current Persona</p>
              <p className="text-xl text-gray-300 font-bold">{displayPersona}</p>
            </div>
            <div>
              <p className="text-gray-500 text-xs uppercase tracking-widest">Citizenship Status</p>
              <p className={`text-xl font-bold ${isCitizen ? 'text-green-400' : 'text-amber-500'}`}>
                {isCitizen ? 'ACTIVE CITIZEN' : 'SOVEREIGN'}
              </p>
            </div>

            <div className="md:col-span-2 border-t border-gray-800 pt-4 mt-2">
              <div className="flex justify-between items-end mb-2">
                <div>
                  <p className="text-gray-500 text-xs uppercase tracking-widest">Common Rep (Public Reputation)</p>
                  <p className="text-2xl text-cyan-400 font-bold">
                    {overallRep} <span className="text-sm text-gray-600">net</span>
                  </p>
                </div>
                <div className="grid grid-cols-2 gap-4 text-right">
                  <div>
                    <p className="text-sm text-gray-500 uppercase tracking-widest">Lit</p>
                    <p className="text-lg font-bold text-green-400">{upvotes}</p>
                  </div>
                  <div>
                    <p className="text-sm text-gray-500 uppercase tracking-widest">Dislikes</p>
                    <p className="text-lg font-bold text-red-400">{downvotes}</p>
                  </div>
                </div>
              </div>
              <div className="h-3 w-full bg-gray-900 border border-gray-800 overflow-hidden relative">
                <div
                  className="h-full bg-cyan-400 transition-all duration-500 shadow-[0_0_10px_rgba(6,182,212,0.5)]"
                  style={{ width: `${repProgress}%` }}
                />
              </div>
              <p className="mt-2 text-sm text-gray-500 uppercase tracking-tighter">
                Reputation is derived from live lit/dislike activity. Net rep can drop below zero even when the bar is clamped at zero.
              </p>
            </div>

            <div className="grid grid-cols-2 gap-4 md:col-span-2 mt-2">
              <div className="p-3 bg-gray-900/40 border border-gray-800">
                <p className="text-sm text-gray-500 uppercase tracking-widest">Active Months</p>
                <p className="text-xl text-white font-bold">0 MONTHS</p>
                <p className="text-[13px] text-gray-600 mt-1 uppercase">No live citizenship accounting yet</p>
              </div>
              <div className="p-3 bg-gray-900/40 border border-gray-800">
                <p className="text-sm text-gray-500 uppercase tracking-widest">Citizenship History</p>
                <p className="text-xl text-gray-400 font-bold">0 MONTHS</p>
                <p className="text-[13px] text-gray-600 mt-1 uppercase">Placeholder totals removed</p>
              </div>
            </div>

            <div className="md:col-span-2">
              <p className="text-gray-500 text-xs uppercase tracking-widest mb-1">Oracle Rep (Truth)</p>
              <div className="flex flex-col">
                <div className="flex items-center justify-between mb-1">
                  <p className="text-xl text-cyan-400 font-bold">
                    {oracleRep.toFixed(1)} <span className="text-xs text-gray-500 font-normal">AVAILABLE</span>
                  </p>
                  <p className="text-sm text-gray-500 uppercase">
                    Win Rate {oracleProfile.win_rate}% • W {oracleProfile.predictions_won} / L {oracleProfile.predictions_lost}
                  </p>
                </div>
                <div className="h-1.5 w-full bg-gray-900 border border-gray-800 overflow-hidden mb-1">
                  <div
                    className="h-full bg-cyan-500 transition-all duration-500 shadow-[0_0_10px_rgba(6,182,212,0.5)]"
                    style={{ width: `${oracleProgress}%` }}
                  />
                </div>
                <p className="text-sm text-gray-500 uppercase tracking-tighter">
                  Available: {oracleRep.toFixed(1)} | Locked: {oracleRepLocked.toFixed(1)} | Total: {oracleRepTotal.toFixed(1)}
                </p>
              </div>
            </div>
          </div>
        </div>

        <div className="border border-gray-800 bg-gray-900/20 p-4">
          <h2 className="text-cyan-400 font-bold mb-4 border-b border-gray-800 pb-2 flex items-center">
            <ShieldCheck size={16} className="mr-2" /> NETWORK HEALTH (VCS ANALYSIS)
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div className="flex flex-col items-center justify-center p-4 border border-gray-800 bg-[#0a0a0a]">
              <p className="text-sm text-gray-500 uppercase tracking-widest mb-2">Vote Correlation</p>
              <div className="relative h-20 w-20">
                <svg className="h-full w-full" viewBox="0 0 36 36">
                  <path className="stroke-gray-800 stroke-[3]" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                  <path className="stroke-gray-500 stroke-[3] transition-all duration-1000" fill="none" strokeDasharray="0, 100" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                </svg>
                <div className="absolute inset-0 flex items-center justify-center">
                  <span className="text-sm font-bold text-gray-400">0.00</span>
                </div>
              </div>
              <p className="text-[12px] text-gray-500 mt-2 uppercase">NOT CALIBRATED</p>
            </div>

            <div className="md:col-span-2 space-y-4">
              <div>
                <div className="flex justify-between items-center mb-1">
                  <p className="text-sm text-gray-500 uppercase tracking-widest">Clustering Coefficient</p>
                  <p className="text-sm text-gray-400 font-bold">0.00</p>
                </div>
                <div className="h-1 w-full bg-gray-900 overflow-hidden">
                  <div className="h-full bg-gray-500 w-0" />
                </div>
              </div>
              <div>
                <div className="flex justify-between items-center mb-1">
                  <p className="text-sm text-gray-500 uppercase tracking-widest">Temporal Burst Detection</p>
                  <p className="text-sm text-gray-400 font-bold">0.00</p>
                </div>
                <div className="h-1 w-full bg-gray-900 overflow-hidden">
                  <div className="h-full bg-gray-500 w-0" />
                </div>
              </div>
              <div className="p-2 border border-gray-800 bg-gray-900/20 flex items-start gap-2">
                <AlertCircle size={14} className="text-gray-500 shrink-0 mt-0.5" />
                <p className="text-[13px] text-gray-500 uppercase leading-tight">
                  Advanced network-health analytics are not calibrated for this profile yet. Live reputation above is authoritative; unresolved analytics stay zeroed.
                </p>
              </div>
            </div>
          </div>
        </div>

        <div className="border border-gray-800 bg-gray-900/20 p-4">
          <h2 className="text-cyan-400 font-bold mb-4 border-b border-gray-800 pb-2 flex items-center">
            <User size={16} className="mr-2" /> IDENTITY DOMAINS (HARD SEPARATION)
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            <div className="border border-gray-800 p-2 bg-[#0a0a0a]">
              <p className="text-sm text-gray-500 uppercase tracking-widest">Root</p>
              <p className="text-xs text-red-400 font-bold">NEVER PUBLIC</p>
            </div>
            <div className="border border-gray-800 p-2 bg-[#0a0a0a]">
              <p className="text-sm text-gray-500 uppercase tracking-widest">Transport</p>
              <p className="text-xs text-green-400 font-bold">PUBLIC MESH</p>
            </div>
            <div className="border border-gray-800 p-2 bg-[#0a0a0a]">
              <p className="text-sm text-gray-500 uppercase tracking-widest">DM Alias</p>
              <p className="text-xs text-cyan-400 font-bold">SEMI-OBFUSCATED</p>
            </div>
            <div className="border border-gray-800 p-2 bg-[#0a0a0a]">
              <p className="text-sm text-gray-500 uppercase tracking-widest">Gate Session</p>
              <p className="text-xs text-cyan-400 font-bold">ANONYMOUS</p>
            </div>
            <div className="border border-gray-800 p-2 bg-[#0a0a0a]">
              <p className="text-sm text-gray-500 uppercase tracking-widest">Gate Persona</p>
              <p className="text-xs text-cyan-400 font-bold">{displayPersona}</p>
            </div>
            <div className="border border-gray-800 p-2 bg-[#0a0a0a]">
              <p className="text-sm text-gray-500 uppercase tracking-widest">Credits</p>
              <p className="text-xs text-gray-300 font-bold">0.00 AVAILABLE</p>
            </div>
          </div>
        </div>

        <div className="border border-gray-800 bg-gray-900/20 p-4">
          <h2 className="text-cyan-400 font-bold mb-4 border-b border-gray-800 pb-2 flex items-center">
            <ShieldCheck size={16} className="mr-2" /> FIRST-CONTACT BOOTSTRAP
          </h2>
          <div className="space-y-4">
            <p className="text-sm text-gray-400 leading-[1.7]">
              Export a signed DM invite for trusted out-of-band exchange. This pins first contact to
              your messaging identity instead of plain first-sight TOFU. It does not link wallet,
              reputation, or other personas.
            </p>
            <div className="flex flex-wrap gap-3">
              <button
                onClick={() => void handleGenerateDmInvite()}
                disabled={dmInviteBusy}
                className="px-4 py-2 border border-cyan-500/40 bg-cyan-950/20 text-cyan-300 text-xs tracking-[0.18em] uppercase disabled:opacity-50"
              >
                {dmInviteBusy ? 'Generating...' : 'Generate Signed DM Invite'}
              </button>
              <button
                onClick={() => void handleCopyDmInvite()}
                disabled={!dmInviteBlob}
                className="px-4 py-2 border border-emerald-500/40 bg-emerald-950/20 text-emerald-300 text-xs tracking-[0.18em] uppercase disabled:opacity-50"
              >
                Copy Invite
              </button>
            </div>
            {dmInviteFingerprint && (
              <div className="text-sm text-emerald-300 font-mono">
                Trust fingerprint: {dmInviteFingerprint}
              </div>
            )}
            {dmInviteStatus && (
              <div
                className={`px-3 py-2 border text-sm ${
                  dmInviteStatus.type === 'ok'
                    ? 'border-emerald-500/30 bg-emerald-950/20 text-emerald-300'
                    : 'border-red-500/30 bg-red-950/20 text-red-300'
                }`}
              >
                {dmInviteStatus.text}
              </div>
            )}
            <textarea
              value={dmInviteBlob}
              readOnly
              className="w-full min-h-[220px] bg-[#0a0a0a] border border-gray-800 px-4 py-3 text-sm text-gray-300 font-mono outline-none"
              placeholder="Generate a signed DM invite to display the export blob here."
              spellCheck={false}
            />
            {dmInviteQrSrc && (
              <div className="border border-emerald-500/20 bg-[#0a0a0a] p-4">
                <div className="text-xs text-emerald-300 uppercase tracking-[0.18em] mb-3">
                  QR Invite
                </div>
                <div className="flex flex-col items-center gap-3">
                  <img
                    src={dmInviteQrSrc}
                    alt="Signed DM invite QR"
                    className="w-[320px] max-w-full border border-gray-800 bg-black p-3"
                  />
                  <div className="text-xs text-gray-500 text-center leading-[1.65] max-w-[32rem]">
                    Scan this over a trusted out-of-band channel. The QR carries the same signed DM
                    invite shown above, including the trust fingerprint and signature envelope.
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="border border-gray-800 bg-gray-900/20 p-4">
          <h2 className="text-cyan-400 font-bold mb-4 border-b border-gray-800 pb-2 flex items-center">
            <Wallet size={16} className="mr-2" /> CREDITS LEDGER
          </h2>

          <div className="space-y-4">
            <div className="flex items-center justify-between p-3 bg-[#0a0a0a] border border-gray-800">
              <div>
                <p className="text-gray-500 text-xs uppercase tracking-widest mb-1">Credits Account Reference</p>
                <p className="text-sm md:text-base text-gray-300 font-mono tracking-wider">
                  {showWallet ? creditsReference : '****************************************'}
                </p>
              </div>
              <button
                onClick={() => setShowWallet(!showWallet)}
                className="text-gray-500 hover:text-gray-300 transition-colors p-2"
              >
                {showWallet ? <EyeOff size={18} /> : <Eye size={18} />}
              </button>
            </div>

            <div className="flex items-center justify-between p-3 bg-[#0a0a0a] border border-gray-800">
              <div>
                <p className="text-gray-500 text-xs uppercase tracking-widest mb-1">Available Credits</p>
                <p className="text-2xl text-green-400 font-mono font-bold">
                  {showBalance ? `${creditsBalance.toFixed(2)} Credits` : '****.** Credits'}
                </p>
              </div>
              <button
                onClick={() => setShowBalance(!showBalance)}
                className="text-gray-500 hover:text-gray-300 transition-colors p-2"
              >
                {showBalance ? <EyeOff size={18} /> : <Eye size={18} />}
              </button>
            </div>

            <div className="mt-4">
              <button
                onClick={() => setShowTransactions(!showTransactions)}
                className="flex items-center text-xs text-cyan-400 hover:text-cyan-300 transition-colors uppercase tracking-widest"
              >
                <Activity size={14} className="mr-1" />
                {showTransactions ? 'HIDE CREDITS HISTORY' : 'VIEW CREDITS HISTORY'}
              </button>

              {showTransactions && (
                <div className="mt-4 space-y-2">
                  {transactions.length ? (
                    transactions.map((tx) => (
                      <div key={tx.id} className="flex justify-between items-center border border-gray-800 bg-gray-900/10 p-3 text-sm">
                        <div>
                          <span className="text-gray-500 mr-4">{tx.date}</span>
                          <span className="text-cyan-400 font-bold mr-2">{tx.type}</span>
                          <span className="text-gray-500 text-xs">
                            {tx.type === 'RECEIVED' ? `FROM: ${tx.from}` : `TO: ${tx.to}`}
                          </span>
                        </div>
                        <div className="text-right">
                          <span className={`font-mono font-bold ${tx.amount.startsWith('+') ? 'text-green-400' : 'text-red-400'}`}>
                            {tx.amount} Credits
                          </span>
                          <div className="text-gray-500 text-xs">{tx.status}</div>
                        </div>
                      </div>
                    ))
                  ) : (
                    <div className="border border-gray-800 bg-gray-900/10 p-3 text-sm text-gray-500 uppercase tracking-widest">
                      No credits activity recorded yet.
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
