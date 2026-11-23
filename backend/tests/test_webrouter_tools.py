"""Unit tests for the WebRouter community web search and fetch tools.

The tools run the real ``web_router.AsyncWebRouter``. Each backend is pinned in
the tool config, and an ``httpx.MockTransport`` handed to that backend through
WebRouter's ``provider_config`` stands in for its API, so the tests check the
request WebRouter sends and the output DeerFlow builds from the reply.
"""

import asyncio
import json
import sys
import threading
from unittest.mock import MagicMock, patch

import httpx
import pytest

from deerflow.community.webrouter import tools as webrouter_tools

web_router = pytest.importorskip("web_router")

_MODULE = "deerflow.community.webrouter.tools"

pytestmark = pytest.mark.asyncio


@pytest.fixture
def tool_config(monkeypatch):
    # The Brave backend needs a key; WebRouter reads it from the environment.
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "test-brave-key")
    with patch(f"{_MODULE}.get_app_config") as mock:
        tool_config = MagicMock()
        tool_config.model_extra = {}
        mock.return_value.get_tool_config.return_value = tool_config
        yield tool_config.model_extra


class _Backend:
    """A fake backend API: records each request and answers with a canned reply."""

    def __init__(self, reply: httpx.Response) -> None:
        self.reply = reply
        self.requests: list[httpx.Request] = []
        self.closed = 0
        self._real_router = web_router.AsyncWebRouter

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.reply

    def build(self, provider: str):
        """A real router whose ``provider`` backend talks to this fake API, counting closes."""
        router = self._real_router(provider, provider_config={provider: {"transport": httpx.MockTransport(self)}})
        close = router.aclose

        async def counted_close() -> None:
            self.closed += 1
            await close()

        router.aclose = counted_close
        return router

    def install(self):
        return patch.object(web_router, "AsyncWebRouter", self.build)


def _brave(hits: list[dict] | None = None, status: int = 200) -> _Backend:
    return _Backend(httpx.Response(status, json={"web": {"results": hits if hits is not None else []}}))


def _hit(n: int, **fields) -> dict:
    return {"url": f"https://example.com/{n}", "title": f"Result {n}", "description": f"Snippet {n}", **fields}


async def _search(backend: _Backend, tool_config: dict, **args) -> dict:
    tool_config.setdefault("provider", "brave")
    with backend.install():
        output = await webrouter_tools.web_search_tool.ainvoke({"query": "python tutorial", **args})
    return json.loads(output)


def _jina(data: dict, status: int = 200) -> _Backend:
    return _Backend(httpx.Response(status, json={"code": status, "data": data}))


async def _fetch(backend: _Backend, tool_config: dict, url: str = "https://example.com/post") -> str:
    tool_config.setdefault("provider", "jina")
    with backend.install():
        return await webrouter_tools.web_fetch_tool.ainvoke({"url": url})


