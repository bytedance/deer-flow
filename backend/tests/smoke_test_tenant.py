"""Quick smoke test for multi-tenant isolation.

Run with: PYTHONPATH=. uv run python tests/smoke_test_tenant.py
"""

import json
import tempfile
from pathlib import Path

from deerflow.config.paths import Paths
from deerflow.config.tenant import (
    _DEFAULT_TENANT_ID,
    get_current_tenant_id,
    reset_tenant_id,
    set_current_tenant_id,
)


def test_path_isolation():
    """Verify different tenants resolve to different directories."""
    with tempfile.TemporaryDirectory() as tmp:
        paths = Paths(base_dir=tmp)

        # Default tenant
        assert paths.tenant_base_dir == Path(tmp)
        assert paths.agents_dir == Path(tmp) / "agents"
        assert paths.memory_file == Path(tmp) / "memory.json"
        assert paths.thread_dir("t1") == Path(tmp) / "threads" / "t1"

        # Named tenant
        token = set_current_tenant_id("acme")
        try:
            assert paths.tenant_base_dir == Path(tmp) / "tenants" / "acme"
            assert paths.agents_dir == Path(tmp) / "tenants" / "acme" / "agents"
            assert paths.memory_file == Path(tmp) / "tenants" / "acme" / "memory.json"
            assert paths.thread_dir("t1") == Path(tmp) / "tenants" / "acme" / "threads" / "t1"
        finally:
            reset_tenant_id(token)

        # Verify ContextVar restored
        assert get_current_tenant_id() == _DEFAULT_TENANT_ID

    print("PASS: path_isolation")


def test_agent_dir_isolation():
    """Verify same agent name in different tenants resolves to different dirs."""
    with tempfile.TemporaryDirectory() as tmp:
        paths = Paths(base_dir=tmp)

        token_a = set_current_tenant_id("tenant-a")
        try:
            dir_a = paths.agent_dir("my-agent")
        finally:
            reset_tenant_id(token_a)

        token_b = set_current_tenant_id("tenant-b")
        try:
            dir_b = paths.agent_dir("my-agent")
        finally:
            reset_tenant_id(token_b)

        assert dir_a != dir_b
        assert str(dir_a) != str(dir_b)

    print("PASS: agent_dir_isolation")


def test_memory_cache_key_isolation():
    """Verify memory cache keys include tenant_id."""
    from deerflow.agents.memory.storage import FileMemoryStorage

    assert FileMemoryStorage._cache_key() == (_DEFAULT_TENANT_ID, None)
    assert FileMemoryStorage._cache_key("agent-x") == (_DEFAULT_TENANT_ID, "agent-x")

    token = set_current_tenant_id("acme")
    try:
        assert FileMemoryStorage._cache_key() == ("acme", None)
        assert FileMemoryStorage._cache_key("agent-x") == ("acme", "agent-x")
    finally:
        reset_tenant_id(token)

    print("PASS: memory_cache_key_isolation")


def test_client_tenant_config():
    """Verify DeerFlowClient includes tenant_id in runnable config."""
    from deerflow.client import DeerFlowClient

    client = DeerFlowClient(tenant_id="acme")
    config = client._get_runnable_config("thread-1")
    assert config["configurable"]["tenant_id"] == "acme"

    client_default = DeerFlowClient()
    config_default = client_default._get_runnable_config("thread-1")
    assert config_default["configurable"]["tenant_id"] == _DEFAULT_TENANT_ID

    print("PASS: client_tenant_config")


def test_tenant_validation():
    """Verify tenant ID validation."""
    from deerflow.config.tenant import validate_tenant_id

    validate_tenant_id("default")
    validate_tenant_id("acme-corp")
    validate_tenant_id("tenant-123")

    for bad in ["../escape", "has space", "has/slash", "", "with.dot"]:
        try:
            validate_tenant_id(bad)
            assert False, f"Should have rejected: {bad!r}"
        except ValueError:
            pass

    print("PASS: tenant_validation")


if __name__ == "__main__":
    test_path_isolation()
    test_agent_dir_isolation()
    test_memory_cache_key_isolation()
    test_client_tenant_config()
    test_tenant_validation()
    print("\nAll smoke tests passed.")
