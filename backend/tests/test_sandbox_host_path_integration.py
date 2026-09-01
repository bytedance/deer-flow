from __future__ import annotations

import importlib
import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from deerflow.config.sandbox_config import SandboxConfig, VolumeMountConfig
from deerflow.sandbox.exceptions import SandboxNotFoundError
from deerflow.sandbox.tools import (
    bash_tool,
    grep_tool,
    read_file_tool,
    validate_local_tool_path,
)
from deerflow.tools.builtins.run_host_program_tool import run_host_program_tool
from deerflow.tools.builtins.view_image_tool import view_image_tool

run_host_program_module = importlib.import_module("deerflow.tools.builtins.run_host_program_tool")
sandbox_tools = importlib.import_module("deerflow.sandbox.tools")

_THREAD_DATA = {
    "workspace_path": r"C:\Users\lichen\thread-workspace",
    "uploads_path": r"C:\Users\lichen\thread-uploads",
    "outputs_path": r"C:\Users\lichen\thread-outputs",
}
_POSIX_THREAD_DATA = {
    "workspace_path": "/tmp/deer-flow/thread-workspace",
    "uploads_path": "/tmp/deer-flow/thread-uploads",
    "outputs_path": "/tmp/deer-flow/thread-outputs",
}
_MOUNTS = [
    VolumeMountConfig(
        host_path=r"C:\Users\lichen",
        container_path="/root",
        read_only=False,
    )
]


def _runtime() -> SimpleNamespace:
    return SimpleNamespace(
        state={
            "sandbox": {"sandbox_id": "local"},
            "thread_data": _THREAD_DATA,
        },
        context={"thread_id": "thread-1"},
        config={},
    )


def _config() -> SimpleNamespace:
    return SimpleNamespace(
        sandbox=SandboxConfig(
            use="deerflow.sandbox.local:LocalSandboxProvider",
            allow_host_bash=True,
            mounts=_MOUNTS,
        )
    )


def _message_content(result) -> str:
    return result.update["messages"][0].content


@pytest.mark.skipif(os.name != "nt", reason="Windows host-path compatibility")
def test_validate_local_tool_path_accepts_configured_windows_host_path() -> None:
    """File tools may use the configured host spelling at their public boundary."""
    with patch("deerflow.sandbox.tools._get_custom_mounts", return_value=_MOUNTS):
        validate_local_tool_path(r"C:\Users\lichen\config.tfx-dms", _THREAD_DATA, read_only=True)


@pytest.mark.skipif(os.name != "nt", reason="Windows host-path compatibility")
def test_bash_tool_normalizes_configured_host_path_before_validation() -> None:
    calls: list[str] = []

    class FakeSandbox:
        id = "local"

        def execute_command(self, command: str, env=None, timeout=None) -> str:
            calls.append(command)
            return "ok"

    runtime = _runtime()
    with (
        patch("deerflow.sandbox.tools.ensure_sandbox_initialized", return_value=FakeSandbox()),
        patch("deerflow.sandbox.tools.ensure_thread_directories_exist"),
        patch("deerflow.sandbox.tools.is_local_sandbox", return_value=True),
        patch("deerflow.sandbox.tools.is_host_bash_allowed", return_value=True),
        patch.object(sandbox_tools, "normalize_local_command", wraps=sandbox_tools.normalize_local_command) as normalize,
        patch("deerflow.sandbox.tools._get_custom_mounts", return_value=_MOUNTS),
        patch("deerflow.sandbox.tools.get_app_config", return_value=_config()),
        patch("deerflow.sandbox.tools._lark_cli_env_from_runtime", return_value=None),
    ):
        result = bash_tool.func(
            runtime=runtime,
            description="统计挂载目录",
            command=r"find C:\Users\lichen -mindepth 1 -maxdepth 1 -type d",
        )

    assert result == "ok"
    assert len(calls) == 1
    assert calls[0].endswith("find /root -mindepth 1 -maxdepth 1 -type d")
    normalize.assert_called_once()


@pytest.mark.skipif(os.name != "nt", reason="Windows host-path compatibility")
def test_read_file_tool_passes_virtual_path_for_configured_windows_host_path() -> None:
    calls: list[str] = []

    class FakeSandbox:
        id = "local"

        def read_file(self, path: str, start_line=None, end_line=None) -> str:
            calls.append(path)
            return "config"

    runtime = _runtime()
    with (
        patch("deerflow.sandbox.tools.ensure_sandbox_initialized", return_value=FakeSandbox()),
        patch("deerflow.sandbox.tools.ensure_thread_directories_exist"),
        patch("deerflow.sandbox.tools.is_local_sandbox", return_value=True),
        patch("deerflow.sandbox.tools._get_custom_mounts", return_value=_MOUNTS),
    ):
        result = read_file_tool.func(
            runtime=runtime,
            description="读取配置",
            path=r"C:\Users\lichen\config.tfx-dms",
        )

    assert result == "config"
    assert calls == ["/root/config.tfx-dms"]


