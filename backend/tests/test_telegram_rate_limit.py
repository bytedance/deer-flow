"""Offline Bot API responses exercise the SDK and real outbound delivery path."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
import pytest_asyncio
from telegram import Bot
from telegram.error import RetryAfter
from telegram.request import BaseRequest

from app.channels import base as base_module
from app.channels.message_bus import MessageBus, OutboundMessage
from app.channels.telegram import TelegramChannel


class _BotAPI(BaseRequest):
    def __init__(self):
        self.now = 0.0
        self.calls = []
        self.delivered = []
        self.sleeps = []
        self.limit_after = None
        self.blocked_until = None
        self.always_limited = False
        self.retry_after = 30
        self.transient_failures = 0
        self.retry_hints = None

    @property
    def read_timeout(self):
        return 5

    async def initialize(self):
        pass

    async def shutdown(self):
        pass

    async def do_request(self, url, method, request_data=None, **kwargs):
        endpoint = url.rsplit("/", 1)[-1]
        parameters = request_data.parameters if request_data else {}
        if endpoint == "getMe":
            result = {"id": 1, "is_bot": True, "first_name": "Offline", "username": "offline_bot"}
            return 200, json.dumps({"ok": True, "result": result}).encode()

        self.calls.append((endpoint, self.now, parameters))
        if self.transient_failures:
            self.transient_failures -= 1
            return 500, json.dumps({"ok": False, "error_code": 500, "description": "Internal Server Error"}).encode()
        if self.retry_hints:
            remaining = self.retry_hints.pop(0)
            return 429, json.dumps({"ok": False, "error_code": 429, "description": "Too Many Requests", "parameters": {"retry_after": remaining}}).encode()
        if self.limit_after is not None and self.blocked_until is None and len(self.delivered) >= self.limit_after:
            self.blocked_until = self.now + 30
        if self.always_limited or (self.blocked_until is not None and self.now < self.blocked_until):
            remaining = self.retry_after if self.always_limited else int(self.blocked_until - self.now)
            return 429, json.dumps({"ok": False, "error_code": 429, "description": "Too Many Requests", "parameters": {"retry_after": remaining}}).encode()

        text = parameters.get("text") or parameters["rich_message"]["markdown"]
        self.delivered.append(text)
        result = {
            "message_id": parameters.get("message_id", 100 + len(self.delivered)),
            "date": 0,
            "chat": {"id": parameters["chat_id"], "type": "private"},
            "text": text,
        }
        return 200, json.dumps({"ok": True, "result": result}).encode()

    async def sleep(self, delay):
        self.sleeps.append(delay)
        self.now += delay


@pytest_asyncio.fixture
async def delivery(monkeypatch):
    monkeypatch.setenv("PTB_TIMEDELTA", "1")
    api = _BotAPI()
    async with Bot("123:offline-token", request=api, get_updates_request=api) as bot:
        channel = TelegramChannel(MessageBus(), {})
        channel._application = SimpleNamespace(bot=bot)
        monkeypatch.setattr(base_module.asyncio, "sleep", api.sleep)
        yield channel, api


def _reply(text="Complete report", **kwargs):
    return OutboundMessage(channel_name="telegram", chat_id="12345", thread_id="offline-thread", text=text, **kwargs)


class _OtherChannel(base_module.Channel):
    """Stand-in for a non-Telegram provider that shares ``_send_with_retry``."""

    def __init__(self, bus: MessageBus) -> None:
        super().__init__(name="other", bus=bus, config={})

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def send(self, msg: OutboundMessage) -> None:
        return None


@pytest.mark.asyncio
@pytest.mark.parametrize("use_timedelta", [False, True])
@pytest.mark.parametrize("rich", [False, True])
async def test_new_reply_waits_for_server_retry_after(delivery, monkeypatch, use_timedelta, rich):
    monkeypatch.setenv("PTB_TIMEDELTA", "1" if use_timedelta else "0")
    channel, api = delivery
    api.limit_after = 0
    channel.config["rich_messages"] = rich
    text = "**Complete report**" if rich else "Complete report"

    await channel.send(_reply(text))

    assert api.sleeps == [30]
    assert [time for _, time, _ in api.calls] == [0, 30]
    assert api.delivered == [text]
    assert [endpoint for endpoint, _, _ in api.calls] == ["sendRichMessage" if rich else "sendMessage"] * 2


@pytest.mark.asyncio
@pytest.mark.parametrize("with_preview", [False, True])
async def test_limited_overflow_preserves_every_chunk_once(delivery, with_preview):
    channel, api = delivery
    text = "A" * 4096 + "B" * 4096 + "C" * 20
    if with_preview:
        await channel.send(_reply("Working on it...", is_final=False, thread_ts="42"))
        api.delivered.clear()
        api.calls.clear()
    api.limit_after = 1

    await channel.send(_reply(text, thread_ts="42"))

    assert api.sleeps == [30]
    assert api.delivered == ["A" * 4096, "B" * 4096, "C" * 20]
    assert "".join(api.delivered) == text
    assert len(api.calls) == 4
    assert api.calls[0][0] == ("editMessageText" if with_preview else "sendMessage")
    assert api.calls[-1][2]["reply_parameters"]["message_id"] == 102


@pytest.mark.asyncio
@pytest.mark.parametrize(("retry_after", "expected_sleeps"), [(30, [30, 30]), (120, [60, 60])])
async def test_persistent_flood_control_keeps_attempt_limit(delivery, retry_after, expected_sleeps):
    channel, api = delivery
    api.always_limited = True
    api.retry_after = retry_after

    with pytest.raises(RetryAfter):
        await channel.send(_reply(), _max_retries=3)

    assert len(api.calls) == 3
    assert api.sleeps == expected_sleeps
    assert api.delivered == []


@pytest.mark.asyncio
async def test_short_server_delay_does_not_shorten_local_backoff(delivery):
    channel, api = delivery
    api.always_limited = True
    api.retry_after = 1

    with pytest.raises(RetryAfter):
        await channel.send(_reply(), _max_retries=3)

    assert api.sleeps == [1, 2]
    assert len(api.calls) == 3


@pytest.mark.parametrize(
    "bad_hint",
    [float("inf"), float("nan"), "invalid", {}, 10**400],
    ids=["infinite", "nan", "nonnumeric", "wrong-type", "overflow"],
)
def test_unusable_hint_keeps_local_backoff(bad_hint):
    exc = SimpleNamespace(retry_after=bad_hint)
    channel = TelegramChannel.__new__(TelegramChannel)
    # attempt=2 -> base backoff 2**2=4; an unusable hint must not change it.
    assert channel._send_retry_delay(exc, 2) == 4


@pytest.mark.asyncio
async def test_cancelled_flood_wait_does_not_send_again(delivery, monkeypatch):
    channel, api = delivery
    api.limit_after = 0
    waiting = asyncio.Event()
    never = asyncio.Event()

    async def wait(delay):
        api.sleeps.append(delay)
        waiting.set()
        await never.wait()

    monkeypatch.setattr(base_module.asyncio, "sleep", wait)
    task = asyncio.create_task(channel.send(_reply()))
    try:
        await asyncio.wait_for(waiting.wait(), timeout=3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    assert api.sleeps == [30]
    assert len(api.calls) == 1
    assert api.delivered == []


@pytest.mark.asyncio
async def test_short_reply_without_flood_control_is_unchanged(delivery):
    channel, api = delivery

    await channel.send(_reply())

    assert api.sleeps == []
    assert api.delivered == ["Complete report"]
    assert len(api.calls) == 1


@pytest.mark.asyncio
async def test_network_errors_keep_exponential_backoff(delivery):
    channel, api = delivery
    api.transient_failures = 2

    await channel.send(_reply())

    assert api.sleeps == [1, 2]
    assert api.delivered == ["Complete report"]
    assert len(api.calls) == 3


@pytest.mark.asyncio
async def test_each_attempt_uses_that_response_hint(delivery):
    channel, api = delivery
    api.retry_hints = [5, 20]

    await channel.send(_reply())

    assert api.sleeps == [5, 20]
    assert api.delivered == ["Complete report"]
    assert len(api.calls) == 3


@pytest.mark.asyncio
async def test_other_channels_keep_ignoring_retry_after(monkeypatch):
    sleeps: list[float] = []

    async def track_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(base_module.asyncio, "sleep", track_sleep)
    channel = _OtherChannel(MessageBus())
    attempts = {"n": 0}

    async def flaky():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RetryAfter(retry_after=50)
        return "sent"

    result = await channel._send_with_retry(flaky, max_retries=3)

    assert result == "sent"
    assert attempts["n"] == 3
    assert sleeps == [1, 2]
