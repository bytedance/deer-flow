"""Regression anchors: channel runtime-config handlers must not block the event loop.

``configure_channel_provider_runtime`` and ``disconnect_channel_provider_runtime``
persist UI-entered channel credentials through ``ChannelRuntimeConfigStore``,
whose construction reads its JSON file and whose setters rewrite it
(``json.dump`` + ``Path.replace`` + ``chmod``). The handlers offload both via
``asyncio.to_thread``; if that regresses back onto the event loop, the strict
Blockbuster gate raises ``BlockingError`` and these tests fail.

The handlers are invoked directly with a minimal Starlette ``Request`` so the
surface under test is exactly the router's own IO, mirroring
``test_agents_router``. Test-side seeding/inspection is offloaded with
``asyncio.to_thread``.
"""

from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import FastAPI, Request

from app.channels.runtime_config_store import ChannelRuntimeConfigStore
from app.gateway.routers.channel_connections import (
    ChannelRuntimeConfigRequest,
    configure_channel_provider_runtime,
    disconnect_channel_provider_runtime,
)
from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config
from deerflow.config.channel_connections_config import ChannelConnectionsConfig

# Pre-import: the handlers import this module lazily; the import's file IO
# must happen at collection time, not on the event loop under the gate.
importlib.import_module("app.channels.service")

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _stub_app_config():
    set_app_config(AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}}))
    yield
    reset_app_config()


def _make_request(tmp_path) -> Request:
    app = FastAPI()
    app.state.channel_connections_config = ChannelConnectionsConfig.model_validate(
        {
            "enabled": True,
            "slack": {"enabled": True},
        }
    )
    app.state.channels_config = {}
    app.state.channel_connection_repo = _FakeRepo()
    store = ChannelRuntimeConfigStore(tmp_path / "channels" / "runtime-config.json")
    app.state.channel_runtime_config_store = store
    user = SimpleNamespace(id=UUID("11111111-2222-3333-4444-555555555555"), system_role="admin")
    return Request({"type": "http", "app": app, "headers": [], "state": {"user": user}})


class _FakeRepo:
    async def list_connections(self, owner_user_id):
        return []


async def test_configure_runtime_channel_does_not_block_event_loop(tmp_path) -> None:
    request = await asyncio.to_thread(_make_request, tmp_path)

    response = await configure_channel_provider_runtime(
        "slack",
        ChannelRuntimeConfigRequest(values={"bot_token": "xoxb-ui", "app_token": "xapp-ui"}),
        request,
    )

    assert response.provider == "slack"
    store = request.app.state.channel_runtime_config_store
    assert await asyncio.to_thread(store.get_provider_config, "slack") == {
        "enabled": True,
        "bot_token": "xoxb-ui",
        "app_token": "xapp-ui",
    }


async def test_disconnect_runtime_channel_does_not_block_event_loop(tmp_path) -> None:
    request = await asyncio.to_thread(_make_request, tmp_path)
    store = request.app.state.channel_runtime_config_store
    await asyncio.to_thread(
        store.set_provider_config,
        "slack",
        {"enabled": True, "bot_token": "xoxb-ui", "app_token": "xapp-ui"},
    )
    request.app.state.channels_config = {
        "slack": {"enabled": True, "bot_token": "xoxb-ui", "app_token": "xapp-ui"},
    }

    response = await disconnect_channel_provider_runtime("slack", request)

    assert response.provider == "slack"
    assert await asyncio.to_thread(store.get_provider_config, "slack") == {
        "enabled": False,
        "_runtime_disabled": True,
    }
