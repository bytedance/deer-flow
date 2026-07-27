"""Collection-policy tests for the live test marker (issue #4481).

These tests verify the selection policy:

* the default pytest invocation never *collects* live tests that talk to real
  external services;
* an explicit opt-in (``-m live``) plus a valid repo-root ``config.yaml`` is
  required to collect them;
* CI always skips the live module even when the opt-in marker is requested.

They drive pytest in a subprocess from the backend directory so the real
``addopts`` / marker / module-skip machinery is exercised end to end.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
LIVE_MODULE = "tests/test_client_live.py"


def _run_pytest(*args: str, env_overrides: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    # Default subprocess behaves like a developer shell, not CI.
    env.pop("CI", None)
    env.update(
        {
            "PYTHONPATH": ".",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
        }
    )
    if env_overrides:
        env.update(env_overrides)
    cmd = [sys.executable, "-m", "pytest", *args]
    return subprocess.run(cmd, cwd=BACKEND_DIR, env=env, capture_output=True, text=True, timeout=180)


@pytest.fixture
def repo_config_yaml():
    """Temporarily provide a repo-root config.yaml.

    ``test_client_live`` only checks existence (it does not parse contents), so
    an empty file is enough to clear the missing-config guard without the test
    needing real credentials. The file is removed afterwards if we created it.
    """
    cfg = REPO_ROOT / "config.yaml"
    created = False
    if not cfg.exists():
        cfg.write_text("# transient fixture for live-test collection policy\n")
        created = True
    try:
        yield cfg
    finally:
        if created:
            try:
                cfg.unlink()
            except OSError:
                pass


def test_live_marker_is_registered():
    """The `live` marker must be registered so `-m live` can select it."""
    result = _run_pytest("--markers")
    assert result.returncode == 0, result.stdout + result.stderr
    out = result.stdout
    assert "live" in out, "live marker not registered in pyproject.toml"


def test_default_never_collects_live_tests():
    """Without an explicit opt-in the live test bodies must not be collected.

    Covers both guards at once: with config.yaml present they are deselected by
    the ``addopts`` ``-m "not live"`` filter; without config.yaml the module is
    skipped. Either way no live test body is collected.
    """
    result = _run_pytest(LIVE_MODULE, "--collect-only", "-q")
    combined = result.stdout + result.stderr
    assert "test_chat_returns_nonempty_string" not in combined, combined


def test_explicit_opt_in_collects_live_when_config_present(repo_config_yaml):
    """`-m live` + valid config.yaml collects the live tests (explicit opt-in).

    Uses --collect-only so no test body runs and no real LLM is called.
    """
    result = _run_pytest(LIVE_MODULE, "--collect-only", "-q", "-m", "live")
    combined = result.stdout + result.stderr
    assert "test_chat_returns_nonempty_string" in combined, combined


def test_ci_skips_live_even_with_opt_in(repo_config_yaml):
    """CI must skip live tests even when the opt-in marker and config exist.

    Uses a real run (not ``--collect-only``): the module-level skip fires at
    import time, so no live test body executes and pytest reports SKIPPED with
    the CI reason. Asserting on a run (rather than collection) is what lets us
    observe the skip reason text.
    """
    result = _run_pytest(
        LIVE_MODULE,
        "-v",
        "-m",
        "live",
        env_overrides={"CI": "1"},
    )
    combined = result.stdout + result.stderr
    lowered = combined.lower()
    assert "skipped" in lowered, combined
