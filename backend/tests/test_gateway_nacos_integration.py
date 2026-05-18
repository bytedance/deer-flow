"""Integration tests for Gateway lifespan Nacos hooks."""

import pytest

from deerflow.config.nacos_config import NacosConfig, load_nacos_config_from_dict


class TestGatewayNacosLifespan:
    def test_nacos_disabled_when_config_is_none(self):
        load_nacos_config_from_dict(None)
        from deerflow.config.nacos_config import get_nacos_config

        assert get_nacos_config() is None

    def test_nacos_registry_created_when_configured(self):
        from deerflow.rpc.nacos_registry import NacosRegistry

        cfg = NacosConfig(server_addr="localhost:8848", namespace="test")
        registry = NacosRegistry(cfg)
        assert registry is not None
        assert not registry.registered

    def test_lifespan_startup_call_flow(self):
        load_nacos_config_from_dict({"server_addr": "localhost:8848", "namespace": "test"})

        from deerflow.config.nacos_config import get_nacos_config

        cfg = get_nacos_config()
        assert cfg is not None
        assert cfg.server_addr == "localhost:8848"
