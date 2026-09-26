"""Tests for SearXNG community tools."""

import json
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from deerflow.community.searxng import tools
from deerflow.community.searxng.searxng_client import SearxngClient


class AsyncMock(MagicMock):
    """Mock that supports async call."""

    async def __call__(self, *args, **kwargs):
        return super().__call__(*args, **kwargs)


@contextmanager
def _searxng_pages(pages: dict[int, list[dict]]):
    """Patch httpx so request page N answers with ``pages[N]``.

    A page that was not given answers with an empty result set, which is what a
    real instance does once the query is exhausted.
    """
    with patch("deerflow.community.searxng.searxng_client.httpx.AsyncClient") as mock_cls:
        mock_ctx = MagicMock()
        mock_cls.return_value.__aenter__.return_value = mock_ctx

        def _get(url, params=None, headers=None):
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"results": pages.get(params["pageno"], [])}
            mock_resp.raise_for_status.return_value = None
            return mock_resp

        mock_ctx.get = AsyncMock(side_effect=_get)
        yield mock_ctx


@pytest.mark.asyncio
class TestSearxngClient:
    """Tests for the SearxngClient class."""

    async def test_search_success(self):
        """Search returns normalized results."""
        results_data = {
            "results": [
                {"title": "Page 1", "url": "https://example.com/1", "content": "Snippet 1"},
                {"title": "Page 2", "url": "https://example.com/2", "content": "Snippet 2"},
            ]
        }

        with patch("deerflow.community.searxng.searxng_client.httpx.AsyncClient") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_ctx

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = results_data
            mock_resp.raise_for_status.return_value = None
            mock_ctx.get = AsyncMock(return_value=mock_resp)

            client = SearxngClient(base_url="http://searxng:8080")
            result = await client.search("test query", max_results=5)

            assert len(result) == 2
            assert result[0]["title"] == "Page 1"
            assert result[1]["url"] == "https://example.com/2"

    async def test_search_empty_results(self):
        """Search returns empty list when no results."""
        with patch("deerflow.community.searxng.searxng_client.httpx.AsyncClient") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_ctx

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"results": []}
            mock_resp.raise_for_status.return_value = None
            mock_ctx.get = AsyncMock(return_value=mock_resp)

            client = SearxngClient(base_url="http://searxng:8080")
            result = await client.search("empty query")
            assert result == []

    async def test_search_http_error(self):
        """Search raises on HTTP error."""
        with patch("deerflow.community.searxng.searxng_client.httpx.AsyncClient") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_ctx

            import httpx

            mock_resp = MagicMock()
            mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError("403 Forbidden", request=MagicMock(), response=MagicMock())
            mock_ctx.get = AsyncMock(return_value=mock_resp)

            client = SearxngClient(base_url="http://searxng:8080")
            with pytest.raises(httpx.HTTPStatusError):
                await client.search("blocked query")

    async def test_search_request_error(self):
        """Search raises on request error."""
        with patch("deerflow.community.searxng.searxng_client.httpx.AsyncClient") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_ctx

            import httpx

            mock_ctx.get = AsyncMock(side_effect=httpx.RequestError("Connection refused"))

            client = SearxngClient(base_url="http://searxng:8080")
            with pytest.raises(httpx.RequestError):
                await client.search("unreachable query")

    async def test_search_with_categories(self):
        """Search passes categories parameter."""
        with patch("deerflow.community.searxng.searxng_client.httpx.AsyncClient") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_ctx

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"results": []}
            mock_resp.raise_for_status.return_value = None
            mock_ctx.get = AsyncMock(return_value=mock_resp)

            client = SearxngClient(base_url="http://searxng:8080")
            await client.search("test", categories=["news", "science"])

            call_kwargs = mock_ctx.get.call_args.kwargs
            assert call_kwargs["params"]["categories"] == "news,science"

    async def test_search_with_time_range(self):
        """Search passes a native relative time range."""
        with patch("deerflow.community.searxng.searxng_client.httpx.AsyncClient") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_ctx

            mock_resp = MagicMock()
            mock_resp.json.return_value = {"results": []}
            mock_resp.raise_for_status.return_value = None
            mock_ctx.get = AsyncMock(return_value=mock_resp)

            client = SearxngClient(base_url="http://searxng:8080")
            await client.search("latest release", time_range="month")

            params = mock_ctx.get.call_args.kwargs["params"]
            assert params["time_range"] == "month"

    async def test_search_without_time_range_omits_parameter(self):
        """The default request shape remains unchanged."""
        with patch("deerflow.community.searxng.searxng_client.httpx.AsyncClient") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_ctx

            mock_resp = MagicMock()
            mock_resp.json.return_value = {"results": []}
            mock_resp.raise_for_status.return_value = None
            mock_ctx.get = AsyncMock(return_value=mock_resp)

            client = SearxngClient(base_url="http://searxng:8080")
            await client.search("stable documentation")

            params = mock_ctx.get.call_args.kwargs["params"]
            assert "time_range" not in params

    async def test_search_collects_results_across_pages(self):
        """A max_results larger than one page is collected by walking pageno.

        SearXNG's search API has no `limit` parameter -- /search answers with one
        page (the instance's results_per_page, 10 by default) and ignores a limit
        it is handed -- so a configured max_results above a page used to be
        silently capped at whatever the first page held.
        """
        pages = {
            1: [{"title": f"page1-{i}", "url": f"https://example.com/1/{i}", "content": "c"} for i in range(3)],
            2: [{"title": f"page2-{i}", "url": f"https://example.com/2/{i}", "content": "c"} for i in range(3)],
        }

        with _searxng_pages(pages) as mock_ctx:
            client = SearxngClient(base_url="http://searxng:8080")
            result = await client.search("test query", max_results=5)

        assert len(result) == 5
        assert [call.kwargs["params"]["pageno"] for call in mock_ctx.get.call_args_list] == [1, 2]

    async def test_search_makes_one_request_when_a_page_is_enough(self):
        """The default max_results still costs exactly one request."""
        rows = [{"title": f"r{i}", "url": f"https://example.com/{i}", "content": "c"} for i in range(10)]

        with _searxng_pages({1: rows}) as mock_ctx:
            client = SearxngClient(base_url="http://searxng:8080")
            result = await client.search("test query", max_results=5)

        assert len(result) == 5
        assert mock_ctx.get.call_count == 1

    async def test_search_stops_when_a_page_adds_nothing_new(self):
        """A repeating page ends the walk instead of duplicating results."""
        repeated = [{"title": f"r{i}", "url": f"https://example.com/{i}", "content": "c"} for i in range(2)]

        with _searxng_pages({1: repeated, 2: repeated, 3: repeated}) as mock_ctx:
            client = SearxngClient(base_url="http://searxng:8080")
            result = await client.search("test query", max_results=50)

        assert len(result) == 2
        assert mock_ctx.get.call_count == 2

    async def test_search_never_sends_the_unsupported_limit_parameter(self):
        """`limit` is not part of the SearXNG search API, so it is not sent."""
        with _searxng_pages({1: [{"title": "t", "url": "https://example.com/1", "content": "c"}]}) as mock_ctx:
            client = SearxngClient(base_url="http://searxng:8080")
            await client.search("test query", max_results=20)

        assert "limit" not in mock_ctx.get.call_args_list[0].kwargs["params"]


