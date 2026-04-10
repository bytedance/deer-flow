"""Tests for deerflow.config.paths — Paths class and path utilities.

Tests the centralized path configuration for DeerFlow application data,
including thread directory management, virtual path resolution, and
cross-platform host-path joining.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path, PureWindowsPath
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Ensure heavy dependencies are mocked before importing deerflow modules.
# This allows running the test suite without the full dependency tree.
# ---------------------------------------------------------------------------
for _mod in ("yaml", "dotenv", "langchain", "langchain_core", "langchain_core.tools"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

_harness_path = str(Path(__file__).resolve().parents[1] / "packages" / "harness")
if _harness_path not in sys.path:
    sys.path.insert(0, _harness_path)

from deerflow.config.paths import (  # noqa: E402
    VIRTUAL_PATH_PREFIX,
    Paths,
    _join_host_path,
    _validate_thread_id,
    get_paths,
    resolve_path,
)
import deerflow.config.paths as _paths_mod  # noqa: E402


# ---------------------------------------------------------------------------
# _validate_thread_id
# ---------------------------------------------------------------------------


class TestValidateThreadId:
    def test_valid_alphanumeric(self):
        assert _validate_thread_id("abc123") == "abc123"

    def test_valid_with_hyphens_and_underscores(self):
        assert _validate_thread_id("thread-1_abc") == "thread-1_abc"

    def test_rejects_path_separators(self):
        with pytest.raises(ValueError, match="Invalid thread_id"):
            _validate_thread_id("../etc/passwd")

    def test_rejects_dots(self):
        with pytest.raises(ValueError, match="Invalid thread_id"):
            _validate_thread_id("thread..id")

    def test_rejects_spaces(self):
        with pytest.raises(ValueError, match="Invalid thread_id"):
            _validate_thread_id("thread id")

    def test_rejects_empty_string(self):
        with pytest.raises(ValueError, match="Invalid thread_id"):
            _validate_thread_id("")

    def test_rejects_special_characters(self):
        for ch in ["@", "#", "$", "!", "+"]:
            with pytest.raises(ValueError):
                _validate_thread_id(f"bad{ch}id")


# ---------------------------------------------------------------------------
# _join_host_path
# ---------------------------------------------------------------------------


class TestJoinHostPath:
    def test_posix_join(self):
        result = _join_host_path("/home/user", "threads", "abc")
        assert result == str(Path("/home/user") / "threads" / "abc")

    def test_no_parts(self):
        assert _join_host_path("/home/user") == "/home/user"

    def test_windows_drive_path_preserved(self):
        result = _join_host_path("C:\\repo\\backend", "threads", "abc")
        expected = str(PureWindowsPath("C:\\repo\\backend") / "threads" / "abc")
        assert result == expected

    def test_windows_unc_path(self):
        result = _join_host_path("\\\\server\\share", "data")
        assert "data" in result

    def test_windows_style_with_backslash(self):
        result = _join_host_path("D:\\some\\path", "sub")
        expected = str(PureWindowsPath("D:\\some\\path") / "sub")
        assert result == expected

    def test_posix_single_part(self):
        result = _join_host_path("/base", "child")
        assert result == str(Path("/base") / "child")


# ---------------------------------------------------------------------------
# Paths — base_dir resolution
# ---------------------------------------------------------------------------


class TestPathsBaseDir:
    def test_explicit_base_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Paths(base_dir=tmp)
            assert p.base_dir == Path(tmp).resolve()

    def test_env_variable_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Paths()
            with patch.dict(os.environ, {"DEER_FLOW_HOME": tmp}):
                assert p.base_dir == Path(tmp).resolve()

    def test_explicit_overrides_env(self):
        with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
            with patch.dict(os.environ, {"DEER_FLOW_HOME": tmp2}):
                p = Paths(base_dir=tmp1)
                assert p.base_dir == Path(tmp1).resolve()

    def test_default_fallback_returns_path(self):
        env = os.environ.copy()
        env.pop("DEER_FLOW_HOME", None)
        with patch.dict(os.environ, env, clear=True):
            p = Paths()
            assert isinstance(p.base_dir, Path)


# ---------------------------------------------------------------------------
# Paths — derived paths
# ---------------------------------------------------------------------------


class TestPathsDerived:
    def setup_method(self):
        self.tmp = tempfile.mkdtemp()
        self.paths = Paths(base_dir=self.tmp)

    def teardown_method(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_memory_file(self):
        assert self.paths.memory_file == Path(self.tmp).resolve() / "memory.json"

    def test_user_md_file(self):
        assert self.paths.user_md_file == Path(self.tmp).resolve() / "USER.md"

    def test_agents_dir(self):
        assert self.paths.agents_dir == Path(self.tmp).resolve() / "agents"

    def test_agent_dir_lowercase(self):
        result = self.paths.agent_dir("MyAgent")
        assert result.name == "myagent"

    def test_agent_memory_file(self):
        result = self.paths.agent_memory_file("TestBot")
        assert result == Path(self.tmp).resolve() / "agents" / "testbot" / "memory.json"

    def test_thread_dir(self):
        result = self.paths.thread_dir("thread-123")
        assert result == Path(self.tmp).resolve() / "threads" / "thread-123"

    def test_thread_dir_invalid_id_raises(self):
        with pytest.raises(ValueError):
            self.paths.thread_dir("../../bad")

    def test_sandbox_work_dir(self):
        result = self.paths.sandbox_work_dir("t1")
        assert str(result).endswith("t1/user-data/workspace")

    def test_sandbox_uploads_dir(self):
        result = self.paths.sandbox_uploads_dir("t1")
        assert str(result).endswith("t1/user-data/uploads")

    def test_sandbox_outputs_dir(self):
        result = self.paths.sandbox_outputs_dir("t1")
        assert str(result).endswith("t1/user-data/outputs")

    def test_acp_workspace_dir(self):
        result = self.paths.acp_workspace_dir("t1")
        assert str(result).endswith("t1/acp-workspace")

    def test_sandbox_user_data_dir(self):
        result = self.paths.sandbox_user_data_dir("t1")
        assert str(result).endswith("t1/user-data")


# ---------------------------------------------------------------------------
# Paths — host_base_dir
# ---------------------------------------------------------------------------


class TestPathsHostDir:
    def test_host_base_dir_defaults_to_base_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Paths(base_dir=tmp)
            env = os.environ.copy()
            env.pop("DEER_FLOW_HOST_BASE_DIR", None)
            with patch.dict(os.environ, env, clear=True):
                assert p.host_base_dir == p.base_dir

    def test_host_base_dir_from_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Paths(base_dir=tmp)
            with patch.dict(os.environ, {"DEER_FLOW_HOST_BASE_DIR": "/host/path"}):
                assert p.host_base_dir == Path("/host/path")


# ---------------------------------------------------------------------------
# Paths — ensure_thread_dirs / delete_thread_dir
# ---------------------------------------------------------------------------


class TestPathsThreadOps:
    def test_ensure_thread_dirs_creates_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Paths(base_dir=tmp)
            p.ensure_thread_dirs("test-thread")
            assert p.sandbox_work_dir("test-thread").exists()
            assert p.sandbox_uploads_dir("test-thread").exists()
            assert p.sandbox_outputs_dir("test-thread").exists()
            assert p.acp_workspace_dir("test-thread").exists()

    def test_ensure_thread_dirs_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Paths(base_dir=tmp)
            p.ensure_thread_dirs("t1")
            p.ensure_thread_dirs("t1")  # Should not raise
            assert p.sandbox_work_dir("t1").exists()

    def test_delete_thread_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Paths(base_dir=tmp)
            p.ensure_thread_dirs("to-delete")
            assert p.thread_dir("to-delete").exists()
            p.delete_thread_dir("to-delete")
            assert not p.thread_dir("to-delete").exists()

    def test_delete_nonexistent_thread_no_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Paths(base_dir=tmp)
            p.delete_thread_dir("does-not-exist")  # Should not raise


# ---------------------------------------------------------------------------
# Paths — resolve_virtual_path
# ---------------------------------------------------------------------------


class TestResolveVirtualPath:
    def test_resolve_valid_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Paths(base_dir=tmp)
            p.ensure_thread_dirs("t1")
            result = p.resolve_virtual_path("t1", "/mnt/user-data/outputs/report.pdf")
            assert str(result).endswith("outputs/report.pdf")

    def test_resolve_virtual_path_exact_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Paths(base_dir=tmp)
            p.ensure_thread_dirs("t1")
            result = p.resolve_virtual_path("t1", "/mnt/user-data")
            assert result == p.sandbox_user_data_dir("t1").resolve()

    def test_reject_wrong_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Paths(base_dir=tmp)
            with pytest.raises(ValueError, match="Path must start with"):
                p.resolve_virtual_path("t1", "/wrong/prefix/file.txt")

    def test_reject_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Paths(base_dir=tmp)
            p.ensure_thread_dirs("t1")
            with pytest.raises(ValueError, match="path traversal"):
                p.resolve_virtual_path("t1", "/mnt/user-data/../../etc/passwd")

    def test_reject_prefix_confusion(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Paths(base_dir=tmp)
            with pytest.raises(ValueError, match="Path must start with"):
                p.resolve_virtual_path("t1", "/mnt/user-dataX/evil")


# ---------------------------------------------------------------------------
# resolve_path (module-level)
# ---------------------------------------------------------------------------


class TestResolvePath:
    def test_absolute_path_returned_as_is(self):
        result = resolve_path("/tmp/somefile.txt")
        assert result == Path("/tmp/somefile.txt").resolve()

    def test_relative_path_resolved_against_base(self):
        result = resolve_path("subdir/file.txt")
        assert result.is_absolute()
        assert "subdir" in str(result)


# ---------------------------------------------------------------------------
# get_paths singleton
# ---------------------------------------------------------------------------


class TestGetPaths:
    def test_returns_paths_instance(self):
        _paths_mod._paths = None
        result = get_paths()
        assert isinstance(result, Paths)

    def test_returns_same_instance(self):
        _paths_mod._paths = None
        a = get_paths()
        b = get_paths()
        assert a is b
