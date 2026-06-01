"""Python client for the external Workbench service (服务平台).

Provides typed access to the workbench statistics API,
including pending todo counts for anomaly/startup/shutdown work orders.
"""

import logging
from typing import Any

from deerflow.rpc.rpc_client import RpcClient, get_rpc_client

logger = logging.getLogger(__name__)

SERVICE_NAME = "workbench-service"
STATS_PATH = "/api/workbench/getStats"


class WorkbenchServiceClient:
    """Python client for the external Workbench service.

    Usage:
        client = WorkbenchServiceClient()
        stats = await client.get_stats(start_time_ms=..., end_time_ms=..., token="...")
    """

    def __init__(self, rpc_client: RpcClient | None = None):
        self._rpc = rpc_client or get_rpc_client()
        if self._rpc is None:
            raise RuntimeError("RPC client is not configured")

    async def get_stats(
        self,
        start_time_ms: int,
        end_time_ms: int,
        *,
        token: str | None = None,
    ) -> dict[str, Any]:
        """Fetch workbench todo statistics.

        Args:
            start_time_ms: Start time in epoch milliseconds (current time - 1 day).
            end_time_ms: End time in epoch milliseconds (current time).
            token: Bearer token for user authentication (forwarded to external service).

        Returns:
            dict: The full ``data`` object from the workbench API response,
            containing fields like ``pendingCount``, ``startPendingCount``,
            ``stopPendingCount``, etc.

        Raises:
            RpcError: On 4xx/5xx responses.
            RpcConnectionError: On network errors.
            RpcTimeoutError: On timeout.
        """
        extra_headers: dict[str, str] | None = None
        if token:
            extra_headers = {"Authorization": f"Bearer {token}"}

        params = {
            "startTime": str(start_time_ms),
            "endTime": str(end_time_ms),
        }

        result = await self._rpc.call_raw(
            SERVICE_NAME,
            STATS_PATH,
            "GET",
            params,
            extra_headers=extra_headers,
        )
        return self._unwrap_result(result)

    @staticmethod
    def _unwrap_result(result: Any) -> Any:
        """Extract data from the standard response wrapper {code, msg, data, success}."""
        if isinstance(result, dict):
            return result.get("data", result)
        return result
