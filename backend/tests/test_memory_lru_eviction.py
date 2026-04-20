"""Tests for LRU eviction in FileMemoryStorage.

Covers:
- Basic LRU ordering (OrderedDict move_to_end)
- _evict_lru_user removes the least-recently-accessed user's entries
- max_cache_entries / max_cache_entries_high_water_diff threshold behaviour
- effective_high_water property
- Thread-safety of eviction under concurrent access
- Config integration
- Edge cases: empty cache, single user, eviction to zero
"""

import threading
from unittest.mock import patch

import pytest

from deerflow.agents.memory.storage import FileMemoryStorage, create_empty_memory
from deerflow.config.memory_config import MemoryConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(max_cache: int = 100, high_water_diff: int = 20) -> MemoryConfig:
    """Create a MemoryConfig with custom cache limits for testing."""
    return MemoryConfig(
        max_cache_entries=max_cache,
        max_cache_entries_high_water_diff=high_water_diff,
    )


def _effective_high_water(max_cache: int, high_water_diff: int) -> int:
    """Compute effective high-water mark (mirrors the property)."""
    return max_cache + high_water_diff


def _seed_cache(storage: FileMemoryStorage, entries: list[tuple[str | None, str | None]]) -> None:
    """Populate the internal _memory_cache with dummy entries in order."""
    with storage._cache_lock:
        for key in entries:
            storage._memory_cache[key] = (create_empty_memory(), None)


# ---------------------------------------------------------------------------
# Tests: MemoryConfig LRU fields
# ---------------------------------------------------------------------------


class TestMemoryConfigLRUFields:
    """Test the LRU-related configuration fields."""

    def test_default_max_cache_entries(self):
        config = MemoryConfig()
        assert config.max_cache_entries == 100

    def test_default_high_water_diff(self):
        config = MemoryConfig()
        assert config.max_cache_entries_high_water_diff == 20

    def test_custom_max_cache_entries(self):
        config = MemoryConfig(max_cache_entries=50)
        assert config.max_cache_entries == 50

    def test_custom_high_water_diff(self):
        config = MemoryConfig(max_cache_entries_high_water_diff=30)
        assert config.max_cache_entries_high_water_diff == 30

    def test_high_water_diff_zero_accepted(self):
        """high_water_diff=0 means effective_high_water == max_cache_entries."""
        config = MemoryConfig(max_cache_entries_high_water_diff=0)
        assert config.max_cache_entries_high_water_diff == 0

    def test_high_water_diff_negative_rejected(self):
        with pytest.raises(Exception):
            MemoryConfig(max_cache_entries_high_water_diff=-1)

    def test_max_cache_entries_ge_one_validation(self):
        with pytest.raises(Exception):
            MemoryConfig(max_cache_entries=0)

    def test_max_cache_entries_at_minimum_boundary(self):
        config = MemoryConfig(max_cache_entries=1)
        assert config.max_cache_entries == 1

    def test_high_water_diff_zero_is_minimum(self):
        """high_water_diff=0 is the minimum accepted value."""
        config = MemoryConfig(max_cache_entries_high_water_diff=0)
        assert config.max_cache_entries_high_water_diff == 0


# ---------------------------------------------------------------------------
# Tests: effective_high_water property
# ---------------------------------------------------------------------------


class TestEffectiveHighWater:
    """Test the effective_high_water property."""

    def test_effective_high_water_is_sum(self):
        """effective_high_water = max_cache_entries + high_water_diff."""
        config = _make_config(max_cache=100, high_water_diff=20)
        assert config.effective_high_water == 120

    def test_effective_high_water_with_zero_diff(self):
        """When high_water_diff=0, effective_high_water == max_cache_entries."""
        config = _make_config(max_cache=50, high_water_diff=0)
        assert config.effective_high_water == 50

    def test_effective_high_water_with_large_diff(self):
        config = _make_config(max_cache=10, high_water_diff=90)
        assert config.effective_high_water == 100

    def test_effective_high_water_defaults(self):
        config = MemoryConfig()
        assert config.effective_high_water == 120


# ---------------------------------------------------------------------------
# Tests: _evict_lru_user
# ---------------------------------------------------------------------------


