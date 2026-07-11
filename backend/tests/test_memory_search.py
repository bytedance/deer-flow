"""Tests for search_memory_facts function."""

import json

from deerflow.agents.memory.storage import FileMemoryStorage, create_empty_memory
from deerflow.agents.memory.updater import search_memory_facts


def _make_fact(content: str, category: str = "context", confidence: float = 0.7) -> dict:
    return {
        "id": f"fact_test_{hash(content) & 0xFFFFFFFF:08x}",
        "content": content,
        "category": category,
        "confidence": confidence,
        "createdAt": "2026-07-09T00:00:00Z",
        "source": "test",
    }


class TestSearchMemoryFacts:
    """Tests for search_memory_facts function."""

    def test_basic_substring_match(self, tmp_path, monkeypatch):
        """Should find facts containing the query string (case-insensitive)."""
        facts = [
            _make_fact("User prefers Python", "preference", 0.9),
            _make_fact("User works with TypeScript", "context", 0.7),
            _make_fact("User lives in Beijing", "personal", 0.8),
        ]
        _setup_memory(tmp_path, monkeypatch, facts)

        results = search_memory_facts("python")
        assert len(results) == 1
        assert results[0]["content"] == "User prefers Python"

    def test_case_insensitive(self, tmp_path, monkeypatch):
        """Should match regardless of case."""
        facts = [_make_fact("User prefers Python", "preference", 0.9)]
        _setup_memory(tmp_path, monkeypatch, facts)

        assert len(search_memory_facts("PYTHON")) == 1
        assert len(search_memory_facts("python")) == 1
        assert len(search_memory_facts("Python")) == 1

    def test_category_filter(self, tmp_path, monkeypatch):
        """Should only return facts matching the given category."""
        facts = [
            _make_fact("Likes dark mode", "preference", 0.8),
            _make_fact("Works remotely", "context", 0.7),
            _make_fact("Prefers short answers", "preference", 0.6),
        ]
        _setup_memory(tmp_path, monkeypatch, facts)

        results = search_memory_facts("prefer", category="preference")
        assert len(results) == 1
        assert results[0]["content"] == "Prefers short answers"

    def test_category_filter_no_match(self, tmp_path, monkeypatch):
        """Should return empty list when category doesn't match."""
        facts = [_make_fact("Likes dark mode", "preference", 0.8)]
        _setup_memory(tmp_path, monkeypatch, facts)

        results = search_memory_facts("dark", category="context")
        assert results == []

    def test_empty_query_returns_empty(self, tmp_path, monkeypatch):
        """Should return empty list for empty query, not error."""
        facts = [_make_fact("Some fact")]
        _setup_memory(tmp_path, monkeypatch, facts)

        results = search_memory_facts("")
        assert results == []

    def test_no_match_returns_empty(self, tmp_path, monkeypatch):
        """Should return empty list when nothing matches."""
        facts = [_make_fact("User prefers Python")]
        _setup_memory(tmp_path, monkeypatch, facts)

        results = search_memory_facts("Rust")
        assert results == []

    def test_sorted_by_confidence_desc(self, tmp_path, monkeypatch):
        """Should return results sorted by confidence descending."""
        facts = [
            _make_fact("Fact A", confidence=0.3),
            _make_fact("Fact B", confidence=0.9),
            _make_fact("Fact C", confidence=0.6),
        ]
        _setup_memory(tmp_path, monkeypatch, facts)

        results = search_memory_facts("Fact")
        assert len(results) == 3
        assert results[0]["confidence"] == 0.9
        assert results[1]["confidence"] == 0.6
        assert results[2]["confidence"] == 0.3

    def test_null_confidence_does_not_crash_sort(self, tmp_path, monkeypatch):
        """A fact stored with ``"confidence": null`` (corrupted/hand-edited memory)
        must not break the confidence sort. ``.get("confidence", 0)`` returns the
        stored ``None`` and comparing None with floats raises TypeError; the coerce
        helper defaults null to a finite midpoint instead."""
        null_fact = {
            "id": "fact_null",
            "content": "Fact with null confidence",
            "category": "context",
            "confidence": None,
            "createdAt": "2026-07-09T00:00:00Z",
            "source": "test",
        }
        facts = [
            _make_fact("Fact high", confidence=0.9),
            null_fact,
            _make_fact("Fact low", confidence=0.2),
        ]
        _setup_memory(tmp_path, monkeypatch, facts)

        # Must not raise TypeError during the confidence sort.
        results = search_memory_facts("Fact")

        assert len(results) == 3
        # Highest real confidence still sorts first; null (coerced to 0.5) sits
        # between the 0.9 and 0.2 facts.
        assert results[0]["content"] == "Fact high"
        assert {r["content"] for r in results} == {"Fact high", "Fact with null confidence", "Fact low"}

    def test_respects_limit(self, tmp_path, monkeypatch):
        """Should return at most `limit` results."""
        facts = [_make_fact(f"Fact {i}", confidence=0.5) for i in range(20)]
        _setup_memory(tmp_path, monkeypatch, facts)

        results = search_memory_facts("Fact", limit=5)
        assert len(results) == 5

    def test_negative_limit_returns_empty(self, tmp_path, monkeypatch):
        """Should not let negative limits expand the result set via slicing."""
        facts = [_make_fact(f"Fact {i}", confidence=0.5) for i in range(3)]
        _setup_memory(tmp_path, monkeypatch, facts)

        results = search_memory_facts("Fact", limit=-1)
        assert results == []

    def test_no_facts_returns_empty(self, tmp_path, monkeypatch):
        """Should return empty list when memory has no facts."""
        _setup_memory(tmp_path, monkeypatch, [])

        results = search_memory_facts("anything")
        assert results == []


def _setup_memory(tmp_path, monkeypatch, facts: list[dict]):
    """Set up a FileMemoryStorage with given facts at a temp path."""
    memory_file = tmp_path / "memory.json"
    memory_data = create_empty_memory()
    memory_data["facts"] = facts

    memory_file.write_text(json.dumps(memory_data))

    storage = FileMemoryStorage()
    # Force the storage to use our temp file
    monkeypatch.setattr(
        "deerflow.agents.memory.updater.get_memory_storage",
        lambda: storage,
    )
    monkeypatch.setattr(
        "deerflow.agents.memory.updater.get_memory_data",
        lambda agent_name=None, user_id=None: json.loads(memory_file.read_text()),
    )
