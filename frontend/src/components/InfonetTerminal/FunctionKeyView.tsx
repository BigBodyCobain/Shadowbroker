'use client';

import React, { useEffect, useState } from 'react';
import { ChevronLeft, KeyRound, ShieldCheck, AlertTriangle, FileKey } from 'lucide-react';
import { fetchInfonetStatus, type InfonetStatus } from '@/mesh/infonetEconomyClient';

interface FunctionKeyViewProps {
  onBack: () => void;
}

const PIECE_STATUS: Record<string, { color: string; label: string }> = {
  not_implemented: { color: 'text-gray-500',   label: 'NOT IMPLEMENTED' },
  scaffolding:     { color: 'text-amber-400',  label: 'SCAFFOLDING' },
  reference_impl:  { color: 'text-blue-400',   label: 'REFERENCE' },
  production_rust: { color: 'text-green-400',  label: 'PRODUCTION' },
};

export default function FunctionKeyView({ onBack }: FunctionKeyViewProps) {
  const [status, setStatus] = useState<InfonetStatus | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const s = await fetchInfonetStatus();
        if (!cancelled) setStatus(s);
      } catch {
        // ignore — render the design overview without status
      }
    })();
    return () => { cancelled = true; };
  }, []);

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <div className="flex items-center justify-between border-b border-gray-800/50 pb-3 mb-4 shrink-0">
        <button onClick={onBack} className="flex items-center text-cyan-400 hover:text-cyan-300 text-sm">
          <ChevronLeft size={14} className="mr-1" /> BACK
        </button>
        <div className="text-sm text-purple-400 font-bold uppercase tracking-widest flex items-center gap-2">
          <KeyRound size={16} /> FUNCTION KEYS — Anonymous Citizenship Proof
        </div>
        <div />
      </div>

      <div className="flex-1 overflow-y-auto pr-3 space-y-4">
        <div className="text-xs text-gray-400 leading-relaxed">
          A citizen proves &quot;I am an Infonet citizen&quot; to a real-world
          operator <span className="text-purple-400">without revealing their Infonet identity</span>.
          The naive approach (scramble a public key, record each redemption on chain) leaks
          identity through metadata correlation. The Function Keys design is six pieces;
          five are implemented; one (issuance via blind signatures / anonymous credentials)
          waits on a cryptographic primitive decision.
        </div>

        {status && (
          <div className="border border-gray-800 bg-black/40 p-3">
            <div className="text-xs uppercase tracking-wider text-purple-400 mb-2 flex items-center gap-1">
              <ShieldCheck size={12} /> Privacy Primitive Status
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
              {Object.entries(status.privacy_primitive_status).map(([k, v]) => {
                const style = PIECE_STATUS[v] ?? PIECE_STATUS.not_implemented;
                return (
                  <div key={k}>
                    <div className="text-gray-500 capitalize">{k.replace(/_/g, ' ')}</div>
                    <div className={`${style.color} font-bold`}>{style.label}</div>
                  </div>
                );
              })}
            </div>
            <div className="text-xs text-gray-500 mt-2">
              Cryptographic primitives are stubbed via the locked Protocol contracts in
              <span className="font-mono"> services/infonet/privacy/contracts.py</span>.
              When the privacy-core Rust binding lands, the scaffolding swaps for the
              production class — no caller changes.
            </div>
          </div>
        )}

        <div className="border border-gray-800 bg-black/40 p-3">
          <div className="text-xs uppercase tracking-wider text-purple-400 mb-2">
            The Six Pieces
          </div>
          <ol className="text-xs space-y-2 text-gray-300">
            <li>
              <span className="text-amber-400 font-bold">1. Issuance</span>{' '}
              <span className="text-gray-500">(NOT IMPLEMENTED — blind sig / BBS+ / U-Prove / Idemix)</span>
              <div className="text-gray-400 ml-4">
                Protocol issues a credential proving citizenship without linking to node_id.
              </div>
            </li>
            <li>
              <span className="text-green-400 font-bold">2. Nullifiers</span>{' '}
              <span className="text-gray-500">(implemented — pure SHA-256)</span>
              <div className="text-gray-400 ml-4">
                <span className="font-mono">nullifier = H(secret || operator_id)</span>.
                Different operators see different nullifiers for the same key — no
                cross-operator linkage. One-time-use per (key, operator) pair via a
                tracker.
              </div>
            </li>
            <li>
              <span className="text-green-400 font-bold">3. Challenge-Response</span>{' '}
              <span className="text-gray-500">(implemented — HMAC-SHA256 placeholder)</span>
              <div className="text-gray-400 ml-4">
                Operator issues a fresh nonce; key-holder signs with the Function Key&apos;s
                secret. Defeats screenshot, replay, key-sharing. Production wires the chosen
                blind-sig scheme; API stays compatible.
              </div>
            </li>
            <li>
              <span className="text-green-400 font-bold">4. Two-Phase Commit Receipts</span>{' '}
              <span className="text-gray-500">(implemented)</span>
              <div className="text-gray-400 ml-4">
                Phase 1: operator signs a verification receipt (day-bucket date,
                nullifier prefix only — NO timestamps, NO full nullifiers, NO node_id).
                Phase 2: citizen counter-signs after service rendered. Both parties hold
                a copy. <span className="text-purple-400">Receipts NEVER published on-chain.</span>
              </div>
            </li>
            <li>
              <span className="text-green-400 font-bold">5. Enumerated Denial Codes</span>{' '}
              <span className="text-gray-500">(implemented — 3-value enum)</span>
              <div className="text-gray-400 ml-4">
                Operators can reject for exactly three reasons: invalid signature,
                nullifier already seen, rate limit exceeded. Adding a 4th code is a hard
                fork. Anti-discrimination by design.
              </div>
            </li>
            <li>
              <span className="text-green-400 font-bold">6. Batched Settlement</span>{' '}
              <span className="text-gray-500">(implemented)</span>
              <div className="text-gray-400 ml-4">
                Operators settle in aggregate. Chain sees{' '}
                <span className="font-mono">&#123;operator_id, period_id, count&#125;</span>{' '}
                — never per-receipt detail. Fraud detection via statistical auditing,
                not per-redemption traces.
              </div>
            </li>
          </ol>
        </div>

        <div className="border border-amber-900/50 bg-amber-900/10 p-3">
          <div className="flex items-center gap-2 text-amber-400 text-xs font-bold uppercase tracking-wider mb-1">
            <AlertTriangle size={12} /> Production Readiness
          </div>
          <div className="text-xs text-gray-400 space-y-1">
            <div>
              <FileKey size={11} className="inline mr-1" />
              The HMAC-SHA256 placeholder requires the verifier to know the citizen&apos;s
              secret — that is NOT private. Production replaces it with a blind-sig
              scheme that verifies without learning the secret.
            </div>
            <div>
              The cryptographic scheme decision (RSA blind sigs vs BBS+ vs U-Prove vs
              Idemix) is open per IMPLEMENTATION_PLAN §6.4.
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