class TestEvictLRUUser:
    """Test the _evict_lru_user method."""

    def test_evict_on_empty_cache_does_nothing(self):
        storage = FileMemoryStorage()
        with storage._cache_lock:
            storage._evict_lru_user()
        assert len(storage._memory_cache) == 0

    def test_evict_removes_least_recently_accessed_user(self):
        storage = FileMemoryStorage()
        _seed_cache(storage, [("alice", None), ("alice", "agent1"), ("bob", None)])

        with storage._cache_lock:
            storage._evict_lru_user()

        assert ("alice", None) not in storage._memory_cache
        assert ("alice", "agent1") not in storage._memory_cache
        assert ("bob", None) in storage._memory_cache

    def test_evict_removes_all_entries_for_lru_user(self):
        storage = FileMemoryStorage()
        _seed_cache(storage, [("alice", None), ("alice", "agent1"), ("alice", "agent2"), ("bob", None)])

        with storage._cache_lock:
            storage._evict_lru_user()

        assert len([k for k in storage._memory_cache if k[0] == "alice"]) == 0
        assert ("bob", None) in storage._memory_cache

    def test_evict_with_single_user(self):
        storage = FileMemoryStorage()
        _seed_cache(storage, [("alice", None), ("alice", "agent1")])

        with storage._cache_lock:
            storage._evict_lru_user()

        assert len(storage._memory_cache) == 0

    def test_evict_preserves_most_recently_accessed_user(self):
        storage = FileMemoryStorage()
        _seed_cache(storage, [("alice", None), ("bob", None), ("charlie", None)])

        with storage._cache_lock:
            storage._evict_lru_user()

        assert ("alice", None) not in storage._memory_cache
        assert ("charlie", None) in storage._memory_cache

    def test_evict_with_none_user_id(self):
        storage = FileMemoryStorage()
        _seed_cache(storage, [(None, None), ("alice", None)])

        with storage._cache_lock:
            storage._evict_lru_user()

        assert (None, None) not in storage._memory_cache
        assert ("alice", None) in storage._memory_cache


# ---------------------------------------------------------------------------
# Tests: _touch_and_evict
# ---------------------------------------------------------------------------


class TestTouchAndEvict:
    """Test the _touch_and_evict method."""

    def test_touch_moves_existing_key_to_end(self):
        storage = FileMemoryStorage()
        _seed_cache(storage, [("alice", None), ("bob", None)])

        with storage._cache_lock:
            storage._touch_and_evict(("alice", None))

        keys = list(storage._memory_cache.keys())
        assert keys[-1] == ("alice", None)

    def test_touch_nonexistent_key_does_not_add(self):
        storage = FileMemoryStorage()
        _seed_cache(storage, [("alice", None)])

        with storage._cache_lock:
            storage._touch_and_evict(("bob", None))

        assert ("bob", None) not in storage._memory_cache
        assert len(storage._memory_cache) == 1

    def test_eviction_triggers_when_over_high_water_mark(self):
        """Eviction should trigger when cache size exceeds effective_high_water."""
        config = _make_config(max_cache=10, high_water_diff=2)
        storage = FileMemoryStorage()
        with patch("deerflow.agents.memory.storage.get_memory_config", return_value=config):
            # effective_high_water = 12, seed 14 entries
            entries = [(f"user{i}", None) for i in range(14)]
            _seed_cache(storage, entries)

            with storage._cache_lock:
                storage._touch_and_evict(("user13", None))

            assert len(storage._memory_cache) <= config.max_cache_entries

    def test_no_eviction_between_max_cache_and_high_water(self):
        """No eviction when cache is between max_cache_entries and effective_high_water."""
        config = _make_config(max_cache=10, high_water_diff=5)
        storage = FileMemoryStorage()
        with patch("deerflow.agents.memory.storage.get_memory_config", return_value=config):
            # effective_high_water = 15, seed 12 entries
            entries = [(f"user{i}", None) for i in range(12)]
            _seed_cache(storage, entries)

            with storage._cache_lock:
                storage._touch_and_evict(("user11", None))

            assert len(storage._memory_cache) == 12

    def test_no_eviction_below_max_cache(self):
        config = _make_config(max_cache=20, high_water_diff=5)
        storage = FileMemoryStorage()
        with patch("deerflow.agents.memory.storage.get_memory_config", return_value=config):
            _seed_cache(storage, [("alice", None), ("bob", None), ("charlie", None)])

            with storage._cache_lock:
                storage._touch_and_evict(("charlie", None))

            assert len(storage._memory_cache) == 3

    def test_eviction_drains_to_max_cache_entries(self):
        config = _make_config(max_cache=10, high_water_diff=2)
        storage = FileMemoryStorage()
        with patch("deerflow.agents.memory.storage.get_memory_config", return_value=config):
            # 18 entries: 6 users x 3 keys each (exceeds effective_high_water=12)
            entries = []
            for i in range(6):
                uid = f"user{i}"
                entries.extend([(uid, None), (uid, "a1"), (uid, "a2")])
            _seed_cache(storage, entries)

            with storage._cache_lock:
                storage._touch_and_evict(("user5", "a2"))

            assert len(storage._memory_cache) <= config.max_cache_entries

    def test_touch_preserves_recently_accessed_entries(self):
        config = _make_config(max_cache=10, high_water_diff=2)
        storage = FileMemoryStorage()
        with patch("deerflow.agents.memory.storage.get_memory_config", return_value=config):
            # effective_high_water = 12, seed 14 entries
            entries = [(f"user{i}", None) for i in range(14)]
            _seed_cache(storage, entries)

            with storage._cache_lock:
                storage._touch_and_evict(("user13", None))

            assert ("user13", None) in storage._memory_cache
            assert len(storage._memory_cache) <= config.max_cache_entries

    def test_eviction_with_zero_high_water_diff(self):
        """When high_water_diff=0, eviction triggers when exceeding max_cache_entries."""
        config = _make_config(max_cache=10, high_water_diff=0)
        storage = FileMemoryStorage()
        with patch("deerflow.agents.memory.storage.get_memory_config", return_value=config):
            # effective_high_water = 10, seed 11 entries
            entries = [(f"user{i}", None) for i in range(11)]
            _seed_cache(storage, entries)

            with storage._cache_lock:
                storage._touch_and_evict(("user10", None))

            assert len(storage._memory_cache) <= config.max_cache_entries


