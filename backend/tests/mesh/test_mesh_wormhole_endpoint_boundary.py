def test_wormhole_identity_allows_local_operator_without_admin_key(client, monkeypatch):
    import main

    monkeypatch.setattr(main, "_current_admin_key", lambda: "test-key")
    monkeypatch.setattr(main, "_allow_insecure_admin", lambda: False)
    monkeypatch.setattr(
        main,
        "get_transport_identity",
        lambda: {
            "node_id": "transport-node",
            "public_key": "pub",
            "public_key_algo": "Ed25519",
        },
    )

    allowed = client.get("/api/wormhole/identity")
    assert allowed.status_code == 200
    assert allowed.json()["node_id"] == "transport-node"


def test_wormhole_gate_identity_allows_local_operator_without_admin_key(client, monkeypatch):
    import main

    monkeypatch.setattr(main, "_current_admin_key", lambda: "test-key")
    monkeypatch.setattr(main, "_allow_insecure_admin", lambda: False)
    monkeypatch.setattr(
        main,
        "get_active_gate_identity",
        lambda gate_id: {
            "ok": True,
            "gate_id": gate_id,
            "identity": {"node_id": "gate-node", "scope": "gate_session"},
        },
    )

    allowed = client.get("/api/wormhole/gate/journalists/identity")
    assert allowed.status_code == 200
    body = allowed.json()
    assert body["gate_id"] == "journalists"
    assert body["identity"]["node_id"] == "gate-node"


def test_wormhole_gate_personas_allows_local_operator_without_admin_key(client, monkeypatch):
    import main

    monkeypatch.setattr(main, "_current_admin_key", lambda: "test-key")
    monkeypatch.setattr(main, "_allow_insecure_admin", lambda: False)
    monkeypatch.setattr(
        main,
        "list_gate_personas",
        lambda gate_id: {
            "ok": True,
            "gate_id": gate_id,
            "active_persona_id": "",
            "personas": [{"node_id": "persona-node", "scope": "gate_persona"}],
        },
    )

    allowed = client.get("/api/wormhole/gate/journalists/personas")
    assert allowed.status_code == 200
    body = allowed.json()
    assert body["gate_id"] == "journalists"
    assert body["personas"][0]["node_id"] == "persona-node"
