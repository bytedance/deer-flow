from deerflow.agents.memory.eval.comparator import MetricsComparator
from deerflow.agents.memory.eval.types import ComparisonResult, RankedFact, ReplayResult


def _make_ranked_fact(**overrides) -> RankedFact:
    defaults = {
        "fact_id": "f1",
        "category": "knowledge",
        "original_rank": 0,
        "new_rank": 0,
        "score": 0.9,
        "score_components": {"confidence": 0.9},
        "included": True,
        "token_cost": 10,
    }
    defaults.update(overrides)
    return RankedFact(**defaults)


def _make_replay_result(**overrides) -> ReplayResult:
    defaults = {
        "trace_id": "t1",
        "strategy_name": "confidence_only",
        "ranked_facts": [_make_ranked_fact()],
        "selected_count": 1,
        "dropped_count": 0,
        "tokens_used": 10,
        "tokens_remaining": 1990,
    }
    defaults.update(overrides)
    return ReplayResult(**defaults)


def test_compare_produces_deltas() -> None:
    baseline = _make_replay_result(
        strategy_name="confidence_only",
        tokens_used=1000,
        tokens_remaining=1000,
    )
    comparison = _make_replay_result(
        strategy_name="multi_signal",
        tokens_used=1600,
        tokens_remaining=400,
    )
    all_results = {
        "confidence_only": [baseline],
        "multi_signal": [comparison],
    }

    comparator = MetricsComparator(baseline_name="confidence_only")
    comparisons = comparator.compare(all_results)

    assert len(comparisons) == 1
    assert "budget_utilization" in comparisons[0].deltas
    expected_delta = comparisons[0].comparison_metrics["budget_utilization"] - comparisons[0].baseline_metrics["budget_utilization"]
    assert abs(comparisons[0].deltas["budget_utilization"] - expected_delta) < 1e-9


def test_compare_multiple_traces() -> None:
    baseline_t1 = _make_replay_result(trace_id="t1", strategy_name="confidence_only")
    baseline_t2 = _make_replay_result(trace_id="t2", strategy_name="confidence_only")
    comp_t1 = _make_replay_result(trace_id="t1", strategy_name="multi_signal")
    comp_t2 = _make_replay_result(trace_id="t2", strategy_name="multi_signal")
    all_results = {
        "confidence_only": [baseline_t1, baseline_t2],
        "multi_signal": [comp_t1, comp_t2],
    }

    comparator = MetricsComparator(baseline_name="confidence_only")
    comparisons = comparator.compare(all_results)

    assert len(comparisons) == 2


def test_summarize_averages_deltas() -> None:
    cr1 = ComparisonResult(
        trace_id="t1",
        baseline_strategy="confidence_only",
        comparison_strategy="multi_signal",
        baseline_metrics={"budget_utilization": 0.5},
        comparison_metrics={"budget_utilization": 0.7},
        deltas={"budget_utilization": 0.2},
    )
    cr2 = ComparisonResult(
        trace_id="t2",
        baseline_strategy="confidence_only",
        comparison_strategy="multi_signal",
        baseline_metrics={"budget_utilization": 0.4},
        comparison_metrics={"budget_utilization": 0.6},
        deltas={"budget_utilization": 0.2},
    )

    comparator = MetricsComparator(baseline_name="confidence_only")
    summary = comparator.summarize([cr1, cr2])

    assert abs(summary["budget_utilization"] - 0.2) < 1e-9


def test_compare_single_strategy_no_output() -> None:
    baseline = _make_replay_result(strategy_name="confidence_only")
    all_results = {"confidence_only": [baseline]}

    comparator = MetricsComparator(baseline_name="confidence_only")
    comparisons = comparator.compare(all_results)

    assert comparisons == []


def test_selection_overlap_metric() -> None:
    f1 = _make_ranked_fact(fact_id="f1", included=True)
    f2_base = _make_ranked_fact(fact_id="f2", included=True)
    f2_comp = _make_ranked_fact(fact_id="f2", included=True)
    f3 = _make_ranked_fact(fact_id="f3", included=True)

    baseline = _make_replay_result(
        strategy_name="confidence_only",
        ranked_facts=[f1, f2_base],
        selected_count=2,
    )
    comparison = _make_replay_result(
        strategy_name="multi_signal",
        ranked_facts=[f2_comp, f3],
        selected_count=2,
    )
    all_results = {
        "confidence_only": [baseline],
        "multi_signal": [comparison],
    }

    comparator = MetricsComparator(baseline_name="confidence_only")
    comparisons = comparator.compare(all_results)

    assert len(comparisons) == 1
    overlap = comparisons[0].baseline_metrics["selection_overlap"]
    assert 0.0 <= overlap <= 1.0
    assert abs(overlap - (1 / 3)) < 1e-9
