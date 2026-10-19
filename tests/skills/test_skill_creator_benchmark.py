"""Regressions for skill-creator benchmark measurements."""

import builtins
import json
import runpy
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def benchmark_script():
    script = (
        Path(__file__).resolve().parents[2]
        / "skills/public/skill-creator/scripts/aggregate_benchmark.py"
    )
    return runpy.run_path(str(script))


def write_run(
    root, *, grading_timing=None, timing=None, config="with_skill", run_number=1
):
    run_dir = root / "eval-1" / config / f"run-{run_number}"
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
    tmp_path, benchmark_script, timing_state, has_grading_duration, capsys
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
    output = capsys.readouterr().out
    if timing_state == "invalid_json":
        assert "Warning:" in output
        assert str(run_dir / "timing.json") in output
    else:
        assert output == ""


@pytest.mark.parametrize("layout", ["workspace", "legacy"])
@pytest.mark.parametrize("has_grading_duration", [False, True])
@pytest.mark.parametrize(
    "timing_data",
    [None, [], [{"total_tokens": 84852}], "timing", 42, False],
    ids=["null", "empty-array", "array", "string", "number", "boolean"],
)
def test_non_object_timing_keeps_fallback_and_other_runs(
    tmp_path, benchmark_script, layout, has_grading_duration, timing_data, capsys
):
    root = tmp_path / "runs" if layout == "legacy" else tmp_path
    grading_timing = {"total_duration_seconds": 23.3} if has_grading_duration else None
    run_dir = write_run(root, grading_timing=grading_timing)
    (run_dir / "timing.json").write_text(json.dumps(timing_data), encoding="utf-8")
    write_run(
        root,
        timing={"total_duration_seconds": 25.0, "total_tokens": 0},
        config="without_skill",
    )

    benchmark = benchmark_script["generate_benchmark"](tmp_path)

    results = {run["configuration"]: run["result"] for run in benchmark["runs"]}
    assert set(results) == {"with_skill", "without_skill"}
    assert results["with_skill"]["tokens"] == 12450
    assert results["with_skill"]["time_seconds"] == (
        23.3 if has_grading_duration else 0.0
    )
    assert results["without_skill"]["tokens"] == 0
    assert results["without_skill"]["time_seconds"] == 25.0
    assert benchmark["run_summary"]["with_skill"]["tokens"]["mean"] == 12450
    assert benchmark["run_summary"]["delta"]["tokens"] == "+12450"
    assert "| Tokens | 12450 ± 0 | 0 ± 0 | +12450 |" in benchmark_script[
        "generate_markdown"
    ](benchmark)
    output = capsys.readouterr().out
    assert "Warning:" in output
    assert "non-object" in output
    assert str(run_dir / "timing.json") in output


@pytest.mark.parametrize("layout", ["workspace", "legacy"])
@pytest.mark.parametrize("has_grading_duration", [False, True])
@pytest.mark.parametrize("field", ["total_tokens", "total_duration_seconds"])
@pytest.mark.parametrize(
    "value",
    [
        "84852",
        {"n": 1},
        [],
        True,
        False,
        -1,
        -0.5,
        float("nan"),
        float("inf"),
        -float("inf"),
    ],
    ids=[
        "string",
        "object",
        "array",
        "true",
        "false",
        "negative-int",
        "negative-float",
        "nan",
        "infinity",
        "negative-infinity",
    ],
)
def test_invalid_timing_field_warns_and_preserves_other_measurements(
    tmp_path, benchmark_script, layout, has_grading_duration, field, value, capsys
):
    root = tmp_path / "runs" if layout == "legacy" else tmp_path
    timing = {"total_tokens": 0, "total_duration_seconds": 25.0, field: value}
    grading_timing = {"total_duration_seconds": 23.3} if has_grading_duration else None
    run_dir = write_run(root, grading_timing=grading_timing, timing=timing)
    write_run(
        root, timing={"total_tokens": 0, "total_duration_seconds": 25.0}, run_number=2
    )

    benchmark = benchmark_script["generate_benchmark"](tmp_path)

    results = {run["run_number"]: run["result"] for run in benchmark["runs"]}
    assert set(results) == {1, 2}
    expected_tokens = 12450 if field == "total_tokens" else 0
    expected_time = (
        23.3
        if has_grading_duration
        else (0.0 if field == "total_duration_seconds" else 25.0)
    )
    assert results[1]["tokens"] == expected_tokens
    assert results[1]["time_seconds"] == expected_time
    assert results[2]["tokens"] == 0
    assert results[2]["time_seconds"] == 25.0
    summary = benchmark["run_summary"]["with_skill"]
    assert summary["tokens"]["mean"] == expected_tokens / 2
    assert summary["time_seconds"]["mean"] == (expected_time + 25.0) / 2
    assert "| Tokens |" in benchmark_script["generate_markdown"](benchmark)
    json.dumps(benchmark, allow_nan=False)
    output = capsys.readouterr().out
    assert "Warning:" in output
    assert field in output
    assert str(run_dir / "timing.json") in output


