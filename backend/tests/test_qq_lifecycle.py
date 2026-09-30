"""Exercise the adapter against real loopback WebSocket connections."""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from websockets.asyncio.server import serve

from app.channels import qq
from app.channels.message_bus import MessageBus


def ready(sequence=1):
    return {
        "op": 0,
        "s": sequence,
        "t": "READY",
        "d": {"session_id": "fixture-session", "user": {"id": "99"}},
    }


def message():
    return {
        "op": 0,
        "s": 2,
        "t": "C2C_MESSAGE_CREATE",
        "d": {
            "id": "fixture-message",
            "content": "hello",
            "author": {"user_openid": "alice"},
        },
    }


async def acknowledge(socket):
    async for raw in socket:
        if json.loads(raw).get("op") == 1:
            await socket.send(json.dumps({"op": 11}))


def adapter(monkeypatch, port):
    channel = qq.QQChannel(MessageBus(), {"app_id": "fixture-app", "client_secret": "fixture-secret"})
    channel._api_request = AsyncMock(return_value={"url": f"ws://127.0.0.1:{port}/"})
    channel._get_access_token = AsyncMock(return_value="fixture-token")
    # Only test-local discovery may use plaintext loopback.
    monkeypatch.setattr(qq, "validate_gateway_url", lambda url: url)
    monkeypatch.setattr(qq, "RECONNECT_DELAY", 0.001)
    return channel


@pytest.mark.asyncio
async def test_reconnect_resume_invalid_session_reidentify_and_deduplicate(monkeypatch):
    authentications = []
    recovered = asyncio.Event()

    async def gateway(socket):
        await socket.send(json.dumps({"op": 10, "d": {"heartbeat_interval": 100}}))
        authentications.append(json.loads(await socket.recv()))
        attempt = len(authentications)
        if attempt == 1:
            await socket.send(json.dumps(ready()))
            await socket.send(json.dumps(message()))
            await socket.send(json.dumps({"op": 7}))
        elif attempt == 2:
            await socket.send(json.dumps({"op": 9, "d": False}))
        else:
            await socket.send(json.dumps(ready()))
            await socket.send(json.dumps(message()))
            recovered.set()
        await acknowledge(socket)

    async with serve(gateway, "127.0.0.1", 0) as server:
        channel = adapter(monkeypatch, server.sockets[0].getsockname()[1])
        try:
            await channel.start()
            await asyncio.wait_for(recovered.wait(), 3)
            await asyncio.wait_for(channel._events.join(), 3)
            assert channel.is_running
            assert [auth["op"] for auth in authentications] == [2, 6, 2]
            assert authentications[0]["d"]["intents"] == 1 << 25
            assert authentications[1]["d"]["session_id"] == "fixture-session"
            assert authentications[1]["d"]["seq"] == 2
            assert channel.bus.inbound_queue.qsize() == 1
            assert channel.bus.get_inbound_nowait().thread_ts == "fixture-message"
        finally:
            await channel.stop()
        assert not channel.is_running
        assert channel._listener is channel._worker is channel._http is None
        assert not [task for task in asyncio.all_tasks() if task.get_name().startswith("qq-")]


@pytest.mark.asyncio
async def test_missing_heartbeat_ack_reconnects(monkeypatch):
    authentications = []
    reconnected = asyncio.Event()

    async def gateway(socket):
        await socket.send(json.dumps({"op": 10, "d": {"heartbeat_interval": 30}}))
        authentications.append(json.loads(await socket.recv()))
        await socket.send(json.dumps(ready()))
        if len(authentications) == 1:
            await socket.wait_closed()
        else:
            reconnected.set()
            await acknowledge(socket)

    async with serve(gateway, "127.0.0.1", 0) as server:
        channel = adapter(monkeypatch, server.sockets[0].getsockname()[1])
        try:
            await channel.start()
            await asyncio.wait_for(reconnected.wait(), 3)
            assert authentications[1]["op"] == 6
        finally:
            await channel.stop()


