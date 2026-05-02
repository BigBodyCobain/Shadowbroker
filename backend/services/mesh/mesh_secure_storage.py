"""Secure local storage helpers for Wormhole-owned state.

Windows uses DPAPI to protect local key envelopes. Non-Windows (including
Docker/Linux) uses a passphrase-based provider: an operator-supplied secret
(via MESH_SECURE_STORAGE_SECRET or MESH_SECURE_STORAGE_SECRET_FILE) is
stretched with PBKDF2-SHA256 and used to AES-GCM-wrap master and domain keys.

Root secure-json payloads still use a dedicated master key, while domain-scoped
payloads use independent per-domain keys so compromise of one domain key does
not automatically collapse every other Wormhole compartment.

Raw/plaintext key fallback is available only when tests are running or an
explicit MESH_ALLOW_RAW_SECURE_STORAGE_FALLBACK=true opt-in is set. Docker
containers no longer auto-allow raw fallback.
"""

from __future__ import annotations

import base64
import ctypes
import hashlib
import hmac
import json
import logging
import os
import shutil
import re
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, TypeVar

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
MASTER_KEY_FILE = DATA_DIR / "wormhole_secure_store.key"

_ENVELOPE_KIND = "sb_secure_json"
_ENVELOPE_VERSION = 1
_MASTER_KIND = "sb_secure_master_key"
_MASTER_VERSION = 1
_DOMAIN_KEY_KIND = "sb_secure_domain_key"
_DOMAIN_KEY_VERSION = 1
_MASTER_KEY_CACHE: tuple[str, bytes] | None = None
_DOMAIN_KEY_CACHE: dict[str, tuple[str, bytes]] = {}

T = TypeVar("T")

logger = logging.getLogger(__name__)


class SecureStorageError(RuntimeError):
    """Raised when secure local storage cannot be read or written safely."""


def _atomic_write_text(target: Path, content: str, encoding: str = "utf-8") -> None:
    """Write content atomically via temp file + os.replace()."""
    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        last_exc: Exception | None = None
        for _ in range(5):
            try:
                os.replace(tmp_path, str(target))
                last_exc = None
                break
            except PermissionError as exc:
                last_exc = exc
                time.sleep(0.02)
        if last_exc is not None:
            raise last_exc
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _unb64(data: str | bytes | None) -> bytes:
    if not data:
        return b""
    if isinstance(data, bytes):
        return base64.b64decode(data)
    return base64.b64decode(data.encode("ascii"))


def _stable_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _envelope_aad(path: Path) -> bytes:
    return f"shadowbroker|secure-json|v{_ENVELOPE_VERSION}|{path.name}".encode("utf-8")


def _master_aad() -> bytes:
    return f"shadowbroker|master-key|v{_MASTER_VERSION}".encode("utf-8")


def _domain_key_aad(domain: str) -> bytes:
    return f"shadowbroker|domain-key|v{_DOMAIN_KEY_VERSION}|{domain}".encode("utf-8")


def _storage_root(base_dir: str | Path | None = None) -> Path:
    return Path(base_dir).resolve() if base_dir is not None else DATA_DIR.resolve()


def _domain_key_dir(base_dir: str | Path | None = None) -> Path:
    return _storage_root(base_dir) / "_domain_keys"


def _normalize_domain_name(domain: str) -> str:
    domain_name = str(domain or "").strip().lower()
    if not domain_name:
        raise SecureStorageError("domain name required for domain-scoped storage")
    if not re.fullmatch(r"[a-z0-9_]+", domain_name):
        raise SecureStorageError(f"invalid domain name: {domain_name!r}")
    return domain_name


def _domain_aad(domain: str, filename: str) -> bytes:
    return f"shadowbroker|domain-json|v{_ENVELOPE_VERSION}|{domain}|{filename}".encode("utf-8")


def _master_envelope_for_windows(protected_key: bytes, *, provider: str) -> dict[str, Any]:
    return {
        "kind": _MASTER_KIND,
        "version": _MASTER_VERSION,
        "provider": provider,
        "protected_key": _b64(protected_key),
    }


def _master_envelope_for_fallback(raw_key: bytes) -> dict[str, Any]:
    return {
        "kind": _MASTER_KIND,
        "version": _MASTER_VERSION,
        "provider": "raw",
        "key": _b64(raw_key),
    }


