"""Tests for deerflow.models.patched_openai.PatchedChatOpenAI.

These tests verify that _restore_thinking_blocks correctly re-injects
thought_signature-carrying thinking blocks into the outgoing payload for
assistant messages, covering the two storage patterns that LangChain may use
and several edge-cases.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage

from deerflow.models.patched_openai import _restore_thinking_blocks

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SIGNED_BLOCK = {
    "type": "thinking",
    "thinking": "Let me reason about this...",
    "thought_signature": "abc123==",
}

UNSIGNED_BLOCK = {
    "type": "thinking",
    "thinking": "Some thought without a signature",
}

TEXT_BLOCK = {"type": "text", "text": "I will fetch the page for you."}


def _ai_msg_with_additional_kwargs(thinking_blocks: list[dict]) -> AIMessage:
    return AIMessage(content="", additional_kwargs={"thinking_blocks": thinking_blocks})


def _ai_msg_with_list_content(content: list[dict]) -> AIMessage:
    return AIMessage(content=content)


def _ai_msg_with_str_content(text: str) -> AIMessage:
    return AIMessage(content=text)


# ---------------------------------------------------------------------------
# Core: signed block in additional_kwargs
# ---------------------------------------------------------------------------


def test_signed_block_from_additional_kwargs_prepended_to_none_content():
    """Signed block from additional_kwargs is injected when payload content is None."""
    payload_msg = {"role": "assistant", "content": None}
    orig = _ai_msg_with_additional_kwargs([SIGNED_BLOCK])

    _restore_thinking_blocks(payload_msg, orig)

    assert payload_msg["content"] == [SIGNED_BLOCK]


def test_signed_block_from_additional_kwargs_prepended_to_string_content():
    """Signed block is prepended; plain string content is wrapped as text block."""
    payload_msg = {"role": "assistant", "content": "Calling tool now."}
    orig = _ai_msg_with_additional_kwargs([SIGNED_BLOCK])

    _restore_thinking_blocks(payload_msg, orig)

    assert payload_msg["content"] == [
        SIGNED_BLOCK,
        {"type": "text", "text": "Calling tool now."},
    ]


def test_signed_block_from_additional_kwargs_prepended_to_list_content():
    """Signed block is prepended to an existing content list."""
    payload_msg = {"role": "assistant", "content": [TEXT_BLOCK]}
    orig = _ai_msg_with_additional_kwargs([SIGNED_BLOCK])

    _restore_thinking_blocks(payload_msg, orig)

    assert payload_msg["content"] == [SIGNED_BLOCK, TEXT_BLOCK]


# ---------------------------------------------------------------------------
# Core: signed block in AIMessage.content (list)
# ---------------------------------------------------------------------------


def test_signed_block_from_list_content():
    """Signed block found in content list is injected into the payload."""
    payload_msg = {"role": "assistant", "content": None}
    orig = _ai_msg_with_list_content([SIGNED_BLOCK, TEXT_BLOCK])

    _restore_thinking_blocks(payload_msg, orig)

    assert SIGNED_BLOCK in payload_msg["content"]


def test_signed_block_from_list_content_deduplicates_existing_stale_blocks():
    """Stale (unsigned) thinking blocks already in the payload list are replaced."""
    stale = {"type": "thinking", "thinking": "old thought"}  # no thought_signature
    payload_msg = {"role": "assistant", "content": [stale, TEXT_BLOCK]}
    orig = _ai_msg_with_list_content([SIGNED_BLOCK, TEXT_BLOCK])

    _restore_thinking_blocks(payload_msg, orig)

    assert stale not in payload_msg["content"]
    assert SIGNED_BLOCK in payload_msg["content"]
    assert TEXT_BLOCK in payload_msg["content"]


# ---------------------------------------------------------------------------
# Edge cases: no-op scenarios
# ---------------------------------------------------------------------------


def test_no_thinking_blocks_anywhere_is_noop():
    """No change when the AIMessage has no thinking blocks at all."""
    payload_msg = {"role": "assistant", "content": None}
    orig = AIMessage(content="plain response")

    _restore_thinking_blocks(payload_msg, orig)

    assert payload_msg["content"] is None


def test_unsigned_block_only_is_noop():
    """Thinking blocks without thought_signature must not be injected."""
    payload_msg = {"role": "assistant", "content": None}
    orig = _ai_msg_with_additional_kwargs([UNSIGNED_BLOCK])

    _restore_thinking_blocks(payload_msg, orig)

    assert payload_msg["content"] is None


def test_empty_additional_kwargs_thinking_blocks_list_is_noop():
    """Empty thinking_blocks list in additional_kwargs triggers no injection."""
    payload_msg = {"role": "assistant", "content": "response"}
    orig = _ai_msg_with_additional_kwargs([])

    _restore_thinking_blocks(payload_msg, orig)

    assert payload_msg["content"] == "response"


def test_additional_kwargs_missing_thinking_blocks_key_is_noop():
    """No thinking_blocks key in additional_kwargs → no injection."""
    payload_msg = {"role": "assistant", "content": "response"}
    orig = AIMessage(content="response", additional_kwargs={"some_other_key": "value"})

    _restore_thinking_blocks(payload_msg, orig)

    assert payload_msg["content"] == "response"


# ---------------------------------------------------------------------------
# Priority: additional_kwargs takes precedence over content list
# ---------------------------------------------------------------------------


def test_additional_kwargs_takes_precedence_over_content_list():
    """When both storage locations have thinking blocks, additional_kwargs wins."""
    alt_block = {
        "type": "thinking",
        "thinking": "Another thought",
        "thought_signature": "xyz789==",
    }
    payload_msg = {"role": "assistant", "content": None}
    # additional_kwargs has SIGNED_BLOCK, content list has alt_block
    orig = AIMessage(
        content=[alt_block],
        additional_kwargs={"thinking_blocks": [SIGNED_BLOCK]},
    )

    _restore_thinking_blocks(payload_msg, orig)

    # SIGNED_BLOCK from additional_kwargs should win
    assert SIGNED_BLOCK in payload_msg["content"]
    assert alt_block not in payload_msg["content"]


# ---------------------------------------------------------------------------
# Multiple signed blocks
# ---------------------------------------------------------------------------


def test_multiple_signed_blocks_all_injected():
    """All signed thinking blocks are injected, preserving order."""
    block1 = {"type": "thinking", "thinking": "first", "thought_signature": "sig1=="}
    block2 = {"type": "thinking", "thinking": "second", "thought_signature": "sig2=="}
    payload_msg = {"role": "assistant", "content": [TEXT_BLOCK]}
    orig = _ai_msg_with_additional_kwargs([block1, block2])

    _restore_thinking_blocks(payload_msg, orig)

    assert payload_msg["content"] == [block1, block2, TEXT_BLOCK]


# Integration behavior is validated via _restore_thinking_blocks unit coverage above.