@pytest.mark.asyncio
async def test_start_timeout_closes_socket_and_owned_tasks(monkeypatch):
    closed = asyncio.Event()

    async def gateway(socket):
        try:
            await socket.send(json.dumps({"op": 10, "d": {"heartbeat_interval": 100}}))
            await acknowledge(socket)
        finally:
            closed.set()

    async with serve(gateway, "127.0.0.1", 0) as server:
        channel = adapter(monkeypatch, server.sockets[0].getsockname()[1])
        monkeypatch.setattr(qq, "START_TIMEOUT", 0.1)
        with pytest.raises(TimeoutError):
            await channel.start()
        await asyncio.wait_for(closed.wait(), 3)
        assert channel._listener is channel._worker is channel._http is None
        assert not channel.is_running


@pytest.mark.asyncio
async def test_start_cancellation_drains_transport_setup(monkeypatch):
    channel = qq.QQChannel(MessageBus(), {"app_id": "fixture-app", "client_secret": "fixture-secret"})
    started, release = asyncio.Event(), asyncio.Event()
    client = AsyncMock()

    async def setup():
        started.set()
        await release.wait()
        channel._http = client

    monkeypatch.setattr(channel, "_setup_transport", setup)
    task = asyncio.create_task(channel.start())
    await started.wait()
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    client.aclose.assert_awaited_once()
    assert channel._http is None


@pytest.mark.asyncio
@pytest.mark.parametrize(("close_code", "expected_op"), [(4004, 2), (4006, 2), (4007, 2), (4009, 6)])
async def test_provider_close_codes_choose_identify_or_resume(monkeypatch, close_code, expected_op):
    authentications = []
    recovered = asyncio.Event()

    async def gateway(socket):
        await socket.send(json.dumps({"op": 10, "d": {"heartbeat_interval": 100}}))
        authentications.append(json.loads(await socket.recv()))
        await socket.send(json.dumps(ready()))
        if len(authentications) == 1:
            await socket.close(code=close_code)
        else:
            recovered.set()
            await acknowledge(socket)

    async with serve(gateway, "127.0.0.1", 0) as server:
        channel = adapter(monkeypatch, server.sockets[0].getsockname()[1])
        try:
            await channel.start()
            await asyncio.wait_for(recovered.wait(), 3)
            assert authentications[1]["op"] == expected_op
        finally:
            await channel.stop()


@pytest.mark.asyncio
async def test_first_heartbeat_uses_ready_sequence(monkeypatch):
    heartbeats = []
    observed = asyncio.Event()

    async def gateway(socket):
        await socket.send(json.dumps({"op": 10, "d": {"heartbeat_interval": 100}}))
        assert json.loads(await socket.recv())["op"] == 2
        await socket.send(json.dumps(ready()))
        async for raw in socket:
            frame = json.loads(raw)
            if frame.get("op") == 1:
                heartbeats.append(frame["d"])
                await socket.send(json.dumps({"op": 11}))
                observed.set()

    async with serve(gateway, "127.0.0.1", 0) as server:
        channel = adapter(monkeypatch, server.sockets[0].getsockname()[1])
        try:
            await channel.start()
            await asyncio.wait_for(observed.wait(), 3)
            assert heartbeats[0] == 1
        finally:
            await channel.stop()


