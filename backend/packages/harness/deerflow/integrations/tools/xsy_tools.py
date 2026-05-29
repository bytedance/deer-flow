"""Xiaoshouyi (销售易) tools for agent integration.

Each method returns a formatted Markdown string suitable for agent consumption.
"""

from __future__ import annotations

import logging

from deerflow.integrations.adapters.base import AuthContext
from deerflow.integrations.errors import IntegrationError
from deerflow.integrations.models.queries import OutboundDetailQuery, ServiceEventQuery
from deerflow.integrations.models.xsy import (
    OutboundDetail,
    OutboundStatistics,
    ServiceEventAnomaly,
    ServiceEventDetail,
    ServiceEventStatistics,
)
from deerflow.integrations.services.xsy_service import XsyService

logger = logging.getLogger(__name__)


class XsyTools:
    """Tool wrappers for Xiaoshouyi CRM operations."""

    def __init__(self, service: XsyService) -> None:
        self._service = service

    async def query_outbound(
        self,
        tenant_id: str,
        user_id: str,
        spec_model: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 500,
        token: str | None = None,
    ) -> str:
        """查询产品出库明细."""
        try:
            from datetime import datetime

            query = OutboundDetailQuery(
                tenant_id=tenant_id,
                spec_model=spec_model,
                start_time=datetime.fromisoformat(start_date) if start_date else None,
                end_time=datetime.fromisoformat(end_date) if end_date else None,
                limit=limit,
            )
            auth_context = AuthContext(tenant_id=tenant_id, user_id=user_id, token=token)
            result = await self._service.query_outbound(query, auth_context)

            records: tuple[OutboundDetail, ...] = result.data
            if not records:
                return "未找到出库记录。"

            lines: list[str] = [f"## 出库明细 (共 {len(records)} 条)\n"]
            lines.append("| 数量 | 规格型号 | 创建日期 |")
            lines.append("|------|---------|---------|")
            for r in records[:50]:  # Limit display to 50
                date_str = r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else "-"
                lines.append(f"| {r.quantity} | {r.spec_model or '-'} | {date_str} |")
            if len(records) > 50:
                lines.append(f"\n... 还有 {len(records) - 50} 条记录")
            return "\n".join(lines)

        except IntegrationError as e:
            logger.error("Failed to query outbound: %s", e)
            return f"查询出库明细失败: {e}"
        except Exception as e:
            logger.error("Unexpected error: %s", e)
            return f"查询出库明细时发生错误: {e}"

    async def get_outbound_statistics(
        self,
        tenant_id: str,
        user_id: str,
        start_date: str | None = None,
        end_date: str | None = None,
        group_by: str | None = None,
        token: str | None = None,
    ) -> str:
        """获取出库统计数据."""
        try:
            from datetime import datetime

            query = OutboundDetailQuery(
                tenant_id=tenant_id,
                start_time=datetime.fromisoformat(start_date) if start_date else None,
                end_time=datetime.fromisoformat(end_date) if end_date else None,
                group_by=group_by,
                limit=500,
            )
            auth_context = AuthContext(tenant_id=tenant_id, user_id=user_id, token=token)
            result = await self._service.get_outbound_statistics(query, auth_context)

            stats: OutboundStatistics = result.data
            lines: list[str] = ["## 出库统计\n"]
            lines.append(f"**总记录数**: {stats.total_records}")
            lines.append(f"**总数量**: {stats.total_quantity:.2f}")
            lines.append(f"**平均数量**: {stats.avg_quantity:.2f}")
            lines.append(f"**最小数量**: {stats.min_quantity:.2f}")
            lines.append(f"**最大数量**: {stats.max_quantity:.2f}")

            if stats.by_spec_model:
                lines.append("\n### 按规格型号")
                for spec, qty in sorted(stats.by_spec_model.items(), key=lambda x: x[1], reverse=True):
                    lines.append(f"- {spec}: {qty:.2f}")

            if stats.by_period:
                lines.append("\n### 按周期")
                for period, qty in sorted(stats.by_period.items()):
                    lines.append(f"- {period}: {qty:.2f}")

            return "\n".join(lines)

        except IntegrationError as e:
            logger.error("Failed to get outbound statistics: %s", e)
            return f"获取出库统计失败: {e}"
        except Exception as e:
            logger.error("Unexpected error: %s", e)
            return f"获取出库统计时发生错误: {e}"

    async def query_service_events(
        self,
        tenant_id: str,
        user_id: str,
        unit_name: str | None = None,
        event_name: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 500,
        token: str | None = None,
    ) -> str:
        """查询服务事件明细."""
        try:
            from datetime import datetime

            query = ServiceEventQuery(
                tenant_id=tenant_id,
                unit_name=unit_name,
                event_name=event_name,
                start_time=datetime.fromisoformat(start_date) if start_date else None,
                end_time=datetime.fromisoformat(end_date) if end_date else None,
                limit=limit,
            )
            auth_context = AuthContext(tenant_id=tenant_id, user_id=user_id, token=token)
            result = await self._service.query_service_events(query, auth_context)

            records: tuple[ServiceEventDetail, ...] = result.data
            if not records:
                return "未找到服务事件记录。"

            lines: list[str] = [f"## 服务事件明细 (共 {len(records)} 条)\n"]
            lines.append("| 机组名称 | 事件名称 | 事件时间 |")
            lines.append("|---------|---------|---------|")
            for r in records[:50]:
                time_str = r.event_time.strftime("%Y-%m-%d %H:%M") if r.event_time else "-"
                lines.append(f"| {r.unit_name or '-'} | {r.event_name or '-'} | {time_str} |")
            if len(records) > 50:
                lines.append(f"\n... 还有 {len(records) - 50} 条记录")
            return "\n".join(lines)

        except IntegrationError as e:
            logger.error("Failed to query service events: %s", e)
            return f"查询服务事件失败: {e}"
        except Exception as e:
            logger.error("Unexpected error: %s", e)
            return f"查询服务事件时发生错误: {e}"

    async def get_service_event_statistics(
        self,
        tenant_id: str,
        user_id: str,
        start_date: str | None = None,
        end_date: str | None = None,
        group_by: str | None = None,
        token: str | None = None,
    ) -> str:
        """获取服务事件统计数据."""
        try:
            from datetime import datetime

            query = ServiceEventQuery(
                tenant_id=tenant_id,
                start_time=datetime.fromisoformat(start_date) if start_date else None,
                end_time=datetime.fromisoformat(end_date) if end_date else None,
                group_by=group_by,
                limit=500,
            )
            auth_context = AuthContext(tenant_id=tenant_id, user_id=user_id, token=token)
            result = await self._service.get_service_event_statistics(query, auth_context)

            stats: ServiceEventStatistics = result.data
            lines: list[str] = ["## 服务事件统计\n"]
            lines.append(f"**总记录数**: {stats.total_records}")

            if stats.by_unit:
                lines.append("\n### 按机组")
                for unit, count in sorted(stats.by_unit.items(), key=lambda x: x[1], reverse=True):
                    lines.append(f"- {unit}: {count} 次")

            if stats.by_event_type:
                lines.append("\n### 按事件类型")
                for event_type, count in sorted(stats.by_event_type.items(), key=lambda x: x[1], reverse=True):
                    lines.append(f"- {event_type}: {count} 次")

            if stats.frequency_per_unit:
                lines.append("\n### 频率（次/天）")
                for unit, freq in sorted(stats.frequency_per_unit.items(), key=lambda x: x[1], reverse=True):
                    lines.append(f"- {unit}: {freq:.2f}")

            return "\n".join(lines)

        except IntegrationError as e:
            logger.error("Failed to get service event statistics: %s", e)
            return f"获取服务事件统计失败: {e}"
        except Exception as e:
            logger.error("Unexpected error: %s", e)
            return f"获取服务事件统计时发生错误: {e}"

    async def detect_event_anomalies(
        self,
        tenant_id: str,
        user_id: str,
        start_date: str | None = None,
        end_date: str | None = None,
        threshold: float = 2.0,
        token: str | None = None,
    ) -> str:
        """检测服务事件异常."""
        try:
            from datetime import datetime

            query = ServiceEventQuery(
                tenant_id=tenant_id,
                start_time=datetime.fromisoformat(start_date) if start_date else None,
                end_time=datetime.fromisoformat(end_date) if end_date else None,
                limit=500,
                extra_filters={"threshold": threshold},
            )
            auth_context = AuthContext(tenant_id=tenant_id, user_id=user_id, token=token)
            result = await self._service.detect_event_anomalies(query, auth_context)

            anomalies: tuple[ServiceEventAnomaly, ...] = result.data
            if not anomalies:
                return "✅ 未检测到异常。"

            lines: list[str] = [f"## ⚠️ 异常检测结果 (共 {len(anomalies)} 个)\n"]
            for i, a in enumerate(anomalies, 1):
                severity_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(a.severity, "⚪")
                lines.append(f"### {i}. {severity_icon} {a.anomaly_type.replace('_', ' ').title()}")
                lines.append(f"**描述**: {a.description}")
                lines.append(f"**严重程度**: {a.severity}")
                if a.unit_name:
                    lines.append(f"**机组**: {a.unit_name}")
                if a.event_name:
                    lines.append(f"**事件**: {a.event_name}")
                lines.append("")

            return "\n".join(lines)

        except IntegrationError as e:
            logger.error("Failed to detect anomalies: %s", e)
            return f"异常检测失败: {e}"
        except Exception as e:
            logger.error("Unexpected error: %s", e)
            return f"异常检测时发生错误: {e}"

    async def generate_report(
        self,
        tenant_id: str,
        user_id: str,
        start_date: str | None = None,
        end_date: str | None = None,
        token: str | None = None,
    ) -> str:
        """生成综合报告."""
        try:
            from datetime import datetime

            query = OutboundDetailQuery(
                tenant_id=tenant_id,
                start_time=datetime.fromisoformat(start_date) if start_date else None,
                end_time=datetime.fromisoformat(end_date) if end_date else None,
                limit=500,
            )
            auth_context = AuthContext(tenant_id=tenant_id, user_id=user_id, token=token)
            result = await self._service.generate_report(query, auth_context)

            data: dict = result.data
            lines: list[str] = ["# 销售易综合报告\n"]

            # Outbound summary
            outbound_stats = data.get("outbound_statistics")
            if outbound_stats:
                lines.append("## 出库概况\n")
                lines.append(f"- 总记录数: {outbound_stats.total_records}")
                lines.append(f"- 总数量: {outbound_stats.total_quantity:.2f}")
                lines.append("")

            # Service events summary
            event_stats = data.get("service_event_statistics")
            if event_stats:
                lines.append("## 服务事件概况\n")
                lines.append(f"- 总记录数: {event_stats.total_records}")
                if event_stats.by_unit:
                    lines.append(f"- 涉及机组: {len(event_stats.by_unit)} 个")
                lines.append("")

            # Anomalies
            anomalies = data.get("anomalies", ())
            if anomalies:
                lines.append(f"## 异常告警 ({len(anomalies)} 个)\n")
                for a in anomalies[:10]:
                    lines.append(f"- **{a.severity}**: {a.description}")
                lines.append("")

            return "\n".join(lines)

        except IntegrationError as e:
            logger.error("Failed to generate report: %s", e)
            return f"生成报告失败: {e}"
        except Exception as e:
            logger.error("Unexpected error: %s", e)
            return f"生成报告时发生错误: {e}"
