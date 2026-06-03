"""日报查询脚本的数据连接器。

提供唯一实现 ``InsDailyProvider``，通过 features-tool 直接获取 InS 数据并本地聚合 KPI。
仅依赖标准库 + features-tool。
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# 结果封装
# ---------------------------------------------------------------------------

DEMO_FALLBACK = "demo_fallback"
INS_SUCCESS = "ins"


@dataclass(frozen=True)
class ProviderResult:
    """数据提供者返回的结果封装。

    ``data`` 是脚本所需的原始数据字典，
    ``data_source`` 标记数据来源，写入脚本的 JSON 输出中。
    """

    data: dict
    data_source: str = DEMO_FALLBACK
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 异常
# ---------------------------------------------------------------------------


class HttpProviderError(RuntimeError):
    """后端调用不可恢复失败时抛出。

    调用方决定是向上传播还是回退到 demo 提供者。
    """


# ---------------------------------------------------------------------------
# 注册表
# ---------------------------------------------------------------------------


_PROVIDER_FACTORIES: dict[str, dict[str, Callable[[], Any]]] = {
    "daily": {},
}


def register_provider(source: str, mode: str, factory: Callable[[], Any]) -> None:
    """注册数据提供者工厂。

    Args:
        source: 数据源标识，如 ``"daily"``
        mode: 模式，如 ``"ins"`` / ``"demo"`` / ``"http"``
        factory: 无参工厂函数，返回提供者实例
    """
    if source not in _PROVIDER_FACTORIES:
        raise ValueError(f"unknown data source: {source!r}")
    _PROVIDER_FACTORIES[source][mode] = factory


def get_provider(source: str, *, mode: str | None = None) -> Any:
    """根据数据源和模式解析并返回提供者实例。

    模式解析优先级：
        1. 显式传入的 ``mode`` 参数
        2. ``DEER_FLOW_DATA_PROVIDER`` 环境变量
        3. 默认 ``ins``

    Raises:
        KeyError: 请求的模式未注册提供者
    """
    if source not in _PROVIDER_FACTORIES:
        raise ValueError(f"unknown data source: {source!r}")
    if mode is not None:
        chosen = mode.lower()
    else:
        env_mode = (os.environ.get("DEER_FLOW_DATA_PROVIDER") or "").lower()
        chosen = env_mode or "ins"
    factories = _PROVIDER_FACTORIES[source]
    if chosen not in factories:
        raise KeyError(
            f"no provider registered for source={source!r} mode={chosen!r}; "
            f"registered={sorted(factories.keys())}"
        )
    return factories[chosen]()


# ---------------------------------------------------------------------------
# InsDailyProvider — 唯一的日报数据提供者实现
# ---------------------------------------------------------------------------


def _aggregate_across_equipment(
    equipment_kpis: dict[str, dict[str, Any]],
    kpi_keys: list[str],
) -> dict[str, Any]:
    """Aggregate per-equipment KPI dicts into a single flat KPI dict.

    For each KPI key, computes the mean across equipment that have a non-None value.
    """
    result: dict[str, Any] = {}
    for key in kpi_keys:
        values = [
            v for eq_kpis in equipment_kpis.values()
            if (v := eq_kpis.get(key)) is not None
        ]
        if values:
            result[key] = round(sum(values) / len(values), 4)
        else:
            result[key] = None
    return result


class InsDailyProvider:
    """通过 features-tool 直接获取 InS 日报数据。

    成功时返回 ``current`` 块结构字典，标记 ``data_source="ins"``。
    失败时抛出 ``HttpProviderError``，由查询脚本转为 ``{"error": ...}`` 输出。
    """

    def fetch(
        self,
        *,
        date_str: str,
        equipment_ids: list[str],
        kpi_keys: list[str],
        eq_type: str = "all",
        include_per_equipment: bool = False,
        equipment_meta: dict[str, dict] | None = None,
    ) -> ProviderResult:
        """获取单日日报数据 — 直接调用 features-tool + 本地 KPI 聚合。

        Args:
            date_str: 报告日期，格式 ``YYYY-MM-DD``
            equipment_ids: 设备 ID 列表
            kpi_keys: 需要查询的 KPI 键列表
            eq_type: 设备类型过滤
            include_per_equipment: 是否包含逐设备明细
            equipment_meta: 设备元信息（id → {name, area}）

        Returns:
            包含 ``kpis``、``hourly_runtime_rate``、``alarms`` 的结果封装
        """
        from _ins_client import fetch_alarm_events, fetch_trend_data, is_available
        from _kpi_aggregator import (
            aggregate_equipment_kpis,
            compute_hourly_runtime_rate,
        )

        if not is_available():
            from _ins_client import get_availability_reason
            raise HttpProviderError(
                f"features-tool not available: {get_availability_reason()}"
            )

        try:
            day_start = f"{date_str}T00:00:00"
            day_end = f"{date_str}T23:59:59"

            trend_data = fetch_trend_data(
                equipment_ids, day_start, day_end, eq_type,
            )

            kpis_by_eq, union_speed = aggregate_equipment_kpis(
                trend_data, kpi_keys, {},
            )
            hourly = compute_hourly_runtime_rate(union_speed)

            alarms = fetch_alarm_events(
                equipment_ids, day_start, day_end, eq_type,
            )

        except Exception as exc:
            raise HttpProviderError(
                f"Ins daily provider failed: {type(exc).__name__}: {exc}"
            ) from exc

        equipment_kpis = kpis_by_eq or {}

        if include_per_equipment and equipment_kpis:
            per_equipment = {
                eq_id: {
                    "kpis": kpis,
                    "hourly_runtime_rate": hourly,
                }
                for eq_id, kpis in equipment_kpis.items()
            }
        else:
            per_equipment = None

        aggregated_kpis = _aggregate_across_equipment(equipment_kpis, kpi_keys)

        return ProviderResult(
            data={
                "kpis": aggregated_kpis,
                "hourly_runtime_rate": hourly,
                "alarms": alarms,
                "per_equipment": per_equipment,
            },
            data_source=INS_SUCCESS,
        )


register_provider("daily", "ins", InsDailyProvider)
