"""Tests for config paths module."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from deerflow.config.paths import Paths, get_paths, resolve_path, VIRTUAL_PATH_PREFIX


class TestPathsBaseDir:
    """Tests for Paths base directory resolution."""

    def test_uses_constructor_argument_when_provided(self, tmp_path):
        """Should use base_dir from constructor when provided."""
        paths = Paths(base_dir=tmp_path)
        assert paths.base_dir == tmp_path.resolve()

    def test_uses_environment_variable(self, tmp_path):
        """Should use DEER_FLOW_HOME environment variable."""
        with patch.dict(os.environ, {"DEER_FLOW_HOME": str(tmp_path)}):
            paths = Paths()
            assert paths.base_dir == tmp_path.resolve()

    def test_uses_home_directory_fallback(self):
        """Should default to ~/.deer-flow when no other option."""
        # Clear env var and don't provide base_dir
        with patch.dict(os.environ, {}, clear=True):
            paths = Paths()
            expected = Path.home() / ".deer-flow"
            assert paths.base_dir == expected


class TestPathsProperties:
    """Tests for Paths properties."""

    def test_memory_file_property(self, tmp_path):
        """memory_file should return correct path."""
        paths = Paths(base_dir=tmp_path)
        assert paths.memory_file == tmp_path / "memory.json"

    def test_user_md_file_property(self, tmp_path):
        """user_md_file should return correct path."""
        paths = Paths(base_dir=tmp_path)
        assert paths.user_md_file == tmp_path / "USER.md"

    def test_agents_dir_property(self, tmp_path):
        """agents_dir should return correct path."""
        paths = Paths(base_dir=tmp_path)
        assert paths.agents_dir == tmp_path / "agents"


class TestPathsAgentMethods:
    """Tests for agent-related path methods."""

    def test_agent_dir_returns_lowercase_path(self, tmp_path):
        """agent_dir should lowercase the agent name."""
        paths = Paths(base_dir=tmp_path)
        result = paths.agent_dir("MyAgent")
        assert result == tmp_path / "agents" / "myagent"

    def test_agent_memory_file_returns_correct_path(self, tmp_path):
        """agent_memory_file should return path to agent memory."""
        paths = Paths(base_dir=tmp_path)
        result = paths.agent_memory_file("test-agent")
        assert result == tmp_path / "agents" / "test-agent" / "memory.json"


class TestPathsThreadMethods:
    """Tests for thread-related path methods."""

    def test_thread_dir_returns_correct_path(self, tmp_path):
        """thread_dir should return correct path for thread."""
        paths = Paths(base_dir=tmp_path)
        result = paths.thread_dir("thread-123")
        assert result == tmp_path / "threads" / "thread-123"

    def test_thread_dir_rejects_invalid_characters(self, tmp_path):
        """thread_dir should reject thread IDs with invalid characters."""
        paths = Paths(base_dir=tmp_path)
        
        with pytest.raises(ValueError, match="Invalid thread_id"):
            paths.thread_dir("../etc/passwd")
        
        with pytest.raises(ValueError, match="Invalid thread_id"):
            paths.thread_dir("thread/path")

    def test_sandbox_work_dir_returns_correct_path(self, tmp_path):
        """sandbox_work_dir should return workspace path."""
        paths = Paths(base_dir=tmp_path)
        result = paths.sandbox_work_dir("thread-123")
        assert result == tmp_path / "threads" / "thread-123" / "user-data" / "workspace"

    def test_sandbox_uploads_dir_returns_correct_path(self, tmp_path):
        """sandbox_uploads_dir should return uploads path."""
        paths = Paths(base_dir=tmp_path)
        result = paths.sandbox_uploads_dir("thread-123")
        assert result == tmp_path / "threads" / "thread-123" / "user-data" / "uploads"

    def test_sandbox_outputs_dir_returns_correct_path(self, tmp_path):
        """sandbox_outputs_dir should return outputs path."""
        paths = Paths(base_dir=tmp_path)
        result = paths.sandbox_outputs_dir("thread-123")
        assert result == tmp_path / "threads" / "thread-123" / "user-data" / "outputs"


class TestPathsEnsureThreadDirs:
    """Tests for ensure_thread_dirs method."""

    def test_creates_all_directories(self, tmp_path):
        """Should create workspace, uploads, and outputs directories."""
        paths = Paths(base_dir=tmp_path)
        paths.ensure_thread_dirs("thread-123")
        
        assert (tmp_path / "threads" / "thread-123" / "user-data" / "workspace").exists()
        assert (tmp_path / "threads" / "thread-123" / "user-data" / "uploads").exists()
        assert (tmp_path / "threads" / "thread-123" / "user-data" / "outputs").exists()

    def test_sets_correct_permissions(self, tmp_path):
        """Should set directories to 0o777 permissions."""
        paths = Paths(base_dir=tmp_path)
        paths.ensure_thread_dirs("thread-123")
        
        workspace = tmp_path / "threads" / "thread-123" / "user-data" / "workspace"
        # Check permissions (may be masked by umask in test environment)
        stat = workspace.stat()
        assert stat.st_mode & 0o777 == 0o777

    def test_idempotent(self, tmp_path):
        """Should be safe to call multiple times."""
        paths = Paths(base_dir=tmp_path)
        paths.ensure_thread_dirs("thread-123")
        paths.ensure_thread_dirs("thread-123")  # Should not raise
        
        # Directories should still exist
        assert (tmp_path / "threads" / "thread-123" / "user-data" / "workspace").exists()


class TestPathsDeleteThreadDir:
    """Tests for delete_thread_dir method."""

    def test_deletes_thread_directory(self, tmp_path):
        """Should delete all thread data."""
        paths = Paths(base_dir=tmp_path)
        paths.ensure_thread_dirs("thread-123")
        
        paths.delete_thread_dir("thread-123")
        
        assert not (tmp_path / "threads" / "thread-123").exists()

    def test_idempotent_when_directory_missing(self, tmp_path):
        """Should not raise when directory doesn't exist."""
        paths = Paths(base_dir=tmp_path)
        
        # Should not raise
        paths.delete_thread_dir("nonexistent-thread")


