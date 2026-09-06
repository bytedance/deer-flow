"""Tests for deerflow.utils.messages text extraction.

``message_to_text`` is the shared extractor that ``RunJournal._message_text``
(BaseMessage, with ``.text`` fallback) and the gateway thread-messages helper
(dict-shaped run_events rows, no fallback) now delegate to — see the
"consolidate message->text helpers" tracking issue.
"""

from __future__ import annotations

from types import SimpleNamespace

from langchain_core.messages import HumanMessage

from deerflow.utils.messages import ORIGINAL_USER_CONTENT_KEY, message_content_to_text, message_to_text, restore_original_human_message

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


# ---------- restore_original_human_message ----------


def test_restore_original_human_message_restores_string_without_mutating_model_copy():
    wrapped = HumanMessage(
        content="--- BEGIN USER INPUT ---\nhello\n--- END USER INPUT ---",
        id="human-1",
        name="request",
        additional_kwargs={ORIGINAL_USER_CONTENT_KEY: "hello", "hide_from_ui": False},
        response_metadata={"source": "gateway"},
    )

    restored = restore_original_human_message(wrapped)

    assert restored is not wrapped
    assert restored.content == "hello"
    assert restored.id == "human-1"
    assert restored.name == "request"
    assert restored.additional_kwargs == {"hide_from_ui": False}
    assert restored.response_metadata == {"source": "gateway"}
    assert wrapped.content.startswith("--- BEGIN USER INPUT ---")
    assert wrapped.additional_kwargs[ORIGINAL_USER_CONTENT_KEY] == "hello"


def test_restore_original_human_message_preserves_mixed_non_text_blocks_in_order():
    image = {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}}
    file_block = {"type": "file", "file_id": "file-1"}
    wrapped = HumanMessage(
        content=[
            image,
            {"type": "text", "text": "--- BEGIN USER INPUT ---\ncompare\n--- END USER INPUT ---"},
            file_block,
        ],
        additional_kwargs={ORIGINAL_USER_CONTENT_KEY: "compare", "metadata": {"source": "user"}},
    )

    restored = restore_original_human_message(wrapped)

    assert restored.content == [image, {"type": "text", "text": "compare"}, file_block]
    assert restored.additional_kwargs == {"metadata": {"source": "user"}}
    assert wrapped.content[1]["text"].startswith("--- BEGIN USER INPUT ---")

    assert restored.content[0] is not wrapped.content[0]
    assert restored.content[0]["image_url"] is not wrapped.content[0]["image_url"]
    assert restored.additional_kwargs["metadata"] is not wrapped.additional_kwargs["metadata"]

    restored.content[0]["image_url"]["url"] = "data:image/png;base64,changed"
    restored.additional_kwargs["metadata"]["source"] = "history"

    assert wrapped.content[0]["image_url"]["url"] == "data:image/png;base64,abc"
    assert wrapped.additional_kwargs["metadata"]["source"] == "user"


def test_restore_original_human_message_without_original_metadata_is_unchanged():
    message = HumanMessage(content="already UI-facing", additional_kwargs={"source": "user"})

    assert restore_original_human_message(message) is message