# ---------------------------------------------------------------------------
# Tests: Integration with load/save/reload
# ---------------------------------------------------------------------------


class TestLRUWithLoadSaveReload:
    """Test that LRU eviction works correctly with load/save/reload operations."""

    def test_load_updates_lru_order(self, tmp_path):
        from deerflow.config.paths import Paths

        paths = Paths(tmp_path)
        config = _make_config(max_cache=20, high_water_diff=5)
        with patch("deerflow.agents.memory.storage.get_paths", return_value=paths), patch(
            "deerflow.agents.memory.storage.get_memory_config", return_value=config
        ):
            storage = FileMemoryStorage()
            for uid in ["alice", "bob", "charlie"]:
                mem = create_empty_memory()
                mem["user"]["workContext"]["summary"] = f"{uid} context"
                storage.save(mem, user_id=uid)

            storage.load(user_id="alice")

            keys = list(storage._memory_cache.keys())
            assert keys[-1][0] == "alice"

    def test_save_updates_lru_order(self, tmp_path):
        from deerflow.config.paths import Paths

        paths = Paths(tmp_path)
        config = _make_config(max_cache=20, high_water_diff=5)
        with patch("deerflow.agents.memory.storage.get_paths", return_value=paths), patch(
            "deerflow.agents.memory.storage.get_memory_config", return_value=config
        ):
            storage = FileMemoryStorage()
            mem = create_empty_memory()
            storage.save(mem, user_id="alice")
            storage.save(mem, user_id="bob")

            mem2 = create_empty_memory()
            mem2["user"]["workContext"]["summary"] = "updated"
            storage.save(mem2, user_id="alice")

            keys = list(storage._memory_cache.keys())
            assert keys[-1] == ("alice", None)

    def test_reload_updates_lru_order(self, tmp_path):
        from deerflow.config.paths import Paths

        paths = Paths(tmp_path)
        config = _make_config(max_cache=20, high_water_diff=5)
        with patch("deerflow.agents.memory.storage.get_paths", return_value=paths), patch(
            "deerflow.agents.memory.storage.get_memory_config", return_value=config
        ):
            storage = FileMemoryStorage()
            mem = create_empty_memory()
            storage.save(mem, user_id="alice")
            storage.save(mem, user_id="bob")

            storage.reload(user_id="alice")

            keys = list(storage._memory_cache.keys())
            assert keys[-1] == ("alice", None)

    def test_eviction_during_save(self, tmp_path):
        from deerflow.config.paths import Paths

        paths = Paths(tmp_path)
        config = _make_config(max_cache=10, high_water_diff=2)
        with patch("deerflow.agents.memory.storage.get_paths", return_value=paths), patch(
            "deerflow.agents.memory.storage.get_memory_config", return_value=config
        ):
            storage = FileMemoryStorage()
            mem = create_empty_memory()

            # Fill to effective_high_water = 12
            for i in range(12):
                storage.save(mem, user_id=f"user{i}")

            # 13th user pushes past effective_high_water, should trigger eviction
            storage.save(mem, user_id="dave")

            assert len(storage._memory_cache) <= config.max_cache_entries
            assert ("dave", None) in storage._memory_cache

    def test_eviction_does_not_corrupt_data(self, tmp_path):
        from deerflow.config.paths import Paths

        paths = Paths(tmp_path)
        config = _make_config(max_cache=10, high_water_diff=2)
        with patch("deerflow.agents.memory.storage.get_paths", return_value=paths), patch(
            "deerflow.agents.memory.storage.get_memory_config", return_value=config
        ):
            storage = FileMemoryStorage()

            for i in range(15):
                mem = create_empty_memory()
                mem["user"]["workContext"]["summary"] = f"user{i} context"
                storage.save(mem, user_id=f"user{i}")

            loaded_last = storage.load(user_id="user14")
            assert loaded_last["user"]["workContext"]["summary"] == "user14 context"

    def test_evicted_entry_can_be_reloaded_from_file(self, tmp_path):
        from deerflow.config.paths import Paths

        paths = Paths(tmp_path)
        config = _make_config(max_cache=10, high_water_diff=2)
        with patch("deerflow.agents.memory.storage.get_paths", return_value=paths), patch(
            "deerflow.agents.memory.storage.get_memory_config", return_value=config
        ):
            storage = FileMemoryStorage()

            for i in range(15):
                mem = create_empty_memory()
                mem["user"]["workContext"]["summary"] = f"user{i} context"
                storage.save(mem, user_id=f"user{i}")

            assert ("user0", None) not in storage._memory_cache

            loaded_user0 = storage.load(user_id="user0")
            assert loaded_user0["user"]["workContext"]["summary"] == "user0 context"


