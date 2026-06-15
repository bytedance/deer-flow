"""Assessment tools for agent integration.

Provides callable tools for health assessment operations that agents can use
to query external systems for health scores, anomaly statistics, and risk rankings.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from deerflow.integrations.adapters.base import AuthContext
from deerflow.integrations.errors import IntegrationError
from deerflow.integrations.models.queries import (
    AbnormalDetailQuery,
    AbnormalListQuery,
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

    async def get_abnormal_list(
        self,
        tenant_id: str,
        user_id: str,
        current_page: int = 1,
        page_size: int = 10,
        start_time: int | None = None,
        end_time: int | None = None,
        org_id: int = 0,
        token: str | None = None,
    ) -> str:
        """获取SMS异常列表。

        Args:
            tenant_id: 租户ID
            user_id: 用户ID
            current_page: 当前页码（默认1）
            page_size: 每页条数（默认10）
            start_time: 开始时间（毫秒时间戳，默认30天前）
            end_time: 结束时间（毫秒时间戳，默认当前）
            org_id: 组织ID（默认0）
            token: 用户访问令牌

        Returns:
            格式化的异常列表JSON字符串
        """
        try:
            import json
            import time

            if end_time is None:
                end_time = int(time.time() * 1000)
            if start_time is None:
                start_time = end_time - 30 * 24 * 3600 * 1000

            query = AbnormalListQuery(
                tenant_id=tenant_id,
                current_page=current_page,
                page_size=page_size,
                start_time=start_time,
                end_time=end_time,
                org_id=org_id,
            )
            auth_context = AuthContext(tenant_id=tenant_id, user_id=user_id, token=token)
            result = await self._service.get_abnormal_list(query, auth_context)
            items = result.data

            if not items:
                return json.dumps({"total": 0, "items": []}, ensure_ascii=False)

            return json.dumps({
                "total": len(items),
                "items": [
                    {
                        "abnormal_id": item.abnormal_id,
                        "mac_path": item.mac_path,
                        "mac_name": item.mac_name,
                        "component_name": item.component_name,
                        "mac_id": item.mac_id,
                        "component_id": item.component_id,
                        "latest_health": item.latest_health,
                        "latest_level": item.latest_level,
                        "event_count": item.event_count,
                        "first_event_time": item.first_event_time,
                        "process_status": item.process_status,
                        "run_status": item.run_status,
                        "mac_type": item.mac_type,
                    }
                    for item in items
                ],
            }, ensure_ascii=False)

        except IntegrationError as e:
            logger.error("Failed to get abnormal list: %s", e)
            return json.dumps({"error": str(e)}, ensure_ascii=False)
        except Exception as e:
            logger.error("Unexpected error getting abnormal list: %s", e)
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    async def get_abnormal_detail(
        self,
        tenant_id: str,
        user_id: str,
        abnormal_id: str,
        mac_id: str = "",
        component_id: str = "",
        token: str | None = None,
    ) -> str:
        """获取SMS异常详情。

        Args:
            tenant_id: 租户ID
            user_id: 用户ID
            abnormal_id: 异常ID
            mac_id: 设备ID（从列表数据补充，详情接口不返回）
            component_id: 子设备ID（从列表数据补充，详情接口不返回）
            token: 用户访问令牌

        Returns:
            格式化的异常详情JSON字符串
        """
        try:
            import json

            query = AbnormalDetailQuery(
                tenant_id=tenant_id,
                abnormal_id=abnormal_id,
            )
            auth_context = AuthContext(tenant_id=tenant_id, user_id=user_id, token=token)
            result = await self._service.get_abnormal_detail(query, auth_context)
            detail = result.data

            # 补充列表侧字段（详情接口mac_id/component_id可能为空）
            if not detail.mac_id and mac_id:
                detail = detail.__class__(
                    abnormal_id=detail.abnormal_id,
                    process_status=detail.process_status,
                    mac_path=detail.mac_path,
                    mac_name=detail.mac_name,
                    component_name=detail.component_name,
                    events=detail.events,
                    logs=detail.logs,
                    ai_analyse=detail.ai_analyse,
                    risk_assessment=detail.risk_assessment,
                    mac_id=mac_id,
                    component_id=component_id,
                )

            return json.dumps({
                "abnormal_id": detail.abnormal_id,
                "mac_path": detail.mac_path,
                "mac_name": detail.mac_name,
                "component_name": detail.component_name,
                "mac_id": detail.mac_id,
                "component_id": detail.component_id,
                "process_status": detail.process_status,
                "events": [
                    {
                        "time": e.time,
                        "health": e.health,
                        "type": e.type,
                        "run_status": e.run_status,
                        "event_level": e.event_level,
                        "desc": e.desc,
                        "points": [
                            {
                                "point_id": p.point_id,
                                "point_name": p.point_name,
                                "value_type": p.value_type,
                                "point_type": p.point_type,
                            }
                            for p in e.points
                        ],
                        "time_range_start": e.time_range_start,
                        "time_range_end": e.time_range_end,
                        "factory_id": e.factory_id,
                    }
                    for e in detail.events
                ],
                "logs": list(detail.logs),
                "ai_analyse": detail.ai_analyse,
                "risk_assessment": detail.risk_assessment,
            }, ensure_ascii=False)

        except IntegrationError as e:
            logger.error("Failed to get abnormal detail: %s", e)
            import json
            return json.dumps({"error": str(e)}, ensure_ascii=False)
        except Exception as e:
            logger.error("Unexpected error getting abnormal detail: %s", e)
            import json
            return json.dumps({"error": str(e)}, ensure_ascii=False)
