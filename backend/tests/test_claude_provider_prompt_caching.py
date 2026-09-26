"""Tests for ClaudeChatModel._apply_prompt_caching.

Validates that the function never places more than 4 cache_control breakpoints
(the hard limit enforced by the Anthropic API and AWS Bedrock) regardless of
how many system blocks, message content blocks, or tool definitions are present,
and that it never writes into blocks the caller still owns.
"""

from unittest import mock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from deerflow.models.claude_provider import ClaudeChatModel


def _make_model(prompt_cache_size: int = 3) -> ClaudeChatModel:
    """Return a minimal ClaudeChatModel instance without network calls."""
    with mock.patch.object(ClaudeChatModel, "model_post_init"):
        m = ClaudeChatModel(
            model="claude-sonnet-4-6",
            anthropic_api_key="sk-ant-fake",  # type: ignore[call-arg]
            prompt_cache_size=prompt_cache_size,
        )
    m._is_oauth = False
    m.enable_prompt_caching = True
    return m


def _count_cache_control(payload: dict) -> int:
    """Count the total number of cache_control markers in a payload."""
    count = 0

    system = payload.get("system", [])
    if isinstance(system, list):
        for block in system:
            if isinstance(block, dict) and "cache_control" in block:
                count += 1

    for msg in payload.get("messages", []):
        if not isinstance(msg, dict):
            continue
        content = msg.get("content", [])
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and "cache_control" in block:
                    count += 1

    for tool in payload.get("tools", []):
        if isinstance(tool, dict) and "cache_control" in tool:
            count += 1

    return count


@pytest.fixture()
def model() -> ClaudeChatModel:
    return _make_model()


# ---------------------------------------------------------------------------
# Basic correctness
# ---------------------------------------------------------------------------


def test_single_system_block_gets_cached(model):
    payload: dict = {"system": [{"type": "text", "text": "sys"}]}
    model._apply_prompt_caching(payload)
    assert payload["system"][0].get("cache_control") == {"type": "ephemeral"}


def test_string_system_converted_and_cached(model):
    payload: dict = {"system": "you are helpful"}
    model._apply_prompt_caching(payload)
    assert isinstance(payload["system"], list)
    assert payload["system"][0].get("cache_control") == {"type": "ephemeral"}


def test_last_tool_gets_cached_when_budget_allows(model):
    payload: dict = {
        "tools": [{"name": "t1"}, {"name": "t2"}],
    }
    model._apply_prompt_caching(payload)
    # With no system or messages the last tool should be cached.
    assert payload["tools"][-1].get("cache_control") == {"type": "ephemeral"}
    assert "cache_control" not in payload["tools"][0]


def test_recent_messages_get_cached(model):
    """The last prompt_cache_size messages' content blocks should be cached."""
    payload: dict = {
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": "hello"}]},
        ],
    }
    model._apply_prompt_caching(payload)
    assert payload["messages"][0]["content"][0].get("cache_control") == {"type": "ephemeral"}


def test_string_message_content_converted_and_cached(model):
    payload: dict = {
        "messages": [
            {"role": "user", "content": "simple string"},
        ],
    }
    model._apply_prompt_caching(payload)
    assert isinstance(payload["messages"][0]["content"], list)
    assert payload["messages"][0]["content"][0].get("cache_control") == {"type": "ephemeral"}


# ---------------------------------------------------------------------------
# Budget enforcement (the core regression test for issue #2448)
# ---------------------------------------------------------------------------


def test_never_exceeds_4_breakpoints_with_large_system(model):
    """Many system text blocks must not produce more than 4 breakpoints total."""
    payload: dict = {
        "system": [{"type": "text", "text": f"sys {i}"} for i in range(6)],
        "tools": [{"name": "t1"}],
    }
    model._apply_prompt_caching(payload)
    assert _count_cache_control(payload) <= 4


def test_never_exceeds_4_breakpoints_multi_turn_with_multi_block_messages(model):
    """Multi-turn conversation where each message has multiple content blocks."""
    # 1 system block + 3 messages × 2 blocks + 1 tool = 8 candidates → must cap at 4
    payload: dict = {
        "system": [{"type": "text", "text": "system prompt"}],
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "user text"},
                    {"type": "tool_result", "tool_use_id": "x", "content": "result"},
                ],
            },
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "assistant text"},
                    {"type": "tool_use", "id": "y", "name": "bash", "input": {}},
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "follow up"},
                    {"type": "text", "text": "second block"},
                ],
            },
        ],
        "tools": [{"name": "bash"}],
    }
    model._apply_prompt_caching(payload)
    total = _count_cache_control(payload)
    assert total <= 4, f"Expected ≤ 4 breakpoints, got {total}"


def test_never_exceeds_4_breakpoints_many_messages(model):
    """Large number of messages with multiple blocks per message."""
    messages = []
    for i in range(10):
        messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": f"msg {i} block a"},
                    {"type": "text", "text": f"msg {i} block b"},
                ],
            }
        )
    payload: dict = {
        "system": [{"type": "text", "text": "sys 1"}, {"type": "text", "text": "sys 2"}],
        "messages": messages,
        "tools": [{"name": "tool_a"}, {"name": "tool_b"}],
    }
    model._apply_prompt_caching(payload)
    total = _count_cache_control(payload)
    assert total <= 4, f"Expected ≤ 4 breakpoints, got {total}"


