"""Router tests for browser-connectable IM channels."""

from __future__ import annotations

from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient

from app.channels.runtime_config_store import ChannelRuntimeConfigStore
from app.gateway.auth.models import User
from app.gateway.routers import channel_connections
from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config
from deerflow.config.channel_connections_config import ChannelConnectionsConfig


@pytest.fixture(autouse=True)
def _stub_app_config(monkeypatch):
    """Keep router tests independent from a developer-local config.yaml."""
    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "0")
    set_app_config(AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}}))
    yield
    reset_app_config()


def _user() -> User:
    return User(
        id=UUID("11111111-2222-3333-4444-555555555555"),
        email="alice@example.com",
        password_hash="x",
        system_role="admin",
    )


def _non_admin_user() -> User:
    return User(
        id=UUID("99999999-8888-7777-6666-555555555555"),
        email="bob@example.com",
        password_hash="x",
        system_role="user",
    )


async def _make_repo(tmp_path):
    from deerflow.persistence.channel_connections import ChannelConnectionRepository
    from deerflow.persistence.engine import get_session_factory, init_engine

    await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path / 'router.db'}", sqlite_dir=str(tmp_path))
    return ChannelConnectionRepository(get_session_factory())


def _make_app(
    config: ChannelConnectionsConfig,
    repo,
    channels_config: dict | None = None,
    *,
    runtime_config_store: ChannelRuntimeConfigStore | None = None,
    set_channels_config_state: bool = True,
):
    app = make_authed_test_app(user_factory=_user)
    app.state.channel_connections_config = config
    app.state.channel_connection_repo = repo
    if set_channels_config_state:
        app.state.channels_config = channels_config or {}
    if runtime_config_store is None:
        runtime_config_dir = TemporaryDirectory()
        app.state.channel_runtime_config_tmpdir = runtime_config_dir
        runtime_config_store = ChannelRuntimeConfigStore(f"{runtime_config_dir.name}/runtime-config.json")
    app.state.channel_runtime_config_store = runtime_config_store
    app.include_router(channel_connections.router)
    return app


def _enabled_connections_config() -> ChannelConnectionsConfig:
    return ChannelConnectionsConfig.model_validate(
        {
            "enabled": True,
            "telegram": {"enabled": True, "bot_username": "deerflow_bot"},
            "slack": {"enabled": True},
            "discord": {"enabled": True},
            "feishu": {"enabled": True},
            "dingtalk": {"enabled": True},
            "wechat": {"enabled": True},
            "wecom": {"enabled": True},
        }
    )


def _channels_config() -> dict:
    return {
        "telegram": {"enabled": True, "bot_token": "telegram-token"},
        "slack": {"enabled": True, "bot_token": "xoxb-operator", "app_token": "xapp-operator"},
        "discord": {"enabled": True, "bot_token": "discord-bot"},
        "feishu": {"enabled": True, "app_id": "feishu-app", "app_secret": "feishu-secret"},
        "dingtalk": {"enabled": True, "client_id": "dingtalk-client", "client_secret": "dingtalk-secret"},
        "wechat": {"enabled": True, "bot_token": "wechat-token"},
        "wecom": {"enabled": True, "bot_id": "wecom-bot", "bot_secret": "wecom-secret"},
    }


