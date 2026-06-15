"""Tests for NacosRegistry with mocked HTTP responses."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deerflow.config.nacos_config import NacosConfig
from deerflow.rpc.nacos_registry import NacosRegistry


@pytest.fixture
def nacos_config():
    return NacosConfig(
        server_addr="localhost:8848",
        namespace="test",
        group="DEFAULT_GROUP",
    )


class TestNacosRegistryRegister:
    def test_register_success(self, nacos_config):
        registry = NacosRegistry(nacos_config)
        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.text = "ok"

        with patch.object(registry, "_resolve_ip", return_value="192.168.1.1"):
            with patch.object(registry, "_ensure_client") as mock_client:
                mock_client.return_value.post.return_value = mock_resp
                result = asyncio.run(registry.register())
                assert result is True
                assert registry.registered is True

    def test_register_failure(self, nacos_config):
        registry = NacosRegistry(nacos_config)
        mock_resp = AsyncMock()
        mock_resp.status_code = 500
        mock_resp.text = "error"

        with patch.object(registry, "_resolve_ip", return_value="192.168.1.1"):
            with patch.object(registry, "_ensure_client") as mock_client:
                mock_client.return_value.post.return_value = mock_resp
                result = asyncio.run(registry.register())
                assert result is False
                assert registry.registered is False

    def test_deregister_success(self, nacos_config):
        registry = NacosRegistry(nacos_config)
        registry._registered = True
        mock_resp = AsyncMock()
        mock_resp.status_code = 200

        with patch.object(registry, "_resolve_ip", return_value="192.168.1.1"):
            with patch.object(registry, "_ensure_client") as mock_client:
                mock_client.return_value.delete.return_value = mock_resp
                result = asyncio.run(registry.deregister())
                assert result is True
                assert registry.registered is False

    def test_deregister_when_not_registered(self, nacos_config):
        registry = NacosRegistry(nacos_config)
        result = asyncio.run(registry.deregister())
        assert result is True


class TestNacosRegistryHeartbeat:
    def test_heartbeat_when_not_registered(self, nacos_config):
        registry = NacosRegistry(nacos_config)
        result = asyncio.run(registry.send_heartbeat())
        assert result is False

    def test_heartbeat_success(self, nacos_config):
        registry = NacosRegistry(nacos_config)
        registry._registered = True
        mock_resp = AsyncMock()
        mock_resp.status_code = 200

        with patch.object(registry, "_resolve_ip", return_value="192.168.1.1"):
            with patch.object(registry, "_ensure_client") as mock_client:
                mock_client.return_value.put.return_value = mock_resp
                result = asyncio.run(registry.send_heartbeat())
                assert result is True


class TestNacosDiscovery:
    def test_discover_service(self, nacos_config):
        registry = NacosRegistry(nacos_config)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "hosts": [
                {"ip": "10.0.0.1", "port": 8080, "weight": 1.0, "healthy": True},
                {"ip": "10.0.0.2", "port": 8080, "weight": 0.5, "healthy": True},
            ]
        }

        with patch.object(registry, "_ensure_client") as mock_client:
            mock_client.return_value.get.return_value = mock_resp
            instances = asyncio.run(registry.discover_service("test-service"))
            assert len(instances) == 2
            assert instances[0]["ip"] == "10.0.0.1"
            assert instances[1]["port"] == 8080

    def test_discover_service_empty(self, nacos_config):
        registry = NacosRegistry(nacos_config)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"hosts": []}

        with patch.object(registry, "_ensure_client") as mock_client:
            mock_client.return_value.get.return_value = mock_resp
            instances = asyncio.run(registry.discover_service("test-service"))
            assert instances == []


class TestNacosAuth:
    @pytest.fixture
    def auth_config(self):
        return NacosConfig(
            server_addr="localhost:8848",
            namespace="test",
            username="nacos",
            password="nacos123",
        )

    def test_get_auth_params_no_auth_configured(self, nacos_config):
        registry = NacosRegistry(nacos_config)
        result = asyncio.run(registry._get_auth_params())
        assert result == {}

    def test_login_success(self, auth_config):
        registry = NacosRegistry(auth_config)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"accessToken": "token-abc", "tokenTtl": 18000}

        with patch.object(registry, "_ensure_client") as mock_client:
            mock_client.return_value.post.return_value = mock_resp
            token = asyncio.run(registry._login())
            assert token == "token-abc"

    def test_login_failure(self, auth_config):
        registry = NacosRegistry(auth_config)
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.text = "invalid credentials"

        with patch.object(registry, "_ensure_client") as mock_client:
            mock_client.return_value.post.return_value = mock_resp
            token = asyncio.run(registry._login())
            assert token is None

    def test_get_auth_params_caches_token(self, auth_config):
        registry = NacosRegistry(auth_config)
        registry._access_token = "cached-token"
        result = asyncio.run(registry._get_auth_params())
        assert result == {"accessToken": "cached-token"}

    def test_register_includes_access_token(self, auth_config):
        registry = NacosRegistry(auth_config)
        registry._access_token = "token-xyz"
        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.text = "ok"

        with patch.object(registry, "_resolve_ip", return_value="192.168.1.1"):
            with patch.object(registry, "_ensure_client") as mock_client:
                mock_client.return_value.post.return_value = mock_resp
                result = asyncio.run(registry.register())
                assert result is True
                call_kwargs = mock_client.return_value.post.call_args
                assert "accessToken" in call_kwargs.kwargs["params"]
                assert call_kwargs.kwargs["params"]["accessToken"] == "token-xyz"

    def test_discover_includes_access_token(self, auth_config):
        registry = NacosRegistry(auth_config)
        registry._access_token = "token-xyz"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"hosts": []}

        with patch.object(registry, "_ensure_client") as mock_client:
            mock_client.return_value.get.return_value = mock_resp
            asyncio.run(registry.discover_service("test-service"))
            call_kwargs = mock_client.return_value.get.call_args
            assert call_kwargs.kwargs["params"]["accessToken"] == "token-xyz"
