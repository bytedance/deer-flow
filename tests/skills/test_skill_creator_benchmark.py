"""Regressions for skill-creator benchmark measurements."""

import json
import runpy
from pathlib import Path

import pytest


@pytest.fixture
def benchmark_script():
    script = (
        Path(__file__).resolve().parents[2]
        / "skills/public/skill-creator/scripts/aggregate_benchmark.py"
    )
    return runpy.run_path(str(script))


def write_run(root, *, grading_timing=None, timing=None, config="with_skill"):
    run_dir = root / "eval-1" / config / "run-1"
    run_dir.mkdir(parents=True)
    grading = {
        "summary": {"pass_rate": 1.0, "passed": 1, "failed": 0, "total": 1},
        "execution_metrics": {"output_chars": 12450},
    }
    if grading_timing is not None:
        grading["timing"] = grading_timing
    (run_dir / "grading.json").write_text(json.dumps(grading), encoding="utf-8")
    if timing is not None:
        (run_dir / "timing.json").write_text(json.dumps(timing), encoding="utf-8")
    return run_dir


def test_recorded_tokens_used_when_grading_already_has_duration(
    tmp_path, benchmark_script
):
    write_run(
        tmp_path,
        grading_timing={"total_duration_seconds": 23.3},
        timing={"total_duration_seconds": 25.0, "total_tokens": 84852},
    )

    benchmark = benchmark_script["generate_benchmark"](tmp_path)

    assert benchmark["runs"][0]["result"]["tokens"] == 84852
    assert benchmark["runs"][0]["result"]["time_seconds"] == 23.3
    assert benchmark["run_summary"]["with_skill"]["tokens"]["mean"] == 84852


@pytest.mark.parametrize("layout", ["workspace", "legacy"])
@pytest.mark.parametrize(
    "grading_timing",
    [None, {}, {"total_duration_seconds": 0}, {"total_duration_seconds": 23.3}],
)
@pytest.mark.parametrize("tokens", [0, 84852])
def test_recorded_tokens_preserved_in_both_layouts(
    tmp_path, benchmark_script, layout, grading_timing, tokens
):
    root = tmp_path / "runs" if layout == "legacy" else tmp_path
    write_run(
        root,
        grading_timing=grading_timing,
        timing={"total_duration_seconds": 23.3, "total_tokens": tokens},
    )

    benchmark = benchmark_script["generate_benchmark"](tmp_path)

    assert benchmark["runs"][0]["result"]["tokens"] == tokens
    assert benchmark["runs"][0]["result"]["time_seconds"] == 23.3
    assert benchmark["run_summary"]["with_skill"]["tokens"]["mean"] == tokens


@pytest.mark.parametrize(
    "timing_state", ["absent", "missing_tokens", "null_tokens", "invalid_json"]
)
@pytest.mark.parametrize("has_grading_duration", [False, True])
def test_missing_token_measurements_keep_legacy_character_fallback(
    tmp_path, benchmark_script, timing_state, has_grading_duration
):
    grading_timing = {"total_duration_seconds": 23.3} if has_grading_duration else None
    timing = None
    if timing_state in {"missing_tokens", "null_tokens"}:
        timing = {"total_duration_seconds": 25.0}
        if timing_state == "null_tokens":
            timing["total_tokens"] = None
    run_dir = write_run(tmp_path, grading_timing=grading_timing, timing=timing)
    if timing_state == "invalid_json":
        (run_dir / "timing.json").write_text("{invalid", encoding="utf-8")

    benchmark = benchmark_script["generate_benchmark"](tmp_path)

    assert benchmark["runs"][0]["result"]["tokens"] == 12450
    expected_time = 23.3 if has_grading_duration else (25.0 if timing else 0.0)
    assert benchmark["runs"][0]["result"]["time_seconds"] == expected_time


def test_recorded_tokens_propagate_to_summary_delta_and_markdown(
    tmp_path, benchmark_script
):
    write_run(
        tmp_path,
        grading_timing={"total_duration_seconds": 23.3},
        timing={"total_tokens": 84852},
        config="with_skill",
    )
    write_run(
        tmp_path,
        grading_timing={"total_duration_seconds": 20.0},
        timing={"total_tokens": 10000},
        config="without_skill",
    )

    benchmark = benchmark_script["generate_benchmark"](tmp_path)

    assert benchmark["run_summary"]["without_skill"]["tokens"]["mean"] == 10000
    assert benchmark["run_summary"]["delta"]["tokens"] == "+74852"
    assert "| Tokens | 84852 ± 0 | 10000 ± 0 | +74852 |" in benchmark_script[
        "generate_markdown"
    ](benchmark)
