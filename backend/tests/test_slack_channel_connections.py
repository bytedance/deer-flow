"""Slack OAuth Events tests for user-owned channel connections."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient

from app.channels.message_bus import MessageBus, OutboundMessage
from app.channels.providers.slack_connect import verify_slack_signature
from app.gateway.auth.models import User
from app.gateway.routers import channel_connections
from deerflow.config.channel_connections_config import ChannelConnectionsConfig


def _user() -> User:
    return User(
        id=UUID("11111111-2222-3333-4444-555555555555"),
        email="alice@example.com",
        password_hash="x",
        system_role="user",
    )


async def _make_repo(tmp_path):
    from deerflow.persistence.channel_connections import ChannelConnectionRepository, ChannelCredentialCipher
    from deerflow.persistence.engine import get_session_factory, init_engine

    await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path / 'slack.db'}", sqlite_dir=str(tmp_path))
    return ChannelConnectionRepository(
        get_session_factory(),
        cipher=ChannelCredentialCipher.from_key("slack-secret"),
    )


def _make_app(config: ChannelConnectionsConfig, repo, bus):
    app = make_authed_test_app(user_factory=_user)
    app.state.channel_connections_config = config
    app.state.channel_connection_repo = repo
    app.state.channel_message_bus = bus
    app.include_router(channel_connections.router)
    return app


def _slack_signature(signing_secret: str, timestamp: str, body: bytes) -> str:
    base = f"v0:{timestamp}:".encode() + body
    digest = hmac.new(signing_secret.encode("utf-8"), base, hashlib.sha256).hexdigest()
    return f"v0={digest}"


def test_verify_slack_signature_accepts_valid_signature():
    body = b'{"type":"event_callback"}'
    timestamp = "1710000000"
    signature = _slack_signature("secret", timestamp, body)

    assert verify_slack_signature(
        signing_secret="secret",
        timestamp=timestamp,
        body=body,
        signature=signature,
        now=1710000001,
    )


def test_verify_slack_signature_rejects_stale_timestamp():
    body = b'{"type":"event_callback"}'
    timestamp = "1710000000"
    signature = _slack_signature("secret", timestamp, body)

    assert not verify_slack_signature(
        signing_secret="secret",
        timestamp=timestamp,
        body=body,
        signature=signature,
        now=1710001000,
    )


def test_slack_events_webhook_publishes_connection_scoped_inbound(tmp_path):
    import anyio

    repo = anyio.run(_make_repo, tmp_path)

    async def seed_connection():
        return await repo.upsert_connection(
            owner_user_id=str(_user().id),
            provider="slack",
            external_account_id="U123",
            workspace_id="T123",
            workspace_name="Deer Team",
            status="connected",
        )

    connection = anyio.run(seed_connection)
    bus = AsyncMock()
    app = _make_app(
        ChannelConnectionsConfig.model_validate(
            {
                "enabled": True,
                "public_base_url": "https://deerflow.example.com",
                "encryption_key": "slack-secret",
                "slack": {
                    "enabled": True,
                    "client_id": "slack-client",
                    "client_secret": "slack-secret",
                    "signing_secret": "slack-signing-secret",
                },
            }
        ),
        repo,
        bus,
    )
    payload = {
        "type": "event_callback",
        "event_id": "Ev123",
        "team_id": "T123",
        "event": {
            "type": "app_mention",
            "user": "U123",
            "channel": "C123",
            "text": "hello deerflow",
            "ts": "1710000000.000100",
        },
    }
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    timestamp = str(int(time.time()))
    headers = {
        "X-Slack-Request-Timestamp": timestamp,
        "X-Slack-Signature": _slack_signature("slack-signing-secret", timestamp, body),
    }

    with TestClient(app) as client:
        response = client.post("/api/channels/webhooks/slack/events", content=body, headers=headers)
        duplicate = client.post("/api/channels/webhooks/slack/events", content=body, headers=headers)

    assert response.status_code == 200
    assert response.json() == {"ok": True, "processed": True}
    assert duplicate.status_code == 200
    assert duplicate.json() == {"ok": True, "duplicate": True, "processed": False}
    bus.publish_inbound.assert_awaited_once()
    inbound = bus.publish_inbound.call_args.args[0]
    assert inbound.connection_id == connection["id"]
    assert inbound.owner_user_id == str(_user().id)
    assert inbound.workspace_id == "T123"
    assert inbound.chat_id == "C123"
    assert inbound.user_id == "U123"
    assert inbound.text == "hello deerflow"
    assert inbound.topic_id == "1710000000.000100"

    anyio.run(repo.close)


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
