"""Tests for memory retrieval metrics computation."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from deerflow.agents.memory.metrics import RetrievalMetrics, compute_retrieval_metrics


def _write_traces(path: Path, traces: list[dict]) -> None:
    """Helper: write trace dicts as JSONL lines."""
    with path.open("w", encoding="utf-8") as fh:
        for trace in traces:
            fh.write(json.dumps(trace, ensure_ascii=False) + "\n")


def _make_trace(
    *,
    max_tokens: int = 2000,
    tokens_used: int = 1000,
    total_candidates: int = 10,
    selected_count: int = 7,
    dropped_count: int = 3,
    candidates: list[dict] | None = None,
    selections: list[dict] | None = None,
) -> dict:
    """Helper: build a minimal trace dict with sensible defaults."""
    return {
        "trace_id": "test",
        "timestamp": "2026-04-13T00:00:00Z",
        "agent_name": None,
        "max_tokens": max_tokens,
        "tokens_used": tokens_used,
        "tokens_remaining": max_tokens - tokens_used,
        "total_candidates": total_candidates,
        "selected_count": selected_count,
        "dropped_count": dropped_count,
        "candidates": candidates or [],
        "selections": selections or [],
        "user_context_included": False,
        "history_sections_included": [],
        "context_tokens": 0,
    }


def test_compute_metrics_basic(tmp_path) -> None:
    trace_file = tmp_path / "traces.jsonl"
    _write_traces(
        trace_file,
        [
            _make_trace(max_tokens=2000, tokens_used=1000, total_candidates=10, dropped_count=3),
            _make_trace(max_tokens=2000, tokens_used=1600, total_candidates=10, dropped_count=5),
        ],
    )

    metrics = compute_retrieval_metrics(trace_path=trace_file, window=50)

    assert metrics.window_size == 2
    assert metrics.trace_count == 2
    # budget_utilization: avg(1000/2000, 1600/2000) = avg(0.5, 0.8) = 0.65
    assert abs(metrics.budget_utilization - 0.65) < 1e-9
    # drop_rate: avg(3/10, 5/10) = avg(0.3, 0.5) = 0.4
    assert abs(metrics.drop_rate - 0.4) < 1e-9
    assert metrics.correction_hit_rate == 0.0
    assert metrics.category_distribution == {}
    assert metrics.staleness_ratio == 0.0
    assert metrics.confidence_floor == 0.0


def test_compute_metrics_empty_file(tmp_path) -> None:
    trace_file = tmp_path / "traces.jsonl"
    trace_file.write_text("", encoding="utf-8")

    metrics = compute_retrieval_metrics(trace_path=trace_file, window=50)

    assert metrics == RetrievalMetrics(
        budget_utilization=0.0,
        drop_rate=0.0,
        correction_hit_rate=0.0,
        category_distribution={},
        staleness_ratio=0.0,
        confidence_floor=0.0,
        window_size=0,
        trace_count=0,
    )


def test_compute_metrics_file_not_exists(tmp_path) -> None:
    non_existent = tmp_path / "does_not_exist.jsonl"

    metrics = compute_retrieval_metrics(trace_path=non_existent, window=50)

    assert metrics.window_size == 0
    assert metrics.trace_count == 0


def test_compute_metrics_window_larger_than_traces(tmp_path) -> None:
    trace_file = tmp_path / "traces.jsonl"
    _write_traces(trace_file, [_make_trace()])

    metrics = compute_retrieval_metrics(trace_path=trace_file, window=100)

    assert metrics.window_size == 1
    assert metrics.trace_count == 1


def test_compute_metrics_zero_max_tokens(tmp_path) -> None:
    """max_tokens=0 should not cause ZeroDivisionError."""
    trace_file = tmp_path / "traces.jsonl"
    _write_traces(trace_file, [_make_trace(max_tokens=0, tokens_used=0)])

    metrics = compute_retrieval_metrics(trace_path=trace_file, window=50)

    assert metrics.budget_utilization == 0.0
    assert metrics.window_size == 1


def test_compute_metrics_zero_candidates(tmp_path) -> None:
    """total_candidates=0 should not cause ZeroDivisionError."""
    trace_file = tmp_path / "traces.jsonl"
    _write_traces(
        trace_file,
        [_make_trace(total_candidates=0, selected_count=0, dropped_count=0)],
    )

    metrics = compute_retrieval_metrics(trace_path=trace_file, window=50)

    assert metrics.drop_rate == 0.0


def test_compute_metrics_no_corrections(tmp_path) -> None:
    """When no correction facts exist, correction_hit_rate is 0.0."""
    trace_file = tmp_path / "traces.jsonl"
    _write_traces(
        trace_file,
        [
            _make_trace(
                candidates=[{"fact_id": "f1", "category": "knowledge", "content_preview": "x", "confidence": 0.9, "layer": None, "created_at": None}],
                selections=[{"fact_id": "f1", "included": True, "reason": "selected", "rank_position": 0, "token_cost": 10, "score_components": {}}],
            )
        ],
    )

    metrics = compute_retrieval_metrics(trace_path=trace_file, window=50)

    assert metrics.correction_hit_rate == 0.0


def test_compute_metrics_correction_hit_rate(tmp_path) -> None:
    """Verify correction_hit_rate across multiple traces."""
    trace_file = tmp_path / "traces.jsonl"
    _write_traces(
        trace_file,
        [
            _make_trace(
                candidates=[
                    {"fact_id": "c1", "category": "correction", "content_preview": "fix A", "confidence": 0.95, "layer": None, "created_at": None},
                    {"fact_id": "c2", "category": "correction", "content_preview": "fix B", "confidence": 0.90, "layer": None, "created_at": None},
                    {"fact_id": "k1", "category": "knowledge", "content_preview": "fact", "confidence": 0.80, "layer": None, "created_at": None},
                ],
                selections=[
                    {"fact_id": "c1", "included": True, "reason": "selected", "rank_position": 0, "token_cost": 10, "score_components": {}},
                    {"fact_id": "c2", "included": False, "reason": "budget_exceeded", "rank_position": 1, "token_cost": 10, "score_components": {}},
                    {"fact_id": "k1", "included": True, "reason": "selected", "rank_position": 2, "token_cost": 10, "score_components": {}},
                ],
            ),
            _make_trace(
                candidates=[
                    {"fact_id": "c3", "category": "correction", "content_preview": "fix C", "confidence": 0.95, "layer": None, "created_at": None},
                ],
                selections=[
                    {"fact_id": "c3", "included": True, "reason": "selected", "rank_position": 0, "token_cost": 10, "score_components": {}},
                ],
            ),
        ],
    )

    metrics = compute_retrieval_metrics(trace_path=trace_file, window=50)

    # Total corrections: c1 + c2 + c3 = 3
    # Selected corrections: c1 + c3 = 2
    # correction_hit_rate: 2/3
    assert abs(metrics.correction_hit_rate - 2 / 3) < 1e-9


def test_compute_metrics_uses_last_n_traces(tmp_path) -> None:
    """Only the last N traces should be used when window < total."""
    trace_file = tmp_path / "traces.jsonl"
    # Write 3 traces; the first has 100% budget, the last two have 50%.
    _write_traces(
        trace_file,
        [
            _make_trace(max_tokens=1000, tokens_used=1000),  # will be outside window
            _make_trace(max_tokens=1000, tokens_used=500),
            _make_trace(max_tokens=1000, tokens_used=500),
        ],
    )

    metrics = compute_retrieval_metrics(trace_path=trace_file, window=2)

    assert metrics.window_size == 2
    assert metrics.trace_count == 3
    # Only the last 2 traces: avg(500/1000, 500/1000) = 0.5
    assert abs(metrics.budget_utilization - 0.5) < 1e-9


def test_compute_metrics_default_path(tmp_path, monkeypatch) -> None:
    """When trace_path is None, resolve_trace_path() is used."""
    trace_file = tmp_path / "retrieval_traces.jsonl"
    _write_traces(trace_file, [_make_trace()])
    monkeypatch.setattr(
        "deerflow.agents.memory.metrics.resolve_trace_path",
        lambda: trace_file,
    )

    metrics = compute_retrieval_metrics(trace_path=None, window=50)

    assert metrics.window_size == 1


def test_compute_metrics_malformed_line_skipped(tmp_path) -> None:
    """Malformed JSONL lines should be silently skipped."""
    trace_file = tmp_path / "traces.jsonl"
    good_trace = _make_trace(max_tokens=1000, tokens_used=700)
    with trace_file.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps(good_trace) + "\n")
        fh.write("THIS IS NOT VALID JSON\n")
        fh.write(json.dumps(good_trace) + "\n")

    metrics = compute_retrieval_metrics(trace_path=trace_file, window=50)

    assert metrics.window_size == 2
    assert metrics.trace_count == 3  # 3 non-empty lines (including the bad one)
    assert abs(metrics.budget_utilization - 0.7) < 1e-9


# --- Tests for the 3 new metrics ---


def test_compute_metrics_category_distribution(tmp_path) -> None:
    """Verify that selected facts are correctly grouped by category."""
    trace_file = tmp_path / "traces.jsonl"
    _write_traces(
        trace_file,
        [
            _make_trace(
                candidates=[
                    {"fact_id": "f1", "category": "knowledge", "content_preview": "x", "confidence": 0.9, "layer": None, "created_at": None},
                    {"fact_id": "f2", "category": "preference", "content_preview": "y", "confidence": 0.8, "layer": None, "created_at": None},
                    {"fact_id": "f3", "category": "knowledge", "content_preview": "z", "confidence": 0.7, "layer": None, "created_at": None},
                    {"fact_id": "f4", "category": "correction", "content_preview": "w", "confidence": 0.95, "layer": None, "created_at": None},
                ],
                selections=[
                    {"fact_id": "f1", "included": True, "reason": "selected", "rank_position": 0, "token_cost": 10, "score_components": {}},
                    {"fact_id": "f2", "included": True, "reason": "selected", "rank_position": 1, "token_cost": 10, "score_components": {}},
                    {"fact_id": "f3", "included": True, "reason": "selected", "rank_position": 2, "token_cost": 10, "score_components": {}},
                    {"fact_id": "f4", "included": False, "reason": "budget_exceeded", "rank_position": 3, "token_cost": 10, "score_components": {}},
                ],
            ),
        ],
    )

    metrics = compute_retrieval_metrics(trace_path=trace_file, window=50)

    assert metrics.category_distribution == {"knowledge": 2, "preference": 1}


def test_compute_metrics_staleness_ratio(tmp_path) -> None:
    """Facts older than staleness_days should count as stale."""
    now = datetime.now(UTC)
    old_date = (now - timedelta(days=60)).isoformat()
    recent_date = (now - timedelta(days=5)).isoformat()

    trace_file = tmp_path / "traces.jsonl"
    _write_traces(
        trace_file,
        [
            _make_trace(
                candidates=[
                    {"fact_id": "old", "category": "knowledge", "content_preview": "x", "confidence": 0.9, "layer": None, "created_at": old_date},
                    {"fact_id": "new", "category": "knowledge", "content_preview": "y", "confidence": 0.8, "layer": None, "created_at": recent_date},
                    {"fact_id": "no_date", "category": "knowledge", "content_preview": "z", "confidence": 0.7, "layer": None, "created_at": None},
                ],
                selections=[
                    {"fact_id": "old", "included": True, "reason": "selected", "rank_position": 0, "token_cost": 10, "score_components": {}},
                    {"fact_id": "new", "included": True, "reason": "selected", "rank_position": 1, "token_cost": 10, "score_components": {}},
                    {"fact_id": "no_date", "included": True, "reason": "selected", "rank_position": 2, "token_cost": 10, "score_components": {}},
                ],
            ),
        ],
    )

    metrics = compute_retrieval_metrics(trace_path=trace_file, window=50, staleness_days=30)

    # 2 facts have dates: "old" (60d) is stale, "new" (5d) is fresh. "no_date" skipped.
    # staleness_ratio = 1/2 = 0.5
    assert abs(metrics.staleness_ratio - 0.5) < 1e-9


def test_compute_metrics_staleness_ratio_no_dates(tmp_path) -> None:
    """When no selected facts have created_at, staleness_ratio is 0.0."""
    trace_file = tmp_path / "traces.jsonl"
    _write_traces(
        trace_file,
        [
            _make_trace(
                candidates=[
                    {"fact_id": "f1", "category": "knowledge", "content_preview": "x", "confidence": 0.9, "layer": None, "created_at": None},
                ],
                selections=[
                    {"fact_id": "f1", "included": True, "reason": "selected", "rank_position": 0, "token_cost": 10, "score_components": {}},
                ],
            ),
        ],
    )

    metrics = compute_retrieval_metrics(trace_path=trace_file, window=50)

    assert metrics.staleness_ratio == 0.0


def test_compute_metrics_confidence_floor(tmp_path) -> None:
    """confidence_floor should be the lowest confidence among selected facts."""
    trace_file = tmp_path / "traces.jsonl"
    _write_traces(
        trace_file,
        [
            _make_trace(
                candidates=[
                    {"fact_id": "f1", "category": "knowledge", "content_preview": "x", "confidence": 0.95, "layer": None, "created_at": None},
                    {"fact_id": "f2", "category": "knowledge", "content_preview": "y", "confidence": 0.60, "layer": None, "created_at": None},
                    {"fact_id": "f3", "category": "knowledge", "content_preview": "z", "confidence": 0.40, "layer": None, "created_at": None},
                ],
                selections=[
                    {"fact_id": "f1", "included": True, "reason": "selected", "rank_position": 0, "token_cost": 10, "score_components": {}},
                    {"fact_id": "f2", "included": True, "reason": "selected", "rank_position": 1, "token_cost": 10, "score_components": {}},
                    {"fact_id": "f3", "included": False, "reason": "budget_exceeded", "rank_position": 2, "token_cost": 10, "score_components": {}},
                ],
            ),
        ],
    )

    metrics = compute_retrieval_metrics(trace_path=trace_file, window=50)

    # f1 (0.95) and f2 (0.60) are selected. f3 (0.40) is dropped.
    # confidence_floor = 0.60
    assert abs(metrics.confidence_floor - 0.60) < 1e-9


def test_compute_metrics_confidence_floor_no_selected(tmp_path) -> None:
    """When no facts are selected, confidence_floor is 0.0."""
    trace_file = tmp_path / "traces.jsonl"
    _write_traces(trace_file, [_make_trace()])

    metrics = compute_retrieval_metrics(trace_path=trace_file, window=50)

    assert metrics.confidence_floor == 0.0
