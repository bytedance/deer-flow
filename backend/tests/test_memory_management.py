"""Tests for memory management operations (delete fact, clear all)."""

import json
from pathlib import Path
from unittest.mock import patch

from deerflow.agents.memory.updater import (
    _create_empty_memory,
    clear_memory,
    delete_memory_fact,
)


def _make_memory_with_facts() -> dict:
    return {
        "version": "1.0",
        "lastUpdated": "2024-01-15T10:30:00Z",
        "user": {
            "workContext": {"summary": "Working on DeerFlow", "updatedAt": "2024-01-15T10:30:00Z"},
            "personalContext": {"summary": "", "updatedAt": ""},
            "topOfMind": {"summary": "", "updatedAt": ""},
        },
        "history": {
            "recentMonths": {"summary": "", "updatedAt": ""},
            "earlierContext": {"summary": "", "updatedAt": ""},
            "longTermBackground": {"summary": "", "updatedAt": ""},
        },
        "facts": [
            {
                "id": "fact_001",
                "content": "User prefers TypeScript",
                "category": "preference",
                "confidence": 0.9,
                "createdAt": "2024-01-15T10:30:00Z",
                "source": "thread_abc",
            },
            {
                "id": "fact_002",
                "content": "User works on AI projects",
                "category": "context",
                "confidence": 0.85,
                "createdAt": "2024-01-15T11:00:00Z",
                "source": "thread_def",
            },
            {
                "id": "fact_003",
                "content": "User likes dark mode",
                "category": "preference",
                "confidence": 0.7,
                "createdAt": "2024-01-16T09:00:00Z",
                "source": "thread_ghi",
            },
        ],
    }


class TestDeleteMemoryFact:
    def test_delete_existing_fact(self, tmp_path: Path) -> None:
        memory_file = tmp_path / "memory.json"
        memory_data = _make_memory_with_facts()
        memory_file.write_text(json.dumps(memory_data))

        with patch("deerflow.agents.memory.updater._get_memory_file_path", return_value=memory_file):
            # Clear the cache so it reads from file
            from deerflow.agents.memory.updater import _memory_cache

            _memory_cache.clear()

            result = delete_memory_fact("fact_002")
            assert result is True

            # Verify the fact was removed
            updated = json.loads(memory_file.read_text())
            fact_ids = [f["id"] for f in updated["facts"]]
            assert "fact_002" not in fact_ids
            assert "fact_001" in fact_ids
            assert "fact_003" in fact_ids
            assert len(updated["facts"]) == 2

    def test_delete_nonexistent_fact(self, tmp_path: Path) -> None:
        memory_file = tmp_path / "memory.json"
        memory_data = _make_memory_with_facts()
        memory_file.write_text(json.dumps(memory_data))

        with patch("deerflow.agents.memory.updater._get_memory_file_path", return_value=memory_file):
            from deerflow.agents.memory.updater import _memory_cache

            _memory_cache.clear()

            result = delete_memory_fact("fact_nonexistent")
            assert result is False

            # Verify no facts were removed
            updated = json.loads(memory_file.read_text())
            assert len(updated["facts"]) == 3

    def test_delete_from_empty_facts(self, tmp_path: Path) -> None:
        memory_file = tmp_path / "memory.json"
        memory_data = _make_memory_with_facts()
        memory_data["facts"] = []
        memory_file.write_text(json.dumps(memory_data))

        with patch("deerflow.agents.memory.updater._get_memory_file_path", return_value=memory_file):
            from deerflow.agents.memory.updater import _memory_cache

            _memory_cache.clear()

            result = delete_memory_fact("fact_001")
            assert result is False


class TestClearMemory:
    def test_clear_resets_to_empty(self, tmp_path: Path) -> None:
        memory_file = tmp_path / "memory.json"
        memory_data = _make_memory_with_facts()
        memory_file.write_text(json.dumps(memory_data))

        with patch("deerflow.agents.memory.updater._get_memory_file_path", return_value=memory_file):
            from deerflow.agents.memory.updater import _memory_cache

            _memory_cache.clear()

            result = clear_memory()
            assert result is True

            # Verify memory is empty
            updated = json.loads(memory_file.read_text())
            assert updated["facts"] == []
            assert updated["user"]["workContext"]["summary"] == ""
            assert updated["user"]["personalContext"]["summary"] == ""
            assert updated["user"]["topOfMind"]["summary"] == ""
            assert updated["history"]["recentMonths"]["summary"] == ""

    def test_clear_updates_last_updated(self, tmp_path: Path) -> None:
        memory_file = tmp_path / "memory.json"
        memory_data = _make_memory_with_facts()
        memory_file.write_text(json.dumps(memory_data))

        with patch("deerflow.agents.memory.updater._get_memory_file_path", return_value=memory_file):
            from deerflow.agents.memory.updater import _memory_cache

            _memory_cache.clear()

            clear_memory()

            updated = json.loads(memory_file.read_text())
            # lastUpdated should be set (not empty)
            assert updated["lastUpdated"] != ""

    def test_clear_when_already_empty(self, tmp_path: Path) -> None:
        memory_file = tmp_path / "memory.json"
        empty = _create_empty_memory()
        memory_file.write_text(json.dumps(empty))

        with patch("deerflow.agents.memory.updater._get_memory_file_path", return_value=memory_file):
            from deerflow.agents.memory.updater import _memory_cache

            _memory_cache.clear()

            result = clear_memory()
            assert result is True
