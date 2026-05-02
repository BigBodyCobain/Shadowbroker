"""Versioned local-custody wrapper for sensitive persisted private state.

This layer sits inside the existing secure/domain storage envelope. New writes
wrap sensitive payloads in a custody envelope before persistence, and legacy
payloads migrate automatically on first successful read.

The wrapper does not change transport or release policy. Its purpose is to
raise the local-compromise cost for persisted private state without breaking
restart recovery or requiring user action.
"""

from __future__ import annotations

import base64
import json
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol, TypeVar

from services.mesh import mesh_secure_storage as secure_storage

logger = logging.getLogger(__name__)

_ENVELOPE_KIND = "sb_local_custody"
_ENVELOPE_VERSION = 1
_STATUS_LABELS = {
    "protected_at_rest": "Protected at rest",
    "degraded_local_custody": "Degraded local custody",
    "migration_in_progress": "Migration in progress",
    "migration_failed": "Migration failed",
}
_STATUS_LOCK = threading.RLock()
_STATUS: dict[str, Any] = {
    "code": "degraded_local_custody",
    "label": _STATUS_LABELS["degraded_local_custody"],
    "provider": "unknown",
    "detail": "Sensitive local custody has not been initialized yet.",
    "scope": "",
    "protected_at_rest": False,
    "last_error": "",
}
_TEST_PROVIDER: "PayloadCustodyProvider | None" = None
_TEST_PROVIDER_REGISTRY: dict[str, "PayloadCustodyProvider"] = {}

T = TypeVar("T")


class LocalCustodyError(RuntimeError):
    """Raised when a sensitive custody envelope cannot be read or written."""


class PayloadCustodyProvider(Protocol):
    name: str
    protected_at_rest: bool

    def wrap(self, scope: str, plaintext: bytes) -> dict[str, Any]:
        ...

    def unwrap(self, envelope: dict[str, Any], scope: str) -> bytes:
        ...


@dataclass(frozen=True)
class _DpapiProvider:
    name: str = "dpapi-machine"
    protected_at_rest: bool = True

    def wrap(self, scope: str, plaintext: bytes) -> dict[str, Any]:
        try:
            protected = secure_storage._dpapi_protect(plaintext, machine_scope=True)
        except Exception as exc:  # pragma: no cover - depends on OS API
            raise LocalCustodyError(f"DPAPI protect failed for {scope}: {exc}") from exc
        return {"protected_payload": secure_storage._b64(protected)}

    def unwrap(self, envelope: dict[str, Any], scope: str) -> bytes:
        try:
            return secure_storage._dpapi_unprotect(
                secure_storage._unb64(envelope.get("protected_payload"))
            )
        except Exception as exc:  # pragma: no cover - depends on OS API
            raise LocalCustodyError(f"DPAPI unwrap failed for {scope}: {exc}") from exc


@dataclass(frozen=True)
class _PassphraseProvider:
    name: str = "passphrase"
    protected_at_rest: bool = True

    def wrap(self, scope: str, plaintext: bytes) -> dict[str, Any]:
        secret = secure_storage._get_storage_secret()
        if not secret:
            raise LocalCustodyError(
                "Passphrase custody provider selected but MESH_SECURE_STORAGE_SECRET is not set"
            )
        wrapped = secure_storage._passphrase_wrap(plaintext, secret)
        return {
            "salt": wrapped["salt"],
            "nonce": wrapped["nonce"],
            "protected_payload": wrapped["protected_key"],
        }

    def unwrap(self, envelope: dict[str, Any], scope: str) -> bytes:
        secret = secure_storage._get_storage_secret()
        if not secret:
            raise LocalCustodyError(
                "Passphrase-protected custody exists but MESH_SECURE_STORAGE_SECRET is not set"
            )
        try:
            return secure_storage._passphrase_unwrap(
                {
                    "salt": envelope.get("salt"),
                    "nonce": envelope.get("nonce"),
                    "protected_key": envelope.get("protected_payload"),
                },
                secret,
            )
        except Exception as exc:
            raise LocalCustodyError(f"Passphrase unwrap failed for {scope}: {exc}") from exc


