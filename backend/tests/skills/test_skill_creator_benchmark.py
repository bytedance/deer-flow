from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "skills" / "public" / "skill-creator" / "scripts" / "aggregate_benchmark.py"


def _run(benchmark_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(benchmark_dir)],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def test_empty_benchmark_dir_fails_without_writing_files(tmp_path: Path) -> None:
    result = _run(tmp_path)

    assert result.returncode != 0
    assert "No eval directories found" in result.stderr
    assert not (tmp_path / "benchmark.json").exists()
    assert not (tmp_path / "benchmark.md").exists()


def test_missing_benchmark_dir_reports_on_stderr(tmp_path: Path) -> None:
    result = _run(tmp_path / "missing")

    assert result.returncode != 0
    assert "Directory not found" in result.stderr


def test_benchmark_with_runs_still_succeeds(tmp_path: Path) -> None:
    run_dir = tmp_path / "eval-0" / "with_skill" / "run-1"
    run_dir.mkdir(parents=True)
    (run_dir / "grading.json").write_text(
        '{"summary": {"pass_rate": 1.0, "passed": 1, "failed": 0, "total": 1}, "expectations": []}',
        encoding="utf-8",
    )

    result = _run(tmp_path)

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "benchmark.json").exists()


_GRADING = '{"summary": {"pass_rate": 1.0, "passed": 1, "failed": 0, "total": 1}, "expectations": []}'


def test_flat_eval_layout_from_skill_md_is_aggregated(tmp_path: Path) -> None:
    # SKILL.md saves outputs to eval-<ID>/<config>/outputs/ and grader.md leaves
    # grading.json next to outputs/, with no run-N directory.
    config_dir = tmp_path / "eval-0" / "with_skill"
    (config_dir / "outputs").mkdir(parents=True)
    (config_dir / "grading.json").write_text(_GRADING, encoding="utf-8")

    result = _run(tmp_path)

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "benchmark.json").exists()


def test_empty_runs_dir_falls_back_to_eval_dirs_in_benchmark_dir(tmp_path: Path) -> None:
    (tmp_path / "runs").mkdir()
    run_dir = tmp_path / "eval-0" / "with_skill" / "run-1"
    run_dir.mkdir(parents=True)
    (run_dir / "grading.json").write_text(_GRADING, encoding="utf-8")

    result = _run(tmp_path)

    assert result.returncode == 0, result.stderr


def test_eval_dirs_without_grading_fail_without_writing_files(tmp_path: Path) -> None:
    (tmp_path / "eval-0" / "with_skill" / "outputs").mkdir(parents=True)

    result = _run(tmp_path)

    assert result.returncode != 0
    assert not (tmp_path / "benchmark.json").exists()