class TestWebSearchTool:
    async def test_returns_normalized_results(self, tool_config):
        backend = _brave([_hit(1), _hit(2)])

        parsed = await _search(backend, tool_config)

        assert parsed == {
            "query": "python tutorial",
            "provider": "brave",
            "total_results": 2,
            "results": [
                {"title": "Result 1", "url": "https://example.com/1", "snippet": "Snippet 1"},
                {"title": "Result 2", "url": "https://example.com/2", "snippet": "Snippet 2"},
            ],
        }
        (request,) = backend.requests
        assert request.url.host == "api.search.brave.com"
        assert request.url.params["q"] == "python tutorial"
        assert request.url.params["count"] == "5"
        assert request.headers["X-Subscription-Token"] == "test-brave-key"
        assert backend.closed == 1

    async def test_default_provider_is_auto(self, tool_config):
        built: list[str] = []

        def refuse(provider: str):
            built.append(provider)
            raise RuntimeError("stop before any request")

        with patch.object(web_router, "AsyncWebRouter", refuse):
            output = await webrouter_tools.web_search_tool.ainvoke({"query": "q"})

        assert built == ["auto"]
        assert json.loads(output)["error"] == "WebRouter search failed: stop before any request"

    async def test_cancel_during_construction_closes_the_router(self, tool_config):
        tool_config["provider"] = "brave"
        backend = _brave([_hit(1)])
        entered, release = threading.Event(), threading.Event()

        def slow_build(provider: str):
            entered.set()
            release.wait(5)
            return backend.build(provider)

        with patch.object(web_router, "AsyncWebRouter", slow_build):
            task = asyncio.create_task(webrouter_tools.web_search_tool.ainvoke({"query": "q"}))
            assert await asyncio.to_thread(entered.wait, 5)
            task.cancel()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task

        assert backend.closed == 1
        assert backend.requests == []

    async def test_max_results_from_config_and_caller(self, tool_config):
        tool_config["max_results"] = 2
        backend = _brave([_hit(n) for n in range(8)])

        assert (await _search(backend, tool_config))["total_results"] == 2
        assert (await _search(backend, tool_config, max_results=3))["total_results"] == 3
        assert [request.url.params["count"] for request in backend.requests] == ["2", "3"]

    async def test_time_range_reaches_the_backend(self, tool_config):
        backend = _brave([_hit(1)])

        await _search(backend, tool_config, time_range="week")

        assert backend.requests[0].url.params["freshness"] == "pw"

    async def test_private_result_url_is_screened(self, tool_config):
        parsed = await _search(_brave([_hit(1, url="http://169.254.169.254/latest/meta-data/")]), tool_config)

        assert parsed["results"][0]["url"] == ""

    async def test_empty_results_return_error_json(self, tool_config):
        parsed = await _search(_brave([]), tool_config)

        assert parsed == {"error": "No results found", "query": "python tutorial"}

    async def test_backend_error_returns_error_json_and_closes_the_router(self, tool_config):
        backend = _brave(status=500)

        parsed = await _search(backend, tool_config)

        assert parsed["query"] == "python tutorial"
        assert parsed["error"].startswith("WebRouter search failed: ")
        assert backend.closed == 1

    async def test_missing_package_returns_install_hint(self, tool_config):
        with patch.dict(sys.modules, {"web_router": None}):
            output = await webrouter_tools.web_search_tool.ainvoke({"query": "q"})

        assert json.loads(output)["error"] == "webrouter is not installed. Run: cd backend && uv sync --extra webrouter"


class TestWebFetchTool:
    async def test_returns_title_and_markdown(self, tool_config):
        backend = _jina({"url": "https://example.com/post", "title": "Example", "content": "Hello world"})

        result = await _fetch(backend, tool_config)

        assert result == "# Example\n\nHello world"
        (request,) = backend.requests
        assert request.url.host == "r.jina.ai"
        assert json.loads(request.content) == {"url": "https://example.com/post"}

    async def test_truncates_content_and_falls_back_to_the_url_as_title(self, tool_config):
        result = await _fetch(_jina({"content": "x" * 10000}), tool_config)

        assert result == "# https://example.com/post\n\n" + "x" * 4096

    async def test_empty_page_returns_error(self, tool_config):
        result = await _fetch(_jina({"title": "T", "content": ""}), tool_config)

        assert result == "Error: No content found"

    async def test_backend_error_returns_error_string(self, tool_config):
        result = await _fetch(_jina({}, status=500), tool_config)

        assert result.startswith("Error: WebRouter fetch failed: ")

    @pytest.mark.parametrize("url", ["http://127.0.0.1:8080/admin", "file:///etc/passwd", "example.com"])
    async def test_rejects_non_public_url_without_a_request(self, tool_config, url):
        backend = _jina({"content": "x"})

        result = await _fetch(backend, tool_config, url=url)

        assert result.startswith("Error: ")
        assert backend.requests == []
