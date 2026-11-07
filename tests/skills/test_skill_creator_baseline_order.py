"""Exercise benchmark comparison direction through real run files and the CLI."""

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


def write_run(root, eval_name, config, pass_rate, duration, tokens):
    run = root / eval_name / config / "run-1"
    run.mkdir(parents=True)
    (run / "grading.json").write_text(
        json.dumps({"summary": {"pass_rate": pass_rate}}), encoding="utf-8"
    )
    (run / "timing.json").write_text(
        json.dumps({"total_duration_seconds": duration, "total_tokens": tokens}),
        encoding="utf-8",
    )


@pytest.mark.parametrize("layout", ["workspace", "legacy"])
@pytest.mark.parametrize("baseline", ["old_skill", "without_skill", "baseline"])
@pytest.mark.parametrize("earlier_baseline_only", [False, True])
def test_cli_compares_improved_skill_against_baseline(
    tmp_path, layout, baseline, earlier_baseline_only
):
    root = tmp_path / "runs" if layout == "legacy" else tmp_path
    if earlier_baseline_only:
        write_run(root, "eval-0", baseline, 0.25, 20, 100)
    write_run(root, "eval-1", baseline, 0.25, 20, 100)
    write_run(root, "eval-1", "with_skill", 0.75, 15, 80)

    completed = subprocess.run(
        [sys.executable, "-B", str(SCRIPT), str(tmp_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=True,
    )

    benchmark = json.loads((tmp_path / "benchmark.json").read_text(encoding="utf-8"))
    summary = benchmark["run_summary"]
    assert summary["delta"] == {
        "pass_rate": "+0.50",
        "time_seconds": "-5.0",
        "tokens": "-20",
    }
    assert list(summary) == ["with_skill", baseline, "delta"]
    assert benchmark["runs"][0]["configuration"] == "with_skill"
    markdown = (tmp_path / "benchmark.md").read_text(encoding="utf-8")
    assert (
        f"| Metric | With Skill | {baseline.replace('_', ' ').title()} | Delta |"
        in markdown
    )
    assert "| Pass Rate | 75% ± 0% | 25% ± 0% | +0.50 |" in markdown
    assert "| Time | 15.0s ± 0.0s | 20.0s ± 0.0s | -5.0s |" in markdown
    assert "| Tokens | 80 ± 0 | 100 ± 0 | -20 |" in markdown
    assert "Delta:         +0.50" in completed.stdout


def test_custom_configurations_keep_existing_alphabetical_order(tmp_path):
    write_run(tmp_path, "eval-1", "variant_b", 0.25, 20, 100)
    write_run(tmp_path, "eval-1", "variant_a", 0.75, 15, 80)

    script = runpy.run_path(str(SCRIPT))
    benchmark = script["generate_benchmark"](tmp_path)

    assert list(benchmark["run_summary"]) == ["variant_a", "variant_b", "delta"]
    assert benchmark["run_summary"]["delta"]["pass_rate"] == "+0.50"


def test_multiple_baselines_keep_relative_order_and_all_runs(tmp_path):
    for eval_name in ["eval-1", "eval-2"]:
        write_run(tmp_path, eval_name, "old_skill", 0.25, 20, 100)
        write_run(tmp_path, eval_name, "without_skill", 0, 10, 50)
        write_run(tmp_path, eval_name, "with_skill", 0.75, 15, 80)

    script = runpy.run_path(str(SCRIPT))
    benchmark = script["generate_benchmark"](tmp_path)

    assert list(benchmark["run_summary"]) == [
        "with_skill",
        "old_skill",
        "without_skill",
        "delta",
    ]
    assert [(run["configuration"], run["eval_id"]) for run in benchmark["runs"]] == [
        ("with_skill", 1),
        ("with_skill", 2),
        ("old_skill", 1),
        ("old_skill", 2),
        ("without_skill", 1),
        ("without_skill", 2),
    ]
    assert benchmark["run_summary"]["delta"]["pass_rate"] == "+0.50"


@pytest.mark.parametrize("config", ["with_skill", "old_skill"])
def test_single_configuration_preserves_metrics(tmp_path, config):
    write_run(tmp_path, "eval-1", config, 0.75, 15, 80)

    script = runpy.run_path(str(SCRIPT))
    benchmark = script["generate_benchmark"](tmp_path)

    assert list(benchmark["run_summary"]) == [config, "delta"]
    assert benchmark["run_summary"][config]["pass_rate"]["mean"] == 0.75
    assert len(benchmark["runs"]) == 1


def test_empty_workspace_preserves_empty_benchmark(tmp_path):
    script = runpy.run_path(str(SCRIPT))

    benchmark = script["generate_benchmark"](tmp_path)

    assert benchmark["runs"] == []
    assert list(benchmark["run_summary"]) == ["delta"]
