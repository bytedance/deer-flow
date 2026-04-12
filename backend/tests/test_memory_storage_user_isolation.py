"""Tests for per-user memory storage isolation."""
import pytest
from pathlib import Path
from unittest.mock import patch

from deerflow.agents.memory.storage import FileMemoryStorage, create_empty_memory


@pytest.fixture
def base_dir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def storage() -> FileMemoryStorage:
    return FileMemoryStorage()


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
        from deerflow.config.paths import Paths
        from deerflow.config.memory_config import MemoryConfig

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
        from deerflow.config.paths import Paths
        from deerflow.config.memory_config import MemoryConfig

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
            s = FileMemoryStorage()
            memory = create_empty_memory()
            memory["user"]["workContext"]["summary"] = "agent scoped"
            s.save(memory, "test-agent", user_id="alice")
            expected_path = base_dir / "users" / "alice" / "agents" / "test-agent" / "memory.json"
            assert expected_path.exists()

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
