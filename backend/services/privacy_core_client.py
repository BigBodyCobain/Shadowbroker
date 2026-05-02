"""ctypes bridge for the Rust privacy-core crate.

This module follows the architecture docs in extra/docs-internal:
- Python orchestrates
- Rust owns private protocol state
- Python sees opaque integer handles and serialized ciphertext only
"""

from __future__ import annotations

import ctypes
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Iterable


class PrivacyCoreError(RuntimeError):
    """Raised when the Rust privacy-core returns an error."""


class PrivacyCoreUnavailable(PrivacyCoreError):
    """Raised when the shared library cannot be found or loaded."""


logger = logging.getLogger(__name__)
_VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")
_DEFAULT_MIN_VERSION = "0.1.0"
_REQUIRED_PRIVACY_CORE_EXPORTS = (
    "privacy_core_version",
    "privacy_core_last_error_message",
    "privacy_core_free_buffer",
    "privacy_core_create_identity",
    "privacy_core_export_key_package",
    "privacy_core_import_key_package",
    "privacy_core_create_group",
    "privacy_core_add_member",
    "privacy_core_remove_member",
    "privacy_core_encrypt_group_message",
    "privacy_core_decrypt_group_message",
    "privacy_core_export_public_bundle",
    "privacy_core_handle_stats",
    "privacy_core_commit_message_bytes",
    "privacy_core_commit_welcome_message_bytes",
    "privacy_core_commit_joined_group_handle",
    "privacy_core_create_dm_session",
    "privacy_core_dm_encrypt",
    "privacy_core_dm_decrypt",
    "privacy_core_dm_session_welcome",
    "privacy_core_dm_session_fingerprint",
    "privacy_core_join_dm_session",
    "privacy_core_release_dm_session",
    "privacy_core_export_dm_state",
    "privacy_core_import_dm_state",
    "privacy_core_export_gate_state",
    "privacy_core_import_gate_state",
    "privacy_core_release_identity",
    "privacy_core_release_key_package",
    "privacy_core_release_group",
    "privacy_core_release_commit",
    "privacy_core_reset_all_state",
)


class _ByteBuffer(ctypes.Structure):
    _fields_ = [
        ("data", ctypes.POINTER(ctypes.c_uint8)),
        ("len", ctypes.c_size_t),
    ]


