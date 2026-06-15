"""Monitoring tools for agent integration.

Provides callable tools for monitoring-related operations that agents can use
to query external systems for trend, waveform, orbit, and alarm data.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from deerflow.integrations.adapters.base import AuthContext
from deerflow.integrations.errors import IntegrationError
from deerflow.integrations.models.queries import (
    AlarmHistoryQuery,
    OrbitQuery,
    TrendQuery,
    WaveformQuery,
)
from deerflow.integrations.services.monitoring_service import MonitoringService

logger = logging.getLogger(__name__)


class MonitoringTools:
    """Tool wrappers for monitoring operations.

    Each method returns a formatted string suitable for agent consumption,
    including structured data and human-readable summaries.
    """

    def __init__(self, service: MonitoringService) -> None:
        self._service = service

    async def get_trend_data(
        self,
        tenant_id: str,
        user_id: str,
        asset_id: str,
        measurement_point_id: str,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        aggregation: str = "avg",
        interval: str = "1h",
        token: str | None = None,
    ) -> str:
        """获取趋势数据。

        Args:
            tenant_id: 租户ID
            user_id: 用户ID
            asset_id: 资产ID
            measurement_point_id: 测量点ID
            start_time: 开始时间（默认24小时前）
            end_time: 结束时间（默认当前）
            aggregation: 聚合方式（avg/max/min/sum）
            interval: 时间间隔（1m/5m/1h/1d）
            token: 用户访问令牌（用于 auth_mode=user_token 的外部系统透传）

        Returns:
            格式化的趋势数据字符串
        """
        try:
            if end_time is None:
                end_time = datetime.now()
            if start_time is None:
                start_time = end_time - timedelta(hours=24)

            query = TrendQuery(
                tenant_id=tenant_id,
                asset_id=asset_id,
                measurement_point_id=measurement_point_id,
                start_time=start_time,
                end_time=end_time,
                aggregation=aggregation,
                sample_interval=interval,
            )
            auth_context = AuthContext(tenant_id=tenant_id, user_id=user_id, token=token)

            result = await self._service.get_trend(query, auth_context)

            series = result.data
            if not series.points:
                return "未找到趋势数据。"

            lines = [
                f"## 趋势数据: {measurement_point_id}\n",
                f"**时间范围**: {start_time.strftime('%Y-%m-%d %H:%M')} 至 {end_time.strftime('%Y-%m-%d %H:%M')}",
                f"**数据点数**: {len(series.points)}",
                f"**单位**: {series.unit or '未指定'}\n",
            ]

            if series.statistics:
                stats = series.statistics
                lines.append("### 统计信息")
                lines.append(f"- 最小值: {stats.min_value}")
                lines.append(f"- 最大值: {stats.max_value}")
                lines.append(f"- 平均值: {stats.avg_value}")
                if stats.std_dev is not None:
                    lines.append(f"- 标准差: {stats.std_dev}")
                lines.append("")

            lines.append("### 最近数据点（最多10个）")
            for point in series.points[-10:]:
                timestamp = point.timestamp.strftime("%H:%M:%S")
                lines.append(f"- {timestamp}: {point.value}")

            return "\n".join(lines)

        except IntegrationError as e:
            logger.error("Failed to get trend data: %s", e)
            return f"获取趋势数据失败: {e}"
        except Exception as e:
            logger.error("Unexpected error getting trend data: %s", e)
            return f"获取趋势数据时发生错误: {e}"

    async def get_waveform_data(
        self,
        tenant_id: str,
        user_id: str,
        asset_id: str,
        measurement_point_id: str,
        captured_at: datetime | None = None,
        token: str | None = None,
    ) -> str:
        """获取波形数据。

        Args:
            tenant_id: 租户ID
            user_id: 用户ID
            asset_id: 资产ID
            measurement_point_id: 测量点ID
            captured_at: 指定时间点（默认最新）
            token: 用户访问令牌（用于 auth_mode=user_token 的外部系统透传）

        Returns:
            格式化的波形数据字符串
        """
        try:
            query = WaveformQuery(
                tenant_id=tenant_id,
                asset_id=asset_id,
                measurement_point_id=measurement_point_id,
                captured_at=captured_at,
            )
            auth_context = AuthContext(tenant_id=tenant_id, user_id=user_id, token=token)

            result = await self._service.get_waveform(query, auth_context)

            waveform = result.data
            lines = [
                f"## 波形数据: {measurement_point_id}\n",
                f"**采样率**: {waveform.sample_rate} Hz" if waveform.sample_rate else "**采样率**: 未指定",
                f"**采样点数**: {len(waveform.wave_x)}",
                f"**单位**: {waveform.unit or '未指定'}\n",
            ]

            if waveform.captured_at:
                lines.append(f"**采集时间**: {waveform.captured_at.strftime('%Y-%m-%d %H:%M:%S')}\n")

            if waveform.speed_rpm:
                lines.append(f"**转速**: {waveform.speed_rpm} RPM\n")

            if waveform.wave_y:
                peak = max(abs(v) for v in waveform.wave_y) if waveform.wave_y else 0
                lines.append("### 波形特征")
                lines.append(f"- 峰值: {peak:.4f}")

            return "\n".join(lines)

        except IntegrationError as e:
            logger.error("Failed to get waveform data: %s", e)
            return f"获取波形数据失败: {e}"
        except Exception as e:
            logger.error("Unexpected error getting waveform data: %s", e)
            return f"获取波形数据时发生错误: {e}"

    async def get_orbit_data(
        self,
        tenant_id: str,
        user_id: str,
        asset_id: str,
        measurement_point_id: str,
        captured_at: datetime | None = None,
        token: str | None = None,
    ) -> str:
        """获取轨迹数据。

        Args:
            tenant_id: 租户ID
            user_id: 用户ID
            asset_id: 资产ID
            measurement_point_id: 测量点ID
            captured_at: 指定时间点（默认最新）
            token: 用户访问令牌（用于 auth_mode=user_token 的外部系统透传）

        Returns:
            格式化的轨迹数据字符串
        """
        try:
            query = OrbitQuery(
                tenant_id=tenant_id,
                asset_id=asset_id,
                measurement_point_id=measurement_point_id,
                captured_at=captured_at,
            )
            auth_context = AuthContext(tenant_id=tenant_id, user_id=user_id, token=token)

            result = await self._service.get_orbit(query, auth_context)

            orbit = result.data
            lines = [
                f"## 轨迹数据: {measurement_point_id}\n",
                f"**数据点数**: {len(orbit.points)}",
                f"**单位**: {orbit.unit or '未指定'}\n",
            ]

            if orbit.captured_at:
                lines.append(f"**采集时间**: {orbit.captured_at.strftime('%Y-%m-%d %H:%M:%S')}\n")

            if orbit.speed_rpm:
                lines.append(f"**转速**: {orbit.speed_rpm} RPM\n")

            if orbit.probe_ids:
                lines.append(f"**探头**: {', '.join(orbit.probe_ids)}\n")

            if orbit.points:
                x_vals = [p[0] for p in orbit.points]
                y_vals = [p[1] for p in orbit.points]
                x_pp = max(x_vals) - min(x_vals) if x_vals else 0
                y_pp = max(y_vals) - min(y_vals) if y_vals else 0
                lines.append("### 轨迹特征")
                lines.append(f"- X方向峰峰值: {x_pp:.4f}")
                lines.append(f"- Y方向峰峰值: {y_pp:.4f}")

            return "\n".join(lines)

        except IntegrationError as e:
            logger.error("Failed to get orbit data: %s", e)
            return f"获取轨迹数据失败: {e}"
        except Exception as e:
            logger.error("Unexpected error getting orbit data: %s", e)
            return f"获取轨迹数据时发生错误: {e}"

    async def get_alarm_history(
        self,
        tenant_id: str,
        user_id: str,
        asset_id: str,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        severity: str | None = None,
        limit: int = 20,
        token: str | None = None,
    ) -> str:
        """获取报警历史。

        Args:
            tenant_id: 租户ID
            user_id: 用户ID
            asset_id: 资产ID
            start_time: 开始时间（默认7天前）
            end_time: 结束时间（默认当前）
            severity: 严重程度过滤（high/medium/low）
            limit: 返回条数限制
            token: 用户访问令牌（用于 auth_mode=user_token 的外部系统透传）

        Returns:
            格式化的报警历史字符串
        """
        try:
            if end_time is None:
                end_time = datetime.now()
            if start_time is None:
                start_time = end_time - timedelta(days=7)

            query = AlarmHistoryQuery(
                tenant_id=tenant_id,
                asset_id=asset_id,
                start_time=start_time,
                end_time=end_time,
                severity=(severity,) if severity else (),
                limit=limit,
            )
            auth_context = AuthContext(tenant_id=tenant_id, user_id=user_id, token=token)

            result = await self._service.get_alarm_history(query, auth_context)

            alarms = result.data
            if not alarms:
                return "未找到报警记录。"

            lines = [
                f"## 报警历史: {asset_id}\n",
                f"**时间范围**: {start_time.strftime('%Y-%m-%d')} 至 {end_time.strftime('%Y-%m-%d')}",
                f"**报警数量**: {len(alarms)}\n",
            ]

            severity_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}

            for alarm in alarms:
                emoji = severity_emoji.get(alarm.severity, "⚪")
                status = "已确认" if alarm.acknowledged else "未确认"
                lines.append(
                    f"{emoji} **{alarm.message}**\n"
                    f"  时间: {alarm.triggered_at.strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"  严重程度: {alarm.severity} | 状态: {status}\n"
                )

            return "\n".join(lines)

        except IntegrationError as e:
            logger.error("Failed to get alarm history: %s", e)
            return f"获取报警历史失败: {e}"
        except Exception as e:
            logger.error("Unexpected error getting alarm history: %s", e)
            return f"获取报警历史时发生错误: {e}"
