"""Tests for NacosRegistry with mocked HTTP responses."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx

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