def _domain_key_envelope_for_windows(
    domain: str,
    protected_key: bytes,
    *,
    provider: str,
) -> dict[str, Any]:
    return {
        "kind": _DOMAIN_KEY_KIND,
        "version": _DOMAIN_KEY_VERSION,
        "provider": provider,
        "domain": domain,
        "protected_key": _b64(protected_key),
    }


def _domain_key_envelope_for_fallback(domain: str, raw_key: bytes) -> dict[str, Any]:
    return {
        "kind": _DOMAIN_KEY_KIND,
        "version": _DOMAIN_KEY_VERSION,
        "provider": "raw",
        "domain": domain,
        "key": _b64(raw_key),
    }


def _secure_envelope(path: Path, nonce: bytes, ciphertext: bytes) -> dict[str, Any]:
    return {
        "kind": _ENVELOPE_KIND,
        "version": _ENVELOPE_VERSION,
        "path": path.name,
        "nonce": _b64(nonce),
        "ciphertext": _b64(ciphertext),
    }


def _is_secure_envelope(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and str(value.get("kind", "") or "") == _ENVELOPE_KIND
        and int(value.get("version", 0) or 0) == _ENVELOPE_VERSION
        and "nonce" in value
        and "ciphertext" in value
    )


def _is_windows() -> bool:
    return os.name == "nt"


def _is_docker_container() -> bool:
    """Detect if we're running inside a Docker container."""
    if os.path.isfile("/.dockerenv"):
        return True
    try:
        with open("/proc/1/cgroup", "r") as f:
            if "docker" in f.read():
                return True
    except OSError:
        pass
    return os.environ.get("container") == "docker"


def _raw_fallback_allowed() -> bool:
    if _is_windows():
        return False
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return True
    try:
        from services.config import get_settings

        settings = get_settings()
        if bool(getattr(settings, "MESH_ALLOW_RAW_SECURE_STORAGE_FALLBACK", False)):
            return True
    except Exception as exc:
        logger.debug(
            "get_settings() unavailable in _raw_fallback_allowed — defaulting to disallow: %s",
            type(exc).__name__,
        )
    return False


def _get_storage_secret() -> str | None:
    """Return the operator-supplied secure storage secret, or None."""
    secret = os.environ.get("MESH_SECURE_STORAGE_SECRET", "").strip()
    if secret:
        return secret
    try:
        from services.config import get_settings

        settings = get_settings()
        secret = str(getattr(settings, "MESH_SECURE_STORAGE_SECRET", "") or "").strip()
        if secret:
            return secret
    except Exception:
        pass
    return None


_PASSPHRASE_PBKDF2_ITERATIONS = 600_000


def _passphrase_wrap(raw_key: bytes, secret: str, salt: bytes | None = None) -> dict[str, str]:
    """Wrap *raw_key* using a PBKDF2-derived AES-GCM key from *secret*."""
    if salt is None:
        salt = os.urandom(32)
    derived = hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), salt, _PASSPHRASE_PBKDF2_ITERATIONS)
    nonce = os.urandom(12)
    ciphertext = AESGCM(derived).encrypt(nonce, raw_key, b"shadowbroker|passphrase-wrap")
    return {
        "salt": _b64(salt),
        "nonce": _b64(nonce),
        "protected_key": _b64(ciphertext),
    }


def _passphrase_unwrap(envelope: dict[str, Any], secret: str) -> bytes:
    """Unwrap a passphrase-protected key envelope."""
    salt = _unb64(envelope.get("salt"))
    nonce = _unb64(envelope.get("nonce"))
    ciphertext = _unb64(envelope.get("protected_key"))
    derived = hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), salt, _PASSPHRASE_PBKDF2_ITERATIONS)
    return AESGCM(derived).decrypt(nonce, ciphertext, b"shadowbroker|passphrase-wrap")


def _master_envelope_for_passphrase(raw_key: bytes, secret: str) -> dict[str, Any]:
    wrapped = _passphrase_wrap(raw_key, secret)
    return {
        "kind": _MASTER_KIND,
        "version": _MASTER_VERSION,
        "provider": "passphrase",
        **wrapped,
    }


