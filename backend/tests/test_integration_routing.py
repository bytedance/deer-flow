"""Unit tests for CapabilityRouter and EntityLinkResolver (Tasks 1.4.8, 1.4.9)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from deerflow.integrations.adapters.base import AuthContext
from deerflow.integrations.config import CapabilityRouteConfig
from deerflow.integrations.entity_link import EntityLinkResolver
from deerflow.integrations.errors import (
    CapabilityRouteNotFoundError,
    EntityLinkNotFound,
    IntegrationError,
)
from deerflow.integrations.routing import CapabilityRouter, ServiceResult


def _mock_adapter(system_key: str, return_value=()):
    adapter = MagicMock()
    adapter.system_key = system_key
    adapter.call = AsyncMock(return_value=return_value)
    return adapter


def _mock_registry(*adapters):
    registry = MagicMock()
    adapter_map = {a.system_key: a for a in adapters}
    registry.get.side_effect = lambda k: adapter_map.get(k)
    return registry


class TestCapabilityRouterBasic:
    @pytest.mark.asyncio
    async def test_simple_route(self):
        adapter = _mock_adapter("ins_prod", return_value="trend_data")
        registry = _mock_registry(adapter)
        routes = {
            "monitoring.trend": CapabilityRouteConfig(
                capability_key="monitoring.trend",
                primary_system_key="ins_prod",
            ),
        }
        router = CapabilityRouter(registry, routes)
        auth = AuthContext(tenant_id="t1", user_id="u1")
        result = await router.route("monitoring.trend", {"asset_id": "A1"}, auth)
        assert isinstance(result, ServiceResult)
        assert result.data == "trend_data"
        assert result.source_system_keys == ("ins_prod",)

    @pytest.mark.asyncio
    async def test_route_not_found(self):
        registry = _mock_registry()
        router = CapabilityRouter(registry, {})
        auth = AuthContext(tenant_id="t1", user_id="u1")
        with pytest.raises(CapabilityRouteNotFoundError):
            await router.route("nonexistent.cap", {}, auth)

    @pytest.mark.asyncio
    async def test_disabled_route(self):
        registry = _mock_registry()
        routes = {
            "test.cap": CapabilityRouteConfig(
                capability_key="test.cap",
                primary_system_key="sys1",
                enabled=False,
            ),
        }
        router = CapabilityRouter(registry, routes)
        auth = AuthContext(tenant_id="t1", user_id="u1")
        with pytest.raises(CapabilityRouteNotFoundError):
            await router.route("test.cap", {}, auth)


class TestCapabilityRouterFallback:
    @pytest.mark.asyncio
    async def test_fallback_on_primary_failure(self):
        primary = _mock_adapter("ins_prod")
        primary.call.side_effect = Exception("primary down")
        fallback = _mock_adapter("ins_backup", return_value="fallback_data")
        registry = _mock_registry(primary, fallback)
        routes = {
            "test.cap": CapabilityRouteConfig(
                capability_key="test.cap",
                primary_system_key="ins_prod",
                fallback_system_keys=["ins_backup"],
            ),
        }
        router = CapabilityRouter(registry, routes)
        auth = AuthContext(tenant_id="t1", user_id="u1")
        result = await router.route("test.cap", {}, auth)
        assert result.data == "fallback_data"
        assert result.source_system_keys == ("ins_backup",)

    @pytest.mark.asyncio
    async def test_all_fail_raises_error(self):
        primary = _mock_adapter("ins_prod")
        primary.call.side_effect = Exception("down")
        fallback = _mock_adapter("ins_backup")
        fallback.call.side_effect = Exception("also down")
        registry = _mock_registry(primary, fallback)
        routes = {
            "test.cap": CapabilityRouteConfig(
                capability_key="test.cap",
                primary_system_key="ins_prod",
                fallback_system_keys=["ins_backup"],
            ),
        }
        router = CapabilityRouter(registry, routes)
        auth = AuthContext(tenant_id="t1", user_id="u1")
        with pytest.raises(IntegrationError, match="All adapters failed"):
            await router.route("test.cap", {}, auth)

    @pytest.mark.asyncio
    async def test_fallback_chain_order(self):
        primary = _mock_adapter("p")
        primary.call.side_effect = Exception("down")
        fb1 = _mock_adapter("fb1")
        fb1.call.side_effect = Exception("down")
        fb2 = _mock_adapter("fb2", return_value="fb2_data")
        registry = _mock_registry(primary, fb1, fb2)
        routes = {
            "test.cap": CapabilityRouteConfig(
                capability_key="test.cap",
                primary_system_key="p",
                fallback_system_keys=["fb1", "fb2"],
            ),
        }
        router = CapabilityRouter(registry, routes)
        auth = AuthContext(tenant_id="t1", user_id="u1")
        result = await router.route("test.cap", {}, auth)
        assert result.data == "fb2_data"


class TestCapabilityRouterEnrich:
    @pytest.mark.asyncio
    async def test_enrich_success(self):
        primary = _mock_adapter("ins_prod", return_value="primary_data")
        enrich = _mock_adapter("sms_prod", return_value="enrich_data")
        registry = _mock_registry(primary, enrich)
        routes = {
            "test.cap": CapabilityRouteConfig(
                capability_key="test.cap",
                primary_system_key="ins_prod",
                enrich_system_keys=["sms_prod"],
                merge_policy="primary_plus_enrich",
            ),
        }
        router = CapabilityRouter(registry, routes)
        auth = AuthContext(tenant_id="t1", user_id="u1")
        result = await router.route("test.cap", {}, auth)
        assert "ins_prod" in result.source_system_keys
        assert "sms_prod" in result.source_system_keys

    @pytest.mark.asyncio
    async def test_enrich_partial_failure(self):
        primary = _mock_adapter("ins_prod", return_value="primary_data")
        enrich_ok = _mock_adapter("sms_prod", return_value="enrich_data")
        enrich_fail = _mock_adapter("erp_prod")
        enrich_fail.call.side_effect = Exception("erp down")
        registry = _mock_registry(primary, enrich_ok, enrich_fail)
        routes = {
            "test.cap": CapabilityRouteConfig(
                capability_key="test.cap",
                primary_system_key="ins_prod",
                enrich_system_keys=["sms_prod", "erp_prod"],
                partial_failure_policy="return_partial",
            ),
        }
        router = CapabilityRouter(registry, routes)
        auth = AuthContext(tenant_id="t1", user_id="u1")
        result = await router.route("test.cap", {}, auth)
        assert result.is_partial
        assert len(result.partial_failures) == 1
        assert result.partial_failures[0].system_key == "erp_prod"

    @pytest.mark.asyncio
    async def test_enrich_fail_all_policy(self):
        primary = _mock_adapter("ins_prod", return_value="primary_data")
        enrich_fail = _mock_adapter("sms_prod")
        enrich_fail.call.side_effect = Exception("down")
        registry = _mock_registry(primary, enrich_fail)
        routes = {
            "test.cap": CapabilityRouteConfig(
                capability_key="test.cap",
                primary_system_key="ins_prod",
                enrich_system_keys=["sms_prod"],
                partial_failure_policy="fail_all",
            ),
        }
        router = CapabilityRouter(registry, routes)
        auth = AuthContext(tenant_id="t1", user_id="u1")
        with pytest.raises(IntegrationError):
            await router.route("test.cap", {}, auth)


class TestCapabilityRouterMergePolicy:
    @pytest.mark.asyncio
    async def test_primary_only_policy(self):
        primary = _mock_adapter("ins_prod", return_value="primary_data")
        enrich = _mock_adapter("sms_prod", return_value="enrich_data")
        registry = _mock_registry(primary, enrich)
        routes = {
            "test.cap": CapabilityRouteConfig(
                capability_key="test.cap",
                primary_system_key="ins_prod",
                enrich_system_keys=["sms_prod"],
                merge_policy="primary_only",
            ),
        }
        router = CapabilityRouter(registry, routes)
        auth = AuthContext(tenant_id="t1", user_id="u1")
        result = await router.route("test.cap", {}, auth)
        assert result.data == "primary_data"

    @pytest.mark.asyncio
    async def test_concatenate_policy(self):
        primary = _mock_adapter("ins_prod", return_value="primary_data")
        enrich = _mock_adapter("sms_prod", return_value="enrich_data")
        registry = _mock_registry(primary, enrich)
        routes = {
            "test.cap": CapabilityRouteConfig(
                capability_key="test.cap",
                primary_system_key="ins_prod",
                enrich_system_keys=["sms_prod"],
                merge_policy="concatenate",
            ),
        }
        router = CapabilityRouter(registry, routes)
        auth = AuthContext(tenant_id="t1", user_id="u1")
        result = await router.route("test.cap", {}, auth)
        assert result.data == ["primary_data", "enrich_data"]


# ---------------------------------------------------------------------------
# EntityLinkResolver (Task 1.4.9)
# ---------------------------------------------------------------------------


def _make_links(canonical_id, entity_type, entries, status="active"):
    from deerflow.integrations.config import EntityLinkConfig, EntityLinkEntry

    return EntityLinkConfig(
        tenant_id="t1",
        entity_type=entity_type,
        canonical_id=canonical_id,
        links=[EntityLinkEntry(**e) for e in entries],
        status=status,
    )


class TestEntityLinkResolver:
    def test_resolve_basic(self):
        link = _make_links("asset:t1:pump-001", "asset", [
            {"system_key": "ins_prod", "remote_id": "INS-001", "is_primary": True},
            {"system_key": "sms_prod", "remote_id": "SMS-001"},
        ])
        resolver = EntityLinkResolver([link])
        assert resolver.resolve("asset:t1:pump-001", "ins_prod") == "INS-001"
        assert resolver.resolve("asset:t1:pump-001", "sms_prod") == "SMS-001"

    def test_resolve_not_found(self):
        resolver = EntityLinkResolver([])
        with pytest.raises(EntityLinkNotFound):
            resolver.resolve("nonexistent", "ins_prod")

    def test_resolve_wrong_system(self):
        link = _make_links("c1", "asset", [
            {"system_key": "ins_prod", "remote_id": "R1"},
        ])
        resolver = EntityLinkResolver([link])
        with pytest.raises(EntityLinkNotFound):
            resolver.resolve("c1", "sms_prod")

    def test_resolve_confidence_filter(self):
        link = _make_links("c1", "asset", [
            {"system_key": "ins_prod", "remote_id": "R1", "confidence": 0.5},
        ])
        resolver = EntityLinkResolver([link])
        # Low threshold passes
        assert resolver.resolve("c1", "ins_prod", min_confidence=0.3) == "R1"
        # High threshold fails
        with pytest.raises(EntityLinkNotFound, match="below threshold"):
            resolver.resolve("c1", "ins_prod", min_confidence=0.9)

    def test_resolve_by_remote(self):
        link = _make_links("asset:t1:pump-001", "asset", [
            {"system_key": "ins_prod", "remote_id": "INS-001"},
        ])
        resolver = EntityLinkResolver([link])
        result = resolver.resolve_by_remote("asset", "ins_prod", "INS-001")
        assert result == "asset:t1:pump-001"

    def test_resolve_by_remote_not_found(self):
        resolver = EntityLinkResolver([])
        with pytest.raises(EntityLinkNotFound):
            resolver.resolve_by_remote("asset", "ins_prod", "MISSING")

    def test_inactive_links_excluded(self):
        link = _make_links("c1", "asset", [
            {"system_key": "ins_prod", "remote_id": "R1"},
        ], status="inactive")
        resolver = EntityLinkResolver([link])
        with pytest.raises(EntityLinkNotFound):
            resolver.resolve("c1", "ins_prod")

    def test_get_all_links(self):
        link = _make_links("c1", "asset", [
            {"system_key": "ins_prod", "remote_id": "R1", "confidence": 1.0},
            {"system_key": "sms_prod", "remote_id": "R2", "confidence": 0.9},
        ])
        resolver = EntityLinkResolver([link])
        links = resolver.get_all_links("c1")
        assert len(links) == 2
        assert ("ins_prod", "R1", 1.0) in links

    def test_get_all_links_missing(self):
        resolver = EntityLinkResolver([])
        assert resolver.get_all_links("nonexistent") == []
