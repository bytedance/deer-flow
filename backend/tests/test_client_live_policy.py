"""Regression tests for the explicit opt-in policy of live client tests."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
LIVE_TEST_PATH = BACKEND_ROOT / "tests" / "test_client_live.py"
LIVE_OPT_IN = "DEER_FLOW_RUN_LIVE_TESTS"
REPRESENTATIVE_LIVE_NODE_IDS = (
    "::TestLiveBasicChat::test_chat_returns_nonempty_string",
    "::TestLiveStreaming::test_stream_yields_messages_tuple_and_end",
)


def _collect_live_tests(
    tmp_path: Path,
    *,
    config_exists: bool,
    opt_in: bool,
    ci: bool,
) -> subprocess.CompletedProcess[str]:
    """Collect a temporary copy without inheriting credentials or a real .env."""
    temp_repo = tmp_path / "repo"
    temp_tests = temp_repo / "backend" / "tests"
    temp_tests.mkdir(parents=True)
    (temp_tests / "test_client_live.py").write_text(
        LIVE_TEST_PATH.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    if config_exists:
        (temp_repo / "config.yaml").write_text("models: []\n", encoding="utf-8")

    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        "PYTHONPATH": os.pathsep.join(
            [
                str(BACKEND_ROOT),
                str(BACKEND_ROOT / "packages" / "harness"),
            ]
        ),
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
    }
    if opt_in:
        env[LIVE_OPT_IN] = "1"
    if ci:
        env["CI"] = "1"

    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-c",
            str(BACKEND_ROOT / "pyproject.toml"),
            "--collect-only",
            "-q",
            "-rs",
            "-p",
            "no:cacheprovider",
            str(temp_tests / "test_client_live.py"),
        ],
        cwd=temp_repo / "backend",
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _assert_collection_skipped(result: subprocess.CompletedProcess[str], reason: str) -> None:
    output = result.stdout + result.stderr
    assert result.returncode in {0, pytest.ExitCode.NO_TESTS_COLLECTED}, output
    assert reason in output
    assert "no tests collected" in output
    assert all(node_id not in output for node_id in REPRESENTATIVE_LIVE_NODE_IDS)


def _dry_run_make_target(target: str, *extra: str) -> str:
    result = subprocess.run(
        ["make", "-n", target, *extra],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    return output


def test_config_alone_does_not_enable_live_collection(tmp_path: Path) -> None:
    result = _collect_live_tests(tmp_path, config_exists=True, opt_in=False, ci=False)

    _assert_collection_skipped(result, f"Set {LIVE_OPT_IN}=1")


def test_explicit_opt_in_collects_live_tests(tmp_path: Path) -> None:
    result = _collect_live_tests(tmp_path, config_exists=True, opt_in=True, ci=False)

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert all(node_id in output for node_id in REPRESENTATIVE_LIVE_NODE_IDS)


def test_ci_blocks_live_collection_even_with_opt_in(tmp_path: Path) -> None:
    result = _collect_live_tests(tmp_path, config_exists=True, opt_in=True, ci=True)

    _assert_collection_skipped(result, "Live tests skipped in CI")


def test_opt_in_without_config_reports_missing_config(tmp_path: Path) -> None:
    result = _collect_live_tests(tmp_path, config_exists=False, opt_in=True, ci=False)

    _assert_collection_skipped(result, "No config.yaml found")


def test_make_targets_keep_default_tests_offline_and_support_live_opt_in() -> None:
    default_command = _dry_run_make_target("test")
    live_command = _dry_run_make_target("test-live")

    assert 'pytest -m "not live"' in default_command
    assert "--ignore=tests/blocking_io" in default_command
    assert "tests/" in default_command
    assert LIVE_OPT_IN not in default_command

    assert f"{LIVE_OPT_IN}=1" in live_command
    assert "pytest -m live" in live_command
    assert "tests/" in live_command
    assert "tests/test_client_live.py" not in live_command


def test_live_marker_is_registered() -> None:
    pyproject = (BACKEND_ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert '"live: tests that call real external APIs and require explicit opt-in"' in pyproject


def test_documentation_matches_live_test_commands() -> None:
    contributor_docs = (REPO_ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    backend_agent_docs = (BACKEND_ROOT / "AGENTS.md").read_text(encoding="utf-8")

    for docs in (contributor_docs, backend_agent_docs):
        assert "make test-live" in docs
        assert LIVE_OPT_IN in docs
        assert "API" in docs


def test_default_ci_workflow_does_not_opt_in_to_live_tests() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "backend-unit-tests.yml").read_text(encoding="utf-8")

    # Assert the exact sharded caller, not the substring `make test` (which
    # `make test-shard` also contains). Otherwise a regression that re-points the
    # workflow at live tests could slip through as a vacuous substring check.
    assert "make test-shard" in workflow
    assert LIVE_OPT_IN not in workflow


def test_ci_unit_test_workflow_runs_duration_aware_shards() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "backend-unit-tests.yml").read_text(encoding="utf-8")

    assert "shard: [1, 2, 3, 4]" in workflow
    assert "make test-shard SPLITS=4" in workflow
    assert "GROUP=${{ matrix.shard }}" in workflow

    # The sharded command must select the offline suite and balance the shards by
    # real wall-clock cost (duration-aware), not fall back to an even split.
    command = _dry_run_make_target("test-shard", "SPLITS=4", "GROUP=2")

    assert "--splits 4" in command
    assert "--group 2" in command
    assert 'pytest -m "not live"' in command
    assert "--ignore=tests/blocking_io" in command
    assert "--splitting-algorithm least_duration" in command
    assert "--durations-path=.test_durations" in command

    # The repo must ship a duration baseline. Without it pytest-split silently
    # degrades to an even (count-based) split, so this is a fail-closed contract.
    assert (BACKEND_ROOT / ".test_durations").exists()

    # The full-suite entry point stays offline-only.
    full_command = _dry_run_make_target("test")
    assert 'pytest -m "not live"' in full_command
    assert "--ignore=tests/blocking_io" in full_command
    assert LIVE_OPT_IN not in full_command


def test_duration_baseline_target_replaces_stale_entries() -> None:
    command = _dry_run_make_target("test-shard-durations")

    assert "--store-durations" in command
    assert "--clean-durations" in command
    assert "--durations-path=.test_durations" in command


def test_blocking_io_ci_workflow_owns_dedicated_suite() -> None:
    command = _dry_run_make_target("test-blocking-io")
    workflow = (REPO_ROOT / ".github" / "workflows" / "backend-blocking-io-tests.yml").read_text(encoding="utf-8")

    assert "pytest tests/blocking_io" in command
    assert "make test-blocking-io" in workflow
