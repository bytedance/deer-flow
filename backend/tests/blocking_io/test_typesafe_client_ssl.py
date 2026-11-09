"""The TypeSafe client must load TLS trust off the agent event loop.

``TypeSafeClient.aask`` builds its ``httpx.AsyncClient`` per evaluation, and that
constructor resolves the certificate store synchronously. ``aask`` is awaited by
``GuardrailMiddleware.awrap_tool_call`` and by both memory paths, so the load runs
on the Gateway loop for every guarded tool call and stalls every other task on it.
``backend/AGENTS.md`` records the rule — HTTPX clients are built with
``asyncio.to_thread`` for the synchronous TLS setup, while requests and cleanup
stay on-loop — and this anchor is the Crawl4AI one's shape for the shared client
that all three TypeSafe consumers go through.
"""

from __future__ import annotations

import asyncio
import ssl
import threading

import httpx
import pytest

from deerflow.typesafe.client import QUESTION_NOUL, NoulAnswer, Question, TransportFactory, TypeSafeClient
from deerflow.typesafe.connection import resolve_connection
from deerflow.typesafe.errors import CAUSE_DEADLINE, TypeSafeError

pytestmark = pytest.mark.asyncio

_API_KEY = "off-loop-tls-test-key"
_BASE_URL = "https://system-one.example"
_QUESTION = "risky_tool_call"

_ANSWER_SET = {"model": "jev-1.13.0", "answers": {_QUESTION: {"type": QUESTION_NOUL, "noul": 0.93}}}


def _client(*, transport_factory: TransportFactory | None = None) -> TypeSafeClient:
    connection = resolve_connection(
        settings={"api_key": _API_KEY, "base_url": _BASE_URL},
        configuration_source="tests.typesafe",
    )
    return TypeSafeClient(connection, transport_factory=transport_factory)


def _questions() -> dict[str, Question]:
    return {_QUESTION: Question(type=QUESTION_NOUL, instructions="Is this tool call risky?")}


async def test_aask_builds_its_client_off_the_loop(monkeypatch):
    """The constructor runs in a worker; the request it produced stays on the loop."""
    loop_thread = threading.get_ident()
    original_context = ssl.create_default_context
    contexts: list[ssl.SSLContext] = []
    clients: list[httpx.AsyncClient] = []

    def create_context(*args, **kwargs):
        assert threading.get_ident() != loop_thread, "TLS trust loading blocks the event loop"
        context = original_context(*args, **kwargs)
        contexts.append(context)
        return context

    async def send(self, request, **kwargs):
        assert threading.get_ident() == loop_thread, "requests must not move onto the worker thread"
        clients.append(self)
        assert request.url.host == "system-one.example"
        return httpx.Response(200, request=request, json=_ANSWER_SET)

    monkeypatch.setattr(ssl, "create_default_context", create_context)
    monkeypatch.setattr(httpx.AsyncClient, "send", send)

    answer_set = await _client().aask({"tool_call": {"name": "bash", "arguments": "{}"}}, _questions())

    assert answer_set.noul(_QUESTION) == NoulAnswer(probability=0.93)
    assert contexts, "the client was never built, so the anchor proves nothing"
    assert len(clients) == 1
    assert clients[0].is_closed, "the per-evaluation client is still closed with its transport"


@pytest.mark.parametrize("deadline", [True, False], ids=["deadline", "caller-cancel"])
async def test_aask_drains_client_construction_and_close(monkeypatch, deadline):
    loop = asyncio.get_running_loop()
    construction_started = asyncio.Event()
    construction_finished = asyncio.Event()
    release_construction = threading.Event()
    close_started = asyncio.Event()
    release_close = asyncio.Event()
    closed = asyncio.Event()
    clients: list[httpx.AsyncClient] = []
    original_init = httpx.AsyncClient.__init__

    class GatedTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            pytest.fail("a cancelled evaluation must never send a request")

        async def aclose(self):
            assert asyncio.get_running_loop() is loop
            close_started.set()
            await release_close.wait()
            closed.set()

    def gated_init(self, *args, **kwargs):
        loop.call_soon_threadsafe(construction_started.set)
        try:
            assert release_construction.wait(timeout=5)
            original_init(self, *args, **kwargs)
            clients.append(self)
        finally:
            loop.call_soon_threadsafe(construction_finished.set)

    timeout = asyncio.timeout(None)
    monkeypatch.setattr(asyncio, "timeout", lambda _delay: timeout)
    monkeypatch.setattr(httpx.AsyncClient, "__init__", gated_init)
    evaluation = asyncio.create_task(_client(transport_factory=GatedTransport).aask({}, _questions()))
    try:
        await asyncio.wait_for(construction_started.wait(), timeout=5)
        if deadline:
            timeout.reschedule(loop.time())
            await asyncio.sleep(0)  # Run the timeout callback.
            assert timeout.expired()
        else:
            evaluation.cancel("caller")
        await asyncio.sleep(0)  # Deliver cancellation to the evaluation.
        assert not evaluation.done(), "the worker still owns the unfinished client"

        release_construction.set()
        await asyncio.wait_for(close_started.wait(), timeout=5)
        if not deadline:
            evaluation.cancel("repeated")
            await asyncio.sleep(0)
        assert not evaluation.done(), "the client still owns an unclosed transport"

        release_close.set()
        if deadline:
            with pytest.raises(TypeSafeError) as excinfo:
                await evaluation
            assert excinfo.value.cause == CAUSE_DEADLINE
        else:
            with pytest.raises(asyncio.CancelledError, match="caller"):
                await evaluation
        assert closed.is_set()
        assert len(clients) == 1 and clients[0].is_closed
    finally:
        release_construction.set()
        release_close.set()
        await asyncio.gather(evaluation, return_exceptions=True)
        if construction_started.is_set():
            await asyncio.wait_for(construction_finished.wait(), timeout=5)
