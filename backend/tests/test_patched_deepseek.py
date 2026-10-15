"""Tests for deerflow.models.patched_deepseek.PatchedChatDeepSeek.

Covers:
- LangChain serialization protocol: is_lc_serializable, lc_secrets, to_json
- reasoning_content restoration in _get_request_payload (single and multi-turn)
- Positional fallback when message counts differ
- No-op when no reasoning_content present
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage


def _make_model(**kwargs):
    from deerflow.models.patched_deepseek import PatchedChatDeepSeek

    return PatchedChatDeepSeek(
        model="deepseek-v4-pro",
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
    assert result["kwargs"]["model_name"] == "deepseek-v4-pro"
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


_TOOL_SPEC = [{"type": "function", "function": {"name": "bash", "parameters": {}}}]


def test_reasoning_content_injected_into_assistant_message():
    """reasoning_content from additional_kwargs is restored in the payload."""
    model = _make_model(extra_body={"thinking": {"type": "enabled"}})

    human = HumanMessage(content="What is 2+2?")
    ai = AIMessage(
        content="",
        additional_kwargs={"reasoning_content": "Let me think: 2+2=4"},
        tool_calls=[{"id": "call-1", "name": "calculator", "args": {"expression": "2+2"}}],
    )

    base_payload = {
        "tools": _TOOL_SPEC,
        "messages": [
            _make_payload_message("user", "What is 2+2?"),
            _make_payload_message(
                "assistant",
                None,
                tool_calls=[
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {"name": "calculator", "arguments": '{"expression":"2+2"}'},
                    }
                ],
            ),
        ],
    }

    with patch.object(type(model).__bases__[0], "_get_request_payload", return_value=base_payload):
        with patch.object(model, "_convert_input") as mock_convert:
            mock_convert.return_value = MagicMock(to_messages=lambda: [human, ai])
            payload = model._get_request_payload([human, ai])

    assistant_msg = next(m for m in payload["messages"] if m["role"] == "assistant")
    assert assistant_msg["reasoning_content"] == "Let me think: 2+2=4"
    assert assistant_msg["content"] == ""


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


def test_thinking_tool_call_without_reasoning_gets_empty_placeholder():
    model = _make_model(extra_body={"thinking": {"type": "enabled"}})
    human = HumanMessage(content="Check the repository")
    ai = AIMessage(
        content="",
        tool_calls=[{"id": "call-1", "name": "bash", "args": {"command": "git status"}}],
    )
    base_payload = {
        "messages": [
            _make_payload_message("user", "Check the repository"),
            _make_payload_message(
                "assistant",
                None,
                tool_calls=[
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {"name": "bash", "arguments": '{"command":"git status"}'},
                    }
                ],
            ),
        ]
    }

    with patch.object(type(model).__bases__[0], "_get_request_payload", return_value=base_payload):
        with patch.object(model, "_convert_input") as mock_convert:
            mock_convert.return_value = MagicMock(to_messages=lambda: [human, ai])
            payload = model._get_request_payload([human, ai])

    assistant_msg = payload["messages"][1]
    assert assistant_msg["content"] == ""
    assert assistant_msg["reasoning_content"] == ""


def test_disabled_thinking_tool_call_does_not_invent_reasoning_placeholder():
    """关闭思考时不为原本不存在的 reasoning_content 扩展协议形状。"""
    model = _make_model(extra_body={"thinking": {"type": "disabled"}})
    ai = AIMessage(
        content="",
        tool_calls=[{"id": "call-1", "name": "bash", "args": {"command": "pwd"}}],
    )
    base_payload = {
        "messages": [
            _make_payload_message(
                "assistant",
                None,
                tool_calls=[
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {"name": "bash", "arguments": '{"command":"pwd"}'},
                    }
                ],
            )
        ]
    }

    with patch.object(type(model).__bases__[0], "_get_request_payload", return_value=base_payload):
        with patch.object(model, "_convert_input") as mock_convert:
            mock_convert.return_value = MagicMock(to_messages=lambda: [ai])
            payload = model._get_request_payload([ai])

    assistant_msg = payload["messages"][0]
    assert assistant_msg["content"] == ""
    assert "reasoning_content" not in assistant_msg


def test_reasoning_content_multi_turn():
    """All assistant turns each get their own reasoning_content."""
    model = _make_model(extra_body={"thinking": {"type": "enabled"}})

    human1 = HumanMessage(content="Step 1?")
    ai1 = AIMessage(
        content="",
        additional_kwargs={"reasoning_content": "Thought1"},
        tool_calls=[{"id": "call-1", "name": "lookup", "args": {}}],
    )
    human2 = HumanMessage(content="Step 2?")
    ai2 = AIMessage(content="A2", additional_kwargs={"reasoning_content": "Thought2"})

    base_payload = {
        "tools": _TOOL_SPEC,
        "messages": [
            _make_payload_message("user", "Step 1?"),
            _make_payload_message(
                "assistant",
                None,
                tool_calls=[
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {"name": "lookup", "arguments": "{}"},
                    }
                ],
            ),
            _make_payload_message("user", "Step 2?"),
            _make_payload_message("assistant", "A2"),
        ],
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
    model = _make_model(extra_body={"thinking": {"type": "enabled"}})

    human = HumanMessage(content="hi")
    ai = AIMessage(
        content="",
        additional_kwargs={"reasoning_content": "My reasoning"},
        tool_calls=[{"id": "call-1", "name": "lookup", "args": {}}],
    )

    # Simulate count mismatch: payload has 3 messages, original has 2
    extra_system = _make_payload_message("system", "You are helpful.")
    base_payload = {
        "tools": _TOOL_SPEC,
        "messages": [
            extra_system,
            _make_payload_message("user", "hi"),
            _make_payload_message(
                "assistant",
                None,
                tool_calls=[
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {"name": "lookup", "arguments": "{}"},
                    }
                ],
            ),
        ],
    }

    with patch.object(type(model).__bases__[0], "_get_request_payload", return_value=base_payload):
        with patch.object(model, "_convert_input") as mock_convert:
            mock_convert.return_value = MagicMock(to_messages=lambda: [human, ai])
            payload = model._get_request_payload([human, ai])

    assistant_msg = next(m for m in payload["messages"] if m["role"] == "assistant")
    assert assistant_msg["reasoning_content"] == "My reasoning"


def test_thinking_does_not_replay_reasoning_for_assistant_without_tool_calls():
    model = _make_model(extra_body={"thinking": {"type": "enabled"}})
    human = HumanMessage(content="continue")
    ai = AIMessage(content="local response")
    base_payload = {
        "tools": _TOOL_SPEC,
        "messages": [
            _make_payload_message("assistant", "local response"),
            _make_payload_message("user", "continue"),
        ],
    }

    with patch.object(type(model).__bases__[0], "_get_request_payload", return_value=base_payload):
        with patch.object(model, "_convert_input") as mock_convert:
            mock_convert.return_value = MagicMock(to_messages=lambda: [ai, human])
            payload = model._get_request_payload([ai, human])

    assistant_msg = next(m for m in payload["messages"] if m["role"] == "assistant")
    assert "reasoning_content" not in assistant_msg


def test_legacy_fallback_assistant_is_removed_before_deepseek_replay():
    model = _make_model(extra_body={"thinking": {"type": "enabled"}})
    fallback = AIMessage(
        content="temporary provider error",
        additional_kwargs={"deerflow_error_fallback": True},
    )
    human = HumanMessage(content="retry")
    base_payload = {
        "tools": _TOOL_SPEC,
        "messages": [_make_payload_message("user", "retry")],
    }

    with patch.object(type(model).__bases__[0], "_get_request_payload", return_value=base_payload):
        with patch.object(model, "_convert_input") as mock_convert:
            mock_convert.return_value = MagicMock(to_messages=lambda: [fallback, human])
            payload = model._get_request_payload([fallback, human])

    assert payload["messages"] == base_payload["messages"]
    assert not any(message.get("role") == "assistant" for message in payload["messages"])