def test_get_providers_only_returns_enabled_channels_and_setup_fields(tmp_path):
    import anyio

    repo = anyio.run(_make_repo, tmp_path)
    config = ChannelConnectionsConfig.model_validate(
        {
            "enabled": True,
            "slack": {"enabled": True},
            "discord": {"enabled": False},
        }
    )
    app = _make_app(config, repo, {})

    with TestClient(app) as client:
        response = client.get("/api/channels/providers")

    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    assert [provider["provider"] for provider in body["providers"]] == ["slack"]
    assert body["providers"][0]["configured"] is False
    assert body["providers"][0]["connectable"] is False
    assert body["providers"][0]["credential_fields"] == [
        {
            "name": "bot_token",
            "label": "Bot token",
            "type": "password",
            "required": True,
        },
        {
            "name": "app_token",
            "label": "App token",
            "type": "password",
            "required": True,
        },
    ]

    anyio.run(repo.close)


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
    assert set(by_provider) == {"telegram", "slack", "discord", "feishu", "dingtalk", "wechat", "wecom"}
    assert by_provider["telegram"]["configured"] is True
    assert by_provider["telegram"]["auth_mode"] == "deep_link"
    assert by_provider["telegram"]["credential_values"] == {
        "bot_token": "********",
        "bot_username": "deerflow_bot",
    }
    assert by_provider["slack"]["configured"] is True
    assert by_provider["slack"]["auth_mode"] == "binding_code"
    assert by_provider["slack"]["connection_status"] == "not_connected"
    assert by_provider["slack"]["credential_values"] == {
        "bot_token": "********",
        "app_token": "********",
    }
    assert by_provider["discord"]["configured"] is True
    assert by_provider["discord"]["auth_mode"] == "binding_code"
    assert by_provider["discord"]["credential_values"] == {"bot_token": "********"}
    assert by_provider["feishu"]["configured"] is True
    assert by_provider["feishu"]["auth_mode"] == "binding_code"
    assert by_provider["feishu"]["connection_status"] == "not_connected"
    assert by_provider["feishu"]["credential_values"] == {
        "app_id": "feishu-app",
        "app_secret": "********",
    }
    assert by_provider["dingtalk"]["configured"] is True
    assert by_provider["dingtalk"]["auth_mode"] == "binding_code"
    assert by_provider["dingtalk"]["credential_values"] == {
        "client_id": "dingtalk-client",
        "client_secret": "********",
    }
    assert by_provider["wechat"]["configured"] is True
    assert by_provider["wechat"]["auth_mode"] == "binding_code"
    assert by_provider["wechat"]["credential_values"] == {"bot_token": "********"}
    assert by_provider["wecom"]["configured"] is True
    assert by_provider["wecom"]["auth_mode"] == "binding_code"
    assert by_provider["wecom"]["credential_values"] == {
        "bot_id": "wecom-bot",
        "bot_secret": "********",
    }

    anyio.run(repo.close)


def test_get_providers_degrades_when_persistence_is_unavailable(monkeypatch):
    monkeypatch.setattr(channel_connections, "get_session_factory", lambda: None)
    app = _make_app(_enabled_connections_config(), None, _channels_config())

    with TestClient(app) as client:
        response = client.get("/api/channels/providers")

    assert response.status_code == 200
    by_provider = {item["provider"]: item for item in response.json()["providers"]}
    assert by_provider["slack"]["configured"] is True
    assert by_provider["slack"]["connectable"] is True
    assert by_provider["slack"]["connection_status"] == "not_connected"