class TestPathsResolveVirtualPath:
    """Tests for resolve_virtual_path method."""

    def test_resolves_workspace_path(self, tmp_path):
        """Should resolve /mnt/user-data/workspace path."""
        paths = Paths(base_dir=tmp_path)
        paths.ensure_thread_dirs("thread-123")
        
        result = paths.resolve_virtual_path("thread-123", "/mnt/user-data/workspace/file.txt")
        expected = tmp_path / "threads" / "thread-123" / "user-data" / "workspace" / "file.txt"
        assert result == expected.resolve()

    def test_resolves_uploads_path(self, tmp_path):
        """Should resolve /mnt/user-data/uploads path."""
        paths = Paths(base_dir=tmp_path)
        paths.ensure_thread_dirs("thread-123")
        
        result = paths.resolve_virtual_path("thread-123", "/mnt/user-data/uploads/image.png")
        expected = tmp_path / "threads" / "thread-123" / "user-data" / "uploads" / "image.png"
        assert result == expected.resolve()

    def test_rejects_invalid_virtual_prefix(self, tmp_path):
        """Should reject paths not starting with virtual prefix."""
        paths = Paths(base_dir=tmp_path)
        
        with pytest.raises(ValueError, match="Path must start with"):
            paths.resolve_virtual_path("thread-123", "/etc/passwd")

    def test_rejects_path_traversal(self, tmp_path):
        """Should reject path traversal attempts."""
        paths = Paths(base_dir=tmp_path)
        paths.ensure_thread_dirs("thread-123")
        
        with pytest.raises(ValueError, match="path traversal detected"):
            paths.resolve_virtual_path("thread-123", "/mnt/user-data/../../etc/passwd")

    def test_handles_leading_slash_variations(self, tmp_path):
        """Should handle paths with or without leading slash."""
        paths = Paths(base_dir=tmp_path)
        paths.ensure_thread_dirs("thread-123")
        
        # With leading slash
        result1 = paths.resolve_virtual_path("thread-123", "/mnt/user-data/file.txt")
        # Without leading slash
        result2 = paths.resolve_virtual_path("thread-123", "mnt/user-data/file.txt")
        
        assert result1 == result2


class TestGetPaths:
    """Tests for get_paths function."""

    def test_returns_singleton(self):
        """Should return same instance on multiple calls."""
        paths1 = get_paths()
        paths2 = get_paths()
        
        assert paths1 is paths2

    def test_lazy_initialization(self):
        """Should create instance on first call."""
        # Reset the singleton
        import deerflow.config.paths as paths_module
        original = paths_module._paths
        paths_module._paths = None
        
        try:
            # First call should create instance
            paths = get_paths()
            assert paths is not None
            assert paths_module._paths is paths
        finally:
            # Restore original
            paths_module._paths = original


class TestResolvePath:
    """Tests for resolve_path function."""

    def test_resolves_relative_to_base_dir(self, tmp_path):
        """Should resolve relative paths against base_dir."""
        with patch("deerflow.config.paths.get_paths") as mock_get_paths:
            mock_paths = Paths(base_dir=tmp_path)
            mock_get_paths.return_value = mock_paths
            
            result = resolve_path("relative/file.txt")
            assert result == (tmp_path / "relative" / "file.txt").resolve()

    def test_returns_absolute_as_is(self, tmp_path):
        """Should return absolute paths unchanged."""
        absolute = tmp_path / "absolute" / "file.txt"
        
        result = resolve_path(str(absolute))
        assert result == absolute.resolve()
