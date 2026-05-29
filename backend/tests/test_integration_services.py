"""Unit tests for service layer (Task 1.8.6)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from deerflow.integrations.adapters.base import AuthContext
from deerflow.integrations.errors import IntegrationError
from deerflow.integrations.models.queries import (
    AssetCatalogQuery,
    AssetContextQuery,
    AssetOverviewQuery,
    HealthAssessmentQuery,
    TrendQuery,
)
from deerflow.integrations.routing import CapabilityRouter, ServiceResult
from deerflow.integrations.services.assessment_service import AssessmentService
from deerflow.integrations.services.asset_service import AssetService
from deerflow.integrations.services.monitoring_service import MonitoringService


def _mock_router(return_value=None, side_effect=None):
    router = MagicMock(spec=CapabilityRouter)
    if side_effect:
        router.route = AsyncMock(side_effect=side_effect)
    else:
        router.route = AsyncMock(return_value=return_value or ServiceResult(
            data=(), source_system_keys=("test_sys",),
        ))
    return router


class TestAssetService:
    @pytest.mark.asyncio
    async def test_get_catalog(self):
        router = _mock_router()
        service = AssetService(router)
        query = AssetCatalogQuery(tenant_id="t1")
        auth = AuthContext(tenant_id="t1", user_id="u1")
        result = await service.get_catalog(query, auth)
        router.route.assert_called_once_with(
            capability_key="asset.catalog", query=query, auth_context=auth,
        )
        assert isinstance(result, ServiceResult)

    @pytest.mark.asyncio
    async def test_get_context(self):
        router = _mock_router()
        service = AssetService(router)
        query = AssetContextQuery(tenant_id="t1", asset_id="A1")
        auth = AuthContext(tenant_id="t1", user_id="u1")
        await service.get_context(query, auth)
        router.route.assert_called_once_with(
            capability_key="asset.context", query=query, auth_context=auth,
        )

    @pytest.mark.asyncio
    async def test_get_overview_composite(self):
        from datetime import datetime
        from deerflow.integrations.models.asset import Asset, AssetContext
        from deerflow.integrations.models.provenance import Provenance

        prov = Provenance(
            source_system_key="ins", source_system_type="ins",
            capability_key="asset.context", fetched_at=datetime.now(),
        )
        asset = Asset(asset_id="A1", asset_code="AC1", asset_name="Pump", asset_type="pump", status="active")
        ctx = AssetContext(asset=asset)

        # Build a chain of route results
        call_count = 0

        async def route_side_effect(capability_key, query, auth_context):
            nonlocal call_count
            call_count += 1
            if capability_key == "asset.context":
                return ServiceResult(data=ctx, source_system_keys=("ins",))
            elif capability_key == "health.assessment":
                return ServiceResult(data=None, source_system_keys=("sms",))
            elif capability_key == "monitoring.alarm_history":
                return ServiceResult(data=(), source_system_keys=("ins",))
            return ServiceResult(data=None, source_system_keys=())

        router = MagicMock(spec=CapabilityRouter)
        router.route = AsyncMock(side_effect=route_side_effect)
        service = AssetService(router)
        query = AssetOverviewQuery(tenant_id="t1", asset_id="A1")
        auth = AuthContext(tenant_id="t1", user_id="u1")
        result = await service.get_overview(query, auth)
        assert result.data.asset.asset_id == "A1"
        assert call_count == 3  # context + health + alarms

    @pytest.mark.asyncio
    async def test_get_overview_health_failure(self):
        from datetime import datetime
        from deerflow.integrations.models.asset import Asset, AssetContext
        from deerflow.integrations.models.provenance import Provenance

        prov = Provenance(
            source_system_key="ins", source_system_type="ins",
            capability_key="asset.context", fetched_at=datetime.now(),
        )
        asset = Asset(asset_id="A1", asset_code="AC1", asset_name="Pump", asset_type="pump", status="active")
        ctx = AssetContext(asset=asset)

        async def route_side_effect(capability_key, query, auth_context):
            if capability_key == "asset.context":
                return ServiceResult(data=ctx, source_system_keys=("ins",))
            elif capability_key == "health.assessment":
                raise IntegrationError("health system down")
            elif capability_key == "monitoring.alarm_history":
                return ServiceResult(data=(), source_system_keys=("ins",))
            return ServiceResult(data=None, source_system_keys=())

        router = MagicMock(spec=CapabilityRouter)
        router.route = AsyncMock(side_effect=route_side_effect)
        service = AssetService(router)
        query = AssetOverviewQuery(tenant_id="t1", asset_id="A1")
        auth = AuthContext(tenant_id="t1", user_id="u1")
        # Should not raise — health failure is caught and logged
        result = await service.get_overview(query, auth)
        assert result.data.health_assessment is None


class TestMonitoringService:
    @pytest.mark.asyncio
    async def test_get_trend(self):
        from datetime import datetime, timedelta
        router = _mock_router()
        service = MonitoringService(router)
        now = datetime.now()
        query = TrendQuery(
            tenant_id="t1", asset_id="A1", measurement_point_id="MP1",
            start_time=now - timedelta(days=7), end_time=now,
        )
        auth = AuthContext(tenant_id="t1", user_id="u1")
        await service.get_trend(query, auth)
        router.route.assert_called_once_with(
            capability_key="monitoring.trend", query=query, auth_context=auth,
        )

    @pytest.mark.asyncio
    async def test_get_alarm_history(self):
        from deerflow.integrations.models.queries import AlarmHistoryQuery
        router = _mock_router()
        service = MonitoringService(router)
        query = AlarmHistoryQuery(tenant_id="t1", asset_id="A1")
        auth = AuthContext(tenant_id="t1", user_id="u1")
        await service.get_alarm_history(query, auth)
        router.route.assert_called_once_with(
            capability_key="monitoring.alarm_history", query=query, auth_context=auth,
        )


class TestAssessmentService:
    @pytest.mark.asyncio
    async def test_get_health_assessment(self):
        router = _mock_router()
        service = AssessmentService(router)
        query = HealthAssessmentQuery(tenant_id="t1", asset_id="A1")
        auth = AuthContext(tenant_id="t1", user_id="u1")
        await service.get_health_assessment(query, auth)
        router.route.assert_called_once_with(
            capability_key="health.assessment", query=query, auth_context=auth,
        )
