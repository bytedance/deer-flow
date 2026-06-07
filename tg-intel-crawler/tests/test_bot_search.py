"""Tests for BotSearchClient — talk to a search bot via Telethon Conversation."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import asyncio
import pytest

from tg_intel_crawler.collector.bot_search import (
    BotSearchClient,
    BotUnavailable,
)


class _FakeConv:
    """Async-context-manager standing in for telethon's client.conversation()."""

    def __init__(self, *, response_text: str | None = "ok", raise_on_send=None,
                 response_delay: float = 0):
        self._response_text = response_text
        self._raise_on_send = raise_on_send
        self._response_delay = response_delay
        self.sent: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def send_message(self, text):
        if self._raise_on_send:
            raise self._raise_on_send
        self.sent.append(text)

    async def get_response(self, timeout=None):
        if self._response_delay:
            await asyncio.sleep(self._response_delay)
        if self._response_text is None:
            raise asyncio.TimeoutError()
        return SimpleNamespace(text=self._response_text)


def _client(conv: _FakeConv | Exception, entity_returns=None):
    """Build a fake client that hands out the given conversation context."""
    c = SimpleNamespace()

    def conversation(target, *, timeout=None):
        # Telethon's client.conversation() is a SYNC function returning an
        # async context manager. Mirror that here.
        if isinstance(conv, Exception):
            raise conv
        return conv

    c.conversation = conversation

    async def get_entity(name):
        if isinstance(entity_returns, Exception):
            raise entity_returns
        return entity_returns or SimpleNamespace(username=name.lstrip("@"))

    c.get_entity = get_entity
    return c


@pytest.mark.asyncio
async def test_query_returns_bot_response_text():
    conv = _FakeConv(response_text="🌄 result https://t.me/foo/1")
    client = _client(conv)
    result = await BotSearchClient(client, bot="@JISOU", timeout=2).query("抖加")
    assert "🌄" in result
    assert conv.sent == ["抖加"]


@pytest.mark.asyncio
async def test_query_timeout_returns_none_not_raise():
    conv = _FakeConv(response_text=None)  # triggers TimeoutError
    client = _client(conv)
    result = await BotSearchClient(client, bot="@JISOU", timeout=1).query("抖加")
    assert result is None


@pytest.mark.asyncio
async def test_ensure_available_passes_when_get_entity_works():
    bot_entity = SimpleNamespace(username="JISOU", bot=True)
    client = _client(_FakeConv(), entity_returns=bot_entity)
    bsc = BotSearchClient(client, bot="@JISOU", timeout=2)
    await bsc.ensure_available()  # should not raise


@pytest.mark.asyncio
async def test_ensure_available_raises_when_bot_not_found():
    client = _client(_FakeConv(), entity_returns=ValueError("Cannot find entity"))
    bsc = BotSearchClient(client, bot="@nope", timeout=2)
    with pytest.raises(BotUnavailable):
        await bsc.ensure_available()


@pytest.mark.asyncio
async def test_query_uses_provided_timeout():
    """The timeout passed to get_response should match the configured value."""
    captured: dict = {}

    class _Conv(_FakeConv):
        async def get_response(self, timeout=None):
            captured["timeout"] = timeout
            return SimpleNamespace(text="ok")

    client = _client(_Conv())
    await BotSearchClient(client, bot="@J", timeout=5).query("x")
    assert captured["timeout"] == 5
