'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { KeyRound } from 'lucide-react';
import { getContacts } from '@/mesh/meshIdentity';
import { friendlyInfonetError } from '@/mesh/friendlyError';
import {
  acceptWormholeGateInvite,
  declineWormholeGateInvite,
  fetchWormholeGateInvites,
  fetchWormholeGateKeySharing,
  rekeyWormholeGate,
  sendWormholeGateInvite,
  type WormholeGateInvite,
  type WormholeGateKeySharing,
} from '@/mesh/wormholeIdentityClient';

const TRUST_LABELS: Record<string, string> = {
  sas_verified: 'SAS verified',
  invite_pinned: 'invite pinned',
  tofu_pinned: 'unverified (TOFU)',
  unpinned: 'unknown',
};

function contactLabel(peerId: string, alias?: string): string {
  return alias ? `${alias} (${peerId.slice(0, 10)})` : peerId;
}

interface GateKeySharingPanelProps {
  /** Limit to one gate; omit to show pending invites for every gate. */
  gateId?: string;
  /** Called after a key is accepted so the room can reload. */
  onKeyChanged?: () => void;
}

export default function GateKeySharingPanel({ gateId, onKeyChanged }: GateKeySharingPanelProps) {
  const [open, setOpen] = useState(false);
  const [sharing, setSharing] = useState<WormholeGateKeySharing | null>(null);
  const [invites, setInvites] = useState<WormholeGateInvite[]>([]);
  const [peerId, setPeerId] = useState('');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');

  const contacts = useMemo(() => {
    if (!open) return [];
    return Object.entries(getContacts())
      .filter(([, contact]) => !contact.blocked)
      .map(([id, contact]) => ({ id, alias: contact.alias }));
  }, [open]);

  const visibleInvites = useMemo(
    () => (gateId ? invites.filter((invite) => invite.gate_id === gateId) : invites),
    [gateId, invites],
  );

  const refresh = useCallback(async () => {
    try {
      setInvites(await fetchWormholeGateInvites());
      if (gateId) setSharing(await fetchWormholeGateKeySharing(gateId));
    } catch (error) {
      setNotice(friendlyInfonetError(error, 'Key sharing is unavailable right now.'));
    }
  }, [gateId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const run = async (action: () => Promise<string>) => {
    setBusy(true);
    setNotice('');
    try {
      setNotice(await action());
      await refresh();
    } catch (error) {
      setNotice(friendlyInfonetError(error));
    } finally {
      setBusy(false);
    }
  };

  const sendInvite = () =>
    run(async () => {
      const result = await sendWormholeGateInvite(gateId || '', peerId, note);
      setNote('');
      const trust = TRUST_LABELS[result.recipient_trust_level || ''] || result.recipient_trust_level;
      return `Key sent over encrypted DM (${trust}). They must accept it on their node.`;
    });

  const rekey = () =>
    run(async () => {
      const result = await rekeyWormholeGate(gateId || '');
      const failed = result.failed?.length ? `, ${result.failed.length} unreachable` : '';
      return `New key sent to ${result.delivered?.length || 0} member(s)${failed}.`;
    });

  const accept = (invite: WormholeGateInvite) =>
    run(async () => {
      await acceptWormholeGateInvite(invite.invite_id);
      onKeyChanged?.();
      return `Key for ${invite.gate_name} installed. Members on other nodes are now readable.`;
    });

  const decline = (invite: WormholeGateInvite) =>
    run(async () => {
      await declineWormholeGateInvite(invite.invite_id);
      return 'Invite declined.';
    });

  const pendingBadge = visibleInvites.length ? ` • ${visibleInvites.length} PENDING` : '';

  return (
    <div className="mb-3 shrink-0 border border-cyan-900/40 bg-cyan-950/10 text-[11px]">
      <button
        onClick={() => setOpen((value) => !value)}
        className="w-full flex items-center gap-2 px-3 py-2 font-mono tracking-[0.18em] text-cyan-300 hover:bg-cyan-900/20"
      >
        <KeyRound size={12} />
        {gateId ? 'GATE KEY SHARING' : 'GATE INVITES'}
        {pendingBadge}
        {gateId && sharing?.secret_id ? (
          <span className="ml-auto text-cyan-500/70 tracking-normal">
            key {sharing.secret_id.slice(0, 8)} • {sharing.shared ? 'shared' : 'only this node'}
          </span>
        ) : null}
      </button>
      {open ? (
        <div className="px-3 pb-3 space-y-3 text-cyan-100/80">
          {visibleInvites.map((invite) => (
            <div key={invite.invite_id} className="border border-amber-500/30 bg-amber-950/15 p-2">
              <div className="text-amber-200">
                {invite.op === 'rekey' ? 'New key' : 'Invite'} for <b>{invite.gate_name}</b> from{' '}
                {invite.from_peer_id}
              </div>
              <div className="mt-1 text-amber-200/70">
                Sender trust: {TRUST_LABELS[invite.from_trust_level] || invite.from_trust_level} • key{' '}
                {invite.secret_id.slice(0, 8)}
                {invite.note ? ` • “${invite.note}”` : ''}
              </div>
              {invite.from_trust_level !== 'sas_verified' ? (
                <div className="mt-1 text-amber-300/80">
                  Compare safety codes with this contact before accepting if you need to be sure who sent it.
                </div>
              ) : null}
              <div className="mt-2 flex gap-2">
                <button
                  disabled={busy}
                  onClick={() => accept(invite)}
                  className="px-3 py-1 border border-cyan-500/40 text-cyan-100 hover:bg-cyan-900/30 disabled:opacity-40"
                >
                  ACCEPT
                </button>
                <button
                  disabled={busy}
                  onClick={() => decline(invite)}
                  className="px-3 py-1 border border-gray-700 text-gray-300 hover:bg-gray-900 disabled:opacity-40"
                >
                  DECLINE
                </button>
              </div>
            </div>
          ))}
          {!visibleInvites.length && !gateId ? <div>No pending gate invites.</div> : null}
          {gateId ? (
            <>
              <div className="leading-relaxed text-cyan-200/70">
                Members on other nodes can only read this room if they hold the same key. Send it to a DM
                contact; it travels inside an end-to-end encrypted DM and is never shown on screen.
              </div>
              <div className="flex flex-wrap gap-2">
                <select
                  value={peerId}
                  onChange={(e) => setPeerId(e.target.value)}
                  className="bg-[#0a0a0a] border border-gray-800 text-white px-2 py-1 min-w-[12rem]"
                >
                  <option value="">Choose a contact…</option>
                  {contacts.map((contact) => (
                    <option key={contact.id} value={contact.id}>
                      {contactLabel(contact.id, contact.alias)}
                    </option>
                  ))}
                </select>
                <input
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  maxLength={240}
                  placeholder="Optional note"
                  className="bg-[#0a0a0a] border border-gray-800 text-white px-2 py-1 flex-1 min-w-[8rem]"
                />
                <button
                  disabled={busy || !peerId}
                  onClick={sendInvite}
                  className="px-3 py-1 border border-cyan-500/40 text-cyan-100 hover:bg-cyan-900/30 disabled:opacity-40"
                >
                  SEND KEY
                </button>
              </div>
              {sharing?.grantees?.length ? (
                <div className="flex items-center gap-2">
                  <span>Shared with {sharing.grantees.length} contact(s).</span>
                  <button
                    disabled={busy}
                    onClick={rekey}
                    className="px-3 py-1 border border-gray-700 text-gray-300 hover:bg-gray-900 disabled:opacity-40"
                  >
                    ROTATE KEY
                  </button>
                </div>
              ) : null}
            </>
          ) : null}
          {notice ? <div className="text-cyan-300">{notice}</div> : null}
        </div>
      ) : null}
    </div>
  );
}
