"""Peer URL SSRF guard: block dangerous targets without breaking private meshes."""
from __future__ import annotations

from services.ssrf_guard import guard_url_for_peer_request


def test_peer_guard_rejects_non_http_schemes():
    for url in ("file:///etc/passwd", "ftp://peer.example/x", "socks5://peer.example/x"):
        result = guard_url_for_peer_request(url)
        assert result["ok"] is False, url


def test_peer_guard_rejects_url_credentials():
    result = guard_url_for_peer_request("https://user:pass@peer.example/api")
    assert result["ok"] is False


def test_peer_guard_rejects_metadata_targets():
    for url in (
        "http://169.254.169.254/latest/meta-data/",
        "http://metadata.google.internal/computeMetadata/v1/",
        "http://metadata/latest/meta-data/",
        "http://[fd00:ec2::254]/latest/meta-data/",
    ):
        assert guard_url_for_peer_request(url)["ok"] is False, url


def test_peer_guard_allows_loopback_and_private_peers():
    # Loopback/RFC1918 peers are legitimate in local and LAN mesh deployments.
    for url in ("http://127.0.0.1:8080", "http://10.0.0.5:9000", "http://192.168.1.7/api"):
        assert guard_url_for_peer_request(url)["ok"] is True, url


def test_peer_guard_allows_onion_and_proxied_peers_without_local_dns():
    assert guard_url_for_peer_request("http://abc123.onion/api")["ok"] is True
    assert guard_url_for_peer_request("https://peer.example.invalid/api", allow_proxied=True)["ok"] is True