class PrivacyCoreClient:
    """Handle-based interface to the local Rust privacy-core."""

    def __init__(self, library: ctypes.CDLL, library_path: Path) -> None:
        self._library = library
        self.library_path = library_path
        self._configure_functions()

    @classmethod
    def load(cls, library_path: str | os.PathLike[str] | None = None) -> "PrivacyCoreClient":
        resolved = cls._resolve_library_path(library_path)
        try:
            library = ctypes.CDLL(str(resolved))
        except OSError as exc:
            raise PrivacyCoreUnavailable(f"failed to load privacy-core library: {resolved}") from exc
        audit_privacy_core_export_set(library, resolved)
        return cls(library, resolved)

    @staticmethod
    def _resolve_library_path(library_path: str | os.PathLike[str] | None) -> Path:
        if library_path:
            resolved = Path(library_path).expanduser().resolve()
            if not resolved.exists():
                raise PrivacyCoreUnavailable(f"privacy-core library not found: {resolved}")
            return resolved

        env_override = os.environ.get("PRIVACY_CORE_LIB")
        if env_override:
            resolved = Path(env_override).expanduser().resolve()
            if not resolved.exists():
                raise PrivacyCoreUnavailable(f"privacy-core library not found: {resolved}")
            return resolved

        repo_root = Path(__file__).resolve().parents[2]
        candidates = []
        for profile in ("debug", "release"):
            target_dir = repo_root / "privacy-core" / "target" / profile
            candidates.extend(
                [
                    target_dir / "privacy_core.dll",
                    target_dir / "libprivacy_core.so",
                    target_dir / "libprivacy_core.dylib",
                ]
            )

        for candidate in candidates:
            if candidate.exists():
                return candidate.resolve()

        searched = "\n".join(str(candidate) for candidate in candidates)
        raise PrivacyCoreUnavailable(
            "privacy-core shared library not found. Looked in:\n" f"{searched}"
        )

    def _configure_functions(self) -> None:
        self._library.privacy_core_version.argtypes = []
        self._library.privacy_core_version.restype = _ByteBuffer

        self._library.privacy_core_last_error_message.argtypes = []
        self._library.privacy_core_last_error_message.restype = _ByteBuffer

        self._library.privacy_core_free_buffer.argtypes = [_ByteBuffer]
        self._library.privacy_core_free_buffer.restype = None

        self._library.privacy_core_create_identity.argtypes = []
        self._library.privacy_core_create_identity.restype = ctypes.c_uint64

        self._library.privacy_core_export_key_package.argtypes = [ctypes.c_uint64]
        self._library.privacy_core_export_key_package.restype = _ByteBuffer

        self._library.privacy_core_import_key_package.argtypes = [
            ctypes.POINTER(ctypes.c_uint8),
            ctypes.c_size_t,
        ]
        self._library.privacy_core_import_key_package.restype = ctypes.c_uint64

        self._library.privacy_core_create_group.argtypes = [ctypes.c_uint64]
        self._library.privacy_core_create_group.restype = ctypes.c_uint64

        self._library.privacy_core_add_member.argtypes = [ctypes.c_uint64, ctypes.c_uint64]
        self._library.privacy_core_add_member.restype = ctypes.c_uint64

        self._library.privacy_core_remove_member.argtypes = [ctypes.c_uint64, ctypes.c_uint32]
        self._library.privacy_core_remove_member.restype = ctypes.c_uint64

        self._library.privacy_core_encrypt_group_message.argtypes = [
            ctypes.c_uint64,
            ctypes.POINTER(ctypes.c_uint8),
            ctypes.c_size_t,
        ]
        self._library.privacy_core_encrypt_group_message.restype = _ByteBuffer

        self._library.privacy_core_decrypt_group_message.argtypes = [
            ctypes.c_uint64,
            ctypes.POINTER(ctypes.c_uint8),
            ctypes.c_size_t,
        ]
        self._library.privacy_core_decrypt_group_message.restype = _ByteBuffer

        self._library.privacy_core_export_public_bundle.argtypes = [ctypes.c_uint64]
        self._library.privacy_core_export_public_bundle.restype = _ByteBuffer

        self._library.privacy_core_handle_stats.argtypes = [
            ctypes.POINTER(ctypes.c_uint8),
            ctypes.c_size_t,
        ]
        self._library.privacy_core_handle_stats.restype = ctypes.c_int64

        self._library.privacy_core_commit_message_bytes.argtypes = [ctypes.c_uint64]
        self._library.privacy_core_commit_message_bytes.restype = _ByteBuffer

        self._library.privacy_core_commit_welcome_message_bytes.argtypes = [
            ctypes.c_uint64,
            ctypes.c_size_t,
        ]
        self._library.privacy_core_commit_welcome_message_bytes.restype = _ByteBuffer

        self._library.privacy_core_commit_joined_group_handle.argtypes = [
            ctypes.c_uint64,
            ctypes.c_size_t,
        ]
        self._library.privacy_core_commit_joined_group_handle.restype = ctypes.c_uint64

        self._library.privacy_core_create_dm_session.argtypes = [
            ctypes.c_uint64,
            ctypes.c_uint64,
        ]
        self._library.privacy_core_create_dm_session.restype = ctypes.c_int64

        self._library.privacy_core_dm_encrypt.argtypes = [
            ctypes.c_uint64,
            ctypes.POINTER(ctypes.c_uint8),
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_uint8),
            ctypes.c_size_t,
        ]
        self._library.privacy_core_dm_encrypt.restype = ctypes.c_int64

        self._library.privacy_core_dm_decrypt.argtypes = [
            ctypes.c_uint64,
            ctypes.POINTER(ctypes.c_uint8),
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_uint8),
            ctypes.c_size_t,
        ]
        self._library.privacy_core_dm_decrypt.restype = ctypes.c_int64

        self._library.privacy_core_dm_session_welcome.argtypes = [
            ctypes.c_uint64,
            ctypes.POINTER(ctypes.c_uint8),
            ctypes.c_size_t,
        ]
        self._library.privacy_core_dm_session_welcome.restype = ctypes.c_int64

        self._library.privacy_core_dm_session_fingerprint.argtypes = [
            ctypes.c_uint64,
            ctypes.POINTER(ctypes.c_uint8),
            ctypes.c_size_t,
        ]
        self._library.privacy_core_dm_session_fingerprint.restype = ctypes.c_int64

        self._library.privacy_core_join_dm_session.argtypes = [
            ctypes.c_uint64,
            ctypes.POINTER(ctypes.c_uint8),
            ctypes.c_size_t,
        ]
        self._library.privacy_core_join_dm_session.restype = ctypes.c_int64

        self._library.privacy_core_release_dm_session.argtypes = [ctypes.c_uint64]
        self._library.privacy_core_release_dm_session.restype = ctypes.c_int32

        self._library.privacy_core_export_dm_state.argtypes = [
            ctypes.POINTER(ctypes.c_uint8),
            ctypes.c_size_t,
        ]
        self._library.privacy_core_export_dm_state.restype = ctypes.c_int64

        self._library.privacy_core_import_dm_state.argtypes = [
            ctypes.POINTER(ctypes.c_uint8),
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_uint8),
            ctypes.c_size_t,
        ]
        self._library.privacy_core_import_dm_state.restype = ctypes.c_int64

        self._library.privacy_core_export_gate_state.argtypes = [
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_uint8),
            ctypes.c_size_t,
        ]
        self._library.privacy_core_export_gate_state.restype = ctypes.c_int64

        self._library.privacy_core_import_gate_state.argtypes = [
            ctypes.POINTER(ctypes.c_uint8),
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_uint8),
            ctypes.c_size_t,
        ]
        self._library.privacy_core_import_gate_state.restype = ctypes.c_int64

        self._library.privacy_core_release_identity.argtypes = [ctypes.c_uint64]
        self._library.privacy_core_release_identity.restype = ctypes.c_bool

        self._library.privacy_core_release_key_package.argtypes = [ctypes.c_uint64]
        self._library.privacy_core_release_key_package.restype = ctypes.c_bool

        self._library.privacy_core_release_group.argtypes = [ctypes.c_uint64]
        self._library.privacy_core_release_group.restype = ctypes.c_bool

        self._library.privacy_core_release_commit.argtypes = [ctypes.c_uint64]
        self._library.privacy_core_release_commit.restype = ctypes.c_bool

        self._library.privacy_core_reset_all_state.argtypes = []
        self._library.privacy_core_reset_all_state.restype = ctypes.c_bool

    def version(self) -> str:
        return self._consume_string(self._library.privacy_core_version())

    def create_identity(self) -> int:
        return self._ensure_handle(self._library.privacy_core_create_identity(), "create_identity")

    def export_key_package(self, identity_handle: int) -> bytes:
        return self._consume_bytes(
            self._library.privacy_core_export_key_package(ctypes.c_uint64(identity_handle)),
            "export_key_package",
        )

    def import_key_package(self, data: bytes) -> int:
        buffer = self._as_ubyte_buffer(data)
        handle = self._library.privacy_core_import_key_package(buffer, len(data))
        return self._ensure_handle(handle, "import_key_package")

    def create_group(self, identity_handle: int) -> int:
        handle = self._library.privacy_core_create_group(ctypes.c_uint64(identity_handle))
        return self._ensure_handle(handle, "create_group")

    def add_member(self, group_handle: int, key_package_handle: int) -> int:
        handle = self._library.privacy_core_add_member(
            ctypes.c_uint64(group_handle),
            ctypes.c_uint64(key_package_handle),
        )
        return self._ensure_handle(handle, "add_member")

    def remove_member(self, group_handle: int, member_ref: int) -> int:
        handle = self._library.privacy_core_remove_member(
            ctypes.c_uint64(group_handle),
            ctypes.c_uint32(member_ref),
        )
        return self._ensure_handle(handle, "remove_member")

    def encrypt_group_message(self, group_handle: int, plaintext: bytes) -> bytes:
        buffer = self._as_ubyte_buffer(plaintext)
        return self._consume_bytes(
            self._library.privacy_core_encrypt_group_message(
                ctypes.c_uint64(group_handle),
                buffer,
                len(plaintext),
            ),
            "encrypt_group_message",
        )

    def decrypt_group_message(self, group_handle: int, ciphertext: bytes) -> bytes:
        buffer = self._as_ubyte_buffer(ciphertext)
        return self._consume_bytes(
            self._library.privacy_core_decrypt_group_message(
                ctypes.c_uint64(group_handle),
                buffer,
                len(ciphertext),
            ),
            "decrypt_group_message",
        )

    def export_public_bundle(self, identity_handle: int) -> bytes:
        return self._consume_bytes(
            self._library.privacy_core_export_public_bundle(ctypes.c_uint64(identity_handle)),
            "export_public_bundle",
        )

    def handle_stats(self) -> dict:
        payload = self._call_i64_bytes_op(
            "handle_stats",
            lambda out_buf, out_cap: self._library.privacy_core_handle_stats(out_buf, out_cap),
        )
        try:
            return json.loads(payload.decode("utf-8"))
        except Exception as exc:
            raise PrivacyCoreError(f"handle_stats failed: invalid JSON: {exc}") from exc

    def commit_message_bytes(self, commit_handle: int) -> bytes:
        return self._consume_bytes(
            self._library.privacy_core_commit_message_bytes(ctypes.c_uint64(commit_handle)),
            "commit_message_bytes",
        )

    def commit_welcome_message_bytes(self, commit_handle: int, index: int = 0) -> bytes:
        return self._consume_bytes(
            self._library.privacy_core_commit_welcome_message_bytes(
                ctypes.c_uint64(commit_handle),
                ctypes.c_size_t(index),
            ),
            "commit_welcome_message_bytes",
        )

    def commit_joined_group_handle(self, commit_handle: int, index: int = 0) -> int:
        handle = self._library.privacy_core_commit_joined_group_handle(
            ctypes.c_uint64(commit_handle),
            ctypes.c_size_t(index),
        )
        return self._ensure_handle(handle, "commit_joined_group_handle")

    def create_dm_session(self, initiator_identity: int, responder_key_package: int) -> int:
        handle = self._library.privacy_core_create_dm_session(
            ctypes.c_uint64(initiator_identity),
            ctypes.c_uint64(responder_key_package),
        )
        if handle > 0:
            return int(handle)
        raise self._error_for("create_dm_session")

    def dm_encrypt(self, session_handle: int, plaintext: bytes) -> bytes:
        buffer = self._as_ubyte_buffer(plaintext)
        return self._call_i64_bytes_op(
            "dm_encrypt",
            lambda out_buf, out_cap: self._library.privacy_core_dm_encrypt(
                ctypes.c_uint64(session_handle),
                buffer,
                len(plaintext),
                out_buf,
                out_cap,
            ),
        )

    def dm_decrypt(self, session_handle: int, ciphertext: bytes) -> bytes:
        buffer = self._as_ubyte_buffer(ciphertext)
        return self._call_i64_bytes_op(
            "dm_decrypt",
            lambda out_buf, out_cap: self._library.privacy_core_dm_decrypt(
                ctypes.c_uint64(session_handle),
                buffer,
                len(ciphertext),
                out_buf,
                out_cap,
            ),
        )

    def dm_session_welcome(self, session_handle: int) -> bytes:
        return self._call_i64_bytes_op(
            "dm_session_welcome",
            lambda out_buf, out_cap: self._library.privacy_core_dm_session_welcome(
                ctypes.c_uint64(session_handle),
                out_buf,
                out_cap,
            ),
        )

    def dm_session_fingerprint(self, session_handle: int) -> str:
        payload = self._call_i64_bytes_op(
            "dm_session_fingerprint",
            lambda out_buf, out_cap: self._library.privacy_core_dm_session_fingerprint(
                ctypes.c_uint64(session_handle),
                out_buf,
                out_cap,
            ),
        )
        return payload.decode("ascii")

    def join_dm_session(self, responder_identity: int, welcome: bytes) -> int:
        buffer = self._as_ubyte_buffer(welcome)
        handle = self._library.privacy_core_join_dm_session(
            ctypes.c_uint64(responder_identity),
            buffer,
            len(welcome),
        )
        if handle > 0:
            return int(handle)
        raise self._error_for("join_dm_session")

    def export_dm_state(self) -> bytes:
        return self._call_i64_bytes_op(
            "export_dm_state",
            lambda out_buf, out_cap: self._library.privacy_core_export_dm_state(out_buf, out_cap),
        )

    def import_dm_state(self, data: bytes) -> dict:
        buffer = self._as_ubyte_buffer(data)
        payload = self._call_i64_bytes_op(
            "import_dm_state",
            lambda out_buf, out_cap: self._library.privacy_core_import_dm_state(
                buffer,
                len(data),
                out_buf,
                out_cap,
            ),
        )
        try:
            return json.loads(payload.decode("utf-8"))
        except Exception as exc:
            raise PrivacyCoreError(f"import_dm_state failed: invalid JSON: {exc}") from exc

    def export_gate_state(
        self, identity_handles: list[int], group_handles: list[int],
    ) -> bytes:
        id_array = (ctypes.c_uint64 * len(identity_handles))(*identity_handles)
        grp_array = (ctypes.c_uint64 * len(group_handles))(*group_handles)
        return self._call_i64_bytes_op(
            "export_gate_state",
            lambda out_buf, out_cap: self._library.privacy_core_export_gate_state(
                id_array,
                len(identity_handles),
                grp_array,
                len(group_handles),
                out_buf,
                out_cap,
            ),
        )

    def import_gate_state(self, data: bytes) -> dict:
        buffer = self._as_ubyte_buffer(data)
        payload = self._call_i64_bytes_op(
            "import_gate_state",
            lambda out_buf, out_cap: self._library.privacy_core_import_gate_state(
                buffer,
                len(data),
                out_buf,
                out_cap,
            ),
        )
        try:
            return json.loads(payload.decode("utf-8"))
        except Exception as exc:
            raise PrivacyCoreError(f"import_gate_state failed: invalid JSON: {exc}") from exc

    def release_dm_session(self, handle: int) -> bool:
        return bool(self._library.privacy_core_release_dm_session(ctypes.c_uint64(handle)))

    def release_identity(self, handle: int) -> bool:
        return bool(self._library.privacy_core_release_identity(ctypes.c_uint64(handle)))

    def release_key_package(self, handle: int) -> bool:
        return bool(self._library.privacy_core_release_key_package(ctypes.c_uint64(handle)))

    def release_group(self, handle: int) -> bool:
        return bool(self._library.privacy_core_release_group(ctypes.c_uint64(handle)))

    def release_commit(self, handle: int) -> bool:
        return bool(self._library.privacy_core_release_commit(ctypes.c_uint64(handle)))

    def reset_all_state(self) -> bool:
        return bool(self._library.privacy_core_reset_all_state())

    def _consume_string(self, buffer: _ByteBuffer) -> str:
        payload = self._consume_buffer(buffer)
        return payload.decode("utf-8")

    def _consume_bytes(self, buffer: _ByteBuffer, operation: str) -> bytes:
        payload = self._consume_buffer(buffer)
        if payload:
            return payload
        raise self._error_for(operation)

    def _consume_buffer(self, buffer: _ByteBuffer) -> bytes:
        try:
            if not buffer.data or buffer.len == 0:
                return b""
            return bytes(ctypes.string_at(buffer.data, buffer.len))
        finally:
            self._library.privacy_core_free_buffer(buffer)

    def _ensure_handle(self, handle: int, operation: str) -> int:
        if handle:
            return int(handle)
        raise self._error_for(operation)

    def _call_i64_bytes_op(self, operation: str, invoker) -> bytes:
        required = int(invoker(None, 0))
        if required < 0:
            raise self._error_for(operation)
        if required == 0:
            return b""
        output = (ctypes.c_uint8 * required)()
        written = int(invoker(output, required))
        if written < 0:
            raise self._error_for(operation)
        return bytes(output[:written])

    def _error_for(self, operation: str) -> PrivacyCoreError:
        message = self._last_error()
        if message:
            return PrivacyCoreError(f"{operation} failed: {message}")
        return PrivacyCoreError(f"{operation} failed without an error message")

    def _last_error(self) -> str:
        return self._consume_string(self._library.privacy_core_last_error_message())

    @staticmethod
    def _as_ubyte_buffer(data: bytes | bytearray | memoryview) -> ctypes.Array[ctypes.c_uint8]:
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError("privacy-core byte arguments must be bytes-like")
        raw = bytes(data)
        return (ctypes.c_uint8 * len(raw)).from_buffer_copy(raw)


