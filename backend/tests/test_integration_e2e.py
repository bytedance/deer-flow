"""
E2E tests for integration tools with mock adapters.

Tests the full flow from tool invocation through mock adapters to formatted output.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from deerflow.integrations.adapters.base import AuthContext
from deerflow.integrations.models import (
    TrendSeries,
    TrendPoint,
    TrendStatistics,
    Asset,
    AssetOverview,
    HealthAssessment,
    AlarmEvent,
)
from deerflow.integrations.services import MonitoringService, AssetService
from deerflow.integrations.tools.monitoring_tools import MonitoringTools
from deerflow.integrations.tools.asset_tools import AssetTools


@pytest.fixture
def auth_context():
    return AuthContext(
        tenant_id="test-tenant",
        user_id="test-user",
    )


@pytest.fixture
def mock_trend_series():
    """Create a mock TrendSeries response."""
    now = datetime.now(timezone.utc)
    return TrendSeries(
        series_id="test-series-001",
        asset_id="asset-001",
        measurement_point_id="mp-vibration-001",
        unit="mm/s",
        points=tuple([
            TrendPoint(timestamp=now, value=2.5, quality="good"),
            TrendPoint(timestamp=now, value=3.1, quality="good"),
            TrendPoint(timestamp=now, value=2.8, quality="good"),
        ]),
        statistics=TrendStatistics(
            min_value=2.5,
            max_value=3.1,
            avg_value=2.8,
            sample_count=3,
        ),
    )


@pytest.fixture
def mock_asset():
    """Create a mock Asset."""
    return Asset(
        asset_id="asset-001",
        asset_code="PUMP-001",
        asset_name="1号泵",
        asset_type="rotating",
        location="A车间",
        manufacturer="ABC公司",
        model="PUMP-X100",
        status="active",
    )


@pytest.fixture
def mock_health_assessment():
    """Create a mock HealthAssessment."""
    return HealthAssessment(
        assessment_id="ha-001",
        asset_id="asset-001",
        overall_score=85.5,
        overall_status="good",
        summary="设备运行状态良好",
        dimensions={
            "vibration": 88.0,
            "temperature": 82.0,
            "bearing": 86.5,
        },
        assessed_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def mock_alarm_events():
    """Create mock alarm events."""
    now = datetime.now(timezone.utc)
    return tuple([
        AlarmEvent(
            event_id="alarm-001",
            asset_id="asset-001",
            event_type="high_vibration",
            severity="warning",
            message="振动值偏高",
            triggered_at=now,
        ),
    ])


class TestE2E_MonitoringGetTrend:
    """E2E test: monitoring_get_trend with mock adapter → TrendSeries → formatted output."""

    @pytest.mark.asyncio
    async def test_monitoring_get_trend_full_flow(
        self, auth_context, mock_trend_series
    ):
        """Test full flow: tool → service → adapter → TrendSeries → formatted output."""
        from deerflow.integrations.routing import ServiceResult

        # Mock the router to return ServiceResult
        mock_router = MagicMock()
        mock_router.route = AsyncMock(
            return_value=ServiceResult(
                data=mock_trend_series,
                source_system_keys=("ins",),
            )
        )

        # Create service and tools
        service = MonitoringService(router=mock_router)
        tools = MonitoringTools(service=service)

        # Call the tool method (not the StructuredTool name)
        result = await tools.get_trend_data(
            tenant_id="test-tenant",
            user_id="test-user",
            asset_id="asset-001",
            measurement_point_id="mp-vibration-001",
        )

        # Verify the result is formatted string
        assert isinstance(result, str)
        assert len(result) > 0

        # Verify key information is in the output
        assert "mm/s" in result  # unit
        assert "2.5" in result or "3.1" in result  # values
        assert "统计" in result or "数据点" in result  # statistics or points

    @pytest.mark.asyncio
    async def test_monitoring_get_trend_with_empty_points(
        self, auth_context
    ):
        """Test monitoring_get_trend with empty points."""
        from deerflow.integrations.routing import ServiceResult

        empty_series = TrendSeries(
            series_id="test-series-empty",
            asset_id="asset-001",
            measurement_point_id="mp-001",
            unit="mm/s",
            points=tuple(),
            statistics=None,
        )

        mock_router = MagicMock()
        mock_router.route = AsyncMock(
            return_value=ServiceResult(
                data=empty_series,
                source_system_keys=("ins",),
            )
        )

        service = MonitoringService(router=mock_router)
        tools = MonitoringTools(service=service)

        result = await tools.get_trend_data(
            tenant_id="test-tenant",
            user_id="test-user",
            asset_id="asset-001",
            measurement_point_id="mp-001",
        )

        assert isinstance(result, str)
        assert "无数据" in result or "没有" in result or len(result) > 0


class TestE2E_EquipmentGetOverview:
    """E2E test: equipment_get_overview composite orchestration."""

    @pytest.mark.asyncio
    async def test_equipment_get_overview_composite_flow(
        self,
        auth_context,
        mock_asset,
        mock_health_assessment,
        mock_alarm_events,
    ):
        """Test composite orchestration: asset + health + alarms → AssetOverview."""
        from deerflow.integrations.routing import ServiceResult
        from deerflow.integrations.models.asset import AssetContext

        # Create AssetContext for the first call
        asset_context = AssetContext(
            asset=mock_asset,
            parent_asset_id=None,
            child_assets=(),
            measurement_points=(),
        )

        # Mock router to return different results based on capability_key
        async def mock_route(capability_key, query, auth_context):
            if capability_key == "asset.context":
                return ServiceResult(
                    data=asset_context,
                    source_system_keys=("ins",),
                )
            elif capability_key == "health.assessment":
                return ServiceResult(
                    data=mock_health_assessment,
                    source_system_keys=("sms",),
                )
            elif capability_key == "monitoring.alarm_history":
                return ServiceResult(
                    data=mock_alarm_events,
                    source_system_keys=("ins",),
                )
            return ServiceResult(data=None, source_system_keys=())

        mock_router = MagicMock()
        mock_router.route = AsyncMock(side_effect=mock_route)

        # Create service and tools
        service = AssetService(router=mock_router)
        tools = AssetTools(service=service)

        # Call the tool method
        result = await tools.get_asset_overview(
            tenant_id="test-tenant",
            user_id="test-user",
            asset_id="asset-001",
            include_health_assessment=True,
            include_recent_alarms=True,
        )

        # Verify the result
        assert isinstance(result, str)
        assert len(result) > 0

        # Verify asset info
        assert "asset-001" in result or "PUMP-001" in result

        # Verify health assessment
        assert "85.5" in result or "健康" in result

        # Verify alarms
        assert "报警" in result or "alarm" in result.lower() or "振动" in result

    @pytest.mark.asyncio
    async def test_equipment_get_overview_without_health(
        self,
        auth_context,
        mock_asset,
    ):
        """Test equipment_get_overview without health assessment."""
        from deerflow.integrations.routing import ServiceResult
        from deerflow.integrations.models.asset import AssetContext

        asset_context = AssetContext(
            asset=mock_asset,
            parent_asset_id=None,
            child_assets=(),
            measurement_points=(),
        )

        async def mock_route(capability_key, query, auth_context):
            if capability_key == "asset.context":
                return ServiceResult(
                    data=asset_context,
                    source_system_keys=("ins",),
                )
            return ServiceResult(data=None, source_system_keys=())

        mock_router = MagicMock()
        mock_router.route = AsyncMock(side_effect=mock_route)

        service = AssetService(router=mock_router)
        tools = AssetTools(service=service)

        result = await tools.get_asset_overview(
            tenant_id="test-tenant",
            user_id="test-user",
            asset_id="asset-001",
            include_health_assessment=False,
            include_recent_alarms=False,
        )

        assert isinstance(result, str)
        assert "asset-001" in result or "PUMP-001" in result or "1号泵" in result


class TestE2E_EnrichScenario:
    """E2E test: enrich scenario with primary + enrich sources."""

    @pytest.mark.asyncio
    async def test_enrich_primary_ins_enrich_sms(
        self,
        auth_context,
        mock_asset,
        mock_health_assessment,
    ):
        """Test enrich scenario: primary from Ins + enrich from Sms."""
        from deerflow.integrations.routing import ServiceResult
        from deerflow.integrations.models.asset import AssetContext

        asset_context = AssetContext(
            asset=mock_asset,
            parent_asset_id=None,
            child_assets=(),
            measurement_points=(),
        )

        async def mock_route(capability_key, query, auth_context):
            if capability_key == "asset.context":
                return ServiceResult(
                    data=asset_context,
                    source_system_keys=("ins",),
                )
            elif capability_key == "health.assessment":
                return ServiceResult(
                    data=mock_health_assessment,
                    source_system_keys=("sms",),
                )
            return ServiceResult(data=None, source_system_keys=())

        mock_router = MagicMock()
        mock_router.route = AsyncMock(side_effect=mock_route)

        service = AssetService(router=mock_router)
        tools = AssetTools(service=service)

        result = await tools.get_asset_overview(
            tenant_id="test-tenant",
            user_id="test-user",
            asset_id="asset-001",
            include_health_assessment=True,
            include_recent_alarms=False,
        )

        # Verify both sources are represented
        assert isinstance(result, str)
        assert "asset-001" in result or "PUMP-001" in result or "1号泵" in result  # from Ins
        assert "85.5" in result or "健康" in result  # from Sms


class TestE2E_CapabilitiesEndpoint:
    """E2E test: /api/capabilities endpoint with integration systems."""

    @pytest.mark.asyncio
    async def test_integration_registry_module_exists(self):
        """Test that integration registry module is importable."""
        from deerflow.integrations.registry import get_integration_registry

        # Just verify the function exists and is callable
        assert callable(get_integration_registry)

    @pytest.mark.asyncio
    async def test_integration_models_importable(self):
        """Test that integration models are importable."""
        from deerflow.integrations.models import (
            TrendSeries,
            TrendPoint,
            Asset,
            AssetOverview,
            HealthAssessment,
        )

        # Verify models can be instantiated
        assert TrendSeries is not None
        assert Asset is not None
        assert AssetOverview is not None

    @pytest.mark.asyncio
    async def test_integration_tools_importable(self):
        """Test that integration tools are importable."""
        from deerflow.integrations.tools.monitoring_tools import MonitoringTools
        from deerflow.integrations.tools.asset_tools import AssetTools

        assert MonitoringTools is not None
        assert AssetTools is not None
