"""Mapped host-directory spaces must not split PowerShell path arguments."""

import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from deerflow.sandbox.local.local_sandbox import LocalSandbox, PathMapping
from deerflow.sandbox.tools import bash_tool


@pytest.fixture
def powershell(monkeypatch):
    if os.name != "nt":
        pytest.skip("native Windows PowerShell execution")
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if shell is None:
        pytest.skip("PowerShell is not installed")
    monkeypatch.setattr(LocalSandbox, "_get_shell", staticmethod(lambda: shell))
    return shell


@pytest.fixture
def mounted(tmp_path):
    root = tmp_path / "host directory with spaces"
    root.mkdir()
    (root / "marker.txt").write_text("needle", encoding="utf-8")
    (root / "other.md").write_text("other", encoding="utf-8")
    return LocalSandbox("local", [PathMapping("/mnt/data", str(root))]), root


@pytest.mark.parametrize(
    "command",
    [
        "Get-Content /mnt/data/marker.txt",
        'Get-Content "/mnt/data/marker.txt"',
        "Get-Content '/mnt/data/marker.txt'",
        "Get-Content \u2018/mnt/data/marker.txt\u2019",
        "Get-Content \u201c/mnt/data/marker.txt\u201d",
        "Get-Content /mnt/data/*.txt",
        "Get-Content /mnt/data/marker.txt | Write-Output",
        "Write-Output ignored; Get-Content /mnt/data/marker.txt",
        "Write-Output /mnt/data/marker.txt",
        "Write-Output --file=/mnt/data/marker.txt",
        'Write-Output "$(Get-Content /mnt/data/marker.txt)"',
        "# it's a directory\nGet-Content /mnt/data/marker.txt",
        "Write-Output before;# it's text\nGet-Content '/mnt/data/marker.txt'",
        "<# it's a directory #> Get-Content /mnt/data/marker.txt",
        "Write-Output @'\nit's text\n'@\nGet-Content /mnt/data/marker.txt",
        'Write-Output @"\ntext with "quotes"\n"@\nGet-Content /mnt/data/marker.txt',
        'Write-Output @"\n$(Get-Content /mnt/data/marker.txt)\n"@',
        'Write-Output `"quoted; Get-Content /mnt/data/marker.txt',
        'Get-Content "/mnt/data/marker.txt"; Get-Content /mnt/data/marker.txt',
    ],
)
def test_powershell_executes_mapped_path_with_spaces(powershell, mounted, command):
    sandbox, _ = mounted
    output = sandbox.execute_command(command)
    expected = "/mnt/data/marker.txt" if command.startswith("Write-Output /") or "--file=" in command else "needle"
    assert expected in output
    assert "Exit Code:" not in output


@pytest.mark.parametrize("shell", ["sh", "cmd.exe"])
def test_other_shell_path_resolution_is_unchanged(mounted, shell):
    sandbox, root = mounted
    command = 'echo /mnt/data/marker.txt "/mnt/data/*.txt"'
    expected = command.replace("/mnt/data", str(root.resolve()).replace("\\", "/"))
    assert sandbox._resolve_paths_in_command(command, shell=shell) == expected


@pytest.mark.parametrize("shell_name", ["sh", "cmd.exe"])
def test_quoted_paths_still_execute_in_other_shells(mounted, monkeypatch, shell_name):
    shell = shutil.which(shell_name)
    if shell is None or (os.name == "nt" and shell_name == "sh"):
        pytest.skip(f"native {shell_name} is unavailable")
    monkeypatch.setattr(LocalSandbox, "_get_shell", staticmethod(lambda: shell))
    sandbox, _ = mounted
    command = 'echo "/mnt/data/marker.txt"' if shell_name == "cmd.exe" else 'cat "/mnt/data/marker.txt"'
    expected = "/mnt/data/marker.txt" if shell_name == "cmd.exe" else "needle"
    output = sandbox.execute_command(command)
    assert expected in output
    assert "Exit Code:" not in output


def test_powershell_redirects_to_mapped_path_with_spaces(powershell, mounted):
    sandbox, root = mounted
    output = sandbox.execute_command("Write-Output saved > /mnt/data/saved.txt; Get-Content /mnt/data/saved.txt")
    assert "saved" in output
    data = (root / "saved.txt").read_bytes()
    assert "saved" in data.decode("utf-16" if data.startswith(b"\xff\xfe") else "utf-8")
    assert "Exit Code:" not in output


@pytest.mark.parametrize("quote", ["", '"', "'"])
def test_public_bash_tool_preserves_thread_path_argument(powershell, tmp_path, monkeypatch, quote):
    from deerflow.config.sandbox_config import SandboxConfig

    dirs = {f"{name}_path": str(tmp_path / "thread data" / name) for name in ("workspace", "uploads", "outputs")}
    for directory in dirs.values():
        Path(directory).mkdir(parents=True)
    Path(dirs["uploads_path"], "marker.txt").write_text("needle", encoding="utf-8")
    sandbox = LocalSandbox("local", [PathMapping(f"/mnt/user-data/{name}", dirs[f"{name}_path"]) for name in ("workspace", "uploads", "outputs")])
    runtime = SimpleNamespace(state={"sandbox": {"sandbox_id": "local"}, "thread_data": dirs}, context={"thread_id": "space-test"})
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda _: sandbox)
    monkeypatch.setattr("deerflow.sandbox.tools.is_host_bash_allowed", lambda: True)
    monkeypatch.setattr("deerflow.sandbox.tools.get_app_config", lambda: SimpleNamespace(sandbox=SandboxConfig()))
    result = bash_tool.func(runtime=runtime, command=f"Get-Content {quote}/mnt/user-data/uploads/marker.txt{quote}")
    assert "needle" in result
    assert "Exit Code:" not in result
    assert not result.startswith("Error:"), result