@pytest.mark.skipif(os.name != "nt", reason="Windows host-path compatibility")
def test_grep_tool_normalizes_configured_windows_host_path() -> None:
    calls: list[str] = []

    class FakeSandbox:
        id = "local"

        def grep(self, path: str, pattern: str, **kwargs):
            calls.append(path)
            return [], False

    runtime = _runtime()
    with (
        patch("deerflow.sandbox.tools.ensure_sandbox_initialized", return_value=FakeSandbox()),
        patch("deerflow.sandbox.tools.ensure_thread_directories_exist"),
        patch("deerflow.sandbox.tools.is_local_sandbox", return_value=True),
        patch("deerflow.sandbox.tools._get_custom_mounts", return_value=_MOUNTS),
    ):
        result = grep_tool.func(
            runtime=runtime,
            description="搜索配置",
            pattern="needle",
            path=r"C:\Users\lichen\config.tfx-dms",
        )

    assert result == "No matches found under C:\\Users\\lichen\\config.tfx-dms"
    assert calls == ["/root/config.tfx-dms"]


@pytest.mark.skipif(os.name != "nt", reason="Windows host-path compatibility")
def test_view_image_tool_normalizes_configured_windows_host_path() -> None:
    """Image reads use the same local host-path compatibility boundary."""
    runtime = _runtime()
    with (
        patch("deerflow.sandbox.tools.get_thread_data", return_value=_THREAD_DATA),
        patch("deerflow.sandbox.tools.is_local_sandbox", return_value=True),
        patch("deerflow.sandbox.tools.normalize_local_tool_path", return_value="/root/chart.png") as normalize,
        patch("deerflow.sandbox.tools.validate_local_tool_path"),
        patch("deerflow.sandbox.tools.resolve_and_validate_user_data_path", return_value=r"C:\Users\lichen\chart.png"),
        patch("deerflow.tools.builtins.view_image_tool.Path.exists", return_value=False),
    ):
        view_image_tool.func(runtime, r"C:\Users\lichen\chart.png", "call-1")

    normalize.assert_called_once_with(r"C:\Users\lichen\chart.png")


