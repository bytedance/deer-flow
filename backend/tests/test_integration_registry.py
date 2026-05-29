"""Unit tests for IntegrationRegistry (Tasks 1.3.11, 1.3.12)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deerflow.integrations.adapters.base import AuthContext, HealthStatus
from deerflow.integrations.registry import IntegrationRegistry, get_integration_registry


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset singleton before each test."""
    IntegrationRegistry._instance = None
    IntegrationRegistry._initialized = False
    yield
    IntegrationRegistry._instance = None
    IntegrationRegistry._initialized = False


def _mock_adapter(system_key: str, system_type: str = "ins"):
    adapter = MagicMock()
    adapter.system_key = system_key
    adapter.system_type = system_type
    adapter.initialize = AsyncMock()
    adapter.shutdown = AsyncMock()
    adapter.health_check = AsyncMock(
        return_value=HealthStatus(
            healthy=True,
            latency_ms=10,
            message="OK",
            checked_at=None,
        )
    )
    adapter.call = AsyncMock(return_value=())
    return adapter


class TestRegistrySingleton:
    def test_singleton_identity(self):
        r1 = get_integration_registry()
        r2 = get_integration_registry()
        assert r1 is r2

    def test_singleton_reset(self):
        r1 = get_integration_registry()
        IntegrationRegistry._instance = None
        IntegrationRegistry._initialized = False
        r2 = get_integration_registry()
        assert r1 is not r2


class TestRegistryRegister:
    def test_register_adapter(self):
        registry = IntegrationRegistry()
        adapter = _mock_adapter("ins_prod")
        registry.register(adapter)
        assert registry.get("ins_prod") is adapter

    def test_register_multiple(self):
        registry = IntegrationRegistry()
        a1 = _mock_adapter("ins_prod")
        a2 = _mock_adapter("sms_prod", "sms")
        registry.register(a1)
        registry.register(a2)
        assert len(registry.list_all()) == 2

    def test_get_nonexistent(self):
        registry = IntegrationRegistry()
        assert registry.get("nonexistent") is None

    def test_get_for_type(self):
        registry = IntegrationRegistry()
        registry.register(_mock_adapter("ins1", "ins"))
        registry.register(_mock_adapter("ins2", "ins"))
        registry.register(_mock_adapter("sms1", "sms"))
        assert len(registry.get_for_type("ins")) == 2
        assert len(registry.get_for_type("sms")) == 1
        assert len(registry.get_for_type("crm")) == 0


class TestRegistryLifecycle:
    @pytest.mark.asyncio
    async def test_initialize_all(self):
        registry = IntegrationRegistry()
        a1 = _mock_adapter("ins1")
        a2 = _mock_adapter("sms1")
        registry.register(a1)
        registry.register(a2)
        await registry.initialize_all()
        a1.initialize.assert_called_once()
        a2.initialize.assert_called_once()

    @pytest.mark.asyncio
    async def test_initialize_error_isolation(self):
        registry = IntegrationRegistry()
        a1 = _mock_adapter("ins1")
        a2 = _mock_adapter("sms1")
        a1.initialize.side_effect = Exception("boom")
        registry.register(a1)
        registry.register(a2)
        await registry.initialize_all()
        # a2 should still initialize despite a1 failure
        a2.initialize.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_all(self):
        registry = IntegrationRegistry()
        a1 = _mock_adapter("ins1")
        a2 = _mock_adapter("sms1")
        registry.register(a1)
        registry.register(a2)
        await registry.shutdown_all()
        a1.shutdown.assert_called_once()
        a2.shutdown.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_reverse_order(self):
        registry = IntegrationRegistry()
        call_order = []
        a1 = _mock_adapter("first")
        a2 = _mock_adapter("second")
        a1.shutdown.side_effect = lambda: call_order.append("first")
        a2.shutdown.side_effect = lambda: call_order.append("second")
        registry.register(a1)
        registry.register(a2)
        await registry.shutdown_all()
        assert call_order == ["second", "first"]


class TestRegistryHealthCheck:
    @pytest.mark.asyncio
    async def test_health_check_all(self):
        registry = IntegrationRegistry()
        a1 = _mock_adapter("ins1")
        a2 = _mock_adapter("sms1")
        registry.register(a1)
        registry.register(a2)
        results = await registry.health_check_all()
        assert len(results) == 2
        assert results["ins1"].healthy is True
        assert results["sms1"].healthy is True

    @pytest.mark.asyncio
    async def test_health_check_failure_isolation(self):
        registry = IntegrationRegistry()
        a1 = _mock_adapter("ins1")
        a2 = _mock_adapter("sms1")
        a1.health_check.side_effect = Exception("network error")
        registry.register(a1)
        registry.register(a2)
        results = await registry.health_check_all()
        assert len(results) == 2
        assert results["ins1"].healthy is False
        assert results["sms1"].healthy is True

    @pytest.mark.asyncio
    async def test_health_check_caches_status(self):
        registry = IntegrationRegistry()
        a1 = _mock_adapter("ins1")
        registry.register(a1)
        await registry.health_check_all()
        status = registry.get_health_status("ins1")
        assert status is not None
        assert status.healthy is True

    @pytest.mark.asyncio
    async def test_health_check_empty_registry(self):
        registry = IntegrationRegistry()
        results = await registry.health_check_all()
        assert results == {}


class TestHealthCheckScheduler:
    @pytest.mark.asyncio
    async def test_scheduler_starts_and_stops(self):
        registry = IntegrationRegistry()
        registry.start_health_check_scheduler(interval=0.05)
        assert registry._health_check_task is not None
        # Stop by cancelling
        await registry.shutdown_all()
        assert registry._health_check_task is None or registry._health_check_task.done()

    @pytest.mark.asyncio
    async def test_scheduler_idempotent(self):
        registry = IntegrationRegistry()
        registry.start_health_check_scheduler(interval=60.0)
        task1 = registry._health_check_task
        registry.start_health_check_scheduler(interval=60.0)
        task2 = registry._health_check_task
        assert task1 is task2  # same task, not restarted
        await registry.shutdown_all()
