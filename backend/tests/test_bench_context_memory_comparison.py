"""Regression checks for the offline benchmark's actual CLI and report."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
MODULE = "scripts.benchmark.context_memory_comparison"
MANIFEST = BACKEND / "scripts/benchmark/context_memory_comparison/manifest.json"


def _run(tmp_path: Path, entrypoint: list[str]) -> tuple[int, dict]:
    # Run the standalone Gateway in a fresh process. In particular, pytest's
    # global stubs and another test's app config must not leak into this run.
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(str(BACKEND / path) for path in (".", "packages/harness", "packages/extension-api")),
    }
    result = subprocess.run(
        [sys.executable, *entrypoint, "run-offline", "--output-dir", str(tmp_path)],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    report = tmp_path / "report.json"
    assert report.is_file(), result.stderr
    assert {path.name for path in tmp_path.iterdir()} == {"report.json"}
    return result.returncode, json.loads(report.read_text(encoding="utf-8"))


def test_offline_cli_records_real_gateway_context(tmp_path: Path) -> None:
    fixture = json.loads(MANIFEST.read_text(encoding="utf-8"))
    code, report = _run(tmp_path, ["-m", MODULE])
    assert report["checkpoint_backend"] == "sqlite"
    assert report["dataset"] == fixture["dataset"]

    scope = report["scope_isolation"]
    assert scope["passed"]
    control = fixture["default_fact"]
    for label, project in fixture["projects"].items():
        turn = scope["threads"][label]
        assert set(turn["present"]) == {control, project["instructions"], project["document"]}
        assert all(turn["context_token_estimate"][tag] > 0 for tag in ("memory", "project", "documents"))
    for label, fact in (("unassigned", control), ("custom_agent", fixture["agent_fact"])):
        turn = scope["threads"][label]
        assert turn["present"] == [fact]
        assert turn["context_token_estimate"]["memory"] > 0
        assert turn["context_token_estimate"]["project"] == turn["context_token_estimate"]["documents"] == 0
    rejected = scope["project_only_fact"]
    assert rejected["update_succeeded"] and rejected["passed"]
    assert rejected["scope_rejections"] == 1
    assert not rejected["stored"]
    assert fixture["project_only_fact"] not in rejected["other_thread"]["present"]

    history = fixture["thread_history_control"]
    assert set(report["invalidation"]) == {"deletion", "replacement"}
    for name, case in report["invalidation"].items():
        data = fixture["invalidation"][name]
        expected = {control}
        if "new" in data:
            expected.add(data["new"])
        assert case["before"]["present"] == sorted({control, data["old"], history})
        assert case["update_succeeded"]
        assert set(case["stored"]) == set(case["new_thread"]["present"]) == expected
        assert history in case["same_thread"]["present"]
        # Pin the benchmark's verdict to the captured messages so a future
        # production invalidation fix can change the observed behavior.
        assert case["passed"] == (set(case["same_thread"]["present"]) == expected | {history})
    assert report["passed"] == all(case["passed"] for case in report["invalidation"].values())
    assert code == (0 if report["passed"] else 1)


@pytest.mark.parametrize("failure_mode", ["extraction_error", "no_scope_rejection"])
def test_scope_isolation_requires_a_scope_rejection(tmp_path: Path, failure_mode: str) -> None:
    driver = """
import sys

from scripts.benchmark.context_memory_comparison import runner
from scripts.benchmark.context_memory_comparison.cli import main

generate = runner.OfflineModel._generate
failure_mode = sys.argv.pop(1)

def change_project_extraction(self, *args, **kwargs):
    update = runner._SCRIPTED_UPDATE.get()
    if self.model == "extract" and update and any(fact["scope"] == "project" for fact in update["newFacts"]):
        if failure_mode == "extraction_error":
            raise OSError("Synthetic extraction failure")
        token = runner._SCRIPTED_UPDATE.set({**update, "newFacts": []})
        try:
            return generate(self, *args, **kwargs)
        finally:
            runner._SCRIPTED_UPDATE.reset(token)
    return generate(self, *args, **kwargs)

runner.OfflineModel._generate = change_project_extraction
raise SystemExit(main())
"""
    code, report = _run(tmp_path, ["-c", driver, failure_mode])
    assert code == 1
    scope = report["scope_isolation"]
    assert all(turn["passed"] for turn in scope["threads"].values())
    project_fact = scope["project_only_fact"]
    assert not project_fact["passed"]
    if failure_mode == "extraction_error":
        assert not project_fact["update_succeeded"]
    else:
        assert project_fact["update_succeeded"]
        assert not project_fact["stored"] and project_fact["other_thread"]["passed"]
        assert project_fact["scope_rejections"] == 0
    assert not scope["passed"] and not report["passed"]
