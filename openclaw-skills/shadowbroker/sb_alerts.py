"""ShadowBroker alert delivery — webhook dispatch for Discord, Telegram, etc.

Sends branded alerts from the AI co-pilot to external channels.
Supports Discord webhooks, Telegram bots, and generic webhooks.

Usage:
    from sb_alerts import AlertDispatcher
    dispatcher = AlertDispatcher()
    dispatcher.add_discord("https://discord.com/api/webhooks/...")
    await dispatcher.send("brief", "Morning intelligence digest...")
"""

import asyncio
import json
import logging
from typing import Any, Optional

try:
    import httpx
except ImportError:
    httpx = None

from sb_signatures import sig

logger = logging.getLogger(__name__)


class AlertDispatcher:
    """Multi-channel alert dispatcher with branded signatures."""

    def __init__(self):
        self.channels: list[dict] = []
        self._client = None

    def _get_client(self):
        if self._client is None:
            if httpx:
                self._client = httpx.AsyncClient(timeout=10)
            else:
                raise RuntimeError("httpx required — pip install httpx")
        return self._client

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    # ── Channel registration ──────────────────────────────────────

    def add_discord(self, webhook_url: str, name: str = "Discord"):
        """Add a Discord webhook channel."""
        self.channels.append({
            "type": "discord",
            "url": webhook_url,
            "name": name,
        })

    def add_telegram(self, bot_token: str, chat_id: str, name: str = "Telegram"):
        """Add a Telegram bot channel."""
        self.channels.append({
            "type": "telegram",
            "bot_token": bot_token,
            "chat_id": chat_id,
            "name": name,
        })

    def add_webhook(self, url: str, name: str = "Webhook", headers: Optional[dict] = None):
        """Add a generic webhook channel."""
        self.channels.append({
            "type": "webhook",
            "url": url,
            "name": name,
            "headers": headers or {},
        })

    # ── Send ──────────────────────────────────────────────────────

    async def send(self, signature_type: str, message: str, **kwargs) -> list[dict]:
        """Send a branded alert to all registered channels.

        Args:
            signature_type: One of the registered sig() types (brief, warning, etc.)
            message: The alert body text
            **kwargs: Extra data (embed fields, etc.)

        Returns:
            List of delivery results for each channel
        """
        branded = f"{sig(signature_type)}\n{message}"
        results = []

        for channel in self.channels:
            try:
                if channel["type"] == "discord":
                    result = await self._send_discord(channel, branded, **kwargs)
                elif channel["type"] == "telegram":
                    result = await self._send_telegram(channel, branded, **kwargs)
                elif channel["type"] == "webhook":
                    result = await self._send_webhook(channel, branded, **kwargs)
                else:
                    result = {"ok": False, "error": f"Unknown channel type: {channel['type']}"}
                results.append({**result, "channel": channel["name"]})
            except Exception as e:
                logger.warning(f"Failed to send to {channel['name']}: {e}")
                results.append({
                    "ok": False,
                    "channel": channel["name"],
                    "error": str(e),
                })

        return results

    # ── Discord ───────────────────────────────────────────────────

    async def _send_discord(self, channel: dict, message: str, **kwargs) -> dict:
        """Send via Discord webhook."""
        # Discord has 2000 char limit — split if needed
        chunks = [message[i:i + 1990] for i in range(0, len(message), 1990)]

        for chunk in chunks:
            payload: dict[str, Any] = {
                "content": chunk,
                "username": "ShadowBroker AI",
            }

            # Add embed if extra data provided
            if kwargs.get("embed_title") or kwargs.get("embed_fields"):
                embed: dict[str, Any] = {
                    "color": 0x8b5cf6,  # violet
                }
                if kwargs.get("embed_title"):
                    embed["title"] = kwargs["embed_title"]
                if kwargs.get("embed_description"):
                    embed["description"] = kwargs["embed_description"]
                if kwargs.get("embed_fields"):
                    embed["fields"] = [
                        {"name": k, "value": str(v), "inline": True}
                        for k, v in kwargs["embed_fields"].items()
                    ]
                if kwargs.get("embed_thumbnail"):
                    embed["thumbnail"] = {"url": kwargs["embed_thumbnail"]}
                payload["embeds"] = [embed]
                # Embeds get the message, content becomes empty
                payload["content"] = ""

            r = await self._get_client().post(channel["url"], json=payload)
            if r.status_code not in (200, 204):
                return {"ok": False, "error": f"Discord {r.status_code}"}

        return {"ok": True}

    # ── Telegram ──────────────────────────────────────────────────

    async def _send_telegram(self, channel: dict, message: str, **kwargs) -> dict:
        """Send via Telegram Bot API."""
        url = f"https://api.telegram.org/bot{channel['bot_token']}/sendMessage"

        # Telegram has 4096 char limit
        chunks = [message[i:i + 4000] for i in range(0, len(message), 4000)]

        for chunk in chunks:
            payload = {
                "chat_id": channel["chat_id"],
                "text": chunk,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            }

            r = await self._get_client().post(url, json=payload)
            if r.status_code != 200:
                # Retry without markdown if it fails (emoji can break MD)
                payload["parse_mode"] = ""
                r = await self._get_client().post(url, json=payload)
                if r.status_code != 200:
                    return {"ok": False, "error": f"Telegram {r.status_code}"}

        return {"ok": True}

    # ── Generic Webhook ───────────────────────────────────────────

    async def _send_webhook(self, channel: dict, message: str, **kwargs) -> dict:
        """Send via generic webhook (JSON POST)."""
        payload = {
            "source": "shadowbroker",
            "message": message,
            "timestamp": __import__("time").time(),
            **kwargs,
        }
        headers = {"Content-Type": "application/json", **(channel.get("headers") or {})}

        r = await self._get_client().post(channel["url"], json=payload, headers=headers)
        if r.status_code not in (200, 201, 202, 204):
            return {"ok": False, "error": f"Webhook {r.status_code}"}

        return {"ok": True}

    # ── Convenience methods ───────────────────────────────────────

    async def send_brief(self, message: str, **kwargs) -> list[dict]:
        return await self.send("brief", message, **kwargs)

    async def send_warning(self, message: str, **kwargs) -> list[dict]:
        return await self.send("warning", message, **kwargs)

    async def send_threat(self, message: str, **kwargs) -> list[dict]:
        return await self.send("threat", message, **kwargs)

    async def send_news(self, message: str, **kwargs) -> list[dict]:
        return await self.send("news", message, **kwargs)

    async def send_intel(self, message: str, **kwargs) -> list[dict]:
        return await self.send("intel", message, **kwargs)
