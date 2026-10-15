"""PII redaction must cover malformed and legacy calls at memory admission."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, messages_from_dict, messages_to_dict
from langchain_openai.chat_models.base import _convert_dict_to_message
from langgraph.runtime import Runtime

from deerflow.agents.memory import summarization_hook
from deerflow.agents.middlewares import memory_middleware
from deerflow.agents.middlewares.memory_middleware import MemoryMiddleware
from deerflow.agents.middlewares.pii_redaction_middleware import redact_text
from deerflow.agents.middlewares.summarization_middleware import SummarizationEvent
from deerflow.config.memory_config import MemoryConfig
from deerflow.config.pii_redaction_config import PiiRedactionConfig

_EMAIL = "alice@example.com"
_SECRET = "memory-regression-deployment-secret"


def _attempt(kind: str) -> AIMessage:
    if kind == "invalid-checkpoint":
        # A persisted parsed-invalid view need not retain provider-raw calls.
        message = AIMessage(content="Preparing contact lookup", invalid_tool_calls=[{"name": "lookup", "id": "call-1", "args": '{"email":"alice@example.com",', "error": "Invalid arguments for alice@example.com"}])
    elif kind == "legacy":
        message = _convert_dict_to_message({"role": "assistant", "content": "Preparing contact lookup", "function_call": {"name": "lookup", "arguments": '{"email":"alice@example.com"}'}})
    else:
        message = _convert_dict_to_message({"role": "assistant", "content": "Preparing contact lookup", "tool_calls": [{"id": "call-1", "type": "function", "function": {"name": "lookup", "arguments": '{"email":"alice@example.com",'}}]})
        assert isinstance(message, AIMessage) and not message.tool_calls and message.invalid_tool_calls
    assert isinstance(message, AIMessage)
    return messages_from_dict(messages_to_dict([message]))[0]


def _capture(monkeypatch: pytest.MonkeyPatch, entry: str, messages: list, pii_config: PiiRedactionConfig | None) -> list:
    recorded = []

    def record(_thread_id, queued, **_kwargs):
        recorded.append(queued)

    manager = MagicMock()
    manager.add.side_effect = record
    manager.aadd = AsyncMock(side_effect=record)
    manager.add_nowait.side_effect = record
    monkeypatch.setattr(memory_middleware, "get_memory_manager", lambda: manager)
    monkeypatch.setattr(summarization_hook, "get_memory_manager", lambda: manager)
    monkeypatch.setattr(summarization_hook, "get_memory_config", lambda: MemoryConfig(enabled=True))
    runtime = Runtime(context={"thread_id": "thread-1", "user_id": "alice"})
    middleware = MemoryMiddleware(memory_config=MemoryConfig(enabled=True), pii_redaction_config=pii_config)
    if entry == "after-agent":
        middleware.after_agent({"messages": messages}, runtime)
    elif entry == "async-after-agent":
        asyncio.run(middleware.aafter_agent({"messages": messages}, runtime))
    else:
        event = SummarizationEvent(messages_to_summarize=tuple(messages), preserved_messages=(), thread_id="thread-1", agent_name=None, runtime=runtime)
        summarization_hook.memory_flush_hook(event, pii_redaction_config=pii_config)
    assert len(recorded) == 1
    return recorded[0]


@pytest.mark.parametrize("kind", ["provider-invalid", "invalid-checkpoint", "legacy"])
@pytest.mark.parametrize("entry", ["after-agent", "async-after-agent", "compaction"])
def test_invalid_and_legacy_call_views_are_redacted_before_memory_admission(monkeypatch, kind: str, entry: str) -> None:
    attempt = _attempt(kind)
    messages = [HumanMessage(f"Look up {_EMAIL}"), attempt, AIMessage("Lookup was not executed")]
    original = messages_to_dict(messages)
    config = PiiRedactionConfig(enabled=True, token_secret=_SECRET)

    queued = _capture(monkeypatch, entry, messages, config)

    assert _EMAIL not in str(messages_to_dict(queued))
    token = redact_text(_EMAIL, config)
    assert token in queued[0].content
    if kind == "legacy":
        assert queued[1].additional_kwargs["function_call"]["name"] == "lookup"
        assert token in queued[1].additional_kwargs["function_call"]["arguments"]
    else:
        assert not queued[1].tool_calls
        assert queued[1].invalid_tool_calls[0]["id"] == "call-1"
        assert queued[1].invalid_tool_calls[0]["name"] == "lookup"
        assert token in queued[1].invalid_tool_calls[0]["args"]
        assert token in queued[1].invalid_tool_calls[0]["error"]
    assert queued[1].content == attempt.content
    assert queued[2] is messages[2]
    assert messages_to_dict(messages) == original


@pytest.mark.parametrize("kind", ["provider-invalid", "invalid-checkpoint", "legacy"])
@pytest.mark.parametrize("entry", ["after-agent", "async-after-agent", "compaction"])
@pytest.mark.parametrize("policy", ["no-config", "disabled", "email-disabled"])
def test_call_views_follow_existing_redaction_opt_in_and_detector_policy(monkeypatch, kind: str, entry: str, policy: str) -> None:
    config = None if policy == "no-config" else PiiRedactionConfig(enabled=policy != "disabled", redact_email=policy != "email-disabled", token_secret=_SECRET)
    messages = [_attempt(kind)]
    original = messages_to_dict(messages)

    queued = _capture(monkeypatch, entry, messages, config)

    assert queued[0] is messages[0]
    assert messages_to_dict(queued) == original
