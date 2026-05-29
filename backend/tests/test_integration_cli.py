"""Unit tests for the CLI subprocess bridge (Phase 2.1.4).

Covers:
- Argument parsing (--capability, --tenant-id, --user-id, --params, --config-path)
- Success path: capability call -> ServiceResult -> JSON stdout
- Error path: capability failure -> error JSON + non-zero exit
- Query building: correct query class constructed from params
- DateTime parsing: ISO strings parsed to datetime objects
- Invalid params JSON -> error JSON
- Integrations disabled -> error JSON
"""

import json
import sys
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deerflow.integrations.cli import (
    _build_parser,
    _build_query,
    _error_output,
    _IntegrationJSONEncoder,
    _run,
    main,
)


# ---------------------------------------------------------------------------
# Argument Parsing Tests
# ---------------------------------------------------------------------------


class TestArgumentParsing:
    """Test CLI argument parsing."""

    def test_required_capability(self):
        parser = _build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([])

    def test_minimal_args(self):
        parser = _build_parser()
        args = parser.parse_args([
            "--capability", "monitoring.trend",
            "--tenant-id", "tenant-1",
        ])
        assert args.capability == "monitoring.trend"
        assert args.tenant_id == "tenant-1"
        assert args.user_id == "cli-subprocess"
        assert args.params == "{}"
        assert args.config_path is None

    def test_all_args(self):
        parser = _build_parser()
        args = parser.parse_args([
            "--capability", "health.assessment",
            "--tenant-id", "tenant-2",
            "--user-id", "user-42",
            "--params", '{"asset_id": "a1"}',
            "--config-path", "/etc/deerflow/config.yaml",
        ])
        assert args.capability == "health.assessment"
        assert args.tenant_id == "tenant-2"
        assert args.user_id == "user-42"
        assert args.params == '{"asset_id": "a1"}'
        assert args.config_path == "/etc/deerflow/config.yaml"


# ---------------------------------------------------------------------------
# Query Building Tests
# ---------------------------------------------------------------------------


class TestQueryBuilding:
    """Test query dataclass construction from params."""

    def test_build_trend_query(self):
        query = _build_query(
            "monitoring.trend",
            {
                "asset_id": "a1",
                "measurement_point_id": "mp1",
                "start_time": "2026-01-01T00:00:00+00:00",
                "end_time": "2026-01-02T00:00:00+00:00",
            },
            "tenant-1",
        )
        from deerflow.integrations.models.queries import TrendQuery

        assert isinstance(query, TrendQuery)
        assert query.tenant_id == "tenant-1"
        assert query.asset_id == "a1"
        assert query.measurement_point_id == "mp1"
        assert isinstance(query.start_time, datetime)
        assert isinstance(query.end_time, datetime)

    def test_build_health_assessment_query(self):
        query = _build_query(
            "health.assessment",
            {"asset_id": "a2"},
            "tenant-1",
        )
        from deerflow.integrations.models.queries import HealthAssessmentQuery

        assert isinstance(query, HealthAssessmentQuery)
        assert query.tenant_id == "tenant-1"
        assert query.asset_id == "a2"

    def test_build_alarm_history_query(self):
        query = _build_query(
            "monitoring.alarm_history",
            {"asset_id": "a3", "limit": 10},
            "tenant-1",
        )
        from deerflow.integrations.models.queries import AlarmHistoryQuery

        assert isinstance(query, AlarmHistoryQuery)
        assert query.tenant_id == "tenant-1"
        assert query.asset_id == "a3"
        assert query.limit == 10

    def test_build_asset_catalog_query(self):
        query = _build_query(
            "asset.catalog",
            {"search_text": "pump"},
            "tenant-1",
        )
        from deerflow.integrations.models.queries import AssetCatalogQuery

        assert isinstance(query, AssetCatalogQuery)
        assert query.tenant_id == "tenant-1"
        assert query.search_text == "pump"

    def test_unknown_capability_raises(self):
        from deerflow.integrations.errors import CapabilityRouteNotFoundError

        with pytest.raises(CapabilityRouteNotFoundError):
            _build_query("unknown.capability", {}, "tenant-1")

    def test_extra_params_ignored(self):
        query = _build_query(
            "health.assessment",
            {"asset_id": "a1", "nonexistent_field": "value"},
            "tenant-1",
        )
        from deerflow.integrations.models.queries import HealthAssessmentQuery

        assert isinstance(query, HealthAssessmentQuery)
        assert not hasattr(query, "nonexistent_field")

    def test_tenant_id_from_cli_overrides_params(self):
        query = _build_query(
            "health.assessment",
            {"asset_id": "a1", "tenant_id": "params-tenant"},
            "cli-tenant",
        )
        assert query.tenant_id == "cli-tenant"