def test_view_image_tool_reads_image_from_custom_mount(tmp_path) -> None:
    from base64 import b64decode

    image_path = tmp_path / "chart.png"
    image_path.write_bytes(b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="))
    mount = VolumeMountConfig(host_path=str(tmp_path), container_path="/root", read_only=True)
    runtime = SimpleNamespace(
        state={"sandbox": {"sandbox_id": "local"}, "thread_data": _POSIX_THREAD_DATA},
        context={"thread_id": "thread-1"},
        config={},
    )
    with (
        patch("deerflow.sandbox.tools._get_custom_mounts", return_value=[mount]),
        patch("deerflow.sandbox.tools.ensure_sandbox_initialized") as acquire,
    ):
        from deerflow.sandbox.local.local_sandbox import LocalSandbox, PathMapping

        acquire.return_value = LocalSandbox("local", [PathMapping("/root", str(tmp_path), True)])
        result = view_image_tool.func(runtime, "/root/chart.png", "call-custom-image")

    assert _message_content(result) == "Successfully read image"
    assert result.update["viewed_images"]["/root/chart.png"]["actual_path"] == str(image_path)


def test_view_image_user_data_does_not_acquire_sandbox() -> None:
    runtime = _runtime()
    with (
        patch("deerflow.sandbox.tools.get_thread_data", return_value=_THREAD_DATA),
        patch("deerflow.sandbox.tools.is_local_sandbox", return_value=True),
        patch("deerflow.sandbox.tools.normalize_local_tool_path", return_value="/mnt/user-data/uploads/chart.png"),
        patch("deerflow.sandbox.tools.validate_local_tool_path"),
        patch("deerflow.sandbox.tools.resolve_and_validate_user_data_path", return_value=r"C:\Users\lichen\chart.png"),
        patch("deerflow.sandbox.tools.ensure_sandbox_initialized") as acquire,
        patch("deerflow.tools.builtins.view_image_tool.Path.exists", return_value=False),
    ):
        view_image_tool.func(runtime, r"C:\Users\lichen\chart.png", "call-user-data")

    acquire.assert_not_called()


def test_view_image_custom_mount_converts_acquisition_error_to_tool_message() -> None:
    runtime = _runtime()
    with (
        patch("deerflow.sandbox.tools.get_thread_data", return_value=_THREAD_DATA),
        patch("deerflow.sandbox.tools.is_local_sandbox", return_value=True),
        patch("deerflow.sandbox.tools.normalize_local_tool_path", return_value="/root/chart.png"),
        patch("deerflow.sandbox.tools._is_custom_mount_path", return_value=True),
        patch("deerflow.sandbox.tools.validate_local_tool_path"),
        patch("deerflow.sandbox.tools.ensure_sandbox_initialized", side_effect=SandboxNotFoundError()),
    ):
        result = view_image_tool.func(runtime, r"C:\Users\lichen\chart.png", "call-custom-error")

    assert _message_content(result) == "Error: Sandbox not found"


def test_view_image_custom_mount_read_error_does_not_leak_host_path(tmp_path, monkeypatch) -> None:
    from base64 import b64decode

    image_path = tmp_path / "chart.png"
    image_path.write_bytes(b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="))
    mount = VolumeMountConfig(host_path=str(tmp_path), container_path="/root", read_only=True)
    runtime = SimpleNamespace(
        state={"sandbox": {"sandbox_id": "local"}, "thread_data": _POSIX_THREAD_DATA},
        context={"thread_id": "thread-1"},
        config={},
    )
    real_open = open

    def fail_custom_mount_open(file, *args, **kwargs):
        if str(file) == str(image_path):
            raise PermissionError(f"permission denied: {image_path}")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr("builtins.open", fail_custom_mount_open)
    with (
        patch("deerflow.sandbox.tools._get_custom_mounts", return_value=[mount]),
        patch("deerflow.sandbox.tools.ensure_sandbox_initialized") as acquire,
    ):
        from deerflow.sandbox.local.local_sandbox import LocalSandbox, PathMapping

        acquire.return_value = LocalSandbox("local", [PathMapping("/root", str(tmp_path), True)])
        result = view_image_tool.func(runtime, "/root/chart.png", "call-custom-read-error")

    message = _message_content(result)
    assert "Error reading image file" in message
    assert str(image_path) not in message
    assert "/root/chart.png" in message


def test_run_host_program_clamps_model_timeout_to_sandbox_limit() -> None:
    calls: list[float | None] = []

    class FakeSandbox:
        id = "local"

        def execute_program(self, program_path, args, *, cwd=None, env=None, timeout=None):
            calls.append(timeout)
            return "ok"

    runtime = SimpleNamespace(
        state={"sandbox": {"sandbox_id": "local"}, "thread_data": _POSIX_THREAD_DATA},
        context={"thread_id": "thread-1"},
        config={},
    )
    config = SimpleNamespace(
        sandbox=SandboxConfig(
            use="deerflow.sandbox.local:LocalSandboxProvider",
            allow_host_bash=True,
            mounts=_MOUNTS,
            bash_command_timeout=12,
        )
    )
    with (
        patch.object(run_host_program_module, "_is_windows_host_program_platform", return_value=True),
        patch("deerflow.sandbox.tools.ensure_sandbox_initialized", return_value=FakeSandbox()),
        patch("deerflow.sandbox.tools.is_local_sandbox", return_value=True),
        patch("deerflow.tools.builtins.run_host_program_tool.is_host_bash_allowed", return_value=True),
        patch("deerflow.sandbox.tools._get_custom_mounts", return_value=_MOUNTS),
        patch("deerflow.config.get_app_config", return_value=config),
    ):
        result = run_host_program_tool.func(
            runtime,
            "运行程序",
            "/root/tools/build.exe",
            [],
            None,
            99,
        )

    assert result == "ok"
    assert calls == [12]


def test_run_host_program_launch_error_does_not_leak_host_path(tmp_path) -> None:
    host_program = tmp_path / "tools" / "build.exe"
    mount = VolumeMountConfig(host_path=str(tmp_path), container_path="/root", read_only=False)

    class FailingSandbox:
        id = "local"

        def _reverse_resolve_paths_in_output(self, output: str) -> str:
            return output.replace(str(host_program), "/root/tools/build.exe")

        def execute_program(self, *args, **kwargs):
            raise PermissionError(f"permission denied: {host_program}")

    runtime = SimpleNamespace(
        state={"sandbox": {"sandbox_id": "local"}, "thread_data": _POSIX_THREAD_DATA},
        context={"thread_id": "thread-1"},
        config={},
    )
    config = SimpleNamespace(
        sandbox=SandboxConfig(
            use="deerflow.sandbox.local:LocalSandboxProvider",
            allow_host_bash=True,
            mounts=[mount],
            bash_command_timeout=12,
        )
    )
    with (
        patch.object(run_host_program_module, "_is_windows_host_program_platform", return_value=True),
        patch("deerflow.sandbox.tools.ensure_sandbox_initialized", return_value=FailingSandbox()),
        patch("deerflow.sandbox.tools.is_local_sandbox", return_value=True),
        patch("deerflow.tools.builtins.run_host_program_tool.is_host_bash_allowed", return_value=True),
        patch("deerflow.sandbox.tools._get_custom_mounts", return_value=[mount]),
        patch("deerflow.config.get_app_config", return_value=config),
    ):
        result = run_host_program_tool.func(
            runtime=runtime,
            description="run program",
            program_path="/root/tools/build.exe",
            args=[],
        )

    assert str(host_program) not in result
    assert result == "Error: Permission denied: PermissionError: permission denied: /root/tools/build.exe"


def test_run_host_program_rejects_non_custom_mount_cwd() -> None:
    calls = 0

    class FakeSandbox:
        id = "local"

        def execute_program(self, *args, **kwargs):
            nonlocal calls
            calls += 1
            return "ok"

    runtime = SimpleNamespace(
        state={"sandbox": {"sandbox_id": "local"}, "thread_data": _POSIX_THREAD_DATA},
        context={"thread_id": "thread-1"},
        config={},
    )
    config = SimpleNamespace(
        sandbox=SandboxConfig(
            use="deerflow.sandbox.local:LocalSandboxProvider",
            allow_host_bash=True,
            mounts=_MOUNTS,
            bash_command_timeout=12,
        )
    )
    with (
        patch.object(run_host_program_module, "_is_windows_host_program_platform", return_value=True),
        patch("deerflow.sandbox.tools.ensure_sandbox_initialized") as acquire,
        patch("deerflow.sandbox.tools.is_local_sandbox", return_value=True),
        patch("deerflow.tools.builtins.run_host_program_tool.is_host_bash_allowed", return_value=True),
        patch("deerflow.sandbox.tools._get_custom_mounts", return_value=_MOUNTS),
        patch("deerflow.config.get_app_config", return_value=config),
    ):
        result = run_host_program_tool.func(
            runtime,
            "运行程序",
            "/root/tools/build.exe",
            [],
            "/mnt/user-data/workspace",
            30,
        )

    assert result == "Error: Working directory must be inside a configured sandbox mount"
    assert calls == 0
    acquire.assert_not_called()


@pytest.mark.parametrize("timeout", [0, -1])
def test_run_host_program_rejects_non_positive_timeout(timeout: float) -> None:
    calls = 0

    class FakeSandbox:
        id = "local"

        def execute_program(self, *args, **kwargs):
            nonlocal calls
            calls += 1
            return "ok"

    runtime = SimpleNamespace(
        state={"sandbox": {"sandbox_id": "local"}, "thread_data": _POSIX_THREAD_DATA},
        context={"thread_id": "thread-1"},
        config={},
    )
    config = SimpleNamespace(
        sandbox=SandboxConfig(
            use="deerflow.sandbox.local:LocalSandboxProvider",
            allow_host_bash=True,
            mounts=_MOUNTS,
            bash_command_timeout=12,
        )
    )
    with (
        patch.object(run_host_program_module, "_is_windows_host_program_platform", return_value=True),
        patch("deerflow.sandbox.tools.ensure_sandbox_initialized", return_value=FakeSandbox()),
        patch("deerflow.sandbox.tools.is_local_sandbox", return_value=True),
        patch("deerflow.tools.builtins.run_host_program_tool.is_host_bash_allowed", return_value=True),
        patch("deerflow.sandbox.tools._get_custom_mounts", return_value=_MOUNTS),
        patch("deerflow.config.get_app_config", return_value=config),
    ):
        result = run_host_program_tool.func(
            runtime,
            "运行程序",
            "/root/tools/build.exe",
            [],
            None,
            timeout,
        )

    assert "timeout must be positive" in result
    assert calls == 0


@pytest.mark.skipif(os.name != "nt", reason="Windows host-path compatibility")
@pytest.mark.parametrize("path", [r"C:\Users\other\secret.txt", r"D:\Users\lichen\secret.txt"])
def test_unconfigured_windows_host_path_still_rejected(path: str) -> None:
    with patch("deerflow.sandbox.tools._get_custom_mounts", return_value=_MOUNTS):
        with pytest.raises(PermissionError, match="Host path is not allowed"):
            validate_local_tool_path(path, _THREAD_DATA, read_only=True)
