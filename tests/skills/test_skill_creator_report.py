"""Render the report payload produced by run_loop with and without a holdout."""

import json
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "skills/public/skill-creator/scripts/generate_report.py"


def train_only_output():
    # run_loop records None for these test fields when --holdout 0 is used.
    return {
        "original_description": "Original description",
        "best_description": "Best description",
        "best_score": "1/1",
        "best_train_score": "1/1",
        "best_test_score": None,
        "holdout": 0,
        "train_size": 1,
        "test_size": 0,
        "iterations_run": 1,
        "history": [
            {
                "iteration": 1,
                "description": "Best description",
                "train_passed": 1,
                "train_total": 1,
                "train_results": [
                    {
                        "query": "Create a skill",
                        "should_trigger": True,
                        "pass": True,
                        "runs": 3,
                        "triggers": 3,
                    }
                ],
                "test_passed": None,
                "test_total": None,
                "test_results": None,
            }
        ],
    }


@pytest.mark.parametrize("test_results", [None, [], "omitted"])
def test_report_without_test_results(test_results):
    data = train_only_output()
    if test_results == "omitted":
        del data["history"][0]["test_results"]
    else:
        data["history"][0]["test_results"] = test_results

    report = runpy.run_path(str(SCRIPT))["generate_html"](data, auto_refresh=True)

    assert '<meta http-equiv="refresh" content="5">' in report
    assert 'class="best-row"' in report
    assert "Create a skill" in report
    assert '<span class="score score-good">3/3</span>' in report
    assert '<span class="score score-bad">0/0</span>' in report
    assert '<th class="test-col' not in report
    assert "(train)" in report


def test_report_keeps_holdout_results():
    data = train_only_output()
    data.update(holdout=0.5, test_size=1, best_test_score="1/1")
    data["history"][0].update(
        test_passed=1,
        test_total=1,
        test_results=[
            {
                "query": "Tell me the weather",
                "should_trigger": False,
                "pass": True,
                "runs": 3,
                "triggers": 0,
            }
        ],
    )

    report = runpy.run_path(str(SCRIPT))["generate_html"](data)

    assert '<th class="test-col negative-col">Tell me the weather</th>' in report
    assert report.count('<span class="score score-good">3/3</span>') == 2
    assert 'class="result test-result pass"' in report
    assert "(test)" in report


@pytest.mark.parametrize("source", ["file", "stdin"])
def test_cli_renders_train_only_output(tmp_path, source):
    payload = json.dumps(train_only_output())
    output_path = tmp_path / "report.html"
    if source == "file":
        input_path = tmp_path / "results.json"
        input_path.write_text(payload, encoding="utf-8")
        arguments = [str(input_path)]
    else:
        arguments = ["-"]

    result = subprocess.run(
        [sys.executable, str(SCRIPT), *arguments, "-o", str(output_path)],
        input=payload if source == "stdin" else None,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert "Report written to" in result.stderr
    assert "Best description" in output_path.read_text(encoding="utf-8")