@pytest.mark.asyncio
class TestSearxngTools:
    """Tests for the SearXNG tool functions."""

    @patch("deerflow.community.searxng.tools._get_searxng_client")
    async def test_web_search_tool_success(self, mock_get_client):
        """web_search_tool returns JSON results."""
        mock_client = MagicMock()
        mock_client.search = AsyncMock(
            return_value=[
                {"title": "Result 1", "url": "https://example.com/1", "content": "Desc 1"},
            ]
        )
        mock_get_client.return_value = mock_client

        with patch("deerflow.community.searxng.tools._get_tool_config", return_value=None):
            result = await tools.web_search_tool.ainvoke("test query")

        data = json.loads(result)
        assert len(data) == 1
        assert data[0]["title"] == "Result 1"

    @patch("deerflow.community.searxng.tools._get_searxng_client")
    async def test_web_search_tool_error(self, mock_get_client):
        """web_search_tool handles errors gracefully."""
        mock_client = MagicMock()
        mock_client.search = AsyncMock(side_effect=Exception("API error"))
        mock_get_client.return_value = mock_client

        with patch("deerflow.community.searxng.tools._get_tool_config", return_value=None):
            result = await tools.web_search_tool.ainvoke("test query")

        data = json.loads(result)
        assert "error" in data

    @patch("deerflow.community.searxng.tools._get_searxng_client")
    async def test_web_search_tool_with_max_results(self, mock_get_client):
        """web_search_tool respects max_results config."""
        mock_client = MagicMock()
        # Return 10 results; the tool should slice to max_results=3
        mock_client.search = AsyncMock(return_value=[{"title": f"Result {i}", "url": f"https://example.com/{i}", "content": f"Desc {i}"} for i in range(10)])
        mock_get_client.return_value = mock_client

        with patch("deerflow.community.searxng.tools._get_tool_config", return_value={"max_results": "3"}):
            await tools.web_search_tool.ainvoke("test query")

        # Verify that search was called with max_results=3 (coerced from string)
        mock_client.search.assert_called_once()
        call_kwargs = mock_client.search.call_args.kwargs
        assert call_kwargs["max_results"] == 3

    @patch("deerflow.community.searxng.tools._get_searxng_client")
    async def test_web_search_tool_unparseable_max_results_uses_default(self, mock_get_client):
        """A max_results the config cannot give as a number falls back to the default."""
        mock_client = MagicMock()
        mock_client.search = AsyncMock(return_value=[])
        mock_get_client.return_value = mock_client

        # ``max_results:`` left blank in config.yaml loads as None; a word is a
        # typo an operator can just as easily make. Neither is a reason to stop
        # searching -- every sibling provider falls back to the default.
        for raw in (None, "many"):
            with patch("deerflow.community.searxng.tools._get_tool_config", return_value={"max_results": raw}):
                result = await tools.web_search_tool.ainvoke("test query")

            assert "error" not in json.loads(result), f"max_results={raw!r} failed the whole call"
            mock_client.search.assert_called_once_with("test query", max_results=5)
            mock_client.search.reset_mock()

    @patch("deerflow.community.searxng.tools._get_searxng_client")
    async def test_web_search_tool_forwards_time_range(self, mock_get_client):
        """web_search_tool forwards the requested relative time range."""
        mock_client = MagicMock()
        mock_client.search = AsyncMock(return_value=[])
        mock_get_client.return_value = mock_client

        with patch("deerflow.community.searxng.tools._get_tool_config", return_value=None):
            await tools.web_search_tool.ainvoke({"query": "latest release", "time_range": "week"})

        mock_client.search.assert_called_once_with("latest release", max_results=5, time_range="week")
