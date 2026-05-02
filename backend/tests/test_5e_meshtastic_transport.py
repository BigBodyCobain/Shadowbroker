"""Phase 5E — Meshtastic Transport Hardening tests.

Validates that:
1. Default config preserves current public deployment values
2. Custom 16-byte PSK is consumed by both TX and RX
3. Custom 32-byte PSK is consumed by both TX and RX
4. Invalid PSK encoding/length is rejected
5. Startup warning matrix behaves correctly
6. No split-brain between send and receive configuration
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_LONGFAST_DEFAULT_KEY = bytes(
    [
        0xD4, 0xF1, 0xBB, 0x3A, 0x20, 0x29, 0x07, 0x59,
        0xF0, 0xBC, 0xFF, 0xAB, 0xCF, 0x4E, 0x69, 0x01,
    ]
)


def _patch_settings(monkeypatch, **overrides):
    """Patch get_settings() to return a fake with given overrides."""
    from services.config import Settings

    defaults = {
        "MESH_MQTT_BROKER": "mqtt.meshtastic.org",
        "MESH_MQTT_PORT": 1883,
        "MESH_MQTT_USER": "meshdev",
        "MESH_MQTT_PASS": "large4cats",
        "MESH_MQTT_PSK": "",
        # Satisfy _ensure_dm_token_pepper so it doesn't write to disk
        "MESH_DM_TOKEN_PEPPER": "a" * 32,
    }
    defaults.update(overrides)

    class _FakeSettings:
        pass

    for k, v in defaults.items():
        setattr(_FakeSettings, k, v)

    # Patch in all modules that import get_settings
    import services.config
    import services.env_check

    fake_fn = lambda: _FakeSettings()
    fake_fn.cache_clear = lambda: None  # satisfy lru_cache callers
    monkeypatch.setattr(services.config, "get_settings", fake_fn)
    monkeypatch.setattr(services.env_check, "get_settings", fake_fn)

    # Patch in mesh_router and sigint_bridge at module level
    from services.mesh import mesh_router
    import services.sigint_bridge

    monkeypatch.setattr(mesh_router, "get_settings", fake_fn, raising=False)
    monkeypatch.setattr(services.sigint_bridge, "get_settings", fake_fn)

    return _FakeSettings


# ---------------------------------------------------------------------------
# 1. Default config preserves current public deployment values
# ---------------------------------------------------------------------------

class TestDefaultCompatibility:
    def test_default_broker(self):
        from services.config import Settings
        s = Settings()
        assert s.MESH_MQTT_BROKER == "mqtt.meshtastic.org"

    def test_default_port(self):
        from services.config import Settings
        s = Settings()
        assert s.MESH_MQTT_PORT == 1883

    def test_default_credentials(self):
        from services.config import Settings
        s = Settings()
        assert s.MESH_MQTT_USER == "meshdev"
        assert s.MESH_MQTT_PASS == "large4cats"

    def test_default_psk_empty(self):
        from services.config import Settings
        s = Settings()
        assert s.MESH_MQTT_PSK == ""

    def test_tx_default_psk_is_longfast(self, monkeypatch):
        _patch_settings(monkeypatch)
        from services.mesh.mesh_router import MeshtasticTransport
        assert MeshtasticTransport._resolve_psk() == _LONGFAST_DEFAULT_KEY

    def test_rx_default_psk_is_longfast(self, monkeypatch):
        _patch_settings(monkeypatch)
        from services.sigint_bridge import MeshtasticBridge
        assert MeshtasticBridge._resolve_psk() == _LONGFAST_DEFAULT_KEY

    def test_tx_default_broker_config(self, monkeypatch):
        _patch_settings(monkeypatch)
        from services.mesh.mesh_router import MeshtasticTransport
        broker, port, user, pw = MeshtasticTransport._mqtt_config()
        assert broker == "mqtt.meshtastic.org"
        assert port == 1883
        assert user == "meshdev"
        assert pw == "large4cats"

    def test_rx_default_broker_config(self, monkeypatch):
        _patch_settings(monkeypatch)
        from services.sigint_bridge import MeshtasticBridge
        broker, port, user, pw = MeshtasticBridge._mqtt_config()
        assert broker == "mqtt.meshtastic.org"
        assert port == 1883
        assert user == "meshdev"
        assert pw == "large4cats"

    def test_rx_client_id_is_runtime_unique_not_fixed_literal(self, monkeypatch):
        _patch_settings(monkeypatch)
        from services.sigint_bridge import MeshtasticBridge

        first = MeshtasticBridge()
        second = MeshtasticBridge()

        assert first._client_id.startswith("sb096-")
        assert second._client_id.startswith("sb096-")
        assert first._client_id != second._client_id
        assert first._client_id != "shadowbroker-mesh"
        assert second._client_id != "shadowbroker-mesh"


# ---------------------------------------------------------------------------
# 2. Custom 16-byte PSK consumed by both TX and RX
# ---------------------------------------------------------------------------

class TestCustom16BytePSK:
    PSK_HEX = "00112233445566778899aabbccddeeff"
    PSK_BYTES = bytes.fromhex(PSK_HEX)

    def test_tx_resolves_16byte_psk(self, monkeypatch):
        _patch_settings(monkeypatch, MESH_MQTT_PSK=self.PSK_HEX)
        from services.mesh.mesh_router import MeshtasticTransport
        assert MeshtasticTransport._resolve_psk() == self.PSK_BYTES

    def test_rx_resolves_16byte_psk(self, monkeypatch):
        _patch_settings(monkeypatch, MESH_MQTT_PSK=self.PSK_HEX)
        from services.sigint_bridge import MeshtasticBridge
        assert MeshtasticBridge._resolve_psk() == self.PSK_BYTES

    def test_16byte_psk_not_longfast(self, monkeypatch):
        _patch_settings(monkeypatch, MESH_MQTT_PSK=self.PSK_HEX)
        from services.mesh.mesh_router import MeshtasticTransport
        assert MeshtasticTransport._resolve_psk() != _LONGFAST_DEFAULT_KEY


# ---------------------------------------------------------------------------
# 3. Custom 32-byte PSK consumed by both TX and RX
# ---------------------------------------------------------------------------

class TestCustom32BytePSK:
    PSK_HEX = "00112233445566778899aabbccddeeff00112233445566778899aabbccddeeff"
    PSK_BYTES = bytes.fromhex(PSK_HEX)

    def test_tx_resolves_32byte_psk(self, monkeypatch):
        _patch_settings(monkeypatch, MESH_MQTT_PSK=self.PSK_HEX)
        from services.mesh.mesh_router import MeshtasticTransport
        assert MeshtasticTransport._resolve_psk() == self.PSK_BYTES

    def test_rx_resolves_32byte_psk(self, monkeypatch):
        _patch_settings(monkeypatch, MESH_MQTT_PSK=self.PSK_HEX)
        from services.sigint_bridge import MeshtasticBridge
        assert MeshtasticBridge._resolve_psk() == self.PSK_BYTES

    def test_32byte_psk_length(self, monkeypatch):
        _patch_settings(monkeypatch, MESH_MQTT_PSK=self.PSK_HEX)
        from services.mesh.mesh_router import MeshtasticTransport
        assert len(MeshtasticTransport._resolve_psk()) == 32


# ---------------------------------------------------------------------------
# 4. Invalid PSK encoding/length is rejected
# ---------------------------------------------------------------------------

class TestInvalidPSKRejected:
    def test_non_hex_rejected(self):
        from services.env_check import validate_mesh_mqtt_psk
        err = validate_mesh_mqtt_psk("not-hex-at-all")
        assert err is not None
        assert "hex" in err.lower()

    def test_odd_hex_rejected(self):
        from services.env_check import validate_mesh_mqtt_psk
        err = validate_mesh_mqtt_psk("abc")  # odd-length hex
        assert err is not None

    def test_wrong_length_8_bytes_rejected(self):
        from services.env_check import validate_mesh_mqtt_psk
        err = validate_mesh_mqtt_psk("00112233aabbccdd")  # 8 bytes
        assert err is not None
        assert "16 or 32" in err

    def test_wrong_length_24_bytes_rejected(self):
        from services.env_check import validate_mesh_mqtt_psk
        err = validate_mesh_mqtt_psk("00" * 24)  # 24 bytes
        assert err is not None
        assert "16 or 32" in err

    def test_valid_16_bytes_accepted(self):
        from services.env_check import validate_mesh_mqtt_psk
        assert validate_mesh_mqtt_psk("00" * 16) is None

    def test_valid_32_bytes_accepted(self):
        from services.env_check import validate_mesh_mqtt_psk
        assert validate_mesh_mqtt_psk("00" * 32) is None

    def test_empty_string_accepted(self):
        from services.env_check import validate_mesh_mqtt_psk
        assert validate_mesh_mqtt_psk("") is None

    def test_validate_env_rejects_bad_psk(self, monkeypatch):
        """validate_env with strict=False returns False on bad PSK."""
        _patch_settings(monkeypatch, MESH_MQTT_PSK="bad-hex")
        from services.env_check import validate_env
        result = validate_env(strict=False)
        assert result is False


# ---------------------------------------------------------------------------
# 5. Startup warning matrix
# ---------------------------------------------------------------------------

class TestStartupWarningMatrix:
    def test_default_config_no_mqtt_warnings(self, monkeypatch):
        """Default public config must emit no MQTT warning."""
        _patch_settings(monkeypatch)
        from services.env_check import _mqtt_startup_warnings, get_settings
        warnings = _mqtt_startup_warnings(get_settings())
        assert warnings == []

    def test_custom_broker_default_psk_warns(self, monkeypatch):
        _patch_settings(monkeypatch, MESH_MQTT_BROKER="my-broker.local")
        from services.env_check import _mqtt_startup_warnings, get_settings
        warnings = _mqtt_startup_warnings(get_settings())
        psk_warnings = [w for w in warnings if "LongFast PSK" in w]
        assert len(psk_warnings) == 1

    def test_custom_broker_default_creds_warns(self, monkeypatch):
        _patch_settings(monkeypatch, MESH_MQTT_BROKER="my-broker.local")
        from services.env_check import _mqtt_startup_warnings, get_settings
        warnings = _mqtt_startup_warnings(get_settings())
        cred_warnings = [w for w in warnings if "credentials" in w.lower()]
        assert len(cred_warnings) == 1

    def test_custom_broker_custom_psk_no_psk_warning(self, monkeypatch):
        _patch_settings(
            monkeypatch,
            MESH_MQTT_BROKER="my-broker.local",
            MESH_MQTT_PSK="00" * 16,
        )
        from services.env_check import _mqtt_startup_warnings, get_settings
        warnings = _mqtt_startup_warnings(get_settings())
        psk_warnings = [w for w in warnings if "LongFast PSK" in w]
        assert len(psk_warnings) == 0

    def test_custom_broker_custom_creds_no_cred_warning(self, monkeypatch):
        _patch_settings(
            monkeypatch,
            MESH_MQTT_BROKER="my-broker.local",
            MESH_MQTT_USER="private",
            MESH_MQTT_PASS="secretpass",
        )
        from services.env_check import _mqtt_startup_warnings, get_settings
        warnings = _mqtt_startup_warnings(get_settings())
        cred_warnings = [w for w in warnings if "credentials" in w.lower()]
        assert len(cred_warnings) == 0

    def test_default_broker_custom_psk_no_warning(self, monkeypatch):
        """Using a custom PSK on the default public broker is fine — no warning."""
        _patch_settings(monkeypatch, MESH_MQTT_PSK="00" * 16)
        from services.env_check import _mqtt_startup_warnings, get_settings
        warnings = _mqtt_startup_warnings(get_settings())
        assert warnings == []

    def test_custom_broker_both_defaults_emits_two_warnings(self, monkeypatch):
        _patch_settings(monkeypatch, MESH_MQTT_BROKER="private.example.com")
        from services.env_check import _mqtt_startup_warnings, get_settings
        warnings = _mqtt_startup_warnings(get_settings())
        assert len(warnings) == 2


# ---------------------------------------------------------------------------
# 6. No split-brain between send and receive configuration
# ---------------------------------------------------------------------------

class TestNoSplitBrain:
    def test_tx_rx_same_broker(self, monkeypatch):
        _patch_settings(monkeypatch, MESH_MQTT_BROKER="custom.broker.io", MESH_MQTT_PORT=8883)
        from services.mesh.mesh_router import MeshtasticTransport
        from services.sigint_bridge import MeshtasticBridge
        tx_broker, tx_port, tx_user, tx_pw = MeshtasticTransport._mqtt_config()
        rx_broker, rx_port, rx_user, rx_pw = MeshtasticBridge._mqtt_config()
        assert tx_broker == rx_broker == "custom.broker.io"
        assert tx_port == rx_port == 8883
        assert tx_user == rx_user
        assert tx_pw == rx_pw

    def test_tx_rx_same_psk(self, monkeypatch):
        psk_hex = "aabbccdd" * 4
        _patch_settings(monkeypatch, MESH_MQTT_PSK=psk_hex)
        from services.mesh.mesh_router import MeshtasticTransport
        from services.sigint_bridge import MeshtasticBridge
        assert MeshtasticTransport._resolve_psk() == MeshtasticBridge._resolve_psk()

    def test_tx_rx_same_default_psk(self, monkeypatch):
        _patch_settings(monkeypatch)
        from services.mesh.mesh_router import MeshtasticTransport
        from services.sigint_bridge import MeshtasticBridge
        assert MeshtasticTransport._resolve_psk() == MeshtasticBridge._resolve_psk()
        assert MeshtasticTransport._resolve_psk() == _LONGFAST_DEFAULT_KEY

    def test_tx_rx_same_custom_credentials(self, monkeypatch):
        _patch_settings(
            monkeypatch,
            MESH_MQTT_USER="private-user",
            MESH_MQTT_PASS="private-pass",
        )
        from services.mesh.mesh_router import MeshtasticTransport
        from services.sigint_bridge import MeshtasticBridge
        _, _, tx_user, tx_pw = MeshtasticTransport._mqtt_config()
        _, _, rx_user, rx_pw = MeshtasticBridge._mqtt_config()
        assert tx_user == rx_user == "private-user"
        assert tx_pw == rx_pw == "private-pass"
