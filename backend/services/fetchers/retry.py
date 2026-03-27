"""Retry decorator with exponential backoff + jitter for network-bound fetcher functions.

Usage:
    @with_retry(max_retries=3, base_delay=2)
    def fetch_something():
        ...
"""

import time
import random
import logging
import functools
import requests

logger = logging.getLogger(__name__)

# Only retry on transient network/OS errors — not on parse errors, key errors, etc.
TRANSIENT_ERRORS = (
    TimeoutError,
    ConnectionError,
    OSError,
    requests.RequestException,
)


def with_retry(max_retries: int = 3, base_delay: float = 2.0, max_delay: float = 30.0):
    """Decorator: retries the wrapped function on transient errors with exponential backoff + jitter.

    Only retries on network/OS errors (TimeoutError, ConnectionError, OSError,
    requests.RequestException). Non-transient errors (ValueError, KeyError, etc.)
    propagate immediately.

    Args:
        max_retries:  Number of retry attempts after the initial failure.
        base_delay:   Base delay (seconds) for exponential backoff (2 → 4 → 8 …).
        max_delay:    Cap on the delay between retries.
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(1 + max_retries):
                try:
                    return func(*args, **kwargs)
                except TRANSIENT_ERRORS as exc:
                    last_exc = exc
                    if attempt < max_retries:
                        delay = min(base_delay * (2**attempt), max_delay)
                        jitter = random.uniform(0, delay * 0.25)
                        total = delay + jitter
                        logger.warning(
                            "%s failed (attempt %d/%d): %s — retrying in %.1fs",
                            func.__name__,
                            attempt + 1,
                            max_retries + 1,
                            exc,
                            total,
                        )
                        time.sleep(total)
                    else:
                        logger.error(
                            "%s failed after %d attempts: %s",
                            func.__name__,
                            max_retries + 1,
                            exc,
                        )
            raise last_exc  # type: ignore[misc]

        return wrapper

    return decorator
