"""Tests for SearXNG community tools."""

from unittest.mock import MagicMock, patch

import json
import pytest

from deerflow.community.searxng.searxng_client import SearxngClient
from deerflow.community.searxng import tools


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
            mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                "403 Forbidden", request=MagicMock(), response=MagicMock()
            )
            mock_ctx.get = AsyncMock(return_value=mock_resp)

            client = SearxngClient(base_url="http://searxng:8080")
            with pytest.raises(httpx.HTTPStatusError):
                await client.search("blocked query")

    async def test_fetch_success(self):
        """Fetch returns HTML content."""
        with patch("deerflow.community.searxng.searxng_client.httpx.AsyncClient") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_ctx

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = "<html><body>Hello</body></html>"
            mock_resp.raise_for_status.return_value = None
            mock_ctx.get = AsyncMock(return_value=mock_resp)

            client = SearxngClient(base_url="http://searxng:8080")
            result = await client.fetch("https://example.com")
            assert result == "<html><body>Hello</body></html>"

    async def test_fetch_error(self):
        """Fetch returns error string on exception."""
        with patch("deerflow.community.searxng.searxng_client.httpx.AsyncClient") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_ctx
            mock_ctx.get = AsyncMock(side_effect=Exception("Connection refused"))

            client = SearxngClient(base_url="http://searxng:8080")
            result = await client.fetch("https://example.com")
            assert result.startswith("Error:")


@pytest.mark.asyncio
class TestSearxngTools:
    """Tests for the SearXNG tool functions."""

    @patch("deerflow.community.searxng.tools._get_searxng_client")
    async def test_web_search_tool_success(self, mock_get_client):
        """web_search_tool returns JSON results."""
        mock_client = MagicMock()
        mock_client.search = AsyncMock(return_value=[
            {"title": "Result 1", "url": "https://example.com/1", "content": "Desc 1"},
        ])
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
