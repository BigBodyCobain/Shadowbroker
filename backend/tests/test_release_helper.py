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


def test_write_release_attestation_writes_expected_payload(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_SHA", "abc1234")
    monkeypatch.setenv("GITHUB_WORKFLOW", "CI")
    monkeypatch.setenv("GITHUB_RUN_ID", "12345")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    output_path = tmp_path / "release_attestation.json"

    payload = release_helper.write_release_attestation(
        output_path,
        suite_green=True,
        report="ops/artifacts/dm-relay-security-report.txt",
        command="uv run pytest tests/mesh/test_mesh_dm_security.py",
        generated_at="2026-04-15T01:02:03Z",
    )

    assert payload["generated_at"] == "2026-04-15T01:02:03Z"
    assert payload["commit"] == "abc1234"
    assert payload["threat_model_reference"] == "docs/mesh/threat-model.md"
    assert payload["dm_relay_security_suite"]["green"] is True
    assert payload["dm_relay_security_suite"]["report"] == "ops/artifacts/dm-relay-security-report.txt"
    assert payload["dm_relay_security_suite"]["command"] == "uv run pytest tests/mesh/test_mesh_dm_security.py"
    assert payload["ci"]["workflow"] == "CI"
    assert payload["ci"]["run_id"] == "12345"
    assert payload["ci"]["run_attempt"] == "2"
    assert payload["ci"]["ref"] == "refs/heads/main"
    written = json.loads(output_path.read_text(encoding="utf-8"))
    assert written == payload


def test_build_release_attestation_uses_failure_default_detail():
    payload = release_helper.build_release_attestation(
        suite_green=False,
        generated_at="2026-04-15T01:02:03Z",
    )

    assert payload["dm_relay_security_suite"]["green"] is False
    assert "failing DM relay security suite run" in payload["dm_relay_security_suite"]["detail"]
