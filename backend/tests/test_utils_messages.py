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


# ---------- restore_original_user_content_blocks (#3689 review feedback) ----------


def _image(url: str = "data:image/png;base64,ABC") -> dict:
    return {"type": "image_url", "image_url": {"url": url}}


def test_restore_string_content_returns_single_text_block():
    from deerflow.utils.messages import restore_original_user_content_blocks

    assert restore_original_user_content_blocks("anything", "look") == [
        {"type": "text", "text": "look"},
    ]


def test_restore_non_list_non_string_returns_single_text_block():
    """Non-list content (e.g. legacy Mapping shape) collapses to a text block."""
    from deerflow.utils.messages import restore_original_user_content_blocks

    assert restore_original_user_content_blocks(None, "look") == [
        {"type": "text", "text": "look"},
    ]
    assert restore_original_user_content_blocks({"text": "wrapped"}, "look") == [
        {"type": "text", "text": "look"},
    ]


def test_restore_list_replaces_first_text_block_with_original_text():
    from deerflow.utils.messages import restore_original_user_content_blocks

    content = [
        {"type": "text", "text": "--- BEGIN USER INPUT ---\nlook\n--- END USER INPUT ---"},
        _image(),
    ]
    assert restore_original_user_content_blocks(content, "look") == [
        {"type": "text", "text": "look"},
        _image(),
    ]


def test_restore_list_drops_subsequent_text_blocks_already_merged_into_first():
    """The middleware merges all text blocks into one; the read path must not
    re-emit the merged-away text blocks (would duplicate displayed text)."""
    from deerflow.utils.messages import restore_original_user_content_blocks

    content = [
        {"type": "text", "text": "wrapped-1"},
        _image(),
        {"type": "text", "text": "wrapped-2"},
    ]
    out = restore_original_user_content_blocks(content, "merged text")
    assert out == [
        {"type": "text", "text": "merged text"},
        _image(),
    ]


def test_restore_list_preserves_non_text_blocks_between_text_blocks():
    from deerflow.utils.messages import restore_original_user_content_blocks

    file_block = {"type": "file", "file_id": "f1"}
    content = [
        {"type": "text", "text": "wrapped"},
        file_block,
        _image("data:image/png;base64,XYZ"),
    ]
    out = restore_original_user_content_blocks(content, "look")
    assert out == [
        {"type": "text", "text": "look"},
        file_block,
        _image("data:image/png;base64,XYZ"),
    ]


def test_restore_list_with_no_text_block_prepends_original_text():
    """Edge case: persisted content has only non-text blocks (rare, but
    defensive). Original text should still surface."""
    from deerflow.utils.messages import restore_original_user_content_blocks

    content = [_image()]
    out = restore_original_user_content_blocks(content, "look")
    assert out == [
        {"type": "text", "text": "look"},
        _image(),
    ]


def test_restore_empty_list_prepends_original_text():
    from deerflow.utils.messages import restore_original_user_content_blocks

    assert restore_original_user_content_blocks([], "look") == [
        {"type": "text", "text": "look"},
    ]


def test_restore_list_does_not_mutate_input_blocks():
    """Helper must not mutate the caller's block dicts — display path should
    be a fresh list with a new first text block."""
    from deerflow.utils.messages import restore_original_user_content_blocks

    original_text_block = {"type": "text", "text": "wrapped"}
    content = [original_text_block, _image()]
    out = restore_original_user_content_blocks(content, "look")
    # Caller's text block unchanged
    assert original_text_block == {"type": "text", "text": "wrapped"}
    # Output is a fresh shape
    assert out[0] == {"type": "text", "text": "look"}
    assert out[0] is not original_text_block
