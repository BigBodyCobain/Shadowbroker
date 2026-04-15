import json
import importlib.util
from pathlib import Path

import pytest


_HELPER_PATH = Path(__file__).resolve().parents[1] / "scripts" / "release_helper.py"
_SPEC = importlib.util.spec_from_file_location("release_helper", _HELPER_PATH)
assert _SPEC and _SPEC.loader
release_helper = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(release_helper)


def test_normalize_version_accepts_plain_and_prefixed():
    assert release_helper._normalize_version("0.9.6") == "0.9.6"
    assert release_helper._normalize_version("v0.9.6") == "0.9.6"


def test_normalize_version_rejects_non_semver_triplet():
    with pytest.raises(ValueError, match="X.Y.Z"):
        release_helper._normalize_version("0.9")


def test_expected_release_names():
    assert release_helper.expected_tag("0.9.6") == "v0.9.6"
    assert release_helper.expected_asset("0.9.6") == "ShadowBroker_v0.9.6.zip"


def test_set_version_updates_package_json(monkeypatch, tmp_path):
    package_json = tmp_path / "package.json"
    package_json.write_text(json.dumps({"name": "frontend", "version": "0.9.5"}) + "\n", encoding="utf-8")
    monkeypatch.setattr(release_helper, "PACKAGE_JSON", package_json)

    version = release_helper.set_version("0.9.6")

    assert version == "0.9.6"
    data = json.loads(package_json.read_text(encoding="utf-8"))
    assert data["version"] == "0.9.6"


def test_sha256_file(tmp_path):
    payload = tmp_path / "payload.zip"
    payload.write_bytes(b"shadowbroker")

    digest = release_helper.sha256_file(payload)

    assert digest == "153f774fe47e71734bf608e20fd59d9ee0ad522811dc9a121bbfd3dbd79a4229"
