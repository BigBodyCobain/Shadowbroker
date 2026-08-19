"""Static contract for the Playwright runtime-user packaging fix in #516."""
from __future__ import annotations

from pathlib import Path


def test_dockerfile_uses_shared_playwright_browser_path_and_runtime_user_check() -> None:
    dockerfile = Path(__file__).resolve().parents[1] / "Dockerfile"
    text = dockerfile.read_text(encoding="utf-8")

    assert "ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright" in text
    assert "playwright install --with-deps chromium" in text
    assert "USER backenduser" in text
    assert "p.chromium.executable_path" in text
    assert "assert os.path.isfile(path)" in text
    assert "chromium_headless_shell-*" in text
