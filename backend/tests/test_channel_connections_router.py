"""Router tests for browser-connectable IM channels."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse
from uuid import UUID

from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient

from app.channels.providers.discord_connect import DiscordIdentity
from app.channels.providers.slack_connect import SlackInstall
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


async def _make_repo(tmp_path, encryption_key: str | None = "router-secret"):
    from deerflow.persistence.channel_connections import ChannelConnectionRepository, ChannelCredentialCipher
    from deerflow.persistence.engine import get_session_factory, init_engine

    await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path / 'router.db'}", sqlite_dir=str(tmp_path))
    cipher = ChannelCredentialCipher.from_key(encryption_key) if encryption_key else None
    return ChannelConnectionRepository(get_session_factory(), cipher=cipher)


def _make_app(config: ChannelConnectionsConfig, repo):
    app = make_authed_test_app(user_factory=_user)
    app.state.channel_connections_config = config
    app.state.channel_connection_repo = repo
    app.include_router(channel_connections.router)
    return app


def test_get_providers_returns_catalog_and_current_status(tmp_path):
    import anyio

    repo = anyio.run(_make_repo, tmp_path)
    config = ChannelConnectionsConfig.model_validate(
        {
            "enabled": True,
            "public_base_url": "https://deerflow.example.com",
            "encryption_key": "router-secret",
            "telegram": {
                "enabled": True,
                "bot_token": "telegram-token",
                "bot_username": "deerflow_bot",
                "webhook_secret": "telegram-secret",
            },
            "slack": {"enabled": True, "client_id": "slack-client"},
        }
    )
    app = _make_app(config, repo)

    with TestClient(app) as client:
        response = client.get("/api/channels/providers")

    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    telegram = next(item for item in body["providers"] if item["provider"] == "telegram")
    slack = next(item for item in body["providers"] if item["provider"] == "slack")
    assert telegram["enabled"] is True
    assert telegram["configured"] is True
    assert telegram["connection_status"] == "not_connected"
    assert slack["enabled"] is True
    assert slack["configured"] is False

    anyio.run(repo.close)


def test_get_connections_returns_current_user_connections_only(tmp_path):
    import anyio

    repo = anyio.run(_make_repo, tmp_path)

    async def seed_connections():
        await repo.upsert_connection(
            owner_user_id=str(_user().id),
            provider="telegram",
            external_account_id="42",
            external_account_name="Alice",
            status="connected",
        )
        await repo.upsert_connection(
            owner_user_id="other-user",
            provider="telegram",
            external_account_id="99",
            external_account_name="Bob",
            status="connected",
        )

    anyio.run(seed_connections)
    app = _make_app(
        ChannelConnectionsConfig.model_validate(
            {
                "enabled": True,
                "public_base_url": "https://deerflow.example.com",
                "encryption_key": "router-secret",
            }
        ),
        repo,
    )

    with TestClient(app) as client:
        response = client.get("/api/channels/connections")

    assert response.status_code == 200
    body = response.json()
    assert len(body["connections"]) == 1
    assert body["connections"][0]["provider"] == "telegram"
    assert body["connections"][0]["external_account_id"] == "42"

    anyio.run(repo.close)


def test_connect_telegram_returns_deep_link_and_persists_state(tmp_path):
    import anyio

    repo = anyio.run(_make_repo, tmp_path)
    app = _make_app(
        ChannelConnectionsConfig.model_validate(
            {
                "enabled": True,
                "public_base_url": "https://deerflow.example.com",
                "encryption_key": "router-secret",
                "telegram": {
                    "enabled": True,
                    "bot_token": "telegram-token",
                    "bot_username": "deerflow_bot",
                    "webhook_secret": "telegram-secret",
                },
            }
        ),
        repo,
    )

    with TestClient(app) as client:
        response = client.post("/api/channels/telegram/connect")

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "telegram"
    assert body["mode"] == "deep_link"
    assert body["url"].startswith("https://t.me/deerflow_bot?start=")

    async def count_states():
        return await repo.count_oauth_states(owner_user_id=str(_user().id), provider="telegram")

    assert anyio.run(count_states) == 1

    anyio.run(repo.close)


def test_connect_telegram_local_mode_without_public_url_or_encryption_key(tmp_path):
    import anyio

    repo = anyio.run(_make_repo, tmp_path, None)
    app = _make_app(
        ChannelConnectionsConfig.model_validate(
            {
                "enabled": True,
                "mode": "local",
                "telegram": {
                    "enabled": True,
                    "bot_token": "telegram-token",
                    "bot_username": "deerflow_bot",
                },
            }
        ),
        repo,
    )

    with TestClient(app) as client:
        response = client.post("/api/channels/telegram/connect")

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "telegram"
    assert body["url"].startswith("https://t.me/deerflow_bot?start=")

    async def count_states():
        return await repo.count_oauth_states(owner_user_id=str(_user().id), provider="telegram")

    assert anyio.run(count_states) == 1

    anyio.run(repo.close)


def test_get_providers_reports_slack_http_unavailable_without_public_url(tmp_path):
    import anyio

    repo = anyio.run(_make_repo, tmp_path)
    config = ChannelConnectionsConfig.model_validate(
        {
            "enabled": True,
            "mode": "local",
            "encryption_key": "router-secret",
            "slack": {
                "enabled": True,
                "client_id": "slack-client",
                "client_secret": "slack-secret",
                "signing_secret": "slack-signing-secret",
                "event_delivery": "http",
            },
        }
    )
    app = _make_app(config, repo)

    with TestClient(app) as client:
        response = client.get("/api/channels/providers")

    assert response.status_code == 200
    slack = next(item for item in response.json()["providers"] if item["provider"] == "slack")
    assert slack["enabled"] is True
    assert slack["configured"] is True
    assert slack["connectable"] is False
    assert "public_base_url" in slack["unavailable_reason"]

    anyio.run(repo.close)


def test_connect_unconfigured_provider_returns_400(tmp_path):
    import anyio

    repo = anyio.run(_make_repo, tmp_path)
    app = _make_app(
        ChannelConnectionsConfig.model_validate(
            {
                "enabled": True,
                "public_base_url": "https://deerflow.example.com",
                "encryption_key": "router-secret",
                "slack": {"enabled": True, "client_id": "slack-client"},
            }
        ),
        repo,
    )

    with TestClient(app) as client:
        response = client.post("/api/channels/slack/connect")

    assert response.status_code == 400
    assert response.json()["detail"] == "Channel provider is not configured"

    anyio.run(repo.close)


def test_connect_slack_http_without_public_url_returns_400(tmp_path):
    import anyio

    repo = anyio.run(_make_repo, tmp_path)
    app = _make_app(
        ChannelConnectionsConfig.model_validate(
            {
                "enabled": True,
                "mode": "local",
                "encryption_key": "router-secret",
                "slack": {
                    "enabled": True,
                    "client_id": "slack-client",
                    "client_secret": "slack-secret",
                    "signing_secret": "slack-signing-secret",
                    "event_delivery": "http",
                },
            }
        ),
        repo,
    )

    with TestClient(app) as client:
        response = client.post("/api/channels/slack/connect")

    assert response.status_code == 400
    assert "public_base_url" in response.json()["detail"]

    anyio.run(repo.close)


def test_connect_discord_uses_request_base_url_without_public_base_url(tmp_path):
    import anyio

    repo = anyio.run(_make_repo, tmp_path)
    app = _make_app(
        ChannelConnectionsConfig.model_validate(
            {
                "enabled": True,
                "mode": "local",
                "encryption_key": "router-secret",
                "discord": {
                    "enabled": True,
                    "client_id": "discord-client",
                    "client_secret": "discord-secret",
                    "bot_token": "discord-bot",
                    "permissions": "274877975552",
                },
            }
        ),
        repo,
    )

    with TestClient(app, base_url="http://localhost:2026") as client:
        response = client.post("/api/channels/discord/connect")

    assert response.status_code == 200
    parsed = urlparse(response.json()["url"])
    query = parse_qs(parsed.query)
    assert query["redirect_uri"] == ["http://localhost:2026/api/channels/discord/callback"]

    anyio.run(repo.close)


def test_connect_discord_without_encryption_key_returns_400(tmp_path):
    import anyio

    repo = anyio.run(_make_repo, tmp_path, None)
    app = _make_app(
        ChannelConnectionsConfig.model_validate(
            {
                "enabled": True,
                "mode": "local",
                "discord": {
                    "enabled": True,
                    "client_id": "discord-client",
                    "client_secret": "discord-secret",
                    "bot_token": "discord-bot",
                },
            }
        ),
        repo,
    )

    with TestClient(app) as client:
        response = client.post("/api/channels/discord/connect")

    assert response.status_code == 400
    assert "encryption_key" in response.json()["detail"]

    anyio.run(repo.close)


def test_connect_discord_includes_bot_install_scope_and_permissions(tmp_path):
    import anyio

    repo = anyio.run(_make_repo, tmp_path)
    app = _make_app(
        ChannelConnectionsConfig.model_validate(
            {
                "enabled": True,
                "public_base_url": "https://deerflow.example.com",
                "encryption_key": "router-secret",
                "discord": {
                    "enabled": True,
                    "client_id": "discord-client",
                    "client_secret": "discord-secret",
                    "bot_token": "discord-bot",
                    "permissions": "274877975552",
                },
            }
        ),
        repo,
    )

    with TestClient(app) as client:
        response = client.post("/api/channels/discord/connect")

    assert response.status_code == 200
    url = response.json()["url"]
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    scopes = set(query["scope"][0].split())
    assert {"identify", "guilds", "bot", "applications.commands"}.issubset(scopes)
    assert query["permissions"] == ["274877975552"]

    anyio.run(repo.close)


def test_slack_callback_exchanges_code_and_stores_connection(tmp_path, monkeypatch):
    import anyio

    from app.channels.providers import slack_connect

    repo = anyio.run(_make_repo, tmp_path)
    state_token = "slack-state-token"

    async def seed_state():
        await repo.create_oauth_state(
            owner_user_id=str(_user().id),
            provider="slack",
            state=state_token,
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
            requested_scopes=["chat:write"],
        )

    async def fake_exchange_slack_oauth_code(**kwargs):
        assert kwargs["code"] == "slack-code"
        assert kwargs["redirect_uri"] == "https://deerflow.example.com/api/channels/slack/callback"
        return SlackInstall(
            team_id="T123",
            team_name="Deer Team",
            authed_user_id="U123",
            bot_user_id="B123",
            bot_access_token="xoxb-secret",
            scopes=["chat:write"],
            raw={"ok": True},
        )

    anyio.run(seed_state)
    monkeypatch.setattr(slack_connect, "exchange_slack_oauth_code", fake_exchange_slack_oauth_code)
    app = _make_app(
        ChannelConnectionsConfig.model_validate(
            {
                "enabled": True,
                "public_base_url": "https://deerflow.example.com",
                "encryption_key": "router-secret",
                "slack": {
                    "enabled": True,
                    "client_id": "slack-client",
                    "client_secret": "slack-secret",
                    "signing_secret": "slack-signing-secret",
                },
            }
        ),
        repo,
    )

    with TestClient(app) as client:
        response = client.get(
            f"/api/channels/slack/callback?code=slack-code&state={state_token}",
            follow_redirects=False,
        )

    assert response.status_code in {302, 307}
    assert response.headers["location"] == "/workspace?channel_connected=slack"

    async def get_connection_and_credentials():
        connections = await repo.list_connections(str(_user().id))
        credentials = await repo.get_credentials(connections[0]["id"])
        return connections[0], credentials

    connection, credentials = anyio.run(get_connection_and_credentials)
    assert connection["provider"] == "slack"
    assert connection["external_account_id"] == "U123"
    assert connection["workspace_id"] == "T123"
    assert connection["bot_user_id"] == "B123"
    assert connection["scopes"] == ["chat:write"]
    assert credentials["access_token"] == "xoxb-secret"

    anyio.run(repo.close)


def test_discord_callback_exchanges_code_and_stores_identity(tmp_path, monkeypatch):
    import anyio

    from app.channels.providers import discord_connect

    repo = anyio.run(_make_repo, tmp_path)
    state_token = "discord-state-token"

    async def seed_state():
        await repo.create_oauth_state(
            owner_user_id=str(_user().id),
            provider="discord",
            state=state_token,
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
            requested_scopes=["identify", "guilds"],
        )

    async def fake_complete_discord_oauth(**kwargs):
        assert kwargs["code"] == "discord-code"
        assert kwargs["redirect_uri"] == "https://deerflow.example.com/api/channels/discord/callback"
        return DiscordIdentity(
            user_id="987",
            display_name="Alice",
            username="alice",
            guilds=[{"id": "G1", "name": "Guild One"}],
            access_token="discord-access-token",
            refresh_token="discord-refresh-token",
            token_type="Bearer",
            scopes=["identify", "guilds"],
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            raw_token={"scope": "identify guilds"},
        )

    anyio.run(seed_state)
    monkeypatch.setattr(discord_connect, "complete_discord_oauth", fake_complete_discord_oauth)
    app = _make_app(
        ChannelConnectionsConfig.model_validate(
            {
                "enabled": True,
                "public_base_url": "https://deerflow.example.com",
                "encryption_key": "router-secret",
                "discord": {
                    "enabled": True,
                    "client_id": "discord-client",
                    "client_secret": "discord-secret",
                    "bot_token": "discord-bot",
                },
            }
        ),
        repo,
    )

    with TestClient(app) as client:
        response = client.get(
            f"/api/channels/discord/callback?code=discord-code&state={state_token}",
            follow_redirects=False,
        )

    assert response.status_code in {302, 307}
    assert response.headers["location"] == "/workspace?channel_connected=discord"

    async def get_connection_and_credentials():
        connections = await repo.list_connections(str(_user().id))
        credentials = await repo.get_credentials(connections[0]["id"])
        return connections[0], credentials

    connection, credentials = anyio.run(get_connection_and_credentials)
    assert connection["provider"] == "discord"
    assert connection["external_account_id"] == "987"
    assert connection["external_account_name"] == "Alice"
    assert connection["metadata"]["guilds"] == [{"id": "G1", "name": "Guild One"}]
    assert credentials["access_token"] == "discord-access-token"
    assert credentials["refresh_token"] == "discord-refresh-token"

    anyio.run(repo.close)


def test_disconnect_connection_revokes_current_user_connection(tmp_path):
    import anyio

    repo = anyio.run(_make_repo, tmp_path)

    async def seed_connection():
        connection = await repo.upsert_connection(
            owner_user_id=str(_user().id),
            provider="telegram",
            external_account_id="42",
            status="connected",
        )
        await repo.store_credentials(connection["id"], access_token="secret-token")
        return connection["id"]

    connection_id = anyio.run(seed_connection)
    app = _make_app(
        ChannelConnectionsConfig.model_validate(
            {
                "enabled": True,
                "public_base_url": "https://deerflow.example.com",
                "encryption_key": "router-secret",
            }
        ),
        repo,
    )

    with TestClient(app) as client:
        response = client.delete(f"/api/channels/connections/{connection_id}")

    assert response.status_code == 204

    async def get_connection_status():
        return (await repo.list_connections(str(_user().id)))[0]["status"]

    assert anyio.run(get_connection_status) == "revoked"
    assert anyio.run(repo.get_credentials, connection_id) is None

    anyio.run(repo.close)


def test_disconnect_connection_is_current_user_scoped(tmp_path):
    import anyio

    repo = anyio.run(_make_repo, tmp_path)

    async def seed_connection():
        connection = await repo.upsert_connection(
            owner_user_id="other-user",
            provider="telegram",
            external_account_id="42",
            status="connected",
        )
        return connection["id"]

    connection_id = anyio.run(seed_connection)
    app = _make_app(
        ChannelConnectionsConfig.model_validate(
            {
                "enabled": True,
                "public_base_url": "https://deerflow.example.com",
                "encryption_key": "router-secret",
            }
        ),
        repo,
    )

    with TestClient(app) as client:
        response = client.delete(f"/api/channels/connections/{connection_id}")

    assert response.status_code == 404

    async def get_connection_status():
        return (await repo.list_connections("other-user"))[0]["status"]

    assert anyio.run(get_connection_status) == "connected"

    anyio.run(repo.close)
