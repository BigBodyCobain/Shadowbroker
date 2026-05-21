"""Issue #251 (tg12): Tor bundle extraction must refuse symlink and
hardlink members.

The previous extractor checked ``member.name`` against path traversal
but never inspected ``member.linkname``. Python 3.11's ``tarfile``
honors symlinks during ``extractall()``, so a malicious archive could
ship a member named ``innocent.txt`` whose linkname points at an
arbitrary filesystem location. After extraction, reads of innocent.txt
dereference to that location; writes corrupt it.

The fix categorically refuses any link member during extraction.
Tor Expert Bundles never legitimately contain symlinks or hardlinks,
so this is non-disruptive for real updates and a hard stop for hostile
archives.

These tests build synthetic tar archives covering each refused case
and assert ``_extract_tor_bundle_safely`` rejects them.
"""
import io
import os
import stat
import tarfile
from pathlib import Path

import pytest

from services.tor_hidden_service import _extract_tor_bundle_safely


def _build_archive(tmp_path: Path, members: list) -> Path:
    """Write a .tar.gz with the given (name, builder) pairs.

    Each builder is called with the open tarfile and is responsible for
    adding its member however it likes (regular file, symlink, etc.).
    """
    archive = tmp_path / "test_bundle.tar.gz"
    with tarfile.open(str(archive), "w:gz") as tar:
        for name, builder in members:
            builder(tar, name)
    return archive


def _add_regular_file(tar: tarfile.TarFile, name: str, payload: bytes = b"hello") -> None:
    info = tarfile.TarInfo(name)
    info.size = len(payload)
    info.mode = 0o644
    info.type = tarfile.REGTYPE
    tar.addfile(info, io.BytesIO(payload))


def _add_symlink(tar: tarfile.TarFile, name: str, linkname: str) -> None:
    info = tarfile.TarInfo(name)
    info.size = 0
    info.type = tarfile.SYMTYPE
    info.linkname = linkname
    info.mode = 0o777
    tar.addfile(info)


def _add_hardlink(tar: tarfile.TarFile, name: str, linkname: str) -> None:
    info = tarfile.TarInfo(name)
    info.size = 0
    info.type = tarfile.LNKTYPE
    info.linkname = linkname
    info.mode = 0o644
    tar.addfile(info)


def _add_fifo(tar: tarfile.TarFile, name: str) -> None:
    info = tarfile.TarInfo(name)
    info.type = tarfile.FIFOTYPE
    info.mode = 0o644
    tar.addfile(info)


def test_clean_archive_extracts_successfully(tmp_path):
    """A normal archive with only regular files extracts fine."""
    install_dir = tmp_path / "install"
    install_dir.mkdir()

    def add_normal(tar, name):
        _add_regular_file(tar, name, b"clean content")

    archive = _build_archive(
        tmp_path,
        [
            ("tor/tor.exe", add_normal),
            ("tor/data/geoip", add_normal),
        ],
    )
    assert _extract_tor_bundle_safely(archive, install_dir) is True
    assert (install_dir / "tor" / "tor.exe").is_file()
    assert (install_dir / "tor" / "data" / "geoip").is_file()


def test_symlink_member_is_rejected(tmp_path, caplog):
    """Issue #251 core regression: symlink members are refused."""
    install_dir = tmp_path / "install"
    install_dir.mkdir()

    archive = _build_archive(
        tmp_path,
        [
            ("tor/innocent.txt", lambda t, n: _add_symlink(t, n, "/etc/passwd")),
        ],
    )

    import logging

    with caplog.at_level(logging.ERROR):
        result = _extract_tor_bundle_safely(archive, install_dir)

    assert result is False
    # No file should have been created
    assert not (install_dir / "tor" / "innocent.txt").exists()
    # Log should explain why
    assert any(
        "symlinks/hardlinks are not allowed" in rec.getMessage()
        for rec in caplog.records
    )


def test_hardlink_member_is_rejected(tmp_path):
    """Hardlinks are refused for the same reason as symlinks."""
    install_dir = tmp_path / "install"
    install_dir.mkdir()

    archive = _build_archive(
        tmp_path,
        [
            ("tor/regular.txt", lambda t, n: _add_regular_file(t, n)),
            ("tor/sneaky.txt", lambda t, n: _add_hardlink(t, n, "regular.txt")),
        ],
    )
    assert _extract_tor_bundle_safely(archive, install_dir) is False
    # The whole extraction is refused even though only one member is bad.
    assert not (install_dir / "tor" / "regular.txt").exists()


def test_symlink_with_relative_target_still_rejected(tmp_path):
    """Even a relative symlink target inside the install dir is refused.

    We don't allow symlinks at all — there is no legitimate Tor bundle
    use case for them, and an attacker can chain link redirections in
    ways the path-resolution check is poor at catching.
    """
    install_dir = tmp_path / "install"
    install_dir.mkdir()

    archive = _build_archive(
        tmp_path,
        [
            ("tor/alias.txt", lambda t, n: _add_symlink(t, n, "tor/tor.exe")),
        ],
    )
    assert _extract_tor_bundle_safely(archive, install_dir) is False


def test_fifo_or_device_member_is_rejected(tmp_path):
    """Non-regular-non-directory members (FIFOs, devices) are refused."""
    install_dir = tmp_path / "install"
    install_dir.mkdir()

    archive = _build_archive(
        tmp_path,
        [
            ("tor/weird.fifo", _add_fifo),
        ],
    )
    assert _extract_tor_bundle_safely(archive, install_dir) is False


def test_path_traversal_member_is_rejected(tmp_path):
    """Pre-existing path-traversal guard still works under the new shape."""
    install_dir = tmp_path / "install"
    install_dir.mkdir()

    def add_traversal(tar, name):
        _add_regular_file(tar, name)

    # ../../escape.txt resolves outside install_dir on most platforms.
    archive = _build_archive(
        tmp_path,
        [
            ("../../escape.txt", add_traversal),
        ],
    )
    assert _extract_tor_bundle_safely(archive, install_dir) is False


def test_malformed_tar_is_rejected(tmp_path):
    """A corrupt/non-tar file is rejected without crashing."""
    install_dir = tmp_path / "install"
    install_dir.mkdir()

    bogus = tmp_path / "not-a-tar.tar.gz"
    bogus.write_bytes(b"this is not a tar archive at all")

    assert _extract_tor_bundle_safely(bogus, install_dir) is False


def test_extraction_failure_does_not_leave_partial_state_referenced_to_caller(tmp_path):
    """When extraction fails partway, the caller relies on a False return
    to know it must clean up. We test the contract here — actual cleanup
    of files that may have been written by tar.extractall() before the
    failure point isn't part of THIS helper's responsibility (the caller
    deletes the install dir if needed)."""
    install_dir = tmp_path / "install"
    install_dir.mkdir()

    # Hostile archive: one good file, then a symlink. Whether the good
    # file was written or not, the return value must be False so the
    # caller refuses the bundle.
    archive = _build_archive(
        tmp_path,
        [
            ("tor/clean.txt", lambda t, n: _add_regular_file(t, n)),
            ("tor/evil-link.txt", lambda t, n: _add_symlink(t, n, "/etc/passwd")),
        ],
    )

    assert _extract_tor_bundle_safely(archive, install_dir) is False
