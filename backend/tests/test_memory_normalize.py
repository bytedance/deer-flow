"""Tests for memory schema normalization."""

import copy

import pytest

from deerflow.agents.memory.backends.deermem.deermem.core.storage import create_empty_memory, normalize_memory_data


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


def test_normalize_memory_data_preserves_unknown_fields() -> None:
    payload = {
        "version": "1.0",
        "revision": 7,
        "lastUpdated": "2026-01-01T00:00:00Z",
        "display": {"title": "Memory export"},
        "data": {"future": True},
        "user": {
            "workContext": {
                "summary": "work",
                "updatedAt": "2026-01-01T00:00:00Z",
                "confidence": 0.8,
            },
            "providerState": {"loaded": True},
        },
        "history": {
            "timeline": {"entries": ["2026-01"]},
        },
        "facts": [
            {
                "content": "User prefers conclusions first.",
                "category": "cognitive",
                "topics": ["communication"],
            }
        ],
    }

    result = normalize_memory_data(payload)

    assert result["revision"] == 7
    assert result["display"] == {"title": "Memory export"}
    assert result["data"] == {"future": True}
    assert result["user"]["providerState"] == {"loaded": True}
    assert result["user"]["workContext"]["confidence"] == 0.8
    assert result["user"]["workContext"]["summary"] == "work"
    assert result["history"]["timeline"] == {"entries": ["2026-01"]}
    assert result["facts"][0]["topics"] == ["communication"]
    assert result["user"]["cognitiveStyle"] == {"summary": "", "updatedAt": ""}


def test_normalize_memory_data_does_not_mutate_caller() -> None:
    payload = {
        "version": "1.0",
        "lastUpdated": "",
        "user": {"workContext": {"summary": "work"}},
        "history": {},
        "facts": [{"content": "kept"}],
    }
    snapshot = copy.deepcopy(payload)

    result = normalize_memory_data(payload)

    assert result is not payload
    assert payload == snapshot


@pytest.mark.parametrize("confidence,expected", [(None, 0.5), (True, 0.5), ("invalid", 0.5), (float("nan"), 0.5), (float("inf"), 0.5), (0, 0), (-1, 0), (2, 1), ("0.8", 0.8)])
def test_normalize_legacy_fact_metadata(confidence, expected):
    fact = {"id": "legacy", "content": "  Keep conclusions first.  ", "confidence": confidence, "source": "  "}
    result = normalize_memory_data({"facts": [fact]})["facts"][0]
    assert result["confidence"] == expected
    assert result["content"] == "Keep conclusions first."
    assert result["source"] == "unknown"


def test_normalize_missing_fact_confidence_uses_neutral_default():
    result = normalize_memory_data({"facts": [{"content": "Legacy preference"}]})
    assert result["facts"][0]["confidence"] == 0.5
