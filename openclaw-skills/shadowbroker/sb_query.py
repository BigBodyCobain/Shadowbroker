"""ShadowBroker query functions - core API interaction for OpenClaw.

This module provides all the functions OpenClaw needs to interact with
the ShadowBroker OSINT platform.

For local access (same machine), no authentication is needed.
For remote access, set SHADOWBROKER_HMAC_SECRET to enable HMAC-signed requests.

Usage (inside an OpenClaw skill):
    from sb_query import ShadowBrokerClient
    sb = ShadowBrokerClient()
    data = await sb.get_telemetry()
    await sb.place_pin(34.05, -118.24, "UAP Sighting", category="anomaly")

Remote usage:
    import os
    os.environ["SHADOWBROKER_URL"] = "https://your-server.com:8000"
    os.environ["SHADOWBROKER_HMAC_SECRET"] = "your-hmac-secret-here"
    sb = ShadowBrokerClient()
"""

import asyncio
import hashlib
import hmac
import json as json_mod
import math
import os
import secrets
import time
from typing import Any, Optional

try:
    import httpx
except ImportError:
    httpx = None  # Will use requests as fallback


SB_BASE = os.environ.get("SHADOWBROKER_URL", "http://127.0.0.1:8000")


class ShadowBrokerClient:
    """Client for the ShadowBroker REST API.

    Supports both local (no auth) and remote (HMAC-signed) connections.
    Set SHADOWBROKER_HMAC_SECRET env var to enable remote authentication.
    """

    def __init__(self, base_url: str = SB_BASE, hmac_secret: str = ""):
        self.base = base_url.rstrip("/")
        self._hmac_secret = hmac_secret or os.environ.get("SHADOWBROKER_HMAC_SECRET", "")
        self._client = None
        # Version tracking for incremental updates
        self._last_data_version: int | None = None
        # Per-layer version tracking — populated by SSE stream or
        # get_layer_slice responses.  Maps layer name → server version.
        self._layer_versions: dict[str, int] = {}
        # Layers for which we have actually received data (not just version
        # numbers from SSE).  Only these are safe to use in
        # since_layer_versions — sending a version for a layer we never
        # fetched causes the server to skip it ("no change") even though
        # the agent has never seen the data.
        self._fetched_layers: set[str] = set()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
        return False

    def __del__(self):
        if self._client is not None:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.close())
            except RuntimeError:
                pass

    def _sign_headers(self, method: str, path: str, body: bytes = b"") -> dict[str, str]:
        """Generate HMAC authentication headers for a request.

        The signing input includes a SHA-256 digest of the request body so
        that body-bearing requests cannot be modified without invalidating
        the signature.  Pass b"" (or omit) for bodyless requests.

        Returns empty dict if no HMAC secret is configured (local mode).
        """
        if not self._hmac_secret:
            return {}

        ts = str(int(time.time()))
        nonce = secrets.token_hex(16)  # 32 char random hex
        body_digest = hashlib.sha256(body).hexdigest()
        message = f"{method.upper()}|{path}|{ts}|{nonce}|{body_digest}"
        signature = hmac.new(
            self._hmac_secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        return {
            "X-SB-Timestamp": ts,
            "X-SB-Nonce": nonce,
            "X-SB-Signature": signature,
        }

    # Patterns that look like LLM API keys — never send these to ShadowBroker.
    _SENSITIVE_KEY_PREFIXES = (
        "sk-",       # OpenAI
        "key-",      # Generic
        "sk-ant-",   # Anthropic
        "AIza",      # Google/Gemini
        "xai-",      # xAI/Grok
        "Bearer ",   # Auth tokens
    )
    _SENSITIVE_ENV_NAMES = frozenset({
        "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY",
        "GEMINI_API_KEY", "XAI_API_KEY", "GROQ_API_KEY",
        "TOGETHER_API_KEY", "MISTRAL_API_KEY", "COHERE_API_KEY",
        "HUGGINGFACE_TOKEN", "HF_TOKEN", "REPLICATE_API_TOKEN",
    })

    @classmethod
    def _sanitize_payload(cls, data: dict) -> dict:
        """Scrub LLM API keys from payloads before sending to ShadowBroker.

        If the LLM is tricked via prompt injection into including its own
        API credentials in a data payload, this filter catches it.
        Never sends values that look like API keys.
        """
        if not isinstance(data, dict):
            return data
        cleaned = {}
        for k, v in data.items():
            if isinstance(v, str):
                # Block values that look like API keys
                stripped = v.strip()
                if any(stripped.startswith(prefix) for prefix in cls._SENSITIVE_KEY_PREFIXES):
                    cleaned[k] = "[REDACTED — possible API key detected]"
                    continue
                # Block env var names that are LLM keys
                if k.upper() in cls._SENSITIVE_ENV_NAMES:
                    cleaned[k] = "[REDACTED]"
                    continue
            elif isinstance(v, dict):
                v = cls._sanitize_payload(v)
            cleaned[k] = v
        return cleaned

    def _get_client(self):
        if self._client is None:
            if httpx:
                self._client = httpx.AsyncClient(timeout=15, base_url=self.base)
            else:
                raise RuntimeError("httpx not available - install it: pip install httpx")
        return self._client

    def _serialize_body(self, kwargs: dict) -> bytes:
        """Serialize the request body to deterministic bytes for HMAC signing.

        If ``json`` is present in *kwargs*, it is serialized to bytes,
        removed from *kwargs*, and replaced with ``content`` + an explicit
        ``Content-Type`` header so the exact bytes sent over the wire are
        the same bytes that were signed.

        Returns the raw body bytes (b"" when there is no body).
        """
        if "json" in kwargs:
            payload = kwargs.pop("json")
            if isinstance(payload, dict):
                payload = self._sanitize_payload(payload)
            body_bytes = json_mod.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
            kwargs["content"] = body_bytes
            kwargs.setdefault("headers", {})
            kwargs["headers"]["Content-Type"] = "application/json"
            return body_bytes
        if "content" in kwargs:
            raw = kwargs["content"]
            return raw if isinstance(raw, bytes) else raw.encode("utf-8")
        return b""

    async def _get(self, path: str, **kwargs) -> httpx.Response:
        """GET with optional HMAC signing."""
        headers = self._sign_headers("GET", path)
        r = await self._get_client().get(path, headers=headers, **kwargs)
        r.raise_for_status()
        return r

    async def _post(self, path: str, **kwargs) -> httpx.Response:
        """POST with optional HMAC signing + body-bound authentication."""
        body_bytes = self._serialize_body(kwargs)
        headers = self._sign_headers("POST", path, body_bytes)
        extra_headers = kwargs.pop("headers", {})
        merged = {**headers, **extra_headers}
        r = await self._get_client().post(path, headers=merged, **kwargs)
        r.raise_for_status()
        return r

    async def _delete(self, path: str, **kwargs) -> httpx.Response:
        """DELETE with optional HMAC signing."""
        body_bytes = self._serialize_body(kwargs)
        headers = self._sign_headers("DELETE", path, body_bytes)
        extra_headers = kwargs.pop("headers", {})
        merged = {**headers, **extra_headers}
        r = await self._get_client().delete(path, headers=merged, **kwargs)
        r.raise_for_status()
        return r

    async def _put(self, path: str, **kwargs) -> httpx.Response:
        """PUT with optional HMAC signing + body-bound authentication."""
        body_bytes = self._serialize_body(kwargs)
        headers = self._sign_headers("PUT", path, body_bytes)
        extra_headers = kwargs.pop("headers", {})
        merged = {**headers, **extra_headers}
        r = await self._get_client().put(path, headers=merged, **kwargs)
        r.raise_for_status()
        return r

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    # ── Command Channel (Bidirectional) ────────────────────────────────

    async def send_command(self, cmd: str, args: dict | None = None) -> dict:
        """Send a command through the channel.

        Commands are sent via HMAC-authenticated HTTP with body-integrity
        binding. Wire privacy relies on TLS. E2EE (MLS) is planned but
        not yet available for this channel.

        Args:
            cmd: Command name (e.g. 'get_summary', 'place_pin')
            args: Optional arguments for the command

        Returns:
            {ok, command_id, tier, status, result}
        """
        payload = {"cmd": cmd, "args": args or {}}
        r = await self._post("/api/ai/channel/command", json=payload)
        return r.json()

    async def poll_channel(self) -> dict:
        """Poll for command responses and tasks from ShadowBroker.

        Returns:
            {ok, commands: [...], tasks: [...], commands_count, tasks_count}
            - commands: Completed command results (destructive read)
            - tasks: Pending tasks pushed by the operator (alerts, requests, etc.)
        """
        r = await self._post("/api/ai/channel/poll")
        return r.json()

    async def channel_status(self) -> dict:
        """Get command channel status.

        Returns:
            {ok, tier, reason, transport, pending_commands, pending_tasks, stats}
        """
        r = await self._get("/api/ai/channel/status")
        return r.json()

    async def send_batch(self, commands: list[dict]) -> dict:
        """Send multiple commands in a single HTTP round-trip.

        Commands execute concurrently on the server — independent queries
        (find_flights + search_news + entities_near) overlap instead of
        serialising behind N separate HTTP calls.  Max 20 per batch.

        Args:
            commands: List of {"cmd": str, "args": dict} dicts.

        Returns:
            {ok, results: [...], tier, count}
        """
        payload = {"commands": [{"cmd": c["cmd"], "args": c.get("args", {})} for c in commands]}
        r = await self._post("/api/ai/channel/batch", json=payload)
        return r.json()

    async def get_layer_slice(
        self,
        layers: list[str],
        limit_per_layer: int | None = None,
        incremental: bool = True,
    ) -> dict:
        """Fetch specific layers with per-layer incremental support.

        When incremental=True the client sends its per-layer version map
        (populated by previous responses and/or SSE layer_changed events).
        The server only serializes layers whose version is newer than what
        the agent already holds — unchanged layers are omitted entirely.

        Falls back to the global ``since_version`` counter if no per-layer
        versions are available yet (first call before SSE is connected).

        Args:
            layers: Layer names (e.g. ["military_flights", "ships"]).
            limit_per_layer: Optional cap per layer.
            incremental: If True, send version info to skip unchanged data.

        Returns:
            {version, layer_versions, changed, layers: {...}, ...}
        """
        args: dict[str, Any] = {"layers": layers}
        if limit_per_layer is not None:
            args["limit_per_layer"] = limit_per_layer

        if incremental:
            # Prefer per-layer versions — but ONLY for layers we have
            # actually fetched data for.  SSE populates _layer_versions
            # with the server's current versions at connect time; using
            # those blindly would make the server think we already have
            # the data and return empty results.
            relevant = {
                l: self._layer_versions[l]
                for l in layers
                if l in self._layer_versions and l in self._fetched_layers
            }
            if relevant:
                args["since_layer_versions"] = relevant
            elif self._last_data_version is not None:
                args["since_version"] = self._last_data_version

        result = await self.send_command("get_layer_slice", args)

        # Update version tracking from the response
        inner = result.get("result", {})
        data = inner.get("data", {}) if isinstance(inner, dict) else {}
        if isinstance(data, dict):
            v = data.get("version")
            if v is not None:
                self._last_data_version = v
            # Per-layer versions returned by server
            lv = data.get("layer_versions")
            if isinstance(lv, dict):
                self._layer_versions.update(lv)
            # Mark layers that actually returned data as fetched so future
            # incremental calls can safely send since_layer_versions for them.
            resp_layers = data.get("layers")
            if isinstance(resp_layers, dict):
                for lname, ldata in resp_layers.items():
                    if ldata:  # non-empty payload
                        self._fetched_layers.add(lname)
        return result

    # ── Core Telemetry ────────────────────────────────────────────────

    async def get_telemetry(self) -> dict:
        """Get all live telemetry from /api/live-data/fast (full dashboard data)."""
        r = await self._get("/api/live-data/fast")
        return r.json()

    async def get_slow_telemetry(self) -> dict:
        """Get slow-cycle data (stocks, oil, prediction markets)."""
        r = await self._get("/api/live-data/slow")
        return r.json()

    async def get_sigint_totals(self) -> dict:
        """Get SIGINT totals (APRS, Meshtastic, JS8Call node counts)."""
        data = await self.get_telemetry()
        return data.get("sigint_totals", {})

    async def get_prediction_markets(self) -> list:
        """Get prediction market data (Polymarket/Kalshi)."""
        data = await self.get_slow_telemetry()
        return data.get("prediction_markets", [])

    # ── AI Intel Status ───────────────────────────────────────────────

    async def ai_status(self) -> dict:
        """Check AI Intel subsystem health."""
        r = await self._get("/api/ai/status")
        return r.json()

    # ── Pin Placement ─────────────────────────────────────────────────

    async def place_pin(
        self,
        lat: float,
        lng: float,
        label: str,
        category: str = "custom",
        *,
        color: str = "",
        description: str = "",
        source: str = "openclaw",
        source_url: str = "",
        confidence: float = 1.0,
        ttl_hours: float = 0,
        metadata: Optional[dict] = None,
    ) -> dict:
        """Place a single pin on the AI Intel map layer."""
        if not (-90 <= lat <= 90):
            raise ValueError(f"Invalid latitude {lat}: must be between -90 and 90")
        if not (-180 <= lng <= 180):
            raise ValueError(f"Invalid longitude {lng}: must be between -180 and 180")
        r = await self._post("/api/ai/pins", json={
            "lat": lat,
            "lng": lng,
            "label": label,
            "category": category,
            "color": color,
            "description": description,
            "source": source,
            "source_url": source_url,
            "confidence": confidence,
            "ttl_hours": ttl_hours,
            "metadata": metadata or {},
        })
        r.raise_for_status()
        return r.json()

    async def place_pins_batch(self, pins: list[dict]) -> dict:
        """Place multiple pins at once (max 100)."""
        r = await self._post("/api/ai/pins/batch", json={"pins": pins})
        return r.json()

    async def get_pins(self, category: str = "", source: str = "", limit: int = 500) -> dict:
        """List AI Intel pins with optional filters."""
        params = {"limit": limit}
        if category:
            params["category"] = category
        if source:
            params["source"] = source
        r = await self._get("/api/ai/pins", params=params)
        return r.json()

    async def clear_pins(self, category: str = "", source: str = "") -> dict:
        """Clear pins - all, or filtered by category/source."""
        params = {}
        if category:
            params["category"] = category
        if source:
            params["source"] = source
        r = await self._delete("/api/ai/pins", params=params)
        return r.json()

    # ── Satellite Imagery ─────────────────────────────────────────────

    async def get_satellite_images(
        self,
        lat: float,
        lng: float,
        count: int = 3,
    ) -> dict:
        """Get latest Sentinel-2 satellite imagery for a location."""
        r = await self._get("/api/ai/satellite-images", params={
            "lat": lat, "lng": lng, "count": count,
        })
        r.raise_for_status()
        return r.json()

    # ── News & GDELT ──────────────────────────────────────────────────

    async def get_news_near(
        self,
        lat: float,
        lng: float,
        radius: float = 500,
    ) -> dict:
        """Get GDELT incidents and news near a coordinate."""
        r = await self._get("/api/ai/news-near", params={
            "lat": lat, "lng": lng, "radius": radius,
        })
        r.raise_for_status()
        return r.json()

    # ── Geocoding ─────────────────────────────────────────────────────

    async def geocode(self, query: str) -> list[dict]:
        """Geocode a place name to coordinates."""
        r = await self._get("/api/geocode/search", params={"q": query})
        return r.json()

    # ── Native Layer Injection ────────────────────────────────────────

    async def inject_data(
        self,
        layer: str,
        items: list[dict],
        mode: str = "append",
    ) -> dict:
        """Inject custom data into a native ShadowBroker layer."""
        r = await self._post("/api/ai/inject", json={
            "layer": layer,
            "items": items,
            "mode": mode,
        })
        r.raise_for_status()
        return r.json()

    async def clear_injected(self, layer: str = "") -> dict:
        """Remove user-injected data from native layers."""
        params = {}
        if layer:
            params["layer"] = layer
        r = await self._delete("/api/ai/inject", params=params)
        return r.json()

    # ── Wormhole / InfoNet ────────────────────────────────────────────

    async def join_wormhole(self) -> dict:
        """Create a Wormhole identity and join the network."""
        r = await self._post("/api/wormhole/join")
        return r.json()

    async def sign_event(self, event_type: str, payload: dict) -> dict:
        """Sign an event with the Wormhole Ed25519 key."""
        r = await self._post("/api/wormhole/sign", json={
            "event_type": event_type,
            "payload": payload,
        })
        r.raise_for_status()
        return r.json()

    async def post_to_infonet(self, message: str, event_type: str = "message") -> dict:
        """Post a signed event to the InfoNet ledger."""
        signed = await self.sign_event(event_type, {"message": message})
        r = await self._post("/api/mesh/infonet/ingest", json={
            "events": [signed],
        })
        r.raise_for_status()
        return r.json()

    async def read_infonet(self, limit: int = 20, gate: str = "") -> dict:
        """Read recent InfoNet messages."""
        params = {"limit": limit}
        if gate:
            params["gate"] = gate
        r = await self._get("/api/mesh/infonet/messages", params=params)
        return r.json()

    async def list_gates(self) -> list:
        """List available encrypted gate channels."""
        r = await self._get("/api/mesh/gate/list")
        return r.json()

    async def post_to_gate(self, gate_id: str, message: str) -> dict:
        """Compose and post an MLS-encrypted message to a gate."""
        compose = await self._post("/api/wormhole/gate/message/compose", json={
            "gate_id": gate_id,
            "plaintext": message,
        })
        compose.raise_for_status()
        envelope = compose.json()

        post = await self._post(f"/api/mesh/gate/{gate_id}/message", json=envelope)
        post.raise_for_status()
        return post.json()

    # ── Meshtastic ────────────────────────────────────────────────────

    async def listen_mesh(self, region: str = "US", limit: int = 20) -> dict:
        """Listen to recent Meshtastic radio signals."""
        r = await self._get("/api/mesh/listen", params={
            "root": region, "limit": limit,
        })
        r.raise_for_status()
        return r.json()

    async def send_mesh(self, region: str, message: str) -> dict:
        """Transmit a signed message on Meshtastic LongFast channel."""
        signed = await self.sign_event("mesh_broadcast", {"message": message})
        r = await self._post("/api/mesh/send", json={
            "root": region,
            "message": message,
            "signed_event": signed,
        })
        r.raise_for_status()
        return r.json()

    # ── Full Telemetry (fast + slow merged) ─────────────────────────────

    async def get_full_telemetry(self) -> dict:
        """Get ALL telemetry: fast-tier + slow-tier merged into one dict.

        This gives the agent access to every layer ShadowBroker tracks:
        flights, ships, SIGINT, satellites, GDELT, CrowdThreat, LiveUAMap,
        UAP sightings, wastewater, FIRMS fires, earthquakes, weather, etc.
        """
        fast = await self.get_telemetry()
        slow = await self.get_slow_telemetry()
        # Merge slow into fast (fast wins on key collisions)
        merged = {**slow, **fast}
        return merged

    # ── Helper: Proximity Search ──────────────────────────────────────

    @staticmethod
    def haversine_miles(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
        """Great-circle distance in miles."""
        for val in (lat1, lng1, lat2, lng2):
            if val is None or (isinstance(val, float) and math.isnan(val)):
                return float("inf")
        R = 3958.8
        dlat = math.radians(lat2 - lat1)
        dlng = math.radians(lng2 - lng1)
        a = (math.sin(dlat / 2) ** 2 +
             math.cos(math.radians(lat1)) *
             math.cos(math.radians(lat2)) *
             math.sin(dlng / 2) ** 2)
        return R * 2 * math.asin(math.sqrt(a))

    def _filter_nearby(
        self,
        items: list,
        center_lat: float,
        center_lng: float,
        radius_miles: float,
        lat_key: str = "lat",
        lng_key: str = "lng",
    ) -> list:
        """Generic proximity filter — returns items within radius, sorted by distance."""
        nearby = []
        for item in items:
            i_lat = item.get(lat_key)
            i_lng = item.get(lng_key) or item.get("lon") or item.get("longitude")
            if i_lat is None or i_lng is None:
                continue
            try:
                d = self.haversine_miles(center_lat, center_lng, float(i_lat), float(i_lng))
            except (ValueError, TypeError):
                continue
            if d <= radius_miles:
                item["distance_miles"] = round(d, 1)
                nearby.append(item)
        return sorted(nearby, key=lambda x: x.get("distance_miles", 0))

    async def get_near_me(
        self,
        lat: float,
        lng: float,
        radius_miles: float = 100,
        entity_types: list[str] | None = None,
        limit: int = 50,
    ) -> dict:
        """Get ALL telemetry within a radius of the user's location.

        Uses server-side entities_near for the heavy spatial filtering
        (no bulk download), plus a batched command for news and correlations.
        This is orders of magnitude faster than the old approach of
        downloading all telemetry and filtering client-side.

        Each item gets a `distance_km` field and results are sorted by proximity.
        """
        radius_km = radius_miles * 1.60934

        # All entity types the server supports for spatial search
        all_types = entity_types or [
            "tracked_flights", "military_flights", "private_jets",
            "commercial_flights", "ships", "uavs", "satellites",
            "earthquakes", "liveuamap", "crowdthreat", "uap_sightings",
            "wastewater", "firms_fires", "weather_alerts",
        ]

        # Use batch to run entities_near + news_near + correlations concurrently
        batch_cmds = [
            {"cmd": "entities_near", "args": {
                "lat": lat, "lng": lng,
                "radius_km": radius_km,
                "entity_types": all_types,
                "limit": limit,
            }},
            {"cmd": "search_news", "args": {
                "query": "", "limit": 10, "include_gdelt": True,
            }},
            {"cmd": "get_correlations", "args": {}},
        ]

        batch_result = await self.send_batch(batch_cmds)
        batch_results = batch_result.get("results", [])

        # Parse the three concurrent results
        entities = {}
        news = []
        correlations = []

        for r in batch_results:
            cmd = r.get("cmd", "")
            inner = r.get("result", {})
            if not inner.get("ok"):
                continue
            data = inner.get("data", {})

            if cmd == "entities_near":
                # Group results by source_layer
                for item in (data.get("results") or []):
                    layer = item.get("source_layer", "other")
                    entities.setdefault(layer, []).append(item)
            elif cmd == "search_news":
                news = data if isinstance(data, list) else data.get("results", [])
            elif cmd == "get_correlations":
                correlations = data if isinstance(data, list) else []

        return {
            **entities,
            "news": news,
            "correlations": correlations,
            "center": {"lat": lat, "lng": lng},
            "radius_miles": radius_miles,
        }

    # ── Reports & Summaries ───────────────────────────────────────

    async def get_report(self) -> dict:
        """Generate a full intelligence report from current telemetry."""
        r = await self._get("/api/ai/report")
        return r.json()

    async def get_summary(self) -> dict:
        """Lightweight telemetry summary - counts only."""
        r = await self._get("/api/ai/summary")
        return r.json()

    # ── Encrypted DMs ─────────────────────────────────────────────

    async def send_encrypted_dm(self, recipient_pubkey: str, message: str) -> dict:
        """Send an E2E encrypted direct message to another Wormhole identity."""
        r = await self._post("/api/wormhole/dm/send", json={
            "recipient": recipient_pubkey,
            "plaintext": message,
        })
        r.raise_for_status()
        return r.json()

    async def read_encrypted_dms(self, limit: int = 20) -> list:
        """Read received encrypted direct messages."""
        r = await self._get("/api/wormhole/dm/inbox", params={"limit": limit})
        return r.json()

    # ── Dead Drop ─────────────────────────────────────────────────

    async def dead_drop_leave(self, location_hash: str, payload: str) -> dict:
        """Leave a dead-drop at a location (hashed coordinates)."""
        signed = await self.sign_event("dead_drop", {
            "location_hash": location_hash,
            "payload": payload,
        })
        r = await self._post("/api/mesh/deaddrops", json=signed)
        return r.json()

    async def dead_drop_check(self, location_hash: str) -> list:
        """Check for dead-drops at a location."""
        r = await self._get("/api/mesh/deaddrops", params={
            "location_hash": location_hash,
        })
        r.raise_for_status()
        return r.json()

    # ── Time Machine ──────────────────────────────────────────────

    async def tm_take_snapshot(self, layers: list[str] = None, profile: str = "") -> dict:
        """Take a Time Machine snapshot of current telemetry."""
        body = {}
        if layers:
            body["layers"] = layers
        if profile:
            body["profile"] = profile
        r = await self._post("/api/ai/timemachine/snapshot", json=body)
        return r.json()

    async def tm_list_snapshots(
        self, layer: str = "", since: float = 0, until: float = 0, limit: int = 20
    ) -> dict:
        """List available snapshots."""
        params = {"limit": limit}
        if layer:
            params["layer"] = layer
        if since:
            params["since"] = since
        if until:
            params["until"] = until
        r = await self._get("/api/ai/timemachine/snapshots", params=params)
        return r.json()

    async def tm_get_snapshot(self, snapshot_id: str, layer: str = "") -> dict:
        """Retrieve a specific snapshot's full data."""
        params = {}
        if layer:
            params["layer"] = layer
        r = await self._get(
            f"/api/ai/timemachine/snapshot/{snapshot_id}", params=params
        )
        r.raise_for_status()
        return r.json()

    async def tm_diff(self, snapshot_a: str, snapshot_b: str, layer: str) -> dict:
        """Compare two snapshots for a specific layer."""
        r = await self._get("/api/ai/timemachine/diff", params={
            "snapshot_a": snapshot_a,
            "snapshot_b": snapshot_b,
            "layer": layer,
        })
        r.raise_for_status()
        return r.json()

    async def tm_get_config(self) -> dict:
        """Get Time Machine configuration."""
        r = await self._get("/api/ai/timemachine/config")
        return r.json()

    async def tm_set_config(self, preset: str = "", **kwargs) -> dict:
        """Update Time Machine configuration."""
        body = {}
        if preset:
            body["preset"] = preset
        body.update(kwargs)
        r = await self._put("/api/ai/timemachine/config", json=body)
        return r.json()

    async def tm_clear(self, before: float = 0) -> dict:
        """Clear snapshots. If before=unix_ts, only clears older ones."""
        params = {}
        if before:
            params["before"] = before
        r = await self._delete("/api/ai/timemachine/snapshots", params=params)
        return r.json()

    # ── Correlation Alerts ────────────────────────────────────────────

    async def get_correlations(self) -> list:
        """Get active multi-layer correlation alerts.

        Returns a list of correlation alerts — each has type, severity,
        lat/lng, score, and drivers (the layers that triggered it).
        Types: rf_anomaly, military_buildup, infra_cascade.
        """
        payload = {"cmd": "get_correlations", "args": {}}
        r = await self._post("/api/ai/channel/command", json=payload)
        data = r.json()
        if data.get("ok") and data.get("result", {}).get("ok"):
            return data["result"].get("data", [])
        return []

    # ── ALPR / Surveillance Cameras ──────────────────────────────────

    async def get_alpr_cameras(self, limit: int = 500) -> list:
        """Get ALPR/surveillance camera locations from the CCTV layer.

        Filters the CCTV feed for ALPR-tagged cameras only.
        Returns locations (no live feeds or detection data).
        """
        data = await self.get_telemetry()
        cctv = data.get("cctv", [])
        alpr = [
            c for c in cctv
            if str(c.get("id", "")).startswith("ALPR-")
            or "alpr" in str(c.get("direction_facing", "")).lower()
        ]
        return alpr[:limit]

    # ── AI News & Correlation Endpoints ──
    async def news_summary(self) -> dict:
        """Get AI-generated summary of current news articles."""
        r = await self._get("/api/ai/news/summary")
        return r.json()

    async def correlation_explain(self) -> dict:
        """Get structured intelligence explanations for active correlation alerts."""
        r = await self._get("/api/ai/correlations/explain")
        return r.json()

    # ── SAR (Synthetic Aperture Radar) Layer ──────────────────────────
    # Two-mode design:
    #   Mode A — free Sentinel-1 catalog from ASF (default-on, no account)
    #   Mode B — pre-processed anomalies from OPERA/EGMS/GFM/EMS/UNOSAT
    #            (opt-in, free Earthdata account, two-step enable)
    #
    # When Mode B is off, sar_status() returns a structured `help` block
    # with the signup URLs the agent should paste to the user instead of
    # telling them to "search for it".

    async def sar_status(self) -> dict:
        """Return SAR layer status + onboarding help.

        When Mode B is disabled the response includes ``data.products.help``
        with a step-by-step list of signup URLs (Earthdata, Copernicus, etc).
        Always check this before answering SAR questions so you can show
        the user the in-app links.
        """
        payload = {"cmd": "sar_status", "args": {}}
        r = await self._post("/api/ai/channel/command", json=payload)
        data = r.json()
        if data.get("ok") and data.get("result", {}).get("ok"):
            return data["result"]
        # Fall back to the public router so non-OpenClaw clients can use it too.
        try:
            r2 = await self._get("/api/sar/status")
            return r2.json()
        except Exception:
            return {"ok": False, "data": {}}

    async def sar_anomalies_recent(
        self, kind: str = "", aoi_id: str = "", limit: int = 50
    ) -> list:
        """Recent Mode B anomalies (deformation, flood, damage, vegetation).

        Returns an empty list if Mode B is not enabled — call sar_status()
        to find out what to ask the user for.
        """
        payload = {
            "cmd": "sar_anomalies_recent",
            "args": {"kind": kind, "aoi_id": aoi_id, "limit": limit},
        }
        r = await self._post("/api/ai/channel/command", json=payload)
        data = r.json()
        if data.get("ok") and data.get("result", {}).get("ok"):
            return data["result"].get("data", [])
        return []

    async def sar_anomalies_near(
        self, lat: float, lng: float, radius_km: float = 50, kind: str = "", limit: int = 25
    ) -> list:
        """Anomalies whose center sits within radius_km of (lat, lng)."""
        payload = {
            "cmd": "sar_anomalies_near",
            "args": {
                "lat": lat, "lng": lng, "radius_km": radius_km,
                "kind": kind, "limit": limit,
            },
        }
        r = await self._post("/api/ai/channel/command", json=payload)
        data = r.json()
        if data.get("ok") and data.get("result", {}).get("ok"):
            return data["result"].get("data", [])
        return []

    async def sar_scene_search(self, aoi_id: str = "", limit: int = 50) -> list:
        """Mode A scene catalog — Sentinel-1 passes that touched the AOI."""
        payload = {
            "cmd": "sar_scene_search",
            "args": {"aoi_id": aoi_id, "limit": limit},
        }
        r = await self._post("/api/ai/channel/command", json=payload)
        data = r.json()
        if data.get("ok") and data.get("result", {}).get("ok"):
            return data["result"].get("data", [])
        return []

    async def sar_coverage_for_aoi(self, aoi_id: str = "") -> list:
        """Per-AOI scene counts and rough next-pass estimates."""
        payload = {
            "cmd": "sar_coverage_for_aoi",
            "args": {"aoi_id": aoi_id},
        }
        r = await self._post("/api/ai/channel/command", json=payload)
        data = r.json()
        if data.get("ok") and data.get("result", {}).get("ok"):
            return data["result"].get("data", [])
        return []

    async def sar_aoi_list(self) -> list:
        """Return all operator-defined SAR AOIs."""
        payload = {"cmd": "sar_aoi_list", "args": {}}
        r = await self._post("/api/ai/channel/command", json=payload)
        data = r.json()
        if data.get("ok") and data.get("result", {}).get("ok"):
            return data["result"].get("data", [])
        return []

    async def sar_aoi_add(
        self, id: str, name: str, center_lat: float, center_lon: float,
        radius_km: float = 25.0, description: str = "", category: str = "watchlist",
        polygon: list | None = None,
    ) -> dict:
        """Create or replace a SAR AOI."""
        args = {
            "id": id, "name": name,
            "center_lat": center_lat, "center_lon": center_lon,
            "radius_km": radius_km, "description": description,
            "category": category,
        }
        if polygon:
            args["polygon"] = polygon
        payload = {"cmd": "sar_aoi_add", "args": args}
        r = await self._post("/api/ai/channel/command", json=payload)
        data = r.json()
        if data.get("ok") and data.get("result", {}).get("ok"):
            return data["result"].get("data", {})
        return {}

    async def sar_aoi_remove(self, aoi_id: str) -> dict:
        """Remove a SAR AOI by id."""
        payload = {"cmd": "sar_aoi_remove", "args": {"id": aoi_id}}
        r = await self._post("/api/ai/channel/command", json=payload)
        data = r.json()
        if data.get("ok") and data.get("result", {}).get("ok"):
            return data["result"].get("data", {})
        return {}

    async def sar_pin_from_anomaly(
        self, anomaly_id: str, label: str = "", description: str = ""
    ) -> dict:
        """Promote a SAR anomaly into an AI Intel pin on the dashboard.

        The pin metadata preserves the anomaly's evidence_hash so other
        nodes can verify lineage.
        """
        payload = {
            "cmd": "sar_pin_from_anomaly",
            "args": {"anomaly_id": anomaly_id, "label": label, "description": description},
        }
        r = await self._post("/api/ai/channel/command", json=payload)
        data = r.json()
        if data.get("ok") and data.get("result", {}).get("ok"):
            return data["result"].get("data", {})
        return {}

    async def sar_watch_anomaly(
        self, aoi_id: str, kind: str = "", min_magnitude: float = 0.0, label: str = ""
    ) -> dict:
        """Add a watchdog rule for SAR anomalies in a specific AOI."""
        payload = {
            "cmd": "sar_watch_anomaly",
            "args": {
                "aoi_id": aoi_id, "kind": kind,
                "min_magnitude": min_magnitude, "label": label,
            },
        }
        r = await self._post("/api/ai/channel/command", json=payload)
        data = r.json()
        if data.get("ok") and data.get("result", {}).get("ok"):
            return data["result"].get("data", {})
        return {}

    async def sar_pin_click(self, anomaly_id: str) -> dict:
        """Fetch the full detail payload shown when a user clicks a SAR pin.

        Returns the anomaly record plus its AOI metadata and the most recent
        scenes that cover the same AOI — the same shape the map popup renders.
        """
        payload = {
            "cmd": "sar_pin_click",
            "args": {"anomaly_id": anomaly_id},
        }
        r = await self._post("/api/ai/channel/command", json=payload)
        data = r.json()
        if data.get("ok") and data.get("result", {}).get("ok"):
            return data["result"].get("data", {})
        return {}

    async def sar_focus_aoi(self, aoi_id: str, zoom: float = 8.0) -> dict:
        """Fly the operator's map to the center of an AOI.

        Queues a fly_to action that the frontend picks up via useAgentActions
        and passes to the map's flyTo handler.  Useful after adding a new AOI
        or when directing the operator's attention to a hot watchbox.
        """
        payload = {
            "cmd": "sar_focus_aoi",
            "args": {"aoi_id": aoi_id, "zoom": zoom},
        }
        r = await self._post("/api/ai/channel/command", json=payload)
        data = r.json()
        if data.get("ok") and data.get("result", {}).get("ok"):
            return data["result"].get("data", {})
        return {}

    # ── Analysis zones (agent-authored map notes) ──────────────────────────

    async def list_analysis_zones(self) -> list:
        """Return all currently active agent-placed analysis zones."""
        payload = {"cmd": "list_analysis_zones", "args": {}}
        r = await self._post("/api/ai/channel/command", json=payload)
        data = r.json()
        if data.get("ok") and data.get("result", {}).get("ok"):
            return data["result"].get("data", [])
        return []

    async def place_analysis_zone(
        self,
        lat: float,
        lng: float,
        title: str,
        body: str,
        category: str = "analysis",
        severity: str = "medium",
        drivers: list[str] | None = None,
        cell_size_deg: float = 2.0,
        ttl_hours: float | None = None,
    ) -> dict:
        """Drop a colored square overlay on the map with a written assessment.

        This is the replacement for the old pattern-matching "contradiction
        detector".  Use it to leave sticky-note style analysis that the
        operator reads by clicking the zone; they can delete any zone from
        the popup.

        category: contradiction | analysis | warning | observation | hypothesis
        severity: high | medium | low  (controls fill opacity)
        body:     your full assessment — preserved verbatim, newlines kept.
        drivers:  up to 5 short bullet strings shown as "KEY INDICATORS".
        cell_size_deg: square size in degrees (default 2.0 ≈ ~220km).
        ttl_hours: optional auto-expiry.  Omit for permanent until deleted.
        """
        args: dict = {
            "lat": lat,
            "lng": lng,
            "title": title,
            "body": body,
            "category": category,
            "severity": severity,
            "cell_size_deg": cell_size_deg,
        }
        if drivers is not None:
            args["drivers"] = drivers
        if ttl_hours is not None:
            args["ttl_hours"] = ttl_hours
        payload = {"cmd": "place_analysis_zone", "args": args}
        r = await self._post("/api/ai/channel/command", json=payload)
        data = r.json()
        if data.get("ok") and data.get("result", {}).get("ok"):
            return data["result"].get("data", {})
        return {}

    async def delete_analysis_zone(self, zone_id: str) -> dict:
        """Remove a specific analysis zone by id."""
        payload = {
            "cmd": "delete_analysis_zone",
            "args": {"zone_id": zone_id},
        }
        r = await self._post("/api/ai/channel/command", json=payload)
        data = r.json()
        if data.get("ok") and data.get("result", {}).get("ok"):
            return data["result"].get("data", {})
        return {}

    async def clear_analysis_zones(self) -> dict:
        """Wipe all analysis zones.  Use sparingly."""
        payload = {"cmd": "clear_analysis_zones", "args": {}}
        r = await self._post("/api/ai/channel/command", json=payload)
        data = r.json()
        if data.get("ok") and data.get("result", {}).get("ok"):
            return data["result"].get("data", {})
        return {}

    # ── SSE Stream (Low-Latency Push) ────────────────────────────────

    async def stream_updates(
        self,
        *,
        on_layer_changed=None,
        on_alert=None,
        on_task=None,
        reconnect_delay: float = 5.0,
        max_reconnect_delay: float = 120.0,
    ):
        """Open the SSE stream and yield events as they arrive.

        This is the preferred way to receive real-time updates from
        ShadowBroker.  The server pushes:

          layer_changed — which layers updated and their new version/count.
                          Internally updates ``self._layer_versions`` so
                          subsequent ``get_layer_slice()`` calls only fetch
                          the layers that actually changed.
          alert         — watchdog hits (geofence, keyword, callsign, etc.)
          task          — operator-pushed tasks
          heartbeat     — keep-alive with full layer version snapshot

        Optional callbacks fire for each event type.  If no callbacks are
        provided, events are yielded as dicts for the caller to handle.

        Auto-reconnects with exponential backoff on disconnect.  HMAC auth
        is validated once at connection open — no per-event signing overhead.

        Usage::

            async for event in sb.stream_updates():
                if event["event"] == "layer_changed":
                    stale = [l for l in event["data"]["layers"]]
                    data = await sb.get_layer_slice(stale)  # only changed layers
        """
        delay = reconnect_delay
        while True:
            try:
                path = "/api/ai/channel/sse"
                headers = self._sign_headers("GET", path)
                client = self._get_client()
                async with client.stream("GET", path, headers=headers, timeout=None) as resp:
                    resp.raise_for_status()
                    delay = reconnect_delay  # Reset backoff on successful connect

                    buffer = ""
                    current_event = "message"
                    current_data = ""

                    async for chunk in resp.aiter_text():
                        buffer += chunk
                        while "\n" in buffer:
                            line, buffer = buffer.split("\n", 1)
                            line = line.rstrip("\r")

                            if line.startswith("event: "):
                                current_event = line[7:]
                            elif line.startswith("data: "):
                                current_data = line[6:]
                            elif line == "":
                                # End of SSE event — process it
                                if current_data:
                                    try:
                                        parsed = json_mod.loads(current_data)
                                    except (json_mod.JSONDecodeError, ValueError):
                                        parsed = current_data

                                    event = {"event": current_event, "data": parsed}

                                    # Update internal state from events
                                    if current_event == "connected" and isinstance(parsed, dict):
                                        lv = parsed.get("layer_versions")
                                        if isinstance(lv, dict):
                                            self._layer_versions.update(lv)

                                    elif current_event == "layer_changed" and isinstance(parsed, dict):
                                        layers_map = parsed.get("layers", {})
                                        for lname, linfo in layers_map.items():
                                            if isinstance(linfo, dict) and "version" in linfo:
                                                self._layer_versions[lname] = linfo["version"]
                                        if on_layer_changed:
                                            on_layer_changed(layers_map)

                                    elif current_event == "alert":
                                        if on_alert:
                                            on_alert(parsed)

                                    elif current_event == "task":
                                        if on_task:
                                            on_task(parsed)

                                    elif current_event == "heartbeat" and isinstance(parsed, dict):
                                        lv = parsed.get("layer_versions")
                                        if isinstance(lv, dict):
                                            self._layer_versions.update(lv)

                                    yield event

                                current_event = "message"
                                current_data = ""

            except (httpx.HTTPStatusError, httpx.StreamError, httpx.RemoteProtocolError) as e:
                import logging as _log
                _log.getLogger(__name__).warning("SSE stream disconnected: %s — reconnecting in %.0fs", e, delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, max_reconnect_delay)
            except (OSError, ConnectionError, TimeoutError) as e:
                import logging as _log
                _log.getLogger(__name__).warning("SSE connection error: %s — reconnecting in %.0fs", e, delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, max_reconnect_delay)

