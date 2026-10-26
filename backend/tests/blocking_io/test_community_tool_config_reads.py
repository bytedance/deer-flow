"""Regression anchors: async community tools must resolve their config off the loop.

Agent runs execute on the Gateway event loop, so an async tool body runs there
too. ``get_app_config()`` stats and hashes ``config.yaml`` and
``extensions_config.json`` on every call and reparses them after an edit, so a
tool that resolved its config inline stalled every other run, request and
stream on the loop. ``image_search``, ``groundroute``, ``webz`` and ``youcom``
already offload it (``test_image_search.py``,
``test_groundroute_search_async.py``); these anchors cover every other async
community tool entry point.

Each case swaps the module's ``get_app_config`` for a loader that performs a
real file read and records the thread it ran on, so the strict gate fails if
the read lands on the loop and the recorded threads prove it ran at all. The
recorded count also pins the tools that now build their client from the same
read instead of resolving the config again. HTTP is stopped at
``httpx.AsyncClient.send`` and the browser session manager is a fake, so no
case touches the network.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import httpx
import pytest
from blockbuster import BlockingError

# Import every module up front: importing on the loop is itself blocking IO.
from deerflow.community.browser_automation import tools as browser_tools
from deerflow.community.browserless import tools as browserless_tools
from deerflow.community.crawl4ai import tools as crawl4ai_tools
from deerflow.community.firecrawl import tools as firecrawl_tools
from deerflow.community.infoquest import tools as infoquest_tools
from deerflow.community.jina_ai import tools as jina_tools
from deerflow.community.jsonify import tools as jsonify_tools
from deerflow.community.lightrag import tools as lightrag_tools
from deerflow.community.ragflow import tools as ragflow_tools
from deerflow.community.searxng import tools as searxng_tools
from deerflow.community.tavily import tools as tavily_tools

pytestmark = pytest.mark.asyncio

# A private literal target needs no DNS lookup; the backends point at the
# discard port and never receive a request because ``send`` is stubbed.
_URL = "http://127.0.0.1:9/page"
_EXTRAS = {
    "allow_private_addresses": True,
    "network_isolation_confirmed": True,
    "api_key": "test-key",
    "base_url": "http://127.0.0.1:9",
}


class _ConfigReads:
    """A ``get_app_config`` replacement that reads a real file per call."""

    def __init__(self) -> None:
        self.threads: list[int] = []

    def __call__(self) -> SimpleNamespace:
        # Record before reading: a read the gate stops on the loop still counts.
        self.threads.append(threading.get_ident())
        Path(__file__).read_text(encoding="utf-8")
        return SimpleNamespace(get_tool_config=lambda _name: SimpleNamespace(model_extra=dict(_EXTRAS)))


class _FakeSession:
    async def navigate(self, url: str) -> Any:
        return self._snapshot()

    async def snapshot(self) -> Any:
        return self._snapshot()

    async def click(self, ref: int) -> Any:
        return self._snapshot()

    async def type_text(self, ref: int, text: str, *, submit: bool = False) -> Any:
        return self._snapshot()

    async def back(self) -> Any:
        return self._snapshot()

    async def get_text(self, *, max_chars: int) -> str:
        return "page text"

    async def screenshot_bytes(self, **_kwargs: Any) -> bytes:
        raise RuntimeError("no screenshots in this anchor")

    @staticmethod
    def _snapshot() -> Any:
        return SimpleNamespace(url=_URL, title="Page", render=lambda: "[1] link: Page")


class _FakeSessionManager:
    def __init__(self) -> None:
        self.session = _FakeSession()

    def get_session(self, thread_id: str | None, **_kwargs: Any) -> _FakeSession:
        return self.session

    def release_session(self, thread_id: str | None, session: _FakeSession) -> None:
        pass

    @contextmanager
    def acquire_session(self, thread_id: str | None, **_kwargs: Any):
        yield self.session


def _runtime(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(context={"thread_id": "thread-1"}, state={"thread_data": {"outputs_path": str(tmp_path)}})


def _call(tool: Any, **kwargs: Any) -> Callable[[Path], Any]:
    return lambda _tmp_path: tool.ainvoke(kwargs)


def _with_runtime(tool: Any, **kwargs: Any) -> Callable[[Path], Any]:
    return lambda tmp_path: tool.coroutine(runtime=_runtime(tmp_path), tool_call_id="call-1", **kwargs)


# (module, entry point, config reads per call). Browser navigation also screens
# the URL through ``validate_browser_url`` in a worker, which reads its policy.
_CASES = [
    pytest.param(jina_tools, _call(jina_tools.web_fetch_tool, url=_URL), 1, id="jina_ai-web_fetch"),
    pytest.param(crawl4ai_tools, _call(crawl4ai_tools.web_fetch_tool, url=_URL), 1, id="crawl4ai-web_fetch"),
    pytest.param(browserless_tools, _call(browserless_tools.web_fetch_tool, url=_URL), 1, id="browserless-web_fetch"),
    pytest.param(browserless_tools, _with_runtime(browserless_tools.web_capture_tool, url=_URL), 1, id="browserless-web_capture"),
    pytest.param(tavily_tools, _call(tavily_tools.web_search_tool, query="q"), 1, id="tavily-web_search"),
    pytest.param(tavily_tools, _call(tavily_tools.web_fetch_tool, url=_URL), 1, id="tavily-web_fetch"),
    pytest.param(searxng_tools, _call(searxng_tools.web_search_tool, query="q"), 1, id="searxng-web_search"),
    pytest.param(firecrawl_tools, _call(firecrawl_tools.web_search_tool, query="q"), 1, id="firecrawl-web_search"),
    pytest.param(firecrawl_tools, _call(firecrawl_tools.web_fetch_tool, url=_URL), 1, id="firecrawl-web_fetch"),
    pytest.param(infoquest_tools, _call(infoquest_tools.web_search_tool, query="q"), 1, id="infoquest-web_search"),
    pytest.param(infoquest_tools, _call(infoquest_tools.web_fetch_tool, url=_URL), 1, id="infoquest-web_fetch"),
    pytest.param(infoquest_tools, _call(infoquest_tools.image_search_tool, query="q"), 1, id="infoquest-image_search"),
    pytest.param(jsonify_tools, _call(jsonify_tools.dataset_rows_tool, dataset="d"), 1, id="jsonify-dataset_rows"),
    pytest.param(ragflow_tools, lambda _tmp_path: ragflow_tools.knowledge_search_tool.coroutine("q", runtime=None), 1, id="ragflow-knowledge_search"),
    pytest.param(ragflow_tools, lambda _tmp_path: ragflow_tools.list_knowledge_bases_tool.coroutine(), 1, id="ragflow-list_knowledge_bases"),
    pytest.param(lightrag_tools, lambda _tmp_path: lightrag_tools.knowledge_search_tool.coroutine("q", runtime=None), 1, id="lightrag-knowledge_search"),
    pytest.param(browser_tools, _with_runtime(browser_tools.browser_navigate_tool, url=_URL), 2, id="browser-navigate"),
    pytest.param(browser_tools, _with_runtime(browser_tools.browser_snapshot_tool), 1, id="browser-snapshot"),
    pytest.param(browser_tools, _with_runtime(browser_tools.browser_click_tool, ref=1), 1, id="browser-click"),
    pytest.param(browser_tools, _with_runtime(browser_tools.browser_type_tool, ref=1, text="hi"), 1, id="browser-type"),
    pytest.param(browser_tools, _with_runtime(browser_tools.browser_get_text_tool), 2, id="browser-get_text"),
    pytest.param(browser_tools, _with_runtime(browser_tools.browser_back_tool), 1, id="browser-back"),
    pytest.param(browser_tools, _with_runtime(browser_tools.browser_screenshot_tool), 1, id="browser-screenshot"),
    pytest.param(
        browser_tools,
        lambda tmp_path: browser_tools.navigate_and_capture(thread_id="thread-1", url=_URL, outputs_path=tmp_path),
        2,
        id="browser-navigate_and_capture",
    ),
]


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    async def refuse(self, request: httpx.Request, **_kwargs: Any) -> httpx.Response:
        raise httpx.ConnectError("offline anchor", request=request)

    monkeypatch.setattr(httpx.AsyncClient, "send", refuse)
    monkeypatch.setattr(browser_tools, "get_browser_session_manager", lambda: _FakeSessionManager())


@pytest.mark.parametrize(("module", "invoke", "expected_reads"), _CASES)
async def test_async_community_tool_resolves_config_off_the_loop(module: ModuleType, invoke: Callable[[Path], Any], expected_reads: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reads = _ConfigReads()
    monkeypatch.setattr(module, "get_app_config", reads)

    try:
        await invoke(tmp_path)
    except Exception:
        # Tools without an error boundary surface the stubbed network failure;
        # only where and how often the config was read matters here.
        pass

    assert len(reads.threads) == expected_reads
    assert threading.get_ident() not in reads.threads


async def test_blocking_probe_inline_config_read_actually_trips_the_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Meta-check: the loader reached from tool code on the loop is caught by the gate.

    The gate only flags IO whose stack passes through ``deerflow.*``, so the
    probe goes through a tool module's own sync config helper.
    """
    reads = _ConfigReads()
    monkeypatch.setattr(crawl4ai_tools, "get_app_config", reads)

    with pytest.raises(BlockingError):
        crawl4ai_tools._get_tool_config("web_fetch")
    assert reads.threads == [threading.get_ident()]