# ---------------------------------------------------------------------------
# JSON Encoder Tests
# ---------------------------------------------------------------------------


class TestJSONEncoder:
    """Test _IntegrationJSONEncoder handles datetimes, dataclasses, tuples."""

    def test_datetime_encoding(self):
        dt = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        result = json.dumps({"ts": dt}, cls=_IntegrationJSONEncoder)
        assert "2026-01-01T12:00:00" in result

    def test_tuple_encoding(self):
        result = json.dumps({"items": (1, 2, 3)}, cls=_IntegrationJSONEncoder)
        parsed = json.loads(result)
        assert parsed["items"] == [1, 2, 3]

    def test_dataclass_encoding(self):
        from deerflow.integrations.models.queries import HealthAssessmentQuery

        query = HealthAssessmentQuery(tenant_id="t1", asset_id="a1")
        result = json.dumps({"q": query}, cls=_IntegrationJSONEncoder)
        parsed = json.loads(result)
        assert parsed["q"]["tenant_id"] == "t1"
        assert parsed["q"]["asset_id"] == "a1"


# ---------------------------------------------------------------------------
# Error Output Tests
# ---------------------------------------------------------------------------


class TestErrorOutput:
    """Test error JSON payload construction."""

    def test_error_output_basic(self):
        result = _error_output(ValueError("bad value"))
        assert result["ok"] is False
        assert result["error"] == "bad value"
        assert result["error_type"] == "ValueError"

    def test_error_output_custom_type(self):
        result = _error_output(
            RuntimeError("timeout"),
            error_type="IntegrationTimeoutError",
        )
        assert result["error_type"] == "IntegrationTimeoutError"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_config(enabled=True, routes=None):
    """Create a mock AppConfig with integrations."""
    mock_app_config = MagicMock()
    if enabled:
        mock_app_config.integrations.enabled = True
        mock_app_config.integrations.routes = routes or {}
    else:
        mock_app_config.integrations = None
    return mock_app_config


def _make_mock_registry():
    """Create a mock registry with async init/shutdown."""
    mock_registry = MagicMock()
    mock_registry.initialize_all = AsyncMock()
    mock_registry.shutdown_all = AsyncMock()
    return mock_registry


def _make_mock_router(return_value=None, side_effect=None):
    """Create a mock CapabilityRouter."""
    mock_router = MagicMock()
    if side_effect is not None:
        mock_router.route = AsyncMock(side_effect=side_effect)
    else:
        mock_router.route = AsyncMock(return_value=return_value)
    return mock_router


_PATCH_CONFIG = "deerflow.integrations.cli.get_app_config"
_PATCH_REGISTRY = "deerflow.integrations.cli.initialize_registry"
_PATCH_ROUTER = "deerflow.integrations.cli.CapabilityRouter"


# ---------------------------------------------------------------------------
# Run Function Tests (Success Path)
# ---------------------------------------------------------------------------


