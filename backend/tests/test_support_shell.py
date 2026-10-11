"""Unit tests for the Windows shell discovery in tests/support/shell.py.

``find_script_bash``/``find_posix_sh`` return at the ``os.name != "nt"``
early-out on POSIX CI, so the candidate-rejection rules would otherwise only
ever run on contributors' Windows machines -- exactly the failure mode the
discovery exists to fix. The candidate construction and the rejection scan are
pinned here against real files (``tmp_path``) with faked inputs, so the logic
is exercised on every CI leg.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from support import shell


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    return path


@pytest.fixture()
def fake_windows(tmp_path: Path) -> Path:
    """A fake Windows layout: git root, ProgramFiles Git, WSL + Store stubs."""
    _touch(tmp_path / "git" / "cmd" / "git.exe")
    _touch(tmp_path / "git" / "bin" / "bash.exe")
    _touch(tmp_path / "git" / "bin" / "sh.exe")
    _touch(tmp_path / "git" / "usr" / "bin" / "sh.exe")
    _touch(tmp_path / "ProgramFiles" / "Git" / "bin" / "bash.exe")
    _touch(tmp_path / "ProgramFiles" / "Git" / "usr" / "bin" / "sh.exe")
    _touch(tmp_path / "Windows" / "System32" / "bash.exe")  # WSL launcher
    _touch(tmp_path / "Windows" / "SysWOW64" / "bash.exe")  # 32-bit WSL launcher
    _touch(tmp_path / "WindowsApps" / "bash.exe")  # Microsoft Store alias stub
    return tmp_path


def _system_root(root: Path) -> Path:
    return root / "Windows"


def test_system32_bash_rejected_even_when_only_path_hit(fake_windows: Path):
    wsl_launcher = fake_windows / "Windows" / "System32" / "bash.exe"

    result = shell._first_runnable_shell([wsl_launcher], _system_root(fake_windows))

    assert result is None


def test_syswow64_bash_rejected(fake_windows: Path):
    syswow64 = fake_windows / "Windows" / "SysWOW64" / "bash.exe"

    result = shell._first_runnable_shell([syswow64], _system_root(fake_windows))

    assert result is None


def test_windowsapps_store_stub_rejected(fake_windows: Path):
    store_stub = fake_windows / "WindowsApps" / "bash.exe"

    result = shell._first_runnable_shell([store_stub], _system_root(fake_windows))

    assert result is None


def test_rejected_candidates_fall_through_to_real_shell(fake_windows: Path):
    wsl_launcher = fake_windows / "Windows" / "System32" / "bash.exe"
    git_bash = fake_windows / "git" / "bin" / "bash.exe"

    result = shell._first_runnable_shell([wsl_launcher, git_bash], _system_root(fake_windows))

    assert result == str(git_bash.resolve())


def test_missing_candidates_are_skipped(fake_windows: Path):
    missing = fake_windows / "no-such-dir" / "bash.exe"
    git_bash = fake_windows / "git" / "bin" / "bash.exe"

    result = shell._first_runnable_shell([missing, git_bash], _system_root(fake_windows))

    assert result == str(git_bash.resolve())


def test_no_runnable_candidate_returns_none(fake_windows: Path):
    missing = fake_windows / "no-such-dir" / "bash.exe"
    wsl_launcher = fake_windows / "Windows" / "System32" / "bash.exe"

    result = shell._first_runnable_shell([missing, wsl_launcher], _system_root(fake_windows))

    assert result is None


def test_git_derived_bash_candidate_comes_first(fake_windows: Path):
    git_exe = str(fake_windows / "git" / "cmd" / "git.exe")
    path_bash = str(fake_windows / "elsewhere" / "bash.exe")

    candidates = shell._script_bash_candidates(git=git_exe, program_files=None, path_bash=path_bash)

    git_root = (fake_windows / "git" / "cmd" / "git.exe").resolve().parent.parent
    assert candidates == [git_root / "bin" / "bash.exe", Path(path_bash)]


def test_program_files_bash_used_when_git_absent(fake_windows: Path):
    program_files = fake_windows / "ProgramFiles"

    candidates = shell._script_bash_candidates(git=None, program_files=str(program_files), path_bash=None)

    assert candidates == [program_files / "Git" / "bin" / "bash.exe"]


def test_posix_sh_prefers_git_sh_exe(fake_windows: Path):
    git_exe = str(fake_windows / "git" / "cmd" / "git.exe")

    candidates = shell._script_sh_candidates(git=git_exe, program_files=None)

    git_root = (fake_windows / "git" / "cmd" / "git.exe").resolve().parent.parent
    assert candidates == [
        git_root / "bin" / "sh.exe",
        git_root / "usr" / "bin" / "sh.exe",
    ]


def test_posix_sh_falls_back_to_program_files(fake_windows: Path):
    program_files = fake_windows / "ProgramFiles"

    candidates = shell._script_sh_candidates(git=None, program_files=str(program_files))

    assert candidates == [
        program_files / "Git" / "bin" / "sh.exe",
        program_files / "Git" / "usr" / "bin" / "sh.exe",
    ]


@pytest.mark.skipif(os.name != "nt", reason="real Windows environment reads")
def test_find_script_bash_never_returns_wsl_or_store_stubs():
    """On a real Windows host the result must not be a stub launcher."""
    result = shell.find_script_bash()

    if result is None:
        pytest.skip("no Git Bash installed on this machine")
    assert "WindowsApps" not in Path(result).parts
    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    assert system_root / "System32" not in Path(result).parents
    assert system_root / "SysWOW64" not in Path(result).parents
