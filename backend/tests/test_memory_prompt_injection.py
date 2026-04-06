"""Tests for memory prompt injection formatting."""

import math

from deerflow.agents.memory.prompt import _coerce_confidence, build_memory_injection_result, format_memory_for_injection
from deerflow.config.memory_config import MemoryConfig, RetrievalTraceConfig


def test_format_memory_includes_facts_section() -> None:
    memory_data = {
        "user": {},
        "history": {},
        "facts": [
            {"content": "User uses PostgreSQL", "category": "knowledge", "confidence": 0.9},
            {"content": "User prefers SQLAlchemy", "category": "preference", "confidence": 0.8},
        ],
    }

    result = format_memory_for_injection(memory_data, max_tokens=2000)

    assert "Facts:" in result
    assert "User uses PostgreSQL" in result
    assert "User prefers SQLAlchemy" in result


def test_format_memory_sorts_facts_by_confidence_desc() -> None:
    memory_data = {
        "user": {},
        "history": {},
        "facts": [
            {"content": "Low confidence fact", "category": "context", "confidence": 0.4},
            {"content": "High confidence fact", "category": "knowledge", "confidence": 0.95},
        ],
    }

    result = format_memory_for_injection(memory_data, max_tokens=2000)

    assert result.index("High confidence fact") < result.index("Low confidence fact")


def test_format_memory_respects_budget_when_adding_facts(monkeypatch) -> None:
    monkeypatch.setattr("deerflow.agents.memory.prompt._count_tokens", lambda text, encoding_name="cl100k_base": len(text))

    memory_data = {
        "user": {},
        "history": {},
        "facts": [
            {"content": "First fact should fit", "category": "knowledge", "confidence": 0.95},
            {"content": "Second fact should not fit in tiny budget", "category": "knowledge", "confidence": 0.90},
        ],
    }

    first_fact_only_memory_data = {
        "user": {},
        "history": {},
        "facts": [
            {"content": "First fact should fit", "category": "knowledge", "confidence": 0.95},
        ],
    }
    one_fact_result = format_memory_for_injection(first_fact_only_memory_data, max_tokens=2000)
    two_facts_result = format_memory_for_injection(memory_data, max_tokens=2000)
    max_tokens = (len(one_fact_result) + len(two_facts_result)) // 2

    first_only_result = format_memory_for_injection(memory_data, max_tokens=max_tokens)

    assert "First fact should fit" in first_only_result
    assert "Second fact should not fit in tiny budget" not in first_only_result


def test_coerce_confidence_nan_falls_back_to_default() -> None:
    result = _coerce_confidence(math.nan, default=0.5)
    assert result == 0.5


def test_coerce_confidence_inf_falls_back_to_default() -> None:
    assert _coerce_confidence(math.inf, default=0.3) == 0.3
    assert _coerce_confidence(-math.inf, default=0.3) == 0.3


def test_coerce_confidence_valid_values_are_clamped() -> None:
    assert _coerce_confidence(1.5) == 1.0
    assert _coerce_confidence(-0.5) == 0.0
    assert abs(_coerce_confidence(0.75) - 0.75) < 1e-9


def test_format_memory_skips_none_content_facts() -> None:
    memory_data = {
        "facts": [
            {"content": None, "category": "knowledge", "confidence": 0.9},
            {"content": "Real fact", "category": "knowledge", "confidence": 0.8},
        ],
    }

    result = format_memory_for_injection(memory_data, max_tokens=2000)

    assert "None" not in result
    assert "Real fact" in result


def test_format_memory_skips_non_string_content_facts() -> None:
    memory_data = {
        "facts": [
            {"content": 42, "category": "knowledge", "confidence": 0.9},
            {"content": ["list"], "category": "knowledge", "confidence": 0.85},
            {"content": "Valid fact", "category": "knowledge", "confidence": 0.7},
        ],
    }

    result = format_memory_for_injection(memory_data, max_tokens=2000)

    assert "| 0.90] 42" not in result
    assert "| 0.85]" not in result
    assert "Valid fact" in result


def test_format_memory_renders_correction_source_error() -> None:
    memory_data = {
        "facts": [
            {
                "content": "Use make dev for local development.",
                "category": "correction",
                "confidence": 0.95,
                "sourceError": "The agent previously suggested npm start.",
            }
        ]
    }

    result = format_memory_for_injection(memory_data, max_tokens=2000)

    assert "Use make dev for local development." in result
    assert "avoid: The agent previously suggested npm start." in result


def test_format_memory_renders_correction_without_source_error_normally() -> None:
    memory_data = {
        "facts": [
            {
                "content": "Use make dev for local development.",
                "category": "correction",
                "confidence": 0.95,
            }
        ]
    }

    result = format_memory_for_injection(memory_data, max_tokens=2000)

    assert "Use make dev for local development." in result
    assert "avoid:" not in result


def test_format_memory_includes_long_term_background() -> None:
    memory_data = {
        "user": {},
        "history": {
            "recentMonths": {"summary": "Recent activity summary"},
            "earlierContext": {"summary": "Earlier context summary"},
            "longTermBackground": {"summary": "Core expertise in distributed systems"},
        },
        "facts": [],
    }

    result = format_memory_for_injection(memory_data, max_tokens=2000)

    assert "Background: Core expertise in distributed systems" in result
    assert "Recent: Recent activity summary" in result
    assert "Earlier: Earlier context summary" in result


def test_build_memory_injection_result_returns_trace_when_enabled(monkeypatch) -> None:
    monkeypatch.setattr(
        "deerflow.agents.memory.prompt.get_memory_config",
        lambda: MemoryConfig(retrieval_trace=RetrievalTraceConfig(enabled=True)),
    )
    monkeypatch.setattr("deerflow.agents.memory.prompt._count_tokens", lambda text, encoding_name="cl100k_base": len(text))

    memory_data = {
        "user": {"workContext": {"summary": "Maintains DeerFlow memory stack"}},
        "facts": [
            {"id": "fact_a", "content": "High confidence fact", "category": "knowledge", "confidence": 0.95},
            {"id": "fact_b", "content": "Second fact is too long for the tiny budget", "category": "context", "confidence": 0.9},
            {"id": "fact_c", "content": "", "category": "context", "confidence": 0.1},
        ],
    }

    result = build_memory_injection_result(memory_data, max_tokens=110)

    assert result.trace is not None
    assert result.trace.user_context_included is True
    assert result.trace.total_candidates == 3
    assert result.trace.selected_count == 1
    assert result.trace.dropped_count == 2
    assert any(selection.fact_id == "fact_b" and selection.reason.value == "budget_exceeded" for selection in result.trace.selections)
    assert any(selection.fact_id == "fact_c" and selection.reason.value == "empty_content" for selection in result.trace.selections)
    assert result.trace.tokens_used <= 110
