"""Regression anchor: channel ``stop()`` must not block the event loop on SDK teardown.

``stop()`` runs on the Gateway event loop, both at shutdown and from
``POST /api/channels/{name}/restart``, so a blocking teardown call there stalls
every run, stream and channel the Gateway serves:

- Slack: ``SocketModeClient.close()`` joins the SDK's message-processor thread
  and waits for in-flight listeners.
- Feishu / DingTalk: ``stop()`` joins the SDK thread with a 5s timeout, and
  that thread only returns on a fatal error.

Each test drives the real ``stop()`` (and, for Slack, a real slack-sdk client).
If a join or close regresses back onto the event loop, the strict Blockbuster
gate raises ``BlockingError`` from the thread-join lock wait.
"""

from __future__ import annotations

import threading

import pytest

from app.channels.dingtalk import DingTalkChannel
from app.channels.feishu import FeishuChannel
from app.channels.message_bus import MessageBus
from app.channels.slack import SlackChannel

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


@pytest.mark.parametrize("channel_cls", [FeishuChannel, DingTalkChannel])
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
