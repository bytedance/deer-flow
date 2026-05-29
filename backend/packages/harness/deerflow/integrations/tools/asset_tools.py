"""Asset tools for agent integration.

Provides callable tools for asset-related operations that agents can use
to query external systems for asset information.
"""

from __future__ import annotations

import logging
from typing import Any

from deerflow.integrations.adapters.base import AuthContext
from deerflow.integrations.errors import IntegrationError
from deerflow.integrations.models.queries import (
    AssetCatalogQuery,
    AssetContextQuery,
    AssetOverviewQuery,
)
from deerflow.integrations.services.asset_service import AssetService

logger = logging.getLogger(__name__)


class AssetTools:
    """Tool wrappers for asset operations.

    Each method returns a formatted string suitable for agent consumption,
    including structured data and human-readable summaries.
    """

    def __init__(self, service: AssetService) -> None:
        self._service = service

    async def get_asset_catalog(
        self,
        tenant_id: str,
        user_id: str,
        asset_types: tuple[str, ...] = (),
        status: str | None = None,
        search_text: str = "",
        limit: int = 100,
        offset: int = 0,
        token: str | None = None,
    ) -> str:
        """获取资产目录列表。

        Args:
            tenant_id: 租户ID
            user_id: 用户ID
            asset_types: 资产类型过滤元组（可选）
            status: 状态过滤（可选）
            search_text: 搜索文本（可选）
            limit: 返回条数限制（默认100）
            offset: 偏移量（默认0）
            token: 用户访问令牌（用于 auth_mode=user_token 的外部系统透传）

        Returns:
            格式化的资产目录字符串
        """
        try:
            query = AssetCatalogQuery(
                tenant_id=tenant_id,
                asset_types=asset_types,
                status=status,
                search_text=search_text,
                limit=limit,
                offset=offset,
            )
            auth_context = AuthContext(tenant_id=tenant_id, user_id=user_id, token=token)

            result = await self._service.get_catalog(query, auth_context)

            assets = result.data
            if not assets:
                return "未找到匹配的资产记录。"

            lines = [f"找到 {len(assets)} 个资产：\n"]
            for asset in assets:
                status_emoji = "✅" if asset.status == "active" else "⚠️"
                lines.append(
                    f"- {status_emoji} **{asset.asset_name}** (ID: {asset.asset_id})\n"
                    f"  类型: {asset.asset_type} | 位置: {asset.location or '未指定'}\n"
                    f"  状态: {asset.status}"
                )

            return "\n".join(lines)

        except IntegrationError as e:
            logger.error("Failed to get asset catalog: %s", e)
            return f"获取资产目录失败: {e}"
        except Exception as e:
            logger.error("Unexpected error getting asset catalog: %s", e)
            return f"获取资产目录时发生错误: {e}"

    async def get_asset_context(
        self,
        tenant_id: str,
        user_id: str,
        asset_id: str,
        include_children: bool = True,
        include_measurement_points: bool = True,
        token: str | None = None,
    ) -> str:
        """获取资产上下文信息。

        Args:
            tenant_id: 租户ID
            user_id: 用户ID
            asset_id: 资产ID
            include_children: 是否包含子资产
            include_measurement_points: 是否包含测量点
            token: 用户访问令牌（用于 auth_mode=user_token 的外部系统透传）

        Returns:
            格式化的资产上下文字符串
        """
        try:
            query = AssetContextQuery(
                tenant_id=tenant_id,
                asset_id=asset_id,
                include_children=include_children,
                include_measurement_points=include_measurement_points,
            )
            auth_context = AuthContext(tenant_id=tenant_id, user_id=user_id, token=token)

            result = await self._service.get_context(query, auth_context)

            context = result.data
            lines = [
                f"## 资产上下文: {context.asset.asset_name}\n",
                f"**资产ID**: {context.asset.asset_id}",
                f"**类型**: {context.asset.asset_type}",
                f"**状态**: {context.asset.status}",
                f"**位置**: {context.asset.location or '未指定'}\n",
            ]

            if context.children and include_children:
                lines.append(f"### 子资产 ({len(context.children)} 个)")
                for child in context.children:
                    lines.append(f"- {child.asset_name} (ID: {child.asset_id})")
                lines.append("")

            if context.measurement_points and include_measurement_points:
                lines.append(f"### 测量点 ({len(context.measurement_points)} 个)")
                for mp in context.measurement_points:
                    lines.append(f"- **{mp.point_name}** ({mp.point_type})")
                    lines.append(f"  单位: {mp.unit} | 方向: {mp.direction}")
                lines.append("")

            return "\n".join(lines)

        except IntegrationError as e:
            logger.error("Failed to get asset context for %s: %s", asset_id, e)
            return f"获取资产上下文失败: {e}"
        except Exception as e:
            logger.error("Unexpected error getting asset context: %s", e)
            return f"获取资产上下文时发生错误: {e}"

    async def get_asset_overview(
        self,
        tenant_id: str,
        user_id: str,
        asset_id: str,
        include_health_assessment: bool = True,
        include_recent_alarms: bool = True,
        token: str | None = None,
    ) -> str:
        """获取资产综合概览。

        Args:
            tenant_id: 租户ID
            user_id: 用户ID
            asset_id: 资产ID
            include_health_assessment: 是否包含健康评估
            include_recent_alarms: 是否包含最近报警
            token: 用户访问令牌（用于 auth_mode=user_token 的外部系统透传）

        Returns:
            格式化的资产概览字符串
        """
        try:
            query = AssetOverviewQuery(
                tenant_id=tenant_id,
                asset_id=asset_id,
                include_health_assessment=include_health_assessment,
                include_recent_alarms=include_recent_alarms,
            )
            auth_context = AuthContext(tenant_id=tenant_id, user_id=user_id, token=token)

            result = await self._service.get_overview(query, auth_context)

            overview = result.data
            lines = [
                f"## 资产概览: {overview.asset.asset_name}\n",
                f"**资产ID**: {overview.asset.asset_id}",
                f"**类型**: {overview.asset.asset_type}",
                f"**状态**: {overview.asset.status}\n",
            ]

            if overview.health_assessment and include_health_assessment:
                health = overview.health_assessment
                lines.append("### 健康评估")
                lines.append(f"**总体评分**: {health.overall_score}/100")
                lines.append(f"**状态**: {health.overall_status}")

                if health.dimensions:
                    lines.append("**维度评分**:")
                    for dim_name, dim_score in health.dimensions.items():
                        lines.append(f"- {dim_name}: {dim_score}/100")
                lines.append("")

            if overview.recent_alarms and include_recent_alarms:
                lines.append(f"### 最近报警 ({len(overview.recent_alarms)} 条)")
                for alarm in overview.recent_alarms[:5]:  # Show max 5
                    severity_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(
                        alarm.severity, "⚪"
                    )
                    lines.append(
                        f"- {severity_icon} **{alarm.message}**\n"
                        f"  时间: {alarm.triggered_at} | 严重程度: {alarm.severity}"
                    )
                if len(overview.recent_alarms) > 5:
                    lines.append(f"- ... 还有 {len(overview.recent_alarms) - 5} 条报警")
                lines.append("")

            if overview.partial_failures:
                lines.append("⚠️ 部分数据获取失败:")
                for failure in overview.partial_failures:
                    lines.append(f"- {failure.system_key}: {failure.error_message}")

            return "\n".join(lines)

        except IntegrationError as e:
            logger.error("Failed to get asset overview for %s: %s", asset_id, e)
            return f"获取资产概览失败: {e}"
        except Exception as e:
            logger.error("Unexpected error getting asset overview: %s", e)
            return f"获取资产概览时发生错误: {e}"
