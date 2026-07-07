"""Tests for deerflow.utils.messages text extraction.

``message_to_text`` is the shared extractor that ``RunJournal._message_text``
(BaseMessage, with ``.text`` fallback) and the gateway thread-messages helper
(dict-shaped run_events rows, no fallback) now delegate to — see the
"consolidate message->text helpers" tracking issue.
"""

from __future__ import annotations

from types import SimpleNamespace

from deerflow.utils.messages import message_content_to_text, message_to_text

# ---------- message_to_text: content shapes ----------


def test_plain_string_content():
    assert message_to_text(SimpleNamespace(content="hello")) == "hello"
    assert message_to_text({"content": "hi"}) == "hi"
    assert message_to_text(SimpleNamespace(content="")) == ""


def test_list_content_joins_without_separator():
    content = ["a", {"text": "B"}, {"content": "C"}, {"other": 1}, 42]
    expected = "aBC"  # strings + dict["text"] + nested dict["content"]; non-text dropped
    assert message_to_text(SimpleNamespace(content=content)) == expected
    assert message_to_text({"content": content}) == expected


def test_mapping_content_text_then_content_key():
    assert message_to_text(SimpleNamespace(content={"text": "T"})) == "T"
    assert message_to_text(SimpleNamespace(content={"content": "N"})) == "N"
    assert message_to_text(SimpleNamespace(content={"other": "x"})) == ""


def test_dict_message_without_content_key():
    assert message_to_text({}) == ""
    assert message_to_text({"role": "user"}) == ""


def test_non_text_content_returns_empty():
    assert message_to_text(SimpleNamespace(content=None)) == ""
    assert message_to_text(SimpleNamespace(content=123)) == ""


# ---------- text_attribute_fallback (journal behavior) ----------


def test_text_attribute_fallback_only_when_enabled():
    # Content yields nothing, but the message has a ``.text`` attribute.
    msg = SimpleNamespace(content=None, text="from-attr")
    assert message_to_text(msg, text_attribute_fallback=True) == "from-attr"
    assert message_to_text(msg) == ""  # default: no fallback


def test_empty_string_content_is_not_overridden_by_fallback():
    # Empty-string content matches the str branch and wins over the fallback.
    msg = SimpleNamespace(content="", text="from-attr")
    assert message_to_text(msg, text_attribute_fallback=True) == ""


def test_non_string_text_attribute_ignored():
    msg = SimpleNamespace(content=None, text=lambda: "callable-not-str")
    assert message_to_text(msg, text_attribute_fallback=True) == ""


# ---------- message_content_to_text unchanged (newline join, takes content) ----------


def test_message_content_to_text_still_joins_with_newline():
    assert message_content_to_text(["a", {"text": "b"}]) == "a\nb"
