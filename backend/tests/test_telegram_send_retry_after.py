"""Telegram's final-reply sends honor bounded Bot API flood waits."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.channels.base import Channel
from app.channels.message_bus import MessageBus, OutboundMessage


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _flood(retry_after):
    exc = Exception("Flood control exceeded")
    exc.retry_after = retry_after
    return exc


class _OtherChannel(Channel):
    """Stand-in for a non-Telegram provider that shares ``_send_with_retry``."""

    def __init__(self, bus: MessageBus) -> None:
        super().__init__(name="other", bus=bus, config={})

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def send(self, msg: OutboundMessage) -> None:
        return None


def _channel_with_bot():
    from app.channels.telegram import TelegramChannel

    bus = MessageBus()
    channel = TelegramChannel(bus=bus, config={"bot_token": "test-token"})
    bot = SimpleNamespace(sent=[], edited=[], rich=[], next_message_id=100)

    async def send_message(**kwargs):
        bot.sent.append(kwargs)
        result = MagicMock()
        result.message_id = bot.next_message_id
        bot.next_message_id += 1
        return result

    async def edit_message_text(**kwargs):
        bot.edited.append(kwargs)
        result = MagicMock()
        result.message_id = kwargs["message_id"]
        return result

    async def do_api_request(endpoint, api_kwargs):
        bot.rich.append((endpoint, api_kwargs))
        result = {"message_id": bot.next_message_id}
        bot.next_message_id += 1
        return result

    bot.send_message = send_message
    bot.edit_message_text = edit_message_text
    bot.do_api_request = do_api_request
    channel._application = SimpleNamespace(bot=bot)
    return channel, bot


def _patch_retry_sleep(monkeypatch):
    """The new-message retry sleeps in the shared helper, not in telegram.py."""
    sleeps: list[float] = []

    async def fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr("app.channels.base.asyncio.sleep", fake_sleep)
    return sleeps


def _final(text: str, *, chat_id: str = "12345") -> OutboundMessage:
    return OutboundMessage(channel_name="telegram", chat_id=chat_id, thread_id="t1", text=text, is_final=True)


class TestTelegramNewMessageRetryAfter:
    def test_plain_new_message_waits_for_retry_after_seconds(self, monkeypatch):
        async def go():
            channel, bot = _channel_with_bot()
            sleeps = _patch_retry_sleep(monkeypatch)
            real_send = bot.send_message
            calls = {"n": 0}

            async def flaky(**kwargs):
                calls["n"] += 1
                if calls["n"] == 1:
                    raise _flood(41)
                return await real_send(**kwargs)

            bot.send_message = flaky
            await channel.send(_final("hello"))

            assert sleeps == [41.0]
            assert calls["n"] == 2
            assert [message["text"] for message in bot.sent] == ["hello"]
            assert channel._last_bot_message["12345"] == 100

        _run(go())

    def test_plain_new_message_waits_for_retry_after_timedelta(self, monkeypatch):
        async def go():
            channel, bot = _channel_with_bot()
            sleeps = _patch_retry_sleep(monkeypatch)
            real_send = bot.send_message
            calls = {"n": 0}

            async def flaky(**kwargs):
                calls["n"] += 1
                if calls["n"] == 1:
                    raise _flood(timedelta(seconds=17))
                return await real_send(**kwargs)

            bot.send_message = flaky
            await channel.send(_final("hello"))

            assert sleeps == [17.0]
            assert [message["text"] for message in bot.sent] == ["hello"]

        _run(go())

    def test_rich_new_message_waits_for_retry_after(self, monkeypatch):
        async def go():
            channel, bot = _channel_with_bot()
            channel.config["rich_messages"] = True
            sleeps = _patch_retry_sleep(monkeypatch)
            real_rich = bot.do_api_request
            calls = {"n": 0}

            async def flaky(endpoint, api_kwargs):
                calls["n"] += 1
                if calls["n"] == 1:
                    raise _flood(12)
                return await real_rich(endpoint, api_kwargs)

            bot.do_api_request = flaky
            await channel.send(_final("**answer**"))

            assert sleeps == [12.0]
            assert calls["n"] == 2
            assert bot.sent == []
            assert [call[0] for call in bot.rich] == ["sendRichMessage"]
            assert channel._last_bot_message["12345"] == 100

        _run(go())

    def test_overflow_without_preview_waits_before_the_next_chunk(self, monkeypatch):
        async def go():
            channel, bot = _channel_with_bot()
            sleeps = _patch_retry_sleep(monkeypatch)
            real_send = bot.send_message
            overflow = "b" * 10
            failed = {"left": 1}

            async def flaky(**kwargs):
                if kwargs.get("text") == overflow and failed["left"] > 0:
                    failed["left"] -= 1
                    raise _flood(9)
                return await real_send(**kwargs)

            bot.send_message = flaky
            await channel.send(_final("a" * 4096 + overflow))

            assert sleeps == [9.0]
            assert [message["text"] for message in bot.sent] == ["a" * 4096, overflow]
            assert channel._last_bot_message["12345"] == 101

        _run(go())

    def test_overflow_after_stream_preview_waits_before_the_next_chunk(self, monkeypatch):
        async def go():
            channel, bot = _channel_with_bot()
            sleeps = _patch_retry_sleep(monkeypatch)
            monkeypatch.setattr("app.channels.telegram._monotonic", lambda: 1000.0)
            await channel._send_running_reply("12345", 42)

            real_send = bot.send_message
            overflow = "b" * 10
            failed = {"left": 1}

            async def flaky(**kwargs):
                if kwargs.get("text") == overflow and failed["left"] > 0:
                    failed["left"] -= 1
                    raise _flood(8)
                return await real_send(**kwargs)

            bot.send_message = flaky
            await channel.send(
                OutboundMessage(
                    channel_name="telegram",
                    chat_id="12345",
                    thread_id="t1",
                    text="a" * 4096 + overflow,
                    is_final=True,
                    thread_ts="42",
                )
            )

            assert sleeps == [8.0]
            assert bot.edited[0]["text"] == "a" * 4096
            assert [message["text"] for message in bot.sent] == ["Working on it...", overflow]
            assert channel._last_bot_message["12345"] == 101
            assert "12345:42" not in channel._stream_messages

        _run(go())

    @pytest.mark.parametrize(("hint", "expected_wait"), [(30, 30.0), (timedelta(hours=2), 60.0)])
    def test_repeated_flood_wait_still_stops_at_the_attempt_bound(self, monkeypatch, hint, expected_wait):
        async def go():
            channel, bot = _channel_with_bot()
            sleeps = _patch_retry_sleep(monkeypatch)
            calls = {"n": 0}

            async def always_limited(**kwargs):
                calls["n"] += 1
                raise _flood(hint)

            bot.send_message = always_limited
            with pytest.raises(Exception, match="Flood control exceeded"):
                await channel.send(_final("hello"), _max_retries=3)

            assert calls["n"] == 3
            assert sleeps == [expected_wait, expected_wait]
            assert bot.sent == []

        _run(go())

    def test_each_attempt_uses_that_response_hint(self, monkeypatch):
        async def go():
            channel, bot = _channel_with_bot()
            sleeps = _patch_retry_sleep(monkeypatch)
            real_send = bot.send_message
            hints = [5, 20]

            async def flaky(**kwargs):
                if hints:
                    raise _flood(hints.pop(0))
                return await real_send(**kwargs)

            bot.send_message = flaky
            await channel.send(_final("hello"))

            assert sleeps == [5.0, 20.0]
            assert [message["text"] for message in bot.sent] == ["hello"]

        _run(go())

    def test_cancellation_during_the_flood_wait_is_not_swallowed(self, monkeypatch):
        async def go():
            channel, bot = _channel_with_bot()
            sleeps: list[float] = []

            async def cancel_sleep(delay):
                sleeps.append(delay)
                raise asyncio.CancelledError()

            monkeypatch.setattr("app.channels.base.asyncio.sleep", cancel_sleep)
            calls = {"n": 0}

            async def limited(**kwargs):
                calls["n"] += 1
                raise _flood(40)

            bot.send_message = limited
            with pytest.raises(asyncio.CancelledError):
                await channel.send(_final("hello"))

            assert calls["n"] == 1
            assert sleeps == [40.0]
            assert bot.sent == []

        _run(go())

    @pytest.mark.parametrize(
        "hint",
        [0.25, float("inf"), float("nan"), "invalid", {}, 10**400],
        ids=["short", "infinite", "nan", "nonnumeric", "wrong-type", "overflow"],
    )
    def test_unusable_hint_keeps_the_local_backoff(self, monkeypatch, hint):
        async def go():
            channel, bot = _channel_with_bot()
            sleeps = _patch_retry_sleep(monkeypatch)
            real_send = bot.send_message
            calls = {"n": 0}

            async def flaky(**kwargs):
                calls["n"] += 1
                if calls["n"] == 1:
                    raise _flood(hint)
                return await real_send(**kwargs)

            bot.send_message = flaky
            await channel.send(_final("hello"))

            assert sleeps == [1]
            assert [message["text"] for message in bot.sent] == ["hello"]

        _run(go())

    def test_ordinary_network_error_keeps_exponential_backoff(self, monkeypatch):
        async def go():
            channel, bot = _channel_with_bot()
            sleeps = _patch_retry_sleep(monkeypatch)
            real_send = bot.send_message
            left = {"n": 2}

            async def flaky(**kwargs):
                if left["n"] > 0:
                    left["n"] -= 1
                    raise ConnectionError("transient")
                return await real_send(**kwargs)

            bot.send_message = flaky
            await channel.send(_final("hello"))

            assert sleeps == [1, 2]
            assert [message["text"] for message in bot.sent] == ["hello"]

        _run(go())

    def test_other_channels_keep_ignoring_retry_after(self, monkeypatch):
        sleeps = _patch_retry_sleep(monkeypatch)
        channel = _OtherChannel(MessageBus())
        attempts = {"n": 0}

        async def flaky():
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise _flood(50)
            return "sent"

        assert _run(channel._send_with_retry(flaky, max_retries=3)) == "sent"
        assert attempts["n"] == 3
        assert sleeps == [1, 2]


def _malformed_flood_app(monkeypatch, calls, sleep_list, *, always_fail=False):
    """Real PTB Application whose SDK request sits on a mock transport.

    The transport answers malformed 429s (retry_after "invalid") and then
    succeeds (or keeps failing when always_fail is set), exercising the
    response-boundary normalization in _BoundedRetryAfterRequest (#8548).
    """
    import httpx
    from telegram.ext import ApplicationBuilder

    from app.channels.telegram import _BoundedRetryAfterRequest

    def respond(request):
        calls["n"] += 1
        if always_fail or calls["n"] <= 1:
            return httpx.Response(
                429,
                json={
                    "ok": False,
                    "error_code": 429,
                    "description": "flood",
                    "parameters": {"retry_after": "invalid"},
                },
            )
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {"message_id": 100, "date": 1700000000, "chat": {"id": 12345, "type": "private"}},
            },
        )

    request = _BoundedRetryAfterRequest.build(httpx_kwargs={"transport": httpx.MockTransport(respond)})
    app = ApplicationBuilder().token("test-token").request(request).build()

    async def fake_sleep(delay):
        sleep_list.append(delay)

    monkeypatch.setattr("app.channels.telegram.asyncio.sleep", fake_sleep)
    return app


def test_final_chunk_edit_malformed_429_beneath_the_real_sdk(monkeypatch):
    async def go():
        calls = {"n": 0}
        sleeps: list[float] = []
        app = _malformed_flood_app(monkeypatch, calls, sleeps)
        channel, _bot = _channel_with_bot()
        channel._application = app
        try:
            # The SDK's own RetryAfter retry absorbs the normalized hint and
            # the edit completes instead of crashing on the parse failure.
            edited = await channel._edit_final_chunk(app.bot, 12345, 100, "hello")
            assert edited is True
            assert calls["n"] == 2
        finally:
            await app.shutdown()

    _run(go())


def test_rich_edit_malformed_429_beneath_the_real_sdk(monkeypatch):
    async def go():
        calls = {"n": 0}
        sleeps: list[float] = []
        app = _malformed_flood_app(monkeypatch, calls, sleeps)
        channel, _bot = _channel_with_bot()
        channel._application = app
        try:
            edited = await channel._edit_rich_message("12345", 100, "**answer**")
            assert edited is True
            assert calls["n"] == 2
        finally:
            await app.shutdown()

    _run(go())


def test_repeated_malformed_429_engages_the_bounded_fallback(monkeypatch):
    async def go():
        calls = {"n": 0}
        sleeps: list[float] = []
        app = _malformed_flood_app(monkeypatch, calls, sleeps, always_fail=True)
        channel, _bot = _channel_with_bot()
        channel._application = app
        try:
            # The channel's bounded flood-wait (1s base backoff) engages after
            # the SDK's internal retry exhausts, instead of the pre-fix skip.
            edited = await channel._edit_final_chunk(app.bot, 12345, 100, "hello")
            assert edited is False
            assert 1.0 in sleeps
        finally:
            await app.shutdown()

    _run(go())
