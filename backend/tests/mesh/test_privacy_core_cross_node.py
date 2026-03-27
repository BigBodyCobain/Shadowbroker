from __future__ import annotations

import base64
import shutil
from pathlib import Path

import pytest

from services.privacy_core_client import (
    PrivacyCoreError,
    PrivacyCoreClient,
    PrivacyCoreUnavailable,
    candidate_library_paths,
)


def _built_library_path() -> Path:
    for candidate in candidate_library_paths():
        if candidate.exists():
            return candidate
    raise PrivacyCoreUnavailable("privacy-core shared library not found")


def _isolated_client(tmp_path: Path, name: str) -> PrivacyCoreClient:
    source = _built_library_path()
    target = tmp_path / f"{name}{source.suffix}"
    shutil.copy2(source, target)
    return PrivacyCoreClient.load(target)


# NOTE: This test runs both clients in the same process. It validates key-package
# serialization/deserialization correctness but does not prove cross-process isolation.
# True cross-process testing deferred — see BUILD_TRACKER S3-F4 note.
def test_cross_client_key_package_serialization_round_trip(tmp_path):
    try:
        client_a = _isolated_client(tmp_path, "privacy_core_node_a")
        client_b = _isolated_client(tmp_path, "privacy_core_node_b")
    except PrivacyCoreUnavailable:
        pytest.skip("privacy-core shared library not found")

    assert client_a.reset_all_state() is True
    assert client_b.reset_all_state() is True

    alice = client_a.create_identity()
    group = client_a.create_group(alice)
    throwaway = client_b.create_identity()
    bob = client_b.create_identity()

    exported = client_b.export_key_package(bob)
    transported = base64.b64decode(base64.b64encode(exported))
    imported = client_a.import_key_package(transported)
    commit = client_a.add_member(group, imported)

    assert client_a.commit_message_bytes(commit)
    assert client_a.commit_welcome_message_bytes(commit)

    assert client_a.release_commit(commit) is True
    assert client_a.release_key_package(imported) is True
    assert client_a.release_group(group) is True
    assert client_a.release_identity(alice) is True
    assert client_b.release_identity(throwaway) is True
    assert client_b.release_identity(bob) is True


def test_import_key_package_rejects_oversized_payload(tmp_path):
    try:
        client = _isolated_client(tmp_path, "privacy_core_oversized")
    except PrivacyCoreUnavailable:
        pytest.skip("privacy-core shared library not found")

    assert client.reset_all_state() is True

    with pytest.raises(PrivacyCoreError, match="maximum size"):
        client.import_key_package(b"x" * 65_537)
