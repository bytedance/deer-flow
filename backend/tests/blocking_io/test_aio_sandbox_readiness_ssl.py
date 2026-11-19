"""Sandbox readiness polling must load HTTPX TLS trust off the event loop.

``wait_for_sandbox_ready_async`` exists precisely so sandbox startup waits do
not block the runtime's event loop, yet it built its client inline: the
``httpx.AsyncClient`` constructor resolves the system trust store synchronously,
so the loop stalled for its whole duration before the first poll was even sent.
"""

import asyncio
import ssl
import threading

import httpx
import pytest

from deerflow.community.aio_sandbox.backend import wait_for_sandbox_ready_async


@pytest.mark.asyncio
async def test_sandbox_readiness_tls_setup_runs_off_loop(monkeypatch):
    loop_thread = threading.get_ident()
    original_context = ssl.create_default_context
    contexts = []
    clients = []
    requests = []

    def create_context(*args, **kwargs):
        assert threading.get_ident() != loop_thread, "TLS trust loading blocks the event loop"
        context = original_context(*args, **kwargs)
        contexts.append(context)
        return context

    async def send(self, request, **kwargs):
        assert threading.get_ident() == loop_thread
        clients.append(self)
        requests.append(str(request.url))
        return httpx.Response(200, request=request, json={"status": "ready"})

    monkeypatch.setattr(ssl, "create_default_context", create_context)
    monkeypatch.setattr(httpx.AsyncClient, "send", send)

    ready = await wait_for_sandbox_ready_async(
        "http://sandbox.example:8080",
        timeout=5,
        headers={"Authorization": "Bearer synthetic"},
    )

    assert ready is True
    assert contexts
    assert requests == ["http://sandbox.example:8080/v1/sandbox"]
    assert len(clients) == 1
    assert clients[0].is_closed


@pytest.mark.asyncio
async def test_sandbox_readiness_closes_client_built_after_cancellation(monkeypatch):
    """Cancelling during construction must not leak the client it eventually builds.

    The constructor cannot be interrupted once it is inside the worker thread, so
    the await is abandoned while the thread goes on and hands back a live client.
    Nothing can enter the ``async with`` for that client, so the construction's
    owner has to close it and the wait still has to end cancelled.
    """
    real_client = httpx.AsyncClient
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    built = []
    sent = []

    def gated_client(*args, **kwargs):
        started.set()
        assert release.wait(10), "the constructor was never released"
        client = real_client(*args, **kwargs)
        built.append(client)
        finished.set()
        return client

    async def send(self, request, **kwargs):
        sent.append(request.url)
        return httpx.Response(200, request=request, json={"status": "ready"})

    monkeypatch.setattr(httpx, "AsyncClient", gated_client)
    monkeypatch.setattr(real_client, "send", send)

    pending = asyncio.ensure_future(wait_for_sandbox_ready_async("http://sandbox.example:8080", timeout=5))

    assert await asyncio.to_thread(started.wait, 10), "the constructor never started"
    # The wait is suspended on the constructor now, so the cancellation lands
    # there and never reaches the request: release the worker only afterwards.
    pending.cancel()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    release.set()

    with pytest.raises(asyncio.CancelledError):
        await pending

    # The worker thread cannot be stopped, so wait for it before judging what it
    # built; a leaked client is only visible once the constructor has returned.
    assert await asyncio.to_thread(finished.wait, 10), "the constructor never finished"

    assert sent == [], "a cancelled construction must not send a poll"
    assert len(built) == 1
    assert built[0].is_closed, "the client built after the cancellation was leaked"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stage", "log_fragment"),
    [
        ("construction", "construction failed after cancellation"),
        ("close", "built after cancellation failed"),
    ],
)
async def test_sandbox_readiness_preserves_caller_cancellation_when_owned_task_is_cancelled(monkeypatch, caplog, stage, log_fragment):
    loop = asyncio.get_running_loop()
    started = asyncio.Event()
    release = threading.Event()

    class Client:
        async def aclose(self):
            raise asyncio.CancelledError("close task cancelled")

    def build_client(**kwargs):
        loop.call_soon_threadsafe(started.set)
        assert release.wait(5), "the constructor was never released"
        if stage == "construction":
            raise asyncio.CancelledError("construction task cancelled")
        return Client()

    monkeypatch.setattr(httpx, "AsyncClient", build_client)
    pending = asyncio.create_task(wait_for_sandbox_ready_async("http://sandbox.example:8080", timeout=5))
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
    finally:
        pending.cancel("readiness caller cancelled")
        release.set()

    with pytest.raises(asyncio.CancelledError, match="readiness caller cancelled"):
        await pending
    assert log_fragment in caplog.text
