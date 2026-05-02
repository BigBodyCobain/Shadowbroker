"""Mesh Reputation Ledger — decentralized node trust scoring with gates.

Every node maintains a local reputation ledger. Votes are weighted by voter
reputation and tenure (anti-Sybil). Scores decay linearly over a 2-year window.

Gates are reputation-scoped communities. Entry requires meeting rep thresholds.
Getting downvoted below the threshold bars you automatically — no moderator needed.

Persistence: JSON files in backend/data/ (auto-saved on change, loaded on start).
"""

import base64
import math
import secrets
import time
import logging
import os
import threading
import atexit
import hmac
import hashlib
from pathlib import Path
from typing import Any, Optional

from services.mesh.mesh_metrics import increment as metrics_inc, observe_ms as metrics_observe_ms
from services.mesh.mesh_privacy_logging import privacy_log_label
from services.mesh.mesh_secure_storage import (
    read_domain_json,
    read_secure_json,
    write_domain_json,
)

logger = logging.getLogger("services.mesh_reputation")

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
LEDGER_FILE = DATA_DIR / "reputation_ledger.json"
GATES_FILE = DATA_DIR / "gates.json"
LEDGER_DOMAIN = "reputation"
GATES_DOMAIN = "gates"

# ─── Constants ────────────────────────────────────────────────────────────

VOTE_DECAY_MONTHS = 24  # Votes decay over 24 months. Recent votes weigh heaviest.
VOTE_DECAY_DAYS = VOTE_DECAY_MONTHS * 30  # ~720 days total window
MIN_REP_TO_VOTE = 3  # Minimum reputation to cast any vote (only enforced after bootstrap)
BOOTSTRAP_THRESHOLD = 1000  # Rep-to-vote rule kicks in after this many nodes join
MIN_REP_TO_CREATE_GATE = 10  # Minimum overall rep to create a gate
GATE_RATIFICATION_REP = (
    50  # Cumulative member rep needed for a gate to be ratified (after bootstrap)
)
BAN_ROTATION_P99_BUDGET_MS = 500.0
ALLOW_DYNAMIC_GATES = False
VALID_ENVELOPE_POLICIES = ("envelope_always", "envelope_recovery", "envelope_disabled")
VOTE_SALT_STATE_FILE = "voter_blind_salt.json"
_VOTE_STORAGE_SALT_CACHE: dict[str, Any] | None = None
_VOTE_STORAGE_SALT_WARNING_EMITTED = False


def _legacy_envelope_fallback_window_s() -> int:
    try:
        from services.config import get_settings

        days = int(getattr(get_settings(), "MESH_GATE_LEGACY_ENVELOPE_FALLBACK_MAX_DAYS", 30) or 30)
    except Exception:
        days = 30
    return max(1, days) * 86400


def _generate_gate_secret() -> str:
    """Generate a cryptographically random 32-byte gate secret (URL-safe base64)."""
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")


def _normalized_gate_secret_archive(raw: Any) -> dict[str, Any]:
    """Return the single-slot gate-secret archive shape used for ban/kick rotation.

    This intentionally stores only the immediately previous secret. Older
    history must come from already-durable local plaintext; the archive only
    bridges the most recent ban/kick rotation.
    """
    archive = dict(raw or {})
    return {
        "previous_secret": str(archive.get("previous_secret", "") or ""),
        "previous_valid_through_event_id": str(
            archive.get("previous_valid_through_event_id", "") or ""
        ),
        "previous_valid_through_epoch": int(archive.get("previous_valid_through_epoch", 0) or 0),
        "rotated_at": float(archive.get("rotated_at", 0.0) or 0.0),
        "reason": str(archive.get("reason", "") or ""),
    }

DEFAULT_PRIVATE_GATES: dict[str, dict] = {
    "infonet": {
        "display_name": "Main Infonet",
        "description": "Private network operations floor. Core testnet traffic, protocol notes, and live coordination stay here.",
        "welcome": "WELCOME TO MAIN INFONET. Treat this as the protocol floor, not a public lobby.",
        "sort_order": 10,
        "envelope_policy": "envelope_always",
    },
    "general-talk": {
        "display_name": "General Talk",
        "description": "Lower-friction private lounge for day-to-day chatter, intros, and community pulse checks.",
        "welcome": "WELCOME TO GENERAL TALK. Keep it human, but remember the lane is still private and reputation-backed.",
        "sort_order": 20,
        "envelope_policy": "envelope_always",
    },
    "gathered-intel": {
        "display_name": "Gathered Intel",
        "description": "Drop sourced observations, OSINT fragments, and operator notes worth preserving for later review.",
        "welcome": "WELCOME TO GATHERED INTEL. Bring sources, timestamps, and enough context for someone else to verify you.",
        "sort_order": 30,
        "envelope_policy": "envelope_always",
    },
    "tracked-planes": {
        "display_name": "Tracked Planes",
        "description": "Aviation watchers, route anomalies, military traffic, and callout chatter for flights worth tracking.",
        "welcome": "WELCOME TO TRACKED PLANES. Call out the flight, route, why it matters, and what pattern you think you see.",
        "sort_order": 40,
        "envelope_policy": "envelope_always",
    },
    "ukraine-front": {
        "display_name": "Ukraine Front",
        "description": "Focused room for Ukraine war developments, map observations, and source cross-checking.",
        "welcome": "WELCOME TO UKRAINE FRONT. Keep reporting tight, sourced, and separated from wishcasting.",
        "sort_order": 50,
        "envelope_policy": "envelope_always",
    },
    "iran-front": {
        "display_name": "Iran Front",
        "description": "Iran flashpoint monitoring, regional spillover, and escalation watch from a private-lane perspective.",
        "welcome": "WELCOME TO IRAN FRONT. Track escalation, proxies, logistics, and what changes the risk picture.",
        "sort_order": 60,
        "envelope_policy": "envelope_always",
    },
    "world-news": {
        "display_name": "World News",
        "description": "Big-picture geopolitical developments, breaking stories, and broader context outside the narrow fronts.",
        "welcome": "WELCOME TO WORLD NEWS. Use this room when the story matters but does not fit a narrower gate.",
        "sort_order": 70,
        "envelope_policy": "envelope_always",
    },
    "prediction-markets": {
        "display_name": "Prediction Markets",
        "description": "Discuss market signals, event contracts, and whether crowd pricing is tracking reality or pure narrative.",
        "welcome": "WELCOME TO PREDICTION MARKETS. Bring the market angle and the narrative angle, then compare them honestly.",
        "sort_order": 80,
        "envelope_policy": "envelope_always",
    },
    "finance": {
        "display_name": "Finance",
        "description": "Macro moves, defense names, rates, liquidity stress, and the parts of finance that steer the rest of the board.",
        "welcome": "WELCOME TO FINANCE. Macro, defense names, liquidity stress, and market structure all belong here.",
        "sort_order": 90,
        "envelope_policy": "envelope_always",
    },
    "cryptography": {
        "display_name": "Cryptography",
        "description": "Protocol design, primitives, breakage reports, and the sharper math behind the network.",
        "welcome": "WELCOME TO CRYPTOGRAPHY. If you think something can be broken, this is where you try to prove it.",
        "sort_order": 100,
        "envelope_policy": "envelope_always",
    },
    "cryptocurrencies": {
        "display_name": "Cryptocurrencies",
        "description": "Chain activity, privacy coin chatter, market structure, and crypto-adjacent threat intel.",
        "welcome": "WELCOME TO CRYPTOCURRENCIES. Chain behavior, privacy tooling, and market weirdness all go on the table.",
        "sort_order": 110,
        "envelope_policy": "envelope_always",
    },
    "meet-chat": {
        "display_name": "Meet Chat",
        "description": "Casual private hangout for getting to know the other operators behind the personas.",
        "welcome": "WELCOME TO MEET CHAT. Lighten up a little and let the community feel like it has actual people in it.",
        "sort_order": 120,
        "envelope_policy": "envelope_always",
    },
    "opsec-lab": {
        "display_name": "OPSEC Lab",
        "description": "Stress-test assumptions, try to break rep or persona boundaries, and document privacy failures without mercy.",
        "welcome": "WELCOME TO OPSEC LAB. Be ruthless, document the leak, and assume everyone is smarter than the last audit.",
        "sort_order": 130,
        "envelope_policy": "envelope_always",
    },
}


