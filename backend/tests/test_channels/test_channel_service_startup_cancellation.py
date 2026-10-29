import asyncio
from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_cancelled_start_drains_partial_service_and_clears_singleton() -> None:
    import app.channels.service as service_module

    start_entered = asyncio.Event()
    stop_entered = asyncio.Event()
    allow_stop = asyncio.Event()

    class FakeService:
        async def start(self) -> None:
            start_entered.set()
            await asyncio.Event().wait()

        async def stop(self) -> None:
            stop_entered.set()
            await allow_stop.wait()

    fake = FakeService()
    service_module._channel_service = None
    config = MagicMock()

    try:
        with patch.object(service_module.ChannelService, "from_app_config", return_value=fake):
            task = asyncio.create_task(service_module.start_channel_service(config))
            await asyncio.wait_for(start_entered.wait(), timeout=1)

            task.cancel()
            for _ in range(5):
                await asyncio.sleep(0)

            assert stop_entered.is_set(), "cancelled startup did not begin partial-service cleanup"
            assert not task.done(), "startup returned before owned partial cleanup finished"

            task.cancel()
            for _ in range(5):
                await asyncio.sleep(0)
            assert not task.done(), "repeated cancellation abandoned partial-service cleanup"

            allow_stop.set()
            with pytest.raises(asyncio.CancelledError):
                await task

            assert service_module.get_channel_service() is None
    finally:
        allow_stop.set()
        service_module._channel_service = None
