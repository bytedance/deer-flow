"""Unit tests for InsAdapter (Task 1.5.14)."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deerflow.integrations.adapters.base import AuthContext
from deerflow.integrations.adapters.ins.adapter import InsAdapter
from deerflow.integrations.config import IntegrationSystemConfig
from deerflow.integrations.errors import (
    IntegrationError,
    IntegrationTimeoutError,
)
from deerflow.integrations.models.queries import (
    AlarmHistoryQuery,
    AssetCatalogQuery,
    AssetContextQuery,
    TrendQuery,
)


def _make_config(**overrides):
    defaults = {
        "system_key": "ins_prod",
        "system_type": "ins",
        "display_name": "InS Production",
        "base_url": "http://ins.example.com",
        "auth_type": "bearer",
    }
    defaults.update(overrides)
    return IntegrationSystemConfig(**defaults)


def _auth(token=None):
    return AuthContext(
        tenant_id="t1",
        user_id="u1",
        token=token,
        extra={"user_id": "100", "org_id": "200"},
    )


def _make_adapter_with_bridge():
    """Create an InsAdapter with a mocked bridge already attached."""
    config = _make_config()
    adapter = InsAdapter(config)
    bridge = MagicMock()
    bridge.initialize = AsyncMock()
    bridge.shutdown = AsyncMock()
    adapter._bridge = bridge
    return adapter, bridge


class TestInsAdapterLifecycle:
    @pytest.mark.asyncio
    async def test_initialize_and_shutdown(self):
        config = _make_config()
        adapter = InsAdapter(config)
        assert adapter.system_key == "ins_prod"
        assert adapter.system_type == "ins"

        with patch(
            "deerflow.integrations.adapters.ins.adapter.InsClientBridge"
        ) as MockBridge:
            bridge_instance = MagicMock()
            bridge_instance.initialize = AsyncMock()
            bridge_instance.shutdown = AsyncMock()
            MockBridge.return_value = bridge_instance

            await adapter.initialize()
            bridge_instance.initialize.assert_called_once()

            await adapter.shutdown()
            bridge_instance.shutdown.assert_called_once()

    @pytest.mark.asyncio
    async def test_call_before_initialize_raises(self):
        config = _make_config()
        adapter = InsAdapter(config)
        with pytest.raises(IntegrationError, match="not initialized"):
            await adapter.call("asset.catalog", {}, _auth())

    @pytest.mark.asyncio
    async def test_unsupported_capability_raises(self):
        adapter, _ = _make_adapter_with_bridge()
        with pytest.raises(IntegrationError, match="Unsupported capability"):
            await adapter.call("nonexistent.cap", {}, _auth())


class TestInsAdapterCapabilities:
    @pytest.mark.asyncio
    async def test_asset_catalog(self):
        adapter, bridge = _make_adapter_with_bridge()
        bridge.get_machine_catalog = AsyncMock(return_value={
            "records": [
                {
                    "macId": "1",
                    "macCode": "PUMP-001",
                    "macName": "Pump A",
                    "macTypeName": "pump",
                    "macStatus": "active",
                },
            ],
        })

        query = AssetCatalogQuery(tenant_id="t1", search_text="Pump")
        result = await adapter.call("asset.catalog", query, _auth())

        bridge.get_machine_catalog.assert_called_once()
        assert len(result) == 1
        assert result[0].asset_id == "1"
        assert result[0].asset_code == "PUMP-001"
        assert result[0].provenance is not None
        assert result[0].provenance.source_system_key == "ins_prod"

    @pytest.mark.asyncio
    async def test_asset_context(self):
        adapter, bridge = _make_adapter_with_bridge()
        bridge.get_machine_context = AsyncMock(return_value={
            "macId": "1",
            "macCode": "PUMP-001",
            "macName": "Pump A",
            "macTypeName": "pump",
            "children": [],
            "components": [
                {
                    "id": "MP1",
                    "code": "V1",
                    "name": "Vibration",
                    "endpoint_series": "8k",
                },
            ],
        })

        query = AssetContextQuery(tenant_id="t1", asset_id="1")
        result = await adapter.call("asset.context", query, _auth())

        bridge.get_machine_context.assert_called_once_with(1, extra_headers=None)
        assert result.asset.asset_id == "1"
        assert len(result.measurement_points) == 1

    @pytest.mark.asyncio
    async def test_asset_context_missing_asset_id(self):
        adapter, bridge = _make_adapter_with_bridge()

        query = AssetContextQuery(tenant_id="t1", asset_id="")
        with pytest.raises(IntegrationError, match="asset_id is required"):
            await adapter.call("asset.context", query, _auth())

    @pytest.mark.asyncio
    async def test_monitoring_trend(self):
        adapter, bridge = _make_adapter_with_bridge()
        now = datetime.now()
        bridge.get_trend_data = AsyncMock(return_value=[
            {"time": now.timestamp() * 1000, "value": 1.5},
            {"time": (now + timedelta(minutes=1)).timestamp() * 1000, "value": 2.0},
        ])

        query = TrendQuery(
            tenant_id="t1",
            asset_id="1",
            measurement_point_id="MP1",
            start_time=now - timedelta(hours=1),
            end_time=now,
        )
        result = await adapter.call("monitoring.trend", query, _auth())

        bridge.get_trend_data.assert_called_once()
        assert result is not None

    @pytest.mark.asyncio
    async def test_monitoring_trend_missing_params(self):
        adapter, bridge = _make_adapter_with_bridge()

        query = MagicMock()
        query.measurement_point_id = ""
        query.start_time = None
        query.end_time = None
        query.extra_params = {}

        with pytest.raises(IntegrationError, match="required"):
            await adapter.call("monitoring.trend", query, _auth())

    @pytest.mark.asyncio
    async def test_monitoring_alarm_history(self):
        adapter, bridge = _make_adapter_with_bridge()
        now = datetime.now()
        bridge.get_machine_drops = AsyncMock(return_value=[
            {
                "eventId": "E1",
                "eventType": 1,
                "startTime": now.timestamp() * 1000,
                "endTime": (now + timedelta(minutes=5)).timestamp() * 1000,
            },
        ])

        query = AlarmHistoryQuery(
            tenant_id="t1",
            asset_id="1",
            start_time=now - timedelta(hours=24),
            end_time=now,
        )
        result = await adapter.call("monitoring.alarm_history", query, _auth())

        bridge.get_machine_drops.assert_called_once()
        assert isinstance(result, tuple)


class TestInsAdapterHealthCheck:
    @pytest.mark.asyncio
    async def test_health_check_not_initialized(self):
        config = _make_config()
        adapter = InsAdapter(config)
        status = await adapter.health_check()
        assert status.healthy is False
        assert "not initialized" in status.message

    @pytest.mark.asyncio
    async def test_health_check_healthy(self):
        adapter, bridge = _make_adapter_with_bridge()
        bridge.health_check = AsyncMock(return_value={
            "ins-base-rpc": True,
            "ins-bus-rpc": True,
        })

        status = await adapter.health_check()
        assert status.healthy is True
        assert status.latency_ms is not None

    @pytest.mark.asyncio
    async def test_health_check_partial_failure(self):
        adapter, bridge = _make_adapter_with_bridge()
        bridge.health_check = AsyncMock(return_value={
            "ins-base-rpc": True,
            "ins-bus-rpc": False,
        })

        status = await adapter.health_check()
        assert status.healthy is False

    @pytest.mark.asyncio
    async def test_health_check_exception(self):
        adapter, bridge = _make_adapter_with_bridge()
        bridge.health_check = AsyncMock(side_effect=Exception("network error"))

        status = await adapter.health_check()
        assert status.healthy is False
        assert "Health check failed" in status.message


class TestInsAdapterErrorHandling:
    @pytest.mark.asyncio
    async def test_timeout_mapped_to_timeout_error(self):
        adapter, bridge = _make_adapter_with_bridge()
        bridge.get_machine_catalog = AsyncMock(side_effect=TimeoutError("timeout"))

        with pytest.raises(IntegrationTimeoutError):
            await adapter.call("asset.catalog", MagicMock(), _auth())

    @pytest.mark.asyncio
    async def test_generic_exception_mapped_to_integration_error(self):
        adapter, bridge = _make_adapter_with_bridge()
        bridge.get_machine_catalog = AsyncMock(side_effect=RuntimeError("unexpected"))

        with pytest.raises(IntegrationError, match="Capability asset.catalog failed"):
            await adapter.call("asset.catalog", MagicMock(), _auth())

    @pytest.mark.asyncio
    async def test_token_redaction_in_error(self):
        adapter, bridge = _make_adapter_with_bridge()
        bridge.get_machine_catalog = AsyncMock(
            side_effect=RuntimeError("token=secret-token-123 leaked")
        )

        auth = _auth(token="secret-token-123")
        with pytest.raises(IntegrationError):
            await adapter.call("asset.catalog", MagicMock(), auth)


class TestInsTransforms:
    def test_transform_asset_catalog(self):
        from deerflow.integrations.adapters.ins.transform import transform_asset_catalog

        raw = {
            "records": [
                {
                    "macId": "1",
                    "macCode": "P-001",
                    "macName": "Pump",
                    "macTypeName": "pump",
                    "macStatus": "active",
                    "producer": "ACME",
                },
            ],
        }
        result = transform_asset_catalog(raw, "ins_prod")
        assert len(result) == 1
        assert result[0].asset_id == "1"
        assert result[0].asset_code == "P-001"
        assert result[0].manufacturer == "ACME"
        assert result[0].provenance.source_system_type == "ins"

    def test_transform_asset_catalog_empty(self):
        from deerflow.integrations.adapters.ins.transform import transform_asset_catalog

        result = transform_asset_catalog({"records": []}, "ins_prod")
        assert result == ()

    def test_transform_asset_catalog_alternate_keys(self):
        from deerflow.integrations.adapters.ins.transform import transform_asset_catalog

        raw = {
            "list": [
                {"id": "1", "code": "P-001", "name": "Pump", "typeName": "pump"},
            ],
        }
        result = transform_asset_catalog(raw, "ins_prod")
        assert len(result) == 1


class TestInsAdapterAggregator:
    """Tests for get_aggregator() method (Task 3.3)."""

    def test_get_aggregator_returns_module(self):
        """get_aggregator() returns the kpi_aggregator module."""
        config = _make_config()
        adapter = InsAdapter(config)

        aggregator = adapter.get_aggregator()

        # Should be the module itself
        assert hasattr(aggregator, "aggregate_trend_to_kpi")
        assert hasattr(aggregator, "select_points_for_kpi")
        assert hasattr(aggregator, "hourly_runtime_rate")
        assert hasattr(aggregator, "aggregate_equipment_kpis")

    def test_aggregator_functions_are_callable(self):
        """Aggregator functions are callable."""
        config = _make_config()
        adapter = InsAdapter(config)

        aggregator = adapter.get_aggregator()

        assert callable(aggregator.aggregate_trend_to_kpi)
        assert callable(aggregator.select_points_for_kpi)
        assert callable(aggregator.hourly_runtime_rate)
        assert callable(aggregator.aggregate_equipment_kpis)

    def test_aggregator_works_without_initialize(self):
        """get_aggregator() works even before adapter.initialize()."""
        config = _make_config()
        adapter = InsAdapter(config)

        # Should not raise
        aggregator = adapter.get_aggregator()
        assert aggregator is not None


class TestInsAdapterBatchQueries:
    """Tests for batch equipment_ids support (Tasks 2.5-2.6)."""

    @pytest.mark.asyncio
    async def test_batch_trend_query_multiple_equipment(self):
        """Batch trend query returns raw rows for all equipment."""
        from datetime import datetime

        adapter, bridge = _make_adapter_with_bridge()

        # Mock get_trend_data to return different data per equipment
        call_count = 0

        async def mock_get_trend(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            component_id = kwargs.get("component_ids", "")
            return [
                {
                    "component_id": component_id,
                    "time_ms": 1000,
                    "values": {"pp_value": 10.0 + call_count, "speed": 100},
                },
                {
                    "component_id": component_id,
                    "time_ms": 2000,
                    "values": {"pp_value": 15.0 + call_count, "speed": 0},
                },
            ]

        bridge.get_trend_data = AsyncMock(side_effect=mock_get_trend)

        query = TrendQuery(
            tenant_id="t1",
            equipment_ids=("EQ1", "EQ2"),
            start_time=datetime(2024, 1, 1),
            end_time=datetime(2024, 1, 2),
            extra_params={"endpoint_series": "8k", "features": ["pp_value", "speed"]},
        )

        result = await adapter.call("monitoring.trend", query, _auth())

        assert "equipment_data" in result
        assert "equipment_ids" in result
        assert "point_metadata" in result
        assert set(result["equipment_ids"]) == {"EQ1", "EQ2"}
        assert "EQ1" in result["equipment_data"]
        assert "EQ2" in result["equipment_data"]
        # Raw rows, not TrendSeries
        assert isinstance(result["equipment_data"]["EQ1"], list)
        assert len(result["equipment_data"]["EQ1"]) == 2
        assert bridge.get_trend_data.call_count == 2

    @pytest.mark.asyncio
    async def test_batch_trend_empty_equipment_ids_falls_back_to_single(self):
        """Empty equipment_ids uses single-asset query (backward compatible)."""
        from datetime import datetime

        from deerflow.integrations.models.monitoring import TrendSeries

        adapter, bridge = _make_adapter_with_bridge()
        bridge.get_trend_data = AsyncMock(return_value=[
            {"component_id": "MP1", "time_ms": 1000, "values": {"value": 5.0}}
        ])

        query = TrendQuery(
            tenant_id="t1",
            measurement_point_id="MP1",
            start_time=datetime(2024, 1, 1),
            end_time=datetime(2024, 1, 2),
            equipment_ids=(),  # empty
        )

        result = await adapter.call("monitoring.trend", query, _auth())

        # Should return TrendSeries, not batch dict
        assert isinstance(result, TrendSeries)
        bridge.get_trend_data.assert_called_once()

    @pytest.mark.asyncio
    async def test_batch_alarm_history_multiple_equipment(self):
        """Batch alarm history query returns data for all equipment."""
        from datetime import datetime

        adapter, bridge = _make_adapter_with_bridge()

        # Mock get_machine_drops to return different data per equipment
        async def mock_get_drops(*args, **kwargs):
            eq_id = kwargs.get("equipment_id", "")
            return [
                {"equipment_id": eq_id, "event_type": 1, "time_ms": 1000},
            ]

        bridge.get_machine_drops = AsyncMock(side_effect=mock_get_drops)

        query = AlarmHistoryQuery(
            tenant_id="t1",
            equipment_ids=("EQ1", "EQ2", "EQ3"),
            start_time=datetime(2024, 1, 1),
            end_time=datetime(2024, 1, 2),
            eq_type="rotating_machinery",
        )

        result = await adapter.call("monitoring.alarm_history", query, _auth())

        assert "equipment_data" in result
        assert "equipment_ids" in result
        assert set(result["equipment_ids"]) == {"EQ1", "EQ2", "EQ3"}
        assert "EQ1" in result["equipment_data"]
        assert "EQ2" in result["equipment_data"]
        assert "EQ3" in result["equipment_data"]
        assert bridge.get_machine_drops.call_count == 3

    @pytest.mark.asyncio
    async def test_batch_alarm_empty_equipment_ids_falls_back_to_single(self):
        """Empty equipment_ids uses single-asset query (backward compatible)."""
        from datetime import datetime

        adapter, bridge = _make_adapter_with_bridge()
        bridge.get_machine_drops = AsyncMock(return_value=[
            {"equipment_id": "EQ1", "event_type": 1, "time_ms": 1000}
        ])

        query = AlarmHistoryQuery(
            tenant_id="t1",
            asset_id="EQ1",
            start_time=datetime(2024, 1, 1),
            end_time=datetime(2024, 1, 2),
            equipment_ids=(),  # empty
        )

        result = await adapter.call("monitoring.alarm_history", query, _auth())

        # Should not return batch structure
        assert "equipment_data" not in result
        bridge.get_machine_drops.assert_called_once()

    @pytest.mark.asyncio
    async def test_batch_trend_requires_time_range(self):
        """Batch trend query requires start_time and end_time."""
        adapter, bridge = _make_adapter_with_bridge()

        query = TrendQuery(
            tenant_id="t1",
            equipment_ids=("EQ1",),
            start_time=None,
            end_time=None,
        )

        with pytest.raises(IntegrationError, match="start_time, end_time required"):
            await adapter.call("monitoring.trend", query, _auth())

    @pytest.mark.asyncio
    async def test_batch_alarm_requires_time_range(self):
        """Batch alarm query requires start_time and end_time."""
        adapter, bridge = _make_adapter_with_bridge()

        query = AlarmHistoryQuery(
            tenant_id="t1",
            equipment_ids=("EQ1",),
            start_time=None,
            end_time=None,
        )

        with pytest.raises(IntegrationError, match="start_time, end_time required"):
            await adapter.call("monitoring.alarm_history", query, _auth())