@pytest.mark.asyncio
async def test_successful_resume_restarts_heartbeats(monkeypatch):
    connections = 0
    resumed_heartbeat = asyncio.Event()

    async def gateway(socket):
        nonlocal connections
        connections += 1
        attempt = connections
        await socket.send(json.dumps({"op": 10, "d": {"heartbeat_interval": 100}}))
        authentication = json.loads(await socket.recv())
        if attempt == 1:
            assert authentication["op"] == 2
            await socket.send(json.dumps(ready()))
            await socket.send(json.dumps({"op": 7}))
        else:
            assert authentication["op"] == 6
            await socket.send(json.dumps({"op": 0, "s": 3, "t": "RESUMED", "d": {}}))
        async for raw in socket:
            frame = json.loads(raw)
            if frame.get("op") == 1:
                await socket.send(json.dumps({"op": 11}))
                if attempt > 1:
                    assert frame["d"] == 3
                    resumed_heartbeat.set()

    async with serve(gateway, "127.0.0.1", 0) as server:
        channel = adapter(monkeypatch, server.sockets[0].getsockname()[1])
        try:
            await channel.start()
            await asyncio.wait_for(resumed_heartbeat.wait(), 3)
            assert channel.is_running
        finally:
            await channel.stop()


@pytest.mark.asyncio
async def test_slow_inbound_work_does_not_block_heartbeats(monkeypatch):
    entered, release, heartbeats_received = (
        asyncio.Event(),
        asyncio.Event(),
        asyncio.Event(),
    )
    count = 0

    async def gateway(socket):
        nonlocal count
        await socket.send(json.dumps({"op": 10, "d": {"heartbeat_interval": 30}}))
        await socket.recv()
        await socket.send(json.dumps(ready()))
        await socket.send(json.dumps(message()))
        async for raw in socket:
            if json.loads(raw).get("op") == 1:
                await socket.send(json.dumps({"op": 11}))
                count += 1
                if count >= 3:
                    heartbeats_received.set()

    async def slow_inbound(frame):
        entered.set()
        await release.wait()

    async with serve(gateway, "127.0.0.1", 0) as server:
        channel = adapter(monkeypatch, server.sockets[0].getsockname()[1])
        monkeypatch.setattr(channel, "_handle_inbound", slow_inbound)
        try:
            await channel.start()
            await asyncio.wait_for(entered.wait(), 3)
            await asyncio.wait_for(heartbeats_received.wait(), 3)
            assert not release.is_set()
            assert channel.is_running
        finally:
            release.set()
            await channel.stop()


@pytest.mark.asyncio
async def test_cancelled_stop_drains_http_client_cleanup():
    channel = qq.QQChannel(MessageBus(), {"app_id": "fixture-app", "client_secret": "fixture-secret"})
    entered, release = asyncio.Event(), asyncio.Event()

    async def close():
        entered.set()
        await release.wait()

    client = AsyncMock()
    client.aclose.side_effect = close
    channel._http = client
    task = asyncio.create_task(channel.stop())
    await entered.wait()
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    client.aclose.assert_awaited_once()
    assert channel._http is None


@pytest.mark.asyncio
async def test_service_registers_starts_and_disposes_qq(tmp_path, monkeypatch):
    from app.channels import service as service_module
    from app.channels.store import ChannelStore
    from deerflow.config.app_config import AppConfig

    store = ChannelStore(tmp_path / "channels.json")
    monkeypatch.setattr(service_module, "ChannelStore", lambda: store)
    config = {
        "app_id": "fixture-app",
        "client_secret": "fixture-secret",
        "enabled": True,
    }
    app_config = AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}})
    repository = object()
    service = service_module.ChannelService({"qq": config}, connection_repo=repository, app_config=app_config)

    async def connected(self, url):
        self._ready.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(
        qq.QQChannel,
        "_api_request",
        AsyncMock(return_value={"url": "wss://api.sgroup.qq.com/websocket/"}),
    )
    monkeypatch.setattr(qq.QQChannel, "_run_connection", connected)
    try:
        assert await service._start_channel("qq", config)
        channel = service.get_channel("qq")
        assert isinstance(channel, qq.QQChannel)
        assert channel.is_running
        assert channel.bus is service.bus
        assert channel._connection_repo is repository
        assert not channel.supports_streaming
    finally:
        channel = service.get_channel("qq")
        if channel is not None:
            await service._stop_and_discard_channel("qq", channel)
    assert service.get_channel("qq") is None
    assert channel._listener is channel._worker is channel._http is None
