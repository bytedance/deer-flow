"""Tests for centralized path configuration (src.config.paths)."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from src.config.paths import VIRTUAL_PATH_PREFIX, Paths


class TestPathsBaseDir:
    """Test Paths.base_dir resolution priority."""

    def test_explicit_base_dir(self, tmp_path):
        """Constructor base_dir takes highest priority."""
        p = Paths(tmp_path / "custom")
        assert p.base_dir == (tmp_path / "custom").resolve()

    def test_env_var_override(self, tmp_path):
        """DEER_FLOW_HOME env var overrides cwd-based detection."""
        custom = tmp_path / "env-home"
        custom.mkdir()
        p = Paths()
        with patch.dict(os.environ, {"DEER_FLOW_HOME": str(custom)}):
            assert p.base_dir == custom.resolve()

    def test_backend_cwd_fallback(self, tmp_path):
        """When cwd is a backend dir, base_dir is cwd/.think-tank."""
        (tmp_path / "pyproject.toml").touch()
        p = Paths()
        with (
            patch.dict(os.environ, {}, clear=False),
            patch("src.config.paths.Path.cwd", return_value=tmp_path),
        ):
            os.environ.pop("DEER_FLOW_HOME", None)
            assert p.base_dir == tmp_path / ".think-tank"

    def test_home_fallback(self, tmp_path):
        """When nothing else matches, base_dir is $HOME/.think-tank."""
        # Use a directory that doesn't look like a backend dir
        other = tmp_path / "some-other-dir"
        other.mkdir()
        p = Paths()
        with (
            patch.dict(os.environ, {}, clear=False),
            patch("src.config.paths.Path.cwd", return_value=other),
            patch("src.config.paths.Path.home", return_value=tmp_path),
        ):
            os.environ.pop("DEER_FLOW_HOME", None)
            assert p.base_dir == tmp_path / ".think-tank"


class TestThreadDirValidation:
    """Test thread_id validation in Paths.thread_dir."""

    def test_valid_thread_ids(self, tmp_path):
        p = Paths(tmp_path)
        for tid in ["abc123", "thread-1", "my_thread", "A-Z_0-9"]:
            result = p.thread_dir(tid)
            assert result == tmp_path.resolve() / "threads" / tid

    def test_rejects_path_traversal(self, tmp_path):
        p = Paths(tmp_path)
        for bad in ["../evil", "foo/bar", "a b", "thread..", "hello world", "a;b"]:
            with pytest.raises(ValueError, match="Invalid thread_id"):
                p.thread_dir(bad)


class TestSandboxDirPaths:
    """Test subdirectory path methods."""

    def test_sandbox_work_dir(self, tmp_path):
        p = Paths(tmp_path)
        assert p.sandbox_work_dir("t1") == tmp_path.resolve() / "threads/t1/user-data/workspace"

    def test_sandbox_uploads_dir(self, tmp_path):
        p = Paths(tmp_path)
        assert p.sandbox_uploads_dir("t1") == tmp_path.resolve() / "threads/t1/user-data/uploads"

    def test_sandbox_outputs_dir(self, tmp_path):
        p = Paths(tmp_path)
        assert p.sandbox_outputs_dir("t1") == tmp_path.resolve() / "threads/t1/user-data/outputs"

    def test_sandbox_user_data_dir(self, tmp_path):
        p = Paths(tmp_path)
        assert p.sandbox_user_data_dir("t1") == tmp_path.resolve() / "threads/t1/user-data"

    def test_memory_file(self, tmp_path):
        p = Paths(tmp_path)
        assert p.memory_file == tmp_path.resolve() / "memory.json"


class TestEnsureThreadDirs:
    """Test directory creation."""

    def test_creates_all_standard_dirs(self, tmp_path):
        p = Paths(tmp_path)
        p.ensure_thread_dirs("my-thread")

        base = tmp_path.resolve() / "threads" / "my-thread" / "user-data"
        assert (base / "workspace").is_dir()
        assert (base / "uploads").is_dir()
        assert (base / "outputs").is_dir()

    def test_idempotent(self, tmp_path):
        """Calling ensure_thread_dirs twice should not fail."""
        p = Paths(tmp_path)
        p.ensure_thread_dirs("t1")
        p.ensure_thread_dirs("t1")  # second call should be fine


class TestResolveVirtualPath:
    """Test virtual path to host path resolution."""

    def test_resolves_outputs_path(self, tmp_path):
        p = Paths(tmp_path)
        p.ensure_thread_dirs("t1")
        result = p.resolve_virtual_path("t1", "/mnt/user-data/outputs/report.pdf")
        expected = tmp_path.resolve() / "threads/t1/user-data/outputs/report.pdf"
        assert result == expected

    def test_resolves_uploads_path(self, tmp_path):
        p = Paths(tmp_path)
        p.ensure_thread_dirs("t1")
        result = p.resolve_virtual_path("t1", "/mnt/user-data/uploads/doc.txt")
        expected = tmp_path.resolve() / "threads/t1/user-data/uploads/doc.txt"
        assert result == expected

    def test_resolves_bare_prefix(self, tmp_path):
        """The virtual prefix alone should resolve to the user-data root."""
        p = Paths(tmp_path)
        p.ensure_thread_dirs("t1")
        result = p.resolve_virtual_path("t1", "/mnt/user-data")
        expected = (tmp_path.resolve() / "threads/t1/user-data").resolve()
        assert result == expected

    def test_rejects_wrong_prefix(self, tmp_path):
        p = Paths(tmp_path)
        with pytest.raises(ValueError, match="must start with"):
            p.resolve_virtual_path("t1", "/some/other/path")

    def test_rejects_path_traversal(self, tmp_path):
        p = Paths(tmp_path)
        p.ensure_thread_dirs("t1")
        with pytest.raises(ValueError, match="traversal"):
            p.resolve_virtual_path("t1", "/mnt/user-data/../../etc/passwd")

    def test_rejects_prefix_confusion(self, tmp_path):
        """Paths like /mnt/user-dataX should not be accepted."""
        p = Paths(tmp_path)
        with pytest.raises(ValueError, match="must start with"):
            p.resolve_virtual_path("t1", "/mnt/user-dataX/evil")


class TestVirtualPathPrefix:
    """Test the module-level constant."""

    def test_prefix_value(self):
        assert VIRTUAL_PATH_PREFIX == "/mnt/user-data"
