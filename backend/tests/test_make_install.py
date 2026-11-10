"""The root install target invokes uv tools without relying on their PATH."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MAKE = shutil.which("make")


@pytest.mark.skipif(MAKE is None or os.name == "nt", reason="requires POSIX make")
def test_make_install_runs_precommit_without_uv_tool_bin_on_path(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    python_dir = tmp_path / "Python With Spaces"
    python_dir.mkdir()
    python = python_dir / "python"
    python.write_text('#!/bin/sh\nexec "$REAL_PYTHON" "$@"\n', encoding="utf-8")
    python.chmod(0o755)
    tool = bin_dir / "tool"
    tool.write_text('#!/bin/sh\nprintf "%s %s\\n" "${0##*/}" "$*" >> "$INSTALL_TRACE"\n', encoding="utf-8")
    tool.chmod(0o755)
    for name in ("uv", "pnpm"):
        (bin_dir / name).symlink_to(tool)

    trace_path = tmp_path / "commands.log"
    env = {**os.environ, "PATH": str(bin_dir), "INSTALL_TRACE": str(trace_path), "REAL_PYTHON": sys.executable}
    result = subprocess.run([MAKE, "install", f"PYTHON={python}"], cwd=REPO_ROOT, env=env, capture_output=True, text=True, check=False)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "uv tool run pre-commit install --overwrite" in trace_path.read_text(encoding="utf-8")


@pytest.mark.skipif(MAKE is None or os.name == "nt", reason="requires POSIX make")
def test_root_python_targets_accept_interpreter_path_with_spaces(tmp_path: Path) -> None:
    python_dir = tmp_path / "Python With Spaces"
    python_dir.mkdir()
    python = python_dir / "python"
    python.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$PYTHON_TRACE"\n', encoding="utf-8")
    python.chmod(0o755)

    trace_path = tmp_path / "python-commands.log"
    env = {**os.environ, "PYTHON_TRACE": str(trace_path)}
    result = subprocess.run(
        [MAKE, "config", "check", "check-agent-guidance", f"PYTHON={python}"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert sorted(trace_path.read_text(encoding="utf-8").splitlines()) == sorted(
        [
            "./scripts/configure.py",
            "./scripts/check.py",
            "./scripts/check_agent_guidance.py",
        ]
    )


@pytest.mark.skipif(MAKE is None or os.name == "nt", reason="requires POSIX make")
def test_frontend_make_accepts_interpreter_path_with_spaces(tmp_path: Path) -> None:
    python_dir = tmp_path / "Python With Spaces"
    python_dir.mkdir()
    python = python_dir / "python"
    python.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$PYTHON_TRACE"\n', encoding="utf-8")
    python.chmod(0o755)

    trace_path = tmp_path / "python-commands.log"
    env = {**os.environ, "PYTHON_TRACE": str(trace_path)}
    result = subprocess.run(
        [MAKE, "install", f"PYTHON={python}"],
        cwd=REPO_ROOT / "frontend",
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert trace_path.read_text(encoding="utf-8").splitlines() == ["../scripts/pnpm.py install"]
