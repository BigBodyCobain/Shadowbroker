"""Issue #231 — self-update SHA-256 verification.

Before this fix, ``_validate_zip_hash`` returned silently whenever the
``MESH_UPDATE_SHA256`` env var was unset (the default — nothing in the
install docs ever told operators to set it). That made the auto-updater
a supply-chain RCE on any compromise of the GitHub release pipeline.

The fix introduces a four-source verification chain:

  1. ``MESH_UPDATE_SHA256`` env var (operator override, preserved)
  2. ``SHA256SUMS.txt`` asset published alongside the release (primary)
  3. Baked-in ``backend/data/release_digests.json`` (fallback)
  4. HTTPS-only fallback with a loud warning (preserves auto-update during
     transient outages so the user isn't stuck)

A mismatch from any source that DID respond is fatal. Only the "no
source reachable at all" case falls back to HTTPS-only.
"""
import hashlib
import json
from pathlib import Path

import pytest

from services import updater
from services.updater import (
    _compute_sha256,
    _fetch_sha256sums,
    _load_baked_in_release_digests,
    _validate_zip_hash,
)


@pytest.fixture
def fake_archive(tmp_path):
    """A tiny synthetic zip-shaped file so we can compute a known digest."""
    archive = tmp_path / "update.zip"
    payload = b"this is not really a release archive"
    archive.write_bytes(payload)
    expected = hashlib.sha256(payload).hexdigest().lower()
    return str(archive), expected


def test_baked_in_release_digests_file_loads():
    """The shipped release_digests.json must parse and contain v0.9.79."""
    digests = _load_baked_in_release_digests()
    assert "v0.9.79" in digests
    entry = digests["v0.9.79"]
    assert "ShadowBroker_v0.9.79.zip" in entry
    digest = entry["ShadowBroker_v0.9.79.zip"]
    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)


def test_baked_in_skips_comment_keys():
    """The _comment top-level key is ignored, not surfaced as a release."""
    digests = _load_baked_in_release_digests()
    assert "_comment" not in digests


def test_compute_sha256_matches_known_value(fake_archive):
    archive, expected = fake_archive
    assert _compute_sha256(archive) == expected


# ──────────────────────────────────────────────────────────────────────────
# Source 1: MESH_UPDATE_SHA256 env override
# ──────────────────────────────────────────────────────────────────────────


def test_env_override_matching_passes(fake_archive, monkeypatch):
    """Path 1: operator pinned the exact digest via env. Match = success."""
    archive, expected = fake_archive
    monkeypatch.setenv("MESH_UPDATE_SHA256", expected)

    note = _validate_zip_hash(archive)
    assert "MESH_UPDATE_SHA256" in note


def test_env_override_mismatch_fails_loudly(fake_archive, monkeypatch):
    """Path 1: operator pinned a different digest. Mismatch = fatal."""
    archive, _expected = fake_archive
    monkeypatch.setenv("MESH_UPDATE_SHA256", "0" * 64)

    with pytest.raises(RuntimeError) as exc_info:
        _validate_zip_hash(archive)
    assert "mismatch" in str(exc_info.value).lower()


# ──────────────────────────────────────────────────────────────────────────
# Source 2: SHA256SUMS.txt asset
# ──────────────────────────────────────────────────────────────────────────


def test_sha256sums_matching_passes(fake_archive, monkeypatch):
    """Path 2: SHA256SUMS.txt has the correct digest for our asset."""
    archive, expected = fake_archive
    monkeypatch.delenv("MESH_UPDATE_SHA256", raising=False)

    def fake_sums(url):
        return {"ShadowBroker_v9.9.9.zip": expected}

    monkeypatch.setattr(updater, "_fetch_sha256sums", fake_sums)
    note = _validate_zip_hash(
        archive,
        asset_name="ShadowBroker_v9.9.9.zip",
        sha256sums_url="https://example.test/SHA256SUMS.txt",
        release_tag="v9.9.9",
    )
    assert "SHA256SUMS.txt" in note


