"""Tests for Browserless community tools."""

import ipaddress
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from deerflow.community.browserless import tools
from deerflow.community.browserless.browserless_client import BrowserlessClient, BrowserlessScreenshotResult


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

    async def test_capture_screenshot_success(self):
        """capture_screenshot posts to /screenshot and returns image bytes."""
        with patch("deerflow.community.browserless.browserless_client.httpx.AsyncClient") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_ctx

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.content = b"\x89PNG\r\n\x1a\nimage"
            mock_resp.text = "<binary>"
            mock_resp.headers = {
                "Content-Type": "image/png",
                "X-Response-Code": "200",
                "X-Response-Status": "OK",
                "X-Response-URL": "https://example.com/final",
            }
            mock_ctx.post = AsyncMock(return_value=mock_resp)

            client = BrowserlessClient(base_url="http://browserless:3000", token="secret-token")
            result = await client.capture_screenshot(
                "https://example.com",
                full_page=True,
                output_format="png",
                viewport={"width": 1280, "height": 720},
                wait_for_selector="main",
                wait_for_selector_timeout_ms=3000,
                wait_for_timeout_ms=500,
                best_attempt=True,
            )

            assert isinstance(result, BrowserlessScreenshotResult)
            assert result.content == b"\x89PNG\r\n\x1a\nimage"
            assert result.content_type == "image/png"
            assert result.target_status_code == "200"
            assert result.target_status == "OK"
            assert result.final_url == "https://example.com/final"

            call = mock_ctx.post.call_args
            assert call.args == ("http://browserless:3000/screenshot",)
            payload = call.kwargs["json"]
            assert payload["url"] == "https://example.com"
            assert payload["options"] == {
                "fullPage": True,
                "type": "png",
            }
            assert call.kwargs["params"] == {"token": "secret-token"}
            assert payload["viewport"] == {"width": 1280, "height": 720}
            assert payload["waitForSelector"] == {"selector": "main", "timeout": 3000}
            assert payload["waitForTimeout"] == 500
            assert payload["bestAttempt"] is True

    async def test_capture_screenshot_http_error(self):
        """capture_screenshot returns a bounded error on non-200 responses."""
        with patch("deerflow.community.browserless.browserless_client.httpx.AsyncClient") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_ctx

            mock_resp = MagicMock()
            mock_resp.status_code = 500
            mock_resp.text = "Internal browserless error"
            mock_resp.headers = {}
            mock_ctx.post = AsyncMock(return_value=mock_resp)

            client = BrowserlessClient(base_url="http://browserless:3000")
            result = await client.capture_screenshot("https://example.com")

        assert isinstance(result, str)
        assert "Error: Browserless HTTP 500" in result
        assert "Internal browserless error" in result

    async def test_capture_screenshot_empty_response(self):
        """capture_screenshot returns a clear error for empty binary content."""
        with patch("deerflow.community.browserless.browserless_client.httpx.AsyncClient") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_ctx

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.content = b""
            mock_resp.text = ""
            mock_resp.headers = {"Content-Type": "image/png"}
            mock_ctx.post = AsyncMock(return_value=mock_resp)

            client = BrowserlessClient(base_url="http://browserless:3000")
            result = await client.capture_screenshot("https://example.com")

        assert result == "Error: Browserless returned empty screenshot response"


