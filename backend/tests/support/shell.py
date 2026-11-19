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


def _git_roots(git: str) -> list[Path]:
    """Return the two directories the Makefile wrapper probes for the Git root.

    ``scripts/run-with-git-bash.cmd`` checks ``bin\\bash.exe`` under ``git.exe``'s
    directory and then one level above it. Git for Windows keeps ``git.exe`` in
    ``<root>/cmd`` (or ``<root>/bin``), so the first entry is the installation
    root. PortableGit and GitHub Desktop keep it in ``<root>/mingw64/bin``, where
    only the second entry is; the first is ``<root>/mingw64`` and typically holds
    no ``bin/bash.exe`` in stock trees. Bash and sh themselves stay at
    ``<root>/bin`` and ``<root>/usr/bin`` in both layouts.
    """
    git_dir = Path(git).resolve().parent
    return [git_dir.parent, git_dir.parent.parent]


def _script_bash_candidates(git: str | None, program_files: str | None, path_bash: str | None) -> list[Path]:
    """Build the ordered bash candidate list for Windows hosts."""
    candidates: list[Path] = []
    if git is not None:
        candidates.extend(root / "bin" / "bash.exe" for root in _git_roots(git))
    if program_files:
        candidates.append(Path(program_files) / "Git" / "bin" / "bash.exe")
    if path_bash is not None:
        candidates.append(Path(path_bash))
    return candidates


def _script_sh_candidates(git: str | None, program_files: str | None) -> list[Path]:
    """Build the ordered POSIX-sh candidate list for Windows hosts.

    Git for Windows ships a real ``sh.exe`` at ``<root>/bin/sh.exe`` (and
    ``<root>/usr/bin/sh.exe``); preferring it over bash lets ``#!/bin/sh``
    scripts run under an actual sh, like the POSIX CI legs.
    """
    candidates: list[Path] = []
    if git is not None:
        for root in _git_roots(git):
            candidates.append(root / "bin" / "sh.exe")
            candidates.append(root / "usr" / "bin" / "sh.exe")
    if program_files:
        program_files_git = Path(program_files) / "Git"
        candidates.append(program_files_git / "bin" / "sh.exe")
        candidates.append(program_files_git / "usr" / "bin" / "sh.exe")
    return candidates


def _first_runnable_shell(candidates: list[Path], system_root: Path) -> str | None:
    """Return the first candidate that is a real shell, rejecting stub launchers.

    The WSL launcher lives in System32/SysWOW64 and the Microsoft Store alias
    stubs live under WindowsApps; neither is an MSYS2 shell that can run repo
    scripts against Windows checkout paths.
    """
    rejected_parents = (system_root / "System32", system_root / "SysWOW64")
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if not resolved.is_file():
            continue
        if any(parent in resolved.parents for parent in rejected_parents):
            continue
        if "WindowsApps" in resolved.parts:
            continue
        return str(resolved)
    return None


def find_script_bash() -> str | None:
    """Return a bash able to run the repo's shell scripts, or ``None``."""
    if os.name != "nt":
        return shutil.which("bash")

    candidates = _script_bash_candidates(
        git=shutil.which("git"),
        program_files=os.environ.get("ProgramFiles"),
        path_bash=shutil.which("bash"),
    )
    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    return _first_runnable_shell(candidates, system_root)


def require_script_bash() -> str:
    """Return :func:`find_script_bash`'s result, skipping the test when absent."""
    bash = find_script_bash()
    if bash is None:
        pytest.skip("repo shell-script tests need Git Bash on Windows")
    return bash


def find_posix_sh() -> str | None:
    """Return a shell able to run the repo's POSIX-sh scripts.

    Plain ``sh`` on POSIX hosts. On Windows no ``sh`` exists on PATH outside
    an MSYS2 installation, so prefer the real ``sh.exe`` shipped with Git for
    Windows and fall back to Git Bash when it is absent.
    """
    if os.name != "nt":
        return shutil.which("sh")
    candidates = _script_sh_candidates(
        git=shutil.which("git"),
        program_files=os.environ.get("ProgramFiles"),
    )
    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    return _first_runnable_shell(candidates, system_root) or find_script_bash()


def require_posix_sh() -> str:
    """Return :func:`find_posix_sh`'s result, skipping the test when absent."""
    sh = find_posix_sh()
    if sh is None:
        pytest.skip("repo shell-script tests need Git Bash on Windows")
    return sh
