"""Workbench tools for agent integration.

Each method returns a formatted Markdown string suitable for agent consumption.
"""

from __future__ import annotations

import logging

from deerflow.integrations.adapters.base import AuthContext
from deerflow.integrations.errors import IntegrationError
from deerflow.integrations.services.workbench_service import WorkbenchService

logger = logging.getLogger(__name__)


class WorkbenchTools:
    """Tool wrappers for 服务平台 (workbench) operations."""

    def __init__(self, service: WorkbenchService) -> None:
        self._service = service

    async def get_todo_stats(
        self,
        tenant_id: str,
        user_id: str,
        token: str | None = None,
    ) -> str:
        """查询待办统计（异常/启机/停机待处理数量）."""
        try:
            auth_context = AuthContext(
                tenant_id=tenant_id,
                user_id=user_id,
                token=token,
            )
            result = await self._service.get_todo_stats(auth_context)
            data: dict = result.data

            return (
                f"## 待办统计\n\n"
                f"- 异常待处理：**{data.get('anomalyPending', 0)}**\n"
                f"- 启机待处理：**{data.get('startupPending', 0)}**\n"
                f"- 停机待处理：**{data.get('shutdownPending', 0)}**"
            )

        except IntegrationError as e:
            logger.error("Failed to get todo stats: %s", e)
            return f"查询待办统计失败: {e}"
        except Exception as e:
            logger.error("Unexpected error: %s", e)
            return f"查询待办统计时发生错误: {e}"
