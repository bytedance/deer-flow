"""Opt-in QQ transport verification; does not send messages or invoke agents."""

import asyncio
import json
import os

import pytest

from app.channels.message_bus import MessageBus
from app.channels.qq import QQChannel

pytestmark = [pytest.mark.live, pytest.mark.asyncio]


async def test_qq_websocket_ready_and_heartbeat_acknowledgements():
    if os.getenv("DEER_FLOW_RUN_LIVE_TESTS") != "1":
        pytest.skip("Set DEER_FLOW_RUN_LIVE_TESTS=1 to enable live QQ verification")
    app_id = os.getenv("QQ_APP_ID")
    secret = os.getenv("QQ_CLIENT_SECRET")
    if not app_id or not secret:
        pytest.skip("QQ_APP_ID and QQ_CLIENT_SECRET are required")

    acknowledged = asyncio.Event()
    count = 0

    class ObservedSocket:
        def __init__(self, socket):
            self.socket = socket

        async def send(self, data):
            await self.socket.send(data)

        async def __aiter__(self):
            nonlocal count
            async for raw in self.socket:
                if json.loads(raw).get("op") == 11:
                    count += 1
                    if count >= 2:
                        acknowledged.set()
                yield raw

    class ObservedChannel(QQChannel):
        async def _read_frames(self, socket, ack):
            await super()._read_frames(ObservedSocket(socket), ack)

    channel = ObservedChannel(MessageBus(), {"app_id": app_id, "client_secret": secret})
    try:
        async with asyncio.timeout(150):
            await channel.start()
            assert channel.is_running
            await acknowledged.wait()
            assert channel.is_running
    finally:
        await channel.stop()
    assert count >= 2
    assert channel._listener is channel._worker is channel._http is None
