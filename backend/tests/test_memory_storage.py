"""Tests for memory storage providers (DI: FileMemoryStorage(config) / create_storage)."""

import threading
from unittest.mock import patch

import pytest

from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig
from deerflow.agents.memory.backends.deermem.deermem.core.paths import validate_agent_name
from deerflow.agents.memory.backends.deermem.deermem.core.storage import (
    FileMemoryStorage,
    MemoryStorage,
    create_empty_memory,
    create_storage,
    normalize_memory_data,
)


def _storage_at(memory_file) -> FileMemoryStorage:
    """A FileMemoryStorage rooted at the directory containing ``memory_file``."""
    root = str(memory_file.parent.resolve())
    return FileMemoryStorage(DeerMemConfig(storage_path=root))


class TestCreateEmptyMemory:
    """Test create_empty_memory function."""

    def test_returns_valid_structure(self):
        memory = create_empty_memory()
        assert isinstance(memory, dict)
        assert memory["version"] == "1.0"
        assert "lastUpdated" in memory
        assert isinstance(memory["user"], dict)
        assert isinstance(memory["history"], dict)
        assert isinstance(memory["facts"], list)


class TestNormalizeMemoryData:
    """Test backward-compatible memory schema normalization."""

    def test_normalizes_legacy_facts_without_mutating_input(self):
        legacy = {
            "version": "1.0",
            "lastUpdated": "",
            "user": {},
            "history": {},
            "facts": [
                {"content": "User prefers conclusions first", "category": "cognitive"},
                None,
                {"category": "context"},
            ],
        }

        normalized = normalize_memory_data(legacy)

        assert legacy == {
            "version": "1.0",
            "lastUpdated": "",
            "user": {},
            "history": {},
            "facts": [
                {"content": "User prefers conclusions first", "category": "cognitive"},
                None,
                {"category": "context"},
            ],
        }
        assert len(normalized["facts"]) == 1
        fact = normalized["facts"][0]
        assert fact["id"].startswith("fact_")
        assert fact["content"] == "User prefers conclusions first"
        assert fact["category"] == "cognitive"
        assert fact["confidence"] == 0.0
        assert fact["createdAt"] == ""
        assert fact["source"] == ""


class TestMemoryStorageInterface:
    """Test MemoryStorage abstract base class."""

    def test_abstract_methods(self):
        class TestStorage(MemoryStorage):
            pass

        with pytest.raises(TypeError):
            TestStorage(DeerMemConfig())


