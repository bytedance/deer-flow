import json
from pathlib import Path

from deerflow.agents.memory.eval.replay import ReplayEvaluator
from deerflow.agents.memory.eval.strategies import ConfidenceOnlyStrategy


def _write_traces(path: Path, traces: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for trace in traces:
            fh.write(json.dumps(trace, ensure_ascii=False) + "\n")


def _make_eval_trace(**overrides) -> dict:
    defaults = {
        "trace_id": "t1",
        "timestamp": "2026-04-13T00:00:00Z",
        "agent_name": None,
        "max_tokens": 2000,
        "tokens_used": 0,
        "tokens_remaining": 2000,
        "total_candidates": 3,
        "selected_count": 0,
        "dropped_count": 0,
        "candidates": [
            {"fact_id": "f1", "content_preview": "x" * 40, "category": "knowledge", "confidence": 0.9, "layer": None, "created_at": None},
            {"fact_id": "f2", "content_preview": "y" * 40, "category": "preference", "confidence": 0.7, "layer": None, "created_at": None},
            {"fact_id": "f3", "content_preview": "z" * 40, "category": "correction", "confidence": 0.8, "layer": None, "created_at": None},
        ],
        "selections": [],
        "user_context_included": False,
        "history_sections_included": [],
        "context_tokens": 0,
    }
    defaults.update(overrides)
    return defaults


def test_replay_single_trace_single_strategy(tmp_path: Path) -> None:
    trace_path = tmp_path / "traces.jsonl"
    _write_traces(trace_path, [_make_eval_trace()])

    evaluator = ReplayEvaluator([ConfidenceOnlyStrategy()], baseline="confidence_only")
    results = evaluator.evaluate(trace_path)

    assert "confidence_only" in results
    assert len(results["confidence_only"]) == 1
    assert results["confidence_only"][0].trace_id == "t1"
    assert results["confidence_only"][0].selected_count > 0


def test_replay_multiple_traces(tmp_path: Path) -> None:
    trace_path = tmp_path / "traces.jsonl"
    traces = [_make_eval_trace(trace_id=f"t{i}") for i in range(1, 4)]
    _write_traces(trace_path, traces)

    evaluator = ReplayEvaluator([ConfidenceOnlyStrategy()], baseline="confidence_only")
    results = evaluator.evaluate(trace_path)

    assert len(results["confidence_only"]) == 3


def test_replay_empty_file(tmp_path: Path) -> None:
    trace_path = tmp_path / "empty.jsonl"
    trace_path.write_text("", encoding="utf-8")

    evaluator = ReplayEvaluator([ConfidenceOnlyStrategy()], baseline="confidence_only")
    results = evaluator.evaluate(trace_path)

    assert results == {}


def test_replay_malformed_lines_skipped(tmp_path: Path) -> None:
    trace_path = tmp_path / "traces.jsonl"
    with trace_path.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps(_make_eval_trace(trace_id="t1")) + "\n")
        fh.write("THIS IS NOT JSON\n")
        fh.write(json.dumps(_make_eval_trace(trace_id="t2")) + "\n")

    evaluator = ReplayEvaluator([ConfidenceOnlyStrategy()], baseline="confidence_only")
    results = evaluator.evaluate(trace_path)

    assert len(results["confidence_only"]) == 2


def test_replay_window_limits_traces(tmp_path: Path) -> None:
    trace_path = tmp_path / "traces.jsonl"
    traces = [_make_eval_trace(trace_id=f"t{i}") for i in range(1, 6)]
    _write_traces(trace_path, traces)

    evaluator = ReplayEvaluator([ConfidenceOnlyStrategy()], baseline="confidence_only")
    results = evaluator.evaluate(trace_path, window=2)

    assert len(results["confidence_only"]) == 2


def test_replay_trace_zero_candidates(tmp_path: Path) -> None:
    trace_path = tmp_path / "traces.jsonl"
    _write_traces(trace_path, [_make_eval_trace(candidates=[])])

    evaluator = ReplayEvaluator([ConfidenceOnlyStrategy()], baseline="confidence_only")
    results = evaluator.evaluate(trace_path)

    assert results["confidence_only"] == []