def _domain_key_envelope_for_passphrase(domain: str, raw_key: bytes, secret: str) -> dict[str, Any]:
    wrapped = _passphrase_wrap(raw_key, secret)
    return {
        "kind": _DOMAIN_KEY_KIND,
        "version": _DOMAIN_KEY_VERSION,
        "provider": "passphrase",
        "domain": domain,
        **wrapped,
    }


if _is_windows():
    from ctypes import wintypes

    class _DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


    _crypt32 = ctypes.windll.crypt32
    _kernel32 = ctypes.windll.kernel32
    _CRYPTPROTECT_UI_FORBIDDEN = 0x1
    _CRYPTPROTECT_LOCAL_MACHINE = 0x4

    _crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB),
        wintypes.LPCWSTR,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DATA_BLOB),
    ]
    _crypt32.CryptProtectData.restype = wintypes.BOOL
    _crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DATA_BLOB),
    ]
    _crypt32.CryptUnprotectData.restype = wintypes.BOOL
    _kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    _kernel32.LocalFree.restype = ctypes.c_void_p


    def _blob_from_bytes(data: bytes) -> tuple[_DATA_BLOB, ctypes.Array[ctypes.c_char]]:
        buf = ctypes.create_string_buffer(data, len(data))
        blob = _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))
        return blob, buf


    def _bytes_from_blob(blob: _DATA_BLOB) -> bytes:
        return ctypes.string_at(blob.pbData, blob.cbData)


    def _dpapi_protect(data: bytes, *, machine_scope: bool) -> bytes:
        in_blob, in_buf = _blob_from_bytes(data)
        out_blob = _DATA_BLOB()
        flags = _CRYPTPROTECT_UI_FORBIDDEN
        if machine_scope:
            flags |= _CRYPTPROTECT_LOCAL_MACHINE
        if not _crypt32.CryptProtectData(
            ctypes.byref(in_blob),
            "ShadowBroker Wormhole",
            None,
            None,
            None,
            flags,
            ctypes.byref(out_blob),
        ):
            raise ctypes.WinError()
        try:
            _ = in_buf  # Keep the backing buffer alive for the API call.
            return _bytes_from_blob(out_blob)
        finally:
            if out_blob.pbData:
                _kernel32.LocalFree(out_blob.pbData)


    def _dpapi_unprotect(data: bytes) -> bytes:
        in_blob, in_buf = _blob_from_bytes(data)
        out_blob = _DATA_BLOB()
        if not _crypt32.CryptUnprotectData(
            ctypes.byref(in_blob),
            None,
            None,
            None,
            None,
            _CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(out_blob),
        ):
            raise ctypes.WinError()
        try:
            _ = in_buf  # Keep the backing buffer alive for the API call.
            return _bytes_from_blob(out_blob)
        finally:
            if out_blob.pbData:
                _kernel32.LocalFree(out_blob.pbData)


else:

    def _dpapi_protect(data: bytes, *, machine_scope: bool) -> bytes:
        raise SecureStorageError("DPAPI is only available on Windows")


    def _dpapi_unprotect(data: bytes) -> bytes:
        raise SecureStorageError("DPAPI is only available on Windows")


