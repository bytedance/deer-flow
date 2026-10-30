r"""Windows host paths must not bypass the local host-bash guard.

``LocalSandbox`` is the documented default provider and executes through
PowerShell, cmd.exe or Git Bash on Windows, all of which resolve ``C:/...``,
``C:\...``, a Win32 namespace path (``\\?\C:\...``, ``\\.\PhysicalDrive0``), a
UNC path (``\\server\share``) and a cmd/PowerShell variable expansion
(``%WINDIR%\win.ini``, ``$env:SystemRoot\win.ini``) against the host
filesystem. A deployment with ``sandbox.allow_host_bash: true`` therefore has to
reject those spellings exactly like the POSIX host paths
``validate_local_bash_command_paths`` already rejects, while regex, glob and
format text (``grep -E '\bword\b'``, ``printf '\t%s\n'``) stays an ordinary
argument.

These cases drive the Python validator, not a real Windows shell, so the host
gate is patched through fixtures and the whole file runs on every host -
including the Ubuntu CI jobs, which otherwise never reach the Windows branches.
"""

import pytest

from deerflow.sandbox import tools as sandbox_tools
from deerflow.sandbox.tools import validate_local_bash_command_paths

_THREAD_DATA = {
    "workspace_path": "/tmp/deer-flow/threads/t1/user-data/workspace",
    "uploads_path": "/tmp/deer-flow/threads/t1/user-data/uploads",
    "outputs_path": "/tmp/deer-flow/threads/t1/user-data/outputs",
}

# Spellings that name a host path on Windows and no path on POSIX.
_REJECTED = [
    "cat C:/Windows/win.ini",
    "cat 'C:\\Windows\\win.ini'",
    'cat "C:\\Windows\\win.ini"',
    "type C://Windows/win.ini",
    "cat C:/",
    "cat C:\\",
    "cat c:/windows/win.ini",
    "cat C:\\Windows\\System32\\config\\SAM",
    "type \\\\?\\C:\\Windows\\win.ini",
    "type \\\\.\\PhysicalDrive0",
    "type \\\\server\\share\\secret.txt",
    "cat %WINDIR%\\win.ini",
    "cat %SystemDrive%\\Windows\\win.ini",
    "cat $env:SystemRoot\\win.ini",
    "cat $HOME\\.ssh\\id_rsa",
    "cd C:/Windows",
    "cd 'C:\\Windows'",
    "cd C:",
    "cd %WINDIR%",
    "cd $env:WINDIR",
    "chdir C:/Windows",
    "cd C:\\Windows\\System32 && cat drivers\\etc\\hosts",
    "cd \\Windows",
    "cd \\Windows && cat win.ini",
    "chdir \\Windows",
    "Set-Location \\Windows",
    "Set-Location -ErrorAction Stop $env:WINDIR",
    "Set-Location -ErrorAction Stop \\Windows",
    "Push-Location -StackName saved $env:WINDIR",
    "cd -ErrorAction SilentlyContinue $env:WINDIR",
    "curl -oC:/Windows/evil.exe http://example.com",
    "git -CC:/Windows status",
    "gcc -IC:/Windows/inc x.c",
    "type ..\\..\\secret.txt",
    "python -c \"open('C:/Windows/win.ini').read()\"",
    'powershell -Command "Get-Content C:\\Windows\\win.ini"',
]

# Arguments the same commands legitimately carry to the same shells.
_ALLOWED = [
    "ls -la",
    "grep -l foo file.txt",
    "echo a:b",
    "grep 'a:b' file.txt",
    "grep -E '\\bword\\b' file.txt",
    "rg -g '*.py' '\\Aclass' .",
    "printf '\\t%s\\n'",
    "python -c \"print('a:b')\"",
    "sed -n '1,5p' file.txt",
    "git log --format='%H:%an'",
    "cat /mnt/user-data/workspace/report.txt",
    "curl 'https://example.com/?ref=C:/Windows'",
    "rg 'foo|..\\bar' .",
    "grep -E 'a|..\\d' file.txt",
    "rg 'then cd \\Windows' docs",
    "git log --grep 'then cd \\Windows'",
]

# Names that are relative on POSIX and must stay allowed there.
_POSIX_RELATIVE = [
    "cat C:/Windows/win.ini",
    "cat %WINDIR%\\win.ini",
    "cd C:/Windows",
]


@pytest.fixture()
def windows_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """Take the validator's Windows path regardless of the actual host."""
    monkeypatch.setattr(sandbox_tools, "_is_windows", lambda: True)


@pytest.fixture()
def posix_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """Take the validator's POSIX path regardless of the actual host."""
    monkeypatch.setattr(sandbox_tools, "_is_windows", lambda: False)


@pytest.mark.usefixtures("windows_host")
@pytest.mark.parametrize("command", _REJECTED)
def test_windows_host_path_is_rejected(command: str) -> None:
    with pytest.raises(PermissionError):
        validate_local_bash_command_paths(command, _THREAD_DATA)


@pytest.mark.usefixtures("windows_host")
@pytest.mark.parametrize("command", _ALLOWED)
def test_windows_relative_argument_is_allowed(command: str) -> None:
    validate_local_bash_command_paths(command, _THREAD_DATA)


@pytest.mark.usefixtures("posix_host")
@pytest.mark.parametrize("command", _POSIX_RELATIVE)
def test_posix_host_keeps_the_relative_name(command: str) -> None:
    validate_local_bash_command_paths(command, _THREAD_DATA)
