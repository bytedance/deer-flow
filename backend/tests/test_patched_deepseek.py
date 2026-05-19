"""Tests for deerflow.models.patched_deepseek.PatchedChatDeepSeek.

Covers:
- LangChain serialization protocol: is_lc_serializable, lc_secrets, to_json
- reasoning_content restoration in _get_request_payload (single and multi-turn)
- Positional fallback when message counts differ
- No-op when no reasoning_content present
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


def _make_model(**kwargs):
    from deerflow.models.patched_deepseek import PatchedChatDeepSeek

    return PatchedChatDeepSeek(
        model="deepseek-reasoner",
        api_key="test-key",
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Serialization protocol
# ---------------------------------------------------------------------------


def test_is_lc_serializable_returns_true():
    from deerflow.models.patched_deepseek import PatchedChatDeepSeek

    assert PatchedChatDeepSeek.is_lc_serializable() is True


def test_lc_secrets_contains_api_key_mapping():
    model = _make_model()
    secrets = model.lc_secrets
    assert "api_key" in secrets
    assert secrets["api_key"] == "DEEPSEEK_API_KEY"
    assert "openai_api_key" in secrets


def test_to_json_produces_constructor_type():
    model = _make_model()
    result = model.to_json()
    assert result["type"] == "constructor"
    assert "kwargs" in result


def test_to_json_kwargs_contains_model():
    model = _make_model()
    result = model.to_json()
    assert result["kwargs"]["model_name"] == "deepseek-reasoner"
    assert result["kwargs"]["api_base"] == "https://api.deepseek.com/v1"


def test_to_json_kwargs_contains_custom_api_base():
    model = _make_model(api_base="https://ark.cn-beijing.volces.com/api/v3")
    result = model.to_json()
    assert result["kwargs"]["api_base"] == "https://ark.cn-beijing.volces.com/api/v3"


def test_to_json_api_key_is_masked():
    """api_key must not appear as plain text in the serialized output."""
    model = _make_model()
    result = model.to_json()
    api_key_value = result["kwargs"].get("api_key") or result["kwargs"].get("openai_api_key")
    assert api_key_value is None or isinstance(api_key_value, dict), f"API key must not be plain text, got: {api_key_value!r}"


# ---------------------------------------------------------------------------
# reasoning_content preservation in _get_request_payload
# ---------------------------------------------------------------------------


def _make_payload_message(role: str, content: str | None = None, tool_calls: list | None = None) -> dict:
    msg: dict = {"role": role, "content": content}
    if tool_calls is not None:
        msg["tool_calls"] = tool_calls
    return msg


def test_reasoning_content_injected_into_assistant_message():
    """reasoning_content from additional_kwargs is restored in the payload."""
    model = _make_model()

    human = HumanMessage(content="What is 2+2?")
    ai = AIMessage(
        content="4",
        additional_kwargs={"reasoning_content": "Let me think: 2+2=4"},
    )

    base_payload = {
        "messages": [
            _make_payload_message("user", "What is 2+2?"),
            _make_payload_message("assistant", "4"),
        ]
    }

    with patch.object(type(model).__bases__[0], "_get_request_payload", return_value=base_payload):
        with patch.object(model, "_convert_input") as mock_convert:
            mock_convert.return_value = MagicMock(to_messages=lambda: [human, ai])
            payload = model._get_request_payload([human, ai])

    assistant_msg = next(m for m in payload["messages"] if m["role"] == "assistant")
    assert assistant_msg["reasoning_content"] == "Let me think: 2+2=4"


def test_no_reasoning_content_is_noop():
    """Messages without reasoning_content are left unchanged."""
    model = _make_model()

    human = HumanMessage(content="hello")
    ai = AIMessage(content="hi", additional_kwargs={})

    base_payload = {
        "messages": [
            _make_payload_message("user", "hello"),
            _make_payload_message("assistant", "hi"),
        ]
    }

    with patch.object(type(model).__bases__[0], "_get_request_payload", return_value=base_payload):
        with patch.object(model, "_convert_input") as mock_convert:
            mock_convert.return_value = MagicMock(to_messages=lambda: [human, ai])
            payload = model._get_request_payload([human, ai])

    assistant_msg = next(m for m in payload["messages"] if m["role"] == "assistant")
    assert "reasoning_content" not in assistant_msg


def test_reasoning_content_multi_turn():
    """All assistant turns each get their own reasoning_content."""
    model = _make_model()

    human1 = HumanMessage(content="Step 1?")
    ai1 = AIMessage(content="A1", additional_kwargs={"reasoning_content": "Thought1"})
    human2 = HumanMessage(content="Step 2?")
    ai2 = AIMessage(content="A2", additional_kwargs={"reasoning_content": "Thought2"})

    base_payload = {
        "messages": [
            _make_payload_message("user", "Step 1?"),
            _make_payload_message("assistant", "A1"),
            _make_payload_message("user", "Step 2?"),
            _make_payload_message("assistant", "A2"),
        ]
    }

    with patch.object(type(model).__bases__[0], "_get_request_payload", return_value=base_payload):
        with patch.object(model, "_convert_input") as mock_convert:
            mock_convert.return_value = MagicMock(to_messages=lambda: [human1, ai1, human2, ai2])
            payload = model._get_request_payload([human1, ai1, human2, ai2])

    assistant_msgs = [m for m in payload["messages"] if m["role"] == "assistant"]
    assert assistant_msgs[0]["reasoning_content"] == "Thought1"
    assert assistant_msgs[1]["reasoning_content"] == "Thought2"


def test_positional_fallback_when_count_differs():
    """Falls back to positional matching when payload/original message counts differ."""
    model = _make_model()

    human = HumanMessage(content="hi")
    ai = AIMessage(content="hello", additional_kwargs={"reasoning_content": "My reasoning"})

    # Simulate count mismatch: payload has 3 messages, original has 2
    extra_system = _make_payload_message("system", "You are helpful.")
    base_payload = {
        "messages": [
            extra_system,
            _make_payload_message("user", "hi"),
            _make_payload_message("assistant", "hello"),
        ]
    }

    with patch.object(type(model).__bases__[0], "_get_request_payload", return_value=base_payload):
        with patch.object(model, "_convert_input") as mock_convert:
            mock_convert.return_value = MagicMock(to_messages=lambda: [human, ai])
            payload = model._get_request_payload([human, ai])

    assistant_msg = next(m for m in payload["messages"] if m["role"] == "assistant")
    assert assistant_msg["reasoning_content"] == "My reasoning"


def test_reasoning_content_injected_when_assistant_has_tool_calls():
    """reasoning_content is preserved on assistant messages that also carry tool_calls.

    Regression for issues #3043 and #3050: APIs like Kimi K2.5 and DeepSeek Chat (thinking
    mode) reject the request with 'reasoning_content missing in assistant tool call message'
    when reasoning_content is dropped from a tool-call turn.
    """
    model = _make_model()

    human = HumanMessage(content="Search for X")
    ai_with_tools = AIMessage(
        content="",
        tool_calls=[{"id": "call_1", "name": "search", "args": {"q": "X"}, "type": "tool_call"}],
        additional_kwargs={"reasoning_content": "I need to search for X"},
    )

    tool_calls_payload = [{"id": "call_1", "type": "function", "function": {"name": "search", "arguments": '{"q": "X"}'}}]
    base_payload = {
        "messages": [
            _make_payload_message("user", "Search for X"),
            _make_payload_message("assistant", "", tool_calls=tool_calls_payload),
        ]
    }

    with patch.object(type(model).__bases__[0], "_get_request_payload", return_value=base_payload):
        with patch.object(model, "_convert_input") as mock_convert:
            mock_convert.return_value = MagicMock(to_messages=lambda: [human, ai_with_tools])
            payload = model._get_request_payload([human, ai_with_tools])

    assistant_msg = next(m for m in payload["messages"] if m["role"] == "assistant")
    assert assistant_msg["reasoning_content"] == "I need to search for X"
    assert assistant_msg["tool_calls"] == tool_calls_payload


def test_reasoning_content_preserved_across_tool_call_turn():
    """reasoning_content survives a full tool-call round-trip (assistant → tool → next turn).

    The payload for the follow-up model call still includes the assistant tool-call message
    from turn 1; that message must carry reasoning_content or the API rejects the request.
    """
    model = _make_model()

    human = HumanMessage(content="Search for X")
    ai_with_tools = AIMessage(
        content="",
        tool_calls=[{"id": "call_1", "name": "search", "args": {"q": "X"}, "type": "tool_call"}],
        additional_kwargs={"reasoning_content": "I need to search for X"},
    )
    tool_result = ToolMessage(content="Found results for X", tool_call_id="call_1")

    tool_calls_payload = [{"id": "call_1", "type": "function", "function": {"name": "search", "arguments": '{"q": "X"}'}}]
    base_payload = {
        "messages": [
            _make_payload_message("user", "Search for X"),
            _make_payload_message("assistant", "", tool_calls=tool_calls_payload),
            {"role": "tool", "content": "Found results for X", "tool_call_id": "call_1"},
        ]
    }

    with patch.object(type(model).__bases__[0], "_get_request_payload", return_value=base_payload):
        with patch.object(model, "_convert_input") as mock_convert:
            mock_convert.return_value = MagicMock(to_messages=lambda: [human, ai_with_tools, tool_result])
            payload = model._get_request_payload([human, ai_with_tools, tool_result])

    assistant_msg = next(m for m in payload["messages"] if m["role"] == "assistant")
    assert assistant_msg["reasoning_content"] == "I need to search for X"
    assert assistant_msg["tool_calls"] == tool_calls_payload