def test_sha256sums_mismatch_fails_loudly(fake_archive, monkeypatch):
    """Path 2: SHA256SUMS.txt has a different digest. Refuse."""
    archive, _expected = fake_archive
    monkeypatch.delenv("MESH_UPDATE_SHA256", raising=False)

    def fake_sums(url):
        return {"ShadowBroker_v9.9.9.zip": "0" * 64}

    monkeypatch.setattr(updater, "_fetch_sha256sums", fake_sums)
    with pytest.raises(RuntimeError) as exc_info:
        _validate_zip_hash(
            archive,
            asset_name="ShadowBroker_v9.9.9.zip",
            sha256sums_url="https://example.test/SHA256SUMS.txt",
            release_tag="v9.9.9",
        )
    assert "mismatch" in str(exc_info.value).lower()
    assert "SHA256SUMS" in str(exc_info.value)


# ──────────────────────────────────────────────────────────────────────────
# Source 3: baked-in digest list
# ──────────────────────────────────────────────────────────────────────────


def test_baked_in_matching_passes(fake_archive, monkeypatch):
    """Path 3: SHA256SUMS unreachable, but the baked-in list has us."""
    archive, expected = fake_archive
    monkeypatch.delenv("MESH_UPDATE_SHA256", raising=False)
    monkeypatch.setattr(updater, "_fetch_sha256sums", lambda url: {})
    monkeypatch.setattr(
        updater,
        "_load_baked_in_release_digests",
        lambda: {"v9.9.9": {"ShadowBroker_v9.9.9.zip": expected}},
    )

    note = _validate_zip_hash(
        archive,
        asset_name="ShadowBroker_v9.9.9.zip",
        sha256sums_url="https://example.test/SHA256SUMS.txt",
        release_tag="v9.9.9",
    )
    assert "baked-in" in note


def test_baked_in_mismatch_fails_loudly(fake_archive, monkeypatch):
    """Path 3: baked-in says something different. Refuse."""
    archive, _expected = fake_archive
    monkeypatch.delenv("MESH_UPDATE_SHA256", raising=False)
    monkeypatch.setattr(updater, "_fetch_sha256sums", lambda url: {})
    monkeypatch.setattr(
        updater,
        "_load_baked_in_release_digests",
        lambda: {"v9.9.9": {"ShadowBroker_v9.9.9.zip": "0" * 64}},
    )

    with pytest.raises(RuntimeError) as exc_info:
        _validate_zip_hash(
            archive,
            asset_name="ShadowBroker_v9.9.9.zip",
            sha256sums_url="",
            release_tag="v9.9.9",
        )
    assert "mismatch" in str(exc_info.value).lower()


# ──────────────────────────────────────────────────────────────────────────
# Source 4: HTTPS-only fallback
# ──────────────────────────────────────────────────────────────────────────


def test_https_only_fallback_when_no_source_available(fake_archive, monkeypatch, caplog):
    """Path 4: nothing matches — fall back to HTTPS-only with loud warning.

    This preserves the auto-update flow during transient outages: an
    operator on a flaky network during update doesn't get a hostile
    error, they get a degraded-but-functional update with a clear log
    message.
    """
    import logging

    archive, _expected = fake_archive
    monkeypatch.delenv("MESH_UPDATE_SHA256", raising=False)
    monkeypatch.setattr(updater, "_fetch_sha256sums", lambda url: {})
    monkeypatch.setattr(updater, "_load_baked_in_release_digests", lambda: {})

    with caplog.at_level(logging.WARNING):
        note = _validate_zip_hash(
            archive,
            asset_name="ShadowBroker_v99.99.zip",
            sha256sums_url="",
            release_tag="v99.99",
        )

    assert "https-only" in note.lower()
    assert any(
        "fell back to HTTPS-only" in rec.getMessage() for rec in caplog.records
    )


def test_https_only_fallback_when_release_tag_unknown(fake_archive, monkeypatch):
    """Path 4 also kicks in when we have a baked-in list but it doesn't
    contain THIS release tag — e.g. a brand-new release that the local
    install hasn't seen a digest for yet."""
    archive, _expected = fake_archive
    monkeypatch.delenv("MESH_UPDATE_SHA256", raising=False)
    monkeypatch.setattr(updater, "_fetch_sha256sums", lambda url: {})
    monkeypatch.setattr(
        updater,
        "_load_baked_in_release_digests",
        lambda: {"v0.0.1": {"old.zip": "0" * 64}},  # different tag, doesn't match
    )

    note = _validate_zip_hash(
        archive,
        asset_name="ShadowBroker_v99.99.zip",
        sha256sums_url="",
        release_tag="v99.99",
    )
    assert "https-only" in note.lower()


