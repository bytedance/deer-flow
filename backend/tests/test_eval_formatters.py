import json

import pytest

from deerflow.agents.memory.eval.formatters import get_formatter
from deerflow.agents.memory.eval.types import ComparisonResult


def _make_comparison(**overrides) -> ComparisonResult:
    defaults = {
        "trace_id": "t1",
        "baseline_strategy": "confidence_only",
        "comparison_strategy": "multi_signal",
        "baseline_metrics": {
            "budget_utilization": 0.5,
            "drop_rate": 0.3,
            "correction_hit_rate": 0.0,
            "selection_overlap": 0.6,
            "rank_correlation": 0.7,
        },
        "comparison_metrics": {
            "budget_utilization": 0.6,
            "drop_rate": 0.2,
            "correction_hit_rate": 0.5,
            "selection_overlap": 0.6,
            "rank_correlation": 0.7,
        },
        "deltas": {
            "budget_utilization": 0.1,
            "drop_rate": -0.1,
            "correction_hit_rate": 0.5,
            "selection_overlap": 0.0,
            "rank_correlation": 0.0,
        },
    }
    defaults.update(overrides)
    return ComparisonResult(**defaults)


def test_json_formatter_valid_json() -> None:
    results = [_make_comparison()]
    formatter = get_formatter("json")
    output = formatter.format(results)

    json.loads(output)


def test_json_formatter_structure() -> None:
    formatter = get_formatter("json")
    output = formatter.format([_make_comparison()])
    parsed = json.loads(output)

    assert "comparisons" in parsed
    assert len(parsed["comparisons"]) == 1
    entry = parsed["comparisons"][0]
    assert "trace_id" in entry
    assert "baseline_strategy" in entry
    assert "comparison_strategy" in entry
    assert "baseline_metrics" in entry
    assert "comparison_metrics" in entry
    assert "deltas" in entry


def test_markdown_formatter_has_header() -> None:
    formatter = get_formatter("markdown")
    output = formatter.format([_make_comparison()])

    assert "# Evaluation Report" in output


def test_markdown_formatter_has_table() -> None:
    formatter = get_formatter("markdown")
    output = formatter.format([_make_comparison()])

    assert "|" in output
    assert "---" in output


def test_terminal_formatter_produces_output() -> None:
    formatter = get_formatter("terminal")
    output = formatter.format([_make_comparison()])

    assert len(output) > 0


def test_get_formatter_unknown_raises() -> None:
    with pytest.raises(ValueError, match="Unknown format"):
        get_formatter("xml")


def test_get_formatter_md_alias() -> None:
    md_fmt = get_formatter("md")
    markdown_fmt = get_formatter("markdown")

    assert type(md_fmt) is type(markdown_fmt)