class TestRunSuccess:
    """Test _run() success path."""

    @pytest.mark.asyncio
    async def test_run_success_outputs_json(self, capsys):
        """Successful capability call outputs result JSON."""
        from deerflow.integrations.routing import ServiceResult
        from deerflow.integrations.models.monitoring import (
            TrendSeries,
            TrendPoint,
            TrendStatistics,
        )

        now = datetime.now(timezone.utc)
        mock_series = TrendSeries(
            series_id="s1",
            asset_id="a1",
            measurement_point_id="mp1",
            points=(TrendPoint(timestamp=now, value=2.5, quality="good"),),
            statistics=TrendStatistics(
                min_value=2.5, max_value=2.5, avg_value=2.5, sample_count=1
            ),
            unit="mm/s",
        )
        mock_result = ServiceResult(
            data=mock_series,
            source_system_keys=("ins",),
        )

        mock_app_config = _make_mock_config(routes={"monitoring.trend": MagicMock()})
        mock_registry = _make_mock_registry()
        mock_router = _make_mock_router(return_value=mock_result)

        args = _build_parser().parse_args([
            "--capability", "monitoring.trend",
            "--tenant-id", "t1",
            "--params", json.dumps({
                "asset_id": "a1",
                "measurement_point_id": "mp1",
                "start_time": "2026-01-01T00:00:00+00:00",
                "end_time": "2026-01-02T00:00:00+00:00",
            }),
        ])

        with (
            patch(_PATCH_CONFIG, return_value=mock_app_config),
            patch(_PATCH_REGISTRY, return_value=mock_registry),
            patch(_PATCH_ROUTER, return_value=mock_router),
        ):
            await _run(args)

        out = capsys.readouterr().out
        output = json.loads(out)
        assert output["ok"] is True
        assert output["source_system_keys"] == ["ins"]
        assert output["data"]["series_id"] == "s1"

    @pytest.mark.asyncio
    async def test_run_initializes_and_shuts_down_registry(self, capsys):
        """Registry is initialized and shut down around the call."""
        from deerflow.integrations.routing import ServiceResult

        mock_result = ServiceResult(data="test", source_system_keys=("ins",))

        mock_app_config = _make_mock_config(routes={"health.assessment": MagicMock()})
        mock_registry = _make_mock_registry()
        mock_router = _make_mock_router(return_value=mock_result)

        args = _build_parser().parse_args([
            "--capability", "health.assessment",
            "--tenant-id", "t1",
            "--params", json.dumps({"asset_id": "a1"}),
        ])

        with (
            patch(_PATCH_CONFIG, return_value=mock_app_config),
            patch(_PATCH_REGISTRY, return_value=mock_registry),
            patch(_PATCH_ROUTER, return_value=mock_router),
        ):
            await _run(args)

        mock_registry.initialize_all.assert_awaited_once()
        mock_registry.shutdown_all.assert_awaited_once()


# ---------------------------------------------------------------------------
# Run Function Tests (Error Path)
# ---------------------------------------------------------------------------


class TestRunError:
    """Test _run() error paths."""

    @pytest.mark.asyncio
    async def test_run_integrations_disabled(self, capsys):
        """Outputs error when integrations are disabled."""
        mock_app_config = _make_mock_config(enabled=False)

        args = _build_parser().parse_args([
            "--capability", "monitoring.trend",
            "--tenant-id", "t1",
        ])

        with patch(_PATCH_CONFIG, return_value=mock_app_config):
            with pytest.raises(SystemExit) as exc_info:
                await _run(args)
            assert exc_info.value.code == 1

        out = capsys.readouterr().out
        output = json.loads(out)
        assert output["ok"] is False
        assert output["error_type"] == "IntegrationDisabled"

    @pytest.mark.asyncio
    async def test_run_integrations_enabled_false(self, capsys):
        """Outputs error when integrations.enabled is False."""
        mock_app_config = MagicMock()
        mock_app_config.integrations.enabled = False

        args = _build_parser().parse_args([
            "--capability", "monitoring.trend",
            "--tenant-id", "t1",
        ])

        with patch(_PATCH_CONFIG, return_value=mock_app_config):
            with pytest.raises(SystemExit) as exc_info:
                await _run(args)
            assert exc_info.value.code == 1

    @pytest.mark.asyncio
    async def test_run_route_not_found(self, capsys):
        """Capability route not found produces error output."""
        from deerflow.integrations.errors import CapabilityRouteNotFoundError

        mock_app_config = _make_mock_config(routes={"monitoring.trend": MagicMock()})
        mock_registry = _make_mock_registry()
        mock_router = _make_mock_router(
            side_effect=CapabilityRouteNotFoundError(
                message="No route configured",
                capability_key="nonexistent",
            )
        )

        args = _build_parser().parse_args([
            "--capability", "monitoring.trend",
            "--tenant-id", "t1",
            "--params", json.dumps({
                "asset_id": "a1",
                "measurement_point_id": "mp1",
                "start_time": "2026-01-01T00:00:00+00:00",
                "end_time": "2026-01-02T00:00:00+00:00",
            }),
        ])

        with (
            patch(_PATCH_CONFIG, return_value=mock_app_config),
            patch(_PATCH_REGISTRY, return_value=mock_registry),
            patch(_PATCH_ROUTER, return_value=mock_router),
        ):
            with pytest.raises(CapabilityRouteNotFoundError):
                await _run(args)

    @pytest.mark.asyncio
    async def test_run_shutdown_on_error(self, capsys):
        """Registry is shut down even when the route call fails."""
        mock_app_config = _make_mock_config(routes={"monitoring.trend": MagicMock()})
        mock_registry = _make_mock_registry()
        mock_router = _make_mock_router(side_effect=RuntimeError("adapter down"))

        args = _build_parser().parse_args([
            "--capability", "monitoring.trend",
            "--tenant-id", "t1",
            "--params", json.dumps({
                "asset_id": "a1",
                "measurement_point_id": "mp1",
                "start_time": "2026-01-01T00:00:00+00:00",
                "end_time": "2026-01-02T00:00:00+00:00",
            }),
        ])

        with (
            patch(_PATCH_CONFIG, return_value=mock_app_config),
            patch(_PATCH_REGISTRY, return_value=mock_registry),
            patch(_PATCH_ROUTER, return_value=mock_router),
        ):
            with pytest.raises(RuntimeError):
                await _run(args)

        mock_registry.shutdown_all.assert_awaited_once()


