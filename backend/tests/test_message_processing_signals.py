"""Tests for message-processing signal detection and trivial filtering.

Pins three behaviors: ``detect_signals`` recognizes all six signal classes
(correction, reinforcement, preference, identity, goal, decision);
``filter_trivial`` drops pure-ack turns and their replies while keeping
substantive turns; and ``_prepare_update`` returns the full signal set as a
``frozenset`` (not just correction/reinforcement), so every detected class
flows through to the extraction prompt.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.memory.backends.deermem.deer_mem import DeerMem
from deerflow.agents.memory.backends.deermem.deermem.core.message_processing import (
    detect_signals,
    extract_message_text,
    filter_trivial,
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


# ── filter_trivial ─────────────────────────────────────────────────────────


def test_filter_trivial_drops_pure_ack_and_its_reply() -> None:
    msgs = [_human("嗯"), _ai("thanks"), _human("what next"), _ai("let's see")]
    result = filter_trivial(msgs)
    # "嗯" + its AI "thanks" dropped; the substantive pair is kept.
    assert len(result) == 2
    assert extract_message_text(result[0]) == "what next"


def test_filter_trivial_keeps_substantive_message_containing_ok() -> None:
    msgs = [_human("use uv to install, ok?"), _ai("done")]
    result = filter_trivial(msgs)
    assert len(result) == 2  # not dropped: not a whole-message ack


def test_filter_trivial_all_trivial_returns_empty() -> None:
    msgs = [_human("好的"), _ai("嗯")]
    assert filter_trivial(msgs) == []


def test_filter_trivial_tolerates_trailing_punctuation() -> None:
    msgs = [_human("ok."), _ai("ok!")]
    assert filter_trivial(msgs) == []


def test_filter_trivial_no_patterns_keeps_all() -> None:
    msgs = [_human("ok"), _ai("ok")]
    assert filter_trivial(msgs, patterns=[]) == msgs


# ── _prepare_update: seam-stable 3-tuple projection ────────────────────────


def _make_deermem(tmp_path, **overrides) -> DeerMem:
    cfg = {"storage_path": str(tmp_path)}
    cfg.update(overrides)
    return DeerMem(backend_config=cfg)


def test_prepare_update_all_trivial_returns_none(tmp_path) -> None:
    m = _make_deermem(tmp_path)
    assert m._prepare_update([_human("好的"), _ai("嗯")]) is None


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
