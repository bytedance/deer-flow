"""Unit tests for RpcClient extensions: auth_headers, response_unwrapper, health_check (Task 1.7.7)."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from deerflow.config.rpc_config import RpcServiceConfig
from deerflow.rpc.rpc_client import RpcClient, RpcError


def _make_service(**overrides):
    defaults = {
        "name": "test-service",
        "base_url": "http://test.example.com",
    }
    defaults.update(overrides)
    return RpcServiceConfig(**defaults)


class TestResolveAuthHeaders:
    def test_no_auth_headers(self):
        client = RpcClient()
        service = _make_service(auth_headers=None)
        result = client._resolve_auth_headers(service)
        assert result == {}

    def test_literal_headers(self):
        client = RpcClient()
        service = _make_service(
            auth_headers={"X-API-Key": "my-secret-key", "X-Tenant": "t1"}
        )
        result = client._resolve_auth_headers(service)
        assert result == {"X-API-Key": "my-secret-key", "X-Tenant": "t1"}

    def test_env_var_resolution(self):
        client = RpcClient()
        service = _make_service(
            auth_headers={"Authorization": "$MY_AUTH_TOKEN"}
        )
        with patch.dict(os.environ, {"MY_AUTH_TOKEN": "Bearer token123"}):
            result = client._resolve_auth_headers(service)
            assert result == {"Authorization": "Bearer token123"}

    def test_missing_env_var_skipped(self):
        client = RpcClient()
        service = _make_service(
            auth_headers={"Authorization": "$NONEXISTENT_VAR_XYZ"}
        )
        with patch.dict(os.environ, {}, clear=True):
            result = client._resolve_auth_headers(service)
            assert result == {}

    def test_protected_content_type_skipped(self):
        client = RpcClient()
        service = _make_service(
            auth_headers={
                "Content-Type": "text/plain",
                "X-API-Key": "key123",
            }
        )
        result = client._resolve_auth_headers(service)
        assert "Content-Type" not in result
        assert result == {"X-API-Key": "key123"}

    def test_protected_accept_skipped(self):
        client = RpcClient()
        service = _make_service(
            auth_headers={
                "Accept": "text/html",
                "X-Custom": "value",
            }
        )
        result = client._resolve_auth_headers(service)
        assert "Accept" not in result
        assert result == {"X-Custom": "value"}

    def test_case_insensitive_protection(self):
        client = RpcClient()
        service = _make_service(
            auth_headers={
                "content-type": "text/plain",
                "ACCEPT": "text/html",
            }
        )
        result = client._resolve_auth_headers(service)
        assert result == {}


class TestResponseUnwrapper:
    def _make_response(self, json_data=None, text="", status_code=200):
        response = MagicMock(spec=httpx.Response)
        response.status_code = status_code
        response.text = text or (str(json_data) if json_data else "")
        response.json.return_value = json_data
        return response

    def test_java_standard_success(self):
        client = RpcClient()
        service = _make_service(response_unwrapper="java_standard")
        response = self._make_response(
            json_data={"success": True, "data": {"id": 1}, "message": "OK"},
        )
        result = client._unwrap_response(service, response)
        assert result == {"id": 1}

    def test_java_standard_error(self):
        client = RpcClient()
        service = _make_service(response_unwrapper="java_standard")
        response = self._make_response(
            json_data={"success": False, "data": None, "message": "Not found"},
        )
        with pytest.raises(RpcError, match="Not found"):
            client._unwrap_response(service, response)

    def test_passthrough(self):
        client = RpcClient()
        service = _make_service(response_unwrapper="passthrough")
        response = self._make_response(
            json_data={"custom": "data", "status": "ok"},
        )
        result = client._unwrap_response(service, response)
        assert result == {"custom": "data", "status": "ok"}

    def test_http_status_only(self):
        client = RpcClient()
        service = _make_service(response_unwrapper="http_status_only")
        response = self._make_response(status_code=200)
        result = client._unwrap_response(service, response)
        assert result == {"status_code": 200, "ok": True}

    def test_http_status_only_error(self):
        client = RpcClient()
        service = _make_service(response_unwrapper="http_status_only")
        response = self._make_response(status_code=500)
        result = client._unwrap_response(service, response)
        assert result == {"status_code": 500, "ok": False}

    def test_empty_response_passthrough(self):
        client = RpcClient()
        service = _make_service(response_unwrapper="passthrough")
        response = self._make_response(text="")
        result = client._unwrap_response(service, response)
        assert result is None

    def test_custom_unwrapper_invalid_path_falls_back(self):
        client = RpcClient()
        service = _make_service(
            response_unwrapper="nonexistent.module.unwrapper"
        )
        response = self._make_response(
            json_data={"success": True, "data": "fallback_data"},
        )
        result = client._unwrap_response(service, response)
        assert result == "fallback_data"


class TestRpcHealthCheck:
    @pytest.mark.asyncio
    async def test_health_check_success(self):
        client = RpcClient()
        mock_http = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_http.head = AsyncMock(return_value=mock_response)
        client._http = mock_http

        service = _make_service(base_url="http://test.example.com")
        with patch.object(client, "_get_service", return_value=service):
            with patch.object(client, "_resolve_base_url", return_value="http://test.example.com"):
                result = await client.health_check("test-service")
                assert result["healthy"] is True
                assert "latency_ms" in result

    @pytest.mark.asyncio
    async def test_health_check_server_error(self):
        client = RpcClient()
        mock_http = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_http.head = AsyncMock(return_value=mock_response)
        client._http = mock_http

        service = _make_service(base_url="http://test.example.com")
        with patch.object(client, "_get_service", return_value=service):
            with patch.object(client, "_resolve_base_url", return_value="http://test.example.com"):
                result = await client.health_check("test-service")
                assert result["healthy"] is False

    @pytest.mark.asyncio
    async def test_health_check_network_error(self):
        client = RpcClient()
        mock_http = MagicMock()
        mock_http.head = AsyncMock(side_effect=Exception("connection refused"))
        client._http = mock_http

        service = _make_service(base_url="http://test.example.com")
        with patch.object(client, "_get_service", return_value=service):
            with patch.object(client, "_resolve_base_url", return_value="http://test.example.com"):
                result = await client.health_check("test-service")
                assert result["healthy"] is False
                assert "connection refused" in result["message"]

    @pytest.mark.asyncio
    async def test_health_check_timeout(self):
        client = RpcClient()
        mock_http = MagicMock()
        mock_http.head = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
        client._http = mock_http

        service = _make_service(base_url="http://test.example.com")
        with patch.object(client, "_get_service", return_value=service):
            with patch.object(client, "_resolve_base_url", return_value="http://test.example.com"):
                result = await client.health_check("test-service", timeout=1.0)
                assert result["healthy"] is False


class TestRpcServiceConfig:
    def test_default_response_unwrapper(self):
        service = _make_service()
        assert service.response_unwrapper == "java_standard"

    def test_custom_auth_headers(self):
        service = _make_service(
            auth_headers={"X-API-Key": "key123", "X-Tenant": "t1"}
        )
        assert service.auth_headers == {"X-API-Key": "key123", "X-Tenant": "t1"}

    def test_no_auth_headers_default(self):
        service = _make_service()
        assert service.auth_headers is None
