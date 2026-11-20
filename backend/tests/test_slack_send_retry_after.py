"""Slack replies wait for a 429 Retry-After instead of the 1s/2s backoff."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from slack_sdk.errors import SlackApiError

from app.channels.message_bus import MessageBus, OutboundMessage
from app.channels.slack import SLACK_MAX_OUTBOUND_RETRY_DELAY_SECONDS, SlackChannel


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _api_error(status_code: int, headers: dict | None):
    response = SimpleNamespace(status_code=status_code, headers={} if headers is None else headers)
    return SlackApiError("ratelimited", response)


def _channel():
    channel = SlackChannel(bus=MessageBus(), config={"bot_token": "xoxb-test", "app_token": "xapp-test"})
    client = SimpleNamespace(posts=[])

    def chat_postMessage(**kwargs):
        client.posts.append(kwargs)
        return {"ok": True, "ts": "1.0"}

    client.chat_postMessage = chat_postMessage
    channel._web_client = client
    return channel, client


def _patch_retry_sleep(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr("app.channels.base.asyncio.sleep", fake_sleep)
    return sleeps


def _reply(text: str = "hello") -> OutboundMessage:
    return OutboundMessage(channel_name="slack", chat_id="C123", thread_id="t1", text=text)


def _install(client, failures: list[BaseException]):
    real = client.chat_postMessage
    pending = list(failures)

    def flaky(**kwargs):
        if pending:
            raise pending.pop(0)
        return real(**kwargs)

    client.chat_postMessage = flaky


class TestSlackSendRetryAfter:
    def test_rate_limited_reply_waits_for_retry_after(self, monkeypatch):
        async def go():
            channel, client = _channel()
            sleeps = _patch_retry_sleep(monkeypatch)
            _install(client, [_api_error(429, {"Retry-After": "12"})])

            await channel.send(_reply())

            assert sleeps == [12.0]
            assert [post["text"] for post in client.posts] == ["hello"]

        _run(go())

    def test_lowercase_header_and_second_hint(self, monkeypatch):
        async def go():
            channel, client = _channel()
            sleeps = _patch_retry_sleep(monkeypatch)
            _install(
                client,
                [
                    _api_error(429, {"retry-after": "5"}),
                    _api_error(429, {"Retry-After": "8"}),
                ],
            )

            await channel.send(_reply("again"))

            assert sleeps == [5.0, 8.0]
            assert len(client.posts) == 1

        _run(go())

    def test_hint_above_the_budget_abandons_without_sleeping(self, monkeypatch):
        async def go():
            channel, client = _channel()
            sleeps = _patch_retry_sleep(monkeypatch)
            _install(client, [_api_error(429, {"Retry-After": "120"})])

            with pytest.raises(SlackApiError):
                await channel.send(_reply())

            assert sleeps == []
            assert client.posts == []
            assert SLACK_MAX_OUTBOUND_RETRY_DELAY_SECONDS == 15.0

        _run(go())

    def test_hint_at_the_budget_is_still_waited_out(self, monkeypatch):
        async def go():
            channel, client = _channel()
            sleeps = _patch_retry_sleep(monkeypatch)
            _install(client, [_api_error(429, {"Retry-After": "15"})])

            await channel.send(_reply())

            assert sleeps == [15.0]

        _run(go())

    def test_short_hint_does_not_shrink_the_backoff(self, monkeypatch):
        async def go():
            channel, client = _channel()
            sleeps = _patch_retry_sleep(monkeypatch)
            _install(client, [_api_error(429, {"Retry-After": "0.25"})])

            await channel.send(_reply())

            assert sleeps == [1.0]

        _run(go())

    @pytest.mark.parametrize(
        "error",
        [
            ConnectionError("reset"),
            _api_error(429, {}),
            _api_error(429, {"Retry-After": "soon"}),
            _api_error(429, {"Retry-After": "nan"}),
            _api_error(500, {"Retry-After": "40"}),
        ],
    )
    def test_unusable_hint_keeps_exponential_backoff(self, monkeypatch, error):
        async def go():
            channel, client = _channel()
            sleeps = _patch_retry_sleep(monkeypatch)
            _install(client, [error, error])

            await channel.send(_reply())

            assert sleeps == [1, 2]

        _run(go())

    def test_three_attempts_still_drop_the_reply(self, monkeypatch):
        async def go():
            channel, client = _channel()
            sleeps = _patch_retry_sleep(monkeypatch)
            _install(client, [_api_error(429, {"Retry-After": "15"})] * 3)

            with pytest.raises(SlackApiError):
                await channel.send(_reply())

            assert sleeps == [15.0, 15.0]
            assert client.posts == []

        _run(go())
