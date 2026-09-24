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
    tool = bin_dir / "tool"
    tool.write_text('#!/bin/sh\nprintf "%s %s\\n" "${0##*/}" "$*" >> "$INSTALL_TRACE"\n', encoding="utf-8")
    tool.chmod(0o755)
    for name in ("uv", "pnpm"):
        (bin_dir / name).symlink_to(tool)

    trace_path = tmp_path / "commands.log"
    env = {**os.environ, "PATH": str(bin_dir), "INSTALL_TRACE": str(trace_path)}
    result = subprocess.run([MAKE, "install", f"PYTHON={sys.executable}"], cwd=REPO_ROOT, env=env, capture_output=True, text=True, check=False)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "uv tool run pre-commit install --overwrite" in trace_path.read_text(encoding="utf-8")
