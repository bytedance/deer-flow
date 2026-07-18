"""Tests for message_processing: externalized signal patterns.

Covers:
  - load_patterns (bundled defaults, caching, custom dir override, missing file)
  - detect_correction / detect_reinforcement (backward-compatible signature,
    patterns override, last-6 window)
  - DeerMem._prepare_update (3-tuple, returns None when missing a role)
  - DeerMemConfig.patterns_dir default
"""

import re

from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.memory.backends.deermem.deer_mem import DeerMem
from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig
from deerflow.agents.memory.backends.deermem.deermem.core.message_processing import (
    detect_correction,
    detect_reinforcement,
    filter_messages_for_memory,
    load_patterns,
)


def _human(text: str) -> HumanMessage:
    return HumanMessage(content=text)


def _ai(text: str) -> AIMessage:
    return AIMessage(content=text)


# ---------------------------------------------------------------------------
# load_patterns
# ---------------------------------------------------------------------------


def test_load_patterns_bundled_nonempty():
    assert len(load_patterns("correction")) > 0
    assert len(load_patterns("reinforcement")) > 0


def test_load_patterns_cached():
    assert load_patterns("correction") is load_patterns("correction")


def test_load_patterns_custom_dir_overrides(tmp_path):
    (tmp_path / "correction.yaml").write_text("- 'foobarbaz'\n", encoding="utf-8")
    pats = load_patterns("correction", patterns_dir=str(tmp_path))
    assert len(pats) == 1
    assert pats[0].search("hello foobarbaz world")
    # bundled defaults remain intact (different cache key)
    assert len(load_patterns("correction")) > 1


def test_load_patterns_missing_file_explicit_dir_raises(tmp_path):
    import pytest

    with pytest.raises(FileNotFoundError, match="nope"):
        load_patterns("nope", patterns_dir=str(tmp_path))


# ---------------------------------------------------------------------------
# detect_correction / detect_reinforcement
# ---------------------------------------------------------------------------


def test_detect_correction_default_bundled():
    msgs = [_human("That's wrong, use uv"), _ai("ok")]
    assert detect_correction(msgs) is True
    assert detect_reinforcement(msgs) is False


def test_detect_reinforcement_default_bundled():
    msgs = [_human("perfect, exactly right"), _ai("great")]
    assert detect_reinforcement(msgs) is True


def test_detect_correction_patterns_override():
    custom = [re.compile(r"zzz")]
    assert detect_correction([_human("zzz here")], patterns=custom) is True
    assert detect_correction([_human("That's wrong")], patterns=custom) is False


def test_detect_window_is_last_six():
    # 7 human turns; a correction in the oldest (outside [-6:]) is not detected.
    msgs = [_human(f"msg {i}") for i in range(7)]
    msgs[0] = _human("That's wrong, old")
    assert detect_correction(msgs) is False
    msgs[-1] = _human("That's wrong, recent")
    assert detect_correction(msgs) is True


# ---------------------------------------------------------------------------
# DeerMem._prepare_update (3-tuple, signal detection with externalized patterns)
# ---------------------------------------------------------------------------


def _make_deermem(tmp_path) -> DeerMem:
    return DeerMem(backend_config={"storage_path": str(tmp_path)})


def test_prepare_update_missing_role_returns_none(tmp_path):
    m = _make_deermem(tmp_path)
    assert m._prepare_update([_human("only human")]) is None
    assert m._prepare_update([_ai("only ai")]) is None
    assert m._prepare_update([]) is None


def test_prepare_update_returns_3tuple_with_correction_true(tmp_path):
    m = _make_deermem(tmp_path)
    r = m._prepare_update([_human("That's wrong, use uv"), _ai("ok")])
    assert r is not None and len(r) == 3
    filtered, corr, rein = r
    assert corr is True
    assert rein is False
    assert len(filtered) == 2


# ---------------------------------------------------------------------------
# Config defaults
# ---------------------------------------------------------------------------


def test_config_patterns_dir_default():
    assert DeerMemConfig().patterns_dir is None


def test_filter_messages_backward_compat():
    filtered = filter_messages_for_memory([_human("hello"), _ai("hi there")])
    assert len(filtered) == 2