def test_get_providers_reports_connected_without_binding_in_auth_disabled_mode(tmp_path, monkeypatch):
    import anyio

    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "1")
    monkeypatch.delenv("DEER_FLOW_ENV", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    repo = anyio.run(_make_repo, tmp_path)
    app = _make_app(_enabled_connections_config(), repo, _channels_config())

    with TestClient(app) as client:
        response = client.get("/api/channels/providers")

    assert response.status_code == 200
    by_provider = {item["provider"]: item for item in response.json()["providers"]}
    # Auth-disabled local mode routes channel messages to the default user, so
    # a configured running channel is effectively connected without a binding.
    assert by_provider["slack"]["connection_status"] == "connected"
    assert by_provider["feishu"]["connection_status"] == "connected"

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
    assert "Slack credentials" in by_provider["slack"]["unavailable_reason"]
    assert by_provider["discord"]["configured"] is False
    assert "Discord credentials" in by_provider["discord"]["unavailable_reason"]
    assert by_provider["feishu"]["configured"] is False
    assert "Feishu credentials" in by_provider["feishu"]["unavailable_reason"]
    assert by_provider["dingtalk"]["configured"] is False
    assert "DingTalk credentials" in by_provider["dingtalk"]["unavailable_reason"]
    assert by_provider["wechat"]["configured"] is False
    assert "WeChat credentials" in by_provider["wechat"]["unavailable_reason"]
    assert by_provider["wecom"]["configured"] is False
    assert "WeCom credentials" in by_provider["wecom"]["unavailable_reason"]

    anyio.run(repo.close)


def test_get_providers_reports_configured_channel_not_running(tmp_path, monkeypatch):
    import anyio

    repo = anyio.run(_make_repo, tmp_path)
    app = _make_app(_enabled_connections_config(), repo, _channels_config())
    service = SimpleNamespace(
        get_status=lambda: {
            "service_running": True,
            "channels": {
                "feishu": {
                    "enabled": True,
                    "running": False,
                }
            },
        }
    )
    monkeypatch.setattr("app.channels.service.get_channel_service", lambda: service)

    with TestClient(app) as client:
        response = client.get("/api/channels/providers")

    assert response.status_code == 200
    by_provider = {item["provider"]: item for item in response.json()["providers"]}
    assert by_provider["feishu"]["configured"] is True
    assert by_provider["feishu"]["connectable"] is False
    assert by_provider["feishu"]["connection_status"] == "not_connected"
    assert "configured but is not running" in by_provider["feishu"]["unavailable_reason"]

    anyio.run(repo.close)


def test_get_providers_provider_unavailable_overrides_stale_connected_row(tmp_path):
    import anyio

    repo = anyio.run(_make_repo, tmp_path)

    async def seed_connection():
        await repo.upsert_connection(
            owner_user_id=str(_user().id),
            provider="slack",
            external_account_id="U123",
            status="connected",
        )

    anyio.run(seed_connection)
    config = ChannelConnectionsConfig.model_validate(
        {
            "enabled": True,
            "slack": {"enabled": True},
        }
    )
    app = _make_app(config, repo, {})

    with TestClient(app) as client:
        response = client.get("/api/channels/providers")

    assert response.status_code == 200
    by_provider = {item["provider"]: item for item in response.json()["providers"]}
    assert by_provider["slack"]["configured"] is False
    assert by_provider["slack"]["connectable"] is False
    assert by_provider["slack"]["connection_status"] == "not_connected"
    assert "Slack credentials" in by_provider["slack"]["unavailable_reason"]

    anyio.run(repo.close)


def test_get_providers_restarts_configured_channel_when_service_can_reconcile(tmp_path, monkeypatch):
    import anyio

    repo = anyio.run(_make_repo, tmp_path)
    config = ChannelConnectionsConfig.model_validate(
        {
            "enabled": True,
            "feishu": {"enabled": True},
        }
    )
    channels_config = {
        "feishu": {
            "enabled": True,
            "app_id": "feishu-app",
            "app_secret": "feishu-secret",
        }
    }
    app = _make_app(config, repo, channels_config)
    status = {
        "service_running": True,
        "channels": {
            "feishu": {
                "enabled": True,
                "running": False,
            }
        },
    }
    reconciled: list[tuple[str, dict]] = []

    async def ensure_channel_ready(provider, runtime_config):
        reconciled.append((provider, dict(runtime_config)))
        status["channels"][provider]["running"] = True
        return True

    service = SimpleNamespace(
        get_status=lambda: status,
        ensure_channel_ready=ensure_channel_ready,
    )
    monkeypatch.setattr("app.channels.service.get_channel_service", lambda: service)

    with TestClient(app) as client:
        response = client.get("/api/channels/providers")

    assert response.status_code == 200
    by_provider = {item["provider"]: item for item in response.json()["providers"]}
    assert by_provider["feishu"]["configured"] is True
    assert by_provider["feishu"]["connectable"] is True
    assert by_provider["feishu"]["connection_status"] == "not_connected"
    assert by_provider["feishu"]["unavailable_reason"] is None
    assert reconciled == [("feishu", channels_config["feishu"])]

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


def test_connect_binding_code_caps_pending_states_per_provider(tmp_path):
    import anyio

    repo = anyio.run(_make_repo, tmp_path)
    app = _make_app(_enabled_connections_config(), repo, _channels_config())

    with TestClient(app) as client:
        responses = [client.post("/api/channels/slack/connect") for _ in range(6)]

    assert [response.status_code for response in responses[:5]] == [200, 200, 200, 200, 200]
    assert responses[5].status_code == 429
    assert "Too many pending channel connection codes" in responses[5].json()["detail"]

    async def count_states():
        return await repo.count_oauth_states(owner_user_id=str(_user().id), provider="slack")

    assert anyio.run(count_states) == 5

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


def test_connect_existing_binding_code_channels_return_command_and_persist_state(tmp_path):
    import anyio

    repo = anyio.run(_make_repo, tmp_path)
    app = _make_app(_enabled_connections_config(), repo, _channels_config())

    providers = ["feishu", "dingtalk", "wechat", "wecom"]
    with TestClient(app) as client:
        responses = {provider: client.post(f"/api/channels/{provider}/connect") for provider in providers}

    for provider, response in responses.items():
        expected_display_name = {
            "feishu": "Feishu",
            "dingtalk": "DingTalk",
            "wechat": "WeChat",
            "wecom": "WeCom",
        }[provider]
        assert response.status_code == 200
        body = response.json()
        assert body["provider"] == provider
        assert body["mode"] == "binding_code"
        assert body["url"] is None
        assert len(body["code"]) >= 22
        assert body["instruction"] == f"Send /connect {body['code']} to the DeerFlow {expected_display_name} bot."

        async def count_states(provider=provider):
            return await repo.count_oauth_states(owner_user_id=str(_user().id), provider=provider)

        assert anyio.run(count_states) == 1

    anyio.run(repo.close)


def test_connect_unconfigured_runtime_channel_returns_400(tmp_path):
    import anyio

    repo = anyio.run(_make_repo, tmp_path)
    app = _make_app(_enabled_connections_config(), repo, {})

    with TestClient(app) as client:
        response = client.post("/api/channels/slack/connect")

    assert response.status_code == 400
    assert "Slack credentials" in response.json()["detail"]

    anyio.run(repo.close)


@pytest.mark.parametrize("provider", ["enabled", "require_bound_identity", "provider_status", "unknown_provider"])
def test_connect_rejects_non_provider_config_attribute_with_404(tmp_path, provider):
    import anyio

    # A request-supplied provider name that collides with a real (non-provider)
    # ChannelConnectionsConfig attribute -- e.g. the "enabled" /
    # "require_bound_identity" bool fields, or the "provider_status" method --
    # must resolve to the intended 404. Before the allowlist check, an
    # unrestricted getattr returned that attribute instead of falling through to
    # the 404, and the connect handler then dereferenced it as a provider config
    # (AttributeError -> HTTP 500) for any authenticated user.
    repo = anyio.run(_make_repo, tmp_path)
    app = _make_app(_enabled_connections_config(), repo, _channels_config())

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(f"/api/channels/{provider}/connect")

    assert response.status_code == 404
    assert response.json()["detail"] == "Unknown channel provider"

    anyio.run(repo.close)


def test_configure_provider_runtime_credentials_enables_connect_without_file_edits(tmp_path):
    import anyio

    repo = anyio.run(_make_repo, tmp_path)
    config = ChannelConnectionsConfig.model_validate(
        {
            "enabled": True,
            "slack": {"enabled": True},
        }
    )
    app = _make_app(config, repo, {})

    with TestClient(app) as client:
        configure_response = client.post(
            "/api/channels/slack/runtime-config",
            json={"values": {"bot_token": "xoxb-ui", "app_token": "xapp-ui"}},
        )
        connect_response = client.post("/api/channels/slack/connect")

    assert configure_response.status_code == 200
    configured = configure_response.json()
    assert configured["provider"] == "slack"
    assert configured["configured"] is True
    assert configured["connectable"] is True
    assert configured["connection_status"] == "not_connected"
    assert app.state.channels_config["slack"] == {
        "enabled": True,
        "bot_token": "xoxb-ui",
        "app_token": "xapp-ui",
    }
    assert connect_response.status_code == 200
    assert connect_response.json()["provider"] == "slack"

    anyio.run(repo.close)


def test_runtime_config_endpoints_require_admin(tmp_path):
    import anyio

    repo = anyio.run(_make_repo, tmp_path)
    config = ChannelConnectionsConfig.model_validate(
        {
            "enabled": True,
            "slack": {"enabled": True},
        }
    )
    app = make_authed_test_app(user_factory=_non_admin_user)
    app.state.channel_connections_config = config
    app.state.channel_connection_repo = repo
    app.state.channels_config = {}
    runtime_config_dir = TemporaryDirectory()
    app.state.channel_runtime_config_tmpdir = runtime_config_dir
    app.state.channel_runtime_config_store = ChannelRuntimeConfigStore(f"{runtime_config_dir.name}/runtime-config.json")
    app.include_router(channel_connections.router)

    with TestClient(app) as client:
        configure_response = client.post(
            "/api/channels/slack/runtime-config",
            json={"values": {"bot_token": "xoxb-ui", "app_token": "xapp-ui"}},
        )
        disconnect_response = client.delete("/api/channels/slack/runtime-config")
        providers_response = client.get("/api/channels/providers")

    assert configure_response.status_code == 403
    assert "Admin privileges" in configure_response.json()["detail"]
    assert disconnect_response.status_code == 403
    # Read-only provider listing stays available to regular users.
    assert providers_response.status_code == 200

    anyio.run(repo.close)


def test_configure_provider_runtime_rolls_back_visible_state_when_start_fails(tmp_path, monkeypatch):
    import anyio

    repo = anyio.run(_make_repo, tmp_path)
    config = ChannelConnectionsConfig.model_validate(
        {
            "enabled": True,
            "slack": {"enabled": True},
        }
    )
    existing_runtime_config = {
        "enabled": True,
        "bot_token": "xoxb-old",
        "app_token": "xapp-old",
    }
    runtime_config_store = ChannelRuntimeConfigStore(tmp_path / "channels" / "runtime-config.json")
    runtime_config_store.set_provider_config("slack", existing_runtime_config)
    service = SimpleNamespace(configure_channel=AsyncMock(return_value=False))
    monkeypatch.setattr("app.channels.service.get_channel_service", lambda: service)
    app = _make_app(
        config,
        repo,
        {"slack": dict(existing_runtime_config)},
        runtime_config_store=runtime_config_store,
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/channels/slack/runtime-config",
            json={"values": {"bot_token": "xoxb-new", "app_token": "xapp-new"}},
        )

    assert response.status_code == 400
    assert "Failed to start Slack channel" in response.json()["detail"]
    service.configure_channel.assert_awaited_once_with(
        "slack",
        {
            "enabled": True,
            "bot_token": "xoxb-new",
            "app_token": "xapp-new",
        },
    )
    assert app.state.channels_config["slack"] == existing_runtime_config
    assert runtime_config_store.get_provider_config("slack") == existing_runtime_config

    anyio.run(repo.close)


def test_configure_telegram_runtime_uses_new_bot_username_for_deep_link_without_mutating_config(tmp_path):
    import anyio

    repo = anyio.run(_make_repo, tmp_path)
    config = ChannelConnectionsConfig.model_validate(
        {
            "enabled": True,
            "telegram": {"enabled": True, "bot_username": "old_bot"},
        }
    )
    app = _make_app(config, repo, {})

    with TestClient(app) as client:
        configure_response = client.post(
            "/api/channels/telegram/runtime-config",
            json={"values": {"bot_token": "tg-token", "bot_username": "new_bot"}},
        )
        connect_response = client.post("/api/channels/telegram/connect")

    assert configure_response.status_code == 200
    assert configure_response.json()["credential_values"]["bot_username"] == "new_bot"
    assert connect_response.status_code == 200
    assert connect_response.json()["url"].startswith("https://t.me/new_bot?start=")
    # The original config object cached by get_app_config() must stay untouched.
    assert config.telegram.bot_username == "old_bot"

    anyio.run(repo.close)


def test_configure_provider_runtime_credentials_survive_local_restart(tmp_path):
    import anyio

    repo = anyio.run(_make_repo, tmp_path)
    config = ChannelConnectionsConfig.model_validate(
        {
            "enabled": True,
            "slack": {"enabled": True},
        }
    )
    runtime_config_path = tmp_path / "channels" / "runtime-config.json"
    first_app = _make_app(
        config,
        repo,
        {},
        runtime_config_store=ChannelRuntimeConfigStore(runtime_config_path),
    )

    with TestClient(first_app) as client:
        configure_response = client.post(
            "/api/channels/slack/runtime-config",
            json={"values": {"bot_token": "xoxb-ui", "app_token": "xapp-ui"}},
        )

    assert configure_response.status_code == 200

    restarted_app = _make_app(
        config,
        repo,
        runtime_config_store=ChannelRuntimeConfigStore(runtime_config_path),
        set_channels_config_state=False,
    )

    with TestClient(restarted_app) as client:
        response = client.get("/api/channels/providers")

    assert response.status_code == 200
    by_provider = {item["provider"]: item for item in response.json()["providers"]}
    assert by_provider["slack"]["configured"] is True
    assert by_provider["slack"]["connectable"] is True
    assert by_provider["slack"]["connection_status"] == "not_connected"
    assert restarted_app.state.channels_config["slack"] == {
        "enabled": True,
        "bot_token": "xoxb-ui",
        "app_token": "xapp-ui",
    }

    anyio.run(repo.close)


def test_configure_provider_runtime_credentials_preserves_masked_secrets(tmp_path):
    import anyio

    repo = anyio.run(_make_repo, tmp_path)
    config = ChannelConnectionsConfig.model_validate(
        {
            "enabled": True,
            "feishu": {"enabled": True},
        }
    )
    runtime_config_store = ChannelRuntimeConfigStore(tmp_path / "channels" / "runtime-config.json")
    app = _make_app(
        config,
        repo,
        {
            "feishu": {
                "enabled": True,
                "app_id": "old-app-id",
                "app_secret": "old-secret",
            }
        },
        runtime_config_store=runtime_config_store,
    )

    with TestClient(app) as client:
        configure_response = client.post(
            "/api/channels/feishu/runtime-config",
            json={
                "values": {
                    "app_id": "new-app-id",
                    "app_secret": "********",
                }
            },
        )
        providers_response = client.get("/api/channels/providers")

    assert configure_response.status_code == 200
    assert app.state.channels_config["feishu"] == {
        "enabled": True,
        "app_id": "new-app-id",
        "app_secret": "old-secret",
    }
    assert runtime_config_store.get_provider_config("feishu") == {
        "enabled": True,
        "app_id": "new-app-id",
        "app_secret": "old-secret",
    }
    by_provider = {item["provider"]: item for item in providers_response.json()["providers"]}
    assert by_provider["feishu"]["credential_values"] == {
        "app_id": "new-app-id",
        "app_secret": "********",
    }

    anyio.run(repo.close)


def test_disconnect_provider_runtime_config_clears_connected_state(tmp_path):
    import anyio

    repo = anyio.run(_make_repo, tmp_path)
    config = ChannelConnectionsConfig.model_validate(
        {
            "enabled": True,
            "slack": {"enabled": True},
        }
    )
    runtime_config_store = ChannelRuntimeConfigStore(tmp_path / "channels" / "runtime-config.json")
    app = _make_app(config, repo, {}, runtime_config_store=runtime_config_store)

    with TestClient(app) as client:
        configure_response = client.post(
            "/api/channels/slack/runtime-config",
            json={"values": {"bot_token": "xoxb-ui", "app_token": "xapp-ui"}},
        )
        disconnect_response = client.delete("/api/channels/slack/runtime-config")
        providers_response = client.get("/api/channels/providers")

    assert configure_response.status_code == 200
    assert disconnect_response.status_code == 200
    disconnected = disconnect_response.json()
    assert disconnected["provider"] == "slack"
    assert disconnected["configured"] is False
    assert disconnected["connectable"] is False
    assert disconnected["connection_status"] == "not_connected"
    assert runtime_config_store.get_provider_config("slack") == {
        "enabled": False,
        "_runtime_disabled": True,
    }

    assert providers_response.status_code == 200
    by_provider = {item["provider"]: item for item in providers_response.json()["providers"]}
    assert by_provider["slack"]["connection_status"] == "not_connected"

    anyio.run(repo.close)


def test_disconnect_provider_runtime_config_suppresses_file_config_and_stops_channel(tmp_path, monkeypatch):
    import anyio

    repo = anyio.run(_make_repo, tmp_path)
    config = ChannelConnectionsConfig.model_validate(
        {
            "enabled": True,
            "feishu": {"enabled": True},
        }
    )
    set_app_config(
        AppConfig.model_validate(
            {
                "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
                "channels": {
                    "feishu": {
                        "enabled": True,
                        "app_id": "file-app-id",
                        "app_secret": "file-secret",
                    }
                },
            }
        )
    )
    runtime_config_store = ChannelRuntimeConfigStore(tmp_path / "channels" / "runtime-config.json")
    runtime_config_store.set_provider_config(
        "feishu",
        {
            "enabled": True,
            "app_id": "runtime-app-id",
            "app_secret": "runtime-secret",
        },
    )
    service = SimpleNamespace(
        configure_channel=AsyncMock(return_value=True),
        remove_channel=AsyncMock(return_value=True),
    )
    monkeypatch.setattr("app.channels.service.get_channel_service", lambda: service)
    app = _make_app(
        config,
        repo,
        {
            "feishu": {
                "enabled": True,
                "app_id": "runtime-app-id",
                "app_secret": "runtime-secret",
            }
        },
        runtime_config_store=runtime_config_store,
    )

    with TestClient(app) as client:
        disconnect_response = client.delete("/api/channels/feishu/runtime-config")
        providers_response = client.get("/api/channels/providers")

    assert disconnect_response.status_code == 200
    disconnected = disconnect_response.json()
    assert disconnected["provider"] == "feishu"
    assert disconnected["configured"] is False
    assert disconnected["connectable"] is False
    assert disconnected["connection_status"] == "not_connected"
    assert "feishu" not in app.state.channels_config
    service.remove_channel.assert_awaited_once_with("feishu")
    service.configure_channel.assert_not_awaited()

    assert providers_response.status_code == 200
    by_provider = {item["provider"]: item for item in providers_response.json()["providers"]}
    assert by_provider["feishu"]["configured"] is False
    assert by_provider["feishu"]["connection_status"] == "not_connected"

    anyio.run(repo.close)


def test_disconnect_provider_runtime_config_revokes_all_provider_connections(tmp_path):
    import anyio

    repo = anyio.run(_make_repo, tmp_path)

    async def seed_connection():
        await repo.upsert_connection(
            owner_user_id=str(_user().id),
            provider="slack",
            external_account_id="U123",
            status="connected",
        )
        await repo.upsert_connection(
            owner_user_id="other-user",
            provider="slack",
            external_account_id="U456",
            status="connected",
        )
        await repo.upsert_connection(
            owner_user_id="other-user",
            provider="telegram",
            external_account_id="42",
            status="connected",
        )

    anyio.run(seed_connection)
    config = ChannelConnectionsConfig.model_validate(
        {
            "enabled": True,
            "slack": {"enabled": True},
        }
    )
    runtime_config_store = ChannelRuntimeConfigStore(tmp_path / "channels" / "runtime-config.json")
    app = _make_app(config, repo, {}, runtime_config_store=runtime_config_store)

    with TestClient(app) as client:
        configure_response = client.post(
            "/api/channels/slack/runtime-config",
            json={"values": {"bot_token": "xoxb-ui", "app_token": "xapp-ui"}},
        )
        disconnect_response = client.delete("/api/channels/slack/runtime-config")

    assert configure_response.status_code == 200
    assert disconnect_response.status_code == 200

    async def get_connection_statuses():
        return {
            "admin_slack": (await repo.list_connections(str(_user().id)))[0]["status"],
            "other": {item["provider"]: item["status"] for item in await repo.list_connections("other-user")},
        }

    statuses = anyio.run(get_connection_statuses)
    assert statuses["admin_slack"] == "revoked"
    assert statuses["other"]["slack"] == "revoked"
    assert statuses["other"]["telegram"] == "connected"

    anyio.run(repo.close)


def test_get_providers_preserves_revoked_status_when_provider_unavailable(tmp_path):
    import anyio

    repo = anyio.run(_make_repo, tmp_path)

    async def seed_connection():
        await repo.upsert_connection(
            owner_user_id=str(_user().id),
            provider="slack",
            external_account_id="U123",
            status="revoked",
        )

    anyio.run(seed_connection)
    config = ChannelConnectionsConfig.model_validate(
        {
            "enabled": True,
            "slack": {"enabled": True},
        }
    )
    # No runtime channels_config -> the slack provider is unavailable.
    app = _make_app(config, repo, {})

    with TestClient(app) as client:
        response = client.get("/api/channels/providers")

    assert response.status_code == 200
    by_provider = {item["provider"]: item for item in response.json()["providers"]}
    assert by_provider["slack"]["connectable"] is False
    assert by_provider["slack"]["unavailable_reason"] is not None
    # A revoked binding must stay distinguishable from a never-connected one,
    # even when the runtime provider is currently unavailable.
    assert by_provider["slack"]["connection_status"] == "revoked"

    anyio.run(repo.close)


def test_configure_provider_runtime_does_not_clobber_concurrent_config_update(tmp_path, monkeypatch):
    import anyio

    repo = anyio.run(_make_repo, tmp_path)
    config = ChannelConnectionsConfig.model_validate(
        {
            "enabled": True,
            "slack": {"enabled": True},
            "telegram": {"enabled": True, "bot_username": "deerflow_bot"},
        }
    )
    runtime_config_store = ChannelRuntimeConfigStore(tmp_path / "channels" / "runtime-config.json")
    app = _make_app(config, repo, {}, runtime_config_store=runtime_config_store)

    async def configure_channel(provider, runtime_config):
        # Simulate a concurrent admin request for a *different* provider whose
        # write to app.state lands while this request awaits the worker restart.
        app.state.channels_config = {
            **app.state.channels_config,
            "telegram": {"enabled": True, "bot_token": "tg-token"},
        }
        return True

    service = SimpleNamespace(configure_channel=configure_channel)
    monkeypatch.setattr("app.channels.service.get_channel_service", lambda: service)

    with TestClient(app) as client:
        response = client.post(
            "/api/channels/slack/runtime-config",
            json={"values": {"bot_token": "xoxb-ui", "app_token": "xapp-ui"}},
        )

    assert response.status_code == 200
    # The concurrent telegram write must survive alongside the slack write.
    assert app.state.channels_config["slack"]["bot_token"] == "xoxb-ui"
    assert app.state.channels_config["telegram"]["bot_token"] == "tg-token"

    anyio.run(repo.close)


def test_disconnect_provider_runtime_keeps_state_consistent_when_revoke_fails(tmp_path):
    import anyio

    repo = anyio.run(_make_repo, tmp_path)
    config = ChannelConnectionsConfig.model_validate(
        {
            "enabled": True,
            "slack": {"enabled": True},
        }
    )
    runtime_config_store = ChannelRuntimeConfigStore(tmp_path / "channels" / "runtime-config.json")
    app = _make_app(config, repo, {}, runtime_config_store=runtime_config_store)

    with TestClient(app) as client:
        configure_response = client.post(
            "/api/channels/slack/runtime-config",
            json={"values": {"bot_token": "xoxb-ui", "app_token": "xapp-ui"}},
        )
    assert configure_response.status_code == 200

    repo.disconnect_provider_connections = AsyncMock(side_effect=RuntimeError("db down"))

    with TestClient(app, raise_server_exceptions=False) as client:
        disconnect_response = client.delete("/api/channels/slack/runtime-config")

    assert disconnect_response.status_code == 500
    # When the DB revoke fails, the store/cache must not be left diverged from
    # the DB: the provider stays configured so a later re-configure cannot
    # silently reactivate un-revoked connection rows.
    assert app.state.channels_config["slack"]["bot_token"] == "xoxb-ui"
    assert runtime_config_store.get_provider_config("slack") == {
        "enabled": True,
        "bot_token": "xoxb-ui",
        "app_token": "xapp-ui",
    }

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
