"""WorkbenchAdapter — external 服务平台 integration adapter.

Implements the IntegrationAdapter Protocol for fetching workbench
todo statistics (anomaly / startup / shutdown pending counts).

Capability keys:
- todo_stats.get: Fetch pending todo counts
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from deerflow.integrations.adapters.base import AuthContext, HealthStatus
from deerflow.integrations.config import IntegrationSystemConfig
from deerflow.integrations.errors import (
    IntegrationAuthError,
    IntegrationError,
    IntegrationTimeoutError,
    IntegrationUnavailableError,
)

logger = logging.getLogger(__name__)

_WORKBENCH_CAPABILITIES = ("todo_stats.get",)

_STATS_PATH = "/api/workbench/getStats"
_ONE_DAY_MS = 24 * 60 * 60 * 1000


class WorkbenchAdapter:
    """Adapter for the external 服务平台 (workbench) system."""

    def __init__(self, config: IntegrationSystemConfig) -> None:
        self._config = config
        self._http: httpx.AsyncClient | None = None
        self._base_url: str = config.base_url.rstrip("/")

    @property
    def system_key(self) -> str:
        return self._config.system_key

    @property
    def system_type(self) -> str:
        return "workbench"

    @property
    def capabilities(self) -> tuple[str, ...]:
        return _WORKBENCH_CAPABILITIES

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        self._http = httpx.AsyncClient(
            timeout=self._config.timeout_seconds,
        )
        logger.info(
            "WorkbenchAdapter initialized: %s (base_url=%s)",
            self._config.system_key,
            self._base_url,
        )

    async def shutdown(self) -> None:
        if self._http:
            await self._http.aclose()
            self._http = None
        logger.info("WorkbenchAdapter shutdown: %s", self._config.system_key)

    # ------------------------------------------------------------------
    # Capability dispatch
    # ------------------------------------------------------------------

    async def call(
        self,
        capability_key: str,
        query: Any,
        auth_context: AuthContext,
    ) -> Any:
        if not self._http:
            raise IntegrationUnavailableError(system_key=self._config.system_key)

        if capability_key not in _WORKBENCH_CAPABILITIES:
            raise IntegrationError(
                f"Unsupported capability: {capability_key}",
            )

        handlers = {
            "todo_stats.get": self._handle_todo_stats,
        }

        handler = handlers[capability_key]
        started = time.monotonic()
        try:
            result = await handler(auth_context)
            elapsed = time.monotonic() - started
            logger.info(
                "WorkbenchAdapter %s.%s completed in %.2fs",
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
            if auth_context.token:
                error_msg = error_msg.replace(auth_context.token, "***REDACTED***")
            raise IntegrationError(
                f"Workbench call failed: {error_msg}",
            ) from exc

    async def health_check(self) -> HealthStatus:
        if not self._http:
            return HealthStatus(
                healthy=False,
                message="HTTP client not initialized",
            )

        started = time.monotonic()
        try:
            now_ms = int(time.time() * 1000)
            params = {
                "startTime": str(now_ms - _ONE_DAY_MS),
                "endTime": str(now_ms),
            }
            resp = await self._http.get(
                f"{self._base_url}{_STATS_PATH}",
                params=params,
                timeout=10.0,
            )
            latency_ms = (time.monotonic() - started) * 1000
            return HealthStatus(
                healthy=resp.status_code < 500,
                latency_ms=latency_ms,
                message=f"HTTP {resp.status_code}",
                checked_at=None,
            )
        except Exception as exc:
            latency_ms = (time.monotonic() - started) * 1000
            return HealthStatus(
                healthy=False,
                latency_ms=latency_ms,
                message=str(exc),
            )

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    async def _handle_todo_stats(self, auth_context: AuthContext) -> dict[str, int]:
        """Fetch workbench todo statistics.

        Returns:
            dict with keys: anomalyPending, startupPending, shutdownPending
        """
        headers = self._build_headers(auth_context)

        now_ms = int(time.time() * 1000)
        params = {
            "startTime": str(now_ms - _ONE_DAY_MS),
            "endTime": str(now_ms),
        }

        resp = await self._http.get(  # type: ignore[union-attr]
            f"{self._base_url}{_STATS_PATH}",
            params=params,
            headers=headers,
        )

        if resp.status_code == 401 or resp.status_code == 403:
            raise IntegrationAuthError(
                system_key=self._config.system_key,
                capability="todo_stats.get",
            )

        resp.raise_for_status()

        body = resp.json()
        data = body.get("data", body) if isinstance(body, dict) else {}

        return {
            "anomalyPending": data.get("pendingCount", 0),
            "startupPending": data.get("startPendingCount", 0),
            "shutdownPending": data.get("stopPendingCount", 0),
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_headers(self, auth_context: AuthContext) -> dict[str, str]:
        """Build HTTP headers, forwarding the user's Bearer token."""
        headers: dict[str, str] = {"Accept": "application/json"}

        if self._config.auth_mode == "user_token" and auth_context.token:
            headers["Authorization"] = f"Bearer {auth_context.token}"

        return headers

    def _handle_http_error(
        self,
        exc: httpx.HTTPStatusError,
        auth_context: AuthContext,
    ) -> None:
        status = exc.response.status_code
        if status in (401, 403):
            raise IntegrationAuthError(
                system_key=self._config.system_key,
            )
        error_msg = str(exc)
        if auth_context.token:
            error_msg = error_msg.replace(auth_context.token, "***REDACTED***")
        raise IntegrationError(
            f"Workbench HTTP {status}: {error_msg}",
        )
