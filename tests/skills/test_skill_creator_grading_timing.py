"""Malformed optional grading durations must not abort benchmark aggregation."""

import json
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "skills/public/skill-creator/scripts/aggregate_benchmark.py"
)


def write_run(root, number, grading_timing, duration=12.5):
    directory = root / "eval-1" / "with_skill" / f"run-{number}"
    directory.mkdir(parents=True)
    (directory / "grading.json").write_text(
        json.dumps(
            {
                "summary": {"pass_rate": 1.0, "passed": 1, "failed": 0, "total": 1},
                "timing": grading_timing,
            }
        ),
        encoding="utf-8",
    )
    if duration is not None:
        (directory / "timing.json").write_text(
            json.dumps({"total_duration_seconds": duration, "total_tokens": 100}),
            encoding="utf-8",
        )
    return directory


@pytest.mark.parametrize("layout", ["workspace", "legacy"])
@pytest.mark.parametrize(
    "grading_timing",
    [
        None,
        [],
        "timing",
        {"total_duration_seconds": None},
        {"total_duration_seconds": "12.5"},
        {"total_duration_seconds": True},
        {"total_duration_seconds": -1},
        {"total_duration_seconds": float("nan")},
        {"total_duration_seconds": float("inf")},
    ],
)
@pytest.mark.parametrize("fallback", [12.5, None])
def test_invalid_grading_timing_uses_available_fallback(
    tmp_path, capsys, layout, grading_timing, fallback
):
    root = tmp_path / "runs" if layout == "legacy" else tmp_path
    directory = write_run(root, 1, grading_timing, fallback)
    write_run(root, 2, {"total_duration_seconds": 20.0})
    module = runpy.run_path(str(SCRIPT))

    benchmark = module["generate_benchmark"](tmp_path)

    runs = {run["run_number"]: run["result"] for run in benchmark["runs"]}
    expected = fallback if fallback is not None else 0.0
    assert runs[1]["time_seconds"] == expected
    assert runs[2]["time_seconds"] == 20.0
    assert runs[1]["tokens"] == (100 if fallback is not None else 0)
    assert (
        benchmark["run_summary"]["with_skill"]["time_seconds"]["mean"]
        == (expected + 20.0) / 2
    )
    json.dumps(benchmark, allow_nan=False)
    assert "| Time |" in module["generate_markdown"](benchmark)
    warnings = capsys.readouterr().out
    if grading_timing == {"total_duration_seconds": None}:
        assert warnings == ""
    else:
        assert "Warning:" in warnings
        assert str(directory / "grading.json") in warnings


@pytest.mark.parametrize("duration", [0, 0.0, 5, 5.5])
def test_valid_grading_duration_keeps_precedence(tmp_path, capsys, duration):
    write_run(tmp_path, 1, {"total_duration_seconds": duration})
    module = runpy.run_path(str(SCRIPT))

    benchmark = module["generate_benchmark"](tmp_path)

    assert benchmark["runs"][0]["result"]["time_seconds"] == (
        duration if duration else 12.5
    )
    assert capsys.readouterr().out == ""


def test_cli_writes_reports_after_null_grading_duration(tmp_path):
    write_run(tmp_path, 1, {"total_duration_seconds": None})

    result = subprocess.run(
        [sys.executable, "-B", str(SCRIPT), str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    benchmark = json.loads((tmp_path / "benchmark.json").read_text(encoding="utf-8"))
    assert benchmark["runs"][0]["result"]["time_seconds"] == 12.5
    assert "12.5s" in (tmp_path / "benchmark.md").read_text(encoding="utf-8")
