from __future__ import annotations

import importlib
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import deerflow.sandbox.local.local_sandbox as local_sandbox
from deerflow.config.sandbox_config import SandboxConfig, VolumeMountConfig
from deerflow.sandbox.local.local_sandbox import LocalSandbox, PathMapping
from deerflow.tools.builtins.run_host_program_tool import run_host_program_tool

run_host_program_module = importlib.import_module("deerflow.tools.builtins.run_host_program_tool")

_LAUNCHER_ROOT = Path(__file__).resolve().parent / ".launcher-mount"
_MOUNT = PathMapping(
    container_path="/root",
    local_path=str(_LAUNCHER_ROOT),
    read_only=False,
)
_MOUNTS = [
    VolumeMountConfig(
        host_path=str(_LAUNCHER_ROOT),
        container_path="/root",
        read_only=False,
    )
]
_WINDOWS_MOUNTS = [
    VolumeMountConfig(
        host_path=r"C:\Users\lichen",
        container_path="/root",
        read_only=False,
    )
]


def _windows_path(path: str) -> str:
    return str(Path(path).resolve()).replace("/", "\\")


def _native_path(path: str) -> str:
    return str(Path(path).resolve())


def test_execute_program_launches_exe_without_shell(monkeypatch) -> None:
    monkeypatch.setattr(local_sandbox, "_is_windows_native_program_platform", lambda: True)
    calls: list[tuple[list[str], float, dict[str, str] | None, str | None]] = []

    def fake_run(args, timeout, env=None, *, cwd=None):
        calls.append((args, timeout, env, cwd))
        return "ok", "", 0, False

    monkeypatch.setattr(LocalSandbox, "_run_windows_command", staticmethod(fake_run))
    sandbox = LocalSandbox("t", [_MOUNT])

    result = sandbox.execute_program(
        "/root/tools/app.exe",
        ["--config", "/root/config.tfx-dms"],
        cwd="/root/tools",
        timeout=7,
    )

    assert result == "ok"
    assert len(calls) == 1
    args, timeout, _env, cwd = calls[0]
    assert args == [
        _windows_path(str(_LAUNCHER_ROOT / "tools" / "app.exe")),
        "--config",
        _native_path(str(_LAUNCHER_ROOT / "config.tfx-dms")),
    ]
    assert timeout == 7
    assert cwd == _windows_path(str(_LAUNCHER_ROOT / "tools"))


def test_execute_program_resolves_virtual_path_embedded_in_key_value_arg(monkeypatch) -> None:
    monkeypatch.setattr(local_sandbox, "_is_windows_native_program_platform", lambda: True)
    calls: list[list[str] | str] = []

    def fake_run(args, timeout, env=None, *, cwd=None):
        calls.append(args)
        return "ok", "", 0, False

    monkeypatch.setattr(LocalSandbox, "_run_windows_command", staticmethod(fake_run))
    sandbox = LocalSandbox("t", [_MOUNT])

    sandbox.execute_program("/root/tools/app.exe", ["--config=/root/config.tfx-dms"])

    assert calls[0][1] == f"--config={_native_path(str(_LAUNCHER_ROOT / 'config.tfx-dms'))}"


def test_execute_program_uses_cmd_call_for_cmd_files(monkeypatch) -> None:
    monkeypatch.setattr(local_sandbox, "_is_windows_native_program_platform", lambda: True)
    calls: list[list[str] | str] = []

    def fake_run(args, timeout, env=None, *, cwd=None):
        calls.append(args)
        return "ok", "", 0, False

    monkeypatch.setattr(LocalSandbox, "_run_windows_command", staticmethod(fake_run))
    shell_path = r"C:\Windows\System32\cmd.exe"
    monkeypatch.setattr(
        LocalSandbox,
        "_find_first_available_shell",
        staticmethod(lambda candidates: shell_path),
    )
    sandbox = LocalSandbox("t", [_MOUNT])

    sandbox.execute_program("/root/tools/build.cmd", ["--release"])

    assert isinstance(calls[0], str)
    expected_program = _windows_path(str(_LAUNCHER_ROOT / "tools" / "build.cmd"))
    expected_command = f"call {local_sandbox._quote_cmd_program_path(expected_program)} --release"
    assert calls[0] == f'{shell_path} /d /s /c "{expected_command}"'


def test_execute_program_batch_invocation_uses_single_helper(monkeypatch) -> None:
    monkeypatch.setattr(local_sandbox, "_is_windows_native_program_platform", lambda: True)
    monkeypatch.setattr(LocalSandbox, "_find_first_available_shell", staticmethod(lambda candidates: r"C:\Windows\System32\cmd.exe"))
    monkeypatch.setattr(LocalSandbox, "_run_windows_command", staticmethod(lambda *args, **kwargs: ("ok", "", 0, False)))
    sandbox = LocalSandbox("t", [_MOUNT])

    with patch.object(local_sandbox, "_build_cmd_invocation", wraps=local_sandbox._build_cmd_invocation) as helper:
        sandbox.execute_program("/root/tools/build.cmd", ["--release"])

    helper.assert_called_once()


