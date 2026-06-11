"""Tests for Browserless community tools."""

from unittest.mock import MagicMock, patch

import pytest

from deerflow.community.browserless import tools
from deerflow.community.browserless.browserless_client import BrowserlessClient


class AsyncMock(MagicMock):
    """Mock that supports async call."""

    async def __call__(self, *args, **kwargs):
        return super().__call__(*args, **kwargs)


@pytest.mark.asyncio
class TestBrowserlessClient:
    """Tests for the BrowserlessClient class."""

    async def test_fetch_html_success(self):
        """fetch_html returns HTML content on success."""
        with patch("deerflow.community.browserless.browserless_client.httpx.AsyncClient") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_ctx

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = "<html><body>Page content</body></html>"
            mock_resp.headers = {}
            mock_ctx.post = AsyncMock(return_value=mock_resp)

            client = BrowserlessClient(base_url="http://browserless:3000")
            result = await client.fetch_html("https://example.com")

            assert result == "<html><body>Page content</body></html>"
            call_kwargs = mock_ctx.post.call_args.kwargs
            assert call_kwargs["json"]["url"] == "https://example.com"
            assert "waitUntil" not in call_kwargs["json"]
            assert "gotoTimeout" not in call_kwargs["json"]
            assert "bestAttempt" not in call_kwargs["json"]

    async def test_fetch_html_empty_response(self):
        """fetch_html returns error for empty response."""
        with patch("deerflow.community.browserless.browserless_client.httpx.AsyncClient") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_ctx

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = "   "
            mock_resp.headers = {}
            mock_ctx.post = AsyncMock(return_value=mock_resp)

            client = BrowserlessClient(base_url="http://browserless:3000")
            result = await client.fetch_html("https://example.com")
            assert result == "Error: Browserless returned empty response"

    async def test_fetch_html_http_error(self):
        """fetch_html returns error for non-200 status."""
        with patch("deerflow.community.browserless.browserless_client.httpx.AsyncClient") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_ctx

            mock_resp = MagicMock()
            mock_resp.status_code = 500
            mock_resp.text = "Internal error"
            mock_resp.headers = {}
            mock_ctx.post = AsyncMock(return_value=mock_resp)

            client = BrowserlessClient(base_url="http://browserless:3000")
            result = await client.fetch_html("https://example.com")
            assert "Error: Browserless HTTP 500" in result

    async def test_fetch_html_timeout(self):
        """fetch_html returns timeout error."""
        with patch("deerflow.community.browserless.browserless_client.httpx.AsyncClient") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_ctx
            import httpx

            mock_ctx.post = AsyncMock(side_effect=httpx.TimeoutException("Timed out"))

            client = BrowserlessClient(base_url="http://browserless:3000", timeout_s=10)
            result = await client.fetch_html("https://example.com")
            assert "timed out" in result.lower() or "timeout" in result.lower()

    async def test_fetch_html_with_token(self):
        """fetch_html includes token in payload when set."""
        with patch("deerflow.community.browserless.browserless_client.httpx.AsyncClient") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_ctx

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = "<html>OK</html>"
            mock_resp.headers = {}
            mock_ctx.post = AsyncMock(return_value=mock_resp)

            client = BrowserlessClient(base_url="http://browserless:3000", token="my-token")
            await client.fetch_html("https://example.com")

            payload = mock_ctx.post.call_args.kwargs["json"]
            assert payload["token"] == "my-token"

    async def test_fetch_html_with_wait_for_selector(self):
        """fetch_html sends waitForSelector when selector is set."""
        with patch("deerflow.community.browserless.browserless_client.httpx.AsyncClient") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_ctx

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = "<html>OK</html>"
            mock_resp.headers = {}
            mock_ctx.post = AsyncMock(return_value=mock_resp)

            client = BrowserlessClient(base_url="http://browserless:3000")
            await client.fetch_html("https://example.com", wait_for_selector="article")

            payload = mock_ctx.post.call_args.kwargs["json"]
            assert payload["waitForSelector"]["selector"] == "article"

    async def test_fetch_html_with_reject_params(self):
        """fetch_html sends reject params when set."""
        with patch("deerflow.community.browserless.browserless_client.httpx.AsyncClient") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_ctx

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = "<html>OK</html>"
            mock_resp.headers = {}
            mock_ctx.post = AsyncMock(return_value=mock_resp)

            client = BrowserlessClient(base_url="http://browserless:3000")
            await client.fetch_html(
                "https://example.com",
                reject_resource_types=["image"],
                reject_request_pattern=[r"\.css$"],
            )

            payload = mock_ctx.post.call_args.kwargs["json"]
            assert payload["rejectResourceTypes"] == ["image"]
            assert payload["rejectRequestPattern"] == [r"\.css$"]


@pytest.mark.asyncio
class TestBrowserlessTools:
    """Tests for the Browserless tool functions."""

    @patch("deerflow.community.browserless.tools._get_browserless_client")
    async def test_web_fetch_tool_success(self, mock_get_client):
        """web_fetch_tool successfully fetches and extracts content."""
        mock_client = MagicMock()
        mock_client.fetch_html = AsyncMock(return_value="<html><body><article><h1>Title</h1><p>Content</p></article></body></html>")
        mock_get_client.return_value = mock_client

        with patch("deerflow.community.browserless.tools._get_tool_config", return_value=None):
            result = await tools.web_fetch_tool.ainvoke("https://example.com/article")

        assert "Error:" not in result

    @patch("deerflow.community.browserless.tools._get_browserless_client")
    async def test_web_fetch_tool_error(self, mock_get_client):
        """web_fetch_tool returns error when fetch fails."""
        mock_client = MagicMock()
        mock_client.fetch_html = AsyncMock(return_value="Error: Browserless returned empty response")
        mock_get_client.return_value = mock_client

        with patch("deerflow.community.browserless.tools._get_tool_config", return_value=None):
            result = await tools.web_fetch_tool.ainvoke("https://example.com")

        assert result.startswith("Error:")

    @patch("deerflow.community.browserless.tools._get_browserless_client")
    async def test_web_fetch_tool_exception(self, mock_get_client):
        """web_fetch_tool returns error when client raises exception."""
        mock_client = MagicMock()
        mock_client.fetch_html = AsyncMock(side_effect=Exception("Unexpected error"))
        mock_get_client.return_value = mock_client

        with patch("deerflow.community.browserless.tools._get_tool_config", return_value=None):
            result = await tools.web_fetch_tool.ainvoke("https://example.com")

        assert result.startswith("Error:")
