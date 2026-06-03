"""日报查询脚本的数据连接器。

提供 ``DailyDataProvider`` 协议及唯一实现 ``PlatformDailyProvider``，
通过集成平台桥接获取数据。仅依赖标准库。
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

# ---------------------------------------------------------------------------
# 结果封装
# ---------------------------------------------------------------------------

DEMO_FALLBACK = "demo_fallback"
HTTP_SUCCESS = "http"
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
# 协议
# ---------------------------------------------------------------------------


class DailyDataProvider(Protocol):
    """日报数据提供者协议，提供单日 ``current``/``compare`` 数据块。"""

    def fetch(
        self,
        *,
        date_str: str,
        equipment_ids: list[str],
        kpi_keys: list[str],
        eq_type: str,
        include_per_equipment: bool,
        equipment_meta: dict[str, dict] | None,
    ) -> ProviderResult: ...


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
        mode: 模式，如 ``"platform"`` / ``"demo"`` / ``"http"``
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
        3. 默认 ``platform``

    Raises:
        KeyError: 请求的模式未注册提供者
    """
    if source not in _PROVIDER_FACTORIES:
        raise ValueError(f"unknown data source: {source!r}")
    if mode is not None:
        chosen = mode.lower()
    else:
        env_mode = (os.environ.get("DEER_FLOW_DATA_PROVIDER") or "").lower()
        chosen = env_mode or "platform"
    factories = _PROVIDER_FACTORIES[source]
    if chosen not in factories:
        raise KeyError(
            f"no provider registered for source={source!r} mode={chosen!r}; "
            f"registered={sorted(factories.keys())}"
        )
    return factories[chosen]()


def list_registered() -> dict[str, list[str]]:
    """返回已注册的数据源及模式列表，供测试检查用。"""
    return {k: sorted(v.keys()) for k, v in _PROVIDER_FACTORIES.items()}


# ---------------------------------------------------------------------------
# 回退辅助
# ---------------------------------------------------------------------------


def fetch_with_fallback(
    *,
    source: str,
    fetch_args: dict,
    mode: str | None = None,
) -> ProviderResult:
    """尝试主提供者，失败时回退到 demo 提供者。

    ``data_source`` 标签会写入脚本 JSON 输出，供下游判断数据来源。
    """
    primary = get_provider(source, mode=mode)
    try:
        result = primary.fetch(**fetch_args)
        if not isinstance(result, ProviderResult):
            raise TypeError(f"{source} provider returned non-ProviderResult: {type(result)}")
        return result
    except HttpProviderError as exc:
        demo = get_provider(source, mode="demo")
        fallback = demo.fetch(**fetch_args)
        notes = list(fallback.notes) + [f"HTTP provider failed, fell back to demo: {exc}"]
        return ProviderResult(
            data=fallback.data,
            data_source=DEMO_FALLBACK,
            notes=notes,
        )
    except Exception:
        raise


# ---------------------------------------------------------------------------
# PlatformDailyProvider — 唯一的日报数据提供者实现
# ---------------------------------------------------------------------------


class PlatformDailyProvider:
    """通过集成平台桥接获取日报数据（capability + action）。

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
        """获取单日日报数据。

        先调用 ``monitoring.trend`` capability 获取原始趋势数据，
        再调用 ``aggregate_kpi`` action 对趋势数据做 KPI 聚合。

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
        from _platform_bridge import call_capability, call_action

        try:
            day_start = f"{date_str}T00:00:00"
            day_end = f"{date_str}T23:59:59"

            trend_result = call_capability("monitoring.trend", {
                "equipment_ids": equipment_ids,
                "start_time": day_start,
                "end_time": day_end,
                "eq_type": eq_type,
            })

            kpi_result = call_action("aggregate_kpi", adapter="ins_prod", params={
                "trend_data": trend_result["data"],
                "kpi_keys": kpi_keys,
                "eq_type": eq_type,
            })

        except Exception as exc:
            raise HttpProviderError(
                f"Platform daily provider failed: {type(exc).__name__}: {exc}"
            ) from exc

        kpi_data = kpi_result["data"]
        return ProviderResult(
            data={
                "kpis": kpi_data.get("kpis", {}),
                "hourly_runtime_rate": kpi_data.get("hourly_runtime_rate", [0.0] * 24),
                "alarms": [],
            },
            data_source=INS_SUCCESS,
        )


register_provider("daily", "platform", PlatformDailyProvider)