@pytest.mark.parametrize("argument", [r"\\host\share\tool.exe", r"--tool=\\host\share\tool.exe"])
def test_execute_program_rejects_unmapped_absolute_argument(argument: str, monkeypatch) -> None:
    monkeypatch.setattr(local_sandbox, "_is_windows_native_program_platform", lambda: True)
    monkeypatch.setattr(LocalSandbox, "_find_first_available_shell", staticmethod(lambda candidates: r"C:\Windows\System32\cmd.exe"))
    monkeypatch.setattr(LocalSandbox, "_run_windows_command", staticmethod(lambda *args, **kwargs: ("ok", "", 0, False)))
    sandbox = LocalSandbox("t", [_MOUNT])

    with pytest.raises(PermissionError, match="program argument"):
        sandbox.execute_program("/root/tools/build.cmd", [argument])


def test_execute_program_allows_parentheses_in_configured_cmd_program_path(monkeypatch) -> None:
    monkeypatch.setattr(local_sandbox, "_is_windows_native_program_platform", lambda: True)
    calls: list[list[str] | str] = []

    def fake_run(args, timeout, env=None, *, cwd=None):
        calls.append(args)
        return "ok", "", 0, False

    shell_path = r"C:\Windows\System32\cmd.exe"
    monkeypatch.setattr(LocalSandbox, "_run_windows_command", staticmethod(fake_run))
    monkeypatch.setattr(LocalSandbox, "_find_first_available_shell", staticmethod(lambda candidates: shell_path))
    sandbox = LocalSandbox("t", [_MOUNT])

    sandbox.execute_program("/root/Program Files (x86)/build.cmd", ["--release"])

    expected_program = _windows_path(str(_LAUNCHER_ROOT / "Program Files (x86)" / "build.cmd"))
    expected_command = f"call {local_sandbox._quote_cmd_program_path(expected_program)} --release"
    assert calls == [f'{shell_path} /d /s /c "{expected_command}"']


@pytest.mark.parametrize("component", ["%TEMP%", "caret^dir"])
def test_execute_program_rejects_unsafe_cmd_program_path(component: str, monkeypatch) -> None:
    monkeypatch.setattr(local_sandbox, "_is_windows_native_program_platform", lambda: True)
    monkeypatch.setattr(LocalSandbox, "_find_first_available_shell", staticmethod(lambda candidates: r"C:\Windows\System32\cmd.exe"))
    sandbox = LocalSandbox("t", [_MOUNT])

    with pytest.raises(PermissionError, match="program paths may not contain"):
        sandbox.execute_program(f"/root/{component}/build.cmd")


def test_execute_program_rejects_unsafe_cmd_arguments(monkeypatch) -> None:
    monkeypatch.setattr(local_sandbox, "_is_windows_native_program_platform", lambda: True)
    shell_path = r"C:\Windows\System32\cmd.exe"
    monkeypatch.setattr(
        LocalSandbox,
        "_find_first_available_shell",
        staticmethod(lambda candidates: shell_path),
    )
    sandbox = LocalSandbox("t", [_MOUNT])

    with pytest.raises(PermissionError, match="cmd.exe arguments may not contain"):
        sandbox.execute_program("/root/tools/build.cmd", ["100% complete"])


def test_execute_program_quotes_cmd_arguments_with_safe_metacharacters(monkeypatch) -> None:
    monkeypatch.setattr(local_sandbox, "_is_windows_native_program_platform", lambda: True)
    calls: list[list[str] | str] = []

    def fake_run(args, timeout, env=None, *, cwd=None):
        calls.append(args)
        return "ok", "", 0, False

    monkeypatch.setattr(LocalSandbox, "_run_windows_command", staticmethod(fake_run))
    shell_path = r"C:\Windows\System32\cmd.exe"
    monkeypatch.setattr(LocalSandbox, "_find_first_available_shell", staticmethod(lambda candidates: shell_path))
    sandbox = LocalSandbox("t", [_MOUNT])

    sandbox.execute_program("/root/tools/build.cmd", ["--out", "/root/Program Files (x86)/out.log", "safe&value"])

    expected_program = _windows_path(str(_LAUNCHER_ROOT / "tools" / "build.cmd"))
    expected_output = str((_LAUNCHER_ROOT / "Program Files (x86)" / "out.log").resolve())
    expected_command = " ".join(
        [
            "call",
            local_sandbox._quote_cmd_program_path(expected_program),
            "--out",
            local_sandbox._quote_cmd_argument(expected_output),
            '"safe&value"',
        ]
    )
    assert calls == [f'{shell_path} /d /s /c "{expected_command}"']


