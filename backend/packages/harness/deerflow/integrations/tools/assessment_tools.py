"""Assessment tools for agent integration.

Provides callable tools for health assessment operations that agents can use
to query external systems for health scores, anomaly statistics, and risk rankings.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from deerflow.integrations.adapters.base import AuthContext
from deerflow.integrations.errors import IntegrationError
from deerflow.integrations.models.queries import (
    AnomalyStatsQuery,
    HealthAssessmentQuery,
    RiskRankingQuery,
)
from deerflow.integrations.services.assessment_service import AssessmentService

logger = logging.getLogger(__name__)


class AssessmentTools:
    """Tool wrappers for health assessment operations.

    Each method returns a formatted string suitable for agent consumption,
    including structured data and human-readable summaries.
    """

    def __init__(self, service: AssessmentService) -> None:
        self._service = service

    async def get_health_assessment(
        self,
        tenant_id: str,
        user_id: str,
        asset_id: str,
        assessed_at: datetime | None = None,
        token: str | None = None,
    ) -> str:
        """获取健康评估。

        Args:
            tenant_id: 租户ID
            user_id: 用户ID
            asset_id: 资产ID
            assessed_at: 评估时间点（默认最新）
            token: 用户访问令牌（用于 auth_mode=user_token 的外部系统透传）

        Returns:
            格式化的健康评估字符串
        """
        try:
            query = HealthAssessmentQuery(
                tenant_id=tenant_id,
                asset_id=asset_id,
                assessed_at=assessed_at,
            )
            auth_context = AuthContext(tenant_id=tenant_id, user_id=user_id, token=token)

            result = await self._service.get_health_assessment(query, auth_context)

            assessment = result.data
            lines = [
                f"## 健康评估: {asset_id}\n",
                f"**总体评分**: {assessment.overall_score}/100",
                f"**状态**: {assessment.overall_status}",
            ]

            if assessment.assessed_at:
                lines.append(f"**评估时间**: {assessment.assessed_at.strftime('%Y-%m-%d %H:%M:%S')}\n")

            if assessment.dimensions:
                lines.append("### 维度评分")
                for dim_name, dim_score in assessment.dimensions.items():
                    status_emoji = "✅" if dim_score >= 80 else "⚠️" if dim_score >= 60 else "❌"
                    lines.append(f"- {status_emoji} {dim_name}: {dim_score}/100")
                lines.append("")

            if assessment.risk_items:
                lines.append("### 风险项")
                for idx, item in enumerate(assessment.risk_items, 1):
                    severity_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(
                        item.severity, "⚪"
                    )
                    lines.append(f"{idx}. {severity_icon} **{item.risk_type}**")
                    lines.append(f"   {item.description}")
                lines.append("")

            return "\n".join(lines)

        except IntegrationError as e:
            logger.error("Failed to get health assessment: %s", e)
            return f"获取健康评估失败: {e}"
        except Exception as e:
            logger.error("Unexpected error getting health assessment: %s", e)
            return f"获取健康评估时发生错误: {e}"

    async def get_anomaly_statistics(
        self,
        tenant_id: str,
        user_id: str,
        asset_id: str,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        token: str | None = None,
    ) -> str:
        """获取异常统计信息。

        Args:
            tenant_id: 租户ID
            user_id: 用户ID
            asset_id: 资产ID
            start_time: 开始时间（默认30天前）
            end_time: 结束时间（默认当前）
            token: 用户访问令牌（用于 auth_mode=user_token 的外部系统透传）

        Returns:
            格式化的异常统计字符串
        """
        try:
            if end_time is None:
                end_time = datetime.now()
            if start_time is None:
                start_time = end_time - timedelta(days=30)

            query = AnomalyStatsQuery(
                tenant_id=tenant_id,
                asset_id=asset_id,
                start_time=start_time,
                end_time=end_time,
            )
            auth_context = AuthContext(tenant_id=tenant_id, user_id=user_id, token=token)

            result = await self._service.get_anomaly_statistics(query, auth_context)

            stats = result.data
            lines = [
                f"## 异常统计: {asset_id}\n",
                f"**时间范围**: {start_time.strftime('%Y-%m-%d')} 至 {end_time.strftime('%Y-%m-%d')}",
                f"**异常总数**: {stats.total_anomalies}\n",
            ]

            if stats.by_severity:
                lines.append("### 按严重程度分类")
                severity_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}
                for severity, count in stats.by_severity.items():
                    emoji = severity_emoji.get(severity, "⚪")
                    lines.append(f"- {emoji} {severity}: {count}")
                lines.append("")

            if stats.by_type:
                lines.append("### 按类型分类")
                for anomaly_type, count in stats.by_type.items():
                    lines.append(f"- {anomaly_type}: {count}")
                lines.append("")

            return "\n".join(lines)

        except IntegrationError as e:
            logger.error("Failed to get anomaly statistics: %s", e)
            return f"获取异常统计失败: {e}"
        except Exception as e:
            logger.error("Unexpected error getting anomaly statistics: %s", e)
            return f"获取异常统计时发生错误: {e}"

    async def get_risk_ranking(
        self,
        tenant_id: str,
        user_id: str,
        scope: str = "",
        limit: int = 50,
        min_risk_score: float = 0.0,
        token: str | None = None,
    ) -> str:
        """获取风险排名。

        Args:
            tenant_id: 租户ID
            user_id: 用户ID
            scope: 评估范围（可选）
            limit: 返回条数限制
            min_risk_score: 最小风险分数过滤
            token: 用户访问令牌（用于 auth_mode=user_token 的外部系统透传）

        Returns:
            格式化的风险排名字符串
        """
        try:
            query = RiskRankingQuery(
                tenant_id=tenant_id,
                scope=scope,
                limit=limit,
                min_risk_score=min_risk_score,
            )
            auth_context = AuthContext(tenant_id=tenant_id, user_id=user_id, token=token)

            result = await self._service.get_risk_ranking(query, auth_context)

            rankings = result.data
            if not rankings:
                return "未找到风险记录。"

            lines = [
                f"## 风险排名 (Top {len(rankings)})\n",
            ]

            for idx, ranking in enumerate(rankings, 1):
                risk_emoji = "🔴" if ranking.risk_score >= 80 else "🟡" if ranking.risk_score >= 60 else "🟢"
                lines.append(
                    f"{idx}. {risk_emoji} **{ranking.asset_name}** (ID: {ranking.asset_id})\n"
                    f"   风险分数: {ranking.risk_score}/100 | 类型: {ranking.asset_type}"
                )

                if ranking.risk_factors:
                    lines.append(f"   主要风险: {', '.join(ranking.risk_factors[:3])}")

                lines.append("")

            return "\n".join(lines)

        except IntegrationError as e:
            logger.error("Failed to get risk ranking: %s", e)
            return f"获取风险排名失败: {e}"
        except Exception as e:
            logger.error("Unexpected error getting risk ranking: %s", e)
            return f"获取风险排名时发生错误: {e}"
