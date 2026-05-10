"""Unit tests for docker/dev-entrypoint.sh (UV_EXTRAS validation + parsing).

Exercises the script via its `--print-extras` dry-run hook so we don't actually
launch uvicorn or hit /app/logs. Together with test_detect_uv_extras.py these
cover both the local make-dev path and the docker-compose-dev path with the
same shape — see PR #2767 / Issue #2754.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ENTRYPOINT = REPO_ROOT / "docker" / "dev-entrypoint.sh"


def _run(uv_extras: str | None) -> subprocess.CompletedProcess[str]:
    """Invoke `dev-entrypoint.sh --print-extras` with UV_EXTRAS set."""
    env = os.environ.copy()
    env.pop("UV_EXTRAS", None)
    if uv_extras is not None:
        env["UV_EXTRAS"] = uv_extras
    return subprocess.run(
        ["sh", str(ENTRYPOINT), "--print-extras"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_entrypoint_script_exists_and_is_posix_sh():
    assert ENTRYPOINT.is_file()
    # Catch syntax errors before runtime — `sh -n` is a parse-only check.
    proc = subprocess.run(["sh", "-n", str(ENTRYPOINT)], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr


def test_no_uv_extras_yields_empty_flags():
    proc = _run(None)
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""


def test_single_extra():
    proc = _run("postgres")
    assert proc.returncode == 0
    assert proc.stdout.strip() == "--extra postgres"


def test_multi_extra_comma_separated():
    proc = _run("postgres,ollama")
    assert proc.returncode == 0
    assert proc.stdout.strip() == "--extra postgres --extra ollama"


def test_multi_extra_whitespace_separated():
    proc = _run("postgres ollama")
    assert proc.returncode == 0
    assert proc.stdout.strip() == "--extra postgres --extra ollama"


def test_multi_extra_mixed_separators():
    proc = _run(" postgres ,  ollama ,")
    assert proc.returncode == 0
    assert proc.stdout.strip() == "--extra postgres --extra ollama"


def test_empty_string_yields_empty_flags():
    proc = _run("")
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""


@pytest.mark.parametrize(
    "bad_value",
    [
        "; rm -rf /",  # the canonical injection attempt
        "$(whoami)",  # command substitution
        "`echo bad`",  # backticks
        "postgres;evil",  # mixed legal+illegal in a single token
        "1postgres",  # leading digit
        "-postgres",  # leading hyphen
        "post gres extra/path",  # contains slash
    ],
)
def test_metacharacters_abort_with_nonzero_exit(bad_value):
    proc = _run(bad_value)
    assert proc.returncode != 0, f"expected abort for {bad_value!r}, got 0"
    assert "is invalid" in proc.stderr
    assert proc.stdout.strip() == ""


def test_underscores_and_hyphens_in_name_are_allowed():
    """Mirrors uv's accepted shape for `[project.optional-dependencies]` keys."""
    proc = _run("post_gres,post-gres")
    assert proc.returncode == 0
    assert proc.stdout.strip() == "--extra post_gres --extra post-gres"