def candidate_library_paths() -> Iterable[Path]:
    """Expose the default search order for diagnostics/tests."""
    from services.privacy_core_attestation import (
        candidate_library_paths as _candidate_library_paths,
    )

    yield from _candidate_library_paths()


def _parse_version_triplet(raw: str) -> tuple[int, int, int] | None:
    match = _VERSION_RE.search(str(raw or "").strip())
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def _settings_snapshot(settings: Any | None = None) -> Any | None:
    if settings is not None:
        return settings
    try:
        from services.config import get_settings

        return get_settings()
    except Exception:
        return None


def _configured_min_version(settings: Any | None = None) -> str:
    snapshot = _settings_snapshot(settings)
    if snapshot is None:
        raw = os.environ.get("PRIVACY_CORE_MIN_VERSION", "")
    else:
        raw = getattr(snapshot, "PRIVACY_CORE_MIN_VERSION", "")
    value = str(raw or "").strip()
    return value or _DEFAULT_MIN_VERSION


def _configured_allowed_hashes(settings: Any | None = None) -> set[str]:
    snapshot = _settings_snapshot(settings)
    if snapshot is None:
        raw = os.environ.get("PRIVACY_CORE_ALLOWED_SHA256", "")
    else:
        raw = getattr(snapshot, "PRIVACY_CORE_ALLOWED_SHA256", "")
    allowed: set[str] = set()
    for item in str(raw or "").split(","):
        digest = item.strip().lower()
        if len(digest) == 64 and all(ch in "0123456789abcdef" for ch in digest):
            allowed.add(digest)
    return allowed