def test_execute_program_quotes_cmd_arguments_with_spaces(monkeypatch) -> None:
    monkeypatch.setattr(local_sandbox, "_is_windows_native_program_platform", lambda: True)
    calls: list[list[str] | str] = []

    def fake_run(args, timeout, env=None, *, cwd=None):
        calls.append(args)
        return "ok", "", 0, False

    monkeypatch.setattr(LocalSandbox, "_run_windows_command", staticmethod(fake_run))
    monkeypatch.setattr(LocalSandbox, "_find_first_available_shell", staticmethod(lambda candidates: r"C:\Windows\System32\cmd.exe"))
    sandbox = LocalSandbox("t", [_MOUNT])

    sandbox.execute_program("/root/tools/build.cmd", ["hello world"])

    assert isinstance(calls[0], str)
    assert '"hello world"' in calls[0]


def test_execute_program_requires_a_mapped_program_path(monkeypatch) -> None:
    monkeypatch.setattr(local_sandbox, "_is_windows_native_program_platform", lambda: True)
    monkeypatch.setattr(LocalSandbox, "_run_windows_command", staticmethod(lambda *args, **kwargs: ("ok", "", 0, False)))
    sandbox = LocalSandbox("t", [_MOUNT])

    with pytest.raises(PermissionError, match="configured sandbox mount"):
        sandbox.execute_program(r"C:\Windows\System32\whoami.exe")


def test_execute_program_uses_powershell_file_for_ps1(monkeypatch) -> None:
    monkeypatch.setattr(local_sandbox, "_is_windows_native_program_platform", lambda: True)
    calls: list[list[str] | str] = []

    def fake_run(args, timeout, env=None, *, cwd=None):
        calls.append(args)
        return "ok", "", 0, False

    monkeypatch.setattr(LocalSandbox, "_run_windows_command", staticmethod(fake_run))
    monkeypatch.setattr(
        LocalSandbox,
        "_find_first_available_shell",
        staticmethod(lambda candidates: r"C:\Program Files\PowerShell\7\pwsh.exe"),
    )
    sandbox = LocalSandbox("t", [_MOUNT])

    sandbox.execute_program("/root/tools/build.ps1", ["-Config", "/root/config.tfx-dms"])

    assert calls == [
        [
            r"C:\Program Files\PowerShell\7\pwsh.exe",
            "-NoProfile",
            "-File",
            _windows_path(str(_LAUNCHER_ROOT / "tools" / "build.ps1")),
            "-Config",
            _native_path(str(_LAUNCHER_ROOT / "config.tfx-dms")),
        ]
    ]


@pytest.mark.skipif(os.name != "nt", reason="Windows native program launcher")
def test_execute_program_runs_a_real_cmd_file(tmp_path) -> None:
    script = tmp_path / "dir with spaces" / "hello.cmd"
    script.parent.mkdir()
    script.write_text("@echo off\necho cmd-ok\n", encoding="utf-8")
    sandbox = LocalSandbox("t", [PathMapping("/root", str(tmp_path), False)])

    output = sandbox.execute_program("/root/dir with spaces/hello.cmd", timeout=10)

    assert "cmd-ok" in output


@pytest.mark.skipif(os.name != "nt", reason="Windows native program launcher")
def test_execute_program_runs_a_real_powershell_file(tmp_path) -> None:
    script = tmp_path / "hello.ps1"
    script.write_text("Write-Output 'powershell-ok'\n", encoding="utf-8")
    sandbox = LocalSandbox("t", [PathMapping("/root", str(tmp_path), False)])

    output = sandbox.execute_program("/root/hello.ps1", timeout=10)

    assert "powershell-ok" in output


@pytest.mark.skipif(os.name != "nt", reason="Windows host-path compatibility")
def test_run_host_program_tool_normalizes_host_paths_before_launch(monkeypatch) -> None:
    monkeypatch.setattr(local_sandbox, "_is_windows_native_program_platform", lambda: True)
    calls: list[tuple[str, list[str], str | None]] = []

    class FakeSandbox:
        id = "local"

        def execute_program(self, program_path, args, *, cwd=None, env=None, timeout=None):
            calls.append((program_path, list(args), cwd))
            return "ok"

    runtime = SimpleNamespace(
        state={"sandbox": {"sandbox_id": "local"}, "thread_data": {}},
        context={"thread_id": "thread-1"},
        config={},
    )
    config = SimpleNamespace(
        sandbox=SandboxConfig(
            use="deerflow.sandbox.local:LocalSandboxProvider",
            allow_host_bash=True,
            mounts=_MOUNTS,
        )
    )

    with (
        patch("deerflow.sandbox.tools.ensure_sandbox_initialized", return_value=FakeSandbox()),
        patch("deerflow.sandbox.tools.is_local_sandbox", return_value=True),
        patch("deerflow.tools.builtins.run_host_program_tool.is_host_bash_allowed", return_value=True),
        patch("deerflow.sandbox.tools._get_custom_mounts", return_value=_WINDOWS_MOUNTS),
        patch("deerflow.config.get_app_config", return_value=config),
    ):
        result = run_host_program_tool.func(
            runtime,
            "运行构建脚本",
            r"C:\Users\lichen\tools\build.ps1",
            ["--config", r"C:\Users\lichen\config.tfx-dms"],
            r"C:\Users\lichen\tools",
            30,
        )

    assert result == "ok"
    assert calls == [
        (
            "/root/tools/build.ps1",
            ["--config", "/root/config.tfx-dms"],
            "/root/tools",
        )
    ]


