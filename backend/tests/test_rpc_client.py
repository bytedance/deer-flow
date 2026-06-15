"""Tests for RpcClient with mocked HTTP responses."""

import asyncio
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from deerflow.config.nacos_config import load_nacos_config_from_dict
from deerflow.config.rpc_config import (
    load_rpc_config_from_dict,
)
from deerflow.rpc.rpc_client import RpcClient, RpcConnectionError, RpcError, RpcTimeoutError


@pytest.fixture(autouse=True)
def setup_rpc_config():
    load_rpc_config_from_dict({
        "default_timeout": 30.0,
        "services": [
            {
                "name": "test-service",
                "base_url": "http://localhost:8080",
                "endpoints": [
                    {"method": "getUser", "path": "/api/users/{id}", "http_method": "GET"},
                    {"method": "createUser", "path": "/api/users", "http_method": "POST"},
                ],
            }
        ],
    })
    yield
    load_rpc_config_from_dict(None)


class TestRpcClient:
    def test_call_get_success(self):
        client = RpcClient()
        mock_resp = AsyncMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.text = '{"id": 1, "name": "test"}'
        mock_resp.json.return_value = {"id": 1, "name": "test"}

        with patch.object(client, "_ensure_client") as mock_client_fn:
            mock_http = AsyncMock()
            mock_http.get.return_value = mock_resp
            mock_client_fn.return_value = mock_http

            result = asyncio.run(client.call("test-service", "getUser", {"id": 1}))
            assert result == {"id": 1, "name": "test"}

    def test_call_post_success(self):
        client = RpcClient()
        mock_resp = AsyncMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.text = '{"id": 2}'
        mock_resp.json.return_value = {"id": 2}

        with patch.object(client, "_ensure_client") as mock_client_fn:
            mock_http = AsyncMock()
            mock_http.post.return_value = mock_resp
            mock_client_fn.return_value = mock_http

            result = asyncio.run(client.call("test-service", "createUser", {"name": "foo"}))
            assert result == {"id": 2}

    def test_call_service_not_found(self):
        client = RpcClient()
        with pytest.raises(RpcError, match="not found"):
            asyncio.run(client.call("unknown-service", "getUser", {}))

    def test_call_method_not_found(self):
        client = RpcClient()
        with pytest.raises(RpcError, match="not found"):
            asyncio.run(client.call("test-service", "unknownMethod", {}))

    def test_call_returns_error_status(self):
        client = RpcClient()
        mock_resp = AsyncMock(spec=httpx.Response)
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"

        with patch.object(client, "_ensure_client") as mock_client_fn:
            mock_http = AsyncMock()
            mock_http.get.return_value = mock_resp
            mock_client_fn.return_value = mock_http

            with pytest.raises(RpcError, match="500"):
                asyncio.run(client.call("test-service", "getUser", {"id": 1}))

    def test_call_timeout(self):
        client = RpcClient()
        with patch.object(client, "_ensure_client") as mock_client_fn:
            mock_http = AsyncMock()
            mock_http.get.side_effect = httpx.TimeoutException("timeout")
            mock_client_fn.return_value = mock_http

            with pytest.raises(RpcTimeoutError):
                asyncio.run(client.call("test-service", "getUser", {"id": 1}))

    def test_call_connection_error(self):
        client = RpcClient()
        with patch.object(client, "_ensure_client") as mock_client_fn:
            mock_http = AsyncMock()
            mock_http.get.side_effect = httpx.ConnectError("refused")
            mock_client_fn.return_value = mock_http

            with pytest.raises(RpcConnectionError, match="RPC call failed after"):
                asyncio.run(client.call("test-service", "getUser", {"id": 1}))


class TestRpcClientNacosDiscovery:
    @pytest.fixture(autouse=True)
    def setup_nacos(self):
        load_nacos_config_from_dict({"server_addr": "localhost:8848", "namespace": "test"})
        yield
        load_nacos_config_from_dict(None)

    def test_resolve_via_nacos_discovery(self):
        load_rpc_config_from_dict({
            "default_timeout": 30.0,
            "services": [
                {"name": "discovery-svc", "discovery": "java-service", "endpoints": [{"method": "ping", "path": "/ping"}]}
            ],
        })
        client = RpcClient()
        mock_registry = AsyncMock()
        mock_registry.discover_service.return_value = [{"ip": "10.0.0.5", "port": 8080, "weight": 1.0, "healthy": True}]

        svc = client._get_service("discovery-svc")
        with patch.object(client, "_get_registry", return_value=mock_registry):
            base_url = asyncio.run(client._resolve_base_url(svc))
            assert base_url == "http://10.0.0.5:8080"


class TestRpcClientCallRaw:
    def test_call_raw_get_success(self):
        client = RpcClient()
        mock_resp = AsyncMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.text = '{"data": [{"id": 1, "name": "pump-01"}]}'
        mock_resp.json.return_value = {"data": [{"id": 1, "name": "pump-01"}]}

        with patch.object(client, "_ensure_client") as mock_client_fn:
            mock_http = AsyncMock()
            mock_http.get.return_value = mock_resp
            mock_client_fn.return_value = mock_http

            result = asyncio.run(client.call_raw(
                "test-service",
                "/ins-bus-rpc/machineModel/getMachineInfoByIds",
                "GET",
                {"machineIds": "1,2,3"},
            ))
            assert result == {"data": [{"id": 1, "name": "pump-01"}]}

    def test_call_raw_post_success(self):
        client = RpcClient()
        mock_resp = AsyncMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.text = '{"success": true}'
        mock_resp.json.return_value = {"success": True}

        with patch.object(client, "_ensure_client") as mock_client_fn:
            mock_http = AsyncMock()
            mock_http.post.return_value = mock_resp
            mock_client_fn.return_value = mock_http

            result = asyncio.run(client.call_raw(
                "test-service",
                "/api/create",
                "POST",
                {"name": "test"},
            ))
            assert result == {"success": True}

    def test_call_raw_returns_error_status(self):
        client = RpcClient()
        mock_resp = AsyncMock(spec=httpx.Response)
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"

        with patch.object(client, "_ensure_client") as mock_client_fn:
            mock_http = AsyncMock()
            mock_http.get.return_value = mock_resp
            mock_client_fn.return_value = mock_http

            with pytest.raises(RpcError, match="500"):
                asyncio.run(client.call_raw("test-service", "/api/test", "GET"))
