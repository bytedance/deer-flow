"""Mapped host-directory spaces must not split PowerShell path arguments."""

import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from deerflow.sandbox.local.local_sandbox import LocalSandbox, PathMapping
from deerflow.sandbox.tools import _apply_cwd_prefix, bash_tool, replace_virtual_paths_in_command


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


@pytest.mark.parametrize("layer", ["provider", "thread"])
@pytest.mark.parametrize(
    "command,expected",
    [
        ("Get-Content {virtual}/marker.txt", "Get-Content {escaped}/marker.txt"),
        ('Get-Content "{virtual}/marker.txt"', 'Get-Content "{raw}/marker.txt"'),
        ("Get-Content '{virtual}/marker.txt'", "Get-Content '{raw}/marker.txt'"),
        ("Get-Content \u2018{virtual}/marker.txt\u2019", "Get-Content \u2018{raw}/marker.txt\u2019"),
        ("Get-Content \u201c{virtual}/marker.txt\u201d", "Get-Content \u201c{raw}/marker.txt\u201d"),
        ('Write-Output "$(Get-Content {virtual}/marker.txt)"', 'Write-Output "$(Get-Content {escaped}/marker.txt)"'),
        ("# it's text\nGet-Content {virtual}/marker.txt", "# it's text\nGet-Content {escaped}/marker.txt"),
        ("<# it's text #> Get-Content {virtual}/*.txt", "<# it's text #> Get-Content {escaped}/*.txt"),
        ('Get-Content "{virtual}/marker.txt"; Get-Content {virtual}/*.txt', 'Get-Content "{raw}/marker.txt"; Get-Content {escaped}/*.txt'),
        ('Write-Output @"\n$(Get-Content {virtual}/marker.txt)\n"@', 'Write-Output @"\n$(Get-Content {escaped}/marker.txt)\n"@'),
    ],
)
def test_powershell_command_mapping_is_portable(mounted, layer, command, expected):
    sandbox, root = mounted
    virtual = "/mnt/data" if layer == "provider" else "/mnt/user-data/uploads"
    raw = str(root.resolve()).replace("\\", "/")
    command = command.format(virtual=virtual)
    if layer == "provider":
        result = sandbox._resolve_paths_in_command(command, shell="pwsh")
    else:
        result = replace_virtual_paths_in_command(command, {"uploads_path": str(root)}, shell="pwsh")
    assert result == expected.format(raw=raw, escaped=raw.replace(" ", "` "))


@pytest.mark.parametrize("layer", ["provider", "thread"])
@pytest.mark.parametrize(
    "directory,escaped",
    [
        ("O'Brien", "O`'Brien"),
        ("Tom & Jerry", "Tom` `&` Jerry"),
        ("a;b", "a`;b"),
        ("a`b", "a``b"),
        ("cost$USER", "cost`$USER"),
        ("a(b)", "a`(b`)"),
        ("a,b", "a`,b"),
        ("a{b}", "a`{b`}"),
        ("a\u2019b", "a`\u2019b"),
        ("a\u201db", "a`\u201db"),
        ("O'Brien's Folder", "O`'Brien`'s` Folder"),
    ],
)
def test_powershell_mapped_metacharacters_are_literal(tmp_path, layer, directory, escaped):
    root = tmp_path / directory
    root.mkdir()
    virtual = "/mnt/data" if layer == "provider" else "/mnt/user-data/uploads"
    command = f"Get-Content {virtual}/marker.txt"
    if layer == "provider":
        result = LocalSandbox("local", [PathMapping(virtual, str(root))])._resolve_paths_in_command(command, shell="pwsh")
    else:
        result = replace_virtual_paths_in_command(command, {"uploads_path": str(root)}, shell="pwsh")
    parent = str(tmp_path.resolve()).replace("\\", "/").replace(" ", "` ")
    assert result == f"Get-Content {parent}/{escaped}/marker.txt"


@pytest.mark.parametrize("layer", ["provider", "thread"])
@pytest.mark.parametrize(
    "directory,quote,escaped",
    [
        ("O'Brien", "'", "O''Brien"),
        ("a`b", '"', "a``b"),
        ("cost$USER", '"', "cost`$USER"),
        ("a\u2019b", "'", "a\u2019\u2019b"),
        ("a\u201db", '"', "a`\u201db"),
    ],
)
def test_quoted_powershell_mapped_metacharacters_are_literal(tmp_path, layer, directory, quote, escaped):
    root = tmp_path / directory
    root.mkdir()
    virtual = "/mnt/data" if layer == "provider" else "/mnt/user-data/uploads"
    command = f"Get-Content {quote}{virtual}/marker.txt{quote}"
    if layer == "provider":
        result = LocalSandbox("local", [PathMapping(virtual, str(root))])._resolve_paths_in_command(command, shell="pwsh")
    else:
        result = replace_virtual_paths_in_command(command, {"uploads_path": str(root)}, shell="pwsh")
    parent = str(tmp_path.resolve()).replace("\\", "/")
    assert result == f"Get-Content {quote}{parent}/{escaped}/marker.txt{quote}"