@pytest.mark.asyncio
class TestBrowserlessTools:
    """Tests for the Browserless tool functions."""

    async def test_get_browserless_client_uses_env_token_fallback(self):
        """Browserless tools use BROWSERLESS_TOKEN when config omits token."""
        with patch("deerflow.community.browserless.tools._get_tool_config") as mock_cfg:
            mock_cfg.return_value = {"base_url": "https://production-sfo.browserless.io"}
            with patch.dict("os.environ", {"BROWSERLESS_TOKEN": "env-token"}, clear=True):
                client = tools._get_browserless_client("web_capture")

        assert client.token == "env-token"

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

    @patch("deerflow.community.browserless.tools._get_browserless_client")
    async def test_web_fetch_tool_rejects_metadata_ip(self, mock_get_client):
        """web_fetch_tool blocks the cloud-metadata link-local endpoint."""
        with patch("deerflow.community.browserless.tools._get_tool_config", return_value=None):
            result = await tools.web_fetch_tool.ainvoke("http://169.254.169.254/latest/meta-data/")

        assert "private, loopback, or metadata" in result
        mock_get_client.assert_not_called()

    @patch("deerflow.community.browserless.tools._get_browserless_client")
    async def test_web_fetch_tool_rejects_dns_resolving_to_private(self, mock_get_client):
        """web_fetch_tool blocks hostnames that resolve to internal IPs."""
        with patch("deerflow.community.browserless.tools._get_tool_config", return_value=None):
            with patch(
                "deerflow.community.browserless.tools._resolve_host_addresses",
                return_value=[ipaddress.ip_address("10.0.0.5")],
            ):
                result = await tools.web_fetch_tool.ainvoke("https://internal.example.com/")

        assert "private, loopback, or metadata" in result
        mock_get_client.assert_not_called()

    @patch("deerflow.community.browserless.tools._get_browserless_client")
    async def test_web_fetch_tool_allows_private_when_opted_in(self, mock_get_client):
        """web_fetch_tool allows internal targets only when explicitly configured."""
        mock_client = MagicMock()
        mock_client.fetch_html = AsyncMock(return_value="<html><body><article><p>internal</p></article></body></html>")
        mock_get_client.return_value = mock_client

        with patch("deerflow.community.browserless.tools._get_tool_config", return_value={"allow_private_addresses": True}):
            result = await tools.web_fetch_tool.ainvoke("http://10.0.0.5/dashboard")

        assert "Error:" not in result
        mock_client.fetch_html.assert_called_once()

    @patch("deerflow.community.browserless.tools._get_browserless_client")
    async def test_web_capture_tool_writes_artifact(self, mock_get_client, tmp_path):
        """web_capture_tool writes screenshots into thread outputs and presents the artifact."""
        outputs_dir = tmp_path / "outputs"
        outputs_dir.mkdir()
        runtime = SimpleNamespace(state={"thread_data": {"outputs_path": str(outputs_dir)}})

        mock_client = MagicMock()
        mock_client.capture_screenshot = AsyncMock(
            return_value=BrowserlessScreenshotResult(
                content=b"\x89PNG\r\n\x1a\nimage",
                content_type="image/png",
                target_status_code="200",
                target_status="OK",
                final_url="https://example.com/final",
            )
        )
        mock_get_client.return_value = mock_client

        with patch("deerflow.community.browserless.tools._get_tool_config") as mock_cfg:
            mock_cfg.side_effect = lambda name: {
                "web_capture": {
                    "full_page": False,
                    "output_format": "png",
                    "viewport_width": 1024,
                    "viewport_height": 768,
                    "wait_for_selector": "main",
                    "wait_for_selector_timeout_ms": 4000,
                    "wait_for_timeout_ms": 250,
                    "best_attempt": True,
                }
            }.get(name)

            with patch(
                "deerflow.community.browserless.tools._resolve_host_addresses",
                return_value=[ipaddress.ip_address("93.184.216.34")],
            ):
                result = await tools.web_capture_tool.coroutine(
                    runtime=runtime,
                    url="https://example.com/dashboard",
                    tool_call_id="tool-1",
                    filename="Dashboard Capture.png",
                )

        artifact_path = result.update["artifacts"][0]
        assert artifact_path == "/mnt/user-data/outputs/Dashboard_Capture.png"
        written = outputs_dir / "Dashboard_Capture.png"
        assert written.read_bytes() == b"\x89PNG\r\n\x1a\nimage"
        assert result.update["messages"][0].content == "Captured screenshot: /mnt/user-data/outputs/Dashboard_Capture.png"
        mock_cfg.assert_any_call("web_capture")
        mock_client.capture_screenshot.assert_called_once_with(
            url="https://example.com/dashboard",
            full_page=False,
            output_format="png",
            quality=None,
            viewport={"width": 1024, "height": 768},
            wait_for_selector="main",
            wait_for_selector_timeout_ms=4000,
            wait_for_timeout_ms=250,
            best_attempt=True,
        )

    async def test_web_capture_tool_rejects_non_http_url(self, tmp_path):
        """web_capture_tool only accepts explicit http(s) URLs."""
        outputs_dir = tmp_path / "outputs"
        outputs_dir.mkdir()
        runtime = SimpleNamespace(state={"thread_data": {"outputs_path": str(outputs_dir)}})

        with patch("deerflow.community.browserless.tools._get_tool_config", return_value=None):
            with patch("deerflow.community.browserless.tools._get_browserless_client") as mock_get_client:
                result = await tools.web_capture_tool.coroutine(
                    runtime=runtime,
                    url="file:///etc/passwd",
                    tool_call_id="tool-1",
                )

        assert "Only http:// and https:// URLs are supported" in result.update["messages"][0].content
        assert "artifacts" not in result.update
        mock_get_client.assert_not_called()
        assert list(outputs_dir.iterdir()) == []

    async def test_web_capture_tool_rejects_loopback_url(self, tmp_path):
        """web_capture_tool blocks loopback/localhost targets to prevent SSRF."""
        outputs_dir = tmp_path / "outputs"
        outputs_dir.mkdir()
        runtime = SimpleNamespace(state={"thread_data": {"outputs_path": str(outputs_dir)}})

        with patch("deerflow.community.browserless.tools._get_tool_config", return_value=None):
            with patch("deerflow.community.browserless.tools._get_browserless_client") as mock_get_client:
                result = await tools.web_capture_tool.coroutine(
                    runtime=runtime,
                    url="http://localhost:8080/admin",
                    tool_call_id="tool-1",
                )

        assert "private or loopback" in result.update["messages"][0].content
        assert "artifacts" not in result.update
        mock_get_client.assert_not_called()
        assert list(outputs_dir.iterdir()) == []

    async def test_web_capture_tool_rejects_metadata_ip(self, tmp_path):
        """web_capture_tool blocks the cloud-metadata link-local endpoint."""
        outputs_dir = tmp_path / "outputs"
        outputs_dir.mkdir()
        runtime = SimpleNamespace(state={"thread_data": {"outputs_path": str(outputs_dir)}})

        with patch("deerflow.community.browserless.tools._get_tool_config", return_value=None):
            with patch("deerflow.community.browserless.tools._get_browserless_client") as mock_get_client:
                result = await tools.web_capture_tool.coroutine(
                    runtime=runtime,
                    url="http://169.254.169.254/latest/meta-data/",
                    tool_call_id="tool-1",
                )

        assert "private, loopback, or metadata" in result.update["messages"][0].content
        assert "artifacts" not in result.update
        mock_get_client.assert_not_called()

    async def test_web_capture_tool_rejects_dns_resolving_to_private(self, tmp_path):
        """web_capture_tool blocks a public hostname that resolves to an internal IP."""
        outputs_dir = tmp_path / "outputs"
        outputs_dir.mkdir()
        runtime = SimpleNamespace(state={"thread_data": {"outputs_path": str(outputs_dir)}})

        with patch("deerflow.community.browserless.tools._get_tool_config", return_value=None):
            with patch(
                "deerflow.community.browserless.tools._resolve_host_addresses",
                return_value=[ipaddress.ip_address("10.0.0.5")],
            ):
                with patch("deerflow.community.browserless.tools._get_browserless_client") as mock_get_client:
                    result = await tools.web_capture_tool.coroutine(
                        runtime=runtime,
                        url="https://internal.example.com/",
                        tool_call_id="tool-1",
                    )

        assert "private, loopback, or metadata" in result.update["messages"][0].content
        assert "artifacts" not in result.update
        mock_get_client.assert_not_called()

    async def test_web_capture_tool_allows_private_when_opted_in(self, tmp_path):
        """web_capture_tool honors allow_private_addresses for internal targets."""
        outputs_dir = tmp_path / "outputs"
        outputs_dir.mkdir()
        runtime = SimpleNamespace(state={"thread_data": {"outputs_path": str(outputs_dir)}})

        mock_client = MagicMock()
        mock_client.capture_screenshot = AsyncMock(
            return_value=BrowserlessScreenshotResult(
                content=b"\x89PNG\r\n\x1a\nimage",
                content_type="image/png",
                target_status_code="200",
                target_status="OK",
                final_url="http://10.0.0.5/final",
            )
        )

        with patch("deerflow.community.browserless.tools._get_tool_config", return_value={"allow_private_addresses": True}):
            with patch("deerflow.community.browserless.tools._get_browserless_client", return_value=mock_client):
                result = await tools.web_capture_tool.coroutine(
                    runtime=runtime,
                    url="http://10.0.0.5/dashboard",
                    tool_call_id="tool-1",
                )

        assert result.update["artifacts"][0].startswith("/mnt/user-data/outputs/")
        assert (outputs_dir / result.update["artifacts"][0].split("/")[-1]).read_bytes() == b"\x89PNG\r\n\x1a\nimage"
        mock_client.capture_screenshot.assert_called_once()

    async def test_web_capture_tool_warns_on_target_error_status(self, tmp_path):
        """web_capture_tool surfaces a warning when the captured page itself errored."""
        outputs_dir = tmp_path / "outputs"
        outputs_dir.mkdir()
        runtime = SimpleNamespace(state={"thread_data": {"outputs_path": str(outputs_dir)}})

        mock_client = MagicMock()
        mock_client.capture_screenshot = AsyncMock(
            return_value=BrowserlessScreenshotResult(
                content=b"\x89PNG\r\n\x1a\nimage",
                content_type="image/png",
                target_status_code="404",
                target_status="Not Found",
                final_url="https://example.com/missing",
            )
        )

        with patch("deerflow.community.browserless.tools._get_tool_config", return_value=None):
            with patch(
                "deerflow.community.browserless.tools._resolve_host_addresses",
                return_value=[ipaddress.ip_address("93.184.216.34")],
            ):
                with patch("deerflow.community.browserless.tools._get_browserless_client", return_value=mock_client):
                    result = await tools.web_capture_tool.coroutine(
                        runtime=runtime,
                        url="https://example.com/missing",
                        tool_call_id="tool-1",
                    )

        message = result.update["messages"][0].content
        assert "warning: target page responded 404 Not Found" in message
        assert result.update["artifacts"]

    async def test_web_capture_tool_dedupes_existing_filename(self, tmp_path):
        """web_capture_tool appends a suffix instead of overwriting an existing capture."""
        outputs_dir = tmp_path / "outputs"
        outputs_dir.mkdir()
        (outputs_dir / "report.png").write_bytes(b"existing")
        runtime = SimpleNamespace(state={"thread_data": {"outputs_path": str(outputs_dir)}})

        mock_client = MagicMock()
        mock_client.capture_screenshot = AsyncMock(
            return_value=BrowserlessScreenshotResult(
                content=b"\x89PNG\r\n\x1a\nnew",
                content_type="image/png",
                target_status_code="200",
                target_status="OK",
                final_url="https://example.com/",
            )
        )

        with patch("deerflow.community.browserless.tools._get_tool_config", return_value=None):
            with patch(
                "deerflow.community.browserless.tools._resolve_host_addresses",
                return_value=[ipaddress.ip_address("93.184.216.34")],
            ):
                with patch("deerflow.community.browserless.tools._get_browserless_client", return_value=mock_client):
                    result = await tools.web_capture_tool.coroutine(
                        runtime=runtime,
                        url="https://example.com/",
                        tool_call_id="tool-1",
                        filename="report.png",
                    )

        assert result.update["artifacts"] == ["/mnt/user-data/outputs/report-1.png"]
        assert (outputs_dir / "report.png").read_bytes() == b"existing"
        assert (outputs_dir / "report-1.png").read_bytes() == b"\x89PNG\r\n\x1a\nnew"

    @patch("deerflow.community.browserless.tools._get_browserless_client")
    async def test_web_capture_tool_missing_outputs_path_returns_error(self, mock_get_client):
        """web_capture_tool requires ThreadDataMiddleware outputs_path."""
        runtime = SimpleNamespace(state={"thread_data": {}})

        with patch("deerflow.community.browserless.tools._get_tool_config", return_value=None):
            with patch(
                "deerflow.community.browserless.tools._resolve_host_addresses",
                return_value=[ipaddress.ip_address("93.184.216.34")],
            ):
                result = await tools.web_capture_tool.coroutine(
                    runtime=runtime,
                    url="https://example.com",
                    tool_call_id="tool-1",
                )

        assert "Thread outputs path is not available" in result.update["messages"][0].content
        assert "artifacts" not in result.update
        mock_get_client.assert_not_called()