def _load_master_key() -> bytes:
    global _MASTER_KEY_CACHE
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cache_key = str(MASTER_KEY_FILE.resolve())
    if _MASTER_KEY_CACHE and _MASTER_KEY_CACHE[0] == cache_key:
        return _MASTER_KEY_CACHE[1]
    if not MASTER_KEY_FILE.exists():
        raw_key = os.urandom(32)
        if _is_windows():
            envelope = _master_envelope_for_windows(
                _dpapi_protect(raw_key, machine_scope=True),
                provider="dpapi-machine",
            )
        else:
            secret = _get_storage_secret()
            if secret:
                envelope = _master_envelope_for_passphrase(raw_key, secret)
            elif _raw_fallback_allowed():
                envelope = _master_envelope_for_fallback(raw_key)
            else:
                raise SecureStorageError(
                    "Non-Windows secure storage requires MESH_SECURE_STORAGE_SECRET "
                    "or explicit MESH_ALLOW_RAW_SECURE_STORAGE_FALLBACK=true"
                )
        _atomic_write_text(MASTER_KEY_FILE, json.dumps(envelope, indent=2), encoding="utf-8")
        _MASTER_KEY_CACHE = (cache_key, raw_key)
        return raw_key

    try:
        payload = json.loads(MASTER_KEY_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SecureStorageError(f"Failed to load secure storage master key: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("kind") != _MASTER_KIND:
        raise SecureStorageError("Malformed secure storage master key envelope")
    provider = str(payload.get("provider", "") or "").lower()
    if provider in {"dpapi", "dpapi-user", "dpapi-machine"}:
        try:
            raw_key = _dpapi_unprotect(_unb64(payload.get("protected_key")))
            _MASTER_KEY_CACHE = (cache_key, raw_key)
            return raw_key
        except Exception as exc:
            raise SecureStorageError(f"Failed to unwrap DPAPI master key: {exc}") from exc
    if provider == "passphrase":
        secret = _get_storage_secret()
        if not secret:
            raise SecureStorageError(
                "Passphrase-protected master key exists but MESH_SECURE_STORAGE_SECRET is not set"
            )
        try:
            raw_key = _passphrase_unwrap(payload, secret)
            _MASTER_KEY_CACHE = (cache_key, raw_key)
            return raw_key
        except Exception as exc:
            raise SecureStorageError(f"Failed to unwrap passphrase-protected master key: {exc}") from exc
    if provider == "raw":
        if not _raw_fallback_allowed():
            # Migration path: if a storage secret is now available, rewrap the raw key
            secret = _get_storage_secret()
            if secret:
                raw_key = _unb64(payload.get("key"))
                envelope = _master_envelope_for_passphrase(raw_key, secret)
                _atomic_write_text(MASTER_KEY_FILE, json.dumps(envelope, indent=2), encoding="utf-8")
                logger.info("Migrated master key from raw to passphrase-protected envelope")
                _MASTER_KEY_CACHE = (cache_key, raw_key)
                return raw_key
            raise SecureStorageError(
                "Raw secure-storage envelopes are disabled outside debug/test unless explicitly opted in. "
                "Set MESH_SECURE_STORAGE_SECRET to migrate to passphrase-protected storage."
            )
        raw_key = _unb64(payload.get("key"))
        _MASTER_KEY_CACHE = (cache_key, raw_key)
        return raw_key
    raise SecureStorageError(f"Unsupported secure storage provider: {provider}")


def _domain_key_file(domain: str, *, base_dir: str | Path | None = None) -> Path:
    domain_name = _normalize_domain_name(domain)
    return (_domain_key_dir(base_dir) / f"{domain_name}.key").resolve()


def _load_domain_key(
    domain: str,
    *,
    create_if_missing: bool = True,
    base_dir: str | Path | None = None,
) -> bytes:
    domain_name = _normalize_domain_name(domain)
    root = _storage_root(base_dir)
    root.mkdir(parents=True, exist_ok=True)
    key_file = _domain_key_file(domain_name, base_dir=base_dir)
    cache_key = str(key_file)
    cache_slot = f"{root}::{domain_name}"
    cached = _DOMAIN_KEY_CACHE.get(cache_slot)
    if cached and cached[0] == cache_key:
        return cached[1]
    if not key_file.exists():
        if not create_if_missing:
            raise SecureStorageError(f"Domain key not found for {domain_name}")
        raw_key = os.urandom(32)
        if _is_windows():
            envelope = _domain_key_envelope_for_windows(
                domain_name,
                _dpapi_protect(raw_key, machine_scope=True),
                provider="dpapi-machine",
            )
        else:
            secret = _get_storage_secret()
            if secret:
                envelope = _domain_key_envelope_for_passphrase(domain_name, raw_key, secret)
            elif _raw_fallback_allowed():
                envelope = _domain_key_envelope_for_fallback(domain_name, raw_key)
            else:
                raise SecureStorageError(
                    "Non-Windows secure storage requires MESH_SECURE_STORAGE_SECRET "
                    "or explicit MESH_ALLOW_RAW_SECURE_STORAGE_FALLBACK=true"
                )
        _atomic_write_text(key_file, json.dumps(envelope, indent=2), encoding="utf-8")
        _DOMAIN_KEY_CACHE[cache_slot] = (cache_key, raw_key)
        return raw_key

    try:
        payload = json.loads(key_file.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SecureStorageError(f"Failed to load domain key for {domain_name}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("kind") != _DOMAIN_KEY_KIND:
        raise SecureStorageError(f"Malformed domain key envelope for {domain_name}")
    if str(payload.get("domain", "") or "").strip().lower() != domain_name:
        raise SecureStorageError(f"Domain key envelope mismatch for {domain_name}")
    provider = str(payload.get("provider", "") or "").lower()
    if provider in {"dpapi", "dpapi-user", "dpapi-machine"}:
        try:
            raw_key = _dpapi_unprotect(_unb64(payload.get("protected_key")))
            _DOMAIN_KEY_CACHE[cache_slot] = (cache_key, raw_key)
            return raw_key
        except Exception as exc:
            raise SecureStorageError(f"Failed to unwrap domain key for {domain_name}: {exc}") from exc
    if provider == "passphrase":
        secret = _get_storage_secret()
        if not secret:
            raise SecureStorageError(
                f"Passphrase-protected domain key exists for {domain_name} but MESH_SECURE_STORAGE_SECRET is not set"
            )
        try:
            raw_key = _passphrase_unwrap(payload, secret)
            _DOMAIN_KEY_CACHE[cache_slot] = (cache_key, raw_key)
            return raw_key
        except Exception as exc:
            raise SecureStorageError(
                f"Failed to unwrap passphrase-protected domain key for {domain_name}: {exc}"
            ) from exc
    if provider == "raw":
        if not _raw_fallback_allowed():
            secret = _get_storage_secret()
            if secret:
                raw_key = _unb64(payload.get("key"))
                envelope = _domain_key_envelope_for_passphrase(domain_name, raw_key, secret)
                _atomic_write_text(key_file, json.dumps(envelope, indent=2), encoding="utf-8")
                logger.info("Migrated domain key %s from raw to passphrase-protected envelope", domain_name)
                _DOMAIN_KEY_CACHE[cache_slot] = (cache_key, raw_key)
                return raw_key
            raise SecureStorageError(
                "Raw secure-storage envelopes are disabled outside debug/test unless explicitly opted in. "
                "Set MESH_SECURE_STORAGE_SECRET to migrate to passphrase-protected storage."
            )
        raw_key = _unb64(payload.get("key"))
        _DOMAIN_KEY_CACHE[cache_slot] = (cache_key, raw_key)
        return raw_key
    raise SecureStorageError(f"Unsupported domain key provider for {domain_name}: {provider}")


def _derive_legacy_domain_key(domain: str) -> bytes:
    domain_name = _normalize_domain_name(domain)
    return hmac.new(
        _load_master_key(),
        domain_name.encode("utf-8"),
        hashlib.sha256,
    ).digest()


def _domain_file_path(domain: str, filename: str, *, base_dir: str | Path | None = None) -> Path:
    domain_name = _normalize_domain_name(domain)
    file_name = str(filename or "").strip()
    if not file_name:
        raise SecureStorageError("filename required for domain-scoped storage")
    if not re.fullmatch(r"[a-z0-9_.]+", file_name):
        raise SecureStorageError(f"invalid filename: {file_name!r}")
    root = _storage_root(base_dir)
    resolved = (root / domain_name / file_name).resolve()
    if not str(resolved).startswith(str(root)):
        raise SecureStorageError("domain storage path traversal rejected")
    return resolved


def rotate_storage_secret(
    old_secret: str,
    new_secret: str,
    *,
    base_dir: str | Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Rewrap all passphrase-protected key envelopes from *old_secret* to *new_secret*.

    This is an explicit operator action — it never runs automatically at startup.
    It fails closed: if *old_secret* cannot unwrap any envelope, or *new_secret*
    is empty, no files are modified.  On success every passphrase envelope under
    *base_dir* is atomically replaced with a fresh wrap using *new_secret*.

    When *dry_run* is ``True``, Phase 1 validation runs (proving the old secret
    can unwrap every envelope) but no files are written — useful for pre-flight
    checks before committing to a rotation.

    Before writing, ``.bak`` copies of every envelope about to be rewritten are
    created so that a mid-rotation crash leaves recoverable backups on disk.

    Returns a summary dict with ``ok``, ``rotated`` (list of rotated file names),
    ``skipped`` (list of non-passphrase envelopes left untouched), and optionally
    ``dry_run`` and ``backups``.
    """
    if not old_secret or not old_secret.strip():
        raise SecureStorageError("Old secret is required for rotation")
    if not new_secret or not new_secret.strip():
        raise SecureStorageError("New secret is required for rotation")
    old_secret = old_secret.strip()
    new_secret = new_secret.strip()
    if old_secret == new_secret:
        raise SecureStorageError("New secret must differ from old secret")

    root = _storage_root(base_dir)
    master_key_file = root / MASTER_KEY_FILE.name if base_dir is not None else MASTER_KEY_FILE

    # Phase 1: Validate — unwrap everything with old_secret, fail before writing anything.
    pending: list[tuple[Path, dict[str, Any], bytes]] = []  # (path, envelope, raw_key)
    skipped: list[str] = []

    # Master key
    if master_key_file.exists():
        try:
            envelope = json.loads(master_key_file.read_text(encoding="utf-8"))
        except Exception as exc:
            raise SecureStorageError(f"Cannot parse master key envelope: {exc}") from exc
        provider = str(envelope.get("provider", "") or "").lower()
        if provider == "passphrase":
            try:
                raw_key = _passphrase_unwrap(envelope, old_secret)
            except Exception as exc:
                raise SecureStorageError(
                    f"Old secret cannot unwrap master key — aborting rotation: {exc}"
                ) from exc
            pending.append((master_key_file, envelope, raw_key))
        else:
            skipped.append(master_key_file.name)

    # Domain keys
    dk_dir = _domain_key_dir(base_dir)
    if dk_dir.exists():
        for key_file in sorted(dk_dir.glob("*.key")):
            try:
                envelope = json.loads(key_file.read_text(encoding="utf-8"))
            except Exception as exc:
                raise SecureStorageError(
                    f"Cannot parse domain key envelope {key_file.name}: {exc}"
                ) from exc
            provider = str(envelope.get("provider", "") or "").lower()
            if provider == "passphrase":
                try:
                    raw_key = _passphrase_unwrap(envelope, old_secret)
                except Exception as exc:
                    raise SecureStorageError(
                        f"Old secret cannot unwrap domain key {key_file.name} — aborting rotation: {exc}"
                    ) from exc
                pending.append((key_file, envelope, raw_key))
            else:
                skipped.append(key_file.name)

    if not pending:
        raise SecureStorageError("No passphrase-protected envelopes found to rotate")

    would_rotate = [p.name for p, _e, _k in pending]

    if dry_run:
        logger.info("Dry-run rotation: %d envelope(s) would rotate: %s", len(would_rotate), ", ".join(would_rotate))
        return {"ok": True, "dry_run": True, "would_rotate": would_rotate, "skipped": skipped}

    # Phase 2a: Create .bak copies of every envelope we are about to rewrite.
    backups: list[str] = []
    for path, _envelope, _raw_key in pending:
        bak_path = path.with_suffix(path.suffix + ".bak")
        try:
            shutil.copy2(str(path), str(bak_path))
            backups.append(bak_path.name)
        except Exception as exc:
            raise SecureStorageError(
                f"Cannot create backup {bak_path.name} — aborting rotation: {exc}"
            ) from exc

    # Phase 2b: Rewrap and write atomically per file.
    rotated: list[str] = []
    for path, envelope, raw_key in pending:
        kind = str(envelope.get("kind", "") or "")
        if kind == _MASTER_KIND:
            new_envelope = _master_envelope_for_passphrase(raw_key, new_secret)
        elif kind == _DOMAIN_KEY_KIND:
            domain = str(envelope.get("domain", "") or "")
            new_envelope = _domain_key_envelope_for_passphrase(domain, raw_key, new_secret)
        else:
            raise SecureStorageError(f"Unexpected envelope kind during rotation: {kind}")
        _atomic_write_text(path, json.dumps(new_envelope, indent=2), encoding="utf-8")
        rotated.append(path.name)

    # Invalidate caches so next load uses the new envelope.
    global _MASTER_KEY_CACHE
    _MASTER_KEY_CACHE = None
    _DOMAIN_KEY_CACHE.clear()

    logger.info("Rotated storage secret for %d envelope(s): %s", len(rotated), ", ".join(rotated))
    return {"ok": True, "rotated": rotated, "skipped": skipped, "backups": backups}


def write_secure_json(path: str | Path, payload: Any) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    master_key = _load_master_key()
    nonce = os.urandom(12)
    ciphertext = AESGCM(master_key).encrypt(nonce, _stable_json(payload), _envelope_aad(file_path))
    envelope = _secure_envelope(file_path, nonce, ciphertext)
    _atomic_write_text(file_path, json.dumps(envelope, indent=2), encoding="utf-8")


def read_secure_json(path: str | Path, default_factory: Callable[[], T]) -> T:
    file_path = Path(path)
    if not file_path.exists():
        return default_factory()

    try:
        raw = json.loads(file_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SecureStorageError(f"Failed to parse secure JSON {file_path.name}: {exc}") from exc

    if _is_secure_envelope(raw):
        master_key = _load_master_key()
        try:
            plaintext = AESGCM(master_key).decrypt(
                _unb64(raw.get("nonce")),
                _unb64(raw.get("ciphertext")),
                _envelope_aad(file_path),
            )
        except Exception as exc:
            raise SecureStorageError(f"Failed to decrypt secure JSON {file_path.name}: {exc}") from exc
        try:
            return json.loads(plaintext.decode("utf-8"))
        except Exception as exc:
            raise SecureStorageError(
                f"Failed to decode secure JSON payload {file_path.name}: {exc}"
            ) from exc

    # Legacy plaintext JSON: migrate in place on first successful read.
    migrated = raw if isinstance(raw, (dict, list)) else default_factory()
    write_secure_json(file_path, migrated)
    return migrated


def write_domain_json(
    domain: str,
    filename: str,
    payload: Any,
    *,
    base_dir: str | Path | None = None,
) -> Path:
    file_path = _domain_file_path(domain, filename, base_dir=base_dir)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    nonce = os.urandom(12)
    domain_name = _normalize_domain_name(domain)
    ciphertext = AESGCM(_load_domain_key(domain_name, base_dir=base_dir)).encrypt(
        nonce,
        _stable_json(payload),
        _domain_aad(domain_name, file_path.name),
    )
    envelope = _secure_envelope(file_path, nonce, ciphertext)
    _atomic_write_text(file_path, json.dumps(envelope, indent=2), encoding="utf-8")
    return file_path


def read_domain_json(
    domain: str,
    filename: str,
    default_factory: Callable[[], T],
    *,
    base_dir: str | Path | None = None,
) -> T:
    file_path = _domain_file_path(domain, filename, base_dir=base_dir)
    domain_name = _normalize_domain_name(domain)
    if not file_path.exists():
        return default_factory()
    try:
        raw = json.loads(file_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SecureStorageError(f"Failed to parse domain JSON {file_path.name}: {exc}") from exc

    if _is_secure_envelope(raw):
        aad = _domain_aad(domain_name, file_path.name)
        plaintext: bytes | None = None
        used_legacy_key = False
        used_master_key = False
        try:
            current_key = _load_domain_key(domain_name, create_if_missing=False, base_dir=base_dir)
        except SecureStorageError:
            current_key = None
        if current_key is not None:
            try:
                plaintext = AESGCM(current_key).decrypt(
                    _unb64(raw.get("nonce")),
                    _unb64(raw.get("ciphertext")),
                    aad,
                )
            except Exception:
                plaintext = None
        if plaintext is None:
            try:
                plaintext = AESGCM(_derive_legacy_domain_key(domain_name)).decrypt(
                    _unb64(raw.get("nonce")),
                    _unb64(raw.get("ciphertext")),
                    aad,
                )
                used_legacy_key = True
            except Exception as exc:
                try:
                    plaintext = AESGCM(_load_master_key()).decrypt(
                        _unb64(raw.get("nonce")),
                        _unb64(raw.get("ciphertext")),
                        _envelope_aad(file_path),
                    )
                    used_master_key = True
                except Exception:
                    raise SecureStorageError(
                        f"Failed to decrypt domain JSON {file_path.name}: {exc}"
                    ) from exc
        try:
            decoded = json.loads(plaintext.decode("utf-8"))
        except Exception as exc:
            raise SecureStorageError(
                f"Failed to decode domain JSON payload {file_path.name}: {exc}"
            ) from exc
        if used_legacy_key or used_master_key:
            write_domain_json(domain_name, file_path.name, decoded, base_dir=base_dir)
        return decoded

    migrated = raw if isinstance(raw, (dict, list)) else default_factory()
    write_domain_json(domain_name, file_path.name, migrated, base_dir=base_dir)
    return migrated
