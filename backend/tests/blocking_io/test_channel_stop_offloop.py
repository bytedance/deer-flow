"""Regression anchor: channel ``stop()`` must not block the event loop on SDK teardown.

``stop()`` runs on the Gateway event loop, both at shutdown and from
``POST /api/channels/{name}/restart``, so a blocking teardown call there stalls
every run, stream and channel the Gateway serves:

- Slack: ``SocketModeClient.close()`` joins the SDK's message-processor thread
  and waits for in-flight listeners.
- Feishu / DingTalk: ``stop()`` asks the SDK thread's private event loop to
  shut down, then joins that thread with a 5s timeout.
- Discord: ``stop()`` joins the client thread with a 10s timeout, which a
  timed-out client close or a slow ``_run_client()`` drain can use up.

Each test drives the real ``stop()`` (and, for Slack, a real slack-sdk client).
If a join or close regresses back onto the event loop, the strict Blockbuster
gate raises ``BlockingError`` from the thread-join lock wait.
"""

from __future__ import annotations

import asyncio
import threading

import pytest

from app.channels.base import ChannelStopTimeout
from app.channels.dingtalk import DingTalkChannel
from app.channels.discord import DiscordChannel
from app.channels.feishu import FeishuChannel
from app.channels.message_bus import MessageBus
from app.channels.slack import SlackChannel
from app.channels.telegram import TelegramChannel

pytestmark = pytest.mark.asyncio


async def test_slack_stop_closes_real_socket_mode_client_off_loop() -> None:
    from slack_sdk.socket_mode import SocketModeClient

    # Never connected: construction alone starts the SDK's worker threads,
    # which is what close() has to join.
    socket_client = SocketModeClient(app_token="xapp-test")
    channel = SlackChannel(bus=MessageBus(), config={})
    channel._socket_client = socket_client
    channel._running = True

    await channel.stop()

    assert socket_client.closed is True
    assert channel._socket_client is None


async def test_slack_stop_keeps_connect_cleanup_off_loop(monkeypatch) -> None:
    started, release = threading.Event(), threading.Event()
    loop_thread = threading.get_ident()
    close_threads = []

    class SocketClient:
        def connect(self):
            started.set()
            release.wait(5)

        def close(self):
            close_threads.append(threading.get_ident())

    monkeypatch.setattr("app.channels.slack.SLACK_STOP_TIMEOUT_SECONDS", 0.02)
    channel = SlackChannel(MessageBus(), {})
    client = SocketClient()
    channel._socket_client = client
    channel._running = True
    future = asyncio.get_running_loop().run_in_executor(None, channel._connect_socket_mode, client)
    channel._socket_connect_future = future
    try:
        assert await asyncio.to_thread(started.wait, 2)
        with pytest.raises(ChannelStopTimeout):
            await channel.stop()
        assert not future.cancelled()
        assert close_threads == []
        release.set()
        await asyncio.wait_for(asyncio.shield(channel._socket_close_task), 2)
        await channel.stop()
        assert len(close_threads) == 1
        assert close_threads[0] != loop_thread
        assert channel._socket_client is None
    finally:
        release.set()
        await asyncio.wait_for(asyncio.shield(future), 5)
        monkeypatch.setattr("app.channels.slack.SLACK_STOP_TIMEOUT_SECONDS", 3)
        await channel.stop()


@pytest.mark.parametrize("channel_cls", [FeishuChannel, DingTalkChannel, DiscordChannel, TelegramChannel])
async def test_stop_joins_sdk_thread_off_loop(channel_cls) -> None:
    release = threading.Event()
    sdk_thread = threading.Thread(target=release.wait, daemon=True)
    sdk_thread.start()
    channel = channel_cls(MessageBus(), {})
    channel._thread = sdk_thread
    channel._running = True
    release.set()

    await channel.stop()

    assert not sdk_thread.is_alive()
    assert channel._thread is None


@pytest.mark.parametrize(
    ("channel_cls", "loop_attr"),
    [(FeishuChannel, "_ws_loop"), (DingTalkChannel, "_stream_loop")],
)
async def test_stop_ends_live_sdk_loop_off_loop(channel_cls, loop_attr) -> None:
    sdk_loop = asyncio.new_event_loop()
    ready = threading.Event()

    def run_sdk_loop() -> None:
        asyncio.set_event_loop(sdk_loop)
        sdk_loop.call_soon(ready.set)
        try:
            sdk_loop.run_forever()
        finally:
            sdk_loop.close()

    sdk_thread = threading.Thread(target=run_sdk_loop, daemon=True)
    sdk_thread.start()
    assert await asyncio.to_thread(ready.wait, 5)
    channel = channel_cls(MessageBus(), {})
    channel._thread = sdk_thread
    channel._running = True
    setattr(channel, loop_attr, sdk_loop)

    await channel.stop()

    assert not sdk_thread.is_alive()
    assert sdk_loop.is_closed()
    assert channel._thread is None
    assert getattr(channel, loop_attr) is None
