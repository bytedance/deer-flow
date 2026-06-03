"""CLI subprocess bridge for integration capabilities.

Invocable as ``python -m deerflow.integrations.cli``.

Report scripts and other subprocess callers use this entry point to
retrieve data through the platform integration layer instead of calling
external systems directly.

Usage::

    python -m deerflow.integrations.cli \\
        --capability monitoring.trend \\
        --tenant-id tenant-1 \\
        --user-id user-1 \\
        --params '{"asset_id": "a1", "measurement_point_id": "mp1", ...}'

Output is always a single JSON document written to stdout.
On success::

    {"ok": true, "data": {...}, "source_system_keys": ["ins"], ...}

On failure::

    {"ok": false, "error": "...", "error_type": "IntegrationError"}
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any

from deerflow.config.app_config import AppConfig, get_app_config
from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.integrations.adapters.base import AuthContext
from deerflow.integrations.registry import initialize_registry
from deerflow.integrations.routing import CapabilityRouter

logger = logging.getLogger(__name__)


def _load_config_lenient(config_path: str | None = None) -> AppConfig:
    """Load AppConfig with lenient env resolution for the CLI bridge.

    The CLI bridge runs inside a sandbox container that doesn't have all the
    host's environment variables (e.g. ``$POSTGRES_URL``, ``$GATEWAY_PORT``).
    The bridge only needs the ``integrations`` section, so we strip all other
    sections before Pydantic validation to avoid type errors from unresolved
    env vars (e.g. empty string for an integer port field).
    """
    import yaml

    resolved = AppConfig.resolve_config_path(config_path)
    with open(resolved, encoding="utf-8") as f:
        config_data = yaml.safe_load(f) or {}

    # Keep only integrations and rpc — strip everything else to avoid env var
    # resolution failures in unrelated sections.
    stripped: dict[str, Any] = {}
    integrations_data = config_data.get("integrations")
    if integrations_data is not None:
        stripped["integrations"] = integrations_data
    rpc_data = config_data.get("rpc")
    if rpc_data is not None:
        stripped["rpc"] = rpc_data

    stripped = AppConfig.resolve_env_variables(stripped, strict=False)

    extensions_config = ExtensionsConfig.from_file()
    stripped["extensions"] = extensions_config.model_dump()

    # Add minimal sandbox config (required field with no default)
    if "sandbox" not in stripped:
        stripped["sandbox"] = {"use": "deerflow.sandbox.local:LocalSandboxProvider"}

    app_config = AppConfig.model_validate(stripped)

    # AppConfig stores integrations as a raw dict (extra="allow").  Convert it
    # to an IntegrationsConfig instance so the caller can use typed attributes.
    from deerflow.integrations.config import IntegrationsConfig

    if "integrations" in stripped and stripped["integrations"] is not None:
        app_config.integrations = IntegrationsConfig.model_validate(stripped["integrations"])

    # Load RPC config into the global singleton (model_validate alone doesn't do this)
    if app_config.rpc is not None:
        from deerflow.config.rpc_config import load_rpc_config_from_dict
        load_rpc_config_from_dict(app_config.rpc.model_dump())

    return app_config

_QUERY_CLASS_MAP: dict[str, str] = {
    "asset.catalog": "AssetCatalogQuery",
    "asset.context": "AssetContextQuery",
    "asset.overview": "AssetOverviewQuery",
    "monitoring.trend": "TrendQuery",
    "monitoring.waveform": "WaveformQuery",
    "monitoring.orbit": "OrbitQuery",
    "monitoring.alarm_history": "AlarmHistoryQuery",
    "health.assessment": "HealthAssessmentQuery",
    "health.anomaly_statistics": "AnomalyStatsQuery",
    "health.risk_ranking": "RiskRankingQuery",
}


def _output(obj: dict[str, Any]) -> None:
    """Write a JSON document to stdout and flush."""
    json.dump(obj, sys.stdout, cls=_IntegrationJSONEncoder, ensure_ascii=False)
    sys.stdout.write("\n")
    sys.stdout.flush()


def _error_output(error: Exception, *, error_type: str | None = None) -> dict[str, Any]:
    """Build a standardized error JSON payload."""
    return {
        "ok": False,
        "error": str(error),
        "error_type": error_type or type(error).__name__,
    }


class _IntegrationJSONEncoder(json.JSONEncoder):
    """JSON encoder that handles datetimes, dataclasses, and tuples."""

    def default(self, o: Any) -> Any:
        if isinstance(o, datetime):
            return o.isoformat()
        if dataclasses.is_dataclass(o) and not isinstance(o, type):
            return dataclasses.asdict(o)
        if isinstance(o, tuple):
            return list(o)
        return super().default(o)


def _build_query(capability_key: str, params: dict[str, Any], tenant_id: str) -> Any:
    """Construct the appropriate query dataclass from params.

    Datetime fields are parsed from ISO-format strings.
    The ``tenant_id`` is always injected from the CLI flag.
    """
    from deerflow.integrations.models import queries as q

    class_name = _QUERY_CLASS_MAP.get(capability_key)
    if class_name is None:
        from deerflow.integrations.errors import CapabilityRouteNotFoundError

        raise CapabilityRouteNotFoundError(
            capability_key=capability_key,
            message=f"No query class mapped for capability: {capability_key}",
        )

    query_cls = getattr(q, class_name)

    coerced = dict(params)
    coerced["tenant_id"] = tenant_id

    import inspect
    import typing

    sig = inspect.signature(query_cls)
    try:
        hints = typing.get_type_hints(query_cls)
    except Exception:
        hints = {}

    datetime_fields: list[str] = []
    for name, param in sig.parameters.items():
        ann = hints.get(name, param.annotation)
        if ann is datetime:
            datetime_fields.append(name)
        elif hasattr(ann, "__args__"):
            for arg in ann.__args__:
                if arg is datetime:
                    datetime_fields.append(name)
                    break

    for field_name in datetime_fields:
        value = coerced.get(field_name)
        if isinstance(value, str):
            coerced[field_name] = datetime.fromisoformat(value)

    valid_fields = set(sig.parameters.keys())
    filtered = {k: v for k, v in coerced.items() if k in valid_fields}

    return query_cls(**filtered)


def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(
        prog="deerflow.integrations.cli",
        description="CLI bridge for integration capabilities and actions",
    )

    # Mutual exclusion: --capability OR --action
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--capability",
        help="Capability key, e.g. 'monitoring.trend'",
    )
    mode_group.add_argument(
        "--action",
        choices=["aggregate_kpi", "select_points"],
        help="Action mode: adapter-internal computation (aggregate_kpi, select_points)",
    )

    parser.add_argument(
        "--adapter",
        help="Adapter key (required for --action mode), e.g. 'ins_prod'",
    )
    parser.add_argument(
        "--tenant-id",
        required=True,
        help="Tenant ID for auth context",
    )
    parser.add_argument(
        "--user-id",
        default="cli-subprocess",
        help="User ID for auth context (default: 'cli-subprocess')",
    )
    parser.add_argument(
        "--params",
        default="{}",
        help="JSON-encoded query parameters",
    )
    parser.add_argument(
        "--params-file",
        default=None,
        help="Path to a JSON file containing query parameters (overrides --params for large payloads)",
    )
    parser.add_argument(
        "--config-path",
        default=None,
        help="Path to config.yaml (default: auto-resolve)",
    )
    return parser


def _load_params(args: argparse.Namespace) -> dict[str, Any]:
    """Load params from --params-file if provided, otherwise from --params."""
    if args.params_file:
        with open(args.params_file, encoding="utf-8") as f:
            return json.load(f)
    return json.loads(args.params)


async def _run(args: argparse.Namespace) -> None:
    """Execute the capability call or action and write result to stdout."""
    app_config = _load_config_lenient()
    integration_config = app_config.integrations

    if integration_config is None or not integration_config.enabled:
        _output(_error_output(
            RuntimeError("Integrations are not enabled in config.yaml"),
            error_type="IntegrationDisabled",
        ))
        sys.exit(1)

    registry = initialize_registry(integration_config)
    await registry.initialize_all()

    try:
        # Action mode: direct adapter-internal computation
        if args.action:
            await _run_action(args, registry)
            return

        # Capability mode: router-based capability call
        router = CapabilityRouter(
            registry=registry,
            routes=integration_config.routes,
        )

        params: dict[str, Any] = _load_params(args)
        query = _build_query(args.capability, params, args.tenant_id)
        token = os.environ.get("DEER_FLOW_INTERNAL_AUTH_VALUE")
        auth_context = AuthContext(
            tenant_id=args.tenant_id,
            user_id=args.user_id,
            token=token,
        )
        logger.info(
            "CLI bridge: capability=%s, tenant=%s, user=%s, has_token=%s, token_len=%d",
            args.capability,
            args.tenant_id,
            args.user_id,
            bool(token),
            len(token) if token else 0,
        )

        result = await router.route(
            capability_key=args.capability,
            query=query,
            auth_context=auth_context,
        )

        _output({
            "ok": True,
            "data": result.data,
            "source_system_keys": list(result.source_system_keys),
            "partial_failures": [
                dataclasses.asdict(pf) for pf in result.partial_failures
            ],
        })
    finally:
        await registry.shutdown_all()


async def _run_action(args: argparse.Namespace, registry: Any) -> None:
    """Execute an action mode call (adapter-internal computation).

    Actions bypass the CapabilityRouter and call adapter-internal pure functions
    directly. Used for InS-specific KPI aggregation and point selection.
    """
    if not args.adapter:
        _output(_error_output(
            ValueError("--adapter is required when using --action mode"),
            error_type="MissingAdapter",
        ))
        sys.exit(1)

    adapter = registry.get(args.adapter)
    if adapter is None:
        _output(_error_output(
            ValueError(f"Adapter not found: {args.adapter}"),
            error_type="AdapterNotFound",
        ))
        sys.exit(1)

    # Check if adapter supports get_aggregator()
    if not hasattr(adapter, "get_aggregator"):
        _output(_error_output(
            ValueError(f"Adapter {args.adapter} does not support action mode"),
            error_type="ActionNotSupported",
        ))
        sys.exit(1)

    aggregator = adapter.get_aggregator()
    params: dict[str, Any] = _load_params(args)

    try:
        if args.action == "aggregate_kpi":
            result = _action_aggregate_kpi(aggregator, params)
        elif args.action == "select_points":
            result = _action_select_points(aggregator, params)
        else:
            _output(_error_output(
                ValueError(f"Unknown action: {args.action}"),
                error_type="UnknownAction",
            ))
            sys.exit(1)
            return

        _output({
            "ok": True,
            "data": result,
            "adapter": args.adapter,
            "action": args.action,
        })
    except Exception as e:
        logger.exception("Action %s failed", args.action)
        _output({
            "ok": False,
            "error": str(e),
            "error_type": type(e).__name__,
            "adapter": args.adapter,
            "action": args.action,
        })
        sys.exit(1)


def _action_aggregate_kpi(aggregator: Any, params: dict[str, Any]) -> dict[str, Any]:
    """Dispatch aggregate_kpi action.

    Expected params:
        trend_data: {equipment_id: [rows...]}
        kpi_keys: [kpi_key, ...]
        point_metadata: {point_id: meta_dict}  (optional)
    """
    trend_data = params.get("trend_data", {})
    kpi_keys = params.get("kpi_keys", [])
    point_metadata = params.get("point_metadata", {})

    if not trend_data or not kpi_keys:
        raise ValueError("trend_data and kpi_keys are required for aggregate_kpi")

    kpis, union_speed = aggregator.aggregate_equipment_kpis(
        trend_data, kpi_keys, point_metadata
    )
    hourly = aggregator.compute_hourly_runtime_rate(union_speed) if union_speed else []

    return {
        "kpis": kpis,
        "hourly_runtime_rate": hourly,
    }


def _action_select_points(aggregator: Any, params: dict[str, Any]) -> list[dict[str, Any]]:
    """Dispatch select_points action.

    Expected params:
        components: [component_tree...]
        kpi_key: str
        eq_type: str  (optional, default "all")
    """
    components = params.get("components", [])
    kpi_key = params.get("kpi_key", "")
    eq_type = params.get("eq_type", "all")

    if not components or not kpi_key:
        raise ValueError("components and kpi_key are required for select_points")

    return aggregator.select_points_for_kpi(components, kpi_key, eq_type)


def main() -> None:
    """CLI entry point."""
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    parser = _build_parser()
    args = parser.parse_args()

    try:
        asyncio.run(_run(args))
    except json.JSONDecodeError as e:
        _output(_error_output(e, error_type="InvalidParamsJSON"))
        sys.exit(1)
    except KeyboardInterrupt:
        _output(_error_output(RuntimeError("Interrupted"), error_type="Interrupted"))
        sys.exit(130)
    except Exception as e:
        logger.exception("CLI bridge failed")
        _output(_error_output(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
