"""Tests for NacosConfig and RpcConfig model validation and singleton lifecycle."""

import pytest

from deerflow.config.nacos_config import (
    NacosConfig,
    NacosHeartbeatConfig,
    NacosServiceConfig,
    get_nacos_config,
    load_nacos_config_from_dict,
)
from deerflow.config.rpc_config import (
    RpcConfig,
    RpcEndpointConfig,
    RpcServiceConfig,
    get_rpc_config,
    load_rpc_config_from_dict,
)


class TestNacosConfigDefaults:
    def test_default_values(self):
        cfg = NacosConfig(server_addr="localhost:8848", namespace="test")
        assert cfg.server_addr == "localhost:8848"
        assert cfg.namespace == "test"
        assert cfg.group == "DEFAULT_GROUP"
        assert cfg.service.name == "deer-flow-gateway"
        assert cfg.service.port == 8001
        assert cfg.service.ip == ""
        assert cfg.service.weight == 1.0
        assert cfg.heartbeat.interval == 5
        assert cfg.heartbeat.timeout == 15
        assert cfg.retry.max_attempts == 10
        assert cfg.retry.base_delay == 1.0
        assert cfg.retry.max_delay == 60.0

    def test_service_config_constraints(self):
        svc = NacosServiceConfig(name="test-svc", port=8080)
        assert svc.name == "test-svc"

    def test_heartbeat_constraints(self):
        with pytest.raises(Exception):
            NacosHeartbeatConfig(interval=0)
        with pytest.raises(Exception):
            NacosHeartbeatConfig(interval=31)
        with pytest.raises(Exception):
            NacosHeartbeatConfig(timeout=3)

    def test_auth_fields(self):
        cfg = NacosConfig(
            server_addr="localhost:8848",
            namespace="test",
            username="nacos",
            password="nacos123",
        )
        assert cfg.username == "nacos"
        assert cfg.password == "nacos123"

    def test_auth_fields_default_none(self):
        cfg = NacosConfig(server_addr="localhost:8848", namespace="test")
        assert cfg.username is None
        assert cfg.password is None


class TestNacosConfigSingleton:
    def test_load_and_get(self):
        load_nacos_config_from_dict({"server_addr": "nacos:8848", "namespace": "ns"})
        cfg = get_nacos_config()
        assert cfg is not None
        assert cfg.server_addr == "nacos:8848"
        assert cfg.namespace == "ns"

    def test_load_none_disables(self):
        load_nacos_config_from_dict({"server_addr": "nacos:8848", "namespace": "ns"})
        load_nacos_config_from_dict(None)
        cfg = get_nacos_config()
        assert cfg is None


class TestRpcConfigDefaults:
    def test_default_values(self):
        cfg = RpcConfig()
        assert cfg.default_timeout == 30.0
        assert cfg.default_retry.max_attempts == 3
        assert cfg.default_retry.backoff_factor == 0.5
        assert cfg.services == []

    def test_service_definition(self):
        cfg = RpcConfig(services=[
            RpcServiceConfig(
                name="test-svc",
                discovery="test-discovery",
                endpoints=[
                    RpcEndpointConfig(method="getById", path="/api/{id}")
                ],
            )
        ])
        assert len(cfg.services) == 1
        svc = cfg.services[0]
        assert svc.name == "test-svc"
        assert svc.discovery == "test-discovery"
        assert svc.endpoints[0].method == "getById"
        assert svc.endpoints[0].http_method == "POST"


class TestRpcConfigSingleton:
    def test_load_and_get(self):
        load_rpc_config_from_dict({"default_timeout": 60.0, "services": []})
        cfg = get_rpc_config()
        assert cfg is not None
        assert cfg.default_timeout == 60.0

    def test_load_none_disables(self):
        load_rpc_config_from_dict({"default_timeout": 10.0, "services": []})
        load_rpc_config_from_dict(None)
        cfg = get_rpc_config()
        assert cfg is None
