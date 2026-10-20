"""Short-lived, single-use WebSocket bootstrap tokens for the agent shell."""

from __future__ import annotations

import secrets
import time
from threading import Lock

_TOKEN_TTL_SECONDS = 60.0
_MAX_ACTIVE_TOKENS = 256

_store: dict[str, float] = {}
_lock = Lock()


def _purge_expired_locked(now: float) -> None:
    """Drop expired tokens while the caller holds ``_lock``."""
    expired = [token for token, expires in _store.items() if expires <= now]
    for token in expired:
        _store.pop(token, None)


def _purge_expired() -> None:
    now = time.time()
    with _lock:
        _purge_expired_locked(now)


def mint_agent_shell_ws_token() -> tuple[str, int]:
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


def consume_agent_shell_ws_token(token: str) -> bool:
    """Validate and burn a one-time token. Returns True when accepted."""
    cleaned = str(token or "").strip()
    if not cleaned:
        return False
    now = time.time()
    with _lock:
        _purge_expired_locked(now)
        expires_at = _store.pop(cleaned, None)
    return expires_at is not None and expires_at > now


def reset_agent_shell_ws_tokens_for_tests() -> None:
    with _lock:
        _store.clear()
