import copy

from services.mesh import mesh_relay_policy


def test_scoped_relay_policy_requires_hidden_transport_and_expires(monkeypatch):
    store = {}
    now = {"value": 1000.0}

    def _read_domain_json(_domain, _filename, default_factory, **_kwargs):
        payload = store.get("payload")
        if payload is None:
            return default_factory()
        return copy.deepcopy(payload)

    def _write_domain_json(_domain, _filename, payload, **_kwargs):
        store["payload"] = copy.deepcopy(payload)

    monkeypatch.setattr(mesh_relay_policy, "read_sensitive_domain_json", _read_domain_json)
    monkeypatch.setattr(mesh_relay_policy, "write_sensitive_domain_json", _write_domain_json)
    monkeypatch.setattr(mesh_relay_policy, "_now", lambda: now["value"])

    grant = mesh_relay_policy.grant_relay_policy(
        scope_type="dm_contact",
        scope_id="bob",
        profile="dev",
        hidden_transport_required=True,
        ttl_s=60,
        reason="test",
    )

    assert grant["scope_type"] == "dm_contact"
    denied = mesh_relay_policy.relay_policy_grants_dm(
        recipient_id="bob",
        profile="dev",
        hidden_transport_effective=False,
    )
    assert denied["granted"] is False
    assert denied["reason_code"] == "relay_policy_hidden_transport_required"

    allowed = mesh_relay_policy.relay_policy_grants_dm(
        recipient_id="bob",
        profile="dev",
        hidden_transport_effective=True,
    )
    assert allowed["granted"] is True

    now["value"] = 1061.0
    expired = mesh_relay_policy.relay_policy_grants_dm(
        recipient_id="bob",
        profile="dev",
        hidden_transport_effective=True,
    )
    assert expired["granted"] is False
    assert expired["reason_code"] == "relay_policy_not_granted"
