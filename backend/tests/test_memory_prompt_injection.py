"""Tests for memory prompt injection formatting."""

import math

from deerflow.agents.memory.prompt import _coerce_confidence, format_memory_for_injection


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
    # Make token counting deterministic for this test by counting characters.
    monkeypatch.setattr("deerflow.agents.memory.prompt._count_tokens", lambda text, encoding_name="cl100k_base", *, use_tiktoken=True: len(text))

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
    # Choose a budget that can include exactly one fact section line.
    max_tokens = (len(one_fact_result) + len(two_facts_result)) // 2

    first_only_result = format_memory_for_injection(memory_data, max_tokens=max_tokens)

    assert "First fact should fit" in first_only_result
    assert "Second fact should not fit in tiny budget" not in first_only_result


def test_coerce_confidence_nan_falls_back_to_default() -> None:
    """NaN should not be treated as a valid confidence value."""
    result = _coerce_confidence(math.nan, default=0.5)
    assert result == 0.5


def test_coerce_confidence_inf_falls_back_to_default() -> None:
    """Infinite values should fall back to default rather than clamping to 1.0."""
    assert _coerce_confidence(math.inf, default=0.3) == 0.3
    assert _coerce_confidence(-math.inf, default=0.3) == 0.3


def test_coerce_confidence_valid_values_are_clamped() -> None:
    """Valid floats outside [0, 1] are clamped; values inside are preserved."""
    assert _coerce_confidence(1.5) == 1.0
    assert _coerce_confidence(-0.5) == 0.0
    assert abs(_coerce_confidence(0.75) - 0.75) < 1e-9


def test_format_memory_skips_none_content_facts() -> None:
    """Facts with content=None must not produce a 'None' line in the output."""
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
    """Facts with non-string content (e.g. int/list) must be ignored."""
    memory_data = {
        "facts": [
            {"content": 42, "category": "knowledge", "confidence": 0.9},
            {"content": ["list"], "category": "knowledge", "confidence": 0.85},
            {"content": "Valid fact", "category": "knowledge", "confidence": 0.7},
        ],
    }

    result = format_memory_for_injection(memory_data, max_tokens=2000)

    # The formatted line for an integer content would be "- [knowledge | 0.90] 42".
    assert "| 0.90] 42" not in result
    # The formatted line for a list content would be "- [knowledge | 0.85] ['list']".
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
    """longTermBackground in history must be injected into the prompt."""
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


# ---------------------------------------------------------------------------
# Guaranteed-category injection tests
# ---------------------------------------------------------------------------


def test_guaranteed_correction_injected_when_budget_tight(monkeypatch) -> None:
    """Correction facts must be injected even when the regular budget is exhausted."""
    # Deterministic char-based counting.
    monkeypatch.setattr(
        "deerflow.agents.memory.prompt._count_tokens",
        lambda text, encoding_name="cl100k_base", *, use_tiktoken=True: len(text),
    )

    memory_data = {
        "user": {},
        "history": {},
        "facts": [
            # Many high-confidence regular facts that will eat the budget.
            {"content": "Regular fact A " * 20, "category": "knowledge", "confidence": 0.95},
            {"content": "Regular fact B " * 20, "category": "knowledge", "confidence": 0.90},
            {"content": "Regular fact C " * 20, "category": "knowledge", "confidence": 0.85},
            # A correction fact with lower confidence.
            {"content": "Use make dev, not npm start", "category": "correction", "confidence": 0.7},
        ],
    }

    # Tight budget that cannot fit all facts.
    result = format_memory_for_injection(
        memory_data,
        max_tokens=200,
        guaranteed_categories=["correction"],
        guaranteed_token_budget=100,
    )

    # The correction fact MUST appear regardless of budget pressure.
    assert "Use make dev, not npm start" in result


