"""Short-lived, single-use WebSocket bootstrap tokens for the voice agent.

Voice-agent plan §4.4 — a clone of ``services/agent_shell_ws_token.py``
semantics with voice-specific bounds:

  - TTL 60 s (one session-start handshake, not a long-lived credential).
  - ``_MAX_ACTIVE_TOKENS = 64`` (voice token store cap, §1.3) — soonest-expiry
    eviction without lock recursion (``agent_shell_ws_token.py:36–41``).

The broker burns a token exactly once during the WebSocket upgrade; failure
closes with code 4403. Tokens never grant anything beyond that upgrade.
"""

from __future__ import annotations

import secrets
import time
from threading import Lock

_TOKEN_TTL_SECONDS = 60.0
_MAX_ACTIVE_TOKENS = 64

_store: dict[str, float] = {}
_lock = Lock()


def _purge_expired_locked(now: float) -> None:
    """Drop expired tokens while the caller holds ``_lock``."""
    expired = [token for token, expires in _store.items() if expires <= now]
    for token in expired:
        _store.pop(token, None)


def mint_voice_session_token() -> tuple[str, int]:
    """Return (token, expires_in_seconds) without exceeding the store bound."""
    token = secrets.token_urlsafe(32)
    now = time.time()
    expires_at = now + _TOKEN_TTL_SECONDS
    with _lock:
        _purge_expired_locked(now)
        if len(_store) >= _MAX_ACTIVE_TOKENS:
            # Evict the token that will expire soonest. This keeps the store
            # bounded without recursively acquiring the non-reentrant lock.
            oldest = min(_store, key=_store.get)
            _store.pop(oldest, None)
        _store[token] = expires_at
    return token, int(_TOKEN_TTL_SECONDS)


def consume_voice_session_token(token: str) -> bool:
    """Validate and burn a one-time token. Returns True when accepted."""
    cleaned = str(token or "").strip()
    if not cleaned:
        return False
    now = time.time()
    with _lock:
        _purge_expired_locked(now)
        expires_at = _store.pop(cleaned, None)
    return expires_at is not None and expires_at > now


def reset_voice_session_tokens_for_tests() -> None:
    with _lock:
        _store.clear()
