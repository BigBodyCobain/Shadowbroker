"""Typed AI analyst tool layer.

The AI operates as an analyst *over structured backend data*, never by scraping
the UI or issuing arbitrary requests. This package provides:

* :mod:`agents.untrusted` — the DATA/INSTRUCTIONS boundary. External OSINT
  content (Telegram, news, scraped pages, API responses) is wrapped so it can
  never be mistaken for an instruction to the model, and obvious injection
  attempts are flagged (not silently mutated).
* :mod:`agents.tools` — a registry of typed tools with strict input schemas,
  per-tool authorization scopes (read/write/act), validation, structured output
  envelopes, audit logging and error handling.

The registry reuses the existing telemetry search, correlation engine and the
investigation store rather than duplicating them.
"""

from agents.tools import ToolContext, ToolError, get_registry
from agents.untrusted import is_suspected_injection, wrap_untrusted

__all__ = [
    "ToolContext",
    "ToolError",
    "get_registry",
    "wrap_untrusted",
    "is_suspected_injection",
]