def test_guaranteed_facts_sorted_by_confidence() -> None:
    """Guaranteed facts should be sorted by confidence descending."""
    memory_data = {
        "user": {},
        "history": {},
        "facts": [
            {"content": "Low conf correction", "category": "correction", "confidence": 0.6},
            {"content": "High conf correction", "category": "correction", "confidence": 0.95},
            {"content": "Regular fact", "category": "knowledge", "confidence": 0.8},
        ],
    }

    result = format_memory_for_injection(
        memory_data,
        max_tokens=2000,
        guaranteed_categories=["correction"],
        guaranteed_token_budget=500,
    )

    assert "High conf correction" in result
    assert "Low conf correction" in result
    assert result.index("High conf correction") < result.index("Low conf correction")


def test_guaranteed_budget_isolation() -> None:
    """Guaranteed facts draw from their own budget, not the regular budget."""
    memory_data = {
        "user": {},
        "history": {},
        "facts": [
            {"content": "Correction one", "category": "correction", "confidence": 0.9},
            {"content": "Regular knowledge", "category": "knowledge", "confidence": 0.8},
        ],
    }

    result = format_memory_for_injection(
        memory_data,
        max_tokens=2000,
        guaranteed_categories=["correction"],
        guaranteed_token_budget=500,
    )

    # Both facts should appear (separate budgets).
    assert "Correction one" in result
    assert "Regular knowledge" in result


def test_no_guaranteed_categories_backward_compatible() -> None:
    """When guaranteed_categories is None, behaviour matches the original."""
    memory_data = {
        "user": {},
        "history": {},
        "facts": [
            {"content": "High conf", "category": "knowledge", "confidence": 0.95},
            {"content": "Low conf", "category": "context", "confidence": 0.4},
        ],
    }

    # No guaranteed_categories passed → original behaviour.
    result = format_memory_for_injection(memory_data, max_tokens=2000)

    assert "High conf" in result
    assert result.index("High conf") < result.index("Low conf")


def test_empty_guaranteed_list_backward_compatible() -> None:
    """An empty guaranteed_categories list should behave like None."""
    memory_data = {
        "user": {},
        "history": {},
        "facts": [
            {"content": "Correction fact", "category": "correction", "confidence": 0.9},
            {"content": "Regular fact", "category": "knowledge", "confidence": 0.8},
        ],
    }

    result = format_memory_for_injection(
        memory_data,
        max_tokens=2000,
        guaranteed_categories=[],
    )

    assert "Correction fact" in result
    assert "Regular fact" in result


