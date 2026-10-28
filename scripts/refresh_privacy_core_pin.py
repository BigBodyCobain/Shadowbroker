from __future__ import annotations

import hashlib
import re
from pathlib import Path


PIN_KEY = "PRIVACY_CORE_ALLOWED_SHA256"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _privacy_core_library(root: Path) -> Path | None:
    release_dir = root / "privacy-core" / "target" / "release"
    candidates = (
        release_dir / "privacy_core.dll",
        release_dir / "libprivacy_core.so",
        release_dir / "libprivacy_core.dylib",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _parse_env(lines: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in lines:
        match = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$", line)
        if not match:
            continue
        key, raw_value = match.groups()
        values[key] = raw_value.strip().strip('"').strip("'")
    return values


def _replace_or_append_pin(lines: list[str], digest: str) -> tuple[list[str], bool]:
    updated: list[str] = []
    replaced = False
    pattern = re.compile(rf"^(\s*{re.escape(PIN_KEY)}\s*=).*$")
    for line in lines:
        if pattern.match(line):
            updated.append(f"{PIN_KEY}={digest}")
            replaced = True
        else:
            updated.append(line)
    if not replaced:
        if updated and updated[-1].strip():
            updated.append("")
        updated.append(f"{PIN_KEY}={digest}")
    return updated, replaced


def main() -> int:
    root = _repo_root()
    env_path = root / "backend" / ".env"
    library_path = _privacy_core_library(root)
    if library_path is None:
        print("[*] privacy-core trust pin refresh skipped: shared library not found.")
        return 0

    # Pin the locally built library whether or not private lanes were enabled
    # in .env: most operators turn Wormhole on from the UI, and without a pin
    # the private lanes report "unattested" and refuse privacy claims.
    text = env_path.read_text(encoding="utf-8-sig") if env_path.is_file() else ""
    lines = text.splitlines()
    values = _parse_env(lines)

    digest = hashlib.sha256(library_path.read_bytes()).hexdigest()
    if values.get(PIN_KEY, "").strip().lower() == digest:
        print("[*] privacy-core trust pin already current.")
        return 0

    updated, replaced = _replace_or_append_pin(lines, digest)
    newline = "\r\n" if "\r\n" in text else "\n"
    env_path.write_text(newline.join(updated) + newline, encoding="utf-8")
    action = "refreshed" if replaced else "enrolled"
    print(f"[*] privacy-core trust pin {action} for local shared library.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
