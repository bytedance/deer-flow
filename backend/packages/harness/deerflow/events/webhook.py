"""Webhook dispatcher — subscribes to EventBus and POSTs events to configured URLs."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging

import httpx

from deerflow.config.webhook_config import get_webhook_config
from deerflow.events.bus import get_event_bus
from deerflow.events.models import Event

logger = logging.getLogger(__name__)


class WebhookDispatcher:
    """Subscribes to the EventBus and forwards events to configured webhook URLs."""

    def __init__(self) -> None:
        self._config = get_webhook_config()
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        if not self._config.enabled or not self._config.urls:
            logger.debug("Webhook dispatcher not started (disabled or no URLs)")
            return

        self._client = httpx.AsyncClient(timeout=self._config.timeout_seconds)
        bus = get_event_bus()
        bus.subscribe(None, self._on_event)
        logger.info("Webhook dispatcher started (%d URLs)", len(self._config.urls))

    async def stop(self) -> None:
        bus = get_event_bus()
        bus.unsubscribe(None, self._on_event)
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        logger.info("Webhook dispatcher stopped")

    async def _on_event(self, event: Event) -> None:
        payload = json.dumps(event.to_dict()).encode()
        signature = self._sign(payload)

        headers = {
            "Content-Type": "application/json",
            "X-DeerFlow-Signature": signature,
            "X-DeerFlow-Event": event.type.value,
        }

        for url in self._config.urls:
            await self._deliver(url, headers, payload)

    async def _deliver(self, url: str, headers: dict, payload: bytes) -> None:
        if self._client is None:
            return

        for attempt in range(self._config.max_retries):
            try:
                resp = await self._client.post(url, headers=headers, content=payload)
                if resp.status_code < 500:
                    return
                logger.warning("Webhook %s returned %d (attempt %d)", url, resp.status_code, attempt + 1)
            except Exception:
                logger.warning("Webhook %s delivery failed (attempt %d)", url, attempt + 1)

            if attempt < self._config.max_retries - 1:
                delay = 2**attempt
                import asyncio
                await asyncio.sleep(delay)

        logger.error("Webhook %s delivery failed after %d retries", url, self._config.max_retries)

    def _sign(self, payload: bytes) -> str:
        if not self._config.signing_secret:
            return ""
        mac = hmac.new(
            self._config.signing_secret.encode(),
            payload,
            hashlib.sha256,
        )
        return f"sha256={mac.hexdigest()}"