def test_fallback_on_ranking_error(monkeypatch) -> None:
    """If the guaranteed path raises, fall back to confidence-only ranking."""

    memory_data = {
        "user": {},
        "history": {},
        "facts": [
            {"content": "Fact A", "category": "knowledge", "confidence": 0.9},
            {"content": "Fact B", "category": "correction", "confidence": 0.8},
        ],
    }

    # Force _select_fact_lines to raise on the *first* call (the guaranteed
    # path) but succeed on subsequent calls (the fallback path).
    call_count = {"n": 0}
    prompt_module = __import__("deerflow.agents.memory.prompt", fromlist=["_select_fact_lines"])
    original_select = prompt_module._select_fact_lines

    def flaky_select(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("simulated error in guaranteed path")
        return original_select(*args, **kwargs)

    monkeypatch.setattr(
        "deerflow.agents.memory.prompt._select_fact_lines",
        flaky_select,
    )

    result = format_memory_for_injection(
        memory_data,
        max_tokens=2000,
        guaranteed_categories=["correction"],
        guaranteed_token_budget=500,
    )

    # Both facts should still appear via the fallback path.
    assert "Fact A" in result
    assert "Fact B" in result


def test_guaranteed_respects_its_own_budget_limit(monkeypatch) -> None:
    """Even guaranteed facts are capped by guaranteed_token_budget."""
    monkeypatch.setattr(
        "deerflow.agents.memory.prompt._count_tokens",
        lambda text, encoding_name="cl100k_base", *, use_tiktoken=True: len(text),
    )

    # Many correction facts that together exceed the guaranteed budget.
    # Formatted line example: "- [correction | 0.95] CorrA xxxxxxxxxxxxxxxx"
    # Each line is ~50 chars; with "Facts:\n" header (7 chars), two lines
    # need ~107 chars, exceeding the 80-char guaranteed budget.
    memory_data = {
        "user": {},
        "history": {},
        "facts": [
            {"content": "CorrA " + "x" * 20, "category": "correction", "confidence": 0.95},
            {"content": "CorrB " + "x" * 20, "category": "correction", "confidence": 0.90},
            {"content": "CorrC " + "x" * 20, "category": "correction", "confidence": 0.85},
            {"content": "Short regular", "category": "knowledge", "confidence": 0.8},
        ],
    }

    result = format_memory_for_injection(
        memory_data,
        max_tokens=2000,
        guaranteed_categories=["correction"],
        guaranteed_token_budget=80,  # Small guaranteed budget — fits 1 fact line only.
    )

    # At least the highest-confidence correction should appear.
    assert "CorrA" in result
    # The regular fact should also appear (it has its own budget).
    assert "Short regular" in result


def test_guaranteed_fact_with_source_error_rendered() -> None:
    """Guaranteed correction facts should still render sourceError."""
    memory_data = {
        "facts": [
            {
                "content": "Use uv, not pip.",
                "category": "correction",
                "confidence": 0.95,
                "sourceError": "Agent suggested pip install.",
            },
            {"content": "Likes Python", "category": "preference", "confidence": 0.8},
        ],
    }

    result = format_memory_for_injection(
        memory_data,
        max_tokens=2000,
        guaranteed_categories=["correction"],
        guaranteed_token_budget=500,
    )

    assert "Use uv, not pip." in result
    assert "avoid: Agent suggested pip install." in result
    assert "Likes Python" in result


def test_single_facts_header_when_both_guaranteed_and_regular() -> None:
    """When both guaranteed and regular facts exist, emit exactly one 'Facts:' header."""
    memory_data = {
        "user": {"workContext": {"summary": "Dev"}},  # non-empty preceding section
        "history": {},
        "facts": [
            {"content": "Correction fact", "category": "correction", "confidence": 0.95},
            {"content": "Knowledge fact", "category": "knowledge", "confidence": 0.80},
        ],
    }

    result = format_memory_for_injection(
        memory_data,
        max_tokens=2000,
        guaranteed_categories=["correction"],
        guaranteed_token_budget=500,
    )

    # Exactly one "Facts:" header.
    assert result.count("Facts:") == 1, f"Expected exactly one 'Facts:' header, got:\n{result}"
    # Both facts appear under the single header.
    assert "Correction fact" in result
    assert "Knowledge fact" in result
    # Guaranteed fact comes first (higher confidence + guaranteed).
    assert result.index("Correction fact") < result.index("Knowledge fact")


def test_strict_confidence_order_when_high_confidence_fact_overflows(monkeypatch) -> None:
    """Within a single budget, a higher-confidence fact that exceeds the
    remaining budget must NOT be skipped in favour of a shorter, lower-
    confidence fact ranked after it.

    This locks in the strict confidence-ordered selection semantics.
    """
    monkeypatch.setattr(
        "deerflow.agents.memory.prompt._count_tokens",
        lambda text, encoding_name="cl100k_base", *, use_tiktoken=True: len(text),
    )

    memory_data = {
        "user": {},
        "history": {},
        "facts": [
            # Higher-confidence but long enough to exceed the remaining budget.
            {"content": "Long high-confidence fact " + "x" * 50, "category": "knowledge", "confidence": 0.95},
            # Lower-confidence but short — would fit if we kept scanning past
            # the over-budget high-confidence fact above.
            {"content": "Short low", "category": "knowledge", "confidence": 0.50},
        ],
    }

    # Budget large enough only for ~one short fact, not the long one.
    result = format_memory_for_injection(memory_data, max_tokens=70, guaranteed_categories=None)

    # The high-confidence fact does not fit, and the low-confidence fact
    # MUST NOT slip in ahead of it.
    assert "Short low" not in result, "Lower-confidence fact should not be selected when a higher-confidence fact ranked before it was skipped (strict ordering)."
