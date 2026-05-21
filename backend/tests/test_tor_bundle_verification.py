"""Issue #201 (tg12): Tor bundle integrity must come from at least one
trusted source. Previously, if the upstream ``.sha256sum`` was
unreachable, the bundle was extracted and executed anyway with only
HTTPS-level transport trust.

The fix introduces a multi-source verification chain:

  1. Upstream ``.sha256sum`` (current behavior)
  2. Baked-in digest list at ``backend/data/tor_bundle_digests.json``
  3. If neither source is reachable AT ALL: HTTPS-only fallback with a
     loud warning (avoids breaking first-run onboarding while the
     maintainer hasn't yet pinned a new Tor release)

A mismatch from a source that DID respond is always fatal — only the
"no source reachable" case falls back to HTTPS-only.
"""
import hashlib
from pathlib import Path

import pytest

from services import tor_hidden_service as tor_svc
from services.tor_hidden_service import (
    _DIGEST_PLACEHOLDER,
    _load_baked_in_digests,
    _verify_tor_bundle,
)


@pytest.fixture
def fake_bundle(tmp_path):
    """A tiny synthetic 'bundle' so we can compute its digest deterministically."""
    archive = tmp_path / "fake-tor.tar.gz"
    payload = b"this is not really a tar archive"
    archive.write_bytes(payload)
    expected = hashlib.sha256(payload).hexdigest().lower()
    return archive, expected


def test_baked_in_digests_skips_placeholders(tmp_path, monkeypatch):
    """Entries with the placeholder value are filtered out."""
    digest_file = tmp_path / "digests.json"
    digest_file.write_text(
        '{"https://example.com/a.tar.gz": "PLACEHOLDER_REPLACE_BEFORE_RELEASE", '
        '"https://example.com/b.tar.gz": "deadbeef"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(tor_svc, "_TOR_DIGEST_FILE", digest_file)

    digests = _load_baked_in_digests()
    assert "https://example.com/a.tar.gz" not in digests
    assert digests.get("https://example.com/b.tar.gz") == "deadbeef"


def test_verification_succeeds_when_upstream_matches(fake_bundle, monkeypatch):
    """Path A: upstream .sha256sum returns the matching digest."""
    archive, expected = fake_bundle

    def fake_urlretrieve(url, dest):
        dest_path = Path(dest)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_text(f"{expected}  bundle.tar.gz\n", encoding="utf-8")

    monkeypatch.setattr(tor_svc, "urlretrieve", fake_urlretrieve)
    monkeypatch.setattr(tor_svc, "_load_baked_in_digests", lambda: {})

    verified, reason = _verify_tor_bundle(archive, "https://example.com/bundle.tar.gz")
    assert verified is True
    assert "upstream" in reason


def test_verification_succeeds_via_baked_in_when_upstream_unreachable(fake_bundle, monkeypatch):
    """Path B: upstream .sha256sum fails; baked-in digest matches."""
    archive, expected = fake_bundle

    def fake_urlretrieve(url, dest):
        raise RuntimeError("upstream unreachable")

    monkeypatch.setattr(tor_svc, "urlretrieve", fake_urlretrieve)
    monkeypatch.setattr(
        tor_svc, "_load_baked_in_digests",
        lambda: {"https://example.com/bundle.tar.gz": expected},
    )

    verified, reason = _verify_tor_bundle(archive, "https://example.com/bundle.tar.gz")
    assert verified is True
    assert "baked-in" in reason


def test_verification_fails_when_upstream_disagrees(fake_bundle, monkeypatch):
    """Mismatch from a source that DID respond is always fatal."""
    archive, _expected = fake_bundle

    def fake_urlretrieve(url, dest):
        dest_path = Path(dest)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_text("0" * 64 + "  bundle.tar.gz\n", encoding="utf-8")

    monkeypatch.setattr(tor_svc, "urlretrieve", fake_urlretrieve)
    monkeypatch.setattr(tor_svc, "_load_baked_in_digests", lambda: {})

    verified, reason = _verify_tor_bundle(archive, "https://example.com/bundle.tar.gz")
    assert verified is False
    assert "mismatch" in reason.lower()


def test_verification_fails_when_baked_in_disagrees(fake_bundle, monkeypatch):
    """Even with no upstream, a baked-in mismatch is fatal."""
    archive, _expected = fake_bundle

    def fake_urlretrieve(url, dest):
        raise RuntimeError("upstream unreachable")

    monkeypatch.setattr(tor_svc, "urlretrieve", fake_urlretrieve)
    monkeypatch.setattr(
        tor_svc, "_load_baked_in_digests",
        lambda: {"https://example.com/bundle.tar.gz": "0" * 64},
    )

    verified, reason = _verify_tor_bundle(archive, "https://example.com/bundle.tar.gz")
    assert verified is False


def test_verification_falls_back_to_https_when_no_source_reachable(fake_bundle, monkeypatch, caplog):
    """No source available → HTTPS-only fallback with a loud warning.

    This preserves first-run onboarding while the maintainer hasn't
    yet pinned a particular Tor release in the digest file.
    """
    archive, _expected = fake_bundle

    def fake_urlretrieve(url, dest):
        raise RuntimeError("upstream unreachable")

    monkeypatch.setattr(tor_svc, "urlretrieve", fake_urlretrieve)
    monkeypatch.setattr(tor_svc, "_load_baked_in_digests", lambda: {})

    import logging
    with caplog.at_level(logging.WARNING):
        verified, reason = _verify_tor_bundle(archive, "https://example.com/bundle.tar.gz")
    assert verified is True
    assert "https-only" in reason.lower()
    assert any(
        "fell back to HTTPS-only" in record.getMessage() for record in caplog.records
    )
