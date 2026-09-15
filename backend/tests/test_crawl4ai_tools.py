"""Tests for Crawl4AI community tools."""

import ipaddress
import json
from unittest.mock import MagicMock, patch

import pytest

from deerflow.community.crawl4ai.crawl4ai_client import Crawl4AiClient


class AsyncMock(MagicMock):
    """Mock that supports async call."""

    async def __call__(self, *args, **kwargs):
        return super().__call__(*args, **kwargs)


@pytest.mark.asyncio
class TestCrawl4AiClient:
    """Tests for the Crawl4AiClient class."""

    async def test_fetch_markdown_success(self):
        with patch("deerflow.community.crawl4ai.crawl4ai_client.httpx.AsyncClient") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_ctx

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"markdown": "# Title\n\nHello", "success": True}
            mock_ctx.post = AsyncMock(return_value=mock_resp)

            client = Crawl4AiClient(base_url="http://crawl4ai:11235")
            result = await client.fetch_markdown("https://example.com")

            assert result == "# Title\n\nHello"
            call = mock_ctx.post.call_args
            assert call.args[0].endswith("/md")
            assert call.kwargs["json"]["url"] == "https://example.com"
            assert call.kwargs["json"]["f"] == "fit"

    async def test_fetch_markdown_strips_trailing_slash_in_base_url(self):
        client = Crawl4AiClient(base_url="http://crawl4ai:11235/")
        assert client.base_url == "http://crawl4ai:11235"

    async def test_fetch_markdown_http_error(self):
        with patch("deerflow.community.crawl4ai.crawl4ai_client.httpx.AsyncClient") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_ctx

            mock_resp = MagicMock()
            mock_resp.status_code = 502
            mock_resp.text = "Bad Gateway"
            mock_ctx.post = AsyncMock(return_value=mock_resp)

            client = Crawl4AiClient(base_url="http://crawl4ai:11235")
            result = await client.fetch_markdown("https://example.com")
            assert "Error: Crawl4AI HTTP 502" in result

    async def test_fetch_markdown_success_false(self):
        with patch("deerflow.community.crawl4ai.crawl4ai_client.httpx.AsyncClient") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_ctx

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"markdown": "", "success": False}
            mock_ctx.post = AsyncMock(return_value=mock_resp)

            client = Crawl4AiClient(base_url="http://crawl4ai:11235")
            result = await client.fetch_markdown("https://example.com")
            assert result.startswith("Error:")

    async def test_fetch_markdown_empty(self):
        with patch("deerflow.community.crawl4ai.crawl4ai_client.httpx.AsyncClient") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_ctx

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"markdown": "   ", "success": True}
            mock_ctx.post = AsyncMock(return_value=mock_resp)

            client = Crawl4AiClient(base_url="http://crawl4ai:11235")
            result = await client.fetch_markdown("https://example.com")
            assert result == "Error: Crawl4AI returned empty markdown"

    async def test_fetch_markdown_timeout(self):
        with patch("deerflow.community.crawl4ai.crawl4ai_client.httpx.AsyncClient") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_ctx
            import httpx

            mock_ctx.post = AsyncMock(side_effect=httpx.TimeoutException("Timed out"))

            client = Crawl4AiClient(base_url="http://crawl4ai:11235", timeout_s=10)
            result = await client.fetch_markdown("https://example.com")
            assert "timed out" in result.lower() or "timeout" in result.lower()

    async def test_fetch_markdown_with_token(self):
        with patch("deerflow.community.crawl4ai.crawl4ai_client.httpx.AsyncClient") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_ctx

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"markdown": "ok", "success": True}
            mock_ctx.post = AsyncMock(return_value=mock_resp)

            client = Crawl4AiClient(base_url="http://crawl4ai:11235", token="secret")
            await client.fetch_markdown("https://example.com")

            headers = mock_ctx.post.call_args.kwargs["headers"]
            assert headers["Authorization"] == "Bearer secret"

    async def test_fetch_markdown_no_token_header_when_unset(self):
        with patch("deerflow.community.crawl4ai.crawl4ai_client.httpx.AsyncClient") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_ctx

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"markdown": "ok", "success": True}
            mock_ctx.post = AsyncMock(return_value=mock_resp)

            client = Crawl4AiClient(base_url="http://crawl4ai:11235")
            await client.fetch_markdown("https://example.com")

            headers = mock_ctx.post.call_args.kwargs["headers"]
            assert "Authorization" not in headers

    async def test_fetch_markdown_request_error(self):
        with patch("deerflow.community.crawl4ai.crawl4ai_client.httpx.AsyncClient") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_ctx
            import httpx

            mock_ctx.post = AsyncMock(side_effect=httpx.ConnectError("connection refused"))

            client = Crawl4AiClient(base_url="http://crawl4ai:11235")
            result = await client.fetch_markdown("https://example.com")
            assert result.startswith("Error: Crawl4AI request failed")

    async def test_fetch_markdown_non_json_200(self):
        with patch("deerflow.community.crawl4ai.crawl4ai_client.httpx.AsyncClient") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_ctx

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.side_effect = json.JSONDecodeError("Expecting value", "doc", 0)
            mock_resp.headers = {"content-type": "text/html"}
            mock_resp.text = "<html>login wall</html>"
            mock_ctx.post = AsyncMock(return_value=mock_resp)

            client = Crawl4AiClient(base_url="http://crawl4ai:11235")
            result = await client.fetch_markdown("https://example.com")
            assert result.startswith("Error: Crawl4AI returned a non-JSON 200 response")
            assert "text/html" in result


