"""Tests for SearXNG community tools."""

from unittest.mock import MagicMock, patch

import json
import pytest

from deerflow.community.searxng.searxng_client import SearxngClient
from deerflow.community.searxng import tools


class TestSearxngClient:
    """Tests for the SearxngClient class."""

    def test_search_success(self):
        """Search returns normalized results."""
        results_data = {
            "results": [
                {"title": "Page 1", "url": "https://example.com/1", "content": "Snippet 1"},
                {"title": "Page 2", "url": "https://example.com/2", "content": "Snippet 2"},
            ]
        }

        with patch("deerflow.community.searxng.searxng_client.httpx.Client") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__enter__.return_value = mock_ctx

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = results_data
            mock_ctx.get.return_value = mock_resp

            client = SearxngClient(base_url="http://searxng:8080")
            result = client.search("test query", max_results=5)

            assert len(result) == 2
            assert result[0]["title"] == "Page 1"
            assert result[1]["url"] == "https://example.com/2"

    def test_search_empty_results(self):
        """Search returns empty list when no results."""
        with patch("deerflow.community.searxng.searxng_client.httpx.Client") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__enter__.return_value = mock_ctx

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"results": []}
            mock_ctx.get.return_value = mock_resp

            client = SearxngClient(base_url="http://searxng:8080")
            result = client.search("empty query")
            assert result == []

    def test_search_http_error(self):
        """Search raises on HTTP error."""
        with patch("deerflow.community.searxng.searxng_client.httpx.Client") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__enter__.return_value = mock_ctx
            # httpx.HTTPStatusError on raise_for_status
            import httpx
            mock_resp = MagicMock()
            mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                "403 Forbidden", request=MagicMock(), response=MagicMock()
            )
            mock_ctx.get.return_value = mock_resp

            client = SearxngClient(base_url="http://searxng:8080")
            with pytest.raises(httpx.HTTPStatusError):
                client.search("blocked query")

    def test_fetch_success(self):
        """Fetch returns HTML content."""
        with patch("deerflow.community.searxng.searxng_client.httpx.Client") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__enter__.return_value = mock_ctx

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = "<html><body>Hello</body></html>"
            mock_ctx.get.return_value = mock_resp

            client = SearxngClient(base_url="http://searxng:8080")
            result = client.fetch("https://example.com")
            assert result == "<html><body>Hello</body></html>"

    def test_fetch_error(self):
        """Fetch returns error string on exception."""
        with patch("deerflow.community.searxng.searxng_client.httpx.Client") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__enter__.return_value = mock_ctx
            mock_ctx.get.side_effect = Exception("Connection refused")

            client = SearxngClient(base_url="http://searxng:8080")
            result = client.fetch("https://example.com")
            assert result.startswith("Error:")


class TestSearxngTools:
    """Tests for the SearXNG tool functions."""

    @patch("deerflow.community.searxng.tools._get_searxng_client")
    def test_web_search_tool_success(self, mock_get_client):
        """web_search_tool returns JSON results."""
        mock_client = MagicMock()
        mock_client.search.return_value = [
            {"title": "Result 1", "url": "https://example.com/1", "content": "Desc 1"},
        ]
        mock_get_client.return_value = mock_client

        with patch("deerflow.community.searxng.tools._get_tool_config", return_value=None):
            result = tools.web_search_tool.invoke("test query")

        data = json.loads(result)
        assert len(data) == 1
        assert data[0]["title"] == "Result 1"

    @patch("deerflow.community.searxng.tools._get_searxng_client")
    def test_web_search_tool_error(self, mock_get_client):
        """web_search_tool handles errors gracefully."""
        mock_client = MagicMock()
        mock_client.search.side_effect = Exception("API error")
        mock_get_client.return_value = mock_client

        with patch("deerflow.community.searxng.tools._get_tool_config", return_value=None):
            result = tools.web_search_tool.invoke("test query")

        data = json.loads(result)
        assert "error" in data
