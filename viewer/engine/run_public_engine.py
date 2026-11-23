#!/usr/bin/env python3
"""Start the ShadowBroker backend as the *public engine*.

The public engine is an ordinary backend that feeds the look-only public
viewer. It is never exposed itself: it binds to loopback only, and the bridge
(viewer/bridge) copies finished map data out of it.

This launcher forces the settings that keep the engine off the community
networks (Infonet, Wormhole/Tor, Reticulum, Meshtastic MQTT, APRS-IS) no
matter what the surrounding environment or a stray .env says, then starts
uvicorn on 127.0.0.1.

Usage:
    python viewer/engine/run_public_engine.py [--port 8011]

Run it from a checkout with a fresh backend/data folder: an old
meshtastic_mqtt.json overrides the MQTT setting, and an old Tor hostname file
restarts the onion service.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Forced on every start. Real env vars win over backend/.env, and startup
# code that rewrites .env cannot flip these back.
PUBLIC_ENGINE_ENV = {
    "MESH_NODE_MODE": "perimeter",
    "MESH_INFONET_FLEET_JOIN_DISABLED": "true",
    "MESH_PEER_REGISTRY_DISABLED": "true",
    "MESH_BOOTSTRAP_DISABLED": "true",
    "MESH_RNS_ENABLED": "false",
    "MESH_ARTI_ENABLED": "false",
    "MESH_INFONET_RELAY_AUTO_WORMHOLE": "false",
    "MESH_INFONET_ALLOW_CLEARNET_SYNC": "false",
    "MESH_MQTT_ENABLED": "false",
    "APRS_IS_ENABLED": "false",
    "OPENCLAW_ACCESS_TIER": "restricted",
    # No background transport warm-up.
    "MESH_PRIVACY_PREWARM_ENABLE": "false",
    # No peers of any kind.
    "MESH_RELAY_PEERS": "",
    "MESH_BOOTSTRAP_SEED_PEERS": "",
    "MESH_FLEET_SEED_PEERS": "",
    "MESH_DEFAULT_SYNC_PEERS": "",
    "MESH_RNS_PEERS": "",
    # Run the scheduler in UTC on every host, so start-up job offsets are right.
    "TZ": "UTC",
    # Never hand a basemap key to a browser (the viewer uses keyless tiles).
    "CARTO_API_KEY": "",
}



def stale_state_problems(data_dir: Path) -> list[str]:
    """State left by another install that would switch a network back on."""
    import json

    problems: list[str] = []
    mqtt_file = data_dir / "meshtastic_mqtt.json"
    if mqtt_file.exists():
        try:
            enabled = bool(json.loads(mqtt_file.read_text(encoding="utf-8")).get("enabled"))
        except (OSError, ValueError):
            enabled = True  # unreadable: assume the worst
        if enabled:
            problems.append("meshtastic_mqtt.json has the MQTT bridge enabled")
    for hostname in data_dir.rglob("hidden_service/hostname"):
        problems.append(f"a Tor onion service is configured ({hostname.relative_to(data_dir)})")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--port", type=int, default=int(os.environ.get("PUBLIC_ENGINE_PORT", "8011")))
    parser.add_argument(
        "--keys-from",
        default=os.environ.get("PUBLIC_ENGINE_KEYS_FROM", ""),
        help="an .env file to borrow data-feed keys from. Only the names listed under "
        "engine_keys in public-layers.json are read; everything else in the file is ignored.",
    )
    args = parser.parse_args()

    backend_dir = Path(__file__).resolve().parents[2] / "backend"
    if not (backend_dir / "main.py").is_file():
        print(f"backend not found at {backend_dir}", file=sys.stderr)
        return 2

    data_dir = backend_dir / "data"
    problems = stale_state_problems(data_dir)
    if problems:
        print(
            "Refusing to start: backend/data holds state from another install "
            f"({'; '.join(problems)}). The public engine needs a fresh data folder.",
            file=sys.stderr,
        )
        return 2

    policy_path = Path(__file__).resolve().parents[1] / "public-layers.json"
    if args.keys_from:
        loaded = borrow_feed_keys(Path(args.keys_from), policy_path)
        # Names only. Values are never printed or written anywhere.
        print(f"[public-engine] data-feed keys loaded: {', '.join(loaded) or 'none'}")

    for key, value in PUBLIC_ENGINE_ENV.items():
        os.environ[key] = value
    # The dev "bind all interfaces" switch must never apply here.
    os.environ.pop("SHADOWBROKER_DEV_BIND_ALL", None)
    os.environ["BACKEND_PORT"] = str(args.port)

    os.chdir(backend_dir)
    sys.path.insert(0, str(backend_dir))

    import uvicorn

    # Importing main runs the backend's own environment setup first.
    import main as backend_main

    apply_public_layers(policy_path)
    lock_out_private_transports()

    # Loopback only, always: the engine has no public address by design.
    uvicorn.run(backend_main.app, host="127.0.0.1", port=args.port, timeout_keep_alive=120)
    return 0


def borrow_feed_keys(env_file: Path, policy_path: Path) -> list[str]:
    """Load only the listed data-feed keys from another install's .env.

    The public engine needs a few upstream keys (aircraft, ships, fires) to
    have anything to show, but it must not inherit the rest of an owner's
    configuration: the admin key, mesh secrets, AI and paid-tool keys all
    stay behind. Returns the names that were loaded.
    """
    import json

    wanted = list(json.loads(policy_path.read_text(encoding="utf-8")).get("engine_keys") or [])
    loaded: list[str] = []
    try:
        lines = env_file.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        print(f"[public-engine] cannot read {env_file}: {exc}", file=sys.stderr)
        return loaded
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, raw = line.partition("=")
        name = name.replace("export ", "").strip()
        value = raw.strip().strip("'\"")
        if name in wanted and value:
            os.environ[name] = value
            loaded.append(name)
    return loaded


def apply_public_layers(policy_path: Path) -> None:
    """Set the backend's fetcher switches from viewer/public-layers.json.

    Nobody is at the engine's screen to toggle layers, and the viewer cannot
    (it has no route back), so the published set is fixed at start.
    """
    import json

    from services.fetchers._store import active_layers, bump_active_layers_version

    wanted = json.loads(policy_path.read_text(encoding="utf-8")).get("engine_layers") or {}
    unknown = sorted(key for key in wanted if key not in active_layers)
    if unknown:
        print(f"public-layers.json names unknown engine layers: {', '.join(unknown)}", file=sys.stderr)
    for key, value in wanted.items():
        if key in active_layers:
            active_layers[key] = bool(value)
    # Any switch the policy does not mention stays off: new layers are private
    # until someone lists them.
    for key in active_layers:
        if key not in wanted:
            active_layers[key] = False
    bump_active_layers_version()


def lock_out_private_transports() -> None:
    """Make it impossible for this process to launch Wormhole or Tor.

    The public engine never needs either. Rather than rely on settings alone,
    their two launch points are disabled in this process; every caller goes
    through them, so nothing can start one here. Nothing in backend/ is
    edited, and a normal ShadowBroker install is unaffected.
    """
    from services import tor_hidden_service, wormhole_supervisor

    wormhole_supervisor._installed = lambda: False  # type: ignore[assignment]

    def _tor_disabled(self, target_port: int = 8000) -> dict:
        return {"ok": False, "detail": "Tor is disabled on the public engine"}

    tor_hidden_service.TorHiddenService.start = _tor_disabled  # type: ignore[method-assign]


if __name__ == "__main__":
    raise SystemExit(main())
