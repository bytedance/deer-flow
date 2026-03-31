"""Tests for multi-user isolation: user_id paths, thread ownership, and memory isolation."""

import json
import tempfile
from pathlib import Path

import pytest

from deerflow.config.paths import Paths


class TestUserPaths:
    """Verify user-level path methods produce correct, isolated paths."""

    def setup_method(self):
        self.tmp = tempfile.mkdtemp()
        self.paths = Paths(self.tmp)
        self.base = Path(self.tmp).resolve()

    def test_user_dir(self):
        p = self.paths.user_dir("user-abc")
        assert p == self.base / "users" / "user-abc"

    def test_user_memory_file(self):
        p = self.paths.user_memory_file("user-abc")
        assert p == self.base / "users" / "user-abc" / "memory.json"

    def test_user_agent_memory_file(self):
        p = self.paths.user_agent_memory_file("user-abc", "SciAgent")
        assert p == self.base / "users" / "user-abc" / "agents" / "sciagent" / "memory.json"

    def test_user_ov_workspace(self):
        p = self.paths.user_ov_workspace("user-abc")
        assert p == self.base / "users" / "user-abc" / "ov-workspace"

    def test_user_profile_file(self):
        p = self.paths.user_profile_file("user-abc")
        assert p == self.base / "users" / "user-abc" / "profile.json"

    def test_session_memory_file(self):
        p = self.paths.session_memory_file("thread-123")
        assert p == self.base / "threads" / "thread-123" / "session-memory.json"

    def test_thread_ownership_file(self):
        p = self.paths.thread_ownership_file()
        assert p == self.base / "thread-ownership.json"

    def test_different_users_have_different_paths(self):
        p1 = self.paths.user_memory_file("user-alice")
        p2 = self.paths.user_memory_file("user-bob")
        assert p1 != p2
        assert "user-alice" in str(p1)
        assert "user-bob" in str(p2)

    def test_invalid_user_id_rejected(self):
        with pytest.raises(ValueError, match="Invalid user_id"):
            self.paths.user_dir("../etc/passwd")

    def test_invalid_user_id_with_slash(self):
        with pytest.raises(ValueError, match="Invalid user_id"):
            self.paths.user_dir("user/evil")

    def test_valid_user_id_formats(self):
        for uid in ["user123", "User_Test", "user-abc-123", "A"]:
            p = self.paths.user_dir(uid)
            assert uid in str(p)

    def test_ensure_user_dirs_creates_directories(self):
        self.paths.ensure_user_dirs("user-abc")
        assert self.paths.user_dir("user-abc").is_dir()
        assert self.paths.user_ov_workspace("user-abc").is_dir()


class TestThreadOwnership:
    """Verify thread-to-user ownership recording in ThreadDataMiddleware."""

    def setup_method(self):
        self.tmp = tempfile.mkdtemp()
        self.paths = Paths(self.tmp)

    def test_ownership_file_created(self):
        from deerflow.agents.middlewares.thread_data_middleware import ThreadDataMiddleware

        middleware = ThreadDataMiddleware(base_dir=self.tmp, lazy_init=True)
        # Simulate recording ownership
        middleware._record_thread_ownership("thread-1", "user-abc")

        ownership_file = self.paths.thread_ownership_file()
        assert ownership_file.exists()

        data = json.loads(ownership_file.read_text())
        assert "thread-1" in data
        assert data["thread-1"]["user_id"] == "user-abc"

    def test_ownership_preserves_existing(self):
        from deerflow.agents.middlewares.thread_data_middleware import ThreadDataMiddleware

        middleware = ThreadDataMiddleware(base_dir=self.tmp, lazy_init=True)
        middleware._record_thread_ownership("thread-1", "user-alice")
        middleware._record_thread_ownership("thread-2", "user-bob")

        data = json.loads(self.paths.thread_ownership_file().read_text())
        assert data["thread-1"]["user_id"] == "user-alice"
        assert data["thread-2"]["user_id"] == "user-bob"

    def test_ownership_not_overwritten(self):
        from deerflow.agents.middlewares.thread_data_middleware import ThreadDataMiddleware

        middleware = ThreadDataMiddleware(base_dir=self.tmp, lazy_init=True)
        middleware._record_thread_ownership("thread-1", "user-alice")
        middleware._record_thread_ownership("thread-1", "user-bob")  # should not overwrite

        data = json.loads(self.paths.thread_ownership_file().read_text())
        assert data["thread-1"]["user_id"] == "user-alice"  # original owner preserved
