"""Tests for DetailFetcher — visit each bot-given deeplink to fetch the
full original message text, with entity caching, downgrade on private
groups, and FloodWait retry-once."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from tg_intel_crawler.collector.bot_response_parser import BotPreview
from tg_intel_crawler.collector.detail_fetcher import (
    DetailFetcher,
    FetchOutcome,
)


def _preview(channel: str | None = "somechan", msg_id: int | None = 100) -> BotPreview:
    from datetime import datetime, timezone
    return BotPreview(
        bot="@JISOU",
        query="抖加",
        raw_line="🌄 preview text https://t.me/somechan/100",
        text="preview text",
        deeplink=f"https://t.me/{channel}/{msg_id}" if channel and msg_id else None,
        channel_username=channel,
        msg_id=msg_id,
        icon="🌄",
        seen_at=datetime.now(timezone.utc),
    )


class _FakeClient:
    def __init__(self, *, get_entity=None, get_messages=None):
        self.get_entity = get_entity or AsyncMock(side_effect=lambda u: SimpleNamespace(id=42, username=u))
        self.get_messages = get_messages or AsyncMock(return_value=SimpleNamespace(text="ORIGINAL FULL MESSAGE"))


@pytest.fixture
def no_throttle():
    """A throttle that never sleeps — keeps tests instant."""
    class _Z:
        async def acquire(self): return None
    return _Z()


@pytest.mark.asyncio
async def test_fetch_returns_full_text_for_public_channel(no_throttle):
    client = _FakeClient()
    p = _preview()
    fetcher = DetailFetcher(client, throttle=no_throttle)
    outcome = await fetcher.fetch(p)
    assert outcome.success is True
    assert outcome.full_text == "ORIGINAL FULL MESSAGE"
    assert outcome.degraded is False


@pytest.mark.asyncio
async def test_skips_when_no_deeplink(no_throttle):
    p = _preview(channel=None, msg_id=None)
    outcome = await DetailFetcher(_FakeClient(), throttle=no_throttle).fetch(p)
    assert outcome.success is False
    assert outcome.degraded is True
    assert outcome.full_text is None
    assert outcome.reason == "no_deeplink"


@pytest.mark.asyncio
async def test_entity_lookup_cached_across_previews(no_throttle):
    """Two previews from the same channel should hit get_entity ONCE."""
    client = _FakeClient()
    fetcher = DetailFetcher(client, throttle=no_throttle)
    await fetcher.fetch(_preview(channel="dup", msg_id=1))
    await fetcher.fetch(_preview(channel="dup", msg_id=2))
    assert client.get_entity.await_count == 1
    assert client.get_messages.await_count == 2


@pytest.mark.asyncio
async def test_channel_private_error_downgrades_gracefully(no_throttle):
    class FakeChannelPrivate(Exception):
        pass

    client = _FakeClient()
    client.get_entity = AsyncMock(side_effect=FakeChannelPrivate("nope"))
    fetcher = DetailFetcher(client, throttle=no_throttle)
    fetcher._private_exc_types = (FakeChannelPrivate,)

    outcome = await fetcher.fetch(_preview())
    assert outcome.success is False
    assert outcome.degraded is True
    assert outcome.full_text is None
    assert outcome.reason == "private"


@pytest.mark.asyncio
async def test_value_error_means_invalid_channel(no_throttle):
    client = _FakeClient()
    client.get_entity = AsyncMock(side_effect=ValueError("Cannot find any entity"))
    outcome = await DetailFetcher(client, throttle=no_throttle).fetch(_preview())
    assert outcome.success is False
    assert outcome.degraded is True
    assert outcome.reason == "invalid_channel"


@pytest.mark.asyncio
async def test_floodwait_retries_once_then_succeeds(no_throttle):
    class FakeFlood(Exception):
        def __init__(self, seconds): self.seconds = seconds

    sleeps: list[float] = []
    async def fake_sleep(s): sleeps.append(s)

    client = _FakeClient()
    client.get_messages = AsyncMock(side_effect=[FakeFlood(20), SimpleNamespace(text="OK")])
    fetcher = DetailFetcher(client, throttle=no_throttle, sleep_fn=fake_sleep)
    fetcher._flood_exc_types = (FakeFlood,)

    outcome = await fetcher.fetch(_preview())
    assert outcome.success is True
    assert outcome.full_text == "OK"
    assert 20 in sleeps
    assert client.get_messages.await_count == 2


@pytest.mark.asyncio
async def test_floodwait_second_failure_propagates_as_degraded(no_throttle):
    class FakeFlood(Exception):
        def __init__(self, seconds): self.seconds = seconds

    client = _FakeClient()
    client.get_messages = AsyncMock(side_effect=[FakeFlood(5), FakeFlood(5)])
    fetcher = DetailFetcher(
        client, throttle=no_throttle, sleep_fn=AsyncMock(),
    )
    fetcher._flood_exc_types = (FakeFlood,)

    outcome = await fetcher.fetch(_preview())
    assert outcome.success is False
    assert outcome.degraded is True
    assert outcome.reason == "flood_wait"


@pytest.mark.asyncio
async def test_message_not_found_returns_degraded(no_throttle):
    """If get_messages returns None (msg deleted/not found), degrade gracefully."""
    client = _FakeClient()
    client.get_messages = AsyncMock(return_value=None)
    outcome = await DetailFetcher(client, throttle=no_throttle).fetch(_preview())
    assert outcome.success is False
    assert outcome.degraded is True
    assert outcome.reason == "msg_not_found"


@pytest.mark.asyncio
async def test_throttle_acquired_before_each_fetch():
    calls: list[int] = []
    class _T:
        async def acquire(self): calls.append(1)

    client = _FakeClient()
    fetcher = DetailFetcher(client, throttle=_T())
    await fetcher.fetch(_preview(channel="a_channel", msg_id=1))
    await fetcher.fetch(_preview(channel="b_channel", msg_id=1))
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_unexpected_exception_does_not_propagate(no_throttle):
    """Catch-all: if get_entity raises something we don't recognize (e.g.
    UsernameNotOccupiedError, ChannelInvalidError, RPCError…), the fetcher
    must NOT crash the whole crawl-bot run — degrade and continue."""
    client = _FakeClient()
    client.get_entity = AsyncMock(side_effect=RuntimeError("unexpected wire-level error"))
    outcome = await DetailFetcher(client, throttle=no_throttle).fetch(_preview())
    assert outcome.success is False
    assert outcome.degraded is True
    assert outcome.reason == "error"


@pytest.mark.asyncio
async def test_unexpected_exception_in_get_messages_also_degrades(no_throttle):
    client = _FakeClient()
    client.get_messages = AsyncMock(side_effect=RuntimeError("rpc died"))
    outcome = await DetailFetcher(client, throttle=no_throttle).fetch(_preview())
    assert outcome.success is False
    assert outcome.degraded is True
    assert outcome.reason == "error"