@pytest.mark.asyncio
class TestCrawl4AiTools:
    """Tests for the Crawl4AI tool functions."""

    @patch("deerflow.community.crawl4ai.tools._build_client")
    async def test_web_fetch_tool_success(self, mock_build):
        from deerflow.community.crawl4ai import tools

        mock_client = MagicMock()
        mock_client.fetch_markdown = AsyncMock(return_value="# Title\n\nContent")
        mock_build.return_value = mock_client

        with patch("deerflow.community.crawl4ai.tools._get_tool_config", return_value=None):
            result = await tools.web_fetch_tool.ainvoke("https://example.com/article")

        assert result == "# Title\n\nContent"
        assert "Error:" not in result

    @patch("deerflow.community.crawl4ai.tools._build_client")
    async def test_web_fetch_tool_truncates_to_4096(self, mock_build):
        from deerflow.community.crawl4ai import tools

        mock_client = MagicMock()
        mock_client.fetch_markdown = AsyncMock(return_value="x" * 5000)
        mock_build.return_value = mock_client

        with patch("deerflow.community.crawl4ai.tools._get_tool_config", return_value=None):
            result = await tools.web_fetch_tool.ainvoke("https://example.com")

        assert len(result) == 4096

    @patch("deerflow.community.crawl4ai.tools._build_client")
    async def test_web_fetch_tool_error_passthrough(self, mock_build):
        from deerflow.community.crawl4ai import tools

        mock_client = MagicMock()
        mock_client.fetch_markdown = AsyncMock(return_value="Error: Crawl4AI returned empty markdown")
        mock_build.return_value = mock_client

        with patch("deerflow.community.crawl4ai.tools._get_tool_config", return_value=None):
            result = await tools.web_fetch_tool.ainvoke("https://example.com")

        assert result.startswith("Error:")

    @patch("deerflow.community.crawl4ai.tools._build_client")
    async def test_web_fetch_tool_exception(self, mock_build):
        from deerflow.community.crawl4ai import tools

        mock_client = MagicMock()
        mock_client.fetch_markdown = AsyncMock(side_effect=Exception("boom"))
        mock_build.return_value = mock_client

        with patch("deerflow.community.crawl4ai.tools._get_tool_config", return_value=None):
            result = await tools.web_fetch_tool.ainvoke("https://example.com")

        assert result.startswith("Error:")

    @patch("deerflow.community.crawl4ai.tools._build_client")
    async def test_web_fetch_tool_rejects_metadata_ip(self, mock_build):
        from deerflow.community.crawl4ai import tools

        with patch("deerflow.community.crawl4ai.tools._get_tool_config", return_value=None):
            result = await tools.web_fetch_tool.ainvoke("http://169.254.169.254/latest/meta-data/")

        assert "private, loopback, or metadata" in result
        mock_build.assert_not_called()

    @patch("deerflow.community.crawl4ai.tools._build_client")
    async def test_web_fetch_tool_rejects_dns_resolving_to_private(self, mock_build):
        from deerflow.community.crawl4ai import tools

        with patch("deerflow.community.crawl4ai.tools._get_tool_config", return_value=None):
            with patch(
                "deerflow.community.url_safety.resolve_host_addresses",
                return_value=[ipaddress.ip_address("10.0.0.5")],
            ):
                result = await tools.web_fetch_tool.ainvoke("https://internal.example.com/")

        assert "private, loopback, or metadata" in result
        mock_build.assert_not_called()

    @patch("deerflow.community.crawl4ai.tools._build_client")
    async def test_web_fetch_tool_allows_private_when_opted_in(self, mock_build):
        from deerflow.community.crawl4ai import tools

        mock_client = MagicMock()
        mock_client.fetch_markdown = AsyncMock(return_value="# internal")
        mock_build.return_value = mock_client

        with patch("deerflow.community.crawl4ai.tools._get_tool_config", return_value={"allow_private_addresses": True}):
            result = await tools.web_fetch_tool.ainvoke("http://10.0.0.5/dashboard")

        assert result == "# internal"
        mock_client.fetch_markdown.assert_called_once()

    @patch("deerflow.community.crawl4ai.tools._build_client")
    async def test_web_fetch_tool_reads_config_once(self, mock_build):
        """Config is read exactly once per invocation (no split read on hot-reload)."""
        from deerflow.community.crawl4ai import tools

        mock_client = MagicMock()
        mock_client.fetch_markdown = AsyncMock(return_value="# ok")
        mock_build.return_value = mock_client

        with patch("deerflow.community.crawl4ai.tools._get_tool_config", return_value={}) as mock_cfg:
            await tools.web_fetch_tool.ainvoke("https://example.com")

        mock_cfg.assert_called_once_with("web_fetch")

    @patch("deerflow.community.crawl4ai.tools._build_client")
    async def test_web_fetch_tool_passes_configured_filter(self, mock_build):
        from deerflow.community.crawl4ai import tools

        mock_client = MagicMock()
        mock_client.fetch_markdown = AsyncMock(return_value="# ok")
        mock_build.return_value = mock_client

        with patch("deerflow.community.crawl4ai.tools._get_tool_config", return_value={"filter": "raw"}):
            await tools.web_fetch_tool.ainvoke("https://example.com")

        mock_client.fetch_markdown.assert_called_once()
        assert mock_client.fetch_markdown.call_args.kwargs.get("filter_mode") == "raw"

    @patch("deerflow.community.crawl4ai.tools._build_client")
    async def test_web_fetch_tool_invalid_filter_falls_back_to_fit(self, mock_build):
        from deerflow.community.crawl4ai import tools

        mock_client = MagicMock()
        mock_client.fetch_markdown = AsyncMock(return_value="# ok")
        mock_build.return_value = mock_client

        with patch("deerflow.community.crawl4ai.tools._get_tool_config", return_value={"filter": "BOGUS"}):
            await tools.web_fetch_tool.ainvoke("https://example.com")

        assert mock_client.fetch_markdown.call_args.kwargs.get("filter_mode") == "fit"

    async def test_build_client_reads_config(self):
        from deerflow.community.crawl4ai import tools

        client = tools._build_client({"base_url": "http://host.docker.internal:11235", "timeout": 45})
        assert client.base_url == "http://host.docker.internal:11235"
        assert client.timeout_s == 45.0

    async def test_build_client_defaults_when_unconfigured(self):
        from deerflow.community.crawl4ai import tools

        client = tools._build_client(None)
        assert client.base_url == "http://localhost:11235"
        assert client.timeout_s == 30.0
        assert client.token == ""

    async def test_build_client_reads_token(self):
        from deerflow.community.crawl4ai import tools

        client = tools._build_client({"token": "secret-token"})
        assert client.token == "secret-token"

    async def test_coerce_timeout_handles_bool_and_bad_values(self):
        from deerflow.community.crawl4ai import tools

        assert tools._coerce_timeout(True, 30) == 30.0
        assert tools._coerce_timeout(False, 30) == 30.0
        assert tools._coerce_timeout("thirty", 30) == 30.0
        assert tools._coerce_timeout("45", 30) == 45.0
        assert tools._coerce_timeout(20, 30) == 20.0
        assert tools._coerce_timeout(12.5, 30) == 12.5

    async def test_coerce_filter_validates_and_normalizes(self):
        from deerflow.community.crawl4ai import tools

        assert tools._coerce_filter("raw") == "raw"
        assert tools._coerce_filter("  FIt ") == "fit"
        assert tools._coerce_filter("bogus") == "fit"
        assert tools._coerce_filter(None) == "fit"
