"""Tests for DeerFlowClient multi-tenant isolation."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from deerflow.client import DeerFlowClient
from deerflow.config.tenant import (
    _DEFAULT_TENANT_ID,
    get_current_tenant_id,
    reset_tenant_id,
    set_current_tenant_id,
)


class TestClientTenantId:
    def test_default_tenant(self):
        client = DeerFlowClient()
        assert client._tenant_id == _DEFAULT_TENANT_ID

    def test_explicit_tenant(self):
        client = DeerFlowClient(tenant_id="acme")
        assert client._tenant_id == "acme"

    def test_invalid_tenant_raises(self):
        with pytest.raises(ValueError, match="Invalid tenant ID"):
            DeerFlowClient(tenant_id="../escape")

    def test_empty_tenant_raises(self):
        with pytest.raises(ValueError, match="Invalid tenant ID"):
            DeerFlowClient(tenant_id="")


class TestRunnableConfig:
    def test_includes_tenant_id(self):
        client = DeerFlowClient(tenant_id="acme")
        config = client._get_runnable_config("thread-1")
        assert config["configurable"]["tenant_id"] == "acme"

    def test_default_tenant_in_config(self):
        client = DeerFlowClient()
        config = client._get_runnable_config("thread-1")
        assert config["configurable"]["tenant_id"] == _DEFAULT_TENANT_ID


class TestAgentConfigKey:
    def test_different_tenants_produce_different_keys(self):
        client_a = DeerFlowClient(tenant_id="tenant-a")
        client_b = DeerFlowClient(tenant_id="tenant-b")
        config_a = client_a._get_runnable_config("t1")
        config_b = client_b._get_runnable_config("t1")

        key_a = (
            config_a["configurable"].get("model_name"),
            config_a["configurable"].get("thinking_enabled"),
            config_a["configurable"].get("is_plan_mode"),
            config_a["configurable"].get("subagent_enabled"),
            client_a._agent_name,
            client_a._tenant_id,
            None,
        )
        key_b = (
            config_b["configurable"].get("model_name"),
            config_b["configurable"].get("thinking_enabled"),
            config_b["configurable"].get("is_plan_mode"),
            config_b["configurable"].get("subagent_enabled"),
            client_b._agent_name,
            client_b._tenant_id,
            None,
        )
        assert key_a != key_b

    def test_same_tenant_same_key(self):
        client1 = DeerFlowClient(tenant_id="acme")
        client2 = DeerFlowClient(tenant_id="acme")
        config1 = client1._get_runnable_config("t1")
        config2 = client2._get_runnable_config("t1")

        key1 = (
            config1["configurable"].get("model_name"),
            config1["configurable"].get("thinking_enabled"),
            config1["configurable"].get("is_plan_mode"),
            config1["configurable"].get("subagent_enabled"),
            client1._agent_name,
            client1._tenant_id,
            None,
        )
        key2 = (
            config2["configurable"].get("model_name"),
            config2["configurable"].get("thinking_enabled"),
            config2["configurable"].get("is_plan_mode"),
            config2["configurable"].get("subagent_enabled"),
            client2._agent_name,
            client2._tenant_id,
            None,
        )
        assert key1 == key2


class TestStreamSetsContextVar:
    def test_stream_sets_tenant_context(self, tmp_path):
        client = DeerFlowClient(tenant_id="acme")

        captured_tenant = None

        def capture_tenant(*args, **kwargs):
            nonlocal captured_tenant
            captured_tenant = get_current_tenant_id()
            return []

        client._agent = MagicMock()
        with patch.object(client, "_ensure_agent"):
            with patch.object(client._agent, "stream", side_effect=capture_tenant):
                try:
                    list(client.stream("hello", thread_id="t1"))
                except Exception:
                    pass

        assert captured_tenant == "acme"