@dataclass(frozen=True)
class _RawFallbackProvider:
    name: str = "raw"
    protected_at_rest: bool = False

    def wrap(self, scope: str, plaintext: bytes) -> dict[str, Any]:
        return {"payload_b64": secure_storage._b64(plaintext)}

    def unwrap(self, envelope: dict[str, Any], scope: str) -> bytes:
        return secure_storage._unb64(envelope.get("payload_b64"))


def _status_for_provider(provider: PayloadCustodyProvider, *, scope: str, detail: str = "") -> dict[str, Any]:
    code = "protected_at_rest" if provider.protected_at_rest else "degraded_local_custody"
    return {
        "code": code,
        "label": _STATUS_LABELS[code],
        "provider": provider.name,
        "detail": detail
        or (
            "Sensitive local state is wrapped before persistence."
            if provider.protected_at_rest
            else "Sensitive local state is preserved, but the local custody provider is degraded."
        ),
        "scope": str(scope or ""),
        "protected_at_rest": bool(provider.protected_at_rest),
        "last_error": "",
    }


def _set_status(snapshot: dict[str, Any]) -> None:
    with _STATUS_LOCK:
        _STATUS.update(snapshot)


def _set_migration_status(code: str, *, scope: str, detail: str, error: str = "") -> None:
    with _STATUS_LOCK:
        _STATUS.update(
            {
                "code": code,
                "label": _STATUS_LABELS[code],
                "provider": _STATUS.get("provider", "unknown"),
                "detail": detail,
                "scope": str(scope or ""),
                "protected_at_rest": bool(_STATUS.get("protected_at_rest", False)),
                "last_error": str(error or ""),
            }
        )


def local_custody_status_snapshot() -> dict[str, Any]:
    with _STATUS_LOCK:
        return dict(_STATUS)


def reset_local_custody_for_tests() -> None:
    global _TEST_PROVIDER
    _TEST_PROVIDER = None
    _TEST_PROVIDER_REGISTRY.clear()
    with _STATUS_LOCK:
        _STATUS.clear()
        _STATUS.update(
            {
                "code": "degraded_local_custody",
                "label": _STATUS_LABELS["degraded_local_custody"],
                "provider": "unknown",
                "detail": "Sensitive local custody has not been initialized yet.",
                "scope": "",
                "protected_at_rest": False,
                "last_error": "",
            }
        )


def set_local_custody_provider_for_tests(provider: PayloadCustodyProvider | None) -> None:
    global _TEST_PROVIDER
    _TEST_PROVIDER = provider
    if provider is not None:
        _TEST_PROVIDER_REGISTRY[str(provider.name or "").strip().lower()] = provider


def _active_provider() -> PayloadCustodyProvider:
    if _TEST_PROVIDER is not None:
        return _TEST_PROVIDER
    if secure_storage._is_windows():
        return _DpapiProvider()
    if secure_storage._get_storage_secret():
        return _PassphraseProvider()
    if secure_storage._raw_fallback_allowed():
        return _RawFallbackProvider()
    raise LocalCustodyError(
        "No local custody provider available. Configure MESH_SECURE_STORAGE_SECRET "
        "or explicitly allow raw secure-storage fallback."
    )


def _provider_for_name(provider_name: str) -> PayloadCustodyProvider:
    normalized = str(provider_name or "").strip().lower()
    if not normalized:
        raise LocalCustodyError("Local custody envelope is missing its provider")
    if normalized in _TEST_PROVIDER_REGISTRY:
        return _TEST_PROVIDER_REGISTRY[normalized]
    if normalized == "dpapi-machine":
        return _DpapiProvider()
    if normalized == "passphrase":
        return _PassphraseProvider()
    if normalized == "raw":
        return _RawFallbackProvider()
    raise LocalCustodyError(f"Unsupported local custody provider: {normalized}")


def _stable_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _scope_name(domain: str, filename: str, custody_scope: str = "") -> str:
    if custody_scope:
        return str(custody_scope).strip().lower()
    return f"{str(domain or '').strip().lower()}::{str(filename or '').strip().lower()}"


def _is_custody_envelope(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and str(value.get("kind", "") or "") == _ENVELOPE_KIND
        and int(value.get("version", 0) or 0) == _ENVELOPE_VERSION
        and "provider" in value
    )


