"""Tests for SearXNG community tools."""

import json
from unittest.mock import MagicMock, patch

import pytest

from deerflow.community.searxng import tools
from deerflow.community.searxng.searxng_client import SearxngClient


class AsyncMock(MagicMock):
    """Mock that supports async call."""

    async def __call__(self, *args, **kwargs):
        return super().__call__(*args, **kwargs)


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

    @staticmethod
    def _page_response(entries):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"results": entries}
        resp.raise_for_status.return_value = None
        return resp

    @staticmethod
    def _page_entries(page_number, count=10):
        return [{"title": f"P{page_number} Result {i}", "url": f"https://example.com/p{page_number}/{i}", "content": f"Snippet {page_number}-{i}"} for i in range(count)]

    async def test_search_paginates_until_max_results(self):
        """max_results beyond one page size walks pageno instead of truncating."""
        with patch("deerflow.community.searxng.searxng_client.httpx.AsyncClient") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_ctx
            # Simulate a SearXNG instance with results_per_page=10: every page
            # returns 10 fresh results.
            mock_ctx.get = AsyncMock(side_effect=[self._page_response(self._page_entries(1)), self._page_response(self._page_entries(2))])

            client = SearxngClient(base_url="http://searxng:8080")
            result = await client.search("broad topic", max_results=20)

            assert len(result) == 20
            assert mock_ctx.get.call_count == 2
            first_params = mock_ctx.get.call_args_list[0].kwargs["params"]
            second_params = mock_ctx.get.call_args_list[1].kwargs["params"]
            assert first_params["pageno"] == 1
            assert second_params["pageno"] == 2
            for call in mock_ctx.get.call_args_list:
                assert "limit" not in call.kwargs["params"]

    async def test_search_stops_on_empty_page(self):
        """Pagination stops once a page comes back empty."""
        with patch("deerflow.community.searxng.searxng_client.httpx.AsyncClient") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_ctx
            mock_ctx.get = AsyncMock(side_effect=[self._page_response(self._page_entries(1)), self._page_response([])])

            client = SearxngClient(base_url="http://searxng:8080")
            result = await client.search("narrow topic", max_results=20)

            assert len(result) == 10
            assert mock_ctx.get.call_count == 2

    async def test_search_stops_when_page_adds_nothing_new(self):
        """Pagination stops when a page only repeats already-collected results."""
        with patch("deerflow.community.searxng.searxng_client.httpx.AsyncClient") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_ctx
            page_one = self._page_entries(1)
            mock_ctx.get = AsyncMock(side_effect=[self._page_response(page_one), self._page_response(list(page_one))])

            client = SearxngClient(base_url="http://searxng:8080")
            result = await client.search("repetitive topic", max_results=20)

            assert len(result) == 10
            assert mock_ctx.get.call_count == 2

    async def test_search_without_max_results_fetches_single_page(self):
        """Without a cap the client keeps the single-request shape."""
        with patch("deerflow.community.searxng.searxng_client.httpx.AsyncClient") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_ctx
            mock_ctx.get = AsyncMock(side_effect=[self._page_response(self._page_entries(1)), self._page_response(self._page_entries(2))])

            client = SearxngClient(base_url="http://searxng:8080")
            result = await client.search("uncapped query", max_results=0)

            assert len(result) == 10
            assert mock_ctx.get.call_count == 1


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
    async def test_web_search_tool_forwards_time_range(self, mock_get_client):
        """web_search_tool forwards the requested relative time range."""
        mock_client = MagicMock()
        mock_client.search = AsyncMock(return_value=[])
        mock_get_client.return_value = mock_client

        with patch("deerflow.community.searxng.tools._get_tool_config", return_value=None):
            await tools.web_search_tool.ainvoke({"query": "latest release", "time_range": "week"})

        mock_client.search.assert_called_once_with("latest release", max_results=5, time_range="week")
