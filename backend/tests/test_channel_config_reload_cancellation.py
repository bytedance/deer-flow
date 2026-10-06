from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest

from app.channels.service import ChannelService
from deerflow.config import app_config as app_config_module


@pytest.mark.asyncio
async def test_cancelled_reload_cannot_overwrite_new_runtime_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = ChannelService(
        channels_config={
            "wechat": {
                "enabled": False,
                "marker": "initial",
            }
        }
    )
    reload_started = threading.Event()
    allow_reload = threading.Event()
    reload_finished = threading.Event()

    def blocking_get_app_config():
        reload_started.set()
        assert allow_reload.wait(timeout=2)
        return SimpleNamespace(
            model_extra={
                "channels": {
                    "wechat": {
                        "enabled": False,
                        "marker": "stale",
                    }
                }
            },
            channel_connections=None,
        )

    monkeypatch.setattr(app_config_module, "get_app_config", blocking_get_app_config)

    real_load = service._load_channel_config

    def tracked_load(name: str):
        try:
            return real_load(name)
        finally:
            reload_finished.set()

    monkeypatch.setattr(service, "_load_channel_config", tracked_load)

    restart = asyncio.create_task(service.restart_channel("wechat"))
    try:
        assert await asyncio.to_thread(reload_started.wait, 2)
        restart.cancel()
        with pytest.raises(asyncio.CancelledError):
            await restart

        assert await service.configure_channel(
            "wechat",
            {"enabled": False, "marker": "fresh"},
        )

        allow_reload.set()
        assert await asyncio.to_thread(reload_finished.wait, 2)
        assert service._config["wechat"]["marker"] == "fresh"
    finally:
        allow_reload.set()
        if not reload_finished.is_set():
            await asyncio.to_thread(reload_finished.wait, 2)
        if not restart.done():
            restart.cancel()
            await asyncio.gather(restart, return_exceptions=True)