def _encode_envelope(payload: Any, *, scope: str, provider: PayloadCustodyProvider) -> dict[str, Any]:
    plaintext = _stable_json(payload)
    provider_payload = provider.wrap(scope, plaintext)
    envelope = {
        "kind": _ENVELOPE_KIND,
        "version": _ENVELOPE_VERSION,
        "scope": scope,
        "provider": provider.name,
        "protected_at_rest": bool(provider.protected_at_rest),
    }
    envelope.update(provider_payload)
    return envelope


def _decode_envelope(envelope: dict[str, Any], *, scope: str, provider: PayloadCustodyProvider) -> Any:
    stored_scope = str(envelope.get("scope", "") or "").strip().lower()
    if stored_scope and stored_scope != scope:
        raise LocalCustodyError(f"Local custody scope mismatch: {stored_scope} != {scope}")
    plaintext = provider.unwrap(envelope, scope)
    try:
        return json.loads(plaintext.decode("utf-8"))
    except Exception as exc:
        raise LocalCustodyError(f"Failed to decode local custody payload for {scope}: {exc}") from exc


def write_sensitive_domain_json(
    domain: str,
    filename: str,
    payload: Any,
    *,
    custody_scope: str = "",
    base_dir: str | Path | None = None,
) -> Path:
    scope = _scope_name(domain, filename, custody_scope)
    provider = _active_provider()
    envelope = _encode_envelope(payload, scope=scope, provider=provider)
    try:
        path = secure_storage.write_domain_json(domain, filename, envelope, base_dir=base_dir)
    except Exception as exc:
        raise LocalCustodyError(f"Failed to persist local custody payload for {scope}: {exc}") from exc
    _set_status(_status_for_provider(provider, scope=scope))
    return path


def read_sensitive_domain_json(
    domain: str,
    filename: str,
    default_factory: Callable[[], T],
    *,
    custody_scope: str = "",
    base_dir: str | Path | None = None,
) -> T:
    scope = _scope_name(domain, filename, custody_scope)
    file_path = secure_storage._domain_file_path(domain, filename, base_dir=base_dir)
    if not file_path.exists():
        return default_factory()

    raw = secure_storage.read_domain_json(domain, filename, default_factory, base_dir=base_dir)
    if _is_custody_envelope(raw):
        persisted = dict(raw)
        provider = _provider_for_name(str(persisted.get("provider", "") or ""))
        decoded = _decode_envelope(persisted, scope=scope, provider=provider)
        _set_status(_status_for_provider(provider, scope=scope))
        return decoded

    # Legacy payload: preserve readability, then migrate automatically.
    legacy_payload = raw
    provider = _active_provider()
    _set_migration_status(
        "migration_in_progress",
        scope=scope,
        detail="Sensitive local state is being migrated to a wrapped custody envelope.",
    )
    try:
        envelope = _encode_envelope(legacy_payload, scope=scope, provider=provider)
        decoded = _decode_envelope(envelope, scope=scope, provider=provider)
        if _stable_json(decoded) != _stable_json(legacy_payload):
            raise LocalCustodyError("Local custody migration verification failed before write")
        secure_storage.write_domain_json(domain, filename, envelope, base_dir=base_dir)
        persisted = secure_storage.read_domain_json(domain, filename, lambda: None, base_dir=base_dir)
        if not _is_custody_envelope(persisted):
            raise LocalCustodyError("Persisted local custody migration did not produce a custody envelope")
        reloaded = _decode_envelope(dict(persisted), scope=scope, provider=provider)
        if _stable_json(reloaded) != _stable_json(legacy_payload):
            raise LocalCustodyError("Persisted local custody migration verification failed")
        _set_status(_status_for_provider(provider, scope=scope))
        return legacy_payload
    except Exception as exc:
        logger.warning("local custody migration failed for %s: %s", scope, exc)
        try:
            # Preserve readable state even if the wrapped rewrite failed.
            secure_storage.write_domain_json(domain, filename, legacy_payload, base_dir=base_dir)
        except Exception:
            logger.warning("local custody restore failed for %s", scope, exc_info=True)
        _set_migration_status(
            "migration_failed",
            scope=scope,
            detail="Sensitive local state could not be migrated and is still using the legacy readable form.",
            error=str(exc),
        )
        return legacy_payload
