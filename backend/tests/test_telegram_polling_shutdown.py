"""Real PTB HTTP connections must close even when startup never completes."""

from __future__ import annotations

import asyncio
import json
import threading
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.channels.base import ChannelStopTimeout
from app.channels.message_bus import MessageBus
from app.channels.telegram import TelegramChannel


async def _until(predicate, timeout=5):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)


class _BotAPI:
    """Small HTTP/1.1 Bot API fixture with observable client EOF."""

    def __init__(self, mode):
        self.mode = mode
        self.requests = []
        self.connections = []
        self.release = asyncio.Event()
        self.handlers = set()

    async def handle(self, reader, writer):
        self.handlers.add(asyncio.current_task())
        connection = {"writer": writer, "eof": asyncio.Event()}
        self.connections.append(connection)
        try:
            while line := await reader.readline():
                method = line.decode().split()[1].rsplit("/", 1)[-1].lower()
                headers = {}
                while (line := await reader.readline()) not in (b"\r\n", b"\n", b""):
                    key, value = line.decode().split(":", 1)
                    headers[key.lower()] = value.strip()
                await reader.readexactly(int(headers.get("content-length", "0")))
                self.requests.append(method)
                if method == "getme" and self.mode == "blocked":
                    gate = asyncio.create_task(self.release.wait())
                    peer = asyncio.create_task(reader.read(1))
                    try:
                        done, _ = await asyncio.wait((gate, peer), return_when=asyncio.FIRST_COMPLETED)
                        if peer in done and not peer.result():
                            connection["eof"].set()
                            return
                    finally:
                        gate.cancel()
                        peer.cancel()
                        await asyncio.gather(gate, peer, return_exceptions=True)
                if method == "getme":
                    result = {"id": 12345, "is_bot": True, "first_name": "Offline", "username": "offline_test_bot"}
                elif method == "getupdates":
                    await asyncio.sleep(0.01)
                    result = []
                else:
                    assert method == "deletewebhook", method
                    result = True
                rejected = method == "getme" and self.mode == "rejected"
                payload = {"ok": False, "error_code": 401, "description": "Unauthorized"} if rejected else {"ok": True, "result": result}
                data = json.dumps(payload).encode()
                status = "401 Unauthorized" if rejected else "200 OK"
                writer.write(f"HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {len(data)}\r\n\r\n".encode() + data)
                await writer.drain()
            connection["eof"].set()
        except (ConnectionError, asyncio.IncompleteReadError):
            connection["eof"].set()
        finally:
            writer.close()
            await writer.wait_closed()
            self.handlers.discard(asyncio.current_task())


