import zipfile
from unittest.mock import patch

import pytest

from services import geopolitics, updater


@pytest.fixture(autouse=True)
def _clear_gdelt_caches():
    geopolitics._article_title_cache.clear()
    geopolitics._article_url_safety_cache.clear()
    yield
    geopolitics._article_title_cache.clear()
    geopolitics._article_url_safety_cache.clear()


class TestGdeltArticleUrlSafety:
    def test_safe_public_article_url_allows_public_dns(self, monkeypatch):
        monkeypatch.setattr(
            geopolitics.socket,
            "getaddrinfo",
            lambda *args, **kwargs: [(0, 0, 0, "", ("93.184.216.34", 443))],
        )

        allowed, reason = geopolitics._is_safe_public_article_url("https://example.com/story")

        assert allowed is True
        assert reason == ""

    def test_safe_public_article_url_blocks_private_dns(self, monkeypatch):
        monkeypatch.setattr(
            geopolitics.socket,
            "getaddrinfo",
            lambda *args, **kwargs: [(0, 0, 0, "", ("10.0.0.7", 443))],
        )

        allowed, reason = geopolitics._is_safe_public_article_url("https://example.com/story")

        assert allowed is False
        assert reason == "private_dns"

    def test_fetch_article_title_refuses_private_ip_without_request(self):
        with patch("services.geopolitics.requests.get") as mock_get:
            title = geopolitics._fetch_article_title("http://127.0.0.1/story")

        assert title is None
        mock_get.assert_not_called()


class TestUpdaterHardening:
    def test_validate_update_url_rejects_untrusted_host(self):
        with pytest.raises(RuntimeError, match="untrusted release host"):
            updater._validate_update_url("https://evil.example.com/update.zip")

    def test_extract_and_copy_rejects_zip_path_traversal(self, tmp_path):
        zip_path = tmp_path / "bad.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("../escape.txt", "nope")

        with pytest.raises(RuntimeError, match="path traversal entry"):
            updater._extract_and_copy(str(zip_path), str(tmp_path / "project"), str(tmp_path / "work"))

    def test_perform_update_returns_manual_url_on_failure(self, monkeypatch, tmp_path):
        def _boom(_temp_dir):
            raise RuntimeError("update exploded")

        monkeypatch.setattr(updater, "_download_release", _boom)

        result = updater.perform_update(str(tmp_path))

        assert result["status"] == "error"
        assert result["manual_url"] == updater.GITHUB_RELEASES_PAGE_URL
        assert "update exploded" in result["message"]

    def test_perform_update_surfaces_release_metadata(self, monkeypatch, tmp_path):
        release_url = "https://github.com/BigBodyCobain/Shadowbroker/releases/tag/v1.2.3"
        download_url = (
            "https://github.com/BigBodyCobain/Shadowbroker/releases/download/v1.2.3/update.zip"
        )
        backup_path = tmp_path / "backup.zip"

        monkeypatch.setattr(
            updater,
            "_download_release",
            lambda _temp_dir: ("dummy.zip", "v1.2.3", download_url, release_url),
        )
        monkeypatch.setattr(updater, "_validate_zip_hash", lambda _zip_path: None)
        monkeypatch.setattr(updater, "_backup_current", lambda *_args: str(backup_path))
        monkeypatch.setattr(updater, "_extract_and_copy", lambda *_args: 42)

        result = updater.perform_update(str(tmp_path))

        assert result["status"] == "ok"
        assert result["version"] == "v1.2.3"
        assert result["files_updated"] == 42
        assert result["backup_path"] == str(backup_path)
        assert result["manual_url"] == release_url
        assert result["release_url"] == release_url
        assert result["download_url"] == download_url
