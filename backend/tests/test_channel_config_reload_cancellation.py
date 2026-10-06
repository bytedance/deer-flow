from __future__ import annotations

import asyncio
import threading

import pytest

from app.channels.service import ChannelService


@pytest.mark.asyncio
async def test_cancelled_reload_cannot_overwrite_new_runtime_config() -> None:
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

    def blocking_reload(_name: str):
        reload_started.set()
        assert allow_reload.wait(timeout=2)
        return {
            "enabled": False,
            "marker": "stale",
        }

    service._load_channel_config = blocking_reload

    restart = asyncio.create_task(service.restart_channel("wechat"))
    try:
        assert await asyncio.to_thread(reload_started.wait, 2)

        restart.cancel()
        with pytest.raises(asyncio.CancelledError):
            await restart

        assert await service.configure_channel(
            "wechat",
            {
                "enabled": False,
                "marker": "fresh",
            },
        )

        allow_reload.set()
        for _ in range(5):
            await asyncio.sleep(0)

        assert service._config["wechat"]["marker"] == "fresh"
    finally:
        allow_reload.set()
        if not restart.done():
            restart.cancel()
            await asyncio.gather(restart, return_exceptions=True)
