#!/usr/bin/env python3
"""ShadowBroker public bridge: copy finished map data out of the engine.

One direction only. The bridge reads the engine's cached map data over
loopback, keeps the keys that ``viewer/public-layers.json`` marks public,
scrubs them, and writes plain JSON files that a static host can serve. The
public viewer reads those files and nothing else.

What the bridge will never do:
  * talk to an engine that is not on loopback;
  * publish a data key that is not explicitly marked public (new keys the
    engine grows later are withheld until someone lists them);
  * write a file that contains one of the engine's configured secrets or a
    credential-bearing URL: the whole cycle is dropped instead.

Standard library only, so it runs on any Python 3.10+ with no install step.

Usage:
    python viewer/bridge/bridge.py --out /var/www/sb-data
    python viewer/bridge/bridge.py --out ./data --once
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

log = logging.getLogger("sb.bridge")

SCHEMA = 1
HERE = Path(__file__).resolve().parent
DEFAULT_POLICY = HERE.parent / "public-layers.json"
DEFAULT_BACKEND_DIR = HERE.parents[1] / "backend"

# Keys larger than this get their own file so an unchanged heavy layer is not
# re-uploaded and re-downloaded every cycle.
HEAVY_KEY_BYTES = 64 * 1024

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}

# Query parameters and JSON field names that carry credentials.
_SECRET_NAME = re.compile(
    r"(api[_-]?key|apikey|access[_-]?token|auth[_-]?token|token|secret|password|passwd|passcode"
    r"|signature|sig|x-amz-credential|x-amz-signature|x-amz-security-token|authorization)$",
    re.IGNORECASE,
)
# Environment variable names whose values are secrets.
_SECRET_ENV_NAME = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PASSCODE|CREDENTIAL|PRIVATE)", re.IGNORECASE)
_MIN_SECRET_LEN = 8


class BridgeRefusal(RuntimeError):
    """The bridge declined to publish. Nothing was written."""


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------

class Policy:
    def __init__(self, raw: dict[str, Any]):
        if raw.get("schema") != SCHEMA:
            raise BridgeRefusal(f"public-layers.json schema {raw.get('schema')!r} is not {SCHEMA}")
        self.keys: dict[str, dict[str, Any]] = dict(raw.get("keys") or {})
        self.protocol_keys = set(raw.get("protocol_keys") or [])
        self.engine_layers: dict[str, bool] = dict(raw.get("engine_layers") or {})

    @classmethod
    def load(cls, path: Path) -> "Policy":
        return cls(json.loads(path.read_text(encoding="utf-8")))

    def rule(self, key: str) -> dict[str, Any] | None:
        return self.keys.get(key)

    def is_public(self, key: str, tier: str) -> bool:
        rule = self.keys.get(key)
        if not rule or rule.get("public") is not True:
            return False
        return rule.get("tier") in (tier, "both")


# ---------------------------------------------------------------------------
# Scrubbing
# ---------------------------------------------------------------------------

def _url_carries_credentials(value: str) -> bool:
    if "://" not in value or len(value) > 4096:
        return False
    try:
        parts = urlsplit(value)
    except ValueError:
        return False
    if parts.scheme not in ("http", "https", "ws", "wss", "rtsp", "rtmp"):
        return False
    if parts.username or parts.password:
        return True
    for name, _ in parse_qsl(parts.query, keep_blank_values=True):
        if _SECRET_NAME.search(name):
            return True
    return False


def scrub(value: Any, drop_fields: frozenset[str], stats: dict[str, int]) -> Any:
    """Return a copy of ``value`` with credential-bearing content removed.

    * dict fields named like a credential, or listed in ``drop_fields``, are
      removed;
    * strings that are URLs with embedded credentials become "".
    """
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            name = str(k)
            if name in drop_fields or _SECRET_NAME.search(name):
                stats["fields_dropped"] = stats.get("fields_dropped", 0) + 1
                continue
            out[name] = scrub(v, drop_fields, stats)
        return out
    if isinstance(value, list):
        return [scrub(item, drop_fields, stats) for item in value]
    if isinstance(value, str) and _url_carries_credentials(value):
        stats["urls_blanked"] = stats.get("urls_blanked", 0) + 1
        return ""
    return value


def direct_media_ok(item: Any, rule: dict[str, Any]) -> bool:
    """True if a camera-like item can be loaded by a browser straight from its
    own public address: plain https, no credentials, and not a kind that needs
    a relay (stream playlists, sources that need server-side decoding)."""
    if not isinstance(item, dict):
        return False
    url = item.get(str(rule.get("url_field") or "url"))
    if not isinstance(url, str) or not url.lower().startswith("https://"):
        return False
    if _url_carries_credentials(url):
        return False
    lowered = url.lower()
    if any(str(part).lower() in lowered for part in rule.get("drop_url_contains") or ()):
        return False
    kind = str(item.get(str(rule.get("type_field") or "media_type")) or "").lower()
    return kind not in {str(t).lower() for t in rule.get("drop_types") or ()}


def sanitize_tier(payload: dict[str, Any], tier: str, policy: Policy) -> tuple[dict[str, Any], dict[str, Any]]:
    """Keep only public keys of one tier payload. Returns (public, report)."""
    public: dict[str, Any] = {}
    report: dict[str, Any] = {"withheld": [], "unknown": [], "fields_dropped": 0, "urls_blanked": 0}
    for key, value in payload.items():
        if key in policy.protocol_keys:
            continue
        rule = policy.rule(key)
        if rule is None:
            report["unknown"].append(key)
            continue
        if not policy.is_public(key, tier):
            report["withheld"].append(key)
            continue
        only_sources = rule.get("only_sources")
        if only_sources and isinstance(value, list):
            allowed = set(only_sources)
            value = [item for item in value if isinstance(item, dict) and item.get("source") in allowed]
        direct = rule.get("direct_media")
        if direct and isinstance(value, list):
            kept = [item for item in value if direct_media_ok(item, direct)]
            report["items_dropped"] = report.get("items_dropped", 0) + len(value) - len(kept)
            value = kept
        stats: dict[str, int] = {}
        public[key] = scrub(value, frozenset(rule.get("drop_fields") or ()), stats)
        report["fields_dropped"] += stats.get("fields_dropped", 0)
        report["urls_blanked"] += stats.get("urls_blanked", 0)
    return public, report


# ---------------------------------------------------------------------------
# Secret canary
# ---------------------------------------------------------------------------

def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return values
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, raw = line.partition("=")
        name = name.replace("export ", "").strip()
        value = raw.strip().strip("'\"")
        if name and value:
            values[name] = value
    return values


def load_secret_values(env_files: list[Path], environ: dict[str, str] | None = None) -> set[str]:
    """Collect the engine's secret *values* so output can be checked for them.

    They stay in this process's memory. They are only ever compared against
    outgoing bytes; none is logged or written.
    """
    found: set[str] = set()
    sources: list[dict[str, str]] = [_parse_env_file(p) for p in env_files]
    sources.append(dict(os.environ if environ is None else environ))
    for source in sources:
        for name, value in source.items():
            if not _SECRET_ENV_NAME.search(name):
                continue
            value = value.strip()
            if len(value) >= _MIN_SECRET_LEN and not value.lower() in {"changeme", "replace-me"}:
                found.add(value)
    return found


def assert_no_secrets(blob: bytes, secrets: set[str], label: str) -> None:
    for secret in secrets:
        if secret.encode("utf-8") in blob:
            # Never echo the secret, or which one it was.
            raise BridgeRefusal(f"a configured secret value appears in {label}; cycle dropped")


# ---------------------------------------------------------------------------
# Engine access
# ---------------------------------------------------------------------------

def check_engine_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme != "http" or (parts.hostname or "") not in LOOPBACK_HOSTS:
        raise BridgeRefusal(
            f"engine URL {url!r} is not loopback http. The bridge runs on the engine machine and "
            "reads it over 127.0.0.1 only."
        )
    return url.rstrip("/")


def fetch_json(url: str, timeout: float = 60.0) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "sb-bridge"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - loopback only
        if response.status != 200:
            raise urllib.error.URLError(f"HTTP {response.status}")
        data = json.loads(response.read().decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("engine returned a non-object payload")
    return data


# ---------------------------------------------------------------------------
# Publishing
# ---------------------------------------------------------------------------

def _dumps(value: Any) -> bytes:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _digest(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()[:12]


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class DirPublisher:
    """Write files into a directory, atomically, so a reader never sees half a file."""

    def __init__(self, out_dir: Path):
        self.out_dir = out_dir
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def put(self, rel_path: str, blob: bytes) -> None:
        target = self.out_dir / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=".tmp-", dir=str(target.parent))
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(blob)
            os.replace(tmp_name, target)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    def delete(self, rel_path: str) -> None:
        try:
            (self.out_dir / rel_path).unlink()
        except FileNotFoundError:
            pass


class Bridge:
    def __init__(
        self,
        policy: Policy,
        publisher: DirPublisher,
        secrets: set[str],
        fast_s: int = 15,
        slow_s: int = 120,
    ):
        self.policy = policy
        self.publisher = publisher
        self.secrets = secrets
        self.fast_s = fast_s
        self.slow_s = slow_s
        self.seq = 0
        self._bundles: dict[str, dict[str, Any]] = {}
        self._keys: dict[str, dict[str, Any]] = {}
        self._tiers: dict[str, dict[str, Any]] = {}
        self._written: dict[str, str] = {}  # rel_path -> digest last written
        self._freshness: dict[str, Any] = {}
        self._warned_unknown: set[str] = set()

    def _put_if_changed(self, rel_path: str, blob: bytes) -> str:
        digest = _digest(blob)
        if self._written.get(rel_path) != digest:
            self.publisher.put(rel_path, blob)
            self._written[rel_path] = digest
        return digest

    def publish_tier(self, tier: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Sanitize one tier payload and write its files. Returns the report."""
        public, report = sanitize_tier(payload, tier, self.policy)

        new_unknown = [k for k in report["unknown"] if k not in self._warned_unknown]
        if new_unknown:
            self._warned_unknown.update(new_unknown)
            log.warning(
                "withholding %d key(s) not listed in public-layers.json: %s",
                len(new_unknown),
                ", ".join(sorted(new_unknown)),
            )

        # Both tiers report freshness for their own feeds; publish the union so
        # the viewer does not flap between two halves.
        if isinstance(public.get("freshness"), dict):
            self._freshness.update(public["freshness"])
            public["freshness"] = dict(self._freshness)

        bundle: dict[str, Any] = {}
        staged: list[tuple[str, bytes]] = []
        heavy_entries: dict[str, dict[str, Any]] = {}
        for key, value in public.items():
            blob = _dumps(value)
            if len(blob) >= HEAVY_KEY_BYTES:
                rel = f"k/{key}.json"
                staged.append((rel, blob))
                entry: dict[str, Any] = {"f": rel, "v": _digest(blob), "bytes": len(blob), "tier": tier}
                if isinstance(value, (list, dict)):
                    entry["count"] = len(value)
                heavy_entries[key] = entry
            else:
                bundle[key] = value
        bundle_blob = _dumps(bundle)
        bundle_rel = f"{tier}.json"
        staged.append((bundle_rel, bundle_blob))

        # Check everything before writing anything: a leak drops the whole cycle.
        for rel, blob in staged:
            assert_no_secrets(blob, self.secrets, rel)

        for rel, blob in staged:
            self._put_if_changed(rel, blob)

        # A key that shrank back into the bundle no longer has its own file.
        for key, entry in list(self._keys.items()):
            if entry.get("tier") == tier and key not in heavy_entries:
                self.publisher.delete(entry["f"])
                self._written.pop(entry["f"], None)
                del self._keys[key]
        self._keys.update(heavy_entries)
        self._bundles[tier] = {"f": bundle_rel, "v": _digest(bundle_blob), "bytes": len(bundle_blob)}
        self._tiers[tier] = {"at": _now_iso()}
        report["published"] = sorted(public.keys())
        report["bytes"] = sum(len(blob) for _, blob in staged)
        return report

    def write_manifest(self) -> None:
        self.seq += 1
        manifest = {
            "schema": SCHEMA,
            "generated_at": _now_iso(),
            "seq": self.seq,
            "cadence": {"fast_s": self.fast_s, "slow_s": self.slow_s},
            "tiers": self._tiers,
            "bundles": self._bundles,
            "keys": self._keys,
        }
        blob = _dumps(manifest)
        assert_no_secrets(blob, self.secrets, "manifest.json")
        self.publisher.put("manifest.json", blob)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run(args: argparse.Namespace) -> int:
    engine = check_engine_url(args.engine)
    policy = Policy.load(Path(args.policy))
    env_files = [Path(p) for p in (args.secrets_env or [])]
    if not args.no_default_secrets_env:
        env_files += [DEFAULT_BACKEND_DIR / ".env", DEFAULT_BACKEND_DIR / "data" / "operator_keys.env"]
    secrets = load_secret_values(env_files)
    log.info("secret canary armed with %d value(s)", len(secrets))

    bridge = Bridge(policy, DirPublisher(Path(args.out)), secrets, fast_s=args.fast_interval, slow_s=args.slow_interval)

    def cycle(tier: str) -> bool:
        try:
            payload = fetch_json(f"{engine}/api/live-data/{tier}")
            report = bridge.publish_tier(tier, payload)
            bridge.write_manifest()
            log.info(
                "%s: %d keys, %.1f KB, withheld %d, scrubbed %d field(s) %d url(s)",
                tier,
                len(report["published"]),
                report["bytes"] / 1024,
                len(report["withheld"]) + len(report["unknown"]),
                report["fields_dropped"],
                report["urls_blanked"],
            )
            return True
        except BridgeRefusal as exc:
            log.error("%s cycle REFUSED: %s", tier, exc)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            log.warning("%s cycle skipped: %s", tier, exc)
        return False

    if args.once:
        ok_fast = cycle("fast")
        ok_slow = cycle("slow")
        return 0 if (ok_fast and ok_slow) else 1

    next_fast = next_slow = 0.0
    while True:
        now = time.monotonic()
        if now >= next_slow:
            cycle("slow")
            next_slow = now + args.slow_interval
        if now >= next_fast:
            cycle("fast")
            next_fast = now + args.fast_interval
        time.sleep(max(0.2, min(next_fast, next_slow) - time.monotonic()))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Publish ShadowBroker public map data as static files.")
    parser.add_argument("--engine", default=os.environ.get("SB_BRIDGE_ENGINE", "http://127.0.0.1:8011"))
    parser.add_argument("--out", required=True, help="directory the static data files are written to")
    parser.add_argument("--policy", default=str(DEFAULT_POLICY))
    parser.add_argument("--fast-interval", type=int, default=15)
    parser.add_argument("--slow-interval", type=int, default=120)
    parser.add_argument("--once", action="store_true", help="run one fast and one slow cycle, then exit")
    parser.add_argument(
        "--secrets-env",
        action="append",
        help="extra .env file whose secret values must never appear in output (repeatable)",
    )
    parser.add_argument("--no-default-secrets-env", action="store_true", help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except BridgeRefusal as exc:
        log.error("bridge refused to start: %s", exc)
        return 2
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
