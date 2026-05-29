"""CrmAdapter implementation.

Integrates with CRM (客户关系管理) systems providing customer profile,
contract, and service object lookup capabilities.

Capability keys:
- customer.get_profile: fetch customer profile by ID or search criteria
- customer.search: search customers by name, industry, region
- contract.get_detail: fetch contract details by contract ID
- contract.list_by_customer: list all contracts for a customer
- service_object.get_detail: fetch service object details
- service_object.list_by_customer: list service objects for a customer
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from deerflow.integrations.adapters.base import AuthContext, HealthStatus
from deerflow.integrations.adapters.crm.transform import (
    transform_contract,
    transform_customer_profile,
    transform_service_object,
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

_CRM_CAPABILITIES = (
    "customer.get_profile",
    "customer.search",
    "contract.get_detail",
    "contract.list_by_customer",
    "service_object.get_detail",
    "service_object.list_by_customer",
)


class CrmAdapter:
    """Adapter for CRM customer relationship management system.

    Capabilities:
    - customer.get_profile: Customer profile lookup
    - customer.search: Customer search by name/industry/region
    - contract.get_detail: Contract detail lookup
    - contract.list_by_customer: List contracts for a customer
    - service_object.get_detail: Service object detail lookup
    - service_object.list_by_customer: List service objects for a customer
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
        return "crm"

    @property
    def capabilities(self) -> tuple[str, ...]:
        return _CRM_CAPABILITIES

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
        logger.info("CrmAdapter initialized: %s (base_url=%s)", self._config.system_key, base_url)

    async def shutdown(self) -> None:
        if self._http:
            await self._http.aclose()
            self._http = None
        logger.info("CrmAdapter shutdown: %s", self._config.system_key)

    async def call(
        self,
        capability_key: str,
        query: Any,
        auth_context: AuthContext,
    ) -> Any:
        if not self._http:
            raise IntegrationUnavailableError(system_key=self._config.system_key)
        if capability_key not in _CRM_CAPABILITIES:
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
            raise  # unreachable, _handle_http_error always raises
        except (IntegrationError, IntegrationTimeoutError):
            raise
        except Exception as exc:
            raise IntegrationError(f"CRM call failed: {exc}") from exc

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
        if capability_key in ("customer.get_profile", "customer.search"):
            params = self._build_customer_params(query)
            resp = await self._http.get("/api/customers", params=params)
            resp.raise_for_status()
            return resp.json()
        elif capability_key in ("contract.get_detail", "contract.list_by_customer"):
            params = self._build_contract_params(query)
            resp = await self._http.get("/api/contracts", params=params)
            resp.raise_for_status()
            return resp.json()
        elif capability_key in ("service_object.get_detail", "service_object.list_by_customer"):
            params = self._build_service_object_params(query)
            resp = await self._http.get("/api/service-objects", params=params)
            resp.raise_for_status()
            return resp.json()
        raise IntegrationError(f"No dispatch for capability: {capability_key}")

    @staticmethod
    def _build_customer_params(query: Any) -> dict[str, str]:
        params: dict[str, str] = {}
        if hasattr(query, "customer_id") and query.customer_id:
            params["id"] = query.customer_id
        if hasattr(query, "search_text") and query.search_text:
            params["q"] = query.search_text
        if hasattr(query, "industry") and query.industry:
            params["industry"] = query.industry
        if hasattr(query, "region") and query.region:
            params["region"] = query.region
        if hasattr(query, "limit"):
            params["limit"] = str(query.limit)
        if hasattr(query, "offset") and query.offset:
            params["offset"] = str(query.offset)
        return params

    @staticmethod
    def _build_contract_params(query: Any) -> dict[str, str]:
        params: dict[str, str] = {}
        if hasattr(query, "contract_id") and query.contract_id:
            params["id"] = query.contract_id
        if hasattr(query, "customer_id") and query.customer_id:
            params["customer_id"] = query.customer_id
        if hasattr(query, "status") and query.status:
            params["status"] = query.status
        if hasattr(query, "limit"):
            params["limit"] = str(query.limit)
        return params

    @staticmethod
    def _build_service_object_params(query: Any) -> dict[str, str]:
        params: dict[str, str] = {}
        if hasattr(query, "service_object_id") and query.service_object_id:
            params["id"] = query.service_object_id
        if hasattr(query, "customer_id") and query.customer_id:
            params["customer_id"] = query.customer_id
        if hasattr(query, "asset_id") and query.asset_id:
            params["asset_id"] = query.asset_id
        if hasattr(query, "object_type") and query.object_type:
            params["type"] = query.object_type
        if hasattr(query, "limit"):
            params["limit"] = str(query.limit)
        return params

    def _transform(self, capability_key: str, raw: dict, elapsed: float) -> Any:
        from datetime import datetime

        from deerflow.integrations.models.provenance import Provenance

        provenance = Provenance(
            source_system_key=self._config.system_key,
            source_system_type="crm",
            capability_key=capability_key,
            fetched_at=datetime.now(),
        )

        if capability_key in ("customer.get_profile", "customer.search"):
            return transform_customer_profile(raw, provenance)
        elif capability_key in ("contract.get_detail", "contract.list_by_customer"):
            return transform_contract(raw, provenance)
        elif capability_key in ("service_object.get_detail", "service_object.list_by_customer"):
            return transform_service_object(raw, provenance)
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
                message=f"CRM auth failed (HTTP {status})",
            ) from exc
        raise IntegrationError(
            f"CRM HTTP error: {status} {exc.response.text[:200]}"
        ) from exc
