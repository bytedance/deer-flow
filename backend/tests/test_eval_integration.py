import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from deerflow.agents.memory.eval.comparator import MetricsComparator
from deerflow.agents.memory.eval.feedback import PlaceholderCorrelator
from deerflow.agents.memory.eval.formatters import get_formatter
from deerflow.agents.memory.eval.replay import ReplayEvaluator
from deerflow.agents.memory.eval.strategies import ConfidenceOnlyStrategy, MultiSignalStrategy


def _write_traces(path: Path, traces: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for trace in traces:
            fh.write(json.dumps(trace, ensure_ascii=False) + "\n")


_REF_TIME = datetime(2026, 4, 14, tzinfo=UTC)


def _make_realistic_trace(trace_id: str, num_candidates: int = 5) -> dict:
    categories = ["knowledge", "correction", "preference", "context", "behavior"]
    candidates = []
    for i in range(num_candidates):
        cat = categories[i % len(categories)]
        created_at = None
        if i % 3 != 0:
            created_at = (_REF_TIME - timedelta(days=i * 10 + 1)).isoformat()
        candidates.append(
            {
                "fact_id": f"{trace_id}_f{i}",
                "content_preview": f"Fact content number {i} for trace {trace_id}" + "x" * 20,
                "category": cat,
                "confidence": round(0.5 + (i % 5) * 0.1, 2),
                "layer": "core" if i % 2 == 0 else None,
                "created_at": created_at,
            }
        )
    return {
        "trace_id": trace_id,
        "timestamp": "2026-04-13T00:00:00Z",
        "agent_name": None,
        "max_tokens": 200,
        "tokens_used": 100,
        "tokens_remaining": 100,
        "total_candidates": num_candidates,
        "selected_count": num_candidates - 1,
        "dropped_count": 1,
        "candidates": candidates,
        "selections": [],
        "user_context_included": False,
        "history_sections_included": [],
        "context_tokens": 0,
    }


def test_full_pipeline_jsonl_to_terminal_output(tmp_path: Path) -> None:
    trace_path = tmp_path / "traces.jsonl"
    _write_traces(trace_path, [_make_realistic_trace(tid) for tid in ("t1", "t2", "t3")])

    strategies = [
        ConfidenceOnlyStrategy(),
        MultiSignalStrategy(reference_time=_REF_TIME),
    ]
    evaluator = ReplayEvaluator(strategies=strategies, baseline="confidence_only")
    results = evaluator.evaluate(trace_path)

    comparator = MetricsComparator(baseline_name="confidence_only")
    comparisons = comparator.compare(results)

    formatter = get_formatter("terminal")
    output = formatter.format(comparisons)

    assert isinstance(output, str)
    assert output
    assert "budget_utilization" in output


def test_full_pipeline_json_output_valid(tmp_path: Path) -> None:
    trace_path = tmp_path / "traces.jsonl"
    _write_traces(trace_path, [_make_realistic_trace(tid) for tid in ("t1", "t2", "t3")])

    strategies = [
        ConfidenceOnlyStrategy(),
        MultiSignalStrategy(reference_time=_REF_TIME),
    ]
    evaluator = ReplayEvaluator(strategies=strategies, baseline="confidence_only")
    results = evaluator.evaluate(trace_path)

    comparator = MetricsComparator(baseline_name="confidence_only")
    comparisons = comparator.compare(results)

    formatter = get_formatter("json")
    output = formatter.format(comparisons)

    parsed = json.loads(output)
    assert isinstance(parsed["comparisons"], list)
    for entry in parsed["comparisons"]:
        assert "trace_id" in entry
        assert "baseline_strategy" in entry
        assert "comparison_strategy" in entry


def test_full_pipeline_markdown_output_valid(tmp_path: Path) -> None:
    trace_path = tmp_path / "traces.jsonl"
    _write_traces(trace_path, [_make_realistic_trace(tid) for tid in ("t1", "t2", "t3")])

    strategies = [
        ConfidenceOnlyStrategy(),
        MultiSignalStrategy(reference_time=_REF_TIME),
    ]
    evaluator = ReplayEvaluator(strategies=strategies, baseline="confidence_only")
    results = evaluator.evaluate(trace_path)

    comparator = MetricsComparator(baseline_name="confidence_only")
    comparisons = comparator.compare(results)

    formatter = get_formatter("markdown")
    output = formatter.format(comparisons)

    assert "# Evaluation Report" in output
    assert "|" in output


def test_pipeline_with_missing_fields_graceful(tmp_path: Path) -> None:
    trace_path = tmp_path / "traces.jsonl"
    trace = _make_realistic_trace("t1", num_candidates=5)
    for candidate in trace["candidates"]:
        candidate["created_at"] = None
        candidate["layer"] = None
    _write_traces(trace_path, [trace])

    strategies = [
        ConfidenceOnlyStrategy(),
        MultiSignalStrategy(reference_time=_REF_TIME),
    ]
    evaluator = ReplayEvaluator(strategies=strategies, baseline="confidence_only")
    results = evaluator.evaluate(trace_path)

    comparator = MetricsComparator(baseline_name="confidence_only")
    comparisons = comparator.compare(results)

    formatter = get_formatter("terminal")
    output = formatter.format(comparisons)

    assert isinstance(output, str)
    assert output


def test_feedback_stub_not_in_pipeline() -> None:
    correlator = PlaceholderCorrelator()
    with pytest.raises(NotImplementedError):
        correlator.correlate([], [])
    with pytest.raises(NotImplementedError):
        correlator.load_feedback(Path("/dummy"))


def test_cli_subprocess_all_formats(tmp_path: Path) -> None:
    trace_file = tmp_path / "traces.jsonl"
    _write_traces(trace_file, [_make_realistic_trace("t1")])

    for fmt in ["terminal", "json", "md"]:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "deerflow.agents.memory.eval",
                "replay",
                "--trace-path",
                str(trace_file),
                "--format",
                fmt,
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Failed for format {fmt}: {result.stderr}"
