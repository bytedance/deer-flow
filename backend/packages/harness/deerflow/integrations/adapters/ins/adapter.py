"""InsAdapter implementation.

Integrates with InS (实时监测系统) providing asset catalog, context,
and monitoring capabilities (trend, waveform, orbit, alarm_history).
"""

from __future__ import annotations

import logging
import time
from typing import Any

from deerflow.integrations.adapters.base import AuthContext, HealthStatus
from deerflow.integrations.adapters.ins.client_bridge import InsClientBridge
from deerflow.integrations.adapters.ins.transform import (
    transform_alarm_history,
    transform_asset_catalog,
    transform_asset_context,
    transform_orbit,
    transform_trend_series,
    transform_waveform,
)
from deerflow.integrations.config import IntegrationSystemConfig
from deerflow.integrations.errors import (
    IntegrationError,
    IntegrationTimeoutError,
)

logger = logging.getLogger(__name__)


class InsAdapter:
    """Adapter for InS real-time monitoring system.

    Capabilities:
    - asset.catalog: Equipment catalog via MachineServiceClient
    - asset.context: Equipment context with components
    - monitoring.trend: Trend time-series data (supports batch equipment_ids)
    - monitoring.waveform: Waveform and spectrum data
    - monitoring.orbit: Orbit (shaft centerline) data
    - monitoring.alarm_history: Machine drop events (alarms, supports batch equipment_ids)

    CLI Action Mode:
    The adapter exposes ``get_aggregator()`` to provide KPI aggregation functions
    for CLI ``--action`` mode. These are adapter-internal pure functions that
    understand InS data model specifics (position_types, endpoint_series, alarm_thresholds).
    """

    def __init__(self, config: IntegrationSystemConfig) -> None:
        self._config = config
        self._bridge: InsClientBridge | None = None
        self._factory_id: str | None = config.extra_config.get("factory_id")

    @property
    def system_key(self) -> str:
        """Unique system identifier."""
        return self._config.system_key

    @property
    def system_type(self) -> str:
        """System type discriminator."""
        return "ins"

    async def initialize(self) -> None:
        """Initialize adapter resources."""
        self._bridge = InsClientBridge(
            system_key=self._config.system_key,
            factory_id=self._factory_id,
        )
        await self._bridge.initialize()
        logger.info("InsAdapter initialized: %s", self._config.system_key)

    async def shutdown(self) -> None:
        """Shutdown adapter resources."""
        if self._bridge:
            await self._bridge.shutdown()
            self._bridge = None
        logger.info("InsAdapter shutdown: %s", self._config.system_key)

    def get_aggregator(self):
        """Return the KPI aggregator module for CLI action mode.

        The aggregator provides pure functions for InS-specific KPI computation:
        - aggregate_trend_to_kpi(): 6 derivation methods (mean/max/runtime_rate/etc.)
        - select_points_for_kpi(): component tree filtering by position_type/series
        - hourly_runtime_rate(): 24-bucket speed > 0 ratios
        - aggregate_equipment_kpis(): multi-equipment batch aggregation

        Returns:
            The kpi_aggregator module with all aggregation functions.
        """
        from deerflow.integrations.adapters.ins import kpi_aggregator

        return kpi_aggregator

    async def call(
        self,
        capability_key: str,
        query: Any,
        auth_context: AuthContext,
    ) -> Any:
        """Execute a capability call.

        Args:
            capability_key: Capability identifier.
            query: Query object specific to the capability.
            auth_context: Authentication context.

        Returns:
            Canonical model result.

        Raises:
            IntegrationError: On capability failure.
        """
        if self._bridge is None:
            raise IntegrationError(
                message=f"InsAdapter {self._config.system_key} not initialized",
                system_key=self._config.system_key,
                capability_key=capability_key,
            )

        # Dispatch to capability handler
        handlers = {
            "asset.catalog": self._handle_asset_catalog,
            "asset.context": self._handle_asset_context,
            "monitoring.trend": self._handle_monitoring_trend,
            "monitoring.waveform": self._handle_monitoring_waveform,
            "monitoring.orbit": self._handle_monitoring_orbit,
            "monitoring.alarm_history": self._handle_monitoring_alarm_history,
        }

        handler = handlers.get(capability_key)
        if handler is None:
            raise IntegrationError(
                message=f"Unsupported capability: {capability_key}",
                system_key=self._config.system_key,
                capability_key=capability_key,
            )

        try:
            return await handler(query, auth_context)
        except IntegrationError:
            raise
        except TimeoutError as e:
            raise IntegrationTimeoutError(
                message=f"Timeout calling {capability_key}: {e}",
                system_key=self._config.system_key,
                capability_key=capability_key,
            ) from e
        except Exception as e:
            # Redact sensitive info from error logs
            error_msg = str(e)
            if auth_context.token:
                error_msg = error_msg.replace(auth_context.token, "***REDACTED***")
            logger.error(
                "InsAdapter %s capability %s failed: %s",
                self._config.system_key,
                capability_key,
                error_msg,
            )
            raise IntegrationError(
                message=f"Capability {capability_key} failed: {e}",
                system_key=self._config.system_key,
                capability_key=capability_key,
            ) from e

    async def health_check(self) -> HealthStatus:
        """Check adapter health.

        Returns:
            HealthStatus with connectivity info.
        """
        if self._bridge is None:
            return HealthStatus(
                healthy=False,
                message="Adapter not initialized",
                checked_at=None,
            )

        start_time = time.time()
        try:
            results = await self._bridge.health_check()
            latency_ms = (time.time() - start_time) * 1000

            all_healthy = all(results.values())
            message = ", ".join(
                f"{k}: {'OK' if v else 'FAIL'}" for k, v in results.items()
            )

            return HealthStatus(
                healthy=all_healthy,
                latency_ms=latency_ms,
                message=message,
                details=results,
            )
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            return HealthStatus(
                healthy=False,
                latency_ms=latency_ms,
                message=f"Health check failed: {e}",
            )

    # --- Capability Handlers ---

    def _build_extra_headers(self, auth_context: AuthContext) -> dict[str, str] | None:
        """Build per-call auth headers when auth_mode is 'user_token'.

        Returns ``None`` when no user token is available or auth_mode is
        ``'static'`` (the default), so bridge methods fall through to the
        service-level credentials already configured on the RPC client.
        """
        if self._config.auth_mode != "user_token":
            return None
        if not auth_context.token:
            return None
        return {"Authorization": f"Bearer {auth_context.token}"}

    async def _handle_asset_catalog(
        self,
        query: Any,
        auth_context: AuthContext,
    ) -> tuple[Any, ...]:
        """Handle asset.catalog capability."""
        if self._bridge is None:
            raise IntegrationError(
                message="Bridge not initialized",
                system_key=self._config.system_key,
            )

        # Extract query parameters
        user_id = int(auth_context.extra.get("user_id", 0))
        org_id = int(auth_context.extra.get("org_id", 0))
        page_size = getattr(query, "limit", 100)

        kwargs: dict[str, Any] = {}
        if hasattr(query, "search_text") and query.search_text:
            kwargs["machine_name"] = query.search_text
        if hasattr(query, "extra_filters"):
            kwargs.update(query.extra_filters)

        raw_data = await self._bridge.get_machine_catalog(
            user_id=user_id,
            org_id=org_id,
            page_size=page_size,
            extra_headers=self._build_extra_headers(auth_context),
            **kwargs,
        )

        return transform_asset_catalog(raw_data, self._config.system_key)

    async def _handle_asset_context(
        self,
        query: Any,
        auth_context: AuthContext,
    ) -> Any:
        """Handle asset.context capability."""
        if self._bridge is None:
            raise IntegrationError(
                message="Bridge not initialized",
                system_key=self._config.system_key,
            )

        asset_id = getattr(query, "asset_id", "")
        if not asset_id:
            raise IntegrationError(
                message="asset_id is required for asset.context",
                system_key=self._config.system_key,
                capability_key="asset.context",
            )

        raw_data = await self._bridge.get_machine_context(
            int(asset_id),
            extra_headers=self._build_extra_headers(auth_context),
        )
        return transform_asset_context(raw_data, self._config.system_key)

    async def _handle_monitoring_trend(
        self,
        query: Any,
        auth_context: AuthContext,
    ) -> Any:
        """Handle monitoring.trend capability.

        Supports both single-asset and batch equipment queries.
        """
        if self._bridge is None:
            raise IntegrationError(
                message="Bridge not initialized",
                system_key=self._config.system_key,
            )

        # Check for batch query
        equipment_ids = getattr(query, "equipment_ids", ())
        if equipment_ids:
            return await self._handle_batch_trend(query, auth_context, equipment_ids)

        # Single-asset query (backward compatible)
        measurement_point_id = getattr(query, "measurement_point_id", "")
        start_time = getattr(query, "start_time", None)
        end_time = getattr(query, "end_time", None)

        if not measurement_point_id or not start_time or not end_time:
            raise IntegrationError(
                message="measurement_point_id, start_time, end_time required",
                system_key=self._config.system_key,
                capability_key="monitoring.trend",
            )

        # Convert datetime to milliseconds
        start_ms = str(int(start_time.timestamp() * 1000))
        end_ms = str(int(end_time.timestamp() * 1000))

        # Determine endpoint series from extra_params or default
        endpoint_series = getattr(query, "extra_params", {}).get("endpoint_series", "2k")
        features = getattr(query, "extra_params", {}).get("features", ["value"])

        raw_rows = await self._bridge.get_trend_data(
            component_ids=str(measurement_point_id),
            start_ms=start_ms,
            end_ms=end_ms,
            features=features if isinstance(features, list) else [features],
            endpoint_series=endpoint_series,
            extra_headers=self._build_extra_headers(auth_context),
        )

        return transform_trend_series(raw_rows, query, self._config.system_key)

    async def _handle_batch_trend(
        self,
        query: Any,
        auth_context: AuthContext,
        equipment_ids: tuple[str, ...],
    ) -> dict[str, Any]:
        """Handle batch trend query for multiple equipment.

        For each equipment, fetches the component tree, selects relevant
        measurement points, and queries trend data using point IDs (not
        equipment IDs).

        Returns raw trend rows per equipment (not transformed TrendSeries).
        This format is required for KPI aggregation which needs access to
        multiple features (speed, pp_value, v_rms, etc.) in their raw form.

        Returns:
            Dict with:
            - equipment_data: {equipment_id: [raw_rows...]}
            - equipment_ids: list of equipment IDs
            - point_metadata: {point_id: metadata_dict} for alarm thresholds
        """
        start_time = getattr(query, "start_time", None)
        end_time = getattr(query, "end_time", None)
        if not start_time or not end_time:
            raise IntegrationError(
                message="start_time, end_time required for batch trend query",
                system_key=self._config.system_key,
                capability_key="monitoring.trend",
            )

        start_ms = str(int(start_time.timestamp() * 1000))
        end_ms = str(int(end_time.timestamp() * 1000))
        endpoint_series = getattr(query, "extra_params", {}).get("endpoint_series", "8k")
        features = getattr(query, "extra_params", {}).get("features", ["pp_value", "speed", "value"])
        features_list = features if isinstance(features, list) else [features]

        results_by_equipment: dict[str, Any] = {}
        point_metadata: dict[str, dict[str, Any]] = {}

        for eq_id in equipment_ids:
            # Fetch component tree to get measurement point IDs
            try:
                components = await self._bridge.get_slim_components(eq_id)
                logger.info(
                    "Fetched %d top-level components for equipment %s",
                    len(components), eq_id,
                )
            except Exception as e:
                logger.warning("Failed to fetch components for %s: %s", eq_id, e)
                results_by_equipment[eq_id] = []
                continue

            # Select measurement points from the component tree
            selected_points = self._select_measurement_points(
                components, endpoint_series, features_list
            )

            if not selected_points:
                logger.warning(
                    "No matching points found for equipment %s (target_series=%s)",
                    eq_id, endpoint_series,
                )
                results_by_equipment[eq_id] = []
                continue

            logger.info(
                "Selected %d measurement points for equipment %s: %s",
                len(selected_points), eq_id,
                [p.get("id") for p in selected_points[:5]],  # First 5 IDs
            )

            # Group points by endpoint_series for batched queries
            points_by_series: dict[str, list[str]] = {}
            for point in selected_points:
                series = point.get("endpoint_series", endpoint_series)
                points_by_series.setdefault(series, []).append(point["id"])

            # Fetch trend data for each series group
            all_rows: list[dict[str, Any]] = []
            for series, point_ids in points_by_series.items():
                combined_id = ",".join(point_ids)
                raw_rows = await self._bridge.get_trend_data(
                    component_ids=combined_id,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    features=features_list,
                    endpoint_series=series,
                    extra_headers=self._build_extra_headers(auth_context),
                )
                all_rows.extend(raw_rows or [])

            results_by_equipment[eq_id] = all_rows

            # Collect point metadata for alarm threshold resolution
            if all_rows:
                point_metadata[eq_id] = {
                    "endpoint_series": endpoint_series,
                    "features": features_list,
                    "selected_points": selected_points,
                }

        return {
            "equipment_data": results_by_equipment,
            "equipment_ids": list(equipment_ids),
            "point_metadata": point_metadata,
        }

    def _select_measurement_points(
        self,
        components: list[dict[str, Any]],
        target_series: str,
        target_features: list[str],
    ) -> list[dict[str, Any]]:
        """Select measurement points from component tree that match the criteria.

        Uses stack-based traversal (not recursive). Once a node with
        ``endpoint_series`` is found, it's yielded and we don't recurse into
        its children (matching the behavior in _ins_provider._iter_points).

        Args:
            components: Slim component tree from get_slim_components()
            target_series: Target endpoint series (e.g., "8k", "2k")
            target_features: List of features to fetch

        Returns:
            List of point dicts with id, endpoint_series, etc.
        """
        selected: list[dict[str, Any]] = []
        stack: list[dict[str, Any]] = list(components)

        while stack:
            node = stack.pop()
            if not isinstance(node, dict):
                continue

            # Check if this node is a measurement point (has endpoint_series)
            node_series = node.get("endpoint_series")
            if node_series is not None:
                # Match by endpoint series
                if node_series == target_series:
                    selected.append(node)
                # Don't recurse into children of measurement points
                continue

            # Recurse into children
            for key in ("children", "points"):
                for child in node.get(key) or []:
                    if isinstance(child, dict):
                        stack.append(child)

        return selected

    async def _handle_monitoring_waveform(
        self,
        query: Any,
        auth_context: AuthContext,
    ) -> Any:
        """Handle monitoring.waveform capability."""
        if self._bridge is None:
            raise IntegrationError(
                message="Bridge not initialized",
                system_key=self._config.system_key,
            )

        measurement_point_id = getattr(query, "measurement_point_id", "")
        if not measurement_point_id:
            raise IntegrationError(
                message="measurement_point_id required",
                system_key=self._config.system_key,
                capability_key="monitoring.waveform",
            )

        endpoint_series = getattr(query, "extra_params", {}).get("endpoint_series", "8k")

        raw_data = await self._bridge.get_waveform(
            component_id=str(measurement_point_id),
            endpoint_series=endpoint_series,
        )

        return transform_waveform(raw_data, query, self._config.system_key)

    async def _handle_monitoring_orbit(
        self,
        query: Any,
        auth_context: AuthContext,
    ) -> Any:
        """Handle monitoring.orbit capability."""
        if self._bridge is None:
            raise IntegrationError(
                message="Bridge not initialized",
                system_key=self._config.system_key,
            )

        measurement_point_id = getattr(query, "measurement_point_id", "")
        if not measurement_point_id:
            raise IntegrationError(
                message="measurement_point_id required",
                system_key=self._config.system_key,
                capability_key="monitoring.orbit",
            )

        endpoint_series = getattr(query, "extra_params", {}).get("endpoint_series", "8k")

        raw_data = await self._bridge.get_orbit(
            component_id=str(measurement_point_id),
            endpoint_series=endpoint_series,
        )

        return transform_orbit(raw_data, query, self._config.system_key)

    async def _handle_monitoring_alarm_history(
        self,
        query: Any,
        auth_context: AuthContext,
    ) -> tuple[Any, ...]:
        """Handle monitoring.alarm_history capability.

        Supports both single-asset and batch equipment queries.
        """
        if self._bridge is None:
            raise IntegrationError(
                message="Bridge not initialized",
                system_key=self._config.system_key,
            )

        # Check for batch query
        equipment_ids = getattr(query, "equipment_ids", ())
        if equipment_ids:
            return await self._handle_batch_alarm_history(
                query, auth_context, equipment_ids
            )

        # Single-asset query (backward compatible)
        asset_id = getattr(query, "asset_id", "")
        start_time = getattr(query, "start_time", None)
        end_time = getattr(query, "end_time", None)

        if not asset_id or not start_time or not end_time:
            raise IntegrationError(
                message="asset_id, start_time, end_time required",
                system_key=self._config.system_key,
                capability_key="monitoring.alarm_history",
            )

        start_ms = str(int(start_time.timestamp() * 1000))
        end_ms = str(int(end_time.timestamp() * 1000))

        # Determine event types based on equipment type
        eq_type = getattr(query, "eq_type", "rotating_machinery")
        from deerflow.integrations.adapters.ins.kpi_map import (
            ENDPOINT_SERIES_BY_EQ_TYPE,
            EVENT_TYPES_BY_EQ_TYPE,
        )

        event_types = list(EVENT_TYPES_BY_EQ_TYPE.get(eq_type, (1, 2, 3, 14, 15)))
        endpoint_series = ENDPOINT_SERIES_BY_EQ_TYPE.get(eq_type, "8k")

        raw_events = await self._bridge.get_machine_drops(
            equipment_id=str(asset_id),
            start_ms=start_ms,
            end_ms=end_ms,
            event_types=event_types,
            endpoint_series=endpoint_series,
            extra_headers=self._build_extra_headers(auth_context),
        )

        return transform_alarm_history(raw_events, self._config.system_key, str(asset_id))

    async def _handle_batch_alarm_history(
        self,
        query: Any,
        auth_context: AuthContext,
        equipment_ids: tuple[str, ...],
    ) -> dict[str, Any]:
        """Handle batch alarm history query for multiple equipment.

        Returns:
            Dict mapping equipment_id to alarm events.
        """
        start_time = getattr(query, "start_time", None)
        end_time = getattr(query, "end_time", None)
        if not start_time or not end_time:
            raise IntegrationError(
                message="start_time, end_time required for batch alarm query",
                system_key=self._config.system_key,
                capability_key="monitoring.alarm_history",
            )

        start_ms = str(int(start_time.timestamp() * 1000))
        end_ms = str(int(end_time.timestamp() * 1000))
        eq_type = getattr(query, "eq_type", "rotating_machinery")

        from deerflow.integrations.adapters.ins.kpi_map import (
            ENDPOINT_SERIES_BY_EQ_TYPE,
            EVENT_TYPES_BY_EQ_TYPE,
        )

        event_types = list(EVENT_TYPES_BY_EQ_TYPE.get(eq_type, (1, 2, 3, 14, 15)))
        endpoint_series = ENDPOINT_SERIES_BY_EQ_TYPE.get(eq_type, "8k")

        results_by_equipment: dict[str, Any] = {}
        for eq_id in equipment_ids:
            raw_events = await self._bridge.get_machine_drops(
                equipment_id=str(eq_id),
                start_ms=start_ms,
                end_ms=end_ms,
                event_types=event_types,
                endpoint_series=endpoint_series,
                extra_headers=self._build_extra_headers(auth_context),
            )
            results_by_equipment[eq_id] = transform_alarm_history(
                raw_events, self._config.system_key, str(eq_id)
            )

        return {"equipment_data": results_by_equipment, "equipment_ids": list(equipment_ids)}
