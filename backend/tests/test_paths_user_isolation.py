"""Tests for user-scoped path resolution in Paths."""

from pathlib import Path

import pytest

from deerflow.config.paths import Paths


@pytest.fixture
def paths(tmp_path: Path) -> Paths:
    return Paths(tmp_path)


class TestValidateUserId:
    def test_valid_user_id(self, paths: Paths):
        d = paths.user_dir("u-abc-123")
        assert d == paths.base_dir / "users" / "u-abc-123"

    def test_rejects_path_traversal(self, paths: Paths):
        with pytest.raises(ValueError, match="Invalid user_id"):
            paths.user_dir("../escape")

    def test_rejects_slash(self, paths: Paths):
        with pytest.raises(ValueError, match="Invalid user_id"):
            paths.user_dir("foo/bar")

    def test_rejects_empty(self, paths: Paths):
        with pytest.raises(ValueError, match="Invalid user_id"):
            paths.user_dir("")


class TestUserDir:
    def test_user_dir(self, paths: Paths):
        assert paths.user_dir("alice") == paths.base_dir / "users" / "alice"


class TestUserMemoryFile:
    def test_user_memory_file(self, paths: Paths):
        assert paths.user_memory_file("bob") == paths.base_dir / "users" / "bob" / "memory.json"


class TestUserAgentMemoryFile:
    def test_user_agent_memory_file(self, paths: Paths):
        expected = paths.base_dir / "users" / "bob" / "agents" / "myagent" / "memory.json"
        assert paths.user_agent_memory_file("bob", "myagent") == expected

    def test_user_agent_memory_file_lowercases_name(self, paths: Paths):
        expected = paths.base_dir / "users" / "bob" / "agents" / "myagent" / "memory.json"
        assert paths.user_agent_memory_file("bob", "MyAgent") == expected


class TestUserThreadDir:
    def test_user_thread_dir(self, paths: Paths):
        expected = paths.base_dir / "users" / "u1" / "threads" / "t1"
        assert paths.thread_dir("t1", user_id="u1") == expected

    def test_thread_dir_no_user_id_falls_back_to_legacy(self, paths: Paths):
        expected = paths.base_dir / "threads" / "t1"
        assert paths.thread_dir("t1") == expected


class TestUserSandboxDirs:
    def test_sandbox_work_dir(self, paths: Paths):
        expected = paths.base_dir / "users" / "u1" / "threads" / "t1" / "user-data" / "workspace"
        assert paths.sandbox_work_dir("t1", user_id="u1") == expected

    def test_sandbox_uploads_dir(self, paths: Paths):
        expected = paths.base_dir / "users" / "u1" / "threads" / "t1" / "user-data" / "uploads"
        assert paths.sandbox_uploads_dir("t1", user_id="u1") == expected

    def test_sandbox_outputs_dir(self, paths: Paths):
        expected = paths.base_dir / "users" / "u1" / "threads" / "t1" / "user-data" / "outputs"
        assert paths.sandbox_outputs_dir("t1", user_id="u1") == expected

    def test_sandbox_user_data_dir(self, paths: Paths):
        expected = paths.base_dir / "users" / "u1" / "threads" / "t1" / "user-data"
        assert paths.sandbox_user_data_dir("t1", user_id="u1") == expected

    def test_acp_workspace_dir(self, paths: Paths):
        expected = paths.base_dir / "users" / "u1" / "threads" / "t1" / "acp-workspace"
        assert paths.acp_workspace_dir("t1", user_id="u1") == expected

    def test_legacy_sandbox_work_dir(self, paths: Paths):
        expected = paths.base_dir / "threads" / "t1" / "user-data" / "workspace"
        assert paths.sandbox_work_dir("t1") == expected


class TestHostPathsWithUserId:
    def test_host_thread_dir_with_user_id(self, paths: Paths):
        result = paths.host_thread_dir("t1", user_id="u1")
        assert "users" in result
        assert "u1" in result
        assert "threads" in result
        assert "t1" in result

    def test_host_thread_dir_legacy(self, paths: Paths):
        result = paths.host_thread_dir("t1")
        assert "threads" in result
        assert "t1" in result
        assert "users" not in result

    def test_host_sandbox_user_data_dir_with_user_id(self, paths: Paths):
        result = paths.host_sandbox_user_data_dir("t1", user_id="u1")
        assert "users" in result
        assert "user-data" in result

    def test_host_sandbox_work_dir_with_user_id(self, paths: Paths):
        result = paths.host_sandbox_work_dir("t1", user_id="u1")
        assert "workspace" in result

    def test_host_sandbox_uploads_dir_with_user_id(self, paths: Paths):
        result = paths.host_sandbox_uploads_dir("t1", user_id="u1")
        assert "uploads" in result

    def test_host_sandbox_outputs_dir_with_user_id(self, paths: Paths):
        result = paths.host_sandbox_outputs_dir("t1", user_id="u1")
        assert "outputs" in result

    def test_host_acp_workspace_dir_with_user_id(self, paths: Paths):
        result = paths.host_acp_workspace_dir("t1", user_id="u1")
        assert "acp-workspace" in result


class TestEnsureAndDeleteWithUserId:
    def test_ensure_thread_dirs_creates_user_scoped(self, paths: Paths):
        paths.ensure_thread_dirs("t1", user_id="u1")
        assert paths.sandbox_work_dir("t1", user_id="u1").is_dir()
        assert paths.sandbox_uploads_dir("t1", user_id="u1").is_dir()
        assert paths.sandbox_outputs_dir("t1", user_id="u1").is_dir()
        assert paths.acp_workspace_dir("t1", user_id="u1").is_dir()

    def test_delete_thread_dir_removes_user_scoped(self, paths: Paths):
        paths.ensure_thread_dirs("t1", user_id="u1")
        assert paths.thread_dir("t1", user_id="u1").exists()
        paths.delete_thread_dir("t1", user_id="u1")
        assert not paths.thread_dir("t1", user_id="u1").exists()

    def test_delete_thread_dir_idempotent(self, paths: Paths):
        paths.delete_thread_dir("nonexistent", user_id="u1")  # should not raise

    def test_ensure_thread_dirs_legacy_still_works(self, paths: Paths):
        paths.ensure_thread_dirs("t1")
        assert paths.sandbox_work_dir("t1").is_dir()

    def test_user_scoped_and_legacy_are_independent(self, paths: Paths):
        paths.ensure_thread_dirs("t1", user_id="u1")
        paths.ensure_thread_dirs("t1")
        # Both exist independently
        assert paths.thread_dir("t1", user_id="u1").exists()
        assert paths.thread_dir("t1").exists()
        # Delete one doesn't affect the other
        paths.delete_thread_dir("t1", user_id="u1")
        assert not paths.thread_dir("t1", user_id="u1").exists()
        assert paths.thread_dir("t1").exists()


class TestResolveVirtualPathWithUserId:
    def test_resolve_virtual_path_with_user_id(self, paths: Paths):
        paths.ensure_thread_dirs("t1", user_id="u1")
        result = paths.resolve_virtual_path("t1", "/mnt/user-data/workspace/file.txt", user_id="u1")
        expected_base = paths.sandbox_user_data_dir("t1", user_id="u1").resolve()
        assert str(result).startswith(str(expected_base))

    def test_resolve_virtual_path_legacy(self, paths: Paths):
        paths.ensure_thread_dirs("t1")
        result = paths.resolve_virtual_path("t1", "/mnt/user-data/workspace/file.txt")
        expected_base = paths.sandbox_user_data_dir("t1").resolve()
        assert str(result).startswith(str(expected_base))
