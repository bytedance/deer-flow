"""Slack connection tests for user-owned channel bindings."""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock

from app.channels.message_bus import MessageBus, OutboundMessage


async def _make_repo(tmp_path):
    from deerflow.persistence.channel_connections import ChannelConnectionRepository, ChannelCredentialCipher
    from deerflow.persistence.engine import get_session_factory, init_engine

    await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path / 'slack.db'}", sqlite_dir=str(tmp_path))
    return ChannelConnectionRepository(
        get_session_factory(),
        cipher=ChannelCredentialCipher.from_key("slack-secret"),
    )


def test_slack_connect_command_binds_socket_mode_identity(tmp_path):
    import anyio

    from app.channels.slack import SlackChannel

    async def go():
        repo = await _make_repo(tmp_path)
        state = "slack-bind-code"
        await repo.create_oauth_state(
            owner_user_id="deerflow-user-1",
            provider="slack",
            state=state,
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        channel = SlackChannel(
            bus=MessageBus(),
            config={"bot_token": "xoxb-operator", "app_token": "xapp-operator", "connection_repo": repo},
        )
        channel._web_client = MagicMock()

        handled = await channel._bind_connection_from_connect_code(
            event={
                "user": "U123",
                "channel": "C123",
                "ts": "1710000000.000100",
            },
            team_id="T123",
            code=state,
        )

        connections = await repo.list_connections("deerflow-user-1")
        assert handled is True
        assert len(connections) == 1
        assert connections[0]["provider"] == "slack"
        assert connections[0]["external_account_id"] == "U123"
        assert connections[0]["workspace_id"] == "T123"
        assert connections[0]["metadata"]["channel_id"] == "C123"
        channel._web_client.chat_postMessage.assert_called_once()
        await repo.close()

    anyio.run(go)


def test_slack_send_uses_connection_bot_token_when_connection_id_is_present():
    import anyio

    from app.channels.slack import SlackChannel

    async def go():
        repo = AsyncMock()
        repo.get_credentials.return_value = {"access_token": "xoxb-connection-token"}
        web_client = MagicMock()
        web_client_factory = MagicMock(return_value=web_client)
        channel = SlackChannel(
            bus=MessageBus(),
            config={
                "connection_repo": repo,
                "web_client_factory": web_client_factory,
            },
        )

        msg = OutboundMessage(
            channel_name="slack",
            chat_id="C123",
            thread_id="thread-1",
            text="hello",
            connection_id="connection-1",
        )
        await channel.send(msg)

        repo.get_credentials.assert_awaited_once_with("connection-1")
        web_client_factory.assert_called_once_with(token="xoxb-connection-token")
        web_client.chat_postMessage.assert_called_once()

    anyio.run(go)


def test_slack_http_events_mode_is_rejected(monkeypatch, caplog):
    import anyio

    from app.channels.slack import SlackChannel

    slack_sdk = ModuleType("slack_sdk")
    slack_sdk.WebClient = object
    socket_mode = ModuleType("slack_sdk.socket_mode")
    socket_mode.SocketModeClient = object
    response = ModuleType("slack_sdk.socket_mode.response")
    response.SocketModeResponse = object
    monkeypatch.setitem(sys.modules, "slack_sdk", slack_sdk)
    monkeypatch.setitem(sys.modules, "slack_sdk.socket_mode", socket_mode)
    monkeypatch.setitem(sys.modules, "slack_sdk.socket_mode.response", response)

    async def go():
        channel = SlackChannel(
            bus=MessageBus(),
            config={
                "bot_token": "xoxb-operator",
                # Provide app_token too so the missing-token early return cannot
                # fire before the HTTP-mode guard — otherwise the state assertions
                # below would hold even if the guard were deleted.
                "app_token": "xapp-token",
                "event_delivery": "http",
                "connection_repo": MagicMock(),
            },
        )

        with caplog.at_level("ERROR", logger="app.channels.slack"):
            await channel.start()

        assert channel._running is False
        assert channel._web_client is None
        assert "Slack HTTP Events mode is not supported" in caplog.text

    anyio.run(go)


def test_slack_socket_mode_connect_failure_is_logged(monkeypatch, caplog):
    import anyio

    from app.channels.slack import SlackChannel

    class FailingSocketModeClient:
        def __init__(self, *, app_token, web_client):
            self.socket_mode_request_listeners = []

        def connect(self):
            raise RuntimeError("apps.connections.open failed: invalid_auth")

        def close(self):
            pass

    slack_sdk = ModuleType("slack_sdk")
    slack_sdk.WebClient = MagicMock
    socket_mode = ModuleType("slack_sdk.socket_mode")
    socket_mode.SocketModeClient = FailingSocketModeClient
    response = ModuleType("slack_sdk.socket_mode.response")
    response.SocketModeResponse = object
    monkeypatch.setitem(sys.modules, "slack_sdk", slack_sdk)
    monkeypatch.setitem(sys.modules, "slack_sdk.socket_mode", socket_mode)
    monkeypatch.setitem(sys.modules, "slack_sdk.socket_mode.response", response)

    async def go():
        channel = SlackChannel(
            bus=MessageBus(),
            config={
                "bot_token": "xoxb-operator",
                "app_token": "xapp-token",
                # A configured bot user id skips the auth_test lookup, so the
                # only background work start() schedules is the connect.
                "bot_user_id": "UBOT",
                "connection_repo": MagicMock(),
            },
        )

        # start() drops the future for the executor-backed connect; capture it
        # here so the test can wait for the connect attempt to finish.
        loop = asyncio.get_running_loop()
        real_run_in_executor = loop.run_in_executor
        connect_futures = []

        def capture_run_in_executor(executor, func, *args):
            future = real_run_in_executor(executor, func, *args)
            connect_futures.append(future)
            return future

        monkeypatch.setattr(loop, "run_in_executor", capture_run_in_executor)

        with caplog.at_level("ERROR", logger="app.channels.slack"):
            await channel.start()
            assert len(connect_futures) == 1
            await asyncio.gather(*connect_futures, return_exceptions=True)
        await channel.stop()

        assert "Socket Mode connection failed" in caplog.text

    anyio.run(go)


def test_slack_socket_mode_queued_connect_does_not_target_replacement_client(monkeypatch):
    import anyio

    from app.channels.slack import SlackChannel

    clients = []

    class RecordingSocketModeClient:
        def __init__(self, *, app_token, web_client):
            self.socket_mode_request_listeners = []
            self.connect_calls = 0
            clients.append(self)

        def connect(self):
            self.connect_calls += 1

        def close(self):
            pass

    slack_sdk = ModuleType("slack_sdk")
    slack_sdk.WebClient = MagicMock
    socket_mode = ModuleType("slack_sdk.socket_mode")
    socket_mode.SocketModeClient = RecordingSocketModeClient
    response = ModuleType("slack_sdk.socket_mode.response")
    response.SocketModeResponse = object
    monkeypatch.setitem(sys.modules, "slack_sdk", slack_sdk)
    monkeypatch.setitem(sys.modules, "slack_sdk.socket_mode", socket_mode)
    monkeypatch.setitem(sys.modules, "slack_sdk.socket_mode.response", response)

    async def go():
        channel = SlackChannel(
            bus=MessageBus(),
            config={
                "bot_token": "xoxb-operator",
                "app_token": "xapp-token",
                "bot_user_id": "UBOT",
                "connection_repo": MagicMock(),
            },
        )
        queued_callbacks = []
        loop = asyncio.get_running_loop()

        def queue_run_in_executor(executor, func, *args):
            queued_callbacks.append((func, args))
            return loop.create_future()

        monkeypatch.setattr(loop, "run_in_executor", queue_run_in_executor)

        await channel.start()
        await channel.stop()
        await channel.start()

        assert len(clients) == 2
        assert len(queued_callbacks) == 2

        stale_func, stale_args = queued_callbacks[0]
        stale_func(*stale_args)
        assert clients[0].connect_calls == 0
        assert clients[1].connect_calls == 0

        current_func, current_args = queued_callbacks[1]
        current_func(*current_args)
        assert clients[0].connect_calls == 0
        assert clients[1].connect_calls == 1

        await channel.stop()

    anyio.run(go)
