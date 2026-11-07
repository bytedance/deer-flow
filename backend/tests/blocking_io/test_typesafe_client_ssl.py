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

import ssl
import threading

import httpx
import pytest

from deerflow.typesafe.client import QUESTION_NOUL, NoulAnswer, Question, TypeSafeClient
from deerflow.typesafe.connection import resolve_connection

pytestmark = pytest.mark.asyncio

_API_KEY = "off-loop-tls-test-key"
_BASE_URL = "https://system-one.example"
_QUESTION = "risky_tool_call"

_ANSWER_SET = {"model": "jev-1.13.0", "answers": {_QUESTION: {"type": QUESTION_NOUL, "noul": 0.93}}}


def _client() -> TypeSafeClient:
    connection = resolve_connection(
        settings={"api_key": _API_KEY, "base_url": _BASE_URL},
        configuration_source="tests.typesafe",
    )
    return TypeSafeClient(connection)


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
