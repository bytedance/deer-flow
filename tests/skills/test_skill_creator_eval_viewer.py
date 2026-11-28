"""Regressions for skill-creator eval-viewer report generation."""

import json
import re
import runpy
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def review_script():
    script = Path(__file__).resolve().parents[2] / "skills/public/skill-creator/eval-viewer/generate_review.py"
    return runpy.run_path(str(script))


def _write_run_output(run_dir: Path, filename: str = "out.txt", content: str = "ok") -> None:
    outputs = run_dir / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    (outputs / filename).write_text(content, encoding="utf-8")


def test_find_runs_sorts_missing_and_mixed_eval_ids(tmp_path, review_script):
    _write_run_output(tmp_path / "eval-1" / "with_skill")
    (tmp_path / "eval-1" / "eval_metadata.json").write_text(json.dumps({"eval_id": 1, "prompt": "Numeric eval"}), encoding="utf-8")
    _write_run_output(tmp_path / "eval-alpha" / "with_skill")
    (tmp_path / "eval-alpha" / "eval_metadata.json").write_text(json.dumps({"eval_id": "alpha", "prompt": "String eval"}), encoding="utf-8")
    _write_run_output(tmp_path / "eval-untagged" / "with_skill")

    runs = review_script["find_runs"](tmp_path)

    assert [r["eval_id"] for r in runs] == [1, "alpha", None]
    assert [r["id"] for r in runs] == [
        "eval-1-with_skill",
        "eval-alpha-with_skill",
        "eval-untagged-with_skill",
    ]


def test_find_runs_reads_nested_eval_metadata_without_escaping_workspace(tmp_path, review_script):
    # Unrelated metadata above the workspace root must never be read.
    (tmp_path / "eval_metadata.json").write_text(json.dumps({"eval_id": 999, "prompt": "Leaked parent prompt"}), encoding="utf-8")

    workspace = tmp_path / "iteration-1"
    eval_dir = workspace / "eval-1"
    _write_run_output(eval_dir / "with_skill" / "run-1")
    (eval_dir / "eval_metadata.json").write_text(
        json.dumps({"eval_id": 1, "prompt": "Summarize quarterly revenue"}),
        encoding="utf-8",
    )

    runs = review_script["find_runs"](workspace)
    assert len(runs) == 1
    assert runs[0]["eval_id"] == 1
    assert runs[0]["prompt"] == "Summarize quarterly revenue"

    # A run located directly at workspace root must not read tmp_path/eval_metadata.json.
    root_workspace = tmp_path / "root-run"
    _write_run_output(root_workspace)
    root_runs = review_script["find_runs"](root_workspace)
    assert len(root_runs) == 1
    assert root_runs[0]["eval_id"] is None
    assert root_runs[0]["prompt"] == "(No prompt found)"


def test_generate_html_escapes_script_tags_in_embedded_data(tmp_path, review_script):
    html_output = "<!doctype html><script>alert('xss')</script><!-- end -->"
    workspace = tmp_path / "iteration-1"
    eval_dir = workspace / "eval-1"
    _write_run_output(eval_dir / "with_skill" / "run-1", "report.html", html_output)
    (eval_dir / "eval_metadata.json").write_text(
        json.dumps({"eval_id": 1, "prompt": "Check </script> handling"}),
        encoding="utf-8",
    )

    runs = review_script["find_runs"](workspace)
    rendered = review_script["generate_html"](runs, "my</script>skill")

    match = re.search(r"const EMBEDDED_DATA = (\{.*?\});\n", rendered)
    assert match is not None
    raw_json = match.group(1)
    assert "</script" not in raw_json.lower()
    assert "<!--" not in raw_json

    decoded = json.loads(raw_json)
    assert decoded["skill_name"] == "my</script>skill"
    assert decoded["runs"][0]["prompt"] == "Check </script> handling"
    assert decoded["runs"][0]["outputs"][0]["content"] == html_output


def test_cli_static_mode_writes_valid_html_for_nested_and_untagged_runs(tmp_path):
    script = Path(__file__).resolve().parents[2] / "skills/public/skill-creator/eval-viewer/generate_review.py"
    workspace = tmp_path / "iteration-1"
    _write_run_output(
        workspace / "eval-1" / "with_skill" / "run-1",
        "page.html",
        "<script>console.log(1)</script>",
    )
    (workspace / "eval-1" / "eval_metadata.json").write_text(json.dumps({"eval_id": 1, "prompt": "Build HTML page"}), encoding="utf-8")
    _write_run_output(workspace / "eval-extra" / "without_skill")
    out_html = tmp_path / "review.html"

    proc = subprocess.run(
        [sys.executable, str(script), str(workspace), "--static", str(out_html)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    rendered = out_html.read_text(encoding="utf-8")
    match = re.search(r"const EMBEDDED_DATA = (\{.*?\});\n", rendered)
    assert match is not None
    assert "</script" not in match.group(1).lower()
    decoded = json.loads(match.group(1))
    assert [r["eval_id"] for r in decoded["runs"]] == [1, None]
    assert decoded["runs"][0]["prompt"] == "Build HTML page"
