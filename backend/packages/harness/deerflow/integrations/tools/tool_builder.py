"""Build LangChain-compatible tools from integration tool classes.

Wraps AssetTools, MonitoringTools, and AssessmentTools methods as StructuredTool
instances that can be injected into get_available_tools().
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from deerflow.integrations.adapters.base import AuthContext

logger = logging.getLogger(__name__)


class AssetCatalogInput(BaseModel):
    asset_types: list[str] = Field(default_factory=list, description="资产类型过滤")
    status: str | None = Field(default=None, description="状态过滤")
    search_text: str = Field(default="", description="搜索文本")
    limit: int = Field(default=100, description="返回条数")


class AssetContextInput(BaseModel):
    asset_id: str = Field(description="资产ID")
    include_children: bool = Field(default=True, description="是否包含子资产")
    include_measurement_points: bool = Field(default=True, description="是否包含测量点")


class AssetOverviewInput(BaseModel):
    asset_id: str = Field(description="资产ID")
    include_health_assessment: bool = Field(default=True, description="是否包含健康评估")
    include_recent_alarms: bool = Field(default=True, description="是否包含最近报警")


class TrendInput(BaseModel):
    asset_id: str = Field(description="资产ID")
    measurement_point_id: str = Field(description="测量点ID")
    start_time: datetime | None = Field(default=None, description="开始时间（默认24小时前）")
    end_time: datetime | None = Field(default=None, description="结束时间（默认当前）")
    aggregation: str = Field(default="avg", description="聚合方式")
    interval: str = Field(default="1h", description="时间间隔")


class WaveformInput(BaseModel):
    asset_id: str = Field(description="资产ID")
    measurement_point_id: str = Field(description="测量点ID")
    captured_at: datetime | None = Field(default=None, description="指定时间点")


class OrbitInput(BaseModel):
    asset_id: str = Field(description="资产ID")
    measurement_point_id: str = Field(description="测量点ID")
    captured_at: datetime | None = Field(default=None, description="指定时间点")


class AlarmHistoryInput(BaseModel):
    asset_id: str = Field(description="资产ID")
    start_time: datetime | None = Field(default=None, description="开始时间（默认7天前）")
    end_time: datetime | None = Field(default=None, description="结束时间（默认当前）")
    severity: str | None = Field(default=None, description="严重程度过滤")
    limit: int = Field(default=20, description="返回条数")


class HealthAssessmentInput(BaseModel):
    asset_id: str = Field(description="资产ID")
    assessed_at: datetime | None = Field(default=None, description="评估时间点")


class AnomalyStatsInput(BaseModel):
    asset_id: str = Field(description="资产ID")
    start_time: datetime | None = Field(default=None, description="开始时间（默认30天前）")
    end_time: datetime | None = Field(default=None, description="结束时间（默认当前）")


class RiskRankingInput(BaseModel):
    scope: str = Field(default="", description="评估范围")
    limit: int = Field(default=50, description="返回条数")
    min_risk_score: float = Field(default=0.0, description="最小风险分数")


class OutboundQueryInput(BaseModel):
    spec_model: str | None = Field(default=None, description="规格型号过滤")
    start_date: str | None = Field(default=None, description="开始日期 (YYYY-MM-DD)")
    end_date: str | None = Field(default=None, description="结束日期 (YYYY-MM-DD)")
    limit: int = Field(default=500, description="返回条数")


class OutboundStatsInput(BaseModel):
    start_date: str | None = Field(default=None, description="开始日期 (YYYY-MM-DD)")
    end_date: str | None = Field(default=None, description="结束日期 (YYYY-MM-DD)")
    group_by: str | None = Field(default=None, description="分组方式 (spec_model/day/week/month)")


class ServiceEventQueryInput(BaseModel):
    unit_name: str | None = Field(default=None, description="机组名称过滤")
    event_name: str | None = Field(default=None, description="事件名称过滤")
    start_date: str | None = Field(default=None, description="开始日期 (YYYY-MM-DD)")
    end_date: str | None = Field(default=None, description="结束日期 (YYYY-MM-DD)")
    limit: int = Field(default=500, description="返回条数")


class ServiceEventStatsInput(BaseModel):
    start_date: str | None = Field(default=None, description="开始日期 (YYYY-MM-DD)")
    end_date: str | None = Field(default=None, description="结束日期 (YYYY-MM-DD)")
    group_by: str | None = Field(default=None, description="分组方式 (unit_name/event_name/day/week/month)")


class EventAnomalyInput(BaseModel):
    start_date: str | None = Field(default=None, description="开始日期 (YYYY-MM-DD)")
    end_date: str | None = Field(default=None, description="结束日期 (YYYY-MM-DD)")
    threshold: float = Field(default=2.0, description="异常检测阈值（标准差倍数）")


class XsyReportInput(BaseModel):
    start_date: str | None = Field(default=None, description="开始日期 (YYYY-MM-DD)")
    end_date: str | None = Field(default=None, description="结束日期 (YYYY-MM-DD)")


def build_integration_tools(
    auth_context: AuthContext,
    data_tools: list[str],
) -> list[StructuredTool]:
    """Build LangChain tools for the given data_tools selection.

    Args:
        auth_context: Authentication context (tenant_id, user_id)
        data_tools: List of tool names to include. Supports:
            - Specific tools: ["equipment_get_overview", "monitoring_get_trend"]
            - Wildcard groups: ["asset.*", "monitoring.*", "assessment.*"]
            - All: ["*"]

    Returns:
        List of StructuredTool instances
    """
    from deerflow.integrations.tools.registry import get_tool_registry

    registry = get_tool_registry()
    if registry is None:
        return []

    if not registry._initialized:
        return []

    tenant_id = auth_context.tenant_id
    user_id = auth_context.user_id or ""
    token = auth_context.token

    tools: list[StructuredTool] = []

    asset_tools = registry.get_tool("asset")
    monitoring_tools = registry.get_tool("monitoring")
    assessment_tools = registry.get_tool("assessment")
    xsy_tools = registry.get_tool("xsy")

    if _should_include(data_tools, "asset_get_catalog", "asset"):
        if asset_tools:
            tools.append(StructuredTool(
                name="asset_get_catalog",
                description="获取资产目录列表，可按类型、状态、关键词过滤",
                args_schema=AssetCatalogInput,
                coroutine=_make_coro(
                    asset_tools.get_asset_catalog, tenant_id, user_id,
                    _transform_catalog_args, token,
                ),
            ))

    if _should_include(data_tools, "equipment_get_context", "asset"):
        if asset_tools:
            tools.append(StructuredTool(
                name="equipment_get_context",
                description="获取设备上下文信息，包括子设备和测量点",
                args_schema=AssetContextInput,
                coroutine=_make_coro(
                    asset_tools.get_asset_context, tenant_id, user_id,
                    _transform_context_args, token,
                ),
            ))

    if _should_include(data_tools, "equipment_get_overview", "asset"):
        if asset_tools:
            tools.append(StructuredTool(
                name="equipment_get_overview",
                description="获取设备综合概览，包括基本信息、健康评估和最近报警",
                args_schema=AssetOverviewInput,
                coroutine=_make_coro(
                    asset_tools.get_asset_overview, tenant_id, user_id,
                    _transform_overview_args, token,
                ),
            ))

    if _should_include(data_tools, "monitoring_get_trend", "monitoring"):
        if monitoring_tools:
            tools.append(StructuredTool(
                name="monitoring_get_trend",
                description="获取测量点趋势数据，包括统计信息和历史数据点",
                args_schema=TrendInput,
                coroutine=_make_coro(
                    monitoring_tools.get_trend_data, tenant_id, user_id,
                    _transform_trend_args, token,
                ),
            ))

    if _should_include(data_tools, "monitoring_get_waveform", "monitoring"):
        if monitoring_tools:
            tools.append(StructuredTool(
                name="monitoring_get_waveform",
                description="获取测量点波形数据，包括峰值、有效值、峭度等特征",
                args_schema=WaveformInput,
                coroutine=_make_coro(
                    monitoring_tools.get_waveform_data, tenant_id, user_id,
                    _transform_waveform_args, token,
                ),
            ))

    if _should_include(data_tools, "monitoring_get_orbit", "monitoring"):
        if monitoring_tools:
            tools.append(StructuredTool(
                name="monitoring_get_orbit",
                description="获取测量点轨迹数据，包括峰峰值、最大半径等特征",
                args_schema=OrbitInput,
                coroutine=_make_coro(
                    monitoring_tools.get_orbit_data, tenant_id, user_id,
                    _transform_orbit_args, token,
                ),
            ))

    if _should_include(data_tools, "monitoring_get_alarm_history", "monitoring"):
        if monitoring_tools:
            tools.append(StructuredTool(
                name="monitoring_get_alarm_history",
                description="获取设备报警历史记录",
                args_schema=AlarmHistoryInput,
                coroutine=_make_coro(
                    monitoring_tools.get_alarm_history, tenant_id, user_id,
                    _transform_alarm_args, token,
                ),
            ))

    if _should_include(data_tools, "health_get_assessment", "assessment"):
        if assessment_tools:
            tools.append(StructuredTool(
                name="health_get_assessment",
                description="获取设备健康评估，包括总体评分、维度评分和建议措施",
                args_schema=HealthAssessmentInput,
                coroutine=_make_coro(
                    assessment_tools.get_health_assessment, tenant_id, user_id,
                    _transform_health_args, token,
                ),
            ))

    if _should_include(data_tools, "anomaly_get_stats", "assessment"):
        if assessment_tools:
            tools.append(StructuredTool(
                name="anomaly_get_stats",
                description="获取设备异常统计信息，按严重程度和类型分类",
                args_schema=AnomalyStatsInput,
                coroutine=_make_coro(
                    assessment_tools.get_anomaly_statistics, tenant_id, user_id,
                    _transform_anomaly_args, token,
                ),
            ))

    if _should_include(data_tools, "fault_get_risk_ranking", "assessment"):
        if assessment_tools:
            tools.append(StructuredTool(
                name="fault_get_risk_ranking",
                description="获取设备风险排名",
                args_schema=RiskRankingInput,
                coroutine=_make_coro(
                    assessment_tools.get_risk_ranking, tenant_id, user_id,
                    _transform_risk_args, token,
                ),
            ))

    # XSY (销售易) CRM tools
    if _should_include(data_tools, "crm_query_outbound", "crm"):
        if xsy_tools:
            tools.append(StructuredTool(
                name="crm_query_outbound",
                description="查询产品出库明细（销售易 CRM）",
                args_schema=OutboundQueryInput,
                coroutine=_make_coro(
                    xsy_tools.query_outbound, tenant_id, user_id,
                    _transform_outbound_query_args, token,
                ),
            ))

    if _should_include(data_tools, "crm_get_outbound_stats", "crm"):
        if xsy_tools:
            tools.append(StructuredTool(
                name="crm_get_outbound_stats",
                description="获取出库统计数据（销售易 CRM）",
                args_schema=OutboundStatsInput,
                coroutine=_make_coro(
                    xsy_tools.get_outbound_statistics, tenant_id, user_id,
                    _transform_outbound_stats_args, token,
                ),
            ))

    if _should_include(data_tools, "crm_query_service_events", "crm"):
        if xsy_tools:
            tools.append(StructuredTool(
                name="crm_query_service_events",
                description="查询服务事件明细（销售易 CRM）",
                args_schema=ServiceEventQueryInput,
                coroutine=_make_coro(
                    xsy_tools.query_service_events, tenant_id, user_id,
                    _transform_service_event_query_args, token,
                ),
            ))

    if _should_include(data_tools, "crm_get_event_stats", "crm"):
        if xsy_tools:
            tools.append(StructuredTool(
                name="crm_get_event_stats",
                description="获取服务事件统计数据（销售易 CRM）",
                args_schema=ServiceEventStatsInput,
                coroutine=_make_coro(
                    xsy_tools.get_service_event_statistics, tenant_id, user_id,
                    _transform_service_event_stats_args, token,
                ),
            ))

    if _should_include(data_tools, "crm_detect_event_anomalies", "crm"):
        if xsy_tools:
            tools.append(StructuredTool(
                name="crm_detect_event_anomalies",
                description="检测服务事件异常（销售易 CRM）",
                args_schema=EventAnomalyInput,
                coroutine=_make_coro(
                    xsy_tools.detect_event_anomalies, tenant_id, user_id,
                    _transform_event_anomaly_args, token,
                ),
            ))

    if _should_include(data_tools, "crm_generate_report", "crm"):
        if xsy_tools:
            tools.append(StructuredTool(
                name="crm_generate_report",
                description="生成综合报告（销售易 CRM）",
                args_schema=XsyReportInput,
                coroutine=_make_coro(
                    xsy_tools.generate_report, tenant_id, user_id,
                    _transform_xsy_report_args, token,
                ),
            ))

    logger.info("Built %d integration tools for data_tools=%s", len(tools), data_tools)
    return tools


def _should_include(data_tools: list[str], tool_name: str, group: str) -> bool:
    if "*" in data_tools:
        return True
    if f"{group}.*" in data_tools:
        return True
    return tool_name in data_tools


def _make_coro(method, tenant_id, user_id, args_transform, token=None):
    async def coro(**kwargs):
        transformed = args_transform(kwargs)
        return await method(tenant_id=tenant_id, user_id=user_id, token=token, **transformed)
    return coro


def _transform_catalog_args(kwargs: dict) -> dict:
    return {
        "asset_types": tuple(kwargs.get("asset_types", [])),
        "status": kwargs.get("status"),
        "search_text": kwargs.get("search_text", ""),
        "limit": kwargs.get("limit", 100),
    }


def _transform_context_args(kwargs: dict) -> dict:
    return {
        "asset_id": kwargs["asset_id"],
        "include_children": kwargs.get("include_children", True),
        "include_measurement_points": kwargs.get("include_measurement_points", True),
    }


def _transform_overview_args(kwargs: dict) -> dict:
    return {
        "asset_id": kwargs["asset_id"],
        "include_health_assessment": kwargs.get("include_health_assessment", True),
        "include_recent_alarms": kwargs.get("include_recent_alarms", True),
    }


def _transform_trend_args(kwargs: dict) -> dict:
    return {
        "asset_id": kwargs["asset_id"],
        "measurement_point_id": kwargs["measurement_point_id"],
        "start_time": kwargs.get("start_time"),
        "end_time": kwargs.get("end_time"),
        "aggregation": kwargs.get("aggregation", "avg"),
        "interval": kwargs.get("interval", "1h"),
    }


def _transform_waveform_args(kwargs: dict) -> dict:
    return {
        "asset_id": kwargs["asset_id"],
        "measurement_point_id": kwargs["measurement_point_id"],
        "captured_at": kwargs.get("captured_at"),
    }


def _transform_orbit_args(kwargs: dict) -> dict:
    return {
        "asset_id": kwargs["asset_id"],
        "measurement_point_id": kwargs["measurement_point_id"],
        "captured_at": kwargs.get("captured_at"),
    }


def _transform_alarm_args(kwargs: dict) -> dict:
    return {
        "asset_id": kwargs["asset_id"],
        "start_time": kwargs.get("start_time"),
        "end_time": kwargs.get("end_time"),
        "severity": kwargs.get("severity"),
        "limit": kwargs.get("limit", 20),
    }


def _transform_health_args(kwargs: dict) -> dict:
    return {
        "asset_id": kwargs["asset_id"],
        "assessed_at": kwargs.get("assessed_at"),
    }


def _transform_anomaly_args(kwargs: dict) -> dict:
    return {
        "asset_id": kwargs["asset_id"],
        "start_time": kwargs.get("start_time"),
        "end_time": kwargs.get("end_time"),
    }


def _transform_risk_args(kwargs: dict) -> dict:
    return {
        "scope": kwargs.get("scope", ""),
        "limit": kwargs.get("limit", 50),
        "min_risk_score": kwargs.get("min_risk_score", 0.0),
    }


def _transform_outbound_query_args(kwargs: dict) -> dict:
    return {
        "spec_model": kwargs.get("spec_model"),
        "start_date": kwargs.get("start_date"),
        "end_date": kwargs.get("end_date"),
        "limit": kwargs.get("limit", 500),
    }


def _transform_outbound_stats_args(kwargs: dict) -> dict:
    return {
        "start_date": kwargs.get("start_date"),
        "end_date": kwargs.get("end_date"),
        "group_by": kwargs.get("group_by"),
    }


def _transform_service_event_query_args(kwargs: dict) -> dict:
    return {
        "unit_name": kwargs.get("unit_name"),
        "event_name": kwargs.get("event_name"),
        "start_date": kwargs.get("start_date"),
        "end_date": kwargs.get("end_date"),
        "limit": kwargs.get("limit", 500),
    }


def _transform_service_event_stats_args(kwargs: dict) -> dict:
    return {
        "start_date": kwargs.get("start_date"),
        "end_date": kwargs.get("end_date"),
        "group_by": kwargs.get("group_by"),
    }


def _transform_event_anomaly_args(kwargs: dict) -> dict:
    return {
        "start_date": kwargs.get("start_date"),
        "end_date": kwargs.get("end_date"),
        "threshold": kwargs.get("threshold", 2.0),
    }


def _transform_xsy_report_args(kwargs: dict) -> dict:
    return {
        "start_date": kwargs.get("start_date"),
        "end_date": kwargs.get("end_date"),
    }