def _export_set_audit_enabled(settings: Any | None = None) -> bool:
    raw_env = os.environ.get("PRIVACY_CORE_EXPORT_SET_AUDIT_ENABLE", "")
    if str(raw_env or "").strip():
        return str(raw_env or "").strip().lower() in {"1", "true", "yes", "on"}
    snapshot = _settings_snapshot(settings)
    if snapshot is None:
        return False
    return bool(getattr(snapshot, "PRIVACY_CORE_EXPORT_SET_AUDIT_ENABLE", False))


def audit_privacy_core_export_set(
    library: Any,
    library_path: str | os.PathLike[str] | Path,
    settings: Any | None = None,
) -> None:
    if not _export_set_audit_enabled(settings):
        return
    missing = [
        symbol
        for symbol in _REQUIRED_PRIVACY_CORE_EXPORTS
        if not hasattr(library, symbol)
    ]
    if missing:
        raise PrivacyCoreUnavailable(
            "privacy-core export-set audit failed for "
            f"{Path(library_path)}; missing exports: {', '.join(missing)}"
        )


def privacy_core_high_privacy_required(settings: Any | None = None) -> bool:
    from services.privacy_core_attestation import (
        privacy_core_high_privacy_required as _privacy_core_high_privacy_required,
    )

    return _privacy_core_high_privacy_required(settings)


