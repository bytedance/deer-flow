"""XsyAdapter — Xiaoshouyi (销售易) CRM integration adapter.

Implements the IntegrationAdapter Protocol for querying Xiaoshouyi CRM data
via OAuth2 password grant and SQL-like query API.

Capability keys:
- outbound.query: Query product shipment records
- outbound.statistics: Aggregate shipment statistics
- service_event.query: Query service event records
- service_event.statistics: Aggregate event statistics
- service_event.anomaly: Detect event anomalies
- xsy.report: Cross-table report data
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any

import httpx

from deerflow.integrations.adapters.base import AuthContext, HealthStatus
from deerflow.integrations.adapters.xsy.sql_builder import (
    build_outbound_query,
    build_service_event_query,
)
from deerflow.integrations.adapters.xsy.token_manager import XsyTokenManager
from deerflow.integrations.adapters.xsy.transform import (
    compute_outbound_statistics,
    compute_service_event_statistics,
    detect_service_event_anomalies,
    transform_outbound_records,
    transform_service_event_records,
)
from deerflow.integrations.config import IntegrationSystemConfig
from deerflow.integrations.errors import (
    IntegrationAuthError,
    IntegrationError,
    IntegrationTimeoutError,
    IntegrationUnavailableError,
)
from deerflow.integrations.models.provenance import Provenance
from deerflow.integrations.models.queries import OutboundDetailQuery, ServiceEventQuery

logger = logging.getLogger(__name__)

_XSY_CAPABILITIES = (
    "outbound.query",
    "outbound.statistics",
    "service_event.query",
    "service_event.statistics",
    "service_event.anomaly",
    "xsy.report",
)


class XsyAdapter:
    """Adapter for Xiaoshouyi (销售易) CRM system."""

    def __init__(self, config: IntegrationSystemConfig) -> None:
        self._config = config
        self._token_manager: XsyTokenManager | None = None
        self._http: httpx.AsyncClient | None = None
        self._base_url: str = config.base_url.rstrip("/")

    @property
    def system_key(self) -> str:
        return self._config.system_key

    @property
    def system_type(self) -> str:
        return "xsy"

    @property
    def capabilities(self) -> tuple[str, ...]:
        return _XSY_CAPABILITIES

    async def initialize(self) -> None:
        """Initialize token manager and HTTP client."""
        # Extract auth URL from extra_config or use default
        auth_url = self._config.extra_config.get(
            "auth_url",
            "https://login.xiaoshouyi.com/auc/oauth2/token",
        )

        self._token_manager = XsyTokenManager(
            auth_url=auth_url,
            extra_config=self._config.extra_config,
            timeout_seconds=self._config.timeout_seconds,
        )

        self._http = httpx.AsyncClient(
            timeout=self._config.timeout_seconds,
        )

        logger.info(
            "XsyAdapter initialized: %s (base_url=%s)",
            self._config.system_key,
            self._base_url,
        )

    async def shutdown(self) -> None:
        """Shutdown HTTP client."""
        if self._http:
            await self._http.aclose()
            self._http = None
        logger.info("XsyAdapter shutdown: %s", self._config.system_key)

    async def call(
        self,
        capability_key: str,
        query: Any,
        auth_context: AuthContext,
    ) -> Any:
        """Execute a capability call."""
        if not self._http or not self._token_manager:
            raise IntegrationUnavailableError(system_key=self._config.system_key)

        if capability_key not in _XSY_CAPABILITIES:
            raise IntegrationError(f"Unsupported capability: {capability_key}")

        handlers = {
            "outbound.query": self._handle_outbound_query,
            "outbound.statistics": self._handle_outbound_statistics,
            "service_event.query": self._handle_service_event_query,
            "service_event.statistics": self._handle_service_event_statistics,
            "service_event.anomaly": self._handle_service_event_anomaly,
            "xsy.report": self._handle_xsy_report,
        }

        handler = handlers.get(capability_key)
        if not handler:
            raise IntegrationError(f"No handler for capability: {capability_key}")

        started = time.monotonic()
        try:
            result = await handler(query, auth_context)
            elapsed = time.monotonic() - started
            logger.info(
                "XsyAdapter %s.%s completed in %.2fs",
                self._config.system_key,
                capability_key,
                elapsed,
            )
            return result
        except (IntegrationError, IntegrationAuthError, IntegrationTimeoutError):
            raise
        except httpx.TimeoutException as exc:
            raise IntegrationTimeoutError(
                system_key=self._config.system_key,
                capability=capability_key,
                timeout_seconds=self._config.timeout_seconds,
            ) from exc
        except httpx.HTTPStatusError as exc:
            self._handle_http_error(exc, auth_context)
            raise  # unreachable
        except Exception as exc:
            error_msg = str(exc)
            # Redact token from error messages
            if auth_context.token:
                error_msg = error_msg.replace(auth_context.token, "***REDACTED***")
            raise IntegrationError(
                f"XSY call failed: {error_msg}",
            ) from exc

    async def health_check(self) -> HealthStatus:
        """Check adapter health by attempting token acquisition."""
        if not self._token_manager:
            return HealthStatus(healthy=False, message="Not initialized")

        try:
            await self._token_manager.get_token()
            return HealthStatus(
                healthy=True,
                message="OK",
                checked_at=datetime.now(),
            )
        except Exception as exc:
            return HealthStatus(
                healthy=False,
                message=str(exc)[:200],
                checked_at=datetime.now(),
            )

    # -------------------------------------------------------------------------
    # Handler methods
    # -------------------------------------------------------------------------

    async def _handle_outbound_query(
        self,
        query: OutboundDetailQuery,
        auth_context: AuthContext,
    ) -> tuple:
        """Handle outbound.query capability."""
        records = await self._fetch_all_pages(
            query_builder=build_outbound_query,
            query=query,
            auth_context=auth_context,
        )

        provenance = Provenance(
            source_system_key=self._config.system_key,
            source_system_type="xsy",
            capability_key="outbound.query",
            fetched_at=datetime.now(),
        )

        return transform_outbound_records(records, provenance)

    async def _handle_outbound_statistics(
        self,
        query: OutboundDetailQuery,
        auth_context: AuthContext,
    ) -> Any:
        """Handle outbound.statistics capability."""
        records = await self._handle_outbound_query(query, auth_context)

        provenance = Provenance(
            source_system_key=self._config.system_key,
            source_system_type="xsy",
            capability_key="outbound.statistics",
            fetched_at=datetime.now(),
        )

        return compute_outbound_statistics(records, query.group_by, provenance)

    async def _handle_service_event_query(
        self,
        query: ServiceEventQuery,
        auth_context: AuthContext,
    ) -> tuple:
        """Handle service_event.query capability."""
        records = await self._fetch_all_pages(
            query_builder=build_service_event_query,
            query=query,
            auth_context=auth_context,
        )

        provenance = Provenance(
            source_system_key=self._config.system_key,
            source_system_type="xsy",
            capability_key="service_event.query",
            fetched_at=datetime.now(),
        )

        return transform_service_event_records(records, provenance)

    async def _handle_service_event_statistics(
        self,
        query: ServiceEventQuery,
        auth_context: AuthContext,
    ) -> Any:
        """Handle service_event.statistics capability."""
        records = await self._handle_service_event_query(query, auth_context)

        provenance = Provenance(
            source_system_key=self._config.system_key,
            source_system_type="xsy",
            capability_key="service_event.statistics",
            fetched_at=datetime.now(),
        )

        return compute_service_event_statistics(records, query.group_by, provenance)

    async def _handle_service_event_anomaly(
        self,
        query: ServiceEventQuery,
        auth_context: AuthContext,
    ) -> tuple:
        """Handle service_event.anomaly capability."""
        records = await self._handle_service_event_query(query, auth_context)

        provenance = Provenance(
            source_system_key=self._config.system_key,
            source_system_type="xsy",
            capability_key="service_event.anomaly",
            fetched_at=datetime.now(),
        )

        threshold = query.extra_filters.get("threshold", 2.0)
        return detect_service_event_anomalies(records, threshold, provenance)

    async def _handle_xsy_report(
        self,
        query: Any,
        auth_context: AuthContext,
    ) -> dict:
        """Handle xsy.report capability — fetch both tables for cross-table report."""
        # Fetch outbound data
        outbound_query = OutboundDetailQuery(
            tenant_id=query.tenant_id,
            start_time=getattr(query, "start_time", None),
            end_time=getattr(query, "end_time", None),
            limit=500,
        )
        outbound_records = await self._handle_outbound_query(outbound_query, auth_context)
        outbound_stats = compute_outbound_statistics(outbound_records, group_by="day")

        # Fetch service events
        event_query = ServiceEventQuery(
            tenant_id=query.tenant_id,
            start_time=getattr(query, "start_time", None),
            end_time=getattr(query, "end_time", None),
            limit=500,
        )
        event_records = await self._handle_service_event_query(event_query, auth_context)
        event_stats = compute_service_event_statistics(event_records, group_by="day")
        anomalies = detect_service_event_anomalies(event_records)

        return {
            "outbound_records": outbound_records,
            "outbound_statistics": outbound_stats,
            "service_event_records": event_records,
            "service_event_statistics": event_stats,
            "anomalies": anomalies,
        }

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    async def _fetch_all_pages(
        self,
        query_builder: Any,
        query: Any,
        auth_context: AuthContext,
    ) -> list[dict[str, Any]]:
        """Fetch all pages using cursor-based pagination.

        Xiaoshouyi returns max 100 records per page. We use id-based cursor
        pagination: WHERE ... AND id > 'last_id' ORDER BY id LIMIT 100.
        """
        assert self._http is not None
        assert self._token_manager is not None

        all_records: list[dict[str, Any]] = []
        last_id: str | None = None
        max_records = query.limit

        while len(all_records) < max_records:
            # Build SQL with cursor
            sql = query_builder(query, last_id=last_id)

            # Execute query
            page_records = await self._execute_query(sql, auth_context)

            if not page_records:
                break

            all_records.extend(page_records)

            # Check if we got fewer than 100 (last page)
            if len(page_records) < 100:
                break

            # Update cursor to last record's id
            last_record = page_records[-1]
            last_id = str(last_record.get("id", ""))
            if not last_id:
                break

        return all_records[:max_records]

    async def _execute_query(
        self,
        sql: str,
        auth_context: AuthContext,
    ) -> list[dict[str, Any]]:
        """Execute a single SQL query against Xiaoshouyi API."""
        assert self._http is not None
        assert self._token_manager is not None

        # Get token
        token = await self._token_manager.get_token()

        # Build headers
        headers = self._build_headers(token, auth_context)

        # Execute query
        api_url = f"{self._base_url}/rest/data/v2/query"
        response = await self._http.get(
            api_url,
            params={"q": sql},
            headers=headers,
        )
        response.raise_for_status()

        # Parse response
        data = response.json()
        if data.get("code") != 200:
            raise IntegrationError(
                f"Xiaoshouyi query error: {data.get('msg', 'Unknown error')}",
            )

        result = data.get("result", {})
        return result.get("records", [])

    def _build_headers(
        self,
        token: str,
        auth_context: AuthContext,
    ) -> dict[str, str]:
        """Build request headers with auth."""
        headers: dict[str, str] = {
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
        }

        # Future: user_token passthrough
        if self._config.auth_mode == "user_token" and auth_context.token:
            headers["Authorization"] = f"Bearer {auth_context.token}"

        return headers

    def _handle_http_error(
        self,
        exc: httpx.HTTPStatusError,
        auth_context: AuthContext,
    ) -> None:
        """Handle HTTP errors with appropriate exception types."""
        status = exc.response.status_code

        if status in (401, 403):
            raise IntegrationAuthError(
                system_key=self._config.system_key,
                message=f"Xiaoshouyi auth failed (HTTP {status})",
            ) from exc

        error_text = exc.response.text[:200]
        if auth_context.token:
            error_text = error_text.replace(auth_context.token, "***REDACTED***")

        raise IntegrationError(
            f"Xiaoshouyi HTTP error: {status} {error_text}",
        ) from exc
