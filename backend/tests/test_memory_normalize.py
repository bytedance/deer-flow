"""Tests for memory schema normalization."""

from deerflow.agents.memory.storage import create_empty_memory, normalize_memory_data


def test_normalize_memory_data_adds_cognitive_style() -> None:
    legacy = {
        "version": "1.0",
        "lastUpdated": "",
        "user": {
            "workContext": {"summary": "work", "updatedAt": "2026-01-01T00:00:00Z"},
            "personalContext": {"summary": "", "updatedAt": ""},
            "topOfMind": {"summary": "", "updatedAt": ""},
        },
        "history": {
            "recentMonths": {"summary": "", "updatedAt": ""},
            "earlierContext": {"summary": "", "updatedAt": ""},
            "longTermBackground": {"summary": "", "updatedAt": ""},
        },
        "facts": [],
    }

    result = normalize_memory_data(legacy)

    assert "cognitiveStyle" in result["user"]
    assert result["user"]["cognitiveStyle"]["summary"] == ""
    assert result["user"]["cognitiveStyle"]["updatedAt"] == ""


def test_create_empty_memory_includes_cognitive_style() -> None:
    empty = create_empty_memory()
    assert empty["user"]["cognitiveStyle"] == {"summary": "", "updatedAt": ""}