# ---------------------------------------------------------------------------
# Tests: Multi-user eviction order
# ---------------------------------------------------------------------------


class TestMultiUserEvictionOrder:
    """Test eviction order with multiple users and agents."""

    def test_lru_user_evicted_not_lru_agent(self):
        storage = FileMemoryStorage()
        _seed_cache(storage, [("alice", None), ("alice", "agent1"), ("bob", None)])

        with storage._cache_lock:
            storage._evict_lru_user()

        assert len([k for k in storage._memory_cache if k[0] == "alice"]) == 0
        assert ("bob", None) in storage._memory_cache

    def test_user_with_multiple_agents_evicted_as_group(self):
        storage = FileMemoryStorage()
        _seed_cache(
            storage,
            [
                ("alice", None),
                ("alice", "a1"),
                ("alice", "a2"),
                ("alice", "a3"),
                ("bob", None),
            ],
        )

        with storage._cache_lock:
            storage._evict_lru_user()

        assert len(storage._memory_cache) == 1
        assert ("bob", None) in storage._memory_cache

    def test_sequential_evictions(self):
        storage = FileMemoryStorage()
        _seed_cache(storage, [("alice", None), ("bob", None), ("charlie", None)])

        with storage._cache_lock:
            storage._evict_lru_user()
            assert ("alice", None) not in storage._memory_cache
            assert len(storage._memory_cache) == 2

            storage._evict_lru_user()
            assert ("bob", None) not in storage._memory_cache
            assert len(storage._memory_cache) == 1

            storage._evict_lru_user()
            assert len(storage._memory_cache) == 0


# ---------------------------------------------------------------------------
# Tests: Thread safety
# ---------------------------------------------------------------------------


class TestLRUThreadSafety:
    """Test that LRU eviction is thread-safe under concurrent access."""

    def test_concurrent_loads_do_not_corrupt_cache(self, tmp_path):
        from deerflow.config.paths import Paths

        paths = Paths(tmp_path)
        config = _make_config(max_cache=20, high_water_diff=5)
        with patch("deerflow.agents.memory.storage.get_paths", return_value=paths), patch(
            "deerflow.agents.memory.storage.get_memory_config", return_value=config
        ):
            storage = FileMemoryStorage()
            for uid in ["alice", "bob", "charlie"]:
                mem = create_empty_memory()
                mem["user"]["workContext"]["summary"] = f"{uid} context"
                storage.save(mem, user_id=uid)

            errors = []

            def load_user(uid):
                try:
                    result = storage.load(user_id=uid)
                    if result["user"]["workContext"]["summary"] != f"{uid} context":
                        errors.append(f"Wrong data for {uid}")
                except Exception as e:
                    errors.append(str(e))

            threads = [threading.Thread(target=load_user, args=(uid,)) for uid in ["alice", "bob", "charlie"] * 10]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert errors == [], f"Concurrent load errors: {errors}"

    def test_concurrent_saves_do_not_crash(self, tmp_path):
        from deerflow.config.paths import Paths

        paths = Paths(tmp_path)
        config = _make_config(max_cache=10, high_water_diff=2)
        with patch("deerflow.agents.memory.storage.get_paths", return_value=paths), patch(
            "deerflow.agents.memory.storage.get_memory_config", return_value=config
        ):
            storage = FileMemoryStorage()
            errors = []

            def save_user(uid):
                try:
                    mem = create_empty_memory()
                    mem["user"]["workContext"]["summary"] = f"{uid} context"
                    storage.save(mem, user_id=uid)
                except Exception as e:
                    if not isinstance(e, OSError):
                        errors.append(str(e))

            threads = []
            for uid in [f"user{i}" for i in range(20)]:
                for _ in range(3):
                    threads.append(threading.Thread(target=save_user, args=(uid,)))

            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert errors == [], f"Unexpected errors during concurrent saves: {errors}"


