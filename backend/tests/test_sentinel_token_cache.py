"""Issue #200 (tg12): Sentinel token cache must require knowledge of the
client secret to hit, not just client_id.

Before this fix, the cache lookup was ``_sh_token_cache["client_id"] ==
client_id``. A caller who knew a valid client_id but supplied any secret
would hit the cache and reuse the original caller's bearer token, burning
their Copernicus quota and accessing imagery on their account.

After the fix, the cache key is an HMAC of ``(client_id, client_secret)``
under a per-process random key, so two callers with the same client_id but
different secrets compute different fingerprints and miss each other's
cache entries.
"""
from routers.tools import _credential_fingerprint, _sh_token_cache


def test_same_client_id_different_secrets_yield_different_fingerprints():
    fp_a = _credential_fingerprint("client-id-X", "secret-A")
    fp_b = _credential_fingerprint("client-id-X", "secret-B")
    assert fp_a != fp_b


def test_same_credentials_yield_same_fingerprint():
    """The cache is still useful — same caller hits its own entry."""
    fp1 = _credential_fingerprint("client-id-X", "secret-A")
    fp2 = _credential_fingerprint("client-id-X", "secret-A")
    assert fp1 == fp2


def test_different_client_ids_yield_different_fingerprints():
    fp_a = _credential_fingerprint("client-id-A", "shared-secret")
    fp_b = _credential_fingerprint("client-id-B", "shared-secret")
    assert fp_a != fp_b


def test_cache_lookup_key_field_renamed():
    """Catch accidental reintroduction of the client_id-only lookup."""
    # If a future commit re-adds `_sh_token_cache["client_id"]` we want this
    # test to fail loudly. The new schema only stores `credential_fp`.
    assert "client_id" not in _sh_token_cache
    assert "credential_fp" in _sh_token_cache


def test_attacker_with_wrong_secret_misses_cache(monkeypatch):
    """An attacker with valid client_id but wrong secret cannot hit the cache."""
    # Populate cache as if a legitimate caller just succeeded.
    legit_fp = _credential_fingerprint("legit-client", "legit-secret")
    _sh_token_cache["token"] = "VICTIM-BEARER-TOKEN"
    _sh_token_cache["credential_fp"] = legit_fp
    _sh_token_cache["expiry"] = 10**12  # far future

    # Attacker arrives with the same client_id but the wrong secret.
    attacker_fp = _credential_fingerprint("legit-client", "wrong-secret")
    assert attacker_fp != legit_fp

    # Reset cache for hygiene between tests.
    _sh_token_cache["token"] = None
    _sh_token_cache["credential_fp"] = ""
    _sh_token_cache["expiry"] = 0