# ──────────────────────────────────────────────────────────────────────────
# Precedence (env > SHA256SUMS > baked-in > https-only)
# ──────────────────────────────────────────────────────────────────────────


def test_env_override_beats_all_other_sources(fake_archive, monkeypatch):
    """When MESH_UPDATE_SHA256 is set, it's the only source consulted.

    The other sources may return false positives or negatives — they
    shouldn't be queried at all when the operator pinned an exact value.
    """
    archive, expected = fake_archive
    monkeypatch.setenv("MESH_UPDATE_SHA256", expected)

    def boom_sums(url):
        raise AssertionError("SHA256SUMS source was queried despite env override")

    def boom_baked():
        raise AssertionError("Baked-in list was queried despite env override")

    monkeypatch.setattr(updater, "_fetch_sha256sums", boom_sums)
    monkeypatch.setattr(updater, "_load_baked_in_release_digests", boom_baked)

    note = _validate_zip_hash(
        archive,
        asset_name="any.zip",
        sha256sums_url="https://example.test/SHA256SUMS.txt",
        release_tag="any",
    )
    assert "MESH_UPDATE_SHA256" in note


# ──────────────────────────────────────────────────────────────────────────
# _fetch_sha256sums parser
# ──────────────────────────────────────────────────────────────────────────


def test_fetch_sha256sums_parses_standard_format(monkeypatch):
    """Standard ``sha256sum`` output: ``<digest>  <filename>``."""
    class _Resp:
        text = (
            "f6877c1d66614525315ea82636ce9f7b41178332c4dbf90d27431a1ea1d9cd47  ShadowBroker_v0.9.79.zip\n"
            "e0713c3cdda184cfbea750bfac0d62a35678fec00847e6476f2cac8e7e42046e  ShadowBroker_0.9.79_x64_en-US.msi\n"
        )

        def raise_for_status(self):
            pass

    def fake_get(url, timeout=15):
        return _Resp()

    monkeypatch.setattr(updater.requests, "get", fake_get)
    monkeypatch.setattr(updater, "_validate_update_url", lambda url, **kw: url)
    sums = _fetch_sha256sums("https://example.test/SHA256SUMS.txt")
    assert sums["ShadowBroker_v0.9.79.zip"].startswith("f6877c1d")
    assert sums["ShadowBroker_0.9.79_x64_en-US.msi"].startswith("e0713c3c")


def test_fetch_sha256sums_handles_binary_marker(monkeypatch):
    """sha256sum -b output: ``<digest> *<filename>``."""
    class _Resp:
        text = "f6877c1d66614525315ea82636ce9f7b41178332c4dbf90d27431a1ea1d9cd47 *ShadowBroker_v0.9.79.zip\n"

        def raise_for_status(self):
            pass

    monkeypatch.setattr(updater.requests, "get", lambda url, timeout=15: _Resp())
    monkeypatch.setattr(updater, "_validate_update_url", lambda url, **kw: url)
    sums = _fetch_sha256sums("https://example.test/SHA256SUMS.txt")
    assert "ShadowBroker_v0.9.79.zip" in sums


def test_fetch_sha256sums_skips_malformed_lines(monkeypatch):
    """Lines that don't parse cleanly are ignored, not aborted on."""
    class _Resp:
        text = (
            "# comment line\n"
            "\n"
            "not-a-digest  bogus.txt\n"
            "f6877c1d66614525315ea82636ce9f7b41178332c4dbf90d27431a1ea1d9cd47  good.zip\n"
        )

        def raise_for_status(self):
            pass

    monkeypatch.setattr(updater.requests, "get", lambda url, timeout=15: _Resp())
    monkeypatch.setattr(updater, "_validate_update_url", lambda url, **kw: url)
    sums = _fetch_sha256sums("https://example.test/SHA256SUMS.txt")
    assert "good.zip" in sums
    assert "bogus.txt" not in sums


def test_fetch_sha256sums_handles_network_failure(monkeypatch):
    """If the SHA256SUMS asset can't be fetched, return empty (caller
    falls through to baked-in / https-only)."""
    import requests as _req

    def fake_get(url, timeout=15):
        raise _req.exceptions.ConnectionError("upstream down")

    monkeypatch.setattr(updater.requests, "get", fake_get)
    monkeypatch.setattr(updater, "_validate_update_url", lambda url, **kw: url)
    sums = _fetch_sha256sums("https://example.test/SHA256SUMS.txt")
    assert sums == {}