@pytest.mark.parametrize("tokens", [0, 0.0, 84852, 12.5])
@pytest.mark.parametrize("duration", [0, 0.0, 25.0])
def test_finite_non_negative_timing_numbers_are_preserved(
    tmp_path, benchmark_script, tokens, duration, capsys
):
    write_run(
        tmp_path, timing={"total_tokens": tokens, "total_duration_seconds": duration}
    )

    benchmark = benchmark_script["generate_benchmark"](tmp_path)

    assert benchmark["runs"][0]["result"]["tokens"] == tokens
    assert benchmark["runs"][0]["result"]["time_seconds"] == duration
    assert benchmark["run_summary"]["with_skill"]["tokens"]["mean"] == tokens
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("has_grading_duration", [False, True])
@pytest.mark.parametrize(
    "timing",
    [
        {},
        {"total_tokens": None},
        {"total_duration_seconds": None},
        {"total_tokens": None, "total_duration_seconds": None},
    ],
)
def test_missing_or_null_timing_fields_use_fallbacks_without_warning(
    tmp_path, benchmark_script, has_grading_duration, timing, capsys
):
    grading_timing = {"total_duration_seconds": 23.3} if has_grading_duration else None
    write_run(tmp_path, grading_timing=grading_timing, timing=timing)

    benchmark = benchmark_script["generate_benchmark"](tmp_path)

    assert benchmark["runs"][0]["result"]["tokens"] == 12450
    assert benchmark["runs"][0]["result"]["time_seconds"] == (
        23.3 if has_grading_duration else 0.0
    )
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("layout", ["workspace", "legacy"])
@pytest.mark.parametrize("has_grading_duration", [False, True])
@pytest.mark.parametrize(
    "timing_content,expected_tokens,expected_duration",
    [
        ("null", 12450, 0.0),
        ("{invalid", 12450, 0.0),
        (b"\xff\xfe{invalid", 12450, 0.0),
        (None, 12450, 0.0),
        ('{"total_tokens": "84852", "total_duration_seconds": 25.0}', 12450, 25.0),
        ('{"total_tokens": 0, "total_duration_seconds": {"n": 1}}', 0, 0.0),
        ('{"total_tokens": false, "total_duration_seconds": true}', 12450, 0.0),
    ],
    ids=[
        "non-object",
        "invalid-json",
        "invalid-utf8",
        "directory",
        "invalid-tokens",
        "invalid-duration",
        "both-invalid",
    ],
)
def test_cli_warns_and_writes_reports_for_invalid_timing(
    tmp_path,
    benchmark_script,
    layout,
    has_grading_duration,
    timing_content,
    expected_tokens,
    expected_duration,
):
    root = tmp_path / "runs" if layout == "legacy" else tmp_path
    grading_timing = {"total_duration_seconds": 23.3} if has_grading_duration else None
    run_dir = write_run(root, grading_timing=grading_timing)
    timing_file = run_dir / "timing.json"
    if timing_content is None:
        timing_file.mkdir()
    elif isinstance(timing_content, bytes):
        timing_file.write_bytes(timing_content)
    else:
        timing_file.write_text(timing_content, encoding="utf-8")
    write_run(
        root,
        timing={"total_tokens": 0, "total_duration_seconds": 25.0},
        config="without_skill",
    )

    completed = subprocess.run(
        [sys.executable, benchmark_script["__file__"], str(tmp_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    assert "Warning:" in completed.stdout
    assert str(run_dir / "timing.json") in completed.stdout
    benchmark = json.loads((tmp_path / "benchmark.json").read_text(encoding="utf-8"))
    results = {run["configuration"]: run["result"] for run in benchmark["runs"]}
    assert set(results) == {"with_skill", "without_skill"}
    assert results["with_skill"]["tokens"] == expected_tokens
    assert results["with_skill"]["time_seconds"] == (
        23.3 if has_grading_duration else expected_duration
    )
    assert results["without_skill"]["tokens"] == 0
    assert results["without_skill"]["time_seconds"] == 25.0
    assert (tmp_path / "benchmark.md").read_text(encoding="utf-8") == benchmark_script[
        "generate_markdown"
    ](benchmark)


@pytest.mark.parametrize("layout", ["workspace", "legacy"])
@pytest.mark.parametrize("has_grading_duration", [False, True])
@pytest.mark.parametrize("operation", ["open", "exists"])
def test_unreadable_timing_warns_and_keeps_fallback_and_other_runs(
    tmp_path,
    benchmark_script,
    layout,
    has_grading_duration,
    operation,
    monkeypatch,
    capsys,
):
    root = tmp_path / "runs" if layout == "legacy" else tmp_path
    grading_timing = {"total_duration_seconds": 23.3} if has_grading_duration else None
    run_dir = write_run(
        root,
        grading_timing=grading_timing,
        timing={"total_tokens": 84852, "total_duration_seconds": 25.0},
    )
    timing_file = run_dir / "timing.json"
    write_run(
        root,
        timing={"total_tokens": 0, "total_duration_seconds": 25.0},
        config="without_skill",
    )
    # Inject access failures without relying on OS permissions or the test user's UID.
    if operation == "open":
        original_open = builtins.open

        def denied_open(file, *args, **kwargs):
            if file == timing_file:
                raise PermissionError("timing access denied")
            return original_open(file, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", denied_open)
    else:
        original_exists = Path.exists

        def denied_exists(path, *args, **kwargs):
            if path == timing_file:
                raise PermissionError("timing access denied")
            return original_exists(path, *args, **kwargs)

        monkeypatch.setattr(Path, "exists", denied_exists)

    benchmark = benchmark_script["generate_benchmark"](tmp_path)

    results = {run["configuration"]: run["result"] for run in benchmark["runs"]}
    assert set(results) == {"with_skill", "without_skill"}
    assert results["with_skill"]["tokens"] == 12450
    assert results["with_skill"]["time_seconds"] == (
        23.3 if has_grading_duration else 0.0
    )
    assert results["without_skill"]["tokens"] == 0
    assert results["without_skill"]["time_seconds"] == 25.0
    assert benchmark["run_summary"]["delta"]["tokens"] == "+12450"
    assert "| Tokens |" in benchmark_script["generate_markdown"](benchmark)
    json.dumps(benchmark, allow_nan=False)
    output = capsys.readouterr().out
    assert "Warning:" in output
    assert str(timing_file) in output
    assert "timing access denied" in output


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