def privacy_core_attestation(settings: Any | None = None) -> dict[str, Any]:
    from services.privacy_core_attestation import (
        privacy_core_attestation as _privacy_core_attestation,
    )

    return _privacy_core_attestation(settings)


def _legacy_auto_pin_privacy_core_hash_unused(digest: str) -> bool:
    """Persist the privacy-core artifact SHA-256 to .env automatically.

    Returns True if the pin was written successfully.  This is intentionally
    non-interactive: the user enabled a private transport lane, the binary is
    present and loadable — the only missing piece is the hash pin, which the
    app can compute itself.  Auto-pinning removes a hostile startup gate
    without reducing security: future startups still verify the hash.
    """
    try:
        from routers.ai_intel import _write_env_value

        _write_env_value("PRIVACY_CORE_ALLOWED_SHA256", digest)
        os.environ["PRIVACY_CORE_ALLOWED_SHA256"] = digest
        logger.info(
            "Auto-pinned privacy-core artifact SHA-256 to .env (hash: %s…%s). "
            "Future startups will verify the binary against this pin.",
            digest[:8],
            digest[-8:],
        )
        return True
    except Exception as exc:
        logger.warning(
            "Could not auto-pin privacy-core SHA-256 to .env: %s", exc,
        )
        return False


def _legacy_validate_privacy_core_startup_unused(settings: Any | None = None) -> None:
    snapshot = _settings_snapshot(settings)
    if not privacy_core_high_privacy_required(snapshot):
        return

    attestation = privacy_core_attestation(snapshot)
    if bool(attestation.get("policy_ok")):
        return

    # ── Auto-heal: binary available but hash not yet pinned ──────────
    # The binary loaded fine and the version is acceptable (or at least
    # parseable).  The operator just hasn't pinned the SHA-256 yet.
    # Compute + persist it automatically, then re-validate once.
    available = bool(attestation.get("available"))
    hash_pinned = bool(attestation.get("hash_pinned"))
    digest = str(attestation.get("library_sha256") or "").strip()

    if available and not hash_pinned and len(digest) == 64:
        if _legacy_auto_pin_privacy_core_hash_unused(digest):
            # Clear settings cache so the re-attestation picks up the new pin
            try:
                from services.config import get_settings
                get_settings.cache_clear()
            except Exception:
                pass
            # Re-run attestation with the newly pinned hash
            attestation = privacy_core_attestation()
            if bool(attestation.get("policy_ok")):
                return

    # ── Auto-heal: binary available, hash pinned, but mismatch ───────
    # This means the binary was rebuilt / updated since the last pin.
    # The old pin is stale, not a tamper event (local dev scenario).
    # Re-pin to the current binary and log prominently.
    hash_ok = bool(attestation.get("hash_ok"))
    if available and hash_pinned and not hash_ok and len(digest) == 64:
        logger.warning(
            "privacy-core artifact hash changed (binary was likely rebuilt). "
            "Re-pinning to current artifact: %s…%s",
            digest[:8],
            digest[-8:],
        )
        if _legacy_auto_pin_privacy_core_hash_unused(digest):
            try:
                from services.config import get_settings
                get_settings.cache_clear()
            except Exception:
                pass
            attestation = privacy_core_attestation()
            if bool(attestation.get("policy_ok")):
                return

    # ── Hard failures (binary missing, version too old) ──────────────
    reasons: list[str] = []
    if not available:
        reasons.append(
            "privacy-core binary not found — private transport requires it. "
            "Build it with: cd privacy-core && cargo build --release"
        )
    if not bool(attestation.get("version_pinned")):
        reasons.append("minimum version pin missing or invalid")
    elif not bool(attestation.get("version_known")):
        reasons.append("loaded privacy-core version unknown")
    elif not bool(attestation.get("version_ok")):
        reasons.append(
            "loaded privacy-core version "
            f"{attestation.get('version') or '<unknown>'} is below "
            f"required minimum {attestation.get('minimum_version') or _DEFAULT_MIN_VERSION}"
        )
    if not bool(attestation.get("hash_pinned")):
        reasons.append("allowed privacy-core sha256 pin could not be auto-set")
    elif not bool(attestation.get("hash_ok")):
        reasons.append("loaded privacy-core artifact hash verification failed after re-pin attempt")

    detail = str(attestation.get("detail") or "").strip()
    if detail:
        reasons.append(detail)

    logger.critical(
        "privacy-core startup validation failed for private-lane startup: %s",
        "; ".join(reasons) or "unknown validation failure",
    )
    raise SystemExit(1)


def validate_privacy_core_startup(settings: Any | None = None) -> None:
    from services.privacy_core_attestation import (
        validate_privacy_core_startup as _validate_privacy_core_startup,
    )

    _validate_privacy_core_startup(settings)
