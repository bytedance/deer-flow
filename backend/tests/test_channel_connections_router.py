"""Router tests for browser-connectable IM channels."""

from __future__ import annotations

from uuid import UUID

from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient

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
    from deerflow.persistence.channel_connections import ChannelConnectionRepository
    from deerflow.persistence.engine import get_session_factory, init_engine

    await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path / 'router.db'}", sqlite_dir=str(tmp_path))
    return ChannelConnectionRepository(get_session_factory())


def _make_app(config: ChannelConnectionsConfig, repo, channels_config: dict | None = None):
    app = make_authed_test_app(user_factory=_user)
    app.state.channel_connections_config = config
    app.state.channel_connection_repo = repo
    app.state.channels_config = channels_config or {}
    app.include_router(channel_connections.router)
    return app


def _enabled_connections_config() -> ChannelConnectionsConfig:
    return ChannelConnectionsConfig.model_validate(
        {
            "enabled": True,
            "telegram": {"enabled": True, "bot_username": "deerflow_bot"},
            "slack": {"enabled": True},
            "discord": {"enabled": True},
        }
    )


def _channels_config() -> dict:
    return {
        "telegram": {"enabled": True, "bot_token": "telegram-token"},
        "slack": {"enabled": True, "bot_token": "xoxb-operator", "app_token": "xapp-operator"},
        "discord": {"enabled": True, "bot_token": "discord-bot"},
    }


def test_get_providers_uses_existing_channels_config(tmp_path):
    import anyio

    repo = anyio.run(_make_repo, tmp_path)
    app = _make_app(_enabled_connections_config(), repo, _channels_config())

    with TestClient(app) as client:
        response = client.get("/api/channels/providers")

    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    by_provider = {item["provider"]: item for item in body["providers"]}
    assert by_provider["telegram"]["configured"] is True
    assert by_provider["telegram"]["auth_mode"] == "deep_link"
    assert by_provider["slack"]["configured"] is True
    assert by_provider["slack"]["auth_mode"] == "binding_code"
    assert by_provider["discord"]["configured"] is True
    assert by_provider["discord"]["auth_mode"] == "binding_code"

    anyio.run(repo.close)


def test_get_providers_reports_unconfigured_when_runtime_channel_is_missing(tmp_path):
    import anyio

    repo = anyio.run(_make_repo, tmp_path)
    app = _make_app(_enabled_connections_config(), repo, {"telegram": {"enabled": True, "bot_token": "telegram-token"}})

    with TestClient(app) as client:
        response = client.get("/api/channels/providers")

    assert response.status_code == 200
    by_provider = {item["provider"]: item for item in response.json()["providers"]}
    assert by_provider["telegram"]["configured"] is True
    assert by_provider["slack"]["configured"] is False
    assert by_provider["slack"]["connectable"] is False
    assert "channels.slack" in by_provider["slack"]["unavailable_reason"]
    assert by_provider["discord"]["configured"] is False
    assert "channels.discord" in by_provider["discord"]["unavailable_reason"]

    anyio.run(repo.close)


def test_get_providers_uses_newest_connection_status_per_provider(tmp_path):
    import anyio

    repo = anyio.run(_make_repo, tmp_path)

    async def seed_connections():
        await repo.upsert_connection(
            owner_user_id=str(_user().id),
            provider="slack",
            external_account_id="U-old",
            workspace_id="T-old",
            status="revoked",
        )
        await anyio.sleep(0.01)
        await repo.upsert_connection(
            owner_user_id=str(_user().id),
            provider="slack",
            external_account_id="U-new",
            workspace_id="T-new",
            status="connected",
        )

    anyio.run(seed_connections)
    app = _make_app(_enabled_connections_config(), repo, _channels_config())

    with TestClient(app) as client:
        response = client.get("/api/channels/providers")

    assert response.status_code == 200
    by_provider = {item["provider"]: item for item in response.json()["providers"]}
    assert by_provider["slack"]["connection_status"] == "connected"

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
    app = _make_app(_enabled_connections_config(), repo, _channels_config())

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
    app = _make_app(_enabled_connections_config(), repo, _channels_config())

    with TestClient(app) as client:
        response = client.post("/api/channels/telegram/connect")

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "telegram"
    assert body["mode"] == "deep_link"
    assert body["url"].startswith("https://t.me/deerflow_bot?start=")
    assert body["code"]
    assert "/start" in body["instruction"]

    async def count_states():
        return await repo.count_oauth_states(owner_user_id=str(_user().id), provider="telegram")

    assert anyio.run(count_states) == 1

    anyio.run(repo.close)


def test_connect_slack_returns_binding_command_and_persists_state(tmp_path):
    import anyio

    repo = anyio.run(_make_repo, tmp_path)
    app = _make_app(_enabled_connections_config(), repo, _channels_config())

    with TestClient(app) as client:
        response = client.post("/api/channels/slack/connect")

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "slack"
    assert body["mode"] == "binding_code"
    assert body["url"] is None
    assert len(body["code"]) >= 22
    assert body["instruction"] == f"Send /connect {body['code']} to the DeerFlow Slack bot."

    async def count_states():
        return await repo.count_oauth_states(owner_user_id=str(_user().id), provider="slack")

    assert anyio.run(count_states) == 1

    anyio.run(repo.close)


def test_connect_discord_returns_binding_command_and_persists_state(tmp_path):
    import anyio

    repo = anyio.run(_make_repo, tmp_path)
    app = _make_app(_enabled_connections_config(), repo, _channels_config())

    with TestClient(app) as client:
        response = client.post("/api/channels/discord/connect")

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "discord"
    assert body["mode"] == "binding_code"
    assert body["url"] is None
    assert body["code"]
    assert body["instruction"] == f"Send /connect {body['code']} to the DeerFlow Discord bot."

    async def count_states():
        return await repo.count_oauth_states(owner_user_id=str(_user().id), provider="discord")

    assert anyio.run(count_states) == 1

    anyio.run(repo.close)


def test_connect_unconfigured_runtime_channel_returns_400(tmp_path):
    import anyio

    repo = anyio.run(_make_repo, tmp_path)
    app = _make_app(_enabled_connections_config(), repo, {})

    with TestClient(app) as client:
        response = client.post("/api/channels/slack/connect")

    assert response.status_code == 400
    assert "channels.slack" in response.json()["detail"]

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
        return connection["id"]

    connection_id = anyio.run(seed_connection)
    app = _make_app(_enabled_connections_config(), repo, _channels_config())

    with TestClient(app) as client:
        response = client.delete(f"/api/channels/connections/{connection_id}")

    assert response.status_code == 204

    async def get_connection_status():
        return (await repo.list_connections(str(_user().id)))[0]["status"]

    assert anyio.run(get_connection_status) == "revoked"

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
    app = _make_app(_enabled_connections_config(), repo, _channels_config())

    with TestClient(app) as client:
        response = client.delete(f"/api/channels/connections/{connection_id}")

    assert response.status_code == 404

    async def get_connection_status():
        return (await repo.list_connections("other-user"))[0]["status"]

    assert anyio.run(get_connection_status) == "connected"

    anyio.run(repo.close)
