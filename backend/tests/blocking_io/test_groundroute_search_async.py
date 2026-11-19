"""GroundRoute community tools must not occupy an executor thread or block the loop.

The GroundRoute provider resolved its config and sent its search request
through a synchronous ``httpx.Client``. A sync LangChain tool invoked through
``ainvoke`` runs on the default executor, so the request held one of that
pool's threads for the whole network round-trip: with several providers
queried in parallel the default pool ran out of threads and the tool calls
queued behind each other.

The probes below assert the whole fix:

* the request is awaited on the event loop thread instead of an executor
  thread, so no pool thread is held for the round-trip;
* the config lookup, which reads the config file, still runs off the loop.
  The tool body is now a coroutine that executes on the loop, so a file read
  left in it would block the loop; the strict blocking-I/O gate fails if the
  lookup regresses onto the loop.
* the request goes out through the async client. A `MockTransport` runs its
  handler on the calling thread and performs no real blocking I/O, so a
  provider that stayed async but sent the request through a sync
  `httpx.Client` would satisfy the thread assertion above; the recorded
  client factory is what catches that partial regression.
"""

import threading
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from deerflow.community.groundroute import tools as groundroute_tools

pytestmark = pytest.mark.asyncio


def _patch_transport(monkeypatch, request_threads: list[int], clients: list[str]) -> None:
    """Answer every request locally and record the thread that served it.

    The provider's module holds the shared ``httpx`` module, so the reference
    itself is replaced with a namespace exposing both client factories. That
    keeps the test hermetic — no request leaves the machine — whichever
    factory the provider uses. Each factory records its name in ``clients``
    so a test can assert which one the provider reached for.
    """

    def respond(request: httpx.Request) -> httpx.Response:
        request_threads.append(threading.get_ident())
        return httpx.Response(200, json={"results": []})

    transport = httpx.MockTransport(respond)

    def async_client(**kwargs):
        clients.append("AsyncClient")
        return httpx.AsyncClient(transport=transport, **kwargs)

    def sync_client(**kwargs):
        clients.append("Client")
        return httpx.Client(transport=transport, **kwargs)

    monkeypatch.setattr(
        groundroute_tools,
        "httpx",
        SimpleNamespace(
            AsyncClient=async_client,
            Client=sync_client,
            HTTPStatusError=httpx.HTTPStatusError,
        ),
    )


def _patch_config(monkeypatch, load_config=None) -> None:
    def config():
        return SimpleNamespace(get_tool_config=lambda _name: SimpleNamespace(model_extra={"api_key": "synthetic-key"}))

    monkeypatch.setattr(groundroute_tools, "get_app_config", load_config or config)


async def test_groundroute_search_request_runs_on_the_event_loop(monkeypatch) -> None:
    """The request is awaited on the loop, not dispatched to an executor thread."""
    request_threads: list[int] = []
    clients: list[str] = []
    loop_thread = threading.get_ident()
    _patch_transport(monkeypatch, request_threads, clients)
    _patch_config(monkeypatch)

    result = await groundroute_tools.web_search_tool.ainvoke({"query": "vector databases"})

    assert '"error": "No results found"' in result
    assert request_threads, "the request must reach the transport"
    assert all(thread == loop_thread for thread in request_threads)
    assert clients == ["AsyncClient"], "the request must go out through the async client"


async def test_groundroute_fetch_request_runs_on_the_event_loop(monkeypatch) -> None:
    """web_fetch shares the same client, so it must stay off the executor too."""
    request_threads: list[int] = []
    clients: list[str] = []
    loop_thread = threading.get_ident()
    _patch_transport(monkeypatch, request_threads, clients)
    _patch_config(monkeypatch)

    result = await groundroute_tools.web_fetch_tool.ainvoke({"url": "https://example.com/report"})

    assert "Error: No results found" == result
    assert request_threads, "the request must reach the transport"
    assert all(thread == loop_thread for thread in request_threads)
    assert clients == ["AsyncClient"], "the request must go out through the async client"


async def test_groundroute_config_lookup_does_not_block_loop(monkeypatch) -> None:
    """The tool body runs on the loop, so the config file read must not."""
    config_threads: list[int] = []
    loop_thread = threading.get_ident()

    def load_config():
        # Keep a real file read in the lookup so the strict blocking-I/O gate
        # fails if the tool resolves config on the event loop.
        Path(__file__).read_text(encoding="utf-8")
        config_threads.append(threading.get_ident())
        return SimpleNamespace(get_tool_config=lambda _name: SimpleNamespace(model_extra={"api_key": "synthetic-key"}))

    request_threads: list[int] = []
    clients: list[str] = []
    _patch_transport(monkeypatch, request_threads, clients)
    _patch_config(monkeypatch, load_config)

    result = await groundroute_tools.web_search_tool.ainvoke({"query": "vector databases"})

    assert '"error": "No results found"' in result
    assert config_threads, "config lookup must run"
    assert all(thread != loop_thread for thread in config_threads)
    assert clients == ["AsyncClient"], "the request must go out through the async client"
