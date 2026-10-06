"""Trend read-set over eval_runs rows (contract v4, spec 2026-09-07 §2).

Pure functions, no IO (``metrics.py`` precedent). run 级点语义：一个点 =
一次真实运行（x = ``coerce_iso`` 完整时间戳），不做周期分桶——周期末次
聚合退役（spec 2026-08-24 §4.2 v3）：同日多次运行各自出点，时间连续性
与密度由前端 ECharts time 轴 + 滚轮缩放承载。窗口过滤由调用方完成
（固定近 ``TREND_WINDOW_DAYS`` 天）；本模块只负责取数集合过滤
（completed + 任一层 metrics 非空 + 默认排除 ci）与 run 级点组装。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Literal, Protocol

from deerflow.knowledge.eval.persistence import ENV_CI, STATUS_COMPLETED
from deerflow.utils.time import coerce_iso

#: 趋势固定窗口（contract v4 冻结）：近 90 天，亦为滚轮缩小上限；
#: 由旧 ``MAX_DAYS_BACK`` day 档上限语义改名而来。
TREND_WINDOW_DAYS = 90

#: sparkline 每指标保留的 run 级近端非空值上限（spec §6.2 冻结）。
MAX_SPARKS = 10

#: 顶层 ``sparks`` 的 8 个 Layer 2 键（RAGAS 4 + 引用 3 + 路由命中率，含退役的
#: context_recall）。ragas 四键取 ``layer2_metrics["ragas"]``，引用三键取
#: ``layer2_metrics["arch_specific"]``；路由命中率取 ``layer2_metrics`` 顶层
#: ``path_accuracy``（真实对话链路口径，展示面键名与存储键名解耦）。
_SPARK_RAGAS_KEYS = ("faithfulness", "answer_relevancy", "context_precision", "context_recall")
_SPARK_ARCH_KEYS = ("citation_precision", "citation_recall", "seed_hit_rate")
_SPARK_LIVE_KEYS = ("routing_hit_rate",)
SPARK_KEYS = (*_SPARK_RAGAS_KEYS, *_SPARK_ARCH_KEYS, *_SPARK_LIVE_KEYS)


class EvalTrendRow(Protocol):
    """聚合所需的最小行形态——ORM ``EvalRunRow`` 与测试替身（SimpleNamespace）均满足。"""

    id: str
    status: str
    environment: str
    layer1_metrics: dict[str, Any]
    layer2_metrics: dict[str, Any]
    baseline_diff: dict[str, Any] | None
    is_baseline: bool
    created_at: datetime


def _in_read_set(row: EvalTrendRow, layer: Literal["layer1", "layer2"], *, include_ci: bool) -> bool:
    """取数集合规则（§4.2，latest 与 trend 同源）：completed + 该层 metrics 非空；ci 默认排除。"""

    if row.status != STATUS_COMPLETED:
        return False
    if not include_ci and row.environment == ENV_CI:
        return False
    metrics = row.layer1_metrics if layer == "layer1" else row.layer2_metrics
    return bool(metrics)


def build_run_points(
    rows: Sequence[EvalTrendRow],
    *,
    include_ci: bool = False,
) -> list[dict[str, Any]]:
    """eval_runs 行 → run 级 ``TrendPoint`` 列表（contract v4，spec 2026-09-07 §2），
    按 ``(created_at, id)`` 升序。

    读集内（任一层入集即出点）每行一点——x 轴 ``ts`` 为 ``coerce_iso``
    完整时间戳（naive 假定 UTC 补 ``+00:00``），不做周期分桶：同日多次
    运行各自出点。11 个指标键取**本 run**：L1 四取 ``layer1_metrics
    ["summary"]``（recall_at_k/hit_rate/mrr/path_accuracy）；ragas 三取
    ``layer2_metrics["ragas"]``（faithfulness/answer_relevancy/context_precision），
    引用三取 ``layer2_metrics["arch_specific"]``（citation_precision/
    citation_recall/seed_hit_rate）；路由命中率 ``routing_hit_rate`` 取
    ``layer2_metrics`` 顶层 ``path_accuracy``（真实对话链路选路口径，与 L1
    同名键不同源——展示面键名解耦防同名误读）；该层缺失则对应键 ``None``
    （前端逐序列取「该指标非空的 run」为点集，不打假缺口）。退役的
    ``context_recall`` 不进点（仅存于 ``sparks``）。``regression`` 透传本 run
    的 per-category 门禁判定（无 diff 为 ``None``）；``is_baseline_update``
    标记 ``--mark-baseline`` 打点；``run_id`` 单键（两层同源一行，退役
    ``layer1_run_id``/``layer2_run_id``）。
    """

    points: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda r: (r.created_at, r.id)):
        if not (_in_read_set(row, "layer1", include_ci=include_ci) or _in_read_set(row, "layer2", include_ci=include_ci)):
            continue
        summary = (row.layer1_metrics.get("summary") or {}) if row.layer1_metrics else {}
        ragas = (row.layer2_metrics.get("ragas") or {}) if row.layer2_metrics else {}
        arch = (row.layer2_metrics.get("arch_specific") or {}) if row.layer2_metrics else {}
        diff = row.baseline_diff
        points.append(
            {
                "ts": coerce_iso(row.created_at),
                "recall_at_k": summary.get("recall_at_k"),
                "hit_rate": summary.get("hit_rate"),
                "mrr": summary.get("mrr"),
                "path_accuracy": summary.get("path_accuracy"),
                "faithfulness": ragas.get("faithfulness"),
                "answer_relevancy": ragas.get("answer_relevancy"),
                "context_precision": ragas.get("context_precision"),
                "citation_precision": arch.get("citation_precision"),
                "citation_recall": arch.get("citation_recall"),
                "seed_hit_rate": arch.get("seed_hit_rate"),
                "routing_hit_rate": row.layer2_metrics.get("path_accuracy") if row.layer2_metrics else None,
                "run_id": row.id,
                "regression": (
                    {
                        "detected": bool(diff.get("regression_detected")),
                        "categories": list(diff.get("regressed_categories") or []),
                    }
                    if diff
                    else None
                ),
                "is_baseline_update": bool(row.is_baseline),
            }
        )
    return points


def latest_layer_row[RowT: EvalTrendRow](rows: Sequence[RowT], layer: Literal["layer1", "layer2"]) -> RowT | None:
    """该层最近一次 completed 且 metrics 非空且非 ci 的运行（latest 端点取数规则）。"""

    candidates = [row for row in rows if _in_read_set(row, layer, include_ci=False)]
    if not candidates:
        return None
    return max(candidates, key=lambda row: (row.created_at, row.id))


def build_sparks(
    rows: Sequence[EvalTrendRow],
    *,
    include_ci: bool = False,
) -> dict[str, list[float]]:
    """eval_runs 行 → 顶层 ``sparks``（spec §6.2）：8 个 Layer 2 键各一条 run 级
    近 ``MAX_SPARKS`` 个非空值序列（``created_at`` 升序）。

    与 ``build_run_points`` 同为 run 级取数，但本函数只服务瓦片 sparkline：
    每键一条近 ``MAX_SPARKS`` 个非空值升序序列，**不做窗口过滤**（由调用方
    传全量行）——与趋势固定窗口解耦（spec §6.2）。null 值（该档未跑该指标）
    被跳过而非占位；某键全 null（如 ragas 未装时的 ``context_recall``）→
    空数组。取数集合规则与趋势同源（completed + layer2 metrics 非空 +
    默认排除 ci）。
    """

    l2_rows = sorted(
        (row for row in rows if _in_read_set(row, "layer2", include_ci=include_ci)),
        key=lambda row: (row.created_at, row.id),
    )
    series: dict[str, list[float]] = {key: [] for key in SPARK_KEYS}
    for row in l2_rows:
        ragas = row.layer2_metrics.get("ragas") or {}
        arch = row.layer2_metrics.get("arch_specific") or {}
        for key in _SPARK_RAGAS_KEYS:
            value = ragas.get(key)
            if value is not None:
                series[key].append(value)
        for key in _SPARK_ARCH_KEYS:
            value = arch.get(key)
            if value is not None:
                series[key].append(value)
        for key in _SPARK_LIVE_KEYS:
            value = row.layer2_metrics.get("path_accuracy")
            if value is not None:
                series[key].append(value)
    return {key: values[-MAX_SPARKS:] for key, values in series.items()}
