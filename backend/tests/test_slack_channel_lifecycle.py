"""Slack stop retains executor-backed connects until their sockets are closed."""

from __future__ import annotations

import asyncio
import contextlib
import socket
import threading
from contextlib import asynccontextmanager
from unittest.mock import MagicMock

import pytest

from app.channels.base import ChannelStopTimeout
from app.channels.message_bus import MessageBus
from app.channels.service import ChannelService
from app.channels.slack import SlackChannel

pytestmark = pytest.mark.asyncio


def _capture_connect(monkeypatch, channel):
    loop = asyncio.get_running_loop()
    run_in_executor = loop.run_in_executor
    futures = []

    def capture(executor, func, *args):
        future = run_in_executor(executor, func, *args)
        if func == channel._connect_socket_mode:
            futures.append(future)
        return future

    monkeypatch.setattr(loop, "run_in_executor", capture)
    return futures


@asynccontextmanager
async def _blocked_connect(monkeypatch):
    import slack_sdk.socket_mode

    started, release = threading.Event(), threading.Event()
    clients = []

    class SocketClient:
        def __init__(self, **kwargs):
            self.socket_mode_request_listeners = []
            self.connect_finished = False
            self.connected = False
            self.close_calls = 0
            clients.append(self)

        def connect(self):
            started.set()
            if not release.wait(5):
                raise TimeoutError("test did not release connection")
            self.connected = True
            self.connect_finished = True

        def close(self):
            self.close_calls += 1
            self.connected = False

    monkeypatch.setattr(slack_sdk.socket_mode, "SocketModeClient", SocketClient)
    channel = SlackChannel(MessageBus(), {"bot_token": "test", "app_token": "test", "bot_user_id": "UBOT", "web_client_factory": lambda **kwargs: object()})
    futures = _capture_connect(monkeypatch, channel)
    try:
        await channel.start()
        assert await asyncio.to_thread(started.wait, 2)
        yield channel, clients, futures[0], release
    finally:
        release.set()
        for future in futures:
            await asyncio.wait_for(asyncio.shield(future), 5)
        monkeypatch.setattr("app.channels.slack.SLACK_STOP_TIMEOUT_SECONDS", 3, raising=False)
        await asyncio.wait_for(channel.stop(), 4)


async def test_stop_preserves_sdk_close_timeout_and_retries():
    error = TimeoutError("SDK close failed")
    socket_client = MagicMock()
    socket_client.close.side_effect = [error, None]
    channel = SlackChannel(MessageBus(), {})
    channel._socket_client = socket_client

    stopping = asyncio.create_task(channel.stop())
    await asyncio.sleep(0)
    cleanup = channel._socket_close_task
    assert cleanup is not None
    with pytest.raises(TimeoutError, match="SDK close failed") as caught:
        await stopping
    # Python may copy TimeoutError across the executor boundary; stop must
    # preserve the exception actually produced by its owned cleanup task.
    assert caught.value is cleanup.exception()
    assert type(caught.value) is TimeoutError
    assert caught.value.__cause__ is not caught.value
    assert channel._socket_client is socket_client
    assert channel._socket_close_task is None
    assert socket_client.close.call_count == 1

    await channel.stop()
    assert socket_client.close.call_count == 2
    assert channel._socket_client is None
    assert channel._socket_close_task is None


async def test_stop_timeout_retains_connect_and_same_cleanup_for_retry(monkeypatch):
    monkeypatch.setattr("app.channels.slack.SLACK_STOP_TIMEOUT_SECONDS", 0.02, raising=False)
    async with _blocked_connect(monkeypatch) as (channel, clients, connect, release):
        with pytest.raises(ChannelStopTimeout, match="cleanup is still running"):
            await channel.stop()
        cleanup = channel._socket_close_task
        assert cleanup is not None and not cleanup.done()
        assert channel._socket_client is clients[0]
        assert channel._socket_connect_future is connect
        assert not connect.done()
        assert clients[0].close_calls == 0

        with pytest.raises(ChannelStopTimeout):
            await channel.start()
        assert channel._socket_close_task is cleanup
        assert len(clients) == 1
        assert not connect.cancelled()

        release.set()
        await asyncio.wait_for(asyncio.shield(cleanup), 2)
        await channel.stop()
        assert clients[0].connect_finished
        assert clients[0].close_calls == 1
        assert not clients[0].connected
        assert channel._socket_client is None
        assert channel._socket_connect_future is None
        assert channel._socket_close_task is None


