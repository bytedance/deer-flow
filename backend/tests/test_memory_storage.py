"""Tests for memory storage providers."""

import threading
from unittest.mock import MagicMock, patch

import pytest

from deerflow.agents.memory.storage import (
    FileMemoryStorage,
    MemoryStorage,
    create_empty_memory,
    get_memory_storage,
)
from deerflow.config.memory_config import MemoryConfig


class TestCreateEmptyMemory:
    """Test create_empty_memory function."""

    def test_returns_valid_structure(self):
        """Should return a valid empty memory structure."""
        memory = create_empty_memory()
        assert isinstance(memory, dict)
        assert memory["version"] == "1.0"
        assert "lastUpdated" in memory
        assert isinstance(memory["user"], dict)
        assert isinstance(memory["history"], dict)
        assert isinstance(memory["facts"], list)


class TestMemoryStorageInterface:
    """Test MemoryStorage abstract base class."""

    def test_abstract_methods(self):
        """Should raise TypeError when trying to instantiate abstract class."""

        class TestStorage(MemoryStorage):
            pass

        with pytest.raises(TypeError):
            TestStorage()


class TestFileMemoryStorage:
    """Test FileMemoryStorage implementation."""

    def test_get_memory_file_path_global(self, tmp_path):
        """Should return global memory file path when agent_name is None."""

        def mock_get_paths():
            mock_paths = MagicMock()
            mock_paths.memory_file = tmp_path / "memory.json"
            return mock_paths

        with patch("deerflow.agents.memory.storage.get_paths", side_effect=mock_get_paths):
            with patch("deerflow.agents.memory.storage.get_memory_config", return_value=MemoryConfig(storage_path="")):
                storage = FileMemoryStorage()
                path = storage._get_memory_file_path(None)
                assert path == tmp_path / "memory.json"

    def test_get_memory_file_path_agent(self, tmp_path):
        """Should return per-agent memory file path when agent_name is provided."""

        def mock_get_paths():
            mock_paths = MagicMock()
            mock_paths.agent_memory_file.return_value = tmp_path / "agents" / "test-agent" / "memory.json"
            return mock_paths

        with patch("deerflow.agents.memory.storage.get_paths", side_effect=mock_get_paths):
            storage = FileMemoryStorage()
            path = storage._get_memory_file_path("test-agent")
            assert path == tmp_path / "agents" / "test-agent" / "memory.json"

    @pytest.mark.parametrize("invalid_name", ["", "../etc/passwd", "agent/name", "agent\\name", "agent name", "agent@123", "agent_name"])
    def test_validate_agent_name_invalid(self, invalid_name):
        """Should raise ValueError for invalid agent names that don't match the pattern."""
        storage = FileMemoryStorage()
        with pytest.raises(ValueError, match="Invalid agent name|Agent name must be a non-empty string"):
            storage._validate_agent_name(invalid_name)

    def test_load_creates_empty_memory(self, tmp_path):
        """Should create empty memory when file doesn't exist."""

        def mock_get_paths():
            mock_paths = MagicMock()
            mock_paths.memory_file = tmp_path / "non_existent_memory.json"
            return mock_paths

        with patch("deerflow.agents.memory.storage.get_paths", side_effect=mock_get_paths):
            with patch("deerflow.agents.memory.storage.get_memory_config", return_value=MemoryConfig(storage_path="")):
                storage = FileMemoryStorage()
                memory = storage.load()
                assert isinstance(memory, dict)
                assert memory["version"] == "1.0"

    def test_save_writes_to_file(self, tmp_path):
        """Should save memory data to file."""
        memory_file = tmp_path / "memory.json"

        def mock_get_paths():
            mock_paths = MagicMock()
            mock_paths.memory_file = memory_file
            return mock_paths

        with patch("deerflow.agents.memory.storage.get_paths", side_effect=mock_get_paths):
            with patch("deerflow.agents.memory.storage.get_memory_config", return_value=MemoryConfig(storage_path="")):
                storage = FileMemoryStorage()
                test_memory = {"version": "1.0", "facts": [{"content": "test fact"}]}
                result = storage.save(test_memory)
                assert result is True
                assert memory_file.exists()

    def test_save_does_not_mutate_caller_dict(self, tmp_path):
        """save() must not mutate the caller's dict (lastUpdated side-effect)."""
        memory_file = tmp_path / "memory.json"

        def mock_get_paths():
            mock_paths = MagicMock()
            mock_paths.memory_file = memory_file
            return mock_paths

        with patch("deerflow.agents.memory.storage.get_paths", side_effect=mock_get_paths):
            with patch("deerflow.agents.memory.storage.get_memory_config", return_value=MemoryConfig(storage_path="")):
                storage = FileMemoryStorage()
                original = {"version": "1.0", "facts": []}
                before_keys = set(original.keys())
                storage.save(original)
                assert set(original.keys()) == before_keys, "save() must not add keys to caller's dict"
                assert "lastUpdated" not in original

    def test_cache_not_corrupted_when_save_fails(self, tmp_path):
        """Cache must remain clean when save() raises OSError.

        If save() fails, the cache must NOT be updated with the new data.
        Together with the deepcopy in updater._finalize_update(), this prevents
        stale mutations from leaking into the cache when persistence fails.
        """
        memory_file = tmp_path / "memory.json"
        memory_file.parent.mkdir(parents=True, exist_ok=True)
        original_data = {"version": "1.0", "facts": [{"content": "original"}]}
        import json as _json

        memory_file.write_text(_json.dumps(original_data))

        def mock_get_paths():
            mock_paths = MagicMock()
            mock_paths.memory_file = memory_file
            return mock_paths

        with patch("deerflow.agents.memory.storage.get_paths", side_effect=mock_get_paths):
            with patch("deerflow.agents.memory.storage.get_memory_config", return_value=MemoryConfig(storage_path="")):
                storage = FileMemoryStorage()
                # Warm the cache
                cached = storage.load()
                assert cached["facts"][0]["content"] == "original"

                # Simulate save failure: mkdir succeeds but open() raises
                modified = {"version": "1.0", "facts": [{"content": "mutated"}]}
                with patch("builtins.open", side_effect=OSError("disk full")):
                    result = storage.save(modified)
                assert result is False

                # Cache must still reflect the original data, not the failed write
                after = storage.load()
                assert after["facts"][0]["content"] == "original"

    def test_cache_thread_safety(self, tmp_path):
        """Concurrent load/reload calls must not race on _memory_cache."""
        memory_file = tmp_path / "memory.json"
        memory_file.parent.mkdir(parents=True, exist_ok=True)
        import json as _json

        memory_file.write_text(_json.dumps({"version": "1.0", "facts": []}))

        def mock_get_paths():
            mock_paths = MagicMock()
            mock_paths.memory_file = memory_file
            return mock_paths

        errors: list[Exception] = []

        def load_many(storage: FileMemoryStorage) -> None:
            try:
                for _ in range(50):
                    storage.load()
            except Exception as exc:
                errors.append(exc)

        with patch("deerflow.agents.memory.storage.get_paths", side_effect=mock_get_paths):
            with patch("deerflow.agents.memory.storage.get_memory_config", return_value=MemoryConfig(storage_path="")):
                storage = FileMemoryStorage()
                threads = [threading.Thread(target=load_many, args=(storage,)) for _ in range(8)]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()

        assert not errors, f"Thread-safety errors: {errors}"

    def test_reload_forces_cache_invalidation(self, tmp_path):
        """Should force reload from file and invalidate cache."""
        memory_file = tmp_path / "memory.json"
        memory_file.parent.mkdir(parents=True, exist_ok=True)
        memory_file.write_text('{"version": "1.0", "facts": [{"content": "initial fact"}]}')

        def mock_get_paths():
            mock_paths = MagicMock()
            mock_paths.memory_file = memory_file
            return mock_paths

        with patch("deerflow.agents.memory.storage.get_paths", side_effect=mock_get_paths):
            with patch("deerflow.agents.memory.storage.get_memory_config", return_value=MemoryConfig(storage_path="")):
                storage = FileMemoryStorage()
                # First load
                memory1 = storage.load()
                assert memory1["facts"][0]["content"] == "initial fact"

                # Update file directly
                memory_file.write_text('{"version": "1.0", "facts": [{"content": "updated fact"}]}')

                # Reload should get updated data
                memory2 = storage.reload()
                assert memory2["facts"][0]["content"] == "updated fact"


