"""Tests for sandbox tool helper functions: virtual path resolution, runtime extraction, and sandbox lifecycle."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.config.paths import VIRTUAL_PATH_PREFIX
from src.sandbox.exceptions import SandboxNotFoundError, SandboxRuntimeError
from src.sandbox.tools import (
    ensure_sandbox_initialized,
    ensure_thread_directories_exist,
    get_thread_data,
    is_local_sandbox,
    replace_virtual_path,
    replace_virtual_paths_in_command,
    sandbox_from_runtime,
)


def _make_runtime(state: dict | None = None, context: dict | None = None) -> SimpleNamespace:
    """Create a lightweight runtime object with dict state/context that supports .get() natively."""
    return SimpleNamespace(state=state, context=context or {})


# ---------------------------------------------------------------------------
# replace_virtual_path
# ---------------------------------------------------------------------------
class TestReplaceVirtualPath:
    """Tests for replace_virtual_path()."""

    def _thread_data(self, tmp_path: Path) -> dict:
        return {
            "workspace_path": str(tmp_path / "ws"),
            "uploads_path": str(tmp_path / "up"),
            "outputs_path": str(tmp_path / "out"),
        }

    def test_workspace_mapping(self, tmp_path: Path) -> None:
        td = self._thread_data(tmp_path)
        result = replace_virtual_path(f"{VIRTUAL_PATH_PREFIX}/workspace/file.py", td)
        assert result == f"{tmp_path}/ws/file.py"

    def test_uploads_mapping(self, tmp_path: Path) -> None:
        td = self._thread_data(tmp_path)
        result = replace_virtual_path(f"{VIRTUAL_PATH_PREFIX}/uploads/data.csv", td)
        assert result == f"{tmp_path}/up/data.csv"

    def test_outputs_mapping(self, tmp_path: Path) -> None:
        td = self._thread_data(tmp_path)
        result = replace_virtual_path(f"{VIRTUAL_PATH_PREFIX}/outputs/result.json", td)
        assert result == f"{tmp_path}/out/result.json"

    def test_unknown_subdir_returns_original(self, tmp_path: Path) -> None:
        td = self._thread_data(tmp_path)
        path = f"{VIRTUAL_PATH_PREFIX}/unknown/file.txt"
        assert replace_virtual_path(path, td) == path

    def test_none_thread_data_returns_original(self) -> None:
        path = f"{VIRTUAL_PATH_PREFIX}/workspace/file.py"
        assert replace_virtual_path(path, None) == path

    def test_non_virtual_path_passthrough(self, tmp_path: Path) -> None:
        td = self._thread_data(tmp_path)
        path = "/home/user/file.py"
        assert replace_virtual_path(path, td) == path

    def test_bare_prefix_returns_original(self, tmp_path: Path) -> None:
        td = self._thread_data(tmp_path)
        assert replace_virtual_path(VIRTUAL_PATH_PREFIX, td) == VIRTUAL_PATH_PREFIX

    def test_bare_prefix_with_slash_returns_original(self, tmp_path: Path) -> None:
        td = self._thread_data(tmp_path)
        assert replace_virtual_path(f"{VIRTUAL_PATH_PREFIX}/", td) == f"{VIRTUAL_PATH_PREFIX}/"

    def test_workspace_subdir_no_file(self, tmp_path: Path) -> None:
        td = self._thread_data(tmp_path)
        result = replace_virtual_path(f"{VIRTUAL_PATH_PREFIX}/workspace", td)
        assert result == str(tmp_path / "ws")

    def test_nested_path(self, tmp_path: Path) -> None:
        td = self._thread_data(tmp_path)
        result = replace_virtual_path(f"{VIRTUAL_PATH_PREFIX}/workspace/dir/sub/file.py", td)
        assert result == f"{tmp_path}/ws/dir/sub/file.py"


# ---------------------------------------------------------------------------
# replace_virtual_paths_in_command
# ---------------------------------------------------------------------------
class TestReplaceVirtualPathsInCommand:
    """Tests for replace_virtual_paths_in_command()."""

    def _thread_data(self, tmp_path: Path) -> dict:
        return {
            "workspace_path": str(tmp_path / "ws"),
            "uploads_path": str(tmp_path / "up"),
            "outputs_path": str(tmp_path / "out"),
        }

    def test_single_path_replacement(self, tmp_path: Path) -> None:
        td = self._thread_data(tmp_path)
        cmd = f"cat {VIRTUAL_PATH_PREFIX}/workspace/file.py"
        result = replace_virtual_paths_in_command(cmd, td)
        assert result == f"cat {tmp_path}/ws/file.py"

    def test_multiple_path_replacement(self, tmp_path: Path) -> None:
        td = self._thread_data(tmp_path)
        cmd = f"cp {VIRTUAL_PATH_PREFIX}/uploads/data.csv {VIRTUAL_PATH_PREFIX}/outputs/result.csv"
        result = replace_virtual_paths_in_command(cmd, td)
        assert f"{tmp_path}/up/data.csv" in result
        assert f"{tmp_path}/out/result.csv" in result

    def test_no_virtual_paths_passthrough(self, tmp_path: Path) -> None:
        td = self._thread_data(tmp_path)
        cmd = "ls -la /home/user"
        assert replace_virtual_paths_in_command(cmd, td) == cmd

    def test_none_thread_data_returns_command(self) -> None:
        cmd = f"cat {VIRTUAL_PATH_PREFIX}/workspace/file.py"
        assert replace_virtual_paths_in_command(cmd, None) == cmd

    def test_command_without_prefix_passthrough(self) -> None:
        cmd = "echo hello"
        assert replace_virtual_paths_in_command(cmd, {}) == cmd


# ---------------------------------------------------------------------------
# get_thread_data
# ---------------------------------------------------------------------------
class TestGetThreadData:
    """Tests for get_thread_data()."""

    def test_valid_runtime(self) -> None:
        runtime = _make_runtime(state={"thread_data": {"workspace_path": "/ws"}})
        assert get_thread_data(runtime) == {"workspace_path": "/ws"}

    def test_none_runtime(self) -> None:
        assert get_thread_data(None) is None

    def test_none_state(self) -> None:
        runtime = _make_runtime(state=None)
        assert get_thread_data(runtime) is None


# ---------------------------------------------------------------------------
# is_local_sandbox
# ---------------------------------------------------------------------------
class TestIsLocalSandbox:
    """Tests for is_local_sandbox()."""

    def test_true_for_local(self) -> None:
        runtime = _make_runtime(state={"sandbox": {"sandbox_id": "local"}})
        assert is_local_sandbox(runtime) is True

    def test_false_for_non_local(self) -> None:
        runtime = _make_runtime(state={"sandbox": {"sandbox_id": "aio-123"}})
        assert is_local_sandbox(runtime) is False

    def test_false_no_sandbox_state(self) -> None:
        runtime = _make_runtime(state={})
        assert is_local_sandbox(runtime) is False

    def test_false_none_runtime(self) -> None:
        assert is_local_sandbox(None) is False

    def test_false_none_state(self) -> None:
        runtime = _make_runtime(state=None)
        assert is_local_sandbox(runtime) is False


# ---------------------------------------------------------------------------
# sandbox_from_runtime
# ---------------------------------------------------------------------------
class TestSandboxFromRuntime:
    """Tests for sandbox_from_runtime()."""

    def test_none_runtime_raises(self) -> None:
        with pytest.raises(SandboxRuntimeError, match="Tool runtime not available"):
            sandbox_from_runtime(None)

    def test_none_state_raises(self) -> None:
        runtime = _make_runtime(state=None)
        with pytest.raises(SandboxRuntimeError, match="Tool runtime state not available"):
            sandbox_from_runtime(runtime)

    def test_no_sandbox_state_raises(self) -> None:
        runtime = _make_runtime(state={})
        with pytest.raises(SandboxRuntimeError, match="Sandbox state not initialized"):
            sandbox_from_runtime(runtime)

    def test_no_sandbox_id_raises(self) -> None:
        runtime = _make_runtime(state={"sandbox": {}})
        with pytest.raises(SandboxRuntimeError, match="Sandbox ID not found"):
            sandbox_from_runtime(runtime)

    @patch("src.sandbox.tools.get_sandbox_provider")
    def test_sandbox_not_found_raises(self, mock_provider_fn) -> None:
        mock_provider = MagicMock()
        mock_provider.get.return_value = None
        mock_provider_fn.return_value = mock_provider

        runtime = _make_runtime(state={"sandbox": {"sandbox_id": "missing-123"}})
        with pytest.raises(SandboxNotFoundError, match="not found"):
            sandbox_from_runtime(runtime)

    @patch("src.sandbox.tools.get_sandbox_provider")
    def test_success(self, mock_provider_fn) -> None:
        fake_sandbox = MagicMock()
        mock_provider = MagicMock()
        mock_provider.get.return_value = fake_sandbox
        mock_provider_fn.return_value = mock_provider

        runtime = _make_runtime(state={"sandbox": {"sandbox_id": "local"}})
        result = sandbox_from_runtime(runtime)
        assert result is fake_sandbox


# ---------------------------------------------------------------------------
# ensure_sandbox_initialized
# ---------------------------------------------------------------------------
class TestEnsureSandboxInitialized:
    """Tests for ensure_sandbox_initialized()."""

    def test_none_runtime_raises(self) -> None:
        with pytest.raises(SandboxRuntimeError, match="Tool runtime not available"):
            ensure_sandbox_initialized(None)

    def test_none_state_raises(self) -> None:
        runtime = _make_runtime(state=None)
        with pytest.raises(SandboxRuntimeError, match="Tool runtime state not available"):
            ensure_sandbox_initialized(runtime)

    @patch("src.sandbox.tools.get_sandbox_provider")
    def test_reuses_existing_sandbox(self, mock_provider_fn) -> None:
        fake_sandbox = MagicMock()
        mock_provider = MagicMock()
        mock_provider.get.return_value = fake_sandbox
        mock_provider_fn.return_value = mock_provider

        runtime = _make_runtime(state={"sandbox": {"sandbox_id": "local"}})
        result = ensure_sandbox_initialized(runtime)
        assert result is fake_sandbox
        mock_provider.acquire.assert_not_called()

    @patch("src.sandbox.tools.get_sandbox_provider")
    def test_lazy_acquires_new_sandbox(self, mock_provider_fn) -> None:
        fake_sandbox = MagicMock()
        mock_provider = MagicMock()
        mock_provider.acquire.return_value = "new-sandbox-id"
        mock_provider.get.return_value = fake_sandbox
        mock_provider_fn.return_value = mock_provider

        state: dict = {}
        runtime = _make_runtime(state=state, context={"thread_id": "thread-1", "user_id": "user-1"})

        result = ensure_sandbox_initialized(runtime)
        assert result is fake_sandbox
        mock_provider.acquire.assert_called_once_with("thread-1", user_id="user-1")
        assert state["sandbox"]["sandbox_id"] == "new-sandbox-id"

    @patch("src.sandbox.tools.get_sandbox_provider")
    def test_no_thread_id_raises(self, mock_provider_fn) -> None:
        runtime = _make_runtime(state={}, context={})
        with pytest.raises(SandboxRuntimeError, match="Thread ID not available"):
            ensure_sandbox_initialized(runtime)


# ---------------------------------------------------------------------------
# ensure_thread_directories_exist
# ---------------------------------------------------------------------------
class TestEnsureThreadDirectoriesExist:
    """Tests for ensure_thread_directories_exist()."""

    def test_creates_dirs_for_local(self, tmp_path: Path) -> None:
        ws = tmp_path / "ws"
        up = tmp_path / "up"
        out = tmp_path / "out"

        state = {
            "sandbox": {"sandbox_id": "local"},
            "thread_data": {
                "workspace_path": str(ws),
                "uploads_path": str(up),
                "outputs_path": str(out),
            },
            "thread_directories_created": False,
        }
        runtime = _make_runtime(state=state)

        ensure_thread_directories_exist(runtime)

        assert ws.is_dir()
        assert up.is_dir()
        assert out.is_dir()
        assert state["thread_directories_created"] is True

    def test_skips_non_local(self, tmp_path: Path) -> None:
        state = {
            "sandbox": {"sandbox_id": "aio-1"},
            "thread_data": {
                "workspace_path": str(tmp_path / "ws"),
            },
        }
        runtime = _make_runtime(state=state)

        ensure_thread_directories_exist(runtime)
        assert not (tmp_path / "ws").exists()

    def test_none_runtime(self) -> None:
        ensure_thread_directories_exist(None)

    def test_skips_if_already_created(self, tmp_path: Path) -> None:
        state = {
            "sandbox": {"sandbox_id": "local"},
            "thread_data": {
                "workspace_path": str(tmp_path / "ws"),
                "uploads_path": str(tmp_path / "up"),
                "outputs_path": str(tmp_path / "out"),
            },
            "thread_directories_created": True,
        }
        runtime = _make_runtime(state=state)

        ensure_thread_directories_exist(runtime)
        assert not (tmp_path / "ws").exists()
