"""Completed Codex refusals survive parsing and avoid empty-response recovery."""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage

from deerflow.agents.middlewares.llm_error_handling_middleware import LLMErrorHandlingMiddleware
from deerflow.agents.middlewares.safety_finish_reason_middleware import SafetyFinishReasonMiddleware
from deerflow.agents.middlewares.terminal_response_middleware import TerminalResponseMiddleware
from deerflow.config.app_config import AppConfig
from deerflow.models import openai_codex_provider as provider
from deerflow.models.credential_loader import CodexCliCredential

REFUSAL = "I cannot help with that request."
USAGE = {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5}


@pytest.fixture
def model(monkeypatch):
    monkeypatch.setattr(provider, "load_codex_cli_credential", lambda: CodexCliCredential("synthetic-token", "synthetic-account"))
    return provider.CodexChatModel(model="fixture-model")


def _message_item(content):
    return {"id": "msg_fixture", "type": "message", "role": "assistant", "status": "completed", "content": content}


def test_refusal_preserves_mixed_output_order_and_other_payloads(model):
    result = model._parse_response(
        {
            "model": "fixture-model",
            "output": [
                {"type": "reasoning", "summary": [{"type": "summary_text", "text": "Reasoning summary"}]},
                _message_item([{"type": "output_text", "text": "Before\n"}, {"type": "refusal", "refusal": REFUSAL}, {"type": "output_text", "text": "\nAfter"}]),
                {"type": "function_call", "name": "echo", "arguments": '{"value":1}', "call_id": "call_fixture"},
            ],
            "usage": USAGE,
        }
    )
    message = result.generations[0].message
    assert message.content == f"Before\n{REFUSAL}\nAfter"
    assert message.additional_kwargs == {"refusal": REFUSAL, "reasoning_content": "Reasoning summary"}
    assert message.tool_calls == [{"name": "echo", "args": {"value": 1}, "id": "call_fixture", "type": "tool_call"}]
    assert message.usage_metadata == USAGE
    assert message.response_metadata == {"model": "fixture-model", "usage": USAGE}


def test_multiple_refusal_parts_preserve_exact_text(model):
    parts = ["  First", "\nSecond  "]
    message = model._parse_response({"output": [_message_item([{"type": "refusal", "refusal": text} for text in parts])]}).generations[0].message
    assert message.content == "".join(parts)
    assert message.additional_kwargs["refusal"] == "".join(parts)


@pytest.mark.parametrize("value", [None, [], {}, 42])
def test_malformed_refusal_does_not_fabricate_visible_content(model, value):
    message = model._parse_response({"output": [_message_item([{"type": "refusal", "refusal": value}, {"type": "output_text", "text": "Original text"}])]}).generations[0].message
    assert message.content == "Original text"
    assert "refusal" not in message.additional_kwargs


@pytest.mark.parametrize("text", ["", " \n "])
def test_blank_refusal_is_not_replaced_with_fabricated_text(model, text):
    message = model._parse_response({"output": [_message_item([{"type": "refusal", "refusal": text}])]}).generations[0].message
    assert message.content == text
    assert message.additional_kwargs["refusal"] == text


class _EventStream(httpx.SyncByteStream, httpx.AsyncByteStream):
    def __init__(self, events):
        self.events = events
        self.closed = False

    def __iter__(self):
        for event in self.events:
            yield f"data: {json.dumps(event)}\n\n".encode()

    async def __aiter__(self):
        for chunk in self:
            yield chunk

    def close(self):
        self.closed = True

    async def aclose(self):
        self.close()


@pytest.mark.parametrize("kind", ["refusal", "output_text"])
@pytest.mark.parametrize("recover_output", [False, True])
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.asyncio
async def test_completed_refusal_avoids_agent_empty_response_retry(model, monkeypatch, kind, recover_output, asynchronous):
    expected_text = REFUSAL if kind == "refusal" else "Control response"
    part = {"type": kind, "refusal" if kind == "refusal" else "text": expected_text}
    item = _message_item([part])
    response = {"id": "resp_fixture", "model": "fixture-model", "status": "completed", "output": [] if recover_output else [item], "usage": USAGE}
    events = [{"type": "response.output_item.done", "output_index": 0, "item": item}, {"type": "response.completed", "response": response}]
    requests = []
    streams = []

    def handle(request):
        requests.append(request)
        stream = _EventStream(events)
        streams.append(stream)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=stream)

    transport = httpx.MockTransport(handle)
    httpx_binding = SimpleNamespace(**{key: getattr(httpx, key) for key in dir(httpx) if not key.startswith("__")})
    httpx_binding.Client = lambda **kwargs: httpx.Client(transport=transport, **kwargs)
    httpx_binding.AsyncClient = lambda **kwargs: httpx.AsyncClient(transport=transport, **kwargs)
    monkeypatch.setattr(provider, "httpx", httpx_binding)
    config = AppConfig.model_validate(
        {
            "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
            "models": [{"name": "fixture-model", "model": "fixture-model", "use": "deerflow.models.openai_codex_provider:CodexChatModel"}],
            "llm_call": {"retry_base_delay_ms": 1, "retry_cap_delay_ms": 1},
        }
    )
    graph = create_agent(model, tools=[], middleware=[LLMErrorHandlingMiddleware(app_config=config), TerminalResponseMiddleware(), SafetyFinishReasonMiddleware()])
    inputs = {"messages": [HumanMessage(content="Synthetic fixture request")]}
    state = await graph.ainvoke(inputs) if asynchronous else graph.invoke(inputs)
    message = state["messages"][-1]

    assert len(requests) == 1
    assert message.content == expected_text
    assert message.additional_kwargs.get("refusal") == (REFUSAL if kind == "refusal" else None)
    assert not message.additional_kwargs.get("deerflow_error_fallback")
    assert message.usage_metadata == USAGE
    assert all(stream.closed for stream in streams)
