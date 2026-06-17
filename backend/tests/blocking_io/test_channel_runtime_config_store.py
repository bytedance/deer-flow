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
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
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
    # No channel_connection_repo is set: _get_repository's isinstance gate then
    # falls through to get_session_factory() (None in tests) and the handlers
    # take the repo-less 503 path. These tests only assert the store's file IO
    # is offloaded off the event loop, so the DB repo is intentionally absent.
    store = ChannelRuntimeConfigStore(tmp_path / "channels" / "runtime-config.json")
    app.state.channel_runtime_config_store = store
    user = SimpleNamespace(id=UUID("11111111-2222-3333-4444-555555555555"), system_role="admin")
    return Request({"type": "http", "app": app, "headers": [], "state": {"user": user}})


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


async def test_runtime_config_store_file_is_owner_only(tmp_path) -> None:
    path = tmp_path / "channels" / "runtime-config.json"
    store = await asyncio.to_thread(ChannelRuntimeConfigStore, path)

    await asyncio.to_thread(
        store.set_provider_config,
        "slack",
        {"enabled": True, "bot_token": "xoxb-ui", "app_token": "xapp-ui"},
    )

    mode = await asyncio.to_thread(lambda: path.stat().st_mode & 0o777)
    assert mode == 0o600


async def test_runtime_config_store_overwrites_loose_existing_file(tmp_path) -> None:
    """A pre-existing world-readable file is tightened to 0o600 after a save.

    ``NamedTemporaryFile`` would yield 0o600 on a fresh path regardless of the
    code under test, so seed the destination at 0o644 first: only the store's
    atomic 0o600-temp + replace path produces an owner-only file here.
    """
    path = tmp_path / "channels" / "runtime-config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}", encoding="utf-8")
    path.chmod(0o644)

    store = await asyncio.to_thread(ChannelRuntimeConfigStore, path)
    await asyncio.to_thread(
        store.set_provider_config,
        "slack",
        {"enabled": True, "bot_token": "xoxb-ui"},
    )

    mode = await asyncio.to_thread(lambda: path.stat().st_mode & 0o777)
    assert mode == 0o600


async def test_runtime_config_store_chmod_failure_is_logged_not_fatal(tmp_path, caplog) -> None:
    """A chmod failure on the temp file is logged at debug and never aborts the save.

    This is the line the previous owner-only assertion could not protect: with the
    pre-rename chmod patched to raise, the save must still persist the secret and
    the destination must still end up owner-only (via the temp file's mkstemp mode
    that ``Path.replace`` preserves). If the chmod call were dropped, the expected
    debug record would be absent and this test would fail.
    """
    path = tmp_path / "channels" / "runtime-config.json"
    store = await asyncio.to_thread(ChannelRuntimeConfigStore, path)

    real_chmod = Path.chmod

    def chmod_spy(self: Path, mode: int, *args, **kwargs):
        if self.suffix == ".tmp":
            raise OSError("chmod unsupported on this filesystem")
        return real_chmod(self, mode, *args, **kwargs)

    def _save_with_failing_temp_chmod() -> None:
        with caplog.at_level(logging.DEBUG, logger="app.channels.runtime_config_store"), mock.patch.object(Path, "chmod", chmod_spy):
            store.set_provider_config("slack", {"enabled": True, "bot_token": "xoxb-ui"})

    await asyncio.to_thread(_save_with_failing_temp_chmod)

    assert any("Unable to chmod temporary channel runtime config store" in record.getMessage() for record in caplog.records)
    mode = await asyncio.to_thread(lambda: path.stat().st_mode & 0o777)
    assert mode == 0o600
    assert await asyncio.to_thread(store.get_provider_config, "slack") == {"enabled": True, "bot_token": "xoxb-ui"}
