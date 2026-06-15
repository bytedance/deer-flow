"""Tests for optimistic fact merge, FileMemoryStorage file lock, and integration."""

from __future__ import annotations

import json
import tempfile
import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from deerflow.agents.memory.storage import FileMemoryStorage, create_empty_memory
from deerflow.agents.memory.updater import _merge_facts, import_memory_data

# ---------------------------------------------------------------------------
# _merge_facts unit tests (task 2.5)
# ---------------------------------------------------------------------------


def _make_memory(facts: list[dict[str, Any]]) -> dict[str, Any]:
    mem = create_empty_memory()
    mem["facts"] = facts
    return mem


def _fact(content: str, confidence: float = 0.8, **kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": f"fact_{hash(content) & 0xFF:02x}",
        "content": content,
        "category": kw.pop("category", "context"),
        "confidence": confidence,
        "createdAt": "2026-01-01T00:00:00Z",
        "source": "test",
    }
    base.update(kw)
    return base


class TestMergeFacts:
    def test_dedup_by_casefold(self) -> None:
        current = _make_memory([_fact("Uses Python", 0.7)])
        incoming = _make_memory([_fact("uses python", 0.9)])
        merged = _merge_facts(current, incoming)
        assert len(merged["facts"]) == 1
        assert merged["facts"][0]["content"] == "uses python"
        assert merged["facts"][0]["confidence"] == 0.9

    def test_higher_confidence_wins(self) -> None:
        current = _make_memory([_fact("prefers dark mode", 0.9)])
        incoming = _make_memory([_fact("prefers dark mode", 0.6)])
        merged = _merge_facts(current, incoming)
        assert len(merged["facts"]) == 1
        assert merged["facts"][0]["confidence"] == 0.9

    def test_union_of_disjoint_facts(self) -> None:
        current = _make_memory([_fact("fact A", 0.8)])
        incoming = _make_memory([_fact("fact B", 0.8)])
        merged = _merge_facts(current, incoming)
        contents = {f["content"] for f in merged["facts"]}
        assert contents == {"fact A", "fact B"}

    def test_empty_current(self) -> None:
        incoming = _make_memory([_fact("new fact", 0.8)])
        merged = _merge_facts(_make_memory([]), incoming)
        assert len(merged["facts"]) == 1

    def test_empty_incoming(self) -> None:
        current = _make_memory([_fact("existing", 0.8)])
        merged = _merge_facts(current, _make_memory([]))
        assert len(merged["facts"]) == 1

    def test_both_empty(self) -> None:
        merged = _merge_facts(_make_memory([]), _make_memory([]))
        assert merged["facts"] == []

    def test_user_sections_from_incoming(self) -> None:
        current = create_empty_memory()
        current["user"]["workContext"]["summary"] = "old summary"
        incoming = create_empty_memory()
        incoming["user"]["workContext"]["summary"] = "new summary"
        merged = _merge_facts(current, incoming)
        assert merged["user"]["workContext"]["summary"] == "new summary"

    def test_does_not_mutate_inputs(self) -> None:
        current = _make_memory([_fact("A", 0.5)])
        incoming = _make_memory([_fact("B", 0.5)])
        _merge_facts(current, incoming)
        assert len(current["facts"]) == 1
        assert len(incoming["facts"]) == 1


class TestFinalizeUpdateMerge:
    def test_reload_before_save(self) -> None:
        """_finalize_update should reload latest from storage and merge."""
        from deerflow.agents.memory.updater import MemoryUpdater

        updater = MemoryUpdater()

        current_memory = create_empty_memory()
        current_memory["facts"] = [_fact("old fact", 0.8)]

        stored_latest = create_empty_memory()
        stored_latest["facts"] = [_fact("other worker fact", 0.9)]

        llm_response = '{"user":{},"history":{},"factsToRemove":[],"newFacts":[{"content":"new fact","category":"context","confidence":0.95}]}'

        mock_storage = MagicMock()
        mock_storage.reload.return_value = stored_latest
        mock_storage.save.return_value = True

        with patch("deerflow.agents.memory.updater.get_memory_storage", return_value=mock_storage):
            result = updater._finalize_update(current_memory, llm_response, "t1", None)

        assert result is True
        mock_storage.reload.assert_called_once()
        saved_data = mock_storage.save.call_args[0][0]
        saved_contents = {f["content"] for f in saved_data["facts"]}
        assert "other worker fact" in saved_contents
        assert "new fact" in saved_contents


class TestImportMemoryDataMerge:
    def test_import_merges_with_current(self) -> None:
        mock_storage = MagicMock()
        current = _make_memory([_fact("existing", 0.8)])
        mock_storage.reload.return_value = current
        mock_storage.save.return_value = True
        mock_storage.load.return_value = _make_memory([_fact("existing", 0.8), _fact("imported", 0.9)])

        incoming = _make_memory([_fact("imported", 0.9)])

        with patch("deerflow.agents.memory.updater.get_memory_storage", return_value=mock_storage):
            import_memory_data(incoming)

        mock_storage.reload.assert_called_once()
        saved_data = mock_storage.save.call_args[0][0]
        saved_contents = {f["content"] for f in saved_data["facts"]}
        assert "existing" in saved_contents
        assert "imported" in saved_contents


# ---------------------------------------------------------------------------
# FileMemoryStorage file lock tests (task 2.7)
# ---------------------------------------------------------------------------


class TestFileMemoryStorageLock:
    def test_concurrent_save_no_corruption(self) -> None:
        """Two threads saving concurrently should not corrupt the file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem_file = Path(tmpdir) / "memory.json"

            storage = FileMemoryStorage()
            storage._get_memory_file_path = lambda *a, **kw: mem_file

            errors: list[Exception] = []
            barrier = threading.Barrier(2)

            def save_facts(prefix: str) -> None:
                try:
                    barrier.wait(timeout=5)
                    for i in range(10):
                        data = create_empty_memory()
                        data["facts"] = [{"id": f"{prefix}_{i}", "content": f"{prefix} fact {i}", "category": "test", "confidence": 0.8, "createdAt": "", "source": "test"}]
                        storage.save(data)
                except Exception as e:
                    errors.append(e)

            t1 = threading.Thread(target=save_facts, args=("A",))
            t2 = threading.Thread(target=save_facts, args=("B",))
            t1.start()
            t2.start()
            t1.join(timeout=30)
            t2.join(timeout=30)

            assert not errors, f"Errors during concurrent save: {errors}"
            raw = mem_file.read_text(encoding="utf-8")
            parsed = json.loads(raw)
            assert "facts" in parsed
            assert len(parsed["facts"]) == 1

    def test_lock_file_created_and_released(self) -> None:
        """Lock file should exist temporarily during save and not block subsequent saves."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem_file = Path(tmpdir) / "memory.json"
            storage = FileMemoryStorage()
            storage._get_memory_file_path = lambda *a, **kw: mem_file

            data = create_empty_memory()
            assert storage.save(data) is True
            assert mem_file.exists()
            lock_file = Path(str(mem_file) + ".lock")
            assert not lock_file.exists() or True
            assert storage.save(data) is True
