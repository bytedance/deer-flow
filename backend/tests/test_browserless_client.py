"""Tests for Browserless community tools."""

from unittest.mock import MagicMock, patch

import json
import pytest

from deerflow.community.browserless.browserless_client import BrowserlessClient
from deerflow.community.browserless import tools


class TestBrowserlessClient:
    """Tests for the BrowserlessClient class."""

    def test_fetch_html_success(self):
        """fetch_html returns HTML content on success."""
        with patch("deerflow.community.browserless.browserless_client.httpx.Client") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__enter__.return_value = mock_ctx

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = "<html><body>Page content</body></html>"
            mock_resp.headers = {}
            mock_ctx.post.return_value = mock_resp

            client = BrowserlessClient(base_url="http://browserless:3000")
            result = client.fetch_html("https://example.com")

            assert result == "<html><body>Page content</body></html>"
            # Verify payload structure
            call_kwargs = mock_ctx.post.call_args.kwargs
            assert call_kwargs["json"]["url"] == "https://example.com"
            assert call_kwargs["json"]["waitUntil"] == "networkidle2"

    def test_fetch_html_empty_response(self):
        """fetch_html returns error for empty response."""
        with patch("deerflow.community.browserless.browserless_client.httpx.Client") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__enter__.return_value = mock_ctx

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = "   "
            mock_resp.headers = {}
            mock_ctx.post.return_value = mock_resp

            client = BrowserlessClient(base_url="http://browserless:3000")
            result = client.fetch_html("https://example.com")
            assert result == "Error: Browserless returned empty response"

    def test_fetch_html_http_error(self):
        """fetch_html returns error for non-200 status."""
        with patch("deerflow.community.browserless.browserless_client.httpx.Client") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__enter__.return_value = mock_ctx

            mock_resp = MagicMock()
            mock_resp.status_code = 500
            mock_resp.text = "Internal error"
            mock_resp.headers = {}
            mock_ctx.post.return_value = mock_resp

            client = BrowserlessClient(base_url="http://browserless:3000")
            result = client.fetch_html("https://example.com")
            assert "Error: Browserless HTTP 500" in result

    def test_fetch_html_timeout(self):
        """fetch_html returns timeout error."""
        with patch("deerflow.community.browserless.browserless_client.httpx.Client") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__enter__.return_value = mock_ctx
            import httpx
            mock_ctx.post.side_effect = httpx.TimeoutException("Timed out")

            client = BrowserlessClient(base_url="http://browserless:3000", timeout_s=10)
            result = client.fetch_html("https://example.com")
            assert "timed out" in result.lower() or "timeout" in result.lower()

    def test_fetch_html_with_token(self):
        """fetch_html includes token in payload when set."""
        with patch("deerflow.community.browserless.browserless_client.httpx.Client") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__enter__.return_value = mock_ctx

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = "<html>OK</html>"
            mock_resp.headers = {}
            mock_ctx.post.return_value = mock_resp

            client = BrowserlessClient(base_url="http://browserless:3000", token="my-token")
            client.fetch_html("https://example.com")

            payload = mock_ctx.post.call_args.kwargs["json"]
            assert payload["token"] == "my-token"


class TestBrowserlessTools:
    """Tests for the Browserless tool functions."""

    @patch("deerflow.community.browserless.tools._get_browserless_client")
    def test_web_fetch_tool_success(self, mock_get_client):
        """web_fetch_tool successfully fetches and extracts content."""
        mock_client = MagicMock()
        mock_client.fetch_html.return_value = "<html><body><article><h1>Title</h1><p>Content</p></article></body></html>"
        mock_get_client.return_value = mock_client

        with patch("deerflow.community.browserless.tools._get_tool_config", return_value=None):
            result = tools.web_fetch_tool.invoke("https://example.com/article")

        # Should be extracted markdown content
        assert "Error:" not in result

    @patch("deerflow.community.browserless.tools._get_browserless_client")
    def test_web_fetch_tool_error(self, mock_get_client):
        """web_fetch_tool returns error when fetch fails."""
        mock_client = MagicMock()
        mock_client.fetch_html.return_value = "Error: Browserless returned empty response"
        mock_get_client.return_value = mock_client

        with patch("deerflow.community.browserless.tools._get_tool_config", return_value=None):
            result = tools.web_fetch_tool.invoke("https://example.com")

        assert result.startswith("Error:")

    @patch("deerflow.community.browserless.tools._get_browserless_client")
    def test_web_fetch_tool_exception(self, mock_get_client):
        """web_fetch_tool returns error when client raises exception."""
        mock_client = MagicMock()
        mock_client.fetch_html.side_effect = Exception("Unexpected error")
        mock_get_client.return_value = mock_client

        with patch("deerflow.community.browserless.tools._get_tool_config", return_value=None):
            result = tools.web_fetch_tool.invoke("https://example.com")

        assert result.startswith("Error:")