@pytest.mark.skipif(os.name != "nt", reason="Windows host-path compatibility")
def test_run_host_program_tool_rejects_program_outside_custom_mount(monkeypatch) -> None:
    monkeypatch.setattr(local_sandbox, "_is_windows_native_program_platform", lambda: True)
    runtime = SimpleNamespace(
        state={"sandbox": {"sandbox_id": "local"}, "thread_data": {}},
        context={"thread_id": "thread-1"},
        config={},
    )
    with (
        patch("deerflow.sandbox.tools.ensure_sandbox_initialized", return_value=SimpleNamespace(execute_program=lambda *args, **kwargs: "ok")),
        patch("deerflow.sandbox.tools.is_local_sandbox", return_value=True),
        patch("deerflow.tools.builtins.run_host_program_tool.is_host_bash_allowed", return_value=True),
        patch("deerflow.sandbox.tools._get_custom_mounts", return_value=_WINDOWS_MOUNTS),
    ):
        result = run_host_program_tool.func(runtime, "运行程序", r"C:\Windows\System32\whoami.exe")

    assert "Host path is not allowed" in result


def test_run_host_program_tool_rejects_unsupported_extension(monkeypatch) -> None:
    monkeypatch.setattr(run_host_program_module, "_is_windows_host_program_platform", lambda: True)
    runtime = SimpleNamespace(
        state={"sandbox": {"sandbox_id": "local"}, "thread_data": {}},
        context={"thread_id": "thread-1"},
        config={},
    )
    with (
        patch("deerflow.sandbox.tools.ensure_sandbox_initialized", return_value=SimpleNamespace(execute_program=lambda *args, **kwargs: "ok")),
        patch("deerflow.sandbox.tools.is_local_sandbox", return_value=True),
        patch("deerflow.tools.builtins.run_host_program_tool.is_host_bash_allowed", return_value=True),
        patch("deerflow.sandbox.tools._get_custom_mounts", return_value=_MOUNTS),
    ):
        result = run_host_program_tool.func(runtime, "运行程序", "/root/tools/build.py")

    assert "Only .exe, .cmd, .bat, and .ps1" in result


def test_trusted_local_windows_runtime_exposes_native_program_tool(monkeypatch) -> None:
    import deerflow.tools.tools as tools_module

    config = SimpleNamespace(
        tools=[],
        models=[],
        sandbox=SimpleNamespace(use="deerflow.sandbox.local:LocalSandboxProvider"),
        tool_search=SimpleNamespace(enabled=False),
        skill_evolution=SimpleNamespace(enabled=False),
        acp_agents={},
    )
    monkeypatch.setattr(tools_module.os, "name", "nt")
    monkeypatch.setattr(tools_module, "uses_local_sandbox_provider", lambda _config: True)
    monkeypatch.setattr(tools_module, "is_host_bash_allowed", lambda _config: True)
    monkeypatch.setattr(tools_module, "BUILTIN_TOOLS", [])

    loaded = tools_module.get_available_tools(
        include_mcp=False,
        include_upload_tool=False,
        app_config=config,
    )

    assert [tool.name for tool in loaded] == ["run_host_program"]


def test_execute_program_rejects_unmapped_cwd(monkeypatch) -> None:
    monkeypatch.setattr(local_sandbox, "_is_windows_native_program_platform", lambda: True)
    monkeypatch.setattr(LocalSandbox, "_run_windows_command", staticmethod(lambda *args, **kwargs: ("ok", "", 0, False)))
    sandbox = LocalSandbox("t", [_MOUNT])

    with pytest.raises(PermissionError, match="working directory"):
        sandbox.execute_program("/root/tools/app.exe", cwd=r"C:\Windows\System32")


def test_execute_program_rejects_non_windows(monkeypatch) -> None:
    monkeypatch.setattr(local_sandbox, "_is_windows_native_program_platform", lambda: False)
    sandbox = LocalSandbox("t", [_MOUNT])

    with pytest.raises(RuntimeError, match="only available on Windows"):
        sandbox.execute_program("/root/tools/app.exe")
