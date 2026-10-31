"""Keep network I/O on the event loop and config/metadata reads off it.

Cache the User-Agent so sequential warm calls need no metadata read or
executor dispatch.
"""

import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from deerflow.community.perplexity import tools as perplexity_tools

pytestmark = pytest.mark.asyncio


def _patch_transport(monkeypatch, request_threads: list[int], clients: list[str]) -> None:
    """Answer every request locally and record the thread that served it."""

    def respond(request: httpx.Request) -> httpx.Response:
        request_threads.append(threading.get_ident())
        return httpx.Response(200, json={"id": "req-1", "results": []})

    transport = httpx.MockTransport(respond)

    def async_client(**kwargs):
        clients.append("AsyncClient")
        return httpx.AsyncClient(transport=transport, **kwargs)

    def sync_client(**kwargs):
        clients.append("Client")
        return httpx.Client(transport=transport, **kwargs)

    monkeypatch.setattr(
        perplexity_tools,
        "httpx",
        SimpleNamespace(
            AsyncClient=async_client,
            Client=sync_client,
            HTTPStatusError=httpx.HTTPStatusError,
            HTTPError=httpx.HTTPError,
        ),
    )


def _patch_config(monkeypatch, load_config=None) -> None:
    def config():
        return SimpleNamespace(get_tool_config=lambda _name: SimpleNamespace(model_extra={"api_key": "synthetic-key"}))

    monkeypatch.setattr(perplexity_tools, "get_app_config", load_config or config)


async def test_perplexity_search_request_runs_on_the_event_loop(monkeypatch) -> None:
    """The request is awaited on the loop, not dispatched to an executor thread."""
    request_threads: list[int] = []
    clients: list[str] = []
    loop_thread = threading.get_ident()
    _patch_transport(monkeypatch, request_threads, clients)
    _patch_config(monkeypatch)

    result = await perplexity_tools.web_search_tool.ainvoke({"query": "vector databases"})

    assert '"error": "No results found; try a broader query or relax the search filters"' in result
    assert request_threads, "the request must reach the transport"
    assert all(thread == loop_thread for thread in request_threads)
    assert clients == ["AsyncClient"], "the request must go out through the async client"


async def test_perplexity_config_lookup_does_not_block_loop(monkeypatch) -> None:
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

    result = await perplexity_tools.web_search_tool.ainvoke({"query": "vector databases"})

    assert '"error": "No results found; try a broader query or relax the search filters"' in result
    assert config_threads, "config lookup must run"
    assert all(thread != loop_thread for thread in config_threads)
    assert clients == ["AsyncClient"], "the request must go out through the async client"


async def test_perplexity_user_agent_reads_metadata_off_the_loop_once(monkeypatch) -> None:
    """The cold User-Agent read goes to an executor; the warm hit stays in memory."""
    loop_thread = threading.get_ident()
    reads: list[int] = []
    real_version = perplexity_tools.version

    def read_version(name: str) -> str:
        reads.append(threading.get_ident())
        return real_version(name)

    monkeypatch.setattr(perplexity_tools, "version", read_version)
    perplexity_tools._user_agent.cache_clear()
    try:
        cold = await perplexity_tools._resolve_user_agent()
        assert reads, "the cold call must read the installed package metadata"
        assert all(thread != loop_thread for thread in reads), "the metadata read must not run on the event loop"

        dispatched: list[object] = []
        real_to_thread = asyncio.to_thread

        async def spy_to_thread(func, /, *args, **kwargs):
            dispatched.append(func)
            return await real_to_thread(func, *args, **kwargs)

        monkeypatch.setattr(asyncio, "to_thread", spy_to_thread)
        reads.clear()

        warm = await perplexity_tools._resolve_user_agent()

        assert warm == cold
        assert not reads, "the warm call must not read the metadata again"
        assert not dispatched, "the warm call must not pay an executor round-trip"
    finally:
        perplexity_tools._user_agent.cache_clear()