class TestFileMemoryStorage:
    """Test FileMemoryStorage implementation (DI: constructed with a config)."""

    def test_get_memory_file_path_global(self, tmp_path, monkeypatch):
        """DEERMEM_DATA_DIR as root + empty storage_path => global legacy path."""
        monkeypatch.setenv("DEERMEM_DATA_DIR", str(tmp_path))
        storage = FileMemoryStorage(DeerMemConfig())
        assert storage._get_memory_file_path(None) == tmp_path / "memory.json"

    def test_get_memory_file_path_agent(self, tmp_path, monkeypatch):
        """Legacy per-agent path lives under the DeerMem root ($DEERMEM_DATA_DIR)."""
        monkeypatch.setenv("DEERMEM_DATA_DIR", str(tmp_path))
        storage = FileMemoryStorage(DeerMemConfig())
        path = storage._get_memory_file_path("test-agent")
        assert path == tmp_path / "agents" / "test-agent" / "memory.json"

    @pytest.mark.parametrize("invalid_name", ["", "../etc/passwd", "agent/name", "agent\\name", "agent name", "agent@123", "agent_name"])
    def test_validate_agent_name_invalid(self, invalid_name):
        """Should raise ValueError for invalid agent names."""
        with pytest.raises(ValueError, match="Invalid agent name|Agent name must be a non-empty string"):
            validate_agent_name(invalid_name)

    def test_load_creates_empty_memory(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DEERMEM_DATA_DIR", str(tmp_path))
        storage = FileMemoryStorage(DeerMemConfig())
        memory = storage.load()
        assert isinstance(memory, dict)
        assert memory["version"] == "1.0"

    def test_save_writes_to_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DEERMEM_DATA_DIR", str(tmp_path))
        memory_file = tmp_path / "memory.json"
        storage = FileMemoryStorage(DeerMemConfig())
        result = storage.save({"version": "1.0", "facts": [{"content": "test fact"}]})
        assert result is True
        assert memory_file.exists()

    def test_save_does_not_mutate_caller_dict(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DEERMEM_DATA_DIR", str(tmp_path))
        storage = FileMemoryStorage(DeerMemConfig())
        original = {"version": "1.0", "facts": []}
        before_keys = set(original.keys())
        storage.save(original)
        assert set(original.keys()) == before_keys, "save() must not add keys to caller's dict"
        assert "lastUpdated" not in original

    def test_cache_not_corrupted_when_save_fails(self, tmp_path, monkeypatch):
        """Cache must remain clean when save() raises OSError."""
        monkeypatch.setenv("DEERMEM_DATA_DIR", str(tmp_path))
        memory_file = tmp_path / "memory.json"
        memory_file.parent.mkdir(parents=True, exist_ok=True)
        import json as _json

        memory_file.write_text(_json.dumps({"version": "1.0", "facts": [{"content": "original"}]}))
        storage = FileMemoryStorage(DeerMemConfig())
        cached = storage.load()
        assert cached["facts"][0]["content"] == "original"

        with patch("builtins.open", side_effect=OSError("disk full")):
            result = storage.save({"version": "1.0", "facts": [{"content": "mutated"}]})
        assert result is False
        after = storage.load()
        assert after["facts"][0]["content"] == "original"

    def test_cache_thread_safety(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DEERMEM_DATA_DIR", str(tmp_path))
        memory_file = tmp_path / "memory.json"
        memory_file.parent.mkdir(parents=True, exist_ok=True)
        import json as _json

        memory_file.write_text(_json.dumps({"version": "1.0", "facts": []}))
        storage = FileMemoryStorage(DeerMemConfig())
        errors: list[Exception] = []

        def load_many(s: FileMemoryStorage) -> None:
            try:
                for _ in range(50):
                    s.load()
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=load_many, args=(storage,)) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors, f"Thread-safety errors: {errors}"

    def test_reload_forces_cache_invalidation(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DEERMEM_DATA_DIR", str(tmp_path))
        memory_file = tmp_path / "memory.json"
        memory_file.parent.mkdir(parents=True, exist_ok=True)
        memory_file.write_text('{"version": "1.0", "facts": [{"content": "initial fact"}]}')
        storage = FileMemoryStorage(DeerMemConfig())
        memory1 = storage.load()
        assert memory1["facts"][0]["content"] == "initial fact"
        memory_file.write_text('{"version": "1.0", "facts": [{"content": "updated fact"}]}')
        memory2 = storage.reload()
        assert memory2["facts"][0]["content"] == "updated fact"


class TestCreateStorage:
    """Test create_storage(config) (replaces the old get_memory_storage() singleton)."""

    def test_returns_file_memory_storage_by_default(self):
        """Empty storage_class (default) -> FileMemoryStorage directly."""
        assert isinstance(create_storage(DeerMemConfig()), FileMemoryStorage)

    def test_raises_on_unresolvable_storage_class(self):
        """An unimportable storage_class raises ValueError (fail-fast), not a silent
        FileMemoryStorage fallback -- memory is persistent state, so a wrong store
        is a data-integrity footgun. Mirrors the manager_class resolution policy."""
        with pytest.raises(ValueError, match="storage_class"):
            create_storage(DeerMemConfig(storage_class="non.existent.StorageClass"))

    def test_raises_on_non_class_storage_class(self):
        """A storage_class that resolves to a non-class (e.g. a function) raises
        ValueError, not a silent fallback to FileMemoryStorage."""
        with pytest.raises(ValueError, match="storage_class"):
            create_storage(DeerMemConfig(storage_class="os.path.join"))

    def test_raises_on_non_subclass_storage_class(self):
        """A storage_class that is not a MemoryStorage subclass raises ValueError,
        not a silent fallback to FileMemoryStorage."""
        with pytest.raises(ValueError, match="storage_class"):
            create_storage(DeerMemConfig(storage_class="builtins.dict"))

    def test_dotted_storage_class_resolves(self):
        storage = create_storage(DeerMemConfig(storage_class="deerflow.agents.memory.backends.deermem.deermem.core.storage.FileMemoryStorage"))
        assert isinstance(storage, FileMemoryStorage)


def test_load_normalizes_legacy_json_without_cognitive_style(tmp_path) -> None:
    memory_file = tmp_path / "memory.json"
    memory_file.write_text(
        '{"version":"1.0","lastUpdated":"","user":{"workContext":{"summary":"work","updatedAt":""}},"history":{},"facts":[]}',
        encoding="utf-8",
    )
    storage = _storage_at(memory_file)

    loaded = storage.load()

    assert loaded["user"]["cognitiveStyle"] == {"summary": "", "updatedAt": ""}
    assert loaded["user"]["workContext"]["summary"] == "work"


def test_cache_hit_returns_already_normalized_memory(tmp_path) -> None:
    memory_file = tmp_path / "memory.json"
    memory_file.write_text(
        '{"version":"1.0","lastUpdated":"","user":{},"history":{},"facts":[{"content":"Legacy cached fact"}]}',
        encoding="utf-8",
    )

    with patch(
        "deerflow.agents.memory.backends.deermem.deermem.core.storage.normalize_memory_data",
        wraps=normalize_memory_data,
    ) as normalize:
        storage = _storage_at(memory_file)
        first = storage.load()
        calls_after_first_load = normalize.call_count
        second = storage.load()

    assert normalize.call_count == calls_after_first_load
    assert second is first
    assert second["facts"][0]["id"] == first["facts"][0]["id"]
