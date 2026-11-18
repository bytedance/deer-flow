"""Tests for message-processing signal detection and DeerMem preparation.

Pins that ``detect_signals`` recognizes all six signal classes (correction,
reinforcement, preference, identity, goal, decision), and ``_prepare_update``
returns the full signal set as a ``frozenset`` so each detected class reaches
the extraction prompt.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.memory.backends.deermem.deer_mem import DeerMem
from deerflow.agents.memory.backends.deermem.deermem.core.message_processing import (
    detect_signals,
    extract_message_text,
    load_patterns,
)


def _human(text: str) -> HumanMessage:
    return HumanMessage(content=text)


def _ai(text: str) -> AIMessage:
    return AIMessage(content=text)


# ── detect_signals: the 6 signal classes ───────────────────────────────────


def test_detect_signals_correction() -> None:
    assert "correction" in detect_signals([_human("That's wrong, use uv"), _ai("ok")])


def test_detect_signals_reinforcement() -> None:
    assert "reinforcement" in detect_signals([_human("perfect, exactly right"), _ai("ok")])


def test_detect_signals_preference() -> None:
    assert "preference" in detect_signals([_human("I prefer uv over pip"), _ai("ok")])


def test_detect_signals_identity() -> None:
    assert "identity" in detect_signals([_human("I am an engineer"), _ai("ok")])


def test_detect_signals_goal() -> None:
    assert "goal" in detect_signals([_human("I plan to migrate to uv"), _ai("ok")])


def test_detect_signals_decision() -> None:
    assert "decision" in detect_signals([_human("let's go with uv"), _ai("ok")])


def test_detect_signals_none_for_substantive_turn() -> None:
    assert detect_signals([_human("what is the weather"), _ai("sunny")]) == set()


def test_detect_signals_multiple_classes_in_one_turn() -> None:
    # A turn that states both a preference and an identity surfaces both.
    signals = detect_signals([_human("I am an engineer and I prefer uv"), _ai("ok")])
    assert "identity" in signals
    assert "preference" in signals


# ── _prepare_update: seam-stable 3-tuple projection ────────────────────────


def _make_deermem(tmp_path, **overrides) -> DeerMem:
    cfg = {"storage_path": str(tmp_path)}
    cfg.update(overrides)
    return DeerMem(backend_config=cfg)


def test_prepare_update_keeps_short_turns(tmp_path) -> None:
    m = _make_deermem(tmp_path)
    messages = [_human("好的"), _ai("嗯")]
    prepared = m._prepare_update(messages)
    assert prepared is not None and prepared[0] == messages


def test_custom_patterns_dir_still_loads_signal_patterns(tmp_path) -> None:
    pattern_file = tmp_path / "preference.yaml"
    pattern_file.write_text("- 'I always prefer kiwi'\n", encoding="utf-8")

    patterns = load_patterns("preference", patterns_dir=str(tmp_path))

    assert len(patterns) == 1
    assert patterns[0].search("I always prefer kiwi")


def test_prepare_update_returns_correction_signal(tmp_path) -> None:
    m = _make_deermem(tmp_path)
    r = m._prepare_update([_human("That's wrong, use uv"), _ai("ok")])
    assert r is not None and len(r) == 2
    _filtered, signals = r
    assert "correction" in signals


def test_prepare_update_returns_reinforcement_signal(tmp_path) -> None:
    m = _make_deermem(tmp_path)
    r = m._prepare_update([_human("perfect, exactly right"), _ai("ok")])
    assert r is not None and len(r) == 2
    _filtered, signals = r
    assert "reinforcement" in signals


def test_prepare_update_returns_new_signals_after_swap(tmp_path) -> None:
    # After the signals-seam swap, the full signal set flows through (not just
    # correction/reinforcement): a preference turn surfaces "preference".
    m = _make_deermem(tmp_path)
    r = m._prepare_update([_human("I prefer uv over pip"), _ai("ok")])
    assert r is not None and len(r) == 2
    _filtered, signals = r
    assert "preference" in signals
    assert len(_filtered) == 2  # not trivial -> kept


# ── extract_message_text: content shapes ───────────────────────────────────


def test_extract_message_text_treats_none_as_empty() -> None:
    """A content-less message must not become the literal string ``"None"``.

    ``str(None)`` is truthy, so the naive fallback would hand ``"None"`` to
    signal detection and to the memory-update prompt as if it were real user
    text. Mirrors ``utils/messages.py:message_content_to_text`` and
    ``test_mem0_memory_backend.py::test_extract_message_text_treats_none_as_empty``.
    """
    msg = _human("")
    msg.content = None
    assert extract_message_text(msg) == ""