def test_exactly_4_breakpoints_when_4_or_more_candidates(model):
    """When there are at least 4 candidates, exactly 4 breakpoints are placed."""
    payload: dict = {
        "system": [{"type": "text", "text": f"sys {i}"} for i in range(3)],
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": "user"}]},
            {"role": "assistant", "content": [{"type": "text", "text": "asst"}]},
            {"role": "user", "content": [{"type": "text", "text": "follow"}]},
        ],
        "tools": [{"name": "bash"}],
    }
    model._apply_prompt_caching(payload)
    total = _count_cache_control(payload)
    assert total == 4


def test_breakpoints_placed_on_last_candidates(model):
    """Breakpoints should be on the *last* candidates, not the first."""
    # 5 system blocks but budget = 4 → first system block should NOT be cached,
    # last 4 (indices 1-4) should be.
    payload: dict = {
        "system": [{"type": "text", "text": f"sys {i}"} for i in range(5)],
    }
    model._apply_prompt_caching(payload)
    # First block is NOT in the last-4 window
    assert "cache_control" not in payload["system"][0]
    # Last 4 blocks ARE cached
    for i in range(1, 5):
        assert payload["system"][i].get("cache_control") == {"type": "ephemeral"}, f"block {i} should be cached"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_no_candidates_is_a_no_op(model):
    payload: dict = {}
    model._apply_prompt_caching(payload)
    assert _count_cache_control(payload) == 0


def test_non_text_system_blocks_not_added_as_candidates(model):
    """Image blocks in system should not receive cache_control."""
    payload: dict = {
        "system": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "abc"}},
            {"type": "text", "text": "text block"},
        ],
    }
    model._apply_prompt_caching(payload)
    assert "cache_control" not in payload["system"][0]
    assert payload["system"][1].get("cache_control") == {"type": "ephemeral"}


def test_old_messages_outside_cache_window_not_cached(model):
    """Messages older than prompt_cache_size should not be cached."""
    m = _make_model(prompt_cache_size=1)
    payload: dict = {
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": "old message"}]},
            {"role": "user", "content": [{"type": "text", "text": "recent message"}]},
        ],
    }
    m._apply_prompt_caching(payload)
    # Only the last message should be within the cache window
    assert "cache_control" not in payload["messages"][0]["content"][0]
    assert payload["messages"][1]["content"][0].get("cache_control") == {"type": "ephemeral"}


# ---------------------------------------------------------------------------
# Caller-owned blocks
# ---------------------------------------------------------------------------


def _native_image() -> dict:
    """A Claude-native image block, which langchain-anthropic forwards by reference."""
    return {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "iVBORw0KGgo="}}


def test_breakpoints_are_placed_on_copies_of_caller_blocks(model):
    system_block = {"type": "text", "text": "sys"}
    image = _native_image()
    tool = {"name": "bash"}
    payload: dict = {
        "system": [system_block],
        "messages": [{"role": "user", "content": [image]}],
        "tools": [tool],
    }

    model._apply_prompt_caching(payload)

    assert _count_cache_control(payload) == 3
    assert payload["messages"][0]["content"][0] == {**_native_image(), "cache_control": {"type": "ephemeral"}}
    assert "cache_control" not in system_block
    assert "cache_control" not in image
    assert "cache_control" not in tool


def test_repeated_requests_leave_thread_messages_unmarked(model):
    """Regression: a marker written into a message's own block was checkpointed.

    Every later request then carried the stale markers of earlier turns on top
    of its own four, and the API rejected the thread from the third turn on.
    """
    history: list = [SystemMessage(content="You are helpful.")]
    for turn in range(1, 6):
        history.append(HumanMessage(content=[_native_image()], id=f"human-{turn}"))
        payload = model._get_request_payload(history)
        assert _count_cache_control(payload) <= 4, f"turn {turn}"
        history.append(AIMessage(content=f"answer {turn}", id=f"ai-{turn}"))

    assert all(message.content == [_native_image()] for message in history if isinstance(message, HumanMessage))


def test_markers_already_in_the_request_are_replaced(model):
    """Checkpoints written by older versions can carry markers on old blocks."""
    stale = [{**_native_image(), "cache_control": {"type": "ephemeral"}} for _ in range(5)]
    payload: dict = {
        "system": [{"type": "text", "text": "sys", "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": [block]} for block in stale],
        "tools": [{"name": "bash", "cache_control": {"type": "ephemeral"}}],
    }

    model._apply_prompt_caching(payload)

    # Candidates: the system block, the last three messages, the tool — the
    # system block falls outside the last four.
    assert _count_cache_control(payload) == 4
    assert [index for index, message in enumerate(payload["messages"]) if "cache_control" in message["content"][0]] == [2, 3, 4]
    assert "cache_control" not in payload["system"][0]
    assert payload["tools"][0]["cache_control"] == {"type": "ephemeral"}
    assert all("cache_control" in block for block in stale)


def test_strip_cache_control_copies_instead_of_popping():
    system_block = {"type": "text", "text": "sys", "cache_control": {"type": "ephemeral"}}
    image = {**_native_image(), "cache_control": {"type": "ephemeral"}}
    tool = {"name": "bash", "cache_control": {"type": "ephemeral"}}
    message = {"role": "user", "content": [image], "cache_control": {"type": "ephemeral"}}
    payload: dict = {"system": [system_block], "messages": [message], "tools": [tool]}

    ClaudeChatModel._strip_cache_control(payload)

    assert _count_cache_control(payload) == 0
    assert payload["messages"][0] == {"role": "user", "content": [_native_image()]}
    assert all("cache_control" in item for item in (system_block, image, tool, message))
