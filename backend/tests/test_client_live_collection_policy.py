"""Collection-policy tests for test_client_live.py.

Verifies that live integration tests are excluded from the default test run
and correctly gated by environment / config presence.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"
CONFIG_YAML = REPO_ROOT / "config.yaml"


def _collect_live_tests(*, env: dict | None = None, extra_args: list[str] | None = None) -> list[str]:
    """Run pytest --collect-only on test_client_live.py and return collected test names."""
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        str(BACKEND_DIR / "tests" / "test_client_live.py"),
        "--collect-only",
        "-q",
        "-p",
        "no:cacheprovider",
    ]
    if extra_args:
        cmd.extend(extra_args)

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(BACKEND_DIR),
        env=env or None,
    )
    # Print stderr for debugging
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    lines = [ln for ln in result.stdout.splitlines() if ln.strip() and "<Module" not in ln and "<Function" not in ln]
    return lines


class TestLiveTestCollectionPolicy:
    """Verify live tests are excluded from the default run."""

    def test_default_run_excludes_live_tests(self):
        """The default make test (no markers) must not collect live tests."""
        # Run with default (excludes live via -m "not live")
        cmd = [
            sys.executable,
            "-m",
            "pytest",
            "tests/",
            "--collect-only",
            "-q",
            "-m",
            "not live",
            "-p",
            "no:cacheprovider",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(BACKEND_DIR))
        collected = [ln for ln in result.stdout.splitlines() if "test_client_live" in ln and ("<Module" in ln or "<Function" in ln)]
        assert len(collected) == 0, f"Default run should not collect live tests, but found: {collected}"

    def test_live_marker_selects_live_tests(self):
        """The live marker should select live tests when config.yaml exists.

        When config.yaml is absent, items are removed before the marker filter
        applies, so the live marker cannot override that. The CI and
        missing-config tests cover those cases.
        """
        if not CONFIG_YAML.exists():
            pytest.skip("config.yaml not present — live tests are removed at collection time when config is absent")
        # Pass a clean env (without CI) so the subprocess is not affected by
        # an inherited CI=true from the outer test runner.
        clean_env = {k: v for k, v in subprocess.os.environ.items() if k != "CI"}
        lines = _collect_live_tests(env=clean_env, extra_args=["-m", "live"])
        # With -m live and config.yaml present, tests should be collected
        module_collected = any("test_client_live.py" in ln for ln in lines)
        assert module_collected, f"Live marker should collect the module when config.yaml exists: {lines}"

    def test_ci_env_skips_live_tests(self):
        """Live tests must be skipped when CI env var is set."""
        env = {**subprocess.os.environ.copy(), "CI": "1"}
        lines = _collect_live_tests(env=env)
        # The module should be skipped (not collected at all) in CI
        module_collected = any("test_client_live.py" in ln for ln in lines)
        assert not module_collected, f"CI should skip live tests: {lines}"

    def test_missing_config_skips_live_tests(self):
        """Live tests must be skipped when config.yaml does not exist."""
        bak_path = None
        if CONFIG_YAML.exists():
            bak_path = CONFIG_YAML.with_suffix(".yaml.bak")
            CONFIG_YAML.rename(bak_path)
        try:
            env = {k: v for k, v in subprocess.os.environ.items() if k != "CI"}
            lines = _collect_live_tests(env=env)
            module_collected = any("test_client_live.py" in ln for ln in lines)
            assert not module_collected, f"Missing config should skip live tests: {lines}"
        finally:
            if bak_path and bak_path.exists():
                bak_path.rename(CONFIG_YAML)

    def test_live_tests_require_explicit_optin(self):
        """Without CI and with config.yaml present, live tests must NOT be collected
        by the default -m "not live" run."""
        if not CONFIG_YAML.exists():
            pytest.skip("config.yaml not present — policy already enforced by missing-config test")

        env = {k: v for k, v in subprocess.os.environ.items() if k != "CI"}
        # Default run
        default_lines = _collect_live_tests(env=env, extra_args=["-m", "not live"])
        default_collected = any("test_client_live" in ln for ln in default_lines)
        assert not default_collected, f"Default run should not collect live tests even with config.yaml present: {default_lines}"

        # Explicit live marker should collect them
        live_lines = _collect_live_tests(env=env, extra_args=["-m", "live"])
        live_collected = any("test_client_live" in ln for ln in live_lines)
        assert live_collected, f"Live marker should collect live tests with config.yaml present: {live_lines}"
