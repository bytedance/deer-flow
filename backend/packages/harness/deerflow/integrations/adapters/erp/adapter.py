"""ErpAdapter implementation.

Integrates with ERP (企业资源计划) systems providing work order management
and inventory/spare parts capabilities.

Capability keys:
- maintenance.get_work_orders: fetch work orders by asset, status, or date range
- maintenance.get_work_order_detail: fetch single work order with parts usage
- inventory.get_parts: search spare parts by category, name, or part number
- inventory.get_part_detail: fetch spare part with inventory levels
- inventory.check_availability: check part availability across warehouses
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from deerflow.integrations.adapters.base import AuthContext, HealthStatus
from deerflow.integrations.adapters.erp.transform import (
    transform_inventory_items,
    transform_spare_parts,
    transform_work_orders,
)
from deerflow.integrations.config import IntegrationSystemConfig
from deerflow.integrations.errors import (
    IntegrationAuthError,
    IntegrationDataShapeError,
    IntegrationError,
    IntegrationTimeoutError,
    IntegrationUnavailableError,
)

logger = logging.getLogger(__name__)

_ERP_CAPABILITIES = (
    "maintenance.get_work_orders",
    "maintenance.get_work_order_detail",
    "inventory.get_parts",
    "inventory.get_part_detail",
    "inventory.check_availability",
)


class ErpAdapter:
    """Adapter for ERP enterprise resource planning system.

    Capabilities:
    - maintenance.get_work_orders: Work order list query
    - maintenance.get_work_order_detail: Work order detail with parts
    - inventory.get_parts: Spare part search
    - inventory.get_part_detail: Spare part detail with inventory
    - inventory.check_availability: Part availability check
    """

    def __init__(self, config: IntegrationSystemConfig) -> None:
        self._config = config
        self._http: httpx.AsyncClient | None = None
        self._api_key: str | None = None

    @property
    def system_key(self) -> str:
        return self._config.system_key

    @property
    def system_type(self) -> str:
        return "erp"

    @property
    def capabilities(self) -> tuple[str, ...]:
        return _ERP_CAPABILITIES

    async def initialize(self) -> None:
        self._api_key = self._config.resolve_secret()
        base_url = self._config.base_url.rstrip("/")
        if self._config.base_path:
            base_url = f"{base_url}{self._config.base_path}"
        self._http = httpx.AsyncClient(
            base_url=base_url,
            timeout=self._config.timeout_seconds,
            headers=self._build_headers(),
        )
        logger.info("ErpAdapter initialized: %s (base_url=%s)", self._config.system_key, base_url)

    async def shutdown(self) -> None:
        if self._http:
            await self._http.aclose()
            self._http = None
        logger.info("ErpAdapter shutdown: %s", self._config.system_key)

    async def call(
        self,
        capability_key: str,
        query: Any,
        auth_context: AuthContext,
    ) -> Any:
        if not self._http:
            raise IntegrationUnavailableError(system_key=self._config.system_key)
        if capability_key not in _ERP_CAPABILITIES:
            raise IntegrationError(f"Unsupported capability: {capability_key}")

        started = time.monotonic()
        try:
            raw = await self._dispatch(capability_key, query)
            elapsed = time.monotonic() - started
            return self._transform(capability_key, raw, elapsed)
        except httpx.TimeoutException as exc:
            raise IntegrationTimeoutError(
                system_key=self._config.system_key,
                capability=capability_key,
                timeout_seconds=self._config.timeout_seconds,
            ) from exc
        except httpx.HTTPStatusError as exc:
            self._handle_http_error(exc)
            raise
        except (IntegrationError, IntegrationTimeoutError):
            raise
        except Exception as exc:
            raise IntegrationError(f"ERP call failed: {exc}") from exc

    async def health_check(self) -> HealthStatus:
        if not self._http:
            return HealthStatus(healthy=False, message="Not initialized")
        try:
            resp = await self._http.get("/health", timeout=5.0)
            healthy = resp.status_code < 500
            return HealthStatus(
                healthy=healthy,
                message="OK" if healthy else f"HTTP {resp.status_code}",
            )
        except Exception as exc:
            return HealthStatus(healthy=False, message=str(exc)[:200])

    def _build_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Accept": "application/json"}
        if self._api_key:
            headers["X-API-Key"] = self._api_key
        return headers

    async def _dispatch(self, capability_key: str, query: Any) -> dict[str, Any]:
        assert self._http is not None
        if capability_key in ("maintenance.get_work_orders", "maintenance.get_work_order_detail"):
            params = self._build_work_order_params(query)
            resp = await self._http.get("/api/work-orders", params=params)
            resp.raise_for_status()
            return resp.json()
        elif capability_key in ("inventory.get_parts", "inventory.get_part_detail"):
            params = self._build_part_params(query)
            resp = await self._http.get("/api/parts", params=params)
            resp.raise_for_status()
            return resp.json()
        elif capability_key == "inventory.check_availability":
            params = self._build_inventory_params(query)
            resp = await self._http.get("/api/inventory", params=params)
            resp.raise_for_status()
            return resp.json()
        raise IntegrationError(f"No dispatch for capability: {capability_key}")

    @staticmethod
    def _build_work_order_params(query: Any) -> dict[str, str]:
        params: dict[str, str] = {}
        if hasattr(query, "work_order_id") and query.work_order_id:
            params["id"] = query.work_order_id
        if hasattr(query, "asset_id") and query.asset_id:
            params["asset_id"] = query.asset_id
        if hasattr(query, "status") and query.status:
            params["status"] = query.status
        if hasattr(query, "priority") and query.priority:
            params["priority"] = query.priority
        if hasattr(query, "start_time") and query.start_time:
            params["start"] = query.start_time.isoformat()
        if hasattr(query, "end_time") and query.end_time:
            params["end"] = query.end_time.isoformat()
        if hasattr(query, "limit"):
            params["limit"] = str(query.limit)
        if hasattr(query, "offset") and query.offset:
            params["offset"] = str(query.offset)
        return params

    @staticmethod
    def _build_part_params(query: Any) -> dict[str, str]:
        params: dict[str, str] = {}
        if hasattr(query, "part_id") and query.part_id:
            params["id"] = query.part_id
        if hasattr(query, "part_number") and query.part_number:
            params["part_number"] = query.part_number
        if hasattr(query, "category") and query.category:
            params["category"] = query.category
        if hasattr(query, "search_text") and query.search_text:
            params["q"] = query.search_text
        if hasattr(query, "limit"):
            params["limit"] = str(query.limit)
        return params

    @staticmethod
    def _build_inventory_params(query: Any) -> dict[str, str]:
        params: dict[str, str] = {}
        if hasattr(query, "part_id") and query.part_id:
            params["part_id"] = query.part_id
        if hasattr(query, "warehouse") and query.warehouse:
            params["warehouse"] = query.warehouse
        if hasattr(query, "min_quantity"):
            params["min_qty"] = str(query.min_quantity)
        if hasattr(query, "limit"):
            params["limit"] = str(query.limit)
        return params

    def _transform(self, capability_key: str, raw: dict, elapsed: float) -> Any:
        from datetime import datetime

        from deerflow.integrations.models.provenance import Provenance

        provenance = Provenance(
            source_system_key=self._config.system_key,
            source_system_type="erp",
            capability_key=capability_key,
            fetched_at=datetime.now(),
        )

        if capability_key in ("maintenance.get_work_orders", "maintenance.get_work_order_detail"):
            return transform_work_orders(raw, provenance)
        elif capability_key in ("inventory.get_parts", "inventory.get_part_detail"):
            return transform_spare_parts(raw, provenance)
        elif capability_key == "inventory.check_availability":
            return transform_inventory_items(raw, provenance)
        raise IntegrationDataShapeError(
            system_key=self._config.system_key,
            capability=capability_key,
            message=f"No transform for capability: {capability_key}",
        )

    def _handle_http_error(self, exc: httpx.HTTPStatusError) -> None:
        status = exc.response.status_code
        if status in (401, 403):
            raise IntegrationAuthError(
                system_key=self._config.system_key,
                message=f"ERP auth failed (HTTP {status})",
            ) from exc
        raise IntegrationError(
            f"ERP HTTP error: {status} {exc.response.text[:200]}"
        ) from exc
