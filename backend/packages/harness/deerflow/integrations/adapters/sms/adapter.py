"""SmsAdapter implementation.

Integrates with Sms (设备异常统计与评估系统) providing health assessment,
anomaly statistics, and risk ranking capabilities.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from deerflow.integrations.adapters.base import AuthContext, HealthStatus
from deerflow.integrations.adapters.sms.transform import (
    transform_anomaly_stats,
    transform_health_assessment,
    transform_risk_ranking,
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


class SmsAdapter:
    """Adapter for Sms equipment assessment system.

    Capabilities:
    - health.assessment: Equipment health score and dimensions
    - health.anomaly_statistics: Anomaly detection statistics
    - health.risk_ranking: Equipment risk ranking
    """

    def __init__(self, config: IntegrationSystemConfig) -> None:
        self._config = config
        self._http: httpx.AsyncClient | None = None
        self._api_key: str | None = None

    @property
    def system_key(self) -> str:
        """Unique system identifier."""
        return self._config.system_key

    @property
    def system_type(self) -> str:
        """System type discriminator."""
        return "sms"

    async def initialize(self) -> None:
        """Initialize adapter resources."""
        # Resolve API key from secret_ref (used when auth_mode is 'static')
        self._api_key = self._config.resolve_secret()

        # Create HTTP client — auth headers are set per-request so that
        # user_token mode can forward the current user's token.
        base_url = self._config.base_url.rstrip("/")
        if self._config.base_path:
            base_url = f"{base_url}{self._config.base_path}"

        self._http = httpx.AsyncClient(
            base_url=base_url,
            timeout=self._config.timeout_seconds,
        )

        logger.info("SmsAdapter initialized: %s (base_url=%s, auth_mode=%s)", self._config.system_key, base_url, self._config.auth_mode)

    async def shutdown(self) -> None:
        """Shutdown adapter resources."""
        if self._http:
            await self._http.aclose()
            self._http = None
        logger.info("SmsAdapter shutdown: %s", self._config.system_key)

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
        if self._http is None:
            raise IntegrationError(
                message=f"SmsAdapter {self._config.system_key} not initialized",
                system_key=self._config.system_key,
                capability_key=capability_key,
            )

        handlers = {
            "health.assessment": self._handle_health_assessment,
            "health.anomaly_statistics": self._handle_anomaly_statistics,
            "health.risk_ranking": self._handle_risk_ranking,
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
        except httpx.TimeoutException as e:
            raise IntegrationTimeoutError(
                message=f"Timeout calling {capability_key}: {e}",
                system_key=self._config.system_key,
                capability_key=capability_key,
            ) from e
        except httpx.HTTPStatusError as e:
            error_msg = f"HTTP {e.response.status_code}"
            if e.response.status_code == 401:
                raise IntegrationAuthError(
                    message=f"Authentication failed: {error_msg}",
                    system_key=self._config.system_key,
                    capability_key=capability_key,
                ) from e
            raise IntegrationError(
                message=f"HTTP error calling {capability_key}: {error_msg}",
                system_key=self._config.system_key,
                capability_key=capability_key,
            ) from e
        except Exception as e:
            logger.error(
                "SmsAdapter %s capability %s failed: %s",
                self._config.system_key,
                capability_key,
                e,
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
        if self._http is None:
            return HealthStatus(
                healthy=False,
                message="Adapter not initialized",
            )

        start_time = time.time()
        try:
            response = await self._http.get(
                "/health",
                timeout=5.0,
                headers=self._build_headers(),
            )
            latency_ms = (time.time() - start_time) * 1000

            healthy = response.status_code < 400
            return HealthStatus(
                healthy=healthy,
                latency_ms=latency_ms,
                message=f"HTTP {response.status_code}",
                details={"status_code": response.status_code},
            )
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            return HealthStatus(
                healthy=False,
                latency_ms=latency_ms,
                message=f"Health check failed: {e}",
            )

    def _build_headers(self, auth_context: AuthContext | None = None) -> dict[str, str]:
        """Build HTTP headers with authentication.

        When ``auth_mode`` is ``"user_token"`` and a user token is present
        in ``auth_context``, the token is forwarded as a Bearer header.
        Otherwise the static API key (resolved from ``secret_ref``) is used.
        """
        headers: dict[str, str] = {
            "Accept": "application/json",
        }
        if (
            self._config.auth_mode == "user_token"
            and auth_context is not None
            and auth_context.token
        ):
            headers["Authorization"] = f"Bearer {auth_context.token}"
        elif self._api_key:
            headers["X-API-Key"] = self._api_key
        return headers

    async def _handle_health_assessment(
        self,
        query: Any,
        auth_context: AuthContext,
    ) -> Any:
        """Handle health.assessment capability."""
        if self._http is None:
            raise IntegrationError(
                message="HTTP client not initialized",
                system_key=self._config.system_key,
            )

        asset_id = getattr(query, "asset_id", "")
        if not asset_id:
            raise IntegrationError(
                message="asset_id is required for health.assessment",
                system_key=self._config.system_key,
                capability_key="health.assessment",
            )

        params: dict[str, Any] = {"equipmentId": asset_id}
        if hasattr(query, "assessed_at") and query.assessed_at:
            params["assessedAt"] = query.assessed_at.isoformat()
        if hasattr(query, "include_risk_items"):
            params["includeRiskItems"] = query.include_risk_items
        if hasattr(query, "min_confidence"):
            params["minConfidence"] = query.min_confidence
        if hasattr(query, "extra_params"):
            params.update(query.extra_params)

        response = await self._http.get(
            "/assessment/health",
            params=params,
            headers=self._build_headers(auth_context),
        )
        response.raise_for_status()

        raw_data = response.json()
        if not isinstance(raw_data, dict):
            raise IntegrationDataShapeError(
                message=f"Expected dict, got {type(raw_data).__name__}",
                system_key=self._config.system_key,
                capability_key="health.assessment",
            )

        # Unwrap standard response envelope if present
        data = raw_data.get("data", raw_data)

        return transform_health_assessment(data, self._config.system_key)

    async def _handle_anomaly_statistics(
        self,
        query: Any,
        auth_context: AuthContext,
    ) -> Any:
        """Handle health.anomaly_statistics capability."""
        if self._http is None:
            raise IntegrationError(
                message="HTTP client not initialized",
                system_key=self._config.system_key,
            )

        asset_id = getattr(query, "asset_id", "")
        if not asset_id:
            raise IntegrationError(
                message="asset_id is required for health.anomaly_statistics",
                system_key=self._config.system_key,
                capability_key="health.anomaly_statistics",
            )

        params: dict[str, Any] = {"equipmentId": asset_id}
        if hasattr(query, "start_time") and query.start_time:
            params["startTime"] = query.start_time.isoformat()
        if hasattr(query, "end_time") and query.end_time:
            params["endTime"] = query.end_time.isoformat()
        if hasattr(query, "group_by"):
            params["groupBy"] = ",".join(query.group_by)
        if hasattr(query, "extra_params"):
            params.update(query.extra_params)

        response = await self._http.get(
            "/assessment/anomaly-stats",
            params=params,
            headers=self._build_headers(auth_context),
        )
        response.raise_for_status()

        raw_data = response.json()
        data = raw_data.get("data", raw_data) if isinstance(raw_data, dict) else raw_data

        return transform_anomaly_stats(data, self._config.system_key)

    async def _handle_risk_ranking(
        self,
        query: Any,
        auth_context: AuthContext,
    ) -> Any:
        """Handle health.risk_ranking capability."""
        if self._http is None:
            raise IntegrationError(
                message="HTTP client not initialized",
                system_key=self._config.system_key,
            )

        tenant_id = getattr(query, "tenant_id", "") or auth_context.tenant_id
        params: dict[str, Any] = {"tenantId": tenant_id}
        if hasattr(query, "scope") and query.scope:
            params["scope"] = query.scope
        if hasattr(query, "limit"):
            params["limit"] = query.limit
        if hasattr(query, "min_risk_score"):
            params["minRiskScore"] = query.min_risk_score
        if hasattr(query, "generated_after") and query.generated_after:
            params["generatedAfter"] = query.generated_after.isoformat()
        if hasattr(query, "extra_filters"):
            params.update(query.extra_filters)

        response = await self._http.get(
            "/assessment/risk-ranking",
            params=params,
            headers=self._build_headers(auth_context),
        )
        response.raise_for_status()

        raw_data = response.json()
        data = raw_data.get("data", raw_data) if isinstance(raw_data, dict) else raw_data

        return transform_risk_ranking(data, self._config.system_key, tenant_id)