# ---------------------------------------------------------------------------
# Tests: Edge cases
# ---------------------------------------------------------------------------


class TestLRUEdgeCases:
    """Edge case tests for LRU eviction."""

    def test_single_entry_below_max_cache(self):
        config = _make_config(max_cache=20, high_water_diff=5)
        storage = FileMemoryStorage()
        with patch("deerflow.agents.memory.storage.get_memory_config", return_value=config):
            _seed_cache(storage, [("alice", None)])

            with storage._cache_lock:
                storage._touch_and_evict(("alice", None))

            assert len(storage._memory_cache) == 1

    def test_cache_order_after_multiple_touches(self, tmp_path):
        from deerflow.config.paths import Paths

        paths = Paths(tmp_path)
        config = _make_config(max_cache=20, high_water_diff=5)
        with patch("deerflow.agents.memory.storage.get_paths", return_value=paths), patch(
            "deerflow.agents.memory.storage.get_memory_config", return_value=config
        ):
            storage = FileMemoryStorage()

            for uid in ["alice", "bob", "charlie"]:
                mem = create_empty_memory()
                storage.save(mem, user_id=uid)

            storage.load(user_id="charlie")
            storage.load(user_id="alice")
            storage.load(user_id="bob")

            keys = list(storage._memory_cache.keys())
            assert keys[-1] == ("bob", None)
            assert keys[-2] == ("alice", None)

    def test_agent_entries_grouped_by_user_for_eviction(self, tmp_path):
        from deerflow.config.paths import Paths

        paths = Paths(tmp_path)
        config = _make_config(max_cache=10, high_water_diff=2)
        with patch("deerflow.agents.memory.storage.get_paths", return_value=paths), patch(
            "deerflow.agents.memory.storage.get_memory_config", return_value=config
        ):
            storage = FileMemoryStorage()
            mem = create_empty_memory()

            storage.save(mem, user_id="alice")
            storage.save(mem, "test-agent", user_id="alice")
            storage.save(mem, "another-agent", user_id="alice")
            storage.save(mem, user_id="bob")

            for i in range(10):
                storage.save(mem, user_id=f"filler{i}")

            alice_entries = [k for k in storage._memory_cache if k[0] == "alice"]
            assert len(alice_entries) == 0

    def test_load_after_external_file_change_updates_cache(self, tmp_path):
        import json
        import os

        from deerflow.config.paths import Paths

        paths = Paths(tmp_path)
        config = _make_config(max_cache=20, high_water_diff=5)
        with patch("deerflow.agents.memory.storage.get_paths", return_value=paths), patch(
                "deerflow.agents.memory.storage.get_memory_config", return_value=config
        ):
            storage = FileMemoryStorage()

            mem = create_empty_memory()
            mem["user"]["workContext"]["summary"] = "original"
            storage.save(mem, user_id="alice")

            user_file = tmp_path / "users" / "alice" / "memory.json"
            updated = create_empty_memory()
            updated["user"]["workContext"]["summary"] = "externally modified"
            user_file.write_text(json.dumps(updated))

            # Force mtime forward for Windows compatibility
            current_mtime = user_file.stat().st_mtime
            os.utime(user_file, (current_mtime + 2, current_mtime + 2))

            loaded = storage.load(user_id="alice")
            assert loaded["user"]["workContext"]["summary"] == "externally modified"

    def test_zero_high_water_diff_with_large_max_cache(self):
        """When high_water_diff=0, eviction triggers at exactly max_cache_entries."""
        config = _make_config(max_cache=10, high_water_diff=0)
        assert config.effective_high_water == 10
        storage = FileMemoryStorage()
        with patch("deerflow.agents.memory.storage.get_memory_config", return_value=config):
            entries = [(f"user{i}", None) for i in range(11)]
            _seed_cache(storage, entries)

            with storage._cache_lock:
                storage._touch_and_evict(("user10", None))

            assert len(storage._memory_cache) <= config.max_cache_entries
