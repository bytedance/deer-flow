"""Unit tests for http_connector tool and HttpConnectorConfig."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from deerflow.config.http_connector_config import HttpConnectorConfig
from deerflow.config.sandbox_config import SandboxConfig


class TestHttpConnectorConfig:
    def test_defaults(self):
        cfg = HttpConnectorConfig(name="test", url="http://example.com")
        assert cfg.method == "GET"
        assert cfg.auth_type == "none"
        assert cfg.timeout_seconds == 30.0
        assert cfg.max_response_bytes == 512 * 1024
        assert cfg.max_retries == 1
        assert cfg.retry_on_status == [502, 503, 504]
        assert cfg.cache_ttl_seconds is None

    def test_resolved_headers_no_auth(self):
        cfg = HttpConnectorConfig(name="test", url="http://example.com", headers={"X-Custom": "val"})
        result = cfg.resolved_headers()
        assert result == {"X-Custom": "val"}

    def test_resolved_headers_bearer(self, monkeypatch):
        monkeypatch.setenv("MY_TOKEN", "secret123")
        cfg = HttpConnectorConfig(
            name="test",
            url="http://example.com",
            auth_type="bearer",
            auth_token_env="MY_TOKEN",
        )
        result = cfg.resolved_headers()
        assert result["Authorization"] == "Bearer secret123"

    def test_resolved_headers_bearer_custom_header(self, monkeypatch):
        monkeypatch.setenv("MY_TOKEN", "secret123")
        cfg = HttpConnectorConfig(
            name="test",
            url="http://example.com",
            auth_type="bearer",
            auth_token_env="MY_TOKEN",
            auth_header="X-Auth-Token",
        )
        result = cfg.resolved_headers()
        assert result["X-Auth-Token"] == "Bearer secret123"

    def test_resolved_headers_api_key(self, monkeypatch):
        monkeypatch.setenv("API_KEY", "key456")
        cfg = HttpConnectorConfig(
            name="test",
            url="http://example.com",
            auth_type="api_key",
            auth_token_env="API_KEY",
            auth_header="X-API-Key",
        )
        result = cfg.resolved_headers()
        assert result["X-API-Key"] == "key456"

    def test_resolved_headers_missing_env_var(self, monkeypatch):
        monkeypatch.delenv("NONEXISTENT_TOKEN", raising=False)
        cfg = HttpConnectorConfig(
            name="test",
            url="http://example.com",
            auth_type="bearer",
            auth_token_env="NONEXISTENT_TOKEN",
        )
        result = cfg.resolved_headers()
        assert "Authorization" not in result

    def test_resolved_headers_merges_with_existing(self, monkeypatch):
        monkeypatch.setenv("MY_TOKEN", "tok")
        cfg = HttpConnectorConfig(
            name="test",
            url="http://example.com",
            headers={"Content-Type": "application/json"},
            auth_type="bearer",
            auth_token_env="MY_TOKEN",
        )
        result = cfg.resolved_headers()
        assert result["Content-Type"] == "application/json"
        assert result["Authorization"] == "Bearer tok"


class TestHttpConnectorTool:
    @pytest.fixture
    def mock_config(self):
        from deerflow.config.app_config import AppConfig

        connector = HttpConnectorConfig(
            name="test_api",
            url="http://api.example.com/data",
            method="GET",
            auth_type="none",
            timeout_seconds=10,
            max_response_bytes=1024,
            max_retries=1,
            retry_on_status=[502, 503, 504],
        )
        config = AppConfig(sandbox=SandboxConfig(use="test"), http_connectors={"tenant-1": [connector]})
        return config

    @pytest.fixture
    def mock_post_config(self):
        from deerflow.config.app_config import AppConfig

        connector = HttpConnectorConfig(
            name="fetch_data",
            url="http://api.example.com/query",
            method="POST",
            auth_type="none",
            timeout_seconds=10,
            max_response_bytes=2048,
            max_retries=0,
        )
        config = AppConfig(sandbox=SandboxConfig(use="test"), http_connectors={"tenant-1": [connector]})
        return config

    @pytest.mark.asyncio
    async def test_unknown_connector(self, mock_config):
        from deerflow.tools.builtins.http_connector_tool import http_connector_tool

        with (
            patch("deerflow.tools.builtins.http_connector_tool.get_current_tenant_id", return_value="tenant-1"),
            patch("deerflow.tools.builtins.http_connector_tool.get_app_config", return_value=mock_config),
        ):
            result = await http_connector_tool.ainvoke({"connector_name": "nonexistent"})
            assert "Error" in result
            assert "nonexistent" in result
            assert "test_api" in result

    @pytest.mark.asyncio
    async def test_no_connectors_for_tenant(self, mock_config):
        from deerflow.tools.builtins.http_connector_tool import http_connector_tool

        with (
            patch("deerflow.tools.builtins.http_connector_tool.get_current_tenant_id", return_value="other-tenant"),
            patch("deerflow.tools.builtins.http_connector_tool.get_app_config", return_value=mock_config),
        ):
            result = await http_connector_tool.ainvoke({"connector_name": "test_api"})
            assert "Error" in result
            assert "No HTTP connectors configured" in result

    @pytest.mark.asyncio
    async def test_successful_get_request(self, mock_config):
        from deerflow.tools.builtins.http_connector_tool import http_connector_tool

        mock_response = httpx.Response(
            200,
            content=b'{"datasets": [{"id": "ds1", "name": "Sales"}]}',
            request=httpx.Request("GET", "http://api.example.com/data"),
        )

        with (
            patch("deerflow.tools.builtins.http_connector_tool.get_current_tenant_id", return_value="tenant-1"),
            patch("deerflow.tools.builtins.http_connector_tool.get_app_config", return_value=mock_config),
            patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response),
        ):
            result = await http_connector_tool.ainvoke({"connector_name": "test_api", "params": {"limit": "10"}})
            assert "datasets" in result
            assert "Sales" in result

    @pytest.mark.asyncio
    async def test_successful_post_request(self, mock_post_config):
        from deerflow.tools.builtins.http_connector_tool import http_connector_tool

        mock_response = httpx.Response(
            200,
            content=b'{"rows": [{"col1": "val1"}]}',
            request=httpx.Request("POST", "http://api.example.com/query"),
        )

        with (
            patch("deerflow.tools.builtins.http_connector_tool.get_current_tenant_id", return_value="tenant-1"),
            patch("deerflow.tools.builtins.http_connector_tool.get_app_config", return_value=mock_post_config),
            patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response),
        ):
            result = await http_connector_tool.ainvoke({"connector_name": "fetch_data", "body": {"dataset_id": "ds1"}})
            assert "rows" in result
            assert "val1" in result

    @pytest.mark.asyncio
    async def test_response_truncation(self, mock_config):
        from deerflow.tools.builtins.http_connector_tool import http_connector_tool

        large_content = b"x" * 2048
        mock_response = httpx.Response(
            200,
            content=large_content,
            request=httpx.Request("GET", "http://api.example.com/data"),
        )

        with (
            patch("deerflow.tools.builtins.http_connector_tool.get_current_tenant_id", return_value="tenant-1"),
            patch("deerflow.tools.builtins.http_connector_tool.get_app_config", return_value=mock_config),
            patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response),
        ):
            result = await http_connector_tool.ainvoke({"connector_name": "test_api"})
            assert "[Response truncated due to size limit]" in result
            assert len(result) < 2048 + 100

    @pytest.mark.asyncio
    async def test_retry_on_502(self, mock_config):
        from deerflow.tools.builtins.http_connector_tool import http_connector_tool

        fail_response = httpx.Response(
            502,
            content=b"Bad Gateway",
            request=httpx.Request("GET", "http://api.example.com/data"),
        )
        success_response = httpx.Response(
            200,
            content=b'{"ok": true}',
            request=httpx.Request("GET", "http://api.example.com/data"),
        )

        mock_get = AsyncMock(side_effect=[fail_response, success_response])

        with (
            patch("deerflow.tools.builtins.http_connector_tool.get_current_tenant_id", return_value="tenant-1"),
            patch("deerflow.tools.builtins.http_connector_tool.get_app_config", return_value=mock_config),
            patch("httpx.AsyncClient.get", mock_get),
        ):
            result = await http_connector_tool.ainvoke({"connector_name": "test_api"})
            assert '"ok": true' in result or "ok" in result
            assert mock_get.call_count == 2

    @pytest.mark.asyncio
    async def test_timeout_handling(self, mock_config):
        from deerflow.tools.builtins.http_connector_tool import http_connector_tool

        mock_get = AsyncMock(side_effect=httpx.TimeoutException("Connection timed out"))

        with (
            patch("deerflow.tools.builtins.http_connector_tool.get_current_tenant_id", return_value="tenant-1"),
            patch("deerflow.tools.builtins.http_connector_tool.get_app_config", return_value=mock_config),
            patch("httpx.AsyncClient.get", mock_get),
        ):
            result = await http_connector_tool.ainvoke({"connector_name": "test_api"})
            assert "Error" in result
            assert "Failed to call connector" in result
            assert "timeout" in result

    @pytest.mark.asyncio
    async def test_http_error_handling(self, mock_config):
        from deerflow.tools.builtins.http_connector_tool import http_connector_tool

        mock_get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))

        with (
            patch("deerflow.tools.builtins.http_connector_tool.get_current_tenant_id", return_value="tenant-1"),
            patch("deerflow.tools.builtins.http_connector_tool.get_app_config", return_value=mock_config),
            patch("httpx.AsyncClient.get", mock_get),
        ):
            result = await http_connector_tool.ainvoke({"connector_name": "test_api"})
            assert "Error" in result
            assert "Failed to call connector" in result

    @pytest.mark.asyncio
    async def test_non_success_status_no_retry(self, mock_post_config):
        from deerflow.tools.builtins.http_connector_tool import http_connector_tool

        mock_response = httpx.Response(
            404,
            content=b'{"error": "Not found"}',
            request=httpx.Request("POST", "http://api.example.com/query"),
        )

        with (
            patch("deerflow.tools.builtins.http_connector_tool.get_current_tenant_id", return_value="tenant-1"),
            patch("deerflow.tools.builtins.http_connector_tool.get_app_config", return_value=mock_post_config),
            patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response),
        ):
            result = await http_connector_tool.ainvoke({"connector_name": "fetch_data", "body": {"id": "x"}})
            assert "Error: HTTP 404" in result
            assert "Check server logs" in result


class TestAppConfigHttpConnectors:
    def test_get_http_connector_found(self):
        from deerflow.config.app_config import AppConfig

        connector = HttpConnectorConfig(name="my_api", url="http://example.com")
        config = AppConfig(sandbox=SandboxConfig(use="test"), http_connectors={"t1": [connector]})
        result = config.get_http_connector("t1", "my_api")
        assert result is not None
        assert result.name == "my_api"

    def test_get_http_connector_not_found(self):
        from deerflow.config.app_config import AppConfig

        connector = HttpConnectorConfig(name="my_api", url="http://example.com")
        config = AppConfig(sandbox=SandboxConfig(use="test"), http_connectors={"t1": [connector]})
        result = config.get_http_connector("t1", "other")
        assert result is None

    def test_get_http_connector_wrong_tenant(self):
        from deerflow.config.app_config import AppConfig

        connector = HttpConnectorConfig(name="my_api", url="http://example.com")
        config = AppConfig(sandbox=SandboxConfig(use="test"), http_connectors={"t1": [connector]})
        result = config.get_http_connector("t2", "my_api")
        assert result is None

    def test_list_connector_names(self):
        from deerflow.config.app_config import AppConfig

        connectors = [
            HttpConnectorConfig(name="api_a", url="http://a.com"),
            HttpConnectorConfig(name="api_b", url="http://b.com"),
        ]
        config = AppConfig(sandbox=SandboxConfig(use="test"), http_connectors={"t1": connectors})
        names = config.list_connector_names("t1")
        assert names == ["api_a", "api_b"]

    def test_list_connector_names_empty_tenant(self):
        from deerflow.config.app_config import AppConfig

        config = AppConfig(sandbox=SandboxConfig(use="test"), http_connectors={})
        names = config.list_connector_names("t1")
        assert names == []
