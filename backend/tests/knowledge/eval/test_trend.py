"""``build_run_points`` pure-function tests (contract v4, spec 2026-09-07 §2).

run 级点语义：一个点 = 一次真实运行（x = ``coerce_iso`` 完整时间戳），不做
周期分桶——同日多次运行各自出点；skipped/error 行与 ``environment='ci'``
行（默认）不进取数集合；``regression`` 透传本 run 的 per-category 门禁判定。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from deerflow.knowledge.eval.trend import build_run_points, build_sparks


def _l1(recall_at_k: float = 0.8, hit_rate: float = 0.9, mrr: float = 0.7) -> dict:
    return {
        "summary": {
            "recall_at_k": recall_at_k,
            "hit_rate": hit_rate,
            "mrr": mrr,
            "path_accuracy": 1.0,
            "question_count": 20,
        }
    }


def _l2(faithfulness: float = 0.95, answer_relevancy: float = 0.88, context_precision: float = 0.91) -> dict:
    return {
        "ragas": {
            "faithfulness": faithfulness,
            "answer_relevancy": answer_relevancy,
            "context_precision": context_precision,
            "context_recall": None,
        },
        "arch_specific": {"citation_precision": 0.9, "citation_recall": 0.85, "seed_hit_rate": None},
        "path_accuracy": 0.75,
        "ragas_available": True,
        "has_graph_questions": False,
    }


def _row(
    run_id: str,
    created_at: datetime,
    *,
    layer1: dict | None = None,
    layer2: dict | None = None,
    status: str = "completed",
    environment: str = "local",
    baseline_diff: dict | None = None,
    is_baseline: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=run_id,
        status=status,
        environment=environment,
        layer1_metrics=layer1 if layer1 is not None else {},
        layer2_metrics=layer2 if layer2 is not None else {},
        baseline_diff=baseline_diff,
        is_baseline=is_baseline,
        created_at=created_at,
    )


# ── run 级点：一 run 一点，无周期分桶 ────────────────────────────────────


def test_same_day_runs_each_get_their_own_point() -> None:
    early = _row("run-early", datetime(2026, 8, 20, 9, 0, tzinfo=UTC), layer1=_l1(recall_at_k=0.70))
    late = _row("run-late", datetime(2026, 8, 20, 18, 30, tzinfo=UTC), layer1=_l1(recall_at_k=0.85))

    points = build_run_points([early, late])

    # 周期末次聚合退役：同日两次运行都出现，升序，各自携带自己的指标值。
    assert [p["run_id"] for p in points] == ["run-early", "run-late"]
    assert [p["recall_at_k"] for p in points] == [0.70, 0.85]


def test_points_sorted_by_created_at_regardless_of_input_order() -> None:
    late = _row("run-late", datetime(2026, 8, 20, 18, 30, tzinfo=UTC), layer1=_l1(recall_at_k=0.85))
    early = _row("run-early", datetime(2026, 8, 20, 9, 0, tzinfo=UTC), layer1=_l1(recall_at_k=0.70))

    points = build_run_points([late, early])

    assert [p["run_id"] for p in points] == ["run-early", "run-late"]


def test_ts_is_full_timestamp_with_utc_offset() -> None:
    aware = _row("run-aware", datetime(2026, 8, 20, 9, 30, tzinfo=UTC), layer1=_l1())
    # SQLite 读回剥掉时区：naive 假定 UTC 补偏移（时区标准，禁裸 isoformat）。
    # 两次独立调用：同一存储内行时区形态一致，naive/aware 不混排（同旧代码约束）。
    naive = _row("run-naive", datetime(2026, 8, 20, 9, 30), layer1=_l1())

    assert build_run_points([aware])[0]["ts"] == "2026-08-20T09:30:00+00:00"
    assert build_run_points([naive])[0]["ts"] == "2026-08-20T09:30:00+00:00"


# ── 指标键取本 run；缺层 null ───────────────────────────────────────────

_TREND_METRIC_KEYS = {
    "recall_at_k",
    "hit_rate",
    "mrr",
    "path_accuracy",
    "faithfulness",
    "answer_relevancy",
    "context_precision",
    "citation_precision",
    "citation_recall",
    "seed_hit_rate",
    "routing_hit_rate",
}


def test_run_point_exposes_eleven_metric_keys_from_its_own_run() -> None:
    row = _row("run-full", datetime(2026, 8, 20, 9, 0, tzinfo=UTC), layer1=_l1(), layer2=_l2())

    point = build_run_points([row])[0]

    assert len(_TREND_METRIC_KEYS) == 11
    assert _TREND_METRIC_KEYS <= set(point)
    # 取值口径：path_accuracy 来自本 run L1 summary；引用三来自本 run arch_specific；
    # routing_hit_rate 来自本 run layer2 顶层 path_accuracy（真实对话链路口径）
    assert point["path_accuracy"] == 1.0
    assert point["routing_hit_rate"] == 0.75
    assert point["citation_precision"] == 0.9
    assert point["citation_recall"] == 0.85
    assert point["seed_hit_rate"] is None
    assert point["run_id"] == "run-full"


def test_missing_layer_keys_are_null() -> None:
    # 仅 L1（快速档无 layer2）：ragas/引用键 null，L1 键有值
    l1_point = build_run_points([_row("run-l1", datetime(2026, 8, 20, 9, 0, tzinfo=UTC), layer1=_l1())])[0]
    assert l1_point["recall_at_k"] == 0.8
    assert l1_point["faithfulness"] is None
    assert l1_point["answer_relevancy"] is None
    assert l1_point["context_precision"] is None
    assert l1_point["citation_precision"] is None
    assert l1_point["routing_hit_rate"] is None

    # 仅 L2：L1 键 null，L2 键有值
    l2_point = build_run_points([_row("run-l2", datetime(2026, 8, 21, 9, 0, tzinfo=UTC), layer2=_l2())])[0]
    assert l2_point["recall_at_k"] is None
    assert l2_point["path_accuracy"] is None
    assert l2_point["routing_hit_rate"] == 0.75
    assert l2_point["faithfulness"] == 0.95
    assert l2_point["citation_precision"] == 0.9


# ── 取数集合过滤 ────────────────────────────────────────────────────────


def test_ci_rows_excluded_by_default_and_included_on_demand() -> None:
    local_run = _row("run-local", datetime(2026, 8, 19, 9, 0, tzinfo=UTC), layer1=_l1(recall_at_k=0.70))
    ci_run = _row("run-ci", datetime(2026, 8, 20, 9, 0, tzinfo=UTC), layer1=_l1(recall_at_k=0.99), environment="ci")

    assert [p["run_id"] for p in build_run_points([local_run, ci_run])] == ["run-local"]
    assert [p["run_id"] for p in build_run_points([local_run, ci_run], include_ci=True)] == ["run-local", "run-ci"]


def test_skipped_and_error_rows_never_enter_the_read_set() -> None:
    skipped = _row("run-skip", datetime(2026, 8, 19, 9, 0, tzinfo=UTC), layer1=_l1(), status="skipped")
    error = _row("run-err", datetime(2026, 8, 20, 9, 0, tzinfo=UTC), layer2=_l2(), status="error")

    assert build_run_points([skipped, error]) == []


def test_row_with_empty_metrics_on_both_layers_does_not_enter() -> None:
    # status=completed 但两层 metrics 均 == {} 的行不进取数集合。
    hollow = _row("run-hollow", datetime(2026, 8, 20, 9, 0, tzinfo=UTC))

    assert build_run_points([hollow]) == []


# ── regression / baseline 透传 ──────────────────────────────────────────


def test_regression_passthrough_from_own_run_baseline_diff() -> None:
    diff = {
        "recall_at_k_delta": -0.05,
        "regression_detected": True,
        "threshold_percent": 3.0,
        "regressed_categories": ["fact"],
    }
    run = _row("run-reg", datetime(2026, 8, 20, 9, 0, tzinfo=UTC), layer1=_l1(), baseline_diff=diff)

    points = build_run_points([run])

    assert points[0]["regression"] == {"detected": True, "categories": ["fact"]}


def test_regression_is_null_when_run_has_no_diff() -> None:
    run = _row("run-plain", datetime(2026, 8, 20, 9, 0, tzinfo=UTC), layer1=_l1())

    points = build_run_points([run])

    assert points[0]["regression"] is None


def test_is_baseline_update_flag_follows_the_row() -> None:
    marked = _row("run-base", datetime(2026, 8, 20, 9, 0, tzinfo=UTC), layer1=_l1(), is_baseline=True)
    plain = _row("run-plain", datetime(2026, 8, 21, 9, 0, tzinfo=UTC), layer1=_l1())

    points = build_run_points([marked, plain])

    assert [p["is_baseline_update"] for p in points] == [True, False]


def test_is_baseline_update_false_for_layer2_only_run() -> None:
    layer2_only = _row("run-l2", datetime(2026, 8, 20, 9, 0, tzinfo=UTC), layer2=_l2())

    points = build_run_points([layer2_only])

    assert points[0]["is_baseline_update"] is False


def test_empty_input_returns_empty_points() -> None:
    assert build_run_points([]) == []


# ── build_sparks：run 级近 10 非空值（spec §6.2，窗口无关，服务瓦片 sparkline） ──

_SPARK_KEYS = {
    "faithfulness",
    "answer_relevancy",
    "context_precision",
    "context_recall",
    "citation_precision",
    "citation_recall",
    "seed_hit_rate",
    "routing_hit_rate",
}


def test_sparks_returns_all_eight_l2_keys() -> None:
    sparks = build_sparks([_row("run-l2", datetime(2026, 8, 20, 9, 0, tzinfo=UTC), layer2=_l2())])

    assert set(sparks) == _SPARK_KEYS


def test_sparks_empty_input_returns_eight_empty_arrays() -> None:
    sparks = build_sparks([])

    assert set(sparks) == _SPARK_KEYS
    assert all(values == [] for values in sparks.values())


def test_sparks_maps_ragas_and_arch_specific_sources() -> None:
    layer2 = {
        "ragas": {"faithfulness": 0.9, "answer_relevancy": 0.8, "context_precision": 0.7, "context_recall": 0.6},
        "arch_specific": {"citation_precision": 0.5, "citation_recall": 0.4, "seed_hit_rate": 0.3},
        "path_accuracy": 0.35,
    }

    sparks = build_sparks([_row("run-full", datetime(2026, 8, 20, 9, 0, tzinfo=UTC), layer2=layer2)])

    assert sparks["faithfulness"] == [0.9]
    assert sparks["answer_relevancy"] == [0.8]
    assert sparks["context_precision"] == [0.7]
    assert sparks["context_recall"] == [0.6]
    assert sparks["citation_precision"] == [0.5]
    assert sparks["citation_recall"] == [0.4]
    assert sparks["seed_hit_rate"] == [0.3]
    # 路由命中率取 layer2 顶层 path_accuracy（展示面键名解耦）
    assert sparks["routing_hit_rate"] == [0.35]


def test_sparks_all_null_key_yields_empty_array() -> None:
    # 默认 _l2：context_recall（ragas 未装）与 seed_hit_rate（无实体标注）恒 null → 空数组
    sparks = build_sparks([_row("run-l2", datetime(2026, 8, 20, 9, 0, tzinfo=UTC), layer2=_l2())])

    assert sparks["context_recall"] == []
    assert sparks["seed_hit_rate"] == []
    assert sparks["faithfulness"] == [0.95]


def test_sparks_sorts_by_created_at_ascending_regardless_of_input_order() -> None:
    early = _row("run-1", datetime(2026, 8, 18, 9, 0, tzinfo=UTC), layer2=_l2(faithfulness=0.80))
    late = _row("run-2", datetime(2026, 8, 20, 9, 0, tzinfo=UTC), layer2=_l2(faithfulness=0.90))

    sparks = build_sparks([late, early])

    assert sparks["faithfulness"] == [0.80, 0.90]


def test_sparks_skips_null_runs_without_placeholder() -> None:
    r1 = _row("run-1", datetime(2026, 8, 18, 9, 0, tzinfo=UTC), layer2=_l2(faithfulness=0.70))
    r2 = _row("run-2", datetime(2026, 8, 19, 9, 0, tzinfo=UTC), layer2=_l2(faithfulness=None))
    r3 = _row("run-3", datetime(2026, 8, 20, 9, 0, tzinfo=UTC), layer2=_l2(faithfulness=0.90))

    sparks = build_sparks([r1, r2, r3])

    # run-2 的 null 被跳过（非占位），数组长度 = 非空 run 数 = 2
    assert sparks["faithfulness"] == [0.70, 0.90]


def test_sparks_length_matches_available_runs_when_under_ten() -> None:
    runs = [_row(f"run-{i}", datetime(2026, 8, 10 + i, 9, 0, tzinfo=UTC), layer2=_l2(faithfulness=0.50 + i * 0.01)) for i in range(5)]

    sparks = build_sparks(runs)

    assert len(sparks["faithfulness"]) == 5


def test_sparks_caps_at_ten_most_recent_non_null_values() -> None:
    runs = [_row(f"run-{i:02d}", datetime(2026, 7, 1, 9, 0, tzinfo=UTC) + timedelta(days=i), layer2=_l2(faithfulness=float(i))) for i in range(15)]

    sparks = build_sparks(runs)

    # 15 个非空 run → 仅保留近 10（升序，丢弃最旧 5 个）
    assert sparks["faithfulness"] == [float(i) for i in range(5, 15)]


def test_sparks_ignores_period_boundaries_single_series_across_months() -> None:
    # 跨 3 个月的 run 进同一条序列（run 级取数，与趋势固定窗口解耦）
    runs = [
        _row("run-jul", datetime(2026, 7, 15, 9, 0, tzinfo=UTC), layer2=_l2(faithfulness=0.70)),
        _row("run-aug", datetime(2026, 8, 15, 9, 0, tzinfo=UTC), layer2=_l2(faithfulness=0.80)),
        _row("run-sep", datetime(2026, 9, 15, 9, 0, tzinfo=UTC), layer2=_l2(faithfulness=0.90)),
    ]

    sparks = build_sparks(runs)

    assert sparks["faithfulness"] == [0.70, 0.80, 0.90]


def test_sparks_ignores_rows_without_layer2_data() -> None:
    l1_only = _row("run-l1", datetime(2026, 8, 20, 9, 0, tzinfo=UTC), layer1=_l1())

    sparks = build_sparks([l1_only])

    assert sparks["faithfulness"] == []


def test_sparks_excludes_ci_by_default_and_includes_on_demand() -> None:
    local = _row("run-local", datetime(2026, 8, 19, 9, 0, tzinfo=UTC), layer2=_l2(faithfulness=0.70))
    ci = _row("run-ci", datetime(2026, 8, 20, 9, 0, tzinfo=UTC), layer2=_l2(faithfulness=0.99), environment="ci")

    assert build_sparks([local, ci])["faithfulness"] == [0.70]
    assert build_sparks([local, ci], include_ci=True)["faithfulness"] == [0.70, 0.99]