async def test_cancelling_stop_does_not_cancel_connect_or_duplicate_cleanup(monkeypatch):
    async with _blocked_connect(monkeypatch) as (channel, clients, connect, release):
        stopping = asyncio.create_task(channel.stop())
        await asyncio.sleep(0)
        stopping.cancel()
        with pytest.raises(asyncio.CancelledError):
            await stopping
        cleanup = channel._socket_close_task
        assert cleanup is not None and not cleanup.done()
        assert channel._socket_client is clients[0]
        assert not connect.cancelled()
        assert clients[0].close_calls == 0

        release.set()
        await channel.stop()
        assert clients[0].close_calls == 1
        assert channel._socket_close_task is None


async def test_service_retains_slack_while_connect_is_still_owned(monkeypatch):
    monkeypatch.setattr("app.channels.slack.SLACK_STOP_TIMEOUT_SECONDS", 0.02, raising=False)
    async with _blocked_connect(monkeypatch) as (channel, clients, connect, release):
        service = ChannelService({"slack": {"enabled": True}}, store=MagicMock())
        service._running = True
        service._channels["slack"] = channel
        assert await service.restart_channel("slack", reload_config=False) is False
        assert service._channels["slack"] is channel
        assert channel._socket_client is clients[0]
        assert not connect.cancelled()
        assert len(clients) == 1

        release.set()
        await asyncio.wait_for(asyncio.shield(channel._socket_close_task), 2)
        assert await service.remove_channel("slack") is True
        assert "slack" not in service._channels
        assert clients[0].close_calls == 1


async def test_real_sdk_late_connection_is_closed_before_stop_completes(monkeypatch):
    from websockets.asyncio.server import serve

    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr("app.channels.slack.SLACK_STOP_TIMEOUT_SECONDS", 0.02, raising=False)
    discovery_started, release_discovery = threading.Event(), threading.Event()
    accepted, peer_closed = asyncio.Event(), asyncio.Event()
    peers = []

    async def handler(peer):
        peers.append(peer)
        accepted.set()
        await peer.wait_closed()
        peer_closed.set()

    async with serve(handler, "127.0.0.1", 0, ping_interval=None, close_timeout=0.2) as server:
        port = server.sockets[0].getsockname()[1]

        class WebClient:
            ssl = None

            def __init__(self, **kwargs):
                pass

            def apps_connections_open(self, **kwargs):
                discovery_started.set()
                if not release_discovery.wait(5):
                    raise TimeoutError("test did not release local URL discovery")
                return {"url": f"ws://127.0.0.1:{port}/socket-mode"}

        channel = SlackChannel(MessageBus(), {"bot_token": "test", "app_token": "test", "bot_user_id": "UBOT", "web_client_factory": WebClient})
        futures = _capture_connect(monkeypatch, channel)
        sdk = None
        try:
            await channel.start()
            sdk = channel._socket_client
            assert await asyncio.to_thread(discovery_started.wait, 2)
            with pytest.raises(ChannelStopTimeout):
                await channel.stop()
            assert channel._socket_client is sdk
            assert not futures[0].cancelled()
            release_discovery.set()
            monkeypatch.setattr("app.channels.slack.SLACK_STOP_TIMEOUT_SECONDS", 5)
            await asyncio.wait_for(channel.stop(), 6)
            await asyncio.wait_for(accepted.wait(), 2)
            await asyncio.wait_for(peer_closed.wait(), 2)
            assert not sdk.is_connected()
            assert sdk.closed is True
            assert sdk.auto_reconnect_enabled is False
            assert channel._socket_client is None
            assert channel._socket_connect_future is None
        finally:
            release_discovery.set()
            for future in futures:
                await asyncio.wait_for(asyncio.shield(future), 5)
            if sdk is not None:
                # slack-sdk 3.41.0 leaves its receiver interval runner alive
                # after close; explicitly reap the test-owned runner as well.
                sdk.auto_reconnect_enabled = False
                sdk.default_auto_reconnect_enabled = False
                if sdk.current_session is not None:
                    sdk.current_session_state.terminated = True
                    sock = sdk.current_session.sock
                    if sock is not None:
                        with contextlib.suppress(OSError):
                            sock.shutdown(socket.SHUT_RDWR)
                await asyncio.wait_for(asyncio.to_thread(sdk.close), 5)
                await asyncio.wait_for(asyncio.to_thread(sdk.current_session_runner.shutdown), 3)
            for peer in peers:
                peer.transport.abort()
