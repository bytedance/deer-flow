"""Locate a shell that can actually run the repo's POSIX shell scripts.

On POSIX hosts ``bash``/``sh`` from PATH are fine. On Windows the suite must
run Git Bash (MSYS2): the WSL launcher at ``%SystemRoot%\\System32\\bash.exe``
and the Microsoft Store alias stubs under ``WindowsApps`` also answer to the
name ``bash`` — and CreateProcess searches System32 before PATH, so even a
literal ``["bash", ...]`` argv with Git Bash first on PATH still reaches
WSL — but neither can run repo scripts against Windows checkout paths. The
discovery below mirrors what ``scripts/run-with-git-bash.cmd`` already does
for the Makefile.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest


def find_script_bash() -> str | None:
    """Return a bash able to run the repo's shell scripts, or ``None``."""
    if os.name != "nt":
        return shutil.which("bash")

    candidates: list[Path] = []
    git = shutil.which("git")
    if git is not None:
        # Git for Windows layout: <root>/cmd/git.exe (or <root>/bin/git.exe)
        # both resolve to <root>/bin/bash.exe two levels up from git's parent.
        candidates.append(Path(git).resolve().parent.parent / "bin" / "bash.exe")
    program_files = os.environ.get("ProgramFiles")
    if program_files:
        candidates.append(Path(program_files) / "Git" / "bin" / "bash.exe")
    bash = shutil.which("bash")
    if bash is not None:
        candidates.append(Path(bash))

    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    rejected_parents = (system_root / "System32", system_root / "SysWOW64")
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if not resolved.is_file():
            continue
        # The WSL launcher lives in System32; the Store alias stubs live under
        # WindowsApps. Neither is an MSYS2 bash that can run repo scripts.
        if any(parent in resolved.parents for parent in rejected_parents):
            continue
        if "WindowsApps" in resolved.parts:
            continue
        return str(resolved)
    return None


def require_script_bash() -> str:
    """Return :func:`find_script_bash`'s result, skipping the test when absent."""
    bash = find_script_bash()
    if bash is None:
        pytest.skip("repo shell-script tests need Git Bash on Windows")
    return bash


def find_posix_sh() -> str | None:
    """Return a shell able to run the repo's POSIX-sh scripts.

    Plain ``sh`` on POSIX hosts; Git Bash on Windows, where no ``sh`` exists
    on PATH outside an MSYS2 installation.
    """
    if os.name != "nt":
        return shutil.which("sh")
    return find_script_bash()


def require_posix_sh() -> str:
    """Return :func:`find_posix_sh`'s result, skipping the test when absent."""
    sh = find_posix_sh()
    if sh is None:
        pytest.skip("repo shell-script tests need Git Bash on Windows")
    return sh