@pytest.mark.parametrize("directory", ["O'Brien", "O'Brien's Folder", "Tom & Jerry", "a;b", "a`b", "cost$USER", "a(b)", "a,b", "a{b}", "a\u2019b", "a\u201db", "a;Write-Output unexpected;#"])
@pytest.mark.parametrize("quote", ["", '"', "'"])
def test_powershell_executes_mapped_metacharacters(powershell, tmp_path, directory, quote):
    root = tmp_path / directory
    root.mkdir()
    (root / "marker.txt").write_text("needle", encoding="utf-8")
    sandbox = LocalSandbox("local", [PathMapping("/mnt/data", str(root))])
    output = sandbox.execute_command(f"Get-Content {quote}/mnt/data/marker.txt{quote}")
    assert "needle" in output, output
    assert "Exit Code:" not in output, output


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
@pytest.mark.parametrize("upload_directory", ["thread data", "O'Brien", "cost$USER", "a;b"])
def test_public_bash_tool_preserves_thread_path_argument(powershell, tmp_path, monkeypatch, quote, upload_directory):
    from deerflow.config.sandbox_config import SandboxConfig

    dirs = {f"{name}_path": str(tmp_path / "thread data" / name) for name in ("workspace", "uploads", "outputs")}
    dirs["uploads_path"] = str(tmp_path / upload_directory / "uploads")
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


def _workspace_runtime(workspace, monkeypatch, *, filename="marker.txt"):
    workspace.mkdir()
    (workspace / filename).write_text("workspace-marker", encoding="utf-8")
    sandbox = LocalSandbox("local", [PathMapping("/mnt/user-data/workspace", str(workspace))])
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda _: sandbox)
    monkeypatch.setattr("deerflow.sandbox.tools.is_host_bash_allowed", lambda: True)
    return SimpleNamespace(
        state={"sandbox": {"sandbox_id": "local"}, "thread_data": {"workspace_path": str(workspace)}, "thread_directories_created": True},
        context={"thread_id": "workspace-test"},
    )


@pytest.mark.parametrize("apostrophe", ["\u2018", "\u2019"])
def test_public_bash_tool_enters_powershell_workspace_with_curly_apostrophe(powershell, tmp_path, monkeypatch, apostrophe):
    runtime = _workspace_runtime(tmp_path / f"O{apostrophe}Brien workspace", monkeypatch)
    assert bash_tool.func(runtime=runtime, command="Get-Content marker.txt").strip() == "workspace-marker"


@pytest.mark.skipif(os.name != "nt", reason="native Windows cmd.exe execution")
def test_public_bash_tool_enters_cmd_workspace_with_spaces(tmp_path, monkeypatch):
    shell = shutil.which("cmd.exe")
    assert shell is not None
    monkeypatch.setattr(LocalSandbox, "_get_shell", staticmethod(lambda: shell))
    workspace = tmp_path / "workspace with spaces"
    runtime = _workspace_runtime(workspace, monkeypatch, filename="marker file.txt")
    command = 'type "marker file.txt"'
    assert bash_tool.func(runtime=runtime, command=command).strip() == "workspace-marker"

    monkeypatch.chdir(tmp_path)
    (tmp_path / "marker file.txt").write_text("inherited-directory-marker", encoding="utf-8")
    workspace.rename(tmp_path / "renamed workspace")
    result = bash_tool.func(runtime=runtime, command=command)
    assert result.startswith("Error:"), result
    assert "inherited-directory-marker" not in result


def test_public_bash_tool_passes_cmd_workspace_to_process_launch(tmp_path, monkeypatch):
    from deerflow.sandbox.local import local_sandbox

    workspace = tmp_path / "workspace with spaces"
    runtime = _workspace_runtime(workspace, monkeypatch)
    monkeypatch.setattr("deerflow.sandbox.tools._is_windows", lambda: True)
    monkeypatch.setattr(local_sandbox, "os", SimpleNamespace(**{**vars(os), "name": "nt"}))
    monkeypatch.setattr(LocalSandbox, "_get_shell", staticmethod(lambda: "cmd.exe"))
    calls = []

    def run(args, timeout, env, **kwargs):
        calls.append((args, kwargs.get("cwd")))
        return "workspace-marker", "", 0, False

    monkeypatch.setattr(LocalSandbox, "_run_windows_command", staticmethod(run))
    assert bash_tool.func(runtime=runtime, command='type "marker file.txt"') == "workspace-marker"
    assert calls == [('cmd.exe /d /s /c "type "marker file.txt""', str(workspace))]