def _cleanup_failed_assertion(loop, application):
    """Tests inspect resources before this fallback; RED must not leak them."""
    if loop.is_closed():
        return
    asyncio.set_event_loop(loop)

    async def close():
        pending = [task for task in asyncio.all_tasks(loop) if task is not asyncio.current_task() and not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        await application.bot.shutdown()

    try:
        loop.run_until_complete(close())
        loop.run_until_complete(loop.shutdown_asyncgens())
    finally:
        loop.close()
        asyncio.set_event_loop(None)


@asynccontextmanager
async def _channel(monkeypatch, *, mode="normal", shutdown_gate=None):
    ext = pytest.importorskip("telegram.ext")
    from telegram.request import HTTPXRequest

    class Request(HTTPXRequest):
        async def shutdown(self):
            if shutdown_gate is not None and not self._client.is_closed:
                shutdown_gate["calls"] += 1
                shutdown_gate["started"].set()
                while not shutdown_gate["release"].is_set():
                    await asyncio.sleep(0.01)
            await super().shutdown()

    api = _BotAPI(mode)
    server = await asyncio.start_server(api.handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    original = ext.ApplicationBuilder

    def builder():
        return original().base_url(f"http://127.0.0.1:{port}/bot").request(Request(httpx_kwargs={"trust_env": False})).get_updates_request(Request(httpx_kwargs={"trust_env": False}))

    monkeypatch.setattr(ext, "ApplicationBuilder", builder)
    channel = TelegramChannel(MessageBus(), {"bot_token": "12345:offline-test-token"})
    owned = []

    async def start():
        before = len(api.requests)
        await channel.start()
        application, thread = channel._application, channel._thread
        await _until(lambda: len(api.requests) > before)
        owned.append((channel._tg_loop, application, thread))
        return application, thread, channel._tg_loop

    try:
        yield channel, api, start
    finally:
        api.release.set()
        if shutdown_gate is not None:
            shutdown_gate["release"].set()
        try:
            await asyncio.wait_for(channel.stop(), 6)
        except (ChannelStopTimeout, TimeoutError):
            pass
        for loop, application, thread in owned:
            if loop.is_running():
                loop.call_soon_threadsafe(loop.stop)
            await asyncio.to_thread(thread.join, 3)
            assert not thread.is_alive(), "test must not leave a Telegram worker"
            await asyncio.to_thread(_cleanup_failed_assertion, loop, application)
        server.close()
        await server.wait_closed()
        for connection in api.connections:
            connection["writer"].close()
        pending = list(api.handlers)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)


async def _assert_closed(api, application, thread, loop):
    assert not thread.is_alive()
    assert all(request._client.is_closed for request in application.bot._request)
    await _until(lambda: all(connection["eof"].is_set() for connection in api.connections))
    assert not asyncio.all_tasks(loop)
    assert loop.is_closed()


@pytest.mark.asyncio
async def test_stop_during_real_ptb_initialize_closes_requests_and_cancels_startup(monkeypatch):
    async with _channel(monkeypatch, mode="blocked") as (channel, api, start):
        application, thread, loop = await start()
        assert not application.running
        assert not application._initialized
        await channel.stop()
        await _assert_closed(api, application, thread, loop)
        assert "deletewebhook" not in api.requests
        assert "getupdates" not in api.requests


@pytest.mark.asyncio
async def test_failed_real_ptb_initialize_closes_partial_bot_without_explicit_stop(monkeypatch):
    async with _channel(monkeypatch, mode="rejected") as (channel, api, start):
        application, thread, loop = await start()
        await _until(lambda: not thread.is_alive())
        await _assert_closed(api, application, thread, loop)
        assert channel.is_running is False
        await channel.stop()


@pytest.mark.asyncio
async def test_real_ptb_can_restart_after_complete_stop(monkeypatch):
    async with _channel(monkeypatch) as (channel, api, start):
        for _ in range(2):
            application, thread, loop = await start()
            await _until(lambda: application.running and application.updater.running)
            await channel.stop()
            await _assert_closed(api, application, thread, loop)


@pytest.mark.asyncio
@pytest.mark.parametrize("interruption", ["cancel", "timeout"])
async def test_stop_interruption_retains_partial_application_cleanup_for_retry(monkeypatch, interruption):
    from app.channels import telegram as telegram_module

    gate = {"started": threading.Event(), "release": threading.Event(), "calls": 0}
    if interruption == "timeout":
        monkeypatch.setattr(telegram_module, "TELEGRAM_SHUTDOWN_TIMEOUT_SECONDS", 0.05)
    async with _channel(monkeypatch, mode="blocked", shutdown_gate=gate) as (channel, api, start):
        application, thread, loop = await start()
        stop = asyncio.create_task(channel.stop())
        try:
            await _until(gate["started"].is_set)
            cleanup = channel._shutdown_resources_future
            if interruption == "cancel":
                stop.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await stop
            else:
                with pytest.raises(ChannelStopTimeout):
                    await stop
            assert channel._thread is thread
            assert thread.is_alive() and loop.is_running()
            assert cleanup is not None and not cleanup.cancelled()
            assert channel._shutdown_resources_future is cleanup
            gate["release"].set()
            monkeypatch.setattr(telegram_module, "TELEGRAM_SHUTDOWN_TIMEOUT_SECONDS", 4)
            await channel.stop()
            await _assert_closed(api, application, thread, loop)
            assert gate["calls"] == 2
        finally:
            gate["release"].set()
            if not stop.done():
                stop.cancel()
            await asyncio.gather(stop, return_exceptions=True)


def test_polling_finalizes_async_generators_when_resource_cleanup_fails(monkeypatch, caplog):
    channel = TelegramChannel(MessageBus(), {"bot_token": "12345:offline-test-token"})
    primary = ValueError("updater shutdown failed")
    channel._application = SimpleNamespace(
        updater=SimpleNamespace(running=True, stop=AsyncMock(side_effect=primary)),
        running=False,
        shutdown=AsyncMock(),
        bot=SimpleNamespace(shutdown=AsyncMock()),
    )
    finalized = threading.Event()
    generators = []

    async def resource():
        try:
            yield
        finally:
            finalized.set()

    async def bootstrap(application):
        generator = resource()
        generators.append(generator)
        await anext(generator)
        channel._running = False

    monkeypatch.setattr(channel, "_bootstrap_telegram", bootstrap)
    channel._running = True
    thread = threading.Thread(target=channel._run_polling)
    thread.start()
    try:
        thread.join(timeout=5)
        assert not thread.is_alive()
        assert finalized.is_set()
        assert channel._tg_loop.is_closed()
        assert any(record.exc_info and record.exc_info[1] is primary for record in caplog.records)
    finally:
        if thread.is_alive():
            channel._tg_loop.call_soon_threadsafe(channel._tg_loop.stop)
            thread.join(timeout=5)
        assert not thread.is_alive(), "test must not leave a Telegram worker"
        # RED must not leak the generator; assertions above precede fallback cleanup.
        for generator in generators:
            asyncio.run(generator.aclose())


@pytest.mark.asyncio
@pytest.mark.parametrize("primary_kind", ["exception", "cancelled", None])
async def test_application_bot_shutdown_preserves_primary_error_and_reports_its_own(primary_kind, caplog):
    channel = TelegramChannel(MessageBus(), {"bot_token": "12345:offline-test-token"})
    primary = None
    if primary_kind == "exception":
        primary = ValueError("updater shutdown failed")
    elif primary_kind == "cancelled":
        primary = asyncio.CancelledError("application cleanup cancelled")
    bot_error = RuntimeError("application bot shutdown failed")
    channel._application = SimpleNamespace(
        updater=SimpleNamespace(running=True, stop=AsyncMock(side_effect=primary)),
        running=False,
        shutdown=AsyncMock(),
        bot=SimpleNamespace(shutdown=AsyncMock(side_effect=bot_error)),
    )

    expected = primary if primary is not None else bot_error
    with pytest.raises(type(expected)) as raised:
        await channel._shutdown_telegram_resources()

    assert raised.value is expected
    channel._application.bot.shutdown.assert_awaited_once()
    if primary is not None:
        assert any("failed to shut down the application bot" in record.message and record.exc_info and record.exc_info[1] is bot_error for record in caplog.records)
