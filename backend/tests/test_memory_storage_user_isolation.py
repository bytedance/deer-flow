"""Tests for per-user memory storage isolation."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from deerflow.agents.memory.storage import (
    FileMemoryStorage,
    cleanup_stale_deleted_agent_memory_marks,
    clear_deleted_agent_memory_marks,
    create_empty_memory,
    is_agent_memory_obsolete,
    mark_agent_memory_deleted,
)


@pytest.fixture
def base_dir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def storage() -> FileMemoryStorage:
    return FileMemoryStorage()


@pytest.fixture(autouse=True)
def reset_deleted_agent_memory_marks(base_dir: Path):
    from deerflow.config.paths import Paths

    paths = Paths(base_dir)
    with patch("deerflow.agents.memory.storage.get_paths", return_value=paths):
        clear_deleted_agent_memory_marks()
        yield
        clear_deleted_agent_memory_marks()


class TestUserIsolatedStorage:
    def test_save_and_load_per_user(self, storage: FileMemoryStorage, base_dir: Path):
        from deerflow.config.paths import Paths

        paths = Paths(base_dir)
        with patch("deerflow.agents.memory.storage.get_paths", return_value=paths):
            memory_a = create_empty_memory()
            memory_a["user"]["workContext"]["summary"] = "User A context"
            storage.save(memory_a, user_id="alice")

            memory_b = create_empty_memory()
            memory_b["user"]["workContext"]["summary"] = "User B context"
            storage.save(memory_b, user_id="bob")

            loaded_a = storage.load(user_id="alice")
            loaded_b = storage.load(user_id="bob")

            assert loaded_a["user"]["workContext"]["summary"] == "User A context"
            assert loaded_b["user"]["workContext"]["summary"] == "User B context"

    def test_user_memory_file_location(self, base_dir: Path):
        from deerflow.config.paths import Paths

        paths = Paths(base_dir)
        with patch("deerflow.agents.memory.storage.get_paths", return_value=paths):
            s = FileMemoryStorage()
            memory = create_empty_memory()
            s.save(memory, user_id="alice")
            expected_path = base_dir / "users" / "alice" / "memory.json"
            assert expected_path.exists()

    def test_cache_isolated_per_user(self, base_dir: Path):
        from deerflow.config.paths import Paths

        paths = Paths(base_dir)
        with patch("deerflow.agents.memory.storage.get_paths", return_value=paths):
            s = FileMemoryStorage()
            memory_a = create_empty_memory()
            memory_a["user"]["workContext"]["summary"] = "A"
            s.save(memory_a, user_id="alice")

            memory_b = create_empty_memory()
            memory_b["user"]["workContext"]["summary"] = "B"
            s.save(memory_b, user_id="bob")

            loaded_a = s.load(user_id="alice")
            assert loaded_a["user"]["workContext"]["summary"] == "A"

    def test_no_user_id_uses_legacy_path(self, base_dir: Path):
        from deerflow.config.memory_config import MemoryConfig
        from deerflow.config.paths import Paths

        paths = Paths(base_dir)
        with patch("deerflow.agents.memory.storage.get_paths", return_value=paths):
            with patch("deerflow.agents.memory.storage.get_memory_config", return_value=MemoryConfig(storage_path="")):
                s = FileMemoryStorage()
                memory = create_empty_memory()
                s.save(memory, user_id=None)
                expected_path = base_dir / "memory.json"
                assert expected_path.exists()

    def test_user_and_legacy_do_not_interfere(self, base_dir: Path):
        """user_id=None (legacy) and user_id='alice' must use different files and caches."""
        from deerflow.config.memory_config import MemoryConfig
        from deerflow.config.paths import Paths

        paths = Paths(base_dir)
        with patch("deerflow.agents.memory.storage.get_paths", return_value=paths):
            with patch("deerflow.agents.memory.storage.get_memory_config", return_value=MemoryConfig(storage_path="")):
                s = FileMemoryStorage()

                legacy_mem = create_empty_memory()
                legacy_mem["user"]["workContext"]["summary"] = "legacy"
                s.save(legacy_mem, user_id=None)

                user_mem = create_empty_memory()
                user_mem["user"]["workContext"]["summary"] = "alice"
                s.save(user_mem, user_id="alice")

                assert s.load(user_id=None)["user"]["workContext"]["summary"] == "legacy"
                assert s.load(user_id="alice")["user"]["workContext"]["summary"] == "alice"

    def test_user_agent_memory_file_location(self, base_dir: Path):
        """Per-user per-agent memory uses the user_agent_memory_file path."""
        from deerflow.config.paths import Paths

        paths = Paths(base_dir)
        with patch("deerflow.agents.memory.storage.get_paths", return_value=paths):
            agent_dir = base_dir / "users" / "alice" / "agents" / "test-agent"
            agent_dir.mkdir(parents=True)
            (agent_dir / "config.yaml").write_text("name: test-agent\n", encoding="utf-8")

            s = FileMemoryStorage()
            memory = create_empty_memory()
            memory["user"]["workContext"]["summary"] = "agent scoped"
            s.save(memory, "test-agent", user_id="alice")
            expected_path = base_dir / "users" / "alice" / "agents" / "test-agent" / "memory.json"
            assert expected_path.exists()

    def test_missing_user_agent_config_does_not_create_memory_only_agent_dir(self, base_dir: Path):
        """Late async saves for deleted agents must not recreate the agent directory."""
        from deerflow.config.paths import Paths

        paths = Paths(base_dir)
        with patch("deerflow.agents.memory.storage.get_paths", return_value=paths):
            s = FileMemoryStorage()
            memory = create_empty_memory()

            saved = s.save(memory, "deleted-agent", user_id="alice")

            assert saved is False
            assert not (base_dir / "users" / "alice" / "agents" / "deleted-agent").exists()
            assert ("alice", "deleted-agent") not in s._memory_cache

    def test_missing_legacy_agent_config_does_not_create_memory_only_agent_dir(self, base_dir: Path):
        """Legacy per-agent memory has the same deleted-agent guard."""
        from deerflow.config.paths import Paths

        paths = Paths(base_dir)
        with patch("deerflow.agents.memory.storage.get_paths", return_value=paths):
            s = FileMemoryStorage()
            memory = create_empty_memory()

            saved = s.save(memory, "deleted-agent", user_id=None)

            assert saved is False
            assert not (base_dir / "agents" / "deleted-agent").exists()

    def test_obsolete_agent_memory_context_is_skipped_after_delete(self, base_dir: Path):
        """Old in-flight memory updates must not write into a recreated same-name agent."""
        from deerflow.config.paths import Paths

        paths = Paths(base_dir)
        context_timestamp = datetime.now(UTC) - timedelta(seconds=5)
        with patch("deerflow.agents.memory.storage.get_paths", return_value=paths):
            s = FileMemoryStorage()
            agent_dir = base_dir / "users" / "alice" / "agents" / "test-agent"
            agent_dir.mkdir(parents=True)
            (agent_dir / "config.yaml").write_text("name: test-agent\n", encoding="utf-8")
            mark_agent_memory_deleted("test-agent", user_id="alice")

            saved = s.save(
                create_empty_memory(),
                "test-agent",
                user_id="alice",
                context_timestamp=context_timestamp,
            )

            assert saved is False
            assert not (agent_dir / "memory.json").exists()

    def test_deleted_agent_marker_is_visible_to_new_storage_instance(self, base_dir: Path):
        """Deleted-agent markers are persisted so another worker can skip old updates."""
        from deerflow.config.paths import Paths

        paths = Paths(base_dir)
        context_timestamp = datetime.now(UTC) - timedelta(seconds=5)
        with patch("deerflow.agents.memory.storage.get_paths", return_value=paths):
            agent_dir = base_dir / "users" / "alice" / "agents" / "test-agent"
            agent_dir.mkdir(parents=True)
            (agent_dir / "config.yaml").write_text("name: test-agent\n", encoding="utf-8")
            mark_agent_memory_deleted("test-agent", user_id="alice")
            from deerflow.agents.memory.storage import _deleted_agent_memory_targets

            _deleted_agent_memory_targets.clear()

            saved = FileMemoryStorage().save(
                create_empty_memory(),
                "test-agent",
                user_id="alice",
                context_timestamp=context_timestamp,
            )

            assert saved is False
            assert not (agent_dir / "memory.json").exists()

    def test_deleted_agent_marker_cache_does_not_overwrite_newer_in_memory_mark(self, monkeypatch):
        """A stale file marker must not clobber a newer in-memory deletion mark."""
        from deerflow.agents.memory import storage as storage_module

        old_deleted_at = datetime.now(UTC) - timedelta(seconds=10)
        newer_deleted_at = datetime.now(UTC)
        context_timestamp = newer_deleted_at - timedelta(seconds=1)
        key = storage_module._deleted_agent_key("test-agent", user_id="alice")

        def read_mark(agent_name: str, *, user_id: str | None = None) -> datetime:
            assert agent_name == "test-agent"
            assert user_id == "alice"
            with storage_module._deleted_agent_memory_lock:
                storage_module._deleted_agent_memory_targets[key] = newer_deleted_at
            return old_deleted_at

        monkeypatch.setattr(storage_module, "_read_deleted_agent_mark", read_mark)

        assert is_agent_memory_obsolete(
            "test-agent",
            user_id="alice",
            context_timestamp=context_timestamp,
        )
        assert storage_module._deleted_agent_memory_targets[key] == newer_deleted_at

    def test_cleanup_stale_deleted_agent_memory_marks_keeps_recent_markers(self, base_dir: Path):
        """Old marker files are removed without clearing recent same-target guards."""
        from deerflow.agents.memory import storage as storage_module
        from deerflow.config.paths import Paths

        paths = Paths(base_dir)
        now = datetime.now(UTC)
        old_deleted_at = now - timedelta(days=31)
        recent_deleted_at = now - timedelta(days=1)

        with patch("deerflow.agents.memory.storage.get_paths", return_value=paths):
            storage_module._write_deleted_agent_mark("old-agent", old_deleted_at, user_id="alice")
            storage_module._write_deleted_agent_mark("recent-agent", recent_deleted_at, user_id="alice")

            old_key = storage_module._deleted_agent_key("old-agent", user_id="alice")
            recent_key = storage_module._deleted_agent_key("recent-agent", user_id="alice")
            with storage_module._deleted_agent_memory_lock:
                storage_module._deleted_agent_memory_targets[old_key] = old_deleted_at
                storage_module._deleted_agent_memory_targets[recent_key] = recent_deleted_at

            removed_count = cleanup_stale_deleted_agent_memory_marks(max_age=timedelta(days=30), now=now)

            assert removed_count == 1
            assert not (base_dir / "users" / "alice" / ".deleted-agent-memory" / "old-agent.json").exists()
            assert (base_dir / "users" / "alice" / ".deleted-agent-memory" / "recent-agent.json").exists()
            assert old_key not in storage_module._deleted_agent_memory_targets
            assert storage_module._deleted_agent_memory_targets[recent_key] == recent_deleted_at

    def test_new_agent_memory_context_after_delete_is_not_obsolete(self):
        mark_agent_memory_deleted("new-agent", user_id="alice")

        context_timestamp = datetime.now(UTC) + timedelta(seconds=5)

        assert not is_agent_memory_obsolete(
            "new-agent",
            user_id="alice",
            context_timestamp=context_timestamp,
        )

    def test_cache_key_is_user_agent_tuple(self, base_dir: Path):
        """Cache keys must be (user_id, agent_name) tuples, not bare agent names."""
        from deerflow.config.paths import Paths

        paths = Paths(base_dir)
        with patch("deerflow.agents.memory.storage.get_paths", return_value=paths):
            s = FileMemoryStorage()
            memory = create_empty_memory()
            s.save(memory, user_id="alice")
            # After save, cache should have tuple key
            assert ("alice", None) in s._memory_cache

    def test_reload_with_user_id(self, base_dir: Path):
        """reload() with user_id should force re-read from the user-scoped file."""
        from deerflow.config.paths import Paths

        paths = Paths(base_dir)
        with patch("deerflow.agents.memory.storage.get_paths", return_value=paths):
            s = FileMemoryStorage()
            memory = create_empty_memory()
            memory["user"]["workContext"]["summary"] = "initial"
            s.save(memory, user_id="alice")

            # Load once to prime cache
            s.load(user_id="alice")

            # Write updated content directly to file
            user_file = base_dir / "users" / "alice" / "memory.json"
            import json

            updated = create_empty_memory()
            updated["user"]["workContext"]["summary"] = "updated"
            user_file.write_text(json.dumps(updated))

            # reload should pick up the new content
            reloaded = s.reload(user_id="alice")
            assert reloaded["user"]["workContext"]["summary"] == "updated"
