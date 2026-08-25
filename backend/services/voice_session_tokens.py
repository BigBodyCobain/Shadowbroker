"""Short-lived, single-use WebSocket bootstrap tokens for the voice agent.

Voice-agent plan §4.4 — a clone of ``services/agent_shell_ws_token.py``
semantics with voice-specific bounds:

  - TTL 60 s (one session-start handshake, not a long-lived credential).
  - ``_MAX_ACTIVE_TOKENS = 64`` (voice token store cap, §1.3) — soonest-expiry
    eviction without lock recursion (``agent_shell_ws_token.py:36–41``).
  - A token minted for a session is BOUND to that sessionId: the burn gate
    rejects an upgrade attempt that names any other session, so a minted
    grant can never be replayed against a different live session.

The broker burns a token exactly once during the WebSocket upgrade; failure
closes with code 4403. Tokens never grant anything beyond that upgrade.
"""

from __future__ import annotations

import secrets
import time
from threading import Lock

_TOKEN_TTL_SECONDS = 60.0
_MAX_ACTIVE_TOKENS = 64

#: Injectable clock — tests advance it past the TTL to exercise REAL expiry
#: instead of relying on unknown-token equivalence.
_now = time.time

#: token -> (expires_at_epoch, bound_session_id | None)
_store: dict[str, tuple[float, str | None]] = {}
_lock = Lock()


def _purge_expired_locked(now: float) -> None:
    """Drop expired tokens while the caller holds ``_lock``."""
    expired = [token for token, entry in _store.items() if entry[0] <= now]
    for token in expired:
        _store.pop(token, None)


def mint_voice_session_token(session_id: str | None = None) -> tuple[str, int]:
    """Return (token, expires_in_seconds) without exceeding the store bound.

    When ``session_id`` is given, the token is bound to that session: the
    burn gate accepts it only for an upgrade naming the same sessionId.
    """
    token = secrets.token_urlsafe(32)
    now = _now()
    expires_at = now + _TOKEN_TTL_SECONDS
    with _lock:
        _purge_expired_locked(now)
        if len(_store) >= _MAX_ACTIVE_TOKENS:
            # Evict the token that will expire soonest. This keeps the store
            # bounded without recursively acquiring the non-reentrant lock.
            oldest = min(_store, key=lambda item: item[1][0])
            _store.pop(oldest, None)
        _store[token] = (
            expires_at,
            str(session_id).strip() if session_id else None,
        )
    return token, int(_TOKEN_TTL_SECONDS)


def consume_voice_session_token(token: str, *, session_id: str | None = None) -> bool:
    """Validate and burn a one-time token. Returns True when accepted.

    The burn happens on use regardless of outcome: a mismatched-sessionId or
    expired attempt still consumes the token, so one-time semantics never
    degrade into replayable probes. A token minted with a session binding is
    accepted only when the upgrade names that same sessionId.
    """
    cleaned = str(token or "").strip()
    if not cleaned:
        return False
    now = _now()
    requested = str(session_id).strip() if session_id else ""
    with _lock:
        _purge_expired_locked(now)
        entry = _store.pop(cleaned, None)
    if entry is None:
        return False
    expires_at, bound_session = entry
    if expires_at <= now:
        return False
    if bound_session and requested != bound_session:
        return False
    return True


def reset_voice_session_tokens_for_tests() -> None:
    with _lock:
        _store.clear()
