"""Git Bash discovery must follow the Git installation root, not ``git.exe``'s parent.

Git for Windows keeps ``git.exe`` in ``<root>/cmd`` (or ``<root>/bin``), while
PortableGit and GitHub Desktop ship ``<root>/mingw64/bin/git.exe``.  Git Bash
stays at ``<root>/bin/bash.exe`` and the POSIX ``sh.exe`` at ``<root>/bin`` /
``<root>/usr/bin`` in both layouts, so a candidate list derived from the parent
of ``git.exe`` misses every PortableGit host.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from support.shell import _script_bash_candidates, _script_sh_candidates


def _touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return path


@pytest.mark.parametrize("git_subdir", ["cmd", "mingw64/bin"], ids=["git-for-windows", "portablegit"])
def test_bash_candidates_reach_the_shell_beside_the_git_root(tmp_path, git_subdir):
    git = _touch(tmp_path / git_subdir / "git.exe")
    bash = _touch(tmp_path / "bin" / "bash.exe")

    resolved = [candidate.resolve() for candidate in _script_bash_candidates(str(git), None, None)]

    assert bash.resolve() in resolved


@pytest.mark.parametrize("git_subdir", ["cmd", "mingw64/bin"], ids=["git-for-windows", "portablegit"])
def test_posix_sh_candidates_reach_the_shell_beside_the_git_root(tmp_path, git_subdir):
    git = _touch(tmp_path / git_subdir / "git.exe")
    sh = _touch(tmp_path / "usr" / "bin" / "sh.exe")

    resolved = [candidate.resolve() for candidate in _script_sh_candidates(str(git), None)]

    assert sh.resolve() in resolved


@pytest.mark.skipif(os.name != "nt", reason="the Makefile shell wrapper is a cmd.exe script")
def test_makefile_shell_wrapper_runs_portablegit_bash(tmp_path):
    """`make` reaches Git Bash when `where git` reports the mingw64 layout.

    A bare ``cmd.exe`` copy stands in for ``bash.exe``: the wrapper only has to
    locate and launch it, and ``cmd /c echo`` keeps the assertion offline.
    """
    root = tmp_path / "PortableGit"
    (root / "mingw64" / "bin").mkdir(parents=True)
    (root / "mingw64" / "bin" / "git.exe").write_bytes(b"")
    bash = root / "bin" / "bash.exe"
    bash.parent.mkdir()
    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    shutil.copy(system_root / "System32" / "cmd.exe", bash)
    wrapper = Path(__file__).resolve().parents[2] / "scripts" / "run-with-git-bash.cmd"

    env = {**os.environ, "PATH": os.pathsep.join([str(root / "mingw64" / "bin"), str(system_root / "System32")])}
    result = subprocess.run(["cmd", "/c", str(wrapper), "/c", "echo", "BASH_OK"], capture_output=True, text=True, env=env, timeout=60)

    assert result.returncode == 0, result.stderr
    assert "BASH_OK" in result.stdout