# ---------------------------------------------------------------------------
# Main Entry Point Tests
# ---------------------------------------------------------------------------


class TestMainEntryPoint:
    """Test main() error handling and exit codes."""

    def test_main_invalid_json_params(self, capsys, monkeypatch):
        """Invalid JSON in --params produces error output and exit 1."""
        monkeypatch.setattr(sys, "argv", [
            "cli",
            "--capability", "monitoring.trend",
            "--tenant-id", "t1",
            "--params", "not-valid-json",
        ])

        mock_app_config = _make_mock_config(routes={"monitoring.trend": MagicMock()})
        mock_registry = _make_mock_registry()

        with (
            patch(_PATCH_CONFIG, return_value=mock_app_config),
            patch(_PATCH_REGISTRY, return_value=mock_registry),
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1

        out = capsys.readouterr().out
        output = json.loads(out)
        assert output["ok"] is False
        assert output["error_type"] == "InvalidParamsJSON"

    def test_main_no_args_exits(self, monkeypatch):
        """Missing required args exits with code 2 (argparse default)."""
        monkeypatch.setattr(sys, "argv", ["cli"])
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 2

    def test_main_success(self, capsys, monkeypatch):
        """Successful main() invocation outputs JSON."""
        from deerflow.integrations.routing import ServiceResult

        monkeypatch.setattr(sys, "argv", [
            "cli",
            "--capability", "health.assessment",
            "--tenant-id", "t1",
            "--params", '{"asset_id": "a1"}',
        ])

        mock_result = ServiceResult(data={"score": 85}, source_system_keys=("sms",))
        mock_app_config = _make_mock_config(routes={"health.assessment": MagicMock()})
        mock_registry = _make_mock_registry()
        mock_router = _make_mock_router(return_value=mock_result)

        with (
            patch(_PATCH_CONFIG, return_value=mock_app_config),
            patch(_PATCH_REGISTRY, return_value=mock_registry),
            patch(_PATCH_ROUTER, return_value=mock_router),
        ):
            main()

        out = capsys.readouterr().out
        output = json.loads(out)
        assert output["ok"] is True
        assert output["source_system_keys"] == ["sms"]

    def test_main_router_error_exits_1(self, capsys, monkeypatch):
        """Router error produces error JSON and exit code 1."""
        monkeypatch.setattr(sys, "argv", [
            "cli",
            "--capability", "health.assessment",
            "--tenant-id", "t1",
            "--params", '{"asset_id": "a1"}',
        ])

        mock_app_config = _make_mock_config(routes={"health.assessment": MagicMock()})
        mock_registry = _make_mock_registry()
        mock_router = _make_mock_router(side_effect=RuntimeError("adapter failure"))

        with (
            patch(_PATCH_CONFIG, return_value=mock_app_config),
            patch(_PATCH_REGISTRY, return_value=mock_registry),
            patch(_PATCH_ROUTER, return_value=mock_router),
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1

        out = capsys.readouterr().out
        output = json.loads(out)
        assert output["ok"] is False
        assert "adapter failure" in output["error"]


# ---------------------------------------------------------------------------
# Partial Failure Tests
# ---------------------------------------------------------------------------


class TestPartialFailures:
    """Test partial failure serialization."""

    @pytest.mark.asyncio
    async def test_partial_failures_included(self, capsys):
        """Partial failures are included in output."""
        from deerflow.integrations.routing import ServiceResult
        from deerflow.integrations.models.provenance import PartialFailure

        pf = PartialFailure(
            system_key="sms",
            capability_key="health.assessment",
            error_type="IntegrationTimeoutError",
            error_message="timeout after 15s",
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

        mock_result = ServiceResult(
            data={"score": 85},
            source_system_keys=("ins",),
            partial_failures=(pf,),
        )

        mock_app_config = _make_mock_config(routes={"health.assessment": MagicMock()})
        mock_registry = _make_mock_registry()
        mock_router = _make_mock_router(return_value=mock_result)

        args = _build_parser().parse_args([
            "--capability", "health.assessment",
            "--tenant-id", "t1",
            "--params", '{"asset_id": "a1"}',
        ])

        with (
            patch(_PATCH_CONFIG, return_value=mock_app_config),
            patch(_PATCH_REGISTRY, return_value=mock_registry),
            patch(_PATCH_ROUTER, return_value=mock_router),
        ):
            await _run(args)

        out = capsys.readouterr().out
        output = json.loads(out)
        assert output["ok"] is True
        assert len(output["partial_failures"]) == 1
        assert output["partial_failures"][0]["system_key"] == "sms"
        assert output["partial_failures"][0]["error_type"] == "IntegrationTimeoutError"


# ---------------------------------------------------------------------------
# Action Mode Tests (Tasks 4.7-4.8)
# ---------------------------------------------------------------------------


class TestActionModeArgumentParsing:
    """Test CLI action mode argument parsing."""

    def test_action_with_adapter(self):
        """--action with --adapter is valid."""
        parser = _build_parser()
        args = parser.parse_args([
            "--action", "aggregate_kpi",
            "--adapter", "ins_prod",
            "--tenant-id", "t1",
        ])
        assert args.action == "aggregate_kpi"
        assert args.adapter == "ins_prod"
        assert args.capability is None

    def test_mutual_exclusion_action_and_capability(self):
        """--action and --capability cannot be used together."""
        parser = _build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([
                "--action", "aggregate_kpi",
                "--capability", "monitoring.trend",
                "--tenant-id", "t1",
            ])

    def test_requires_either_action_or_capability(self):
        """Must provide either --action or --capability."""
        parser = _build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([
                "--tenant-id", "t1",
            ])

    def test_action_choices(self):
        """--action only accepts aggregate_kpi or select_points."""
        parser = _build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([
                "--action", "invalid_action",
                "--tenant-id", "t1",
            ])


class TestActionModeExecution:
    """Test CLI action mode execution."""

    @pytest.mark.asyncio
    async def test_aggregate_kpi_success(self, capsys):
        """aggregate_kpi action returns KPI data."""
        from deerflow.integrations.adapters.ins import kpi_aggregator

        mock_app_config = _make_mock_config()
        mock_registry = _make_mock_registry_with_aggregator()

        args = _build_parser().parse_args([
            "--action", "aggregate_kpi",
            "--adapter", "ins_prod",
            "--tenant-id", "t1",
            "--params", json.dumps({
                "trend_data": {
                    "EQ1": [
                        {"time_ms": 1000, "values": {"speed": 100}},
                        {"time_ms": 2000, "values": {"speed": 0}},
                    ]
                },
                "kpi_keys": ["runtime_rate"],
            }),
        ])

        with (
            patch(_PATCH_CONFIG, return_value=mock_app_config),
            patch(_PATCH_REGISTRY, return_value=mock_registry),
        ):
            await _run(args)

        out = capsys.readouterr().out
        output = json.loads(out)
        assert output["ok"] is True
        assert output["adapter"] == "ins_prod"
        assert output["action"] == "aggregate_kpi"
        assert "kpis" in output["data"]
        assert "EQ1" in output["data"]["kpis"]
        assert output["data"]["kpis"]["EQ1"]["runtime_rate"] == 0.5

    @pytest.mark.asyncio
    async def test_select_points_success(self, capsys):
        """select_points action returns filtered points."""
        mock_app_config = _make_mock_config()
        mock_registry = _make_mock_registry_with_aggregator()

        args = _build_parser().parse_args([
            "--action", "select_points",
            "--adapter", "ins_prod",
            "--tenant-id", "t1",
            "--params", json.dumps({
                "components": [
                    {
                        "id": "p1",
                        "position_type": 81,
                        "endpoint_series": "8k",
                        "name": "振动",
                    }
                ],
                "kpi_key": "vibration_level",
                "eq_type": "rotating_machinery",
            }),
        ])

        with (
            patch(_PATCH_CONFIG, return_value=mock_app_config),
            patch(_PATCH_REGISTRY, return_value=mock_registry),
        ):
            await _run(args)

        out = capsys.readouterr().out
        output = json.loads(out)
        assert output["ok"] is True
        assert output["adapter"] == "ins_prod"
        assert output["action"] == "select_points"
        assert isinstance(output["data"], list)
        assert len(output["data"]) == 1
        assert output["data"][0]["id"] == "p1"

    @pytest.mark.asyncio
    async def test_action_missing_adapter(self, capsys):
        """Action without --adapter returns error."""
        mock_app_config = _make_mock_config()
        mock_registry = _make_mock_registry()

        args = _build_parser().parse_args([
            "--action", "aggregate_kpi",
            "--tenant-id", "t1",
            "--params", "{}",
        ])

        with (
            patch(_PATCH_CONFIG, return_value=mock_app_config),
            patch(_PATCH_REGISTRY, return_value=mock_registry),
        ):
            with pytest.raises(SystemExit):
                await _run(args)

        out = capsys.readouterr().out
        output = json.loads(out)
        assert output["ok"] is False
        assert output["error_type"] == "MissingAdapter"

    @pytest.mark.asyncio
    async def test_action_adapter_not_found(self, capsys):
        """Action with unknown adapter returns error."""
        mock_app_config = _make_mock_config()
        mock_registry = _make_mock_registry()
        mock_registry.get_adapter = MagicMock(return_value=None)  # explicit None

        args = _build_parser().parse_args([
            "--action", "aggregate_kpi",
            "--adapter", "unknown_adapter",
            "--tenant-id", "t1",
            "--params", "{}",
        ])

        with (
            patch(_PATCH_CONFIG, return_value=mock_app_config),
            patch(_PATCH_REGISTRY, return_value=mock_registry),
        ):
            with pytest.raises(SystemExit):
                await _run(args)

        out = capsys.readouterr().out
        output = json.loads(out)
        assert output["ok"] is False
        assert output["error_type"] == "AdapterNotFound"

    @pytest.mark.asyncio
    async def test_action_aggregate_kpi_missing_params(self, capsys):
        """aggregate_kpi with missing params returns error."""
        mock_app_config = _make_mock_config()
        mock_registry = _make_mock_registry_with_aggregator()

        args = _build_parser().parse_args([
            "--action", "aggregate_kpi",
            "--adapter", "ins_prod",
            "--tenant-id", "t1",
            "--params", json.dumps({}),  # missing trend_data and kpi_keys
        ])

        with (
            patch(_PATCH_CONFIG, return_value=mock_app_config),
            patch(_PATCH_REGISTRY, return_value=mock_registry),
        ):
            with pytest.raises(SystemExit):
                await _run(args)

        out = capsys.readouterr().out
        output = json.loads(out)
        assert output["ok"] is False
        assert "trend_data and kpi_keys are required" in output["error"]


def _make_mock_registry_with_aggregator():
    """Create a mock registry with an adapter that supports get_aggregator()."""
    from deerflow.integrations.adapters.ins.adapter import InsAdapter
    from deerflow.integrations.config import IntegrationSystemConfig

    config = IntegrationSystemConfig(
        system_key="ins_prod",
        system_type="ins",
        display_name="InS Production",
        base_url="http://ins.example.com",
        auth_type="bearer",
    )
    adapter = InsAdapter(config)

    registry = MagicMock()
    registry.get_adapter = MagicMock(return_value=adapter)
    registry.initialize_all = AsyncMock()
    registry.shutdown_all = AsyncMock()
    return registry

