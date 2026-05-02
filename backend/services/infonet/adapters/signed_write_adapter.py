"""Parallel ``SignedWriteKind`` enum for Infonet economy events.

Why a parallel enum and not extending the legacy one:

The legacy ``services/mesh/mesh_signed_events.SignedWriteKind`` is
imported in many places and changing it ripples through DM, gate, and
oracle code that we are not modifying in Sprint 1. Instead we publish a
parallel enum here for the new event types and rely on the hashchain
adapter to translate or co-route as needed.

Sprint 7+ may collapse these two enums once the upgrade-hash governance
is shipped and a coordinated cutover is possible.
"""

from __future__ import annotations

from enum import Enum


class InfonetSignedWriteKind(str, Enum):
    # Reputation
    UPREP = "uprep"
    DOWNREP = "downrep"

    # Markets / resolution-as-prediction
    PREDICTION_CREATE = "prediction_create"
    PREDICTION_PLACE = "prediction_place"
    TRUTH_STAKE_PLACE = "truth_stake_place"
    TRUTH_STAKE_RESOLVE = "truth_stake_resolve"
    MARKET_SNAPSHOT = "market_snapshot"
    EVIDENCE_SUBMIT = "evidence_submit"
    RESOLUTION_STAKE = "resolution_stake"
    BOOTSTRAP_RESOLUTION_VOTE = "bootstrap_resolution_vote"
    RESOLUTION_FINALIZE = "resolution_finalize"

    # Disputes
    DISPUTE_OPEN = "dispute_open"
    DISPUTE_STAKE = "dispute_stake"
    DISPUTE_RESOLVE = "dispute_resolve"

    # Gates (extend legacy GATE_CREATE / GATE_MESSAGE)
    GATE_ENTER = "gate_enter"
    GATE_EXIT = "gate_exit"
    GATE_LOCK = "gate_lock"

    # Gate shutdown lifecycle
    GATE_SUSPEND_FILE = "gate_suspend_file"
    GATE_SUSPEND_VOTE = "gate_suspend_vote"
    GATE_SUSPEND_EXECUTE = "gate_suspend_execute"
    GATE_SHUTDOWN_FILE = "gate_shutdown_file"
    GATE_SHUTDOWN_VOTE = "gate_shutdown_vote"
    GATE_SHUTDOWN_EXECUTE = "gate_shutdown_execute"
    GATE_UNSUSPEND = "gate_unsuspend"
    GATE_SHUTDOWN_APPEAL_FILE = "gate_shutdown_appeal_file"
    GATE_SHUTDOWN_APPEAL_VOTE = "gate_shutdown_appeal_vote"
    GATE_SHUTDOWN_APPEAL_RESOLVE = "gate_shutdown_appeal_resolve"

    # Governance
    PETITION_FILE = "petition_file"
    PETITION_SIGN = "petition_sign"
    PETITION_VOTE = "petition_vote"
    CHALLENGE_FILE = "challenge_file"
    CHALLENGE_VOTE = "challenge_vote"
    PETITION_EXECUTE = "petition_execute"

    # Upgrade-hash governance
    UPGRADE_PROPOSE = "upgrade_propose"
    UPGRADE_SIGN = "upgrade_sign"
    UPGRADE_VOTE = "upgrade_vote"
    UPGRADE_CHALLENGE = "upgrade_challenge"
    UPGRADE_CHALLENGE_VOTE = "upgrade_challenge_vote"
    UPGRADE_SIGNAL_READY = "upgrade_signal_ready"
    UPGRADE_ACTIVATE = "upgrade_activate"

    # Identity
    NODE_REGISTER = "node_register"
    IDENTITY_ROTATE = "identity_rotate"
    CITIZENSHIP_CLAIM = "citizenship_claim"

    # Economy
    COIN_TRANSFER = "coin_transfer"
    COIN_MINT = "coin_mint"
    BOUNTY_CREATE = "bounty_create"
    BOUNTY_CLAIM = "bounty_claim"

    # Content
    POST_CREATE = "post_create"
    POST_REPLY = "post_reply"


INFONET_SIGNED_WRITE_KINDS: frozenset[InfonetSignedWriteKind] = frozenset(InfonetSignedWriteKind)


__all__ = [
    "INFONET_SIGNED_WRITE_KINDS",
    "InfonetSignedWriteKind",
]
