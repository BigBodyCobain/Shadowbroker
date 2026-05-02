from __future__ import annotations

import base64
import json
import shutil
import subprocess
import sys
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


def _isolated_library_path(tmp_path: Path, name: str) -> Path:
    source = _built_library_path()
    target = tmp_path / f"{name}{source.suffix}"
    shutil.copy2(source, target)
    return target


def _isolated_client(tmp_path: Path, name: str) -> PrivacyCoreClient:
    return PrivacyCoreClient.load(_isolated_library_path(tmp_path, name))


def _export_key_package_in_subprocess(library_path: Path) -> bytes:
    backend_root = Path(__file__).resolve().parents[2]
    script = """
import base64
import json
import sys
from pathlib import Path

backend_root = Path(sys.argv[1])
library_path = Path(sys.argv[2])
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

from services.privacy_core_client import PrivacyCoreClient

client = PrivacyCoreClient.load(library_path)
assert client.reset_all_state() is True
_throwaway = client.create_identity()
identity = client.create_identity()
payload = client.export_key_package(identity)
print(json.dumps({"key_package_b64": base64.b64encode(payload).decode("ascii")}))
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(backend_root), str(library_path)],
        check=True,
        capture_output=True,
        text=True,
        cwd=str(backend_root),
    )
    payload = json.loads(result.stdout.strip())
    return base64.b64decode(payload["key_package_b64"])


def test_cross_process_key_package_serialization_round_trip(tmp_path):
    try:
        library_a = _isolated_library_path(tmp_path, "privacy_core_node_a")
        library_b = _isolated_library_path(tmp_path, "privacy_core_node_b")
        client_a = PrivacyCoreClient.load(library_a)
    except PrivacyCoreUnavailable:
        pytest.skip("privacy-core shared library not found")

    assert client_a.reset_all_state() is True

    alice = client_a.create_identity()
    group = client_a.create_group(alice)
    exported = _export_key_package_in_subprocess(library_b)
    transported = base64.b64decode(base64.b64encode(exported))
    imported = client_a.import_key_package(transported)
    commit = client_a.add_member(group, imported)

    assert client_a.commit_message_bytes(commit)
    assert client_a.commit_welcome_message_bytes(commit)

    assert client_a.release_commit(commit) is True
    assert client_a.release_key_package(imported) is True
    assert client_a.release_group(group) is True
    assert client_a.release_identity(alice) is True


def test_import_key_package_rejects_oversized_payload(tmp_path):
    try:
        client = _isolated_client(tmp_path, "privacy_core_oversized")
    except PrivacyCoreUnavailable:
        pytest.skip("privacy-core shared library not found")

    assert client.reset_all_state() is True

    with pytest.raises(PrivacyCoreError, match="maximum size"):
        client.import_key_package(b"x" * 65_537)