class TestGetMemoryStorage:
    """Test get_memory_storage function."""

    @pytest.fixture(autouse=True)
    def reset_storage_instance(self):
        """Reset the global storage instance before and after each test."""
        import deerflow.agents.memory.storage as storage_mod

        storage_mod._storage_instance = None
        yield
        storage_mod._storage_instance = None

    def test_returns_file_memory_storage_by_default(self):
        """Should return FileMemoryStorage by default."""
        with patch("deerflow.agents.memory.storage.get_memory_config", return_value=MemoryConfig(storage_class="deerflow.agents.memory.storage.FileMemoryStorage")):
            storage = get_memory_storage()
            assert isinstance(storage, FileMemoryStorage)

    def test_falls_back_to_file_memory_storage_on_error(self):
        """Should fall back to FileMemoryStorage if configured storage fails to load."""
        with patch("deerflow.agents.memory.storage.get_memory_config", return_value=MemoryConfig(storage_class="non.existent.StorageClass")):
            storage = get_memory_storage()
            assert isinstance(storage, FileMemoryStorage)

    def test_returns_singleton_instance(self):
        """Should return the same instance on subsequent calls."""
        with patch("deerflow.agents.memory.storage.get_memory_config", return_value=MemoryConfig(storage_class="deerflow.agents.memory.storage.FileMemoryStorage")):
            storage1 = get_memory_storage()
            storage2 = get_memory_storage()
            assert storage1 is storage2

    def test_get_memory_storage_thread_safety(self):
        """Should safely initialize the singleton even with concurrent calls."""
        results = []

        def get_storage():
            # get_memory_storage is called concurrently from multiple threads while
            # get_memory_config is patched once around thread creation. This verifies
            # that the singleton initialization remains thread-safe.
            results.append(get_memory_storage())

        with patch("deerflow.agents.memory.storage.get_memory_config", return_value=MemoryConfig(storage_class="deerflow.agents.memory.storage.FileMemoryStorage")):
            threads = [threading.Thread(target=get_storage) for _ in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        # All results should be the exact same instance
        assert len(results) == 10
        assert all(r is results[0] for r in results)

    def test_get_memory_storage_invalid_class_fallback(self):
        """Should fall back to FileMemoryStorage if the configured class is not actually a class."""
        # Using a built-in function instead of a class
        with patch("deerflow.agents.memory.storage.get_memory_config", return_value=MemoryConfig(storage_class="os.path.join")):
            storage = get_memory_storage()
            assert isinstance(storage, FileMemoryStorage)

    def test_get_memory_storage_non_subclass_fallback(self):
        """Should fall back to FileMemoryStorage if the configured class is not a subclass of MemoryStorage."""
        # Using 'dict' as a class that is not a MemoryStorage subclass
        with patch("deerflow.agents.memory.storage.get_memory_config", return_value=MemoryConfig(storage_class="builtins.dict")):
            storage = get_memory_storage()
            assert isinstance(storage, FileMemoryStorage)
