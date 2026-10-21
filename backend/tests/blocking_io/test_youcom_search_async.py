"""The You.com community tool must not occupy an executor thread or block the loop.

The You.com provider resolved its config and sent its search request through
a synchronous ``httpx.Client``. A sync LangChain tool invoked through
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

import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from deerflow.community.youcom import tools as youcom_tools

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
        return httpx.Response(200, json={"results": {"web": []}})

    transport = httpx.MockTransport(respond)

    def async_client(**kwargs):
        clients.append("AsyncClient")
        return httpx.AsyncClient(transport=transport, **kwargs)

    def sync_client(**kwargs):
        clients.append("Client")
        return httpx.Client(transport=transport, **kwargs)

    monkeypatch.setattr(
        youcom_tools,
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

    monkeypatch.setattr(youcom_tools, "get_app_config", load_config or config)


async def test_youcom_search_request_runs_on_the_event_loop(monkeypatch) -> None:
    """The request is awaited on the loop, not dispatched to an executor thread."""
    request_threads: list[int] = []
    clients: list[str] = []
    loop_thread = threading.get_ident()
    _patch_transport(monkeypatch, request_threads, clients)
    _patch_config(monkeypatch)

    result = await youcom_tools.web_search_tool.ainvoke({"query": "vector databases"})

    assert '"error": "No results found"' in result
    assert request_threads, "the request must reach the transport"
    assert all(thread == loop_thread for thread in request_threads)
    assert clients == ["AsyncClient"], "the request must go out through the async client"


async def test_youcom_config_lookup_does_not_block_loop(monkeypatch) -> None:
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

    result = await youcom_tools.web_search_tool.ainvoke({"query": "vector databases"})

    assert '"error": "No results found"' in result
    assert config_threads, "config lookup must run"
    assert all(thread != loop_thread for thread in config_threads)
    assert clients == ["AsyncClient"], "the request must go out through the async client"


async def test_youcom_user_agent_reads_metadata_off_the_loop_once(monkeypatch) -> None:
    """The cold User-Agent read goes to an executor; the warm hit stays in memory.

    ``_user_agent`` is cached, so only the first call reads the installed
    package metadata. That read must stay off the event loop, and every later
    call is a pure memory hit that must not pay an executor round-trip.
    """
    loop_thread = threading.get_ident()
    reads: list[int] = []
    real_version = youcom_tools.version

    def read_version(name: str) -> str:
        reads.append(threading.get_ident())
        return real_version(name)

    monkeypatch.setattr(youcom_tools, "version", read_version)
    youcom_tools._user_agent.cache_clear()
    try:
        cold = await youcom_tools._resolve_user_agent()
        assert reads, "the cold call must read the installed package metadata"
        assert all(thread != loop_thread for thread in reads), "the metadata read must not run on the event loop"

        dispatched: list[object] = []
        real_to_thread = asyncio.to_thread

        async def spy_to_thread(func, /, *args, **kwargs):
            dispatched.append(func)
            return await real_to_thread(func, *args, **kwargs)

        monkeypatch.setattr(asyncio, "to_thread", spy_to_thread)
        reads.clear()

        warm = await youcom_tools._resolve_user_agent()

        assert warm == cold
        assert not reads, "the warm call must not read the metadata again"
        assert not dispatched, "the warm call must not pay an executor round-trip"
    finally:
        youcom_tools._user_agent.cache_clear()