@pytest.mark.parametrize(
    ("shell", "expected_prefix"),
    [
        ("/bin/bash", "cd '/tmp/thread data/workspace' && "),
        ("/bin/sh", "cd '/tmp/thread data/workspace' && "),
        # Git Bash/MSYS on Windows reports as sh.exe and speaks POSIX.
        ("C:/Program Files/Git/bin/bash.exe", "cd '/tmp/thread data/workspace' && "),
        # PowerShell 7 and Windows PowerShell 5.1: the 5.1 parser has no `&&`.
        ("/usr/local/bin/pwsh", "Set-Location -LiteralPath '/tmp/thread data/workspace' -ErrorAction Stop; "),
        ("C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe", "Set-Location -LiteralPath '/tmp/thread data/workspace' -ErrorAction Stop; "),
        # cmd.exe keeps single quotes as literal characters, so `cd '<path>'` looks
        # for a directory whose name includes them.
        ("C:\\Windows\\System32\\cmd.exe", 'cd /d "/tmp/thread data/workspace" && '),
    ],
)
def test_cwd_prefix_uses_syntax_the_selected_shell_can_parse(shell, expected_prefix):
    workspace = "/tmp/thread data/workspace"
    assert _apply_cwd_prefix("echo hi", {"workspace_path": workspace}, shell=shell) == f"{expected_prefix}echo hi"


def test_cwd_prefix_quotes_a_workspace_with_an_apostrophe():
    workspace = "/tmp/O'Brien's thread/workspace"
    assert _apply_cwd_prefix("echo hi", {"workspace_path": workspace}, shell="/bin/bash") == "cd '/tmp/O'\"'\"'Brien'\"'\"'s thread/workspace' && echo hi"
    # PowerShell escapes a literal quote by doubling it inside a single-quoted string.
    assert _apply_cwd_prefix("echo hi", {"workspace_path": workspace}, shell="pwsh") == "Set-Location -LiteralPath '/tmp/O''Brien''s thread/workspace' -ErrorAction Stop; echo hi"


@pytest.mark.parametrize("apostrophe", ["\u2018", "\u2019"])
def test_cwd_prefix_quotes_a_workspace_with_a_curly_apostrophe(apostrophe):
    workspace = f"/tmp/O{apostrophe}Brien workspace"
    prefix = _apply_cwd_prefix("echo hi", {"workspace_path": workspace}, shell="powershell.exe")
    assert prefix == f"Set-Location -LiteralPath '/tmp/O{apostrophe * 2}Brien workspace' -ErrorAction Stop; echo hi"


@pytest.mark.parametrize("shell", ["/bin/bash", "pwsh", "C:\\Windows\\System32\\cmd.exe"])
def test_cwd_prefix_leaves_the_command_alone_without_a_workspace(shell):
    assert _apply_cwd_prefix("echo hi", None, shell=shell) == "echo hi"
    assert _apply_cwd_prefix("echo hi", {}, shell=shell) == "echo hi"


def test_powershell_prefix_skips_the_command_when_the_workspace_is_gone(powershell, tmp_path):
    """A vanished workspace must abort the command, not run it from the inherited cwd.

    ``Set-Location`` reports a missing directory as a non-terminating error, so
    without ``-ErrorAction Stop`` the ``;``-separated command still runs — from
    whatever directory the gateway was started in.
    """
    missing = tmp_path / "workspace-that-was-removed"
    command = _apply_cwd_prefix('Write-Output "SHOULD_NOT_RUN"', {"workspace_path": str(missing)}, shell=powershell)
    completed = subprocess.run(
        [powershell, "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    assert completed.returncode != 0, completed.stdout
    assert "SHOULD_NOT_RUN" not in completed.stdout

    # Control: the same prefix does run the command once the workspace exists,
    # so the assertion above cannot pass by the command never running at all.
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    ok_command = _apply_cwd_prefix('Write-Output "RAN"', {"workspace_path": str(workspace)}, shell=powershell)
    ran = subprocess.run(
        [powershell, "-NoProfile", "-Command", ok_command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    assert ran.returncode == 0, ran.stderr
    assert "RAN" in ran.stdout
