"""Unit tests for integration tools, tool builder, and tool registry.

Covers:
- Tool builder: building LangChain tools from data_tools config
- Tool registry: registration, retrieval, lifecycle
- Prompt scoping: data_sources section generation with wildcards and specific tools
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime
from typing import Any

from deerflow.integrations.adapters.base import AuthContext
from deerflow.integrations.models import (
    Asset,
    AssetContext,
    MeasurementPoint,
    HealthAssessment,
    TrendSeries,
    TrendPoint,
    TrendStatistics,
    AlarmEvent,
)
from deerflow.integrations.models.provenance import PartialFailure
from deerflow.integrations.routing import ServiceResult
from deerflow.integrations.services import (
    AssetService,
    MonitoringService,
    AssessmentService,
)
from deerflow.integrations.tools.asset_tools import AssetTools
from deerflow.integrations.tools.monitoring_tools import MonitoringTools
from deerflow.integrations.tools.assessment_tools import AssessmentTools
from deerflow.integrations.tools.tool_builder import build_integration_tools


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def auth_context():
    """Standard auth context for tests."""
    return AuthContext(tenant_id="test-tenant", user_id="test-user")


@pytest.fixture
def mock_router():
    """Mock CapabilityRouter with async route() method."""
    router = MagicMock()
    router.route = AsyncMock()
    return router


@pytest.fixture
def sample_asset():
    """Sample Asset for testing."""
    return Asset(
        asset_id="asset-001",
        asset_code="PUMP-001",
        asset_name="Test Pump",
        asset_type="rotating",
        location="Building A",
        manufacturer="Test Corp",
        model="TP-100",
        status="running",
    )


@pytest.fixture
def sample_asset_context(sample_asset):
    """Sample AssetContext for testing composite overview."""
    return AssetContext(
        asset=sample_asset,
        parent_asset_id=None,
        child_assets=(),
        measurement_points=(),
    )


@pytest.fixture
def sample_trend_series():
    """Sample TrendSeries for testing."""
    return TrendSeries(
        series_id="series-001",
        asset_id="asset-001",
        measurement_point_id="mp-001",
        unit="mm/s",
        points=(
            TrendPoint(timestamp=datetime(2024, 1, 1, 10, 0), value=1.5),
            TrendPoint(timestamp=datetime(2024, 1, 1, 11, 0), value=1.6),
        ),
        statistics=TrendStatistics(
            min_value=1.5,
            max_value=1.6,
            avg_value=1.55,
            sample_count=2,
        ),
    )


@pytest.fixture
def sample_health_assessment():
    """Sample HealthAssessment for testing."""
    return HealthAssessment(
        assessment_id="ha-001",
        asset_id="asset-001",
        overall_score=85.5,
        overall_status="good",
        summary="Equipment in good condition",
        dimensions={"vibration": 90.0, "temperature": 80.0},
    )


@pytest.fixture
def sample_alarm():
    """Sample AlarmEvent for testing."""
    return AlarmEvent(
        event_id="alarm-001",
        asset_id="asset-001",
        event_type="high_vibration",
        severity="high",
        message="High vibration detected",
        triggered_at=datetime(2024, 1, 1, 10, 0),
        acknowledged=False,
    )


# ---------------------------------------------------------------------------
# Tool Builder Tests (Phase 1.9.11, 1.9.12)
# ---------------------------------------------------------------------------


class TestBuildIntegrationTools:
    """Test build_integration_tools() with various data_tools configs."""

    def test_build_with_wildcard_includes_all_tools(self, auth_context):
        """Wildcard '*' should include all 10 integration tools."""
        with patch(
            "deerflow.integrations.tools.registry.get_tool_registry"
        ) as mock_get_registry:
            mock_registry = MagicMock()
            mock_registry._initialized = True
            mock_registry.get_tool.side_effect = lambda name: MagicMock()
            mock_get_registry.return_value = mock_registry

            tools = build_integration_tools(auth_context, ["*"])

            assert len(tools) == 10
            tool_names = {t.name for t in tools}
            assert "equipment_get_overview" in tool_names
            assert "monitoring_get_trend" in tool_names
            assert "health_get_assessment" in tool_names
            assert "asset_get_catalog" in tool_names

    def test_build_with_group_wildcard(self, auth_context):
        """Group wildcard 'monitoring.*' should include only monitoring tools."""
        with patch(
            "deerflow.integrations.tools.registry.get_tool_registry"
        ) as mock_get_registry:
            mock_registry = MagicMock()
            mock_registry._initialized = True
            mock_registry.get_tool.side_effect = lambda name: MagicMock()
            mock_get_registry.return_value = mock_registry

            tools = build_integration_tools(auth_context, ["monitoring.*"])

            assert len(tools) == 4
            tool_names = {t.name for t in tools}
            assert "monitoring_get_trend" in tool_names
            assert "monitoring_get_waveform" in tool_names
            assert "monitoring_get_orbit" in tool_names
            assert "monitoring_get_alarm_history" in tool_names
            assert "equipment_get_overview" not in tool_names

    def test_build_with_specific_tools(self, auth_context):
        """Specific tool names should include only those tools."""
        with patch(
            "deerflow.integrations.tools.registry.get_tool_registry"
        ) as mock_get_registry:
            mock_registry = MagicMock()
            mock_registry._initialized = True
            mock_registry.get_tool.side_effect = lambda name: MagicMock()
            mock_get_registry.return_value = mock_registry

            tools = build_integration_tools(
                auth_context,
                ["equipment_get_overview", "monitoring_get_trend"],
            )

            assert len(tools) == 2
            tool_names = {t.name for t in tools}
            assert "equipment_get_overview" in tool_names
            assert "monitoring_get_trend" in tool_names

    def test_build_with_empty_list_returns_no_tools(self, auth_context):
        """Empty data_tools list should return no tools."""
        with patch(
            "deerflow.integrations.tools.registry.get_tool_registry"
        ) as mock_get_registry:
            mock_registry = MagicMock()
            mock_registry._initialized = True
            mock_get_registry.return_value = mock_registry

            tools = build_integration_tools(auth_context, [])

            assert len(tools) == 0

    def test_build_handles_missing_registry(self, auth_context):
        """Missing tool registry should return empty list gracefully."""
        with patch(
            "deerflow.integrations.tools.registry.get_tool_registry"
        ) as mock_get_registry:
            mock_get_registry.return_value = None

            tools = build_integration_tools(auth_context, ["*"])

            assert tools == []

    def test_build_handles_uninitialized_registry(self, auth_context):
        """Uninitialized registry should return empty list gracefully."""
        with patch(
            "deerflow.integrations.tools.registry.get_tool_registry"
        ) as mock_get_registry:
            mock_registry = MagicMock()
            mock_registry._initialized = False
            mock_get_registry.return_value = mock_registry

            tools = build_integration_tools(auth_context, ["*"])

            assert tools == []

    def test_tool_schema_has_correct_fields(self, auth_context):
        """Built tools should have correct Pydantic schema."""
        with patch(
            "deerflow.integrations.tools.registry.get_tool_registry"
        ) as mock_get_registry:
            mock_registry = MagicMock()
            mock_registry._initialized = True
            mock_registry.get_tool.side_effect = lambda name: MagicMock()
            mock_get_registry.return_value = mock_registry

            tools = build_integration_tools(
                auth_context, ["equipment_get_overview"]
            )

            assert len(tools) == 1
            tool = tools[0]
            assert tool.name == "equipment_get_overview"
            schema = tool.args_schema.model_json_schema()
            assert "asset_id" in schema["properties"]
            assert "tenant_id" not in schema["properties"]

    def test_tool_deduplication(self, auth_context):
        """Duplicate tool names in data_tools should not create duplicate tools."""
        with patch(
            "deerflow.integrations.tools.registry.get_tool_registry"
        ) as mock_get_registry:
            mock_registry = MagicMock()
            mock_registry._initialized = True
            mock_registry.get_tool.side_effect = lambda name: MagicMock()
            mock_get_registry.return_value = mock_registry

            tools = build_integration_tools(
                auth_context,
                ["equipment_get_overview", "equipment_get_overview"],
            )

            assert len(tools) == 1

    def test_build_with_assessment_group_wildcard(self, auth_context):
        """Group wildcard 'assessment.*' should include only assessment-group tools."""
        with patch(
            "deerflow.integrations.tools.registry.get_tool_registry"
        ) as mock_get_registry:
            mock_registry = MagicMock()
            mock_registry._initialized = True
            mock_registry.get_tool.side_effect = lambda name: MagicMock()
            mock_get_registry.return_value = mock_registry

            tools = build_integration_tools(auth_context, ["assessment.*"])

            tool_names = {t.name for t in tools}
            assert "fault_get_risk_ranking" in tool_names
            assert "monitoring_get_trend" not in tool_names
            assert "equipment_get_overview" not in tool_names


# ---------------------------------------------------------------------------
# Tool Registry Tests (Phase 1.9.12)
# ---------------------------------------------------------------------------


class TestToolRegistry:
    """Test ToolRegistry tool registration and retrieval."""

    def test_register_and_get_tool(self):
        """Register and retrieve a tool group by name."""
        from deerflow.integrations.tools.registry import ToolRegistry

        mock_config = MagicMock()
        mock_integration_registry = MagicMock()
        mock_router = MagicMock()
        registry = ToolRegistry(
            mock_config, mock_integration_registry, mock_router
        )

        mock_tool = MagicMock()
        registry._tools["asset"] = mock_tool
        retrieved = registry.get_tool("asset")

        assert retrieved is mock_tool

    def test_get_nonexistent_tool_returns_none(self):
        """Getting a non-existent tool group should return None."""
        from deerflow.integrations.tools.registry import ToolRegistry

        mock_config = MagicMock()
        mock_integration_registry = MagicMock()
        mock_router = MagicMock()
        registry = ToolRegistry(
            mock_config, mock_integration_registry, mock_router
        )
        result = registry.get_tool("nonexistent")

        assert result is None

    def test_list_tools(self):
        """List all registered tool group names."""
        from deerflow.integrations.tools.registry import ToolRegistry

        mock_config = MagicMock()
        mock_integration_registry = MagicMock()
        mock_router = MagicMock()
        registry = ToolRegistry(
            mock_config, mock_integration_registry, mock_router
        )
        registry._tools["asset"] = MagicMock()
        registry._tools["monitoring"] = MagicMock()

        names = registry.list_tools()

        assert set(names) == {"asset", "monitoring"}

    @pytest.mark.asyncio
    async def test_initialized_flag(self):
        """Registry should track initialization state."""
        from deerflow.integrations.tools.registry import ToolRegistry

        mock_config = MagicMock()
        mock_integration_registry = MagicMock()
        mock_router = MagicMock()
        registry = ToolRegistry(
            mock_config, mock_integration_registry, mock_router
        )
        assert not registry._initialized

        await registry.initialize()
        assert registry._initialized


# ---------------------------------------------------------------------------
# Prompt Scoping Tests (Phase 1.9.13)
# ---------------------------------------------------------------------------


class TestPromptScoping:
    """Test _build_data_sources_section() with various configs."""

    def test_none_returns_empty(self):
        """None data_tools should return empty string."""
        from deerflow.agents.lead_agent.prompt import _build_data_sources_section

        result = _build_data_sources_section(None)
        assert result == ""

    def test_empty_list_returns_empty(self):
        """Empty data_tools list should return empty string."""
        from deerflow.agents.lead_agent.prompt import _build_data_sources_section

        result = _build_data_sources_section([])
        assert result == ""

    def test_wildcard_includes_all_descriptions(self):
        """Wildcard '*' should include all tool descriptions."""
        from deerflow.agents.lead_agent.prompt import _build_data_sources_section

        result = _build_data_sources_section(["*"])

        assert "<data_sources>" in result
        assert "equipment_get_overview" in result
        assert "monitoring_get_trend" in result
        assert "health_get_assessment" in result
        assert "asset_get_catalog" in result
        assert "anomaly_get_stats" in result
        assert "fault_get_risk_ranking" in result
        assert "</data_sources>" in result

    def test_group_wildcard_includes_group_only(self):
        """Group wildcard 'monitoring.*' should include only monitoring tools."""
        from deerflow.agents.lead_agent.prompt import _build_data_sources_section

        result = _build_data_sources_section(["monitoring.*"])

        assert "monitoring_get_trend" in result
        assert "monitoring_get_waveform" in result
        assert "monitoring_get_orbit" in result
        assert "monitoring_get_alarm_history" in result
        assert "- **equipment_get_overview**" not in result
        assert "- **health_get_assessment**" not in result

    def test_specific_tools_includes_only_those(self):
        """Specific tool names should include only those descriptions."""
        from deerflow.agents.lead_agent.prompt import _build_data_sources_section

        result = _build_data_sources_section(
            ["equipment_get_overview", "monitoring_get_trend"]
        )

        assert "equipment_get_overview" in result
        assert "monitoring_get_trend" in result
        assert "- **health_get_assessment**" not in result
        assert "- **asset_get_catalog**" not in result

    def test_mixed_wildcard_and_specific(self):
        """Mixing wildcards and specific tools should work correctly."""
        from deerflow.agents.lead_agent.prompt import _build_data_sources_section

        result = _build_data_sources_section(
            ["monitoring.*", "health_get_assessment"]
        )

        assert "monitoring_get_trend" in result
        assert "monitoring_get_waveform" in result
        assert "health_get_assessment" in result
        assert "asset_get_catalog" not in result


# ---------------------------------------------------------------------------
# Tool Output Formatting Tests (Phase 1.9.11)
# ---------------------------------------------------------------------------


class TestToolOutputFormatting:
    """Test that tools format output correctly."""

    @pytest.mark.asyncio
    async def test_equipment_get_overview_formats_output(
        self, mock_router, sample_asset_context
    ):
        """get_asset_overview should format AssetContext as readable text."""
        result = ServiceResult(
            data=sample_asset_context,
            source_system_keys=("ins",),
            partial_failures=(),
        )
        mock_router.route.return_value = result

        service = AssetService(mock_router)
        tools = AssetTools(service)

        output = await tools.get_asset_overview(
            tenant_id="test-tenant",
            user_id="test-user",
            asset_id="asset-001",
            include_health_assessment=False,
            include_recent_alarms=False,
        )

        assert "Test Pump" in output
        assert "asset-001" in output
        assert "rotating" in output

    @pytest.mark.asyncio
    async def test_monitoring_get_trend_formats_output(
        self, mock_router, sample_trend_series
    ):
        """get_trend_data should format TrendSeries with statistics."""
        result = ServiceResult(
            data=sample_trend_series,
            source_system_keys=("ins",),
            partial_failures=(),
        )
        mock_router.route.return_value = result

        service = MonitoringService(mock_router)
        tools = MonitoringTools(service)

        output = await tools.get_trend_data(
            tenant_id="test-tenant",
            user_id="test-user",
            asset_id="asset-001",
            measurement_point_id="mp-001",
        )

        assert "mm/s" in output
        assert "1.5" in output or "1.6" in output
        assert "统计" in output

    @pytest.mark.asyncio
    async def test_health_get_assessment_formats_output(
        self, mock_router, sample_health_assessment
    ):
        """get_health_assessment should format HealthAssessment with dimensions."""
        result = ServiceResult(
            data=sample_health_assessment,
            source_system_keys=("sms",),
            partial_failures=(),
        )
        mock_router.route.return_value = result

        service = AssessmentService(mock_router)
        tools = AssessmentTools(service)

        output = await tools.get_health_assessment(
            tenant_id="test-tenant",
            user_id="test-user",
            asset_id="asset-001",
        )

        assert "85.5" in output
        assert "vibration" in output or "维度" in output


# ---------------------------------------------------------------------------
# Error Handling Tests (Phase 1.9.11)
# ---------------------------------------------------------------------------


class TestToolErrorHandling:
    """Test that tools handle errors gracefully."""

    @pytest.mark.asyncio
    async def test_tool_returns_error_message_on_exception(self, mock_router):
        """Tool should return user-friendly error message on exception."""
        from deerflow.integrations.errors import IntegrationError

        mock_router.route.side_effect = IntegrationError("Connection failed")

        service = AssetService(mock_router)
        tools = AssetTools(service)

        output = await tools.get_asset_overview(
            tenant_id="test-tenant",
            user_id="test-user",
            asset_id="asset-001",
        )

        assert "失败" in output or "错误" in output
        assert "Connection failed" in output

    @pytest.mark.asyncio
    async def test_monitoring_tool_handles_error(self, mock_router):
        """Monitoring tool should return user-friendly error on exception."""
        from deerflow.integrations.errors import IntegrationError

        mock_router.route.side_effect = IntegrationError("Timeout")

        service = MonitoringService(mock_router)
        tools = MonitoringTools(service)

        output = await tools.get_trend_data(
            tenant_id="test-tenant",
            user_id="test-user",
            asset_id="asset-001",
            measurement_point_id="mp-001",
        )

        assert "失败" in output or "错误" in output
        assert "Timeout" in output

    @pytest.mark.asyncio
    async def test_assessment_tool_handles_error(self, mock_router):
        """Assessment tool should return user-friendly error on exception."""
        from deerflow.integrations.errors import IntegrationError

        mock_router.route.side_effect = IntegrationError("Service unavailable")

        service = AssessmentService(mock_router)
        tools = AssessmentTools(service)

        output = await tools.get_health_assessment(
            tenant_id="test-tenant",
            user_id="test-user",
            asset_id="asset-001",
        )

        assert "失败" in output or "错误" in output
        assert "Service unavailable" in output

    @pytest.mark.asyncio
    async def test_tool_handles_empty_result(self, mock_router):
        """Tool should handle empty result gracefully."""
        result = ServiceResult(
            data=(),
            source_system_keys=("ins",),
            partial_failures=(),
        )
        mock_router.route.return_value = result

        service = AssetService(mock_router)
        tools = AssetTools(service)

        output = await tools.get_asset_catalog(
            tenant_id="test-tenant",
            user_id="test-user",
        )

        assert "未找到" in output