def _blind_voter(voter_id: str, salt: bytes) -> str:
    if not voter_id:
        return ""
    digest = hmac.new(salt, voter_id.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{digest[:8]}…"


def _vote_storage_window_seconds(grace_seconds: int) -> int:
    return max(VOTE_DECAY_DAYS * 86400, 86400) + max(0, grace_seconds)


def _derive_legacy_secret_vote_salt(secret: str) -> bytes:
    return hmac.new(
        secret.encode("utf-8"),
        b"shadowbroker|reputation|voter-blind|v1",
        hashlib.sha256,
    ).digest()


def _derive_rotated_secret_vote_salt(secret: str, epoch_index: int) -> bytes:
    material = f"shadowbroker|reputation|voter-blind|v2|{epoch_index}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), material, hashlib.sha256).digest()


def _load_vote_storage_state() -> dict[str, Any]:
    try:
        raw = read_domain_json(
            LEDGER_DOMAIN,
            VOTE_SALT_STATE_FILE,
            lambda: {"version": 2, "local_history": []},
        )
    except Exception as exc:
        logger.error("Failed to load voter salt rotation state: %s", exc)
        raw = {"version": 2, "local_history": []}

    history: list[dict[str, Any]] = []
    for entry in raw.get("local_history", []) if isinstance(raw, dict) else []:
        salt_hex = str(entry.get("salt", "") or "").strip().lower()
        if len(salt_hex) != 64:
            continue
        try:
            activated_at = float(entry.get("activated_at", 0) or 0)
        except (TypeError, ValueError):
            continue
        if activated_at <= 0:
            continue
        history.append({"salt": salt_hex, "activated_at": activated_at})

    state: dict[str, Any] = {
        "version": 2,
        "local_history": history,
        "legacy_secret_until": 0.0,
    }
    try:
        state["legacy_secret_until"] = float(raw.get("legacy_secret_until", 0) or 0)
    except (TypeError, ValueError):
        state["legacy_secret_until"] = 0.0
    return state


def _write_vote_storage_state(state: dict[str, Any]) -> None:
    payload = {
        "version": 2,
        "legacy_secret_until": float(state.get("legacy_secret_until", 0) or 0),
        "local_history": [
            {
                "salt": str(entry.get("salt", "") or "").strip().lower(),
                "activated_at": float(entry.get("activated_at", 0) or 0),
            }
            for entry in state.get("local_history", [])
        ],
    }
    write_domain_json(LEDGER_DOMAIN, VOTE_SALT_STATE_FILE, payload)


def _vote_storage_cache_ttl(now: float, *, next_refresh: float | None = None) -> float:
    default_refresh = now + 3600.0
    if next_refresh is None or next_refresh <= now:
        return default_refresh
    return min(default_refresh, next_refresh)


def _vote_storage_candidates(now: float | None = None) -> dict[str, Any]:
    global _VOTE_STORAGE_SALT_CACHE, _VOTE_STORAGE_SALT_WARNING_EMITTED
    current_time = float(now if now is not None else time.time())
    if (
        _VOTE_STORAGE_SALT_CACHE is not None
        and current_time < float(_VOTE_STORAGE_SALT_CACHE.get("refresh_at", 0) or 0)
    ):
        return _VOTE_STORAGE_SALT_CACHE

    try:
        from services.config import get_settings

        settings = get_settings()
        secret = str(settings.MESH_PEER_PUSH_SECRET or "").strip()
        rotate_days = max(0, int(getattr(settings, "MESH_VOTER_BLIND_SALT_ROTATE_DAYS", 30) or 0))
        grace_days = max(0, int(getattr(settings, "MESH_VOTER_BLIND_SALT_GRACE_DAYS", 30) or 0))
    except Exception:
        secret = ""
        rotate_days = 30
        grace_days = 30

    rotate_seconds = rotate_days * 86400
    grace_seconds = grace_days * 86400
    history_window_seconds = _vote_storage_window_seconds(grace_seconds)
    state = _load_vote_storage_state()
    changed = False

    if not secret and not _VOTE_STORAGE_SALT_WARNING_EMITTED:
        logger.warning("MESH_PEER_PUSH_SECRET missing; falling back to local voter blinding salt")
        _VOTE_STORAGE_SALT_WARNING_EMITTED = True

    salt_path = DATA_DIR / "voter_blind_salt.bin"
    local_history = list(state.get("local_history", []))
    history_cutoff = current_time - history_window_seconds
    pruned_history = [entry for entry in local_history if float(entry.get("activated_at", 0)) >= history_cutoff]
    if pruned_history != local_history:
        local_history = pruned_history
        state["local_history"] = local_history
        changed = True

    migrated_legacy_bin = False
    if not secret:
        try:
            if not local_history and salt_path.exists() and salt_path.stat().st_size == 32:
                seed_time = current_time - rotate_seconds if rotate_seconds > 0 else current_time
                local_history = [{"salt": salt_path.read_bytes().hex(), "activated_at": seed_time}]
                state["local_history"] = local_history
                changed = True
                migrated_legacy_bin = True
                logger.info("Migrated legacy voter blinding salt into rotating history")
            if not local_history:
                local_history = [{"salt": os.urandom(32).hex(), "activated_at": current_time}]
                state["local_history"] = local_history
                changed = True
                logger.info("Generated initial rotating voter blinding salt")
            if rotate_seconds > 0:
                last_activated_at = float(local_history[-1].get("activated_at", 0) or 0)
                if current_time - last_activated_at >= rotate_seconds:
                    local_history.append({"salt": os.urandom(32).hex(), "activated_at": current_time})
                    state["local_history"] = local_history
                    changed = True
                    logger.info("Rotated voter blinding salt")
        except Exception as exc:
            logger.error("Failed to prepare rotating voter salt history, falling back to random: %s", exc)
            fallback = os.urandom(32)
            _VOTE_STORAGE_SALT_CACHE = {
                "active": fallback,
                "salts": [fallback],
                "refresh_at": current_time + 300.0,
            }
            return _VOTE_STORAGE_SALT_CACHE

    legacy_secret_until = float(state.get("legacy_secret_until", 0) or 0)
    if secret and legacy_secret_until <= 0:
        state["legacy_secret_until"] = current_time + history_window_seconds
        legacy_secret_until = float(state["legacy_secret_until"])
        changed = True

    if changed:
        try:
            _write_vote_storage_state(state)
            if migrated_legacy_bin:
                salt_path.unlink(missing_ok=True)
        except Exception as exc:
            logger.error("Failed to persist voter salt rotation state: %s", exc)

    salts: list[bytes] = []
    refresh_at: float | None = None

    if secret:
        if rotate_seconds > 0:
            current_epoch = int(current_time // rotate_seconds)
            epoch_window = max(1, int(math.ceil(history_window_seconds / rotate_seconds)))
            start_epoch = max(0, current_epoch - epoch_window)
            for epoch_index in range(current_epoch, start_epoch - 1, -1):
                salts.append(_derive_rotated_secret_vote_salt(secret, epoch_index))
            refresh_at = (current_epoch + 1) * rotate_seconds
        else:
            salts.append(_derive_rotated_secret_vote_salt(secret, 0))
        if legacy_secret_until > current_time:
            salts.append(_derive_legacy_secret_vote_salt(secret))
            refresh_at = legacy_secret_until if refresh_at is None else min(refresh_at, legacy_secret_until)

    for entry in reversed(local_history):
        salt_hex = str(entry.get("salt", "") or "").strip().lower()
        if len(salt_hex) != 64:
            continue
        try:
            salts.append(bytes.fromhex(salt_hex))
        except ValueError:
            continue

    unique_salts: list[bytes] = []
    seen_salts: set[bytes] = set()
    for salt in salts:
        if not salt or salt in seen_salts:
            continue
        seen_salts.add(salt)
        unique_salts.append(salt)

    if not unique_salts:
        unique_salts.append(os.urandom(32))

    _VOTE_STORAGE_SALT_CACHE = {
        "active": unique_salts[0],
        "salts": unique_salts,
        "refresh_at": _vote_storage_cache_ttl(current_time, next_refresh=refresh_at),
    }
    return _VOTE_STORAGE_SALT_CACHE


def _vote_storage_salt() -> bytes:
    return _vote_storage_candidates()["active"]


def _vote_storage_salts() -> list[bytes]:
    return list(_vote_storage_candidates()["salts"])


def _blinded_voter_candidates(voter_id: str) -> list[str]:
    if not voter_id:
        return []
    blinded_ids: list[str] = []
    for salt in _vote_storage_salts():
        blinded = _blind_voter(voter_id, salt)
        if blinded and blinded not in blinded_ids:
            blinded_ids.append(blinded)
    return blinded_ids


def _stored_voter_matches(vote: dict, voter_id: str) -> bool:
    blinded = _stored_voter_id(vote)
    if not blinded:
        return False
    return blinded in _blinded_voter_candidates(voter_id)


def _reset_vote_storage_salt_cache() -> None:
    global _VOTE_STORAGE_SALT_CACHE, _VOTE_STORAGE_SALT_WARNING_EMITTED
    _VOTE_STORAGE_SALT_CACHE = None
    _VOTE_STORAGE_SALT_WARNING_EMITTED = False


def _stored_voter_id(vote: dict) -> str:
    blinded = str(vote.get("blinded_voter_id", "") or "").strip()
    if blinded:
        return blinded
    raw = str(vote.get("voter_id", "") or "").strip()
    if not raw:
        return ""
    return _blind_voter(raw, _vote_storage_salt())


def _serialize_vote_record(vote: dict) -> dict:
    blinded = _stored_voter_id(vote)
    payload = dict(vote or {})
    payload.pop("voter_id", None)
    if blinded:
        payload["blinded_voter_id"] = blinded
    return payload


# ─── Vote Record ──────────────────────────────────────────────────────────


class ReputationLedger:
    """Local reputation ledger — each node maintains its own view.

    Storage format:
      nodes: {node_id: {first_seen, public_key, agent}}
      votes: [{voter_id, target_id, vote (+1/-1), gate (optional), timestamp}]
      scores_cache: {node_id: {overall: int, gates: {gate_id: int}}}
    """

    def __init__(self):
        self.nodes: dict[str, dict] = {}  # {node_id: {first_seen, public_key, agent}}
        self.votes: list[dict] = []  # [{voter_id, target_id, vote, gate, timestamp}]
        self.vouches: list[dict] = []  # [{voucher_id, target_id, note, timestamp}]
        self.aliases: dict[str, str] = {}  # {new_node_id: old_node_id}
        self._scores_dirty = True
        self._scores_cache: dict[str, dict] = {}
        self._dirty = False
        self._save_lock = threading.Lock()
        self._save_timer: threading.Timer | None = None
        self._SAVE_INTERVAL = 5.0
        atexit.register(self._flush)
        self._load()

    # ─── Persistence ──────────────────────────────────────────────────

    def _load(self):
        """Load ledger from disk."""
        domain_path = DATA_DIR / LEDGER_DOMAIN / LEDGER_FILE.name
        if not domain_path.exists() and LEDGER_FILE.exists():
            try:
                legacy = read_secure_json(
                    LEDGER_FILE,
                    lambda: {"nodes": {}, "votes": [], "vouches": [], "aliases": {}},
                )
                write_domain_json(LEDGER_DOMAIN, LEDGER_FILE.name, legacy)
                LEDGER_FILE.unlink(missing_ok=True)
            except Exception as e:
                logger.error(f"Failed to migrate reputation ledger: {e}")
        try:
            data = read_domain_json(
                LEDGER_DOMAIN,
                LEDGER_FILE.name,
                lambda: {"nodes": {}, "votes": [], "vouches": [], "aliases": {}},
            )
            self.nodes = data.get("nodes", {})
            raw_votes = data.get("votes", [])
            # Purge legacy __system__ cost votes — they stored raw voter
            # identities as target_id, which is a privacy leak.
            before = len(raw_votes)
            self.votes = [v for v in raw_votes if not v.get("system_cost")]
            purged = before - len(self.votes)
            if purged:
                self._dirty = True  # re-save without the leaked records
                logger.info(f"Purged {purged} legacy system_cost vote(s) with raw identity leak")
            self.vouches = data.get("vouches", [])
            self.aliases = data.get("aliases", {})
            self._scores_dirty = True
            logger.info(
                f"Loaded reputation ledger: {len(self.nodes)} nodes, {len(self.votes)} votes"
            )
        except Exception as e:
            logger.error(f"Failed to load reputation ledger: {e}")

    def _save(self):
        """Mark dirty and schedule a coalesced disk write."""
        self._dirty = True
        with self._save_lock:
            if self._save_timer is None or not self._save_timer.is_alive():
                self._save_timer = threading.Timer(self._SAVE_INTERVAL, self._flush)
                self._save_timer.daemon = True
                self._save_timer.start()

    def _flush(self):
        """Actually write to disk (called by timer or atexit)."""
        if not self._dirty:
            return
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            data = {
                "nodes": self.nodes,
                "votes": [_serialize_vote_record(vote) for vote in self.votes],
                "vouches": self.vouches,
                "aliases": self.aliases,
            }
            write_domain_json(LEDGER_DOMAIN, LEDGER_FILE.name, data)
            LEDGER_FILE.unlink(missing_ok=True)
            self._dirty = False
        except Exception as e:
            logger.error(f"Failed to save reputation ledger: {e}")

    # ─── Node Registration ────────────────────────────────────────────

    def register_node(
        self, node_id: str, public_key: str = "", public_key_algo: str = "", agent: bool = False
    ):
        """Register a node if not already known. Updates public_key if provided."""
        if node_id not in self.nodes:
            self.nodes[node_id] = {
                "first_seen": time.time(),
                "public_key": public_key,
                "public_key_algo": public_key_algo,
                "agent": agent,
            }
            self._save()
            logger.info(
                "Registered new node: %s",
                privacy_log_label(node_id, label="node"),
            )
        elif public_key and not self.nodes[node_id].get("public_key"):
            self.nodes[node_id]["public_key"] = public_key
            if public_key_algo:
                self.nodes[node_id]["public_key_algo"] = public_key_algo
            self._save()

    def link_identities(self, old_id: str, new_id: str) -> tuple[bool, str]:
        """Link a new node_id to an old one for reputation continuity."""
        if not old_id or not new_id:
            return False, "Missing old_id or new_id"
        if old_id == new_id:
            return False, "Old and new IDs must differ"
        if new_id in self.aliases:
            return False, f"{new_id} is already linked"
        if old_id in self.aliases:
            return False, f"{old_id} is already linked to {self.aliases[old_id]}"
        if old_id in self.aliases.values():
            return False, f"{old_id} is already the source of a link"

        self.aliases[new_id] = old_id
        self._scores_dirty = True
        self._save()
        logger.info(
            "Linked identity: %s -> %s",
            privacy_log_label(old_id, label="node"),
            privacy_log_label(new_id, label="node"),
        )
        return True, "linked"

    def get_node_age_days(self, node_id: str) -> float:
        """Get node age in days."""
        node = self.nodes.get(node_id)
        if not node:
            return 0
        return (time.time() - node.get("first_seen", time.time())) / 86400

    def is_agent(self, node_id: str) -> bool:
        """Check if node is registered as an Agent (bot/AI)."""
        return self.nodes.get(node_id, {}).get("agent", False)

    # ─── Voting ───────────────────────────────────────────────────────

    def _compute_vote_weight(self, voter_id: str) -> float:
        """Rep-weighted voting — your vote's power scales with reputation and tenure.

        Two factors combine:
          rep_factor:    log10(1 + |rep|) / log10(101)  →  0 rep ≈ 0.0, 100 rep = 1.0
          tenure_factor: age_days / 720                  →  new = 0.0, 2yr+ = 1.0

        Combined weight = max(0.1, rep_factor × tenure_factor), capped at 1.0.
        Floor of 0.1 ensures every user's vote still counts for something.

        | Rep  | Day 1 | 6 months | 1 year | 2 years |
        |------|-------|----------|--------|---------|
        | 0    | 0.10  | 0.10     | 0.10   | 0.10    |
        | 5    | 0.10  | 0.10     | 0.20   | 0.39    |
        | 25   | 0.10  | 0.18     | 0.35   | 0.70    |
        | 50   | 0.10  | 0.21     | 0.42   | 0.85    |
        | 100+ | 0.10  | 0.25     | 0.50   | 1.00    |
        """
        # ── Rep factor: logarithmic scale, 100 rep = full power ──
        rep = self.get_reputation(voter_id).get("overall", 0)
        rep_factor = math.log10(1 + abs(rep)) / math.log10(101)  # 0→0.0, 100→1.0

        # ── Tenure factor: linear over the 2-year decay window ──
        age_days = self.get_node_age_days(voter_id)
        decay_window = float(VOTE_DECAY_DAYS) if VOTE_DECAY_DAYS > 0 else 720.0
        tenure_factor = min(1.0, age_days / decay_window)

        weight = rep_factor * tenure_factor
        return max(0.1, min(1.0, weight))

    def cast_vote(
        self, voter_id: str, target_id: str, vote: int, gate: str = ""
    ) -> tuple[bool, str, float]:
        """Cast a vote. Returns (success, reason, weight).

        Rules:
          - Self-votes allowed (costs -1 rep like any vote — net negative for voter)
          - Must have rep >= MIN_REP_TO_VOTE (except first few bootstrap votes)
          - One vote per voter per target per gate (can change direction)
          - Vote value is weighted by voter's reputation and tenure
        """
        if vote not in (1, -1):
            return False, "Vote must be +1 or -1", 0.0

        # Reputation burn: minimum rep to vote — only enforced after network bootstraps
        network_size = len(self.nodes)
        if network_size >= BOOTSTRAP_THRESHOLD:
            voter_rep = self.get_reputation(voter_id).get("overall", 0)
            if voter_rep < MIN_REP_TO_VOTE:
                return (
                    False,
                    f"Need {MIN_REP_TO_VOTE} reputation to vote (you have {voter_rep}). Network has {network_size} nodes — rep-to-vote is active.",
                    0.0,
                )

        blinded_voter_id = _blind_voter(voter_id, _vote_storage_salt())
        existing_vote = next(
            (
                v
                for v in self.votes
                if _stored_voter_matches(v, voter_id)
                and v["target_id"] == target_id
                and v.get("gate", "") == gate
            ),
            None,
        )
        existing_vote_value = None
        if existing_vote is not None:
            try:
                existing_vote_value = int(existing_vote.get("vote", 0))
            except (TypeError, ValueError):
                existing_vote_value = None
        if existing_vote and existing_vote_value == vote:
            direction = "up" if vote == 1 else "down"
            gate_str = f" in gate '{gate}'" if gate else ""
            return False, f"Vote already set to {direction} on {target_id}{gate_str}", 0.0

        # Remove existing vote from this voter for this target in this gate
        self.votes = [
            v
            for v in self.votes
            if not (
                _stored_voter_matches(v, voter_id)
                and v["target_id"] == target_id
                and v.get("gate", "") == gate
            )
        ]

        # Record the new vote
        now = time.time()
        weight = self._compute_vote_weight(voter_id)
        is_direction_change = existing_vote is not None
        self.votes.append(
            {
                "voter_id": voter_id,
                "blinded_voter_id": blinded_voter_id,
                "target_id": target_id,
                "vote": vote,
                "gate": gate,
                "timestamp": now,
                "weight": weight,
                "agent_verify": self.is_agent(voter_id),
            }
        )

        # Vote cost: costs the same as the vote's weight (if your vote only
        # moves the score by 0.1, you only pay 0.1 — not a flat 1.0).
        # Only on first vote, not direction changes.  The target_id is the
        # *blinded* voter ID so the root identity never touches disk.
        if not is_direction_change:
            self.votes.append(
                {
                    "voter_id": "__system__",
                    "target_id": blinded_voter_id,
                    "vote": -1,
                    "gate": "",
                    "timestamp": now,
                    "weight": weight,
                    "agent_verify": False,
                    "vote_cost": True,
                }
            )

        self._scores_dirty = True
        self._save()

        direction = "up" if vote == 1 else "down"
        gate_str = f" in gate '{gate}'" if gate else ""
        logger.info(
            "Vote: %s voted %s on %s%s",
            privacy_log_label(voter_id, label="node"),
            direction,
            privacy_log_label(target_id, label="node"),
            f" in {privacy_log_label(gate, label='gate')}" if gate else "",
        )
        return True, f"Voted {direction} on {target_id}{gate_str}", weight

    # ─── Trust Vouches ────────────────────────────────────────────────

    def add_vouch(
        self, voucher_id: str, target_id: str, note: str = "", timestamp: float | None = None
    ) -> tuple[bool, str]:
        if not voucher_id or not target_id:
            return False, "Missing voucher_id or target_id"
        if voucher_id == target_id:
            return False, "Cannot vouch for yourself"
        ts = timestamp if timestamp is not None else time.time()
        # Deduplicate vouches from same voucher to same target within 30 days
        cutoff = ts - (30 * 86400)
        for v in self.vouches:
            if (
                v.get("voucher_id") == voucher_id
                and v.get("target_id") == target_id
                and float(v.get("timestamp", 0)) >= cutoff
            ):
                return False, "Duplicate vouch"
        self.vouches.append(
            {
                "voucher_id": voucher_id,
                "target_id": target_id,
                "note": str(note)[:140],
                "timestamp": float(ts),
            }
        )
        self._save()
        return True, "vouched"

    def get_vouches(self, target_id: str, limit: int = 50) -> list[dict]:
        if not target_id:
            return []
        entries = [v for v in self.vouches if v.get("target_id") == target_id]
        entries = sorted(entries, key=lambda v: v.get("timestamp", 0), reverse=True)
        return entries[: max(1, limit)]

    # ─── Score Computation ────────────────────────────────────────────

    def _recompute_scores(self):
        """Recompute all scores with time-weighted decay.

        Votes decay linearly over VOTE_DECAY_MONTHS (24 months).
        A vote cast today has full weight (1.0).  A vote cast 12 months ago
        has ~0.5 weight.  A vote older than 24 months has 0 weight and is
        skipped entirely.  This means recent activity always matters more
        than ancient history, but nothing ever fully disappears until 2 years
        have passed.
        """
        if not self._scores_dirty:
            return

        now = time.time()
        decay_seconds = VOTE_DECAY_DAYS * 86400 if VOTE_DECAY_DAYS > 0 else 0
        scores: dict[str, dict] = {}

        for v in self.votes:
            age = now - v["timestamp"]

            # If decay is enabled, skip votes older than the window
            if decay_seconds and age >= decay_seconds:
                continue

            # Time-decay multiplier: 1.0 for brand new, 0.0 at the boundary.
            # Recent months weigh heaviest.
            if decay_seconds:
                decay_factor = 1.0 - (age / decay_seconds)
            else:
                decay_factor = 1.0

            target = v["target_id"]
            if target not in scores:
                scores[target] = {"overall": 0.0, "gates": {}, "upvotes": 0, "downvotes": 0}

            weighted = v["vote"] * v.get("weight", 1.0) * decay_factor
            scores[target]["overall"] += weighted

            if v["vote"] > 0:
                scores[target]["upvotes"] += 1
            else:
                scores[target]["downvotes"] += 1

            gate = v.get("gate", "")
            if gate:
                scores[target]["gates"].setdefault(gate, 0.0)
                scores[target]["gates"][gate] += weighted

        # Round to 1 decimal place — weighted votes produce fractional scores
        for nid in scores:
            scores[nid]["overall"] = round(scores[nid]["overall"], 1)
            for gid in scores[nid]["gates"]:
                scores[nid]["gates"][gid] = round(scores[nid]["gates"][gid], 1)

        self._scores_cache = scores
        self._scores_dirty = False

    def get_reputation(self, node_id: str) -> dict:
        """Get reputation for a single node.

        Returns {overall: int, gates: {gate_id: int}, upvotes: int, downvotes: int}

        Scores are merged from three possible sources:
          1. Direct scores on ``node_id`` (votes targeting posts by this identity).
          2. Alias scores (if ``node_id`` is linked to an older identity).
          3. Blinded-wallet scores — vote costs are stored under the deterministic
             HMAC-blinded form of the voter's root identity so the raw private key
             never touches disk.  When the caller supplies the raw node_id we can
             recompute the blind and merge those costs in.
        """
        self._recompute_scores()
        _zero = lambda: {"overall": 0, "gates": {}, "upvotes": 0, "downvotes": 0}
        base = self._scores_cache.get(node_id, _zero())

        # Merge alias (old identity linked to this one)
        alias = self.aliases.get(node_id)
        if alias:
            old = self._scores_cache.get(alias, _zero())
            base = self._merge_scores(base, old)

        # Merge blinded-wallet costs (vote-cost records target the blinded ID)
        for blinded in _blinded_voter_candidates(node_id):
            if not blinded or blinded == node_id:
                continue
            wallet = self._scores_cache.get(blinded, _zero())
            if wallet["overall"] != 0 or wallet["upvotes"] != 0 or wallet["downvotes"] != 0:
                base = self._merge_scores(base, wallet)

        return base

    @staticmethod
    def _merge_scores(a: dict, b: dict) -> dict:
        merged = {
            "overall": a["overall"] + b["overall"],
            "gates": {},
            "upvotes": a["upvotes"] + b["upvotes"],
            "downvotes": a["downvotes"] + b["downvotes"],
        }
        gates = set(a.get("gates", {}).keys()) | set(b.get("gates", {}).keys())
        for g in gates:
            merged["gates"][g] = a.get("gates", {}).get(g, 0) + b.get("gates", {}).get(g, 0)
        return merged

    def get_all_reputations(self) -> dict[str, int]:
        """Get overall reputation for all known nodes."""
        self._recompute_scores()
        return {nid: s["overall"] for nid, s in self._scores_cache.items()}

    def get_reputation_log(self, node_id: str, *, detailed: bool = False) -> dict:
        """Return reputation data for a node.

        Public callers receive a summary-only view. Rich breakdowns remain
        available to authenticated audit tooling.
        """
        cutoff = time.time() - (VOTE_DECAY_DAYS * 86400)
        rep = self.get_reputation(node_id)
        result = {
            "node_id": node_id,
            "overall": rep.get("overall", 0),
            "upvotes": rep.get("upvotes", 0),
            "downvotes": rep.get("downvotes", 0),
        }
        if not detailed:
            return result

        alias = self.aliases.get(node_id)
        target_ids = {node_id}
        if alias:
            target_ids.add(alias)
        query_salt = os.urandom(8)
        recent = [
            {
                "voter": _blind_voter(_stored_voter_id(v), query_salt),
                "vote": v["vote"],
                "gate": "",
                "weight": v.get("weight", 1.0),
                "agent_verify": v.get("agent_verify", False),
                "age": f"{int((time.time() - v['timestamp']) / 86400)}d ago",
            }
            for v in sorted(self.votes, key=lambda x: x["timestamp"], reverse=True)
            if v["target_id"] in target_ids and v["timestamp"] >= cutoff
        ][:20]

        result.update(
            {
                "gates": {},
                "recent_votes": recent,
                "node_age_days": round(self.get_node_age_days(node_id), 1),
                "is_agent": self.is_agent(node_id),
            }
        )
        return result

    # ─── DM Threshold ────────────────────────────────────────────────

    def should_accept_message(self, sender_id: str, recipient_threshold: int) -> bool:
        """Check if sender meets recipient's reputation threshold for DMs."""
        if recipient_threshold <= 0:
            return True
        sender_rep = self.get_reputation(sender_id).get("overall", 0)
        return sender_rep >= recipient_threshold

    # ─── Cleanup ──────────────────────────────────────────────────────

    def cleanup_expired(self):
        """Remove votes older than the 2-year decay window."""
        if VOTE_DECAY_DAYS <= 0:
            return
        cutoff = time.time() - (VOTE_DECAY_DAYS * 86400)
        before = len(self.votes)
        self.votes = [v for v in self.votes if v["timestamp"] >= cutoff]
        after = len(self.votes)
        if before != after:
            self._scores_dirty = True
            self._save()
            logger.info(f"Cleaned up {before - after} expired votes")


# ─── Gate System ──────────────────────────────────────────────────────────


class GateManager:
    """Self-governing reputation-gated communities.

    Anyone with rep >= 10 can create a gate. Entry requires meeting rep thresholds.
    Getting downvoted below threshold bars you automatically.
    """

    def __init__(self, ledger: ReputationLedger):
        self.ledger = ledger
        self.gates: dict[str, dict] = {}
        self._gate_lock = threading.RLock()
        self._dirty = False
        self._save_lock = threading.Lock()
        self._save_timer: threading.Timer | None = None
        self._SAVE_INTERVAL = 5.0
        atexit.register(self._flush)
        self._load()

    def _load(self):
        domain_path = DATA_DIR / GATES_DOMAIN / GATES_FILE.name
        if not domain_path.exists() and GATES_FILE.exists():
            try:
                legacy = read_secure_json(GATES_FILE, lambda: {})
                write_domain_json(GATES_DOMAIN, GATES_FILE.name, legacy)
                GATES_FILE.unlink(missing_ok=True)
            except Exception as e:
                logger.error(f"Failed to migrate gates: {e}")
        try:
            self.gates = read_domain_json(GATES_DOMAIN, GATES_FILE.name, lambda: {})
            logger.info(f"Loaded {len(self.gates)} gates")
        except Exception as e:
            logger.error(f"Failed to load gates: {e}")
        if self._apply_gate_catalog():
            self._save()

    def _apply_gate_catalog(self) -> bool:
        """Seed fixed private launch gates and retire obsolete defaults."""
        changed = False
        legacy_public_square = self.gates.get("public-square")
        if isinstance(legacy_public_square, dict) and not legacy_public_square.get("fixed"):
            self.gates.pop("public-square", None)
            changed = True

        for gate_id, seed in DEFAULT_PRIVATE_GATES.items():
            gate = self.gates.get(gate_id)
            if not isinstance(gate, dict):
                self.gates[gate_id] = {
                    "creator_node_id": "!sb_seed",
                    "display_name": seed["display_name"],
                    "description": seed["description"],
                    "welcome": seed["welcome"],
                    "rules": {
                        "min_overall_rep": 0,
                        "min_gate_rep": {},
                    },
                    "created_at": time.time(),
                    "message_count": 0,
                    "fixed": True,
                    "sort_order": seed["sort_order"],
                    "gate_secret": "",
                    "gate_secret_archive": _normalized_gate_secret_archive({}),
                    "envelope_policy": str(seed.get("envelope_policy", "envelope_disabled") or "envelope_disabled"),
                }
                changed = True
                continue

            for key in ("display_name", "description", "welcome", "sort_order", "envelope_policy"):
                if gate.get(key) != seed[key]:
                    gate[key] = seed[key]
                    changed = True
            if gate.get("fixed") is not True:
                gate["fixed"] = True
                changed = True
            if "rules" not in gate or not isinstance(gate["rules"], dict):
                gate["rules"] = {"min_overall_rep": 0, "min_gate_rep": {}}
                changed = True
            gate["rules"].setdefault("min_overall_rep", 0)
            gate["rules"].setdefault("min_gate_rep", {})
            gate.setdefault("message_count", 0)
            gate.setdefault("created_at", time.time())
            archive = _normalized_gate_secret_archive(gate.get("gate_secret_archive"))
            if gate.get("gate_secret_archive") != archive:
                gate["gate_secret_archive"] = archive
                changed = True

        for gate in self.gates.values():
            if not isinstance(gate, dict):
                continue
            gate.setdefault("message_count", 0)
            gate.setdefault("created_at", time.time())
            policy = str(gate.get("envelope_policy", "") or "")
            if policy not in VALID_ENVELOPE_POLICIES:
                # Sprint 1 / Rec #1: default closed — no durable envelope unless
                # the operator explicitly opts in via set_envelope_policy().
                gate["envelope_policy"] = "envelope_disabled"
                changed = True
            if "legacy_envelope_fallback" not in gate or gate.get("legacy_envelope_fallback") is None:
                gate["legacy_envelope_fallback"] = False
                changed = True
            if bool(gate.get("legacy_envelope_fallback")):
                if not int(gate.get("legacy_envelope_fallback_expires_at", 0) or 0):
                    enabled_at = int(time.time())
                    gate["legacy_envelope_fallback_acknowledged"] = True
                    gate["legacy_envelope_fallback_enabled_at"] = enabled_at
                    gate["legacy_envelope_fallback_expires_at"] = (
                        enabled_at + _legacy_envelope_fallback_window_s()
                    )
                    changed = True
            else:
                if gate.get("legacy_envelope_fallback_acknowledged") or gate.get(
                    "legacy_envelope_fallback_enabled_at"
                ) or gate.get("legacy_envelope_fallback_expires_at"):
                    gate["legacy_envelope_fallback_acknowledged"] = False
                    gate["legacy_envelope_fallback_enabled_at"] = 0
                    gate["legacy_envelope_fallback_expires_at"] = 0
                    changed = True
            if "envelope_always_acknowledged" not in gate:
                gate["envelope_always_acknowledged"] = bool(
                    str(gate.get("envelope_policy", "") or "") == "envelope_always"
                )
                changed = True
            archive = _normalized_gate_secret_archive(gate.get("gate_secret_archive"))
            if gate.get("gate_secret_archive") != archive:
                gate["gate_secret_archive"] = archive
                changed = True

        for gate_id, gate in list(self.gates.items()):
            if isinstance(gate, dict) and not str(gate.get("gate_secret", "") or "").strip():
                self.ensure_gate_secret(gate_id)
                changed = True

        return changed

    def _save(self):
        """Mark dirty and schedule a coalesced disk write."""
        self._dirty = True
        with self._save_lock:
            if self._save_timer is None or not self._save_timer.is_alive():
                self._save_timer = threading.Timer(self._SAVE_INTERVAL, self._flush)
                self._save_timer.daemon = True
                self._save_timer.start()

    def _flush(self):
        """Actually write to disk (called by timer or atexit)."""
        if not self._dirty:
            return
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            write_domain_json(GATES_DOMAIN, GATES_FILE.name, self.gates)
            GATES_FILE.unlink(missing_ok=True)
            self._dirty = False
        except Exception as e:
            logger.error(f"Failed to save gates: {e}")

    def create_gate(
        self,
        creator_id: str,
        gate_id: str,
        display_name: str,
        min_overall_rep: int = 0,
        min_gate_rep: Optional[dict] = None,
        description: str = "",
    ) -> tuple[bool, str]:
        """Create a new gate. Rep gate disabled until network reaches critical mass."""

        if not ALLOW_DYNAMIC_GATES:
            return False, "Gate creation is disabled for the fixed private launch catalog"

        gate_id = gate_id.lower().strip()
        if not gate_id or not gate_id.isalnum() and "-" not in gate_id:
            return False, "Gate ID must be alphanumeric (hyphens allowed)"
        if len(gate_id) > 32:
            return False, "Gate ID too long (max 32 chars)"
        if gate_id in self.gates:
            return False, f"Gate '{gate_id}' already exists"

        self.gates[gate_id] = {
            "creator_node_id": creator_id,
            "display_name": display_name[:64],
            "description": description[:240],
            "rules": {
                "min_overall_rep": min_overall_rep,
                "min_gate_rep": min_gate_rep or {},
            },
            "created_at": time.time(),
            "message_count": 0,
            "fixed": False,
            "sort_order": 1000,
            "gate_secret": "",
            "gate_secret_archive": _normalized_gate_secret_archive({}),
            "envelope_policy": "envelope_always",
            "envelope_always_acknowledged": False,
            "legacy_envelope_fallback": False,
        }
        self.ensure_gate_secret(gate_id)
        logger.info(
            "Gate created: %s by %s",
            privacy_log_label(gate_id, label="gate"),
            privacy_log_label(creator_id, label="node"),
        )
        return True, f"Gate '{gate_id}' created"

    def can_enter(self, node_id: str, gate_id: str) -> tuple[bool, str]:
        """Check if a node meets the entry rules for a gate."""
        gate = self.gates.get(gate_id)
        if not gate:
            return False, f"Gate '{gate_id}' does not exist"

        rules = gate.get("rules", {})
        rep = self.ledger.get_reputation(node_id)

        # Check overall rep requirement
        min_overall = rules.get("min_overall_rep", 0)
        if rep.get("overall", 0) < min_overall:
            return False, f"Need {min_overall} overall rep (you have {rep.get('overall', 0)})"

        # Check gate-specific rep requirements
        for req_gate, req_min in rules.get("min_gate_rep", {}).items():
            gate_rep = rep.get("gates", {}).get(req_gate, 0)
            if gate_rep < req_min:
                return False, f"Need {req_min} rep in '{req_gate}' gate (you have {gate_rep})"

        return True, "Access granted"

    def list_gates(self, *, include_secrets: bool = False) -> list[dict]:
        """List all gates with metadata.

        When *include_secrets* is True the per-gate content key is included so
        the frontend can encrypt/decrypt gate_envelope payloads.  The caller
        must ensure the request is authenticated before passing True.
        """
        result = []
        for gid, gate in self.gates.items():
            entry: dict = {
                "gate_id": gid,
                "display_name": gate.get("display_name", gid),
                "description": gate.get("description", ""),
                "welcome": gate.get("welcome", ""),
                "rules": gate.get("rules", {}),
                "created_at": gate.get("created_at", 0),
                "fixed": bool(gate.get("fixed", False)),
                "sort_order": int(gate.get("sort_order", 1000) or 1000),
            }
            if include_secrets:
                entry["gate_secret"] = gate.get("gate_secret", "")
            result.append(entry)
        return sorted(
            result,
            key=lambda x: (
                0 if x.get("fixed") else 1,
                int(x.get("sort_order", 1000) or 1000),
                -float(x.get("created_at", 0) or 0),
                x.get("gate_id", ""),
            ),
        )

    def get_gate_secret(self, gate_id: str) -> str:
        """Return the per-gate content key, or empty string if unknown."""
        gate = self.gates.get(str(gate_id or "").strip().lower())
        if not gate:
            return ""
        return str(gate.get("gate_secret", "") or "")

    def get_gate_secret_archive(self, gate_id: str) -> dict[str, Any]:
        gate_key = str(gate_id or "").strip().lower()
        gate = self.gates.get(gate_key)
        if not gate:
            return _normalized_gate_secret_archive({})
        self._prune_expired_gate_secret_archive_if_needed(gate_key)
        return _normalized_gate_secret_archive(gate.get("gate_secret_archive"))

    def _prune_expired_gate_secret_archive_if_needed(self, gate_key: str) -> bool:
        """Hardening Rec #10: wipe ``previous_secret`` bytes from disk state once
        the configured TTL has elapsed since rotation.

        Epoch/event_id ceilings in ``mesh_gate_mls._archived_gate_secret_allowed``
        already bound *decryption policy*, but the raw secret bytes otherwise sit
        in the on-disk gate state indefinitely. A disk-read adversary could use
        them to decrypt any old envelope keyed under that secret. This pruner
        caps that exposure to the TTL window (default 7 d). Returns True if a
        scrub happened, False otherwise.
        """
        from services.mesh.mesh_rollout_flags import gate_previous_secret_ttl_s

        ttl_s = int(gate_previous_secret_ttl_s() or 0)
        if ttl_s <= 0:
            return False
        gate = self.gates.get(gate_key)
        if not gate:
            return False
        raw = gate.get("gate_secret_archive") or {}
        previous_secret = str(raw.get("previous_secret", "") or "")
        if not previous_secret:
            return False
        rotated_at = float(raw.get("rotated_at", 0.0) or 0.0)
        if rotated_at <= 0.0:
            return False
        if (time.time() - rotated_at) < float(ttl_s):
            return False
        with self._gate_lock:
            gate = self.gates.get(gate_key)
            if not gate:
                return False
            raw = gate.get("gate_secret_archive") or {}
            if not str(raw.get("previous_secret", "") or ""):
                return False
            rotated_at = float(raw.get("rotated_at", 0.0) or 0.0)
            if rotated_at <= 0.0 or (time.time() - rotated_at) < float(ttl_s):
                return False
            gate["gate_secret_archive"] = _normalized_gate_secret_archive(
                {
                    "previous_secret": "",
                    "previous_valid_through_event_id": "",
                    "previous_valid_through_epoch": 0,
                    "rotated_at": float(raw.get("rotated_at", 0.0) or 0.0),
                    "reason": str(raw.get("reason", "") or "") + "|scrubbed_ttl",
                }
            )
            self._save()
            return True

    def ensure_gate_secret(self, gate_id: str) -> str:
        """Ensure a gate has a secret; generate and persist if missing."""
        gate_key = str(gate_id or "").strip().lower()
        with self._gate_lock:
            gate = self.gates.get(gate_key)
            if not gate:
                return ""
            current = str(gate.get("gate_secret", "") or "")
            if current:
                return current
            gate["gate_secret"] = _generate_gate_secret()
            gate["gate_secret_archive"] = _normalized_gate_secret_archive(gate.get("gate_secret_archive"))
            self._save()
            return str(gate.get("gate_secret", "") or "")

    def _rotate_gate_secret_for_member_removal_locked(
        self,
        gate_id: str,
        *,
        reason: str,
        previous_valid_through_event_id: str = "",
        previous_valid_through_epoch: int = 0,
    ) -> dict[str, Any]:
        """Rotate a gate secret and retain one prior value for pre-rotation reads.

        Single-slot archive is intentional: N-2 and older history must already
        exist in durable local plaintext. The archive only covers the most
        recent ban/kick transition.
        """
        gate_key = str(gate_id or "").strip().lower()
        gate = self.gates.get(gate_key)
        if not gate:
            return _normalized_gate_secret_archive({})
        current_secret = str(gate.get("gate_secret", "") or "")
        if not current_secret:
            current_secret = _generate_gate_secret()
        archive = {
            "previous_secret": current_secret,
            "previous_valid_through_event_id": str(previous_valid_through_event_id or ""),
            "previous_valid_through_epoch": max(0, int(previous_valid_through_epoch or 0)),
            "rotated_at": time.time(),
            "reason": str(reason or ""),
        }
        gate["gate_secret_archive"] = _normalized_gate_secret_archive(archive)
        gate["gate_secret"] = _generate_gate_secret()
        self._save()
        return dict(gate["gate_secret_archive"])

    def remove_member(self, gate_id: str, member_id: str, *, kind: str = "leave") -> dict[str, Any]:
        """Single authority for gate-member removal and ban/kick secret rotation."""
        gate_key = str(gate_id or "").strip().lower()
        member_key = str(member_id or "").strip()
        removal_kind = str(kind or "leave").strip().lower() or "leave"
        if removal_kind not in {"leave", "join", "kick", "ban"}:
            return {"ok": False, "detail": "invalid removal kind"}
        if gate_key not in self.gates:
            return {"ok": False, "detail": "Gate not found"}
        if not member_key:
            return {"ok": False, "detail": "member_id required"}
        if removal_kind == "join":
            return {
                "ok": True,
                "gate_id": gate_key,
                "member_id": member_key,
                "kind": removal_kind,
                "gate_secret_rotated": False,
                "detail": "join does not rotate gate_secret",
            }

        from services.mesh import mesh_gate_mls
        from services.mesh.mesh_rollout_flags import gate_ban_kick_rotation_enabled

        started = time.perf_counter()
        removed = mesh_gate_mls.remove_gate_member(
            gate_key,
            member_key,
            reason=removal_kind,
        )
        if not removed.get("ok"):
            return removed

        rotated = False
        archive = self.get_gate_secret_archive(gate_key)
        if removal_kind in {"ban", "kick"}:
            if gate_ban_kick_rotation_enabled():
                with self._gate_lock:
                    archive = self._rotate_gate_secret_for_member_removal_locked(
                        gate_key,
                        reason=removal_kind,
                        previous_valid_through_event_id=str(
                            removed.get("previous_valid_through_event_id", "") or ""
                        ),
                        previous_valid_through_epoch=int(removed.get("previous_epoch", 0) or 0),
                    )
                rotated = True
            else:
                logger.info(
                    "Gate secret rotation disabled; observed %s for %s member %s without rotating",
                    removal_kind,
                    privacy_log_label(gate_key, label="gate"),
                    privacy_log_label(member_key, label="member"),
                )
            metrics_observe_ms("ban_rotation_latency_ms", (time.perf_counter() - started) * 1000.0)

        result = dict(removed)
        result.update(
            {
                "gate_id": gate_key,
                "member_id": member_key,
                "kind": removal_kind,
                "gate_secret_rotated": rotated,
                "gate_secret_archive": archive,
                "ban_rotation_p99_budget_ms": BAN_ROTATION_P99_BUDGET_MS,
            }
        )
        if removal_kind in {"ban", "kick"} and not rotated:
            result["rotation_observed_only"] = True
        return result

    def get_envelope_policy(self, gate_id: str) -> str:
        """Return the envelope policy for a gate. Missing field → 'envelope_disabled'."""
        gate = self.gates.get(str(gate_id or "").strip().lower())
        if not gate:
            return "envelope_disabled"
        policy = str(gate.get("envelope_policy", "") or "")
        if policy not in VALID_ENVELOPE_POLICIES:
            return "envelope_disabled"
        return policy

    def set_envelope_policy(
        self,
        gate_id: str,
        policy: str,
        *,
        acknowledge_recovery_risk: bool = False,
    ) -> tuple[bool, str]:
        """Set the envelope policy for a gate. Returns (ok, detail)."""
        gate_key = str(gate_id or "").strip().lower()
        gate = self.gates.get(gate_key)
        if not gate:
            return False, "Gate not found"
        if policy not in VALID_ENVELOPE_POLICIES:
            return False, f"Invalid policy: must be one of {VALID_ENVELOPE_POLICIES}"
        if policy == "envelope_always" and not acknowledge_recovery_risk:
            return False, (
                "envelope_always requires acknowledge_recovery_risk=true because "
                "durable recovery envelopes weaken gate content privacy"
            )
        previous_policy = str(gate.get("envelope_policy", "") or "")
        gate["envelope_policy"] = policy
        gate["envelope_always_acknowledged"] = bool(policy == "envelope_always")
        self._save()
        if previous_policy != policy:
            metrics_inc("envelope_policy_transitions")
        return True, f"envelope_policy set to '{policy}' for gate '{gate_key}'"

    def get_legacy_envelope_fallback(self, gate_id: str) -> bool:
        """Legacy envelope fallback has been removed.

        Sprint 1 / Rec #6: the Phase-1 gate-name-only and node-local
        envelope key paths no longer exist in _gate_envelope_decrypt.
        This helper is retained as a stub so older API handlers and
        tests don't explode — it always returns False.
        """
        return False

    def set_legacy_envelope_fallback(
        self,
        gate_id: str,
        enabled: bool,
        *,
        acknowledge_legacy_risk: bool = False,
    ) -> tuple[bool, str]:
        """Rejects enable attempts; disable is always a no-op success.

        Sprint 1 / Rec #6: the legacy envelope key derivation has been
        removed, so there is nothing left to enable. We return a clear
        error for enable attempts and accept disable as a no-op so old
        operator scripts can still tidy up state without crashing.
        """
        gate_key = str(gate_id or "").strip().lower()
        gate = self.gates.get(gate_key)
        if not gate:
            return False, "Gate not found"
        # Always sanitise any stale persisted flag — the legacy path is gone.
        gate["legacy_envelope_fallback"] = False
        gate["legacy_envelope_fallback_acknowledged"] = False
        gate["legacy_envelope_fallback_enabled_at"] = 0
        gate["legacy_envelope_fallback_expires_at"] = 0
        self._save()
        _ = acknowledge_legacy_risk  # accepted for API compat, ignored
        if enabled:
            logger.warning(
                "[mesh] set_legacy_envelope_fallback(enabled=True) rejected for %s — "
                "legacy envelope key path removed in Sprint 1 / Rec #6",
                privacy_log_label(gate_key, label="gate"),
            )
            return False, (
                "legacy_envelope_fallback has been removed in Sprint 1 / Rec #6; "
                "there is no weaker key path left to enable"
            )
        return True, f"legacy_envelope_fallback cleared for gate '{gate_key}'"

    def get_gate(self, gate_id: str) -> Optional[dict]:
        """Get gate details (safe for remote callers — secrets excluded)."""
        gate = self.gates.get(gate_id)
        if not gate:
            return None
        public_gate = {
            key: value
            for key, value in gate.items()
            if key not in {"creator_node_id", "message_count", "gate_secret", "gate_secret_archive"}
        }
        return {
            "gate_id": gate_id,
            **public_gate,
        }

    def record_message(self, gate_id: str):
        """Increment message count for a gate."""
        if gate_id in self.gates:
            self.gates[gate_id]["message_count"] = self.gates[gate_id].get("message_count", 0) + 1
            self._save()

    def is_ratified(self, gate_id: str) -> bool:
        """Check if a gate is ratified (has permanent chain address).

        Before BOOTSTRAP_THRESHOLD nodes: all gates are ratified (early access).
        After bootstrap: gates need cumulative member rep >= GATE_RATIFICATION_REP.
        """
        if len(self.ledger.nodes) < BOOTSTRAP_THRESHOLD:
            return True  # Pre-bootstrap: all gates are ratified

        gate = self.gates.get(gate_id)
        if not gate:
            return False

        # Sum rep of all nodes that have gate-specific rep in this gate
        all_reps = self.ledger.get_all_reputations()
        self.ledger._recompute_scores()
        cumulative = 0
        for nid, score_data in self.ledger._scores_cache.items():
            gate_rep = score_data.get("gates", {}).get(gate_id, 0)
            if gate_rep > 0:
                cumulative += gate_rep

        return cumulative >= GATE_RATIFICATION_REP

    def get_ratification_status(self, gate_id: str) -> dict:
        """Get gate's ratification progress."""
        gate = self.gates.get(gate_id)
        if not gate:
            return {"ratified": False, "reason": "Gate not found"}

        network_size = len(self.ledger.nodes)
        if network_size < BOOTSTRAP_THRESHOLD:
            return {
                "ratified": True,
                "reason": f"Pre-bootstrap ({network_size}/{BOOTSTRAP_THRESHOLD} nodes) — all gates ratified",
                "cumulative_rep": 0,
                "required_rep": GATE_RATIFICATION_REP,
            }

        # Compute cumulative gate rep
        self.ledger._recompute_scores()
        cumulative = 0
        contributors = 0
        for nid, score_data in self.ledger._scores_cache.items():
            gate_rep = score_data.get("gates", {}).get(gate_id, 0)
            if gate_rep > 0:
                cumulative += gate_rep
                contributors += 1

        ratified = cumulative >= GATE_RATIFICATION_REP
        return {
            "ratified": ratified,
            "cumulative_rep": cumulative,
            "required_rep": GATE_RATIFICATION_REP,
            "contributors": contributors,
            "reason": (
                "Ratified — permanent chain address"
                if ratified
                else f"Need {GATE_RATIFICATION_REP - cumulative} more cumulative rep"
            ),
        }


# ─── Module-level singletons ─────────────────────────────────────────────

reputation_ledger = ReputationLedger()
gate_manager = GateManager(reputation_ledger)
