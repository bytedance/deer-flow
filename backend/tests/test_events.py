"""Tests for event system — EventBus pub/sub, webhook dispatcher, and event models."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from deerflow.config.webhook_config import (
    WebhookConfig,
    get_webhook_config,
    load_webhook_config_from_dict,
    reset_webhook_config,
)
from deerflow.events.bus import EventBus, get_event_bus, reset_event_bus
from deerflow.events.models import Event, EventType
from deerflow.events.webhook import WebhookDispatcher


class TestWebhookConfig:
    def test_default_config(self):
        reset_webhook_config()
        config = get_webhook_config()
        assert config.enabled is False
        assert config.signing_secret == ""
        assert config.max_retries == 3
        assert config.timeout_seconds == 10.0
        assert config.urls == []

    def test_load_from_dict(self):
        load_webhook_config_from_dict({
            "enabled": True,
            "signing_secret": "secret123",
            "max_retries": 5,
            "timeout_seconds": 5.0,
            "urls": ["https://hooks.example.com/webhook"],
        })
        config = get_webhook_config()
        assert config.enabled is True
        assert config.signing_secret == "secret123"
        assert config.max_retries == 5
        assert config.urls == ["https://hooks.example.com/webhook"]

    def test_reset(self):
        load_webhook_config_from_dict({"enabled": True})
        reset_webhook_config()
        assert get_webhook_config().enabled is False


class TestEventModels:
    def test_event_to_dict(self):
        event = Event(
            type=EventType.RUN_STARTED,
            tenant_id="default",
            thread_id="thread-1",
            data={"key": "value"},
        )
        d = event.to_dict()
        assert d["type"] == "run_started"
        assert d["tenant_id"] == "default"
        assert d["thread_id"] == "thread-1"
        assert d["data"] == {"key": "value"}
        assert "id" in d
        assert "timestamp" in d

    def test_event_from_dict(self):
        d = {
            "id": "abc123",
            "type": "run_completed",
            "tenant_id": "acme",
            "thread_id": "th1",
            "timestamp": "2025-01-01T00:00:00",
            "data": {"tokens": 100},
        }
        event = Event.from_dict(d)
        assert event.id == "abc123"
        assert event.type == EventType.RUN_COMPLETED
        assert event.tenant_id == "acme"
        assert event.data == {"tokens": 100}

    def test_event_from_dict_minimal(self):
        d = {"id": "x", "type": "run_failed", "tenant_id": "t"}
        event = Event.from_dict(d)
        assert event.thread_id is None
        assert event.data == {}

    def test_event_defaults(self):
        event = Event(type=EventType.RUN_STARTED, tenant_id="default")
        assert len(event.id) == 12
        assert event.thread_id is None
        assert event.data == {}


class TestEventBus:
    @pytest.fixture(autouse=True)
    def _reset(self):
        reset_event_bus()
        yield
        reset_event_bus()

    @pytest.mark.anyio
    async def test_publish_to_subscriber(self):
        bus = get_event_bus()
        received: list[Event] = []

        async def handler(event: Event):
            received.append(event)

        bus.subscribe(EventType.RUN_STARTED, handler)
        event = Event(type=EventType.RUN_STARTED, tenant_id="default")
        bus.publish(event)

        import asyncio
        await asyncio.sleep(0.05)
        assert len(received) == 1
        assert received[0].type == EventType.RUN_STARTED

    @pytest.mark.anyio
    async def test_wildcard_subscriber(self):
        bus = get_event_bus()
        received: list[Event] = []

        async def handler(event: Event):
            received.append(event)

        bus.subscribe(None, handler)
        bus.publish(Event(type=EventType.RUN_STARTED, tenant_id="t"))
        bus.publish(Event(type=EventType.RUN_COMPLETED, tenant_id="t"))

        import asyncio
        await asyncio.sleep(0.05)
        assert len(received) == 2

    @pytest.mark.anyio
    async def test_unsubscribe(self):
        bus = get_event_bus()
        received: list[Event] = []

        async def handler(event: Event):
            received.append(event)

        bus.subscribe(EventType.RUN_STARTED, handler)
        bus.unsubscribe(EventType.RUN_STARTED, handler)
        bus.publish(Event(type=EventType.RUN_STARTED, tenant_id="t"))

        import asyncio
        await asyncio.sleep(0.05)
        assert len(received) == 0

    @pytest.mark.anyio
    async def test_apublish(self):
        bus = get_event_bus()
        received: list[Event] = []

        async def handler(event: Event):
            received.append(event)

        bus.subscribe(EventType.RUN_COMPLETED, handler)
        event = Event(type=EventType.RUN_COMPLETED, tenant_id="t")
        await bus.apublish(event)

        assert len(received) == 1

    @pytest.mark.anyio
    async def test_apublish_handles_exceptions(self):
        bus = get_event_bus()
        received: list[Event] = []

        async def failing_handler(event: Event):
            raise RuntimeError("boom")

        async def good_handler(event: Event):
            received.append(event)

        bus.subscribe(EventType.RUN_FAILED, failing_handler)
        bus.subscribe(EventType.RUN_FAILED, good_handler)
        event = Event(type=EventType.RUN_FAILED, tenant_id="t")
        await bus.apublish(event)

        assert len(received) == 1

    @pytest.mark.anyio
    async def test_no_subscribers_no_error(self):
        bus = get_event_bus()
        event = Event(type=EventType.RUN_STARTED, tenant_id="t")
        bus.publish(event)
        await bus.apublish(event)


class TestWebhookDispatcher:
    @pytest.fixture(autouse=True)
    def _reset(self):
        reset_webhook_config()
        reset_event_bus()
        yield
        reset_webhook_config()
        reset_event_bus()

    def test_sign_with_secret(self):
        load_webhook_config_from_dict({"signing_secret": "mysecret"})
        dispatcher = WebhookDispatcher()
        sig = dispatcher._sign(b"hello")
        assert sig.startswith("sha256=")
        assert len(sig) > 7

    def test_sign_without_secret(self):
        load_webhook_config_from_dict({"signing_secret": ""})
        dispatcher = WebhookDispatcher()
        assert dispatcher._sign(b"hello") == ""

    @pytest.mark.anyio
    async def test_start_disabled(self):
        load_webhook_config_from_dict({"enabled": False})
        dispatcher = WebhookDispatcher()
        await dispatcher.start()
        assert dispatcher._client is None

    @pytest.mark.anyio
    async def test_start_no_urls(self):
        load_webhook_config_from_dict({"enabled": True, "urls": []})
        dispatcher = WebhookDispatcher()
        await dispatcher.start()
        assert dispatcher._client is None

    @pytest.mark.anyio
    async def test_deliver_success(self):
        load_webhook_config_from_dict({
            "enabled": True,
            "urls": ["https://hooks.example.com/webhook"],
            "max_retries": 1,
        })
        dispatcher = WebhookDispatcher()
        dispatcher._client = AsyncMock()
        mock_response = AsyncMock()
        mock_response.status_code = 200
        dispatcher._client.post.return_value = mock_response

        await dispatcher._deliver(
            "https://hooks.example.com/webhook",
            {"Content-Type": "application/json"},
            b"{}",
        )
        dispatcher._client.post.assert_called_once()

    @pytest.mark.anyio
    async def test_deliver_retry_on_500(self):
        load_webhook_config_from_dict({
            "enabled": True,
            "urls": ["https://hooks.example.com/webhook"],
            "max_retries": 2,
        })
        dispatcher = WebhookDispatcher()
        dispatcher._client = AsyncMock()
        mock_response = AsyncMock()
        mock_response.status_code = 500
        dispatcher._client.post.return_value = mock_response

        await dispatcher._deliver(
            "https://hooks.example.com/webhook",
            {"Content-Type": "application/json"},
            b"{}",
        )
        assert dispatcher._client.post.call_count == 2

    @pytest.mark.anyio
    async def test_deliver_retry_on_exception(self):
        load_webhook_config_from_dict({
            "enabled": True,
            "urls": ["https://hooks.example.com/webhook"],
            "max_retries": 2,
        })
        dispatcher = WebhookDispatcher()
        dispatcher._client = AsyncMock()
        dispatcher._client.post.side_effect = RuntimeError("network error")

        await dispatcher._deliver(
            "https://hooks.example.com/webhook",
            {"Content-Type": "application/json"},
            b"{}",
        )
        assert dispatcher._client.post.call_count == 2

    @pytest.mark.anyio
    async def test_stop(self):
        load_webhook_config_from_dict({"enabled": True, "urls": ["https://hooks.example.com/webhook"]})
        dispatcher = WebhookDispatcher()
        await dispatcher.start()
        assert dispatcher._client is not None

        await dispatcher.stop()
        assert dispatcher._client is None
