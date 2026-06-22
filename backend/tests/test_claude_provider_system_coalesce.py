"""Tests for non-consecutive system message coalescing in ClaudeChatModel.

Regression test for the Anthropic-only error "Received multiple non-consecutive
system messages." raised by ``langchain_anthropic._format_messages`` when a
``SystemMessage`` is left mid-conversation (e.g. by skill activation,
summarization message removal, or midnight date reminders). The provider now
folds all system content into a single leading block before formatting, so any
message shape stays valid for the Anthropic Messages API.
"""

from unittest import mock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from deerflow.models.claude_provider import ClaudeChatModel


def _make_model() -> ClaudeChatModel:
    """Minimal non-OAuth ClaudeChatModel instance without network calls."""
    with mock.patch.object(ClaudeChatModel, "model_post_init"):
        model = ClaudeChatModel(model="claude-sonnet-4-6", anthropic_api_key="sk-ant-fake-token")  # type: ignore[call-arg]
    # model_post_init is mocked, so initialize the PrivateAttr fields it would
    # normally set (otherwise pydantic's __pydantic_private__ stays None).
    model._is_oauth = False
    model._oauth_access_token = ""
    return model


@pytest.fixture()
def model() -> ClaudeChatModel:
    return _make_model()


def _system_text(system: object) -> str:
    """Flatten a payload ``system`` value (str or list of blocks) to plain text."""
    if isinstance(system, str):
        return system
    if isinstance(system, list):
        return "\n".join(b.get("text", "") for b in system if isinstance(b, dict))
    return ""


# ---------------------------------------------------------------------------
# Regression: the failing shape must not raise (red on main, green here)
# ---------------------------------------------------------------------------


def test_non_consecutive_system_messages_do_not_raise(model):
    """A SystemMessage stranded after human/AI turns previously raised ValueError."""
    messages = [
        SystemMessage(content="MAIN PROMPT"),
        HumanMessage(content="hi"),
        AIMessage(content="hello"),
        SystemMessage(content="LATE SYSTEM"),  # stranded mid-conversation
        HumanMessage(content="more"),
    ]

    payload = model._get_request_payload(messages, stop=None)

    text = _system_text(payload["system"])
    assert "MAIN PROMPT" in text  # both system instructions survive the merge
    assert "LATE SYSTEM" in text
    assert len(payload["messages"]) == 3  # the three non-system turns remain


def test_front_anchored_systems_still_work(model):
    messages = [
        SystemMessage(content="MAIN"),
        SystemMessage(content="DATE"),
        HumanMessage(content="hi"),
    ]

    payload = model._get_request_payload(messages, stop=None)

    text = _system_text(payload["system"])
    assert "MAIN" in text
    assert "DATE" in text


# ---------------------------------------------------------------------------
# _coalesce_system_messages unit behavior
# ---------------------------------------------------------------------------


def test_coalesce_merges_non_leading_system_messages():
    from deerflow.models.claude_provider import _coalesce_system_messages

    messages = [
        SystemMessage(content="A"),
        HumanMessage(content="h1"),
        SystemMessage(content="B"),
        AIMessage(content="a1"),
        SystemMessage(content="C"),
        HumanMessage(content="h2"),
    ]

    result = _coalesce_system_messages(messages)

    assert isinstance(result[0], SystemMessage)
    assert sum(isinstance(m, SystemMessage) for m in result) == 1
    assert [b["text"] for b in result[0].content] == ["A", "B", "C"]
    # Non-system messages keep their original relative order.
    assert [type(m).__name__ for m in result[1:]] == ["HumanMessage", "AIMessage", "HumanMessage"]


@pytest.mark.parametrize(
    "messages",
    [
        [],
        [HumanMessage(content="hi")],
        [SystemMessage(content="only")],
        [SystemMessage(content="a"), SystemMessage(content="b"), HumanMessage(content="hi")],
    ],
)
def test_coalesce_leaves_valid_shapes_untouched(messages):
    from deerflow.models.claude_provider import _coalesce_system_messages

    # Front-anchored (or absent) system messages are already valid for Anthropic;
    # the helper returns the exact same object so normal requests never drift.
    assert _coalesce_system_messages(messages) is messages


def test_coalesce_preserves_list_content_blocks():
    from deerflow.models.claude_provider import _coalesce_system_messages

    block = {"type": "text", "text": "structured", "cache_control": {"type": "ephemeral"}}
    messages = [
        SystemMessage(content="lead"),
        HumanMessage(content="hi"),
        SystemMessage(content=[block]),
    ]

    result = _coalesce_system_messages(messages)

    assert result[0].content[0] == {"type": "text", "text": "lead"}
    assert result[0].content[1] == block  # original block dict preserved verbatim
