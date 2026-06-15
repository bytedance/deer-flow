"""Bridge to existing Ins API infrastructure.

Wraps existing InsApiClient (features-tool) and MachineServiceClient
to provide a unified interface for the InsAdapter.
"""

from __future__ import annotations

import logging
from typing import Any

from deerflow.rpc.rpc_client import RpcClient, get_rpc_client

logger = logging.getLogger(__name__)

SERVICE_NAME_BUS = "ins-bus-rpc"
SERVICE_NAME_BASE = "ins-base-rpc"
PATH_PREFIX_MACHINE = "/ins-bus-rpc/machineModel"
PATH_PREFIX_COMPONENT = "/ins-bus-rpc/componentModel"


class InsClientBridge:
    """Bridge to Ins API infrastructure.

    Data capabilities (trend, drops, waveform, orbit) go exclusively through
    features-tool InsApiClient. Device catalog/context queries go through
    ins-bus-rpc for equipment discovery.
    """

    def __init__(self, system_key: str, factory_id: str | None = None) -> None:
        self._system_key = system_key
        self._factory_id = factory_id
        self._rpc: RpcClient | None = None
        self._features_client: Any = None

    async def initialize(self) -> None:
        """Initialize the bridge, connecting to RPC services and features-tool."""
        self._rpc = get_rpc_client()
        if self._rpc is None:
            raise RuntimeError("RPC client is not configured")

        # Load features-tool client — required for all data capabilities
        try:
            import os
            import sys

            features_root = os.environ.get("FEATURES_TOOL_ROOT", "/mnt/skills/custom/features-tool")
            if features_root and features_root not in sys.path:
                sys.path.insert(0, features_root)

            from ins import InsApiClient, load_ins_settings  # type: ignore[import-not-found]

            settings = load_ins_settings()
            self._features_client = InsApiClient(settings)
            logger.info("features-tool InsApiClient loaded for %s", self._system_key)
        except Exception as e:
            logger.warning(
                "features-tool not available for %s: %s. "
                "Data capabilities (trend/drops/waveform/orbit) will be unavailable.",
                self._system_key,
                e,
            )

    async def shutdown(self) -> None:
        """Shutdown the bridge, releasing connections."""
        if self._features_client is not None:
            try:
                await self._features_client.close()
            except Exception:
                pass
            self._features_client = None

    async def health_check(self) -> dict[str, bool]:
        """Check connectivity to Ins services.

        Returns:
            Dict with service name -> connectivity status.
        """
        results: dict[str, bool] = {}

        if self._rpc is None:
            return {"ins-bus-rpc": False, "ins-base-rpc": False}

        for service_name in (SERVICE_NAME_BUS, SERVICE_NAME_BASE):
            try:
                await self._rpc.call_raw(
                    service_name,
                    f"/{service_name}/health",
                    "GET",
                    timeout=5.0,
                )
                results[service_name] = True
            except Exception:
                results[service_name] = False

        return results

    async def get_machine_catalog(
        self,
        user_id: int,
        org_id: int,
        page_size: int = 100,
        *,
        extra_headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Fetch machine catalog via MachineServiceClient path.

        Args:
            user_id: User ID for access control.
            org_id: Organization ID for scoping.
            page_size: Number of records per page.
            extra_headers: Per-call auth headers forwarded from AuthContext.
            **kwargs: Additional filter parameters.

        Returns:
            Raw response dict with machine records.
        """
        if self._rpc is None:
            raise RuntimeError("RPC client not initialized")

        params: dict[str, Any] = {
            "userId": user_id,
            "orgId": org_id,
            "noPage": 1,
            "currentPage": 1,
            "pageSize": page_size,
        }
        params.update(kwargs)

        result = await self._rpc.call_raw(
            SERVICE_NAME_BUS,
            f"{PATH_PREFIX_MACHINE}/getMachineDetailInfo",
            "GET",
            params,
            extra_headers=extra_headers,
        )
        return self._unwrap_ajax_result(result)

    async def get_machine_context(
        self,
        machine_id: int,
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Fetch machine detail with components.

        Args:
            machine_id: The machine ID.
            extra_headers: Per-call auth headers forwarded from AuthContext.

        Returns:
            Combined machine info + component list.
        """
        if self._rpc is None:
            raise RuntimeError("RPC client not initialized")

        # Fetch machine info
        info_result = await self._rpc.call_raw(
            SERVICE_NAME_BUS,
            f"{PATH_PREFIX_MACHINE}/getMachineInfoByIds",
            "GET",
            {"machineIds": str(machine_id)},
            extra_headers=extra_headers,
        )
        info = self._unwrap_result(info_result)
        machine_info = info[0] if isinstance(info, list) and info else {}

        # Fetch components
        comp_result = await self._rpc.call_raw(
            SERVICE_NAME_BUS,
            f"{PATH_PREFIX_COMPONENT}/getComponentInfoByMachineId",
            "GET",
            {"machineId": machine_id},
            extra_headers=extra_headers,
        )
        components = self._unwrap_ajax_result(comp_result)

        machine_info["components"] = components if isinstance(components, list) else []
        return machine_info

    async def get_slim_components(
        self,
        equipment_id: str,
    ) -> list[dict[str, Any]]:
        """Fetch slim component tree for an equipment via features-tool."""
        if self._features_client is None:
            from deerflow.integrations.errors import IntegrationUnavailableError

            raise IntegrationUnavailableError(
                message="get_slim_components requires features-tool",
                system_key=self._system_key,
                capability_key="asset.context",
            )

        return await self._features_client.get_slim_components(equipment_id)

    async def get_trend_data(
        self,
        component_ids: str,
        start_ms: str,
        end_ms: str,
        features: list[str],
        endpoint_series: str = "2k",
        factory_id: str | None = None,
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch trend data from InS via features-tool."""
        fid = factory_id or self._factory_id

        if self._features_client is None:
            from deerflow.integrations.errors import IntegrationUnavailableError

            raise IntegrationUnavailableError(
                message="get_trend_data requires features-tool",
                system_key=self._system_key,
                capability_key="monitoring.trend",
            )

        return await self._features_client.get_trend_data(
            component_ids, start_ms, end_ms, features,
            endpoint_series=endpoint_series,
            factory_id=fid,
            extra_headers=extra_headers,
        )

    async def get_machine_drops(
        self,
        equipment_id: str,
        start_ms: str,
        end_ms: str,
        event_types: list[int],
        endpoint_series: str = "8k",
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch machine drop events (alarm history) via features-tool."""
        if self._features_client is None:
            from deerflow.integrations.errors import IntegrationUnavailableError

            raise IntegrationUnavailableError(
                message="get_machine_drops requires features-tool",
                system_key=self._system_key,
                capability_key="monitoring.alarm_history",
            )

        return await self._features_client.get_machine_drops(
            equipment_id, start_ms, end_ms, event_types,
            endpoint_series=endpoint_series,
            factory_id=self._factory_id,
        )

    async def get_waveform(
        self,
        component_id: str,
        endpoint_series: str = "8k",
    ) -> dict[str, Any]:
        """Fetch waveform data.

        Requires features-tool; no RPC fallback.
        """
        if self._features_client is None:
            from deerflow.integrations.errors import IntegrationUnavailableError

            raise IntegrationUnavailableError(
                message="Waveform requires features-tool",
                system_key=self._system_key,
                capability_key="monitoring.waveform",
            )

        return await self._features_client.get_waveform(
            component_id,
            endpoint_series=endpoint_series,
            factory_id=self._factory_id,
        )

    async def get_orbit(
        self,
        component_id: str,
        endpoint_series: str = "8k",
    ) -> dict[str, Any]:
        """Fetch orbit data.

        Requires features-tool; no RPC fallback.
        """
        if self._features_client is None:
            from deerflow.integrations.errors import IntegrationUnavailableError

            raise IntegrationUnavailableError(
                message="Orbit requires features-tool",
                system_key=self._system_key,
                capability_key="monitoring.orbit",
            )

        return await self._features_client.get_orbit(
            component_id,
            endpoint_series=endpoint_series,
            factory_id=self._factory_id,
        )

    @staticmethod
    def _unwrap_result(result: Any) -> Any:
        """Extract data from ResultT wrapper {code, message, data, success}."""
        if isinstance(result, dict):
            return result.get("data", result)
        return result

    @staticmethod
    def _unwrap_ajax_result(result: Any) -> Any:
        """Extract data from AjaxResult wrapper {code, msg, data}."""
        if isinstance(result, dict):
            return result.get("data", result)
        return result
