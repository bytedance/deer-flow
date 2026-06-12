"""Slack connection tests for user-owned channel bindings."""

from __future__ import annotations

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


def test_slack_http_events_mode_initializes_operator_web_client(monkeypatch):
    import anyio

    from app.channels.slack import SlackChannel

    class FakeWebClient:
        def __init__(self, token: str) -> None:
            self.token = token
            self.messages: list[dict] = []

        def auth_test(self):
            return {"user_id": "B-http"}

        def chat_postMessage(self, **kwargs):
            self.messages.append(kwargs)

    slack_sdk = ModuleType("slack_sdk")
    slack_sdk.WebClient = FakeWebClient
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
                "event_delivery": "http",
                "connection_repo": MagicMock(),
            },
        )

        await channel.start()
        assert channel._running is True
        assert channel._web_client is not None
        assert channel._web_client.token == "xoxb-operator"
        assert channel._bot_user_id == "B-http"

        await channel._post_connection_reply("C123", "Slack connected to DeerFlow.", "1710000000.000100")

        assert channel._web_client.messages == [
            {
                "channel": "C123",
                "text": "Slack connected to DeerFlow.",
                "thread_ts": "1710000000.000100",
            }
        ]
        await channel.stop()

    anyio.run(go)
