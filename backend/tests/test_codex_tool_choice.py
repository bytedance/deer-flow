"""Preserve tool selection through public Codex calls and real HTTP serialization."""

from __future__ import annotations

import asyncio
import copy
import json

import httpx
import pytest
from langchain_core.messages import HumanMessage, ToolMessage

from deerflow.models import openai_codex_provider as provider
from deerflow.models.credential_loader import CodexCliCredential


@pytest.mark.parametrize(
    "tool_choice,expected",
    [
        (None, None),
        (False, None),
        (True, "required"),
        ("auto", "auto"),
        ("none", "none"),
        ("required", "required"),
        ("any", "required"),
        ("read_report", {"type": "function", "name": "read_report"}),
        ({"type": "function", "name": "read_report"}, {"type": "function", "name": "read_report"}),
        ({"type": "function", "function": {"name": "read_report"}}, {"type": "function", "name": "read_report"}),
    ],
)
@pytest.mark.parametrize("binding", ["direct", "bound"])
@pytest.mark.parametrize("invocation", ["invoke", "ainvoke"])
def test_tool_choice_survives_request_and_tool_followup(monkeypatch, tool_choice, expected, binding, invocation):
    definition = {"type": "function", "function": {"name": "read_report", "description": "Read a prepared report.", "parameters": {"type": "object", "properties": {}}}}
    original_definition = copy.deepcopy(definition)
    original_choice = copy.deepcopy(tool_choice)
    monkeypatch.setattr(provider, "load_codex_cli_credential", lambda: CodexCliCredential("fake-token", "fake-account"))
    model = provider.CodexChatModel(retry_max_attempts=1)
    runnable = model.bind_tools([definition], tool_choice=tool_choice) if binding == "bound" else model
    kwargs = {} if binding == "bound" else {"tools": [definition], "tool_choice": tool_choice}
    requests = []
    clients = []
    responses = []
    client_class = httpx.Client

    def handle(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if len(requests) == 1 and payload.get("tool_choice") != "none":
            output = [{"type": "function_call", "name": "read_report", "arguments": "{}", "call_id": "call-report"}]
        else:
            output = [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Report ready."}]}]
        event = {"type": "response.completed", "response": {"id": "response-report", "status": "completed", "output": output, "usage": None}}
        response = httpx.Response(200, headers={"content-type": "text/event-stream"}, content=f"data: {json.dumps(event)}\n\n".encode())
        responses.append(response)
        return response

    def make_client(**options):
        client = client_class(transport=httpx.MockTransport(handle), **options)
        clients.append(client)
        return client

    monkeypatch.setattr(provider.httpx, "Client", make_client)
    history = [HumanMessage(content="Read the quarterly report.")]

    if invocation == "invoke":
        first = runnable.invoke(history, **kwargs)
        followup = [*history, first, ToolMessage(content="Report contents", tool_call_id="call-report")] if first.tool_calls else None
        answer = runnable.invoke(followup, **{**kwargs, "tool_choice": "none"}) if followup else first
    else:

        async def exchange():
            first = await runnable.ainvoke(history, **kwargs)
            followup = [*history, first, ToolMessage(content="Report contents", tool_call_id="call-report")] if first.tool_calls else None
            answer = await runnable.ainvoke(followup, **{**kwargs, "tool_choice": "none"}) if followup else first
            return first, followup, answer

        first, followup, answer = asyncio.run(exchange())

    if expected is None:
        assert "tool_choice" not in requests[0]
    else:
        assert requests[0].get("tool_choice") == expected
    assert answer.content == "Report ready."
    if expected == "none":
        assert not first.tool_calls
        assert len(requests) == 1
    else:
        assert first.tool_calls == [{"name": "read_report", "args": {}, "id": "call-report", "type": "tool_call"}]
        assert len(requests) == 2
        assert requests[1]["tool_choice"] == "none"
        assert requests[1]["input"][-2:] == [
            {"type": "function_call", "name": "read_report", "arguments": "{}", "call_id": "call-report"},
            {"type": "function_call_output", "call_id": "call-report", "output": "Report contents"},
        ]
    assert definition == original_definition
    assert tool_choice == original_choice
    assert history == [HumanMessage(content="Read the quarterly report.")]
    assert all(client.is_closed for client in clients)
    assert all(response.is_closed for response in responses)


@pytest.mark.parametrize("tool_choice", [123, [], "", {"type": "file_search"}, {"type": "function"}, {"type": "function", "function": "read_report"}])
def test_invalid_tool_choice_fails_before_http(monkeypatch, tool_choice):
    monkeypatch.setattr(provider, "load_codex_cli_credential", lambda: CodexCliCredential("fake-token", "fake-account"))
    model = provider.CodexChatModel(retry_max_attempts=1)
    definition = {"name": "read_report", "parameters": {"type": "object", "properties": {}}}

    def unexpected_http(**options):
        pytest.fail("Invalid tool_choice must fail before creating an HTTP client")

    monkeypatch.setattr(provider.httpx, "Client", unexpected_http)
    with pytest.raises(ValueError, match="tool_choice"):
        model.invoke([HumanMessage(content="Read the report.")], tools=[definition], tool_choice=tool_choice)


@pytest.mark.parametrize("tool_choice", [123, [], "", {"type": "file_search"}, {"type": "function"}, {"type": "function", "function": "read_report"}])
def test_invalid_bound_choice_fails_at_bind_time(monkeypatch, tool_choice):
    monkeypatch.setattr(provider, "load_codex_cli_credential", lambda: CodexCliCredential("fake-token", "fake-account"))
    model = provider.CodexChatModel(retry_max_attempts=1)
    with pytest.raises(ValueError, match="tool_choice"):
        model.bind_tools([{"name": "read_report"}], tool_choice=tool_choice)


@pytest.mark.parametrize(
    "tools,tool_choice",
    [
        (None, "required"),
        ([], "any"),
        ([], "read_report"),
        ([{"type": "web_search"}], True),
        ([{"type": "web_search"}], {"type": "function", "function": {"name": "read_report"}}),
        ([{"name": "other_function"}], "read_report"),
        ([{"name": "other_function"}], {"type": "function", "name": "read_report"}),
    ],
)
@pytest.mark.parametrize("invocation", ["invoke", "ainvoke", "bind_tools"])
def test_forced_selection_needs_available_function(monkeypatch, tools, tool_choice, invocation):
    monkeypatch.setattr(provider, "load_codex_cli_credential", lambda: CodexCliCredential("fake-token", "fake-account"))
    model = provider.CodexChatModel(retry_max_attempts=1)

    def unexpected_http(**options):
        pytest.fail("Invalid selection must be rejected before creating an HTTP client")

    monkeypatch.setattr(provider.httpx, "Client", unexpected_http)
    with pytest.raises(ValueError, match="tool_choice"):
        if invocation == "bind_tools":
            model.bind_tools(tools or [], tool_choice=tool_choice)
        elif invocation == "ainvoke":
            asyncio.run(model.ainvoke([HumanMessage(content="Read the report.")], tools=tools, tool_choice=tool_choice))
        else:
            model.invoke([HumanMessage(content="Read the report.")], tools=tools, tool_choice=tool_choice)


@pytest.mark.parametrize("override", [{"tools": []}, {"tool_choice": "missing_function"}, {"tool_choice": {"type": "function"}}])
def test_bound_call_revalidates_invocation_overrides(monkeypatch, override):
    monkeypatch.setattr(provider, "load_codex_cli_credential", lambda: CodexCliCredential("fake-token", "fake-account"))
    model = provider.CodexChatModel(retry_max_attempts=1)
    runnable = model.bind_tools([{"name": "read_report"}], tool_choice="required")

    def unexpected_http(**options):
        pytest.fail("Invocation overrides must be validated before creating an HTTP client")

    monkeypatch.setattr(provider.httpx, "Client", unexpected_http)
    with pytest.raises(ValueError, match="tool_choice"):
        runnable.invoke([HumanMessage(content="Read the report.")], **override)


@pytest.mark.parametrize(
    "tools,tool_choice,invocation",
    [(None, None, "invoke"), ([], False, "ainvoke"), ([], "auto", "bound_invoke"), ([], "none", "bound_ainvoke"), ([{"type": "web_search"}], "none", "invoke"), ([{"type": "web_search"}], "auto", "bound_invoke")],
)
def test_no_function_tools_preserves_nonforcing_choices(monkeypatch, tools, tool_choice, invocation):
    monkeypatch.setattr(provider, "load_codex_cli_credential", lambda: CodexCliCredential("fake-token", "fake-account"))
    model = provider.CodexChatModel(retry_max_attempts=1)
    payloads = []
    client_class = httpx.Client

    def handle(request):
        payloads.append(json.loads(request.content))
        event = {"type": "response.completed", "response": {"output": [{"type": "message", "content": [{"type": "output_text", "text": "OK"}]}]}}
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=f"data: {json.dumps(event)}\n\n".encode())

    monkeypatch.setattr(provider.httpx, "Client", lambda **options: client_class(transport=httpx.MockTransport(handle), **options))
    runnable = model.bind_tools(tools or [], tool_choice=tool_choice) if invocation.startswith("bound_") else model
    kwargs = {} if invocation.startswith("bound_") else {"tools": tools, "tool_choice": tool_choice}
    answer = asyncio.run(runnable.ainvoke([HumanMessage(content="Say OK.")], **kwargs)) if invocation.endswith("ainvoke") else runnable.invoke([HumanMessage(content="Say OK.")], **kwargs)
    assert answer.content == "OK"
    assert len(payloads) == 1
    assert not payloads[0].get("tools")
    if tool_choice in ("auto", "none"):
        assert payloads[0]["tool_choice"] == tool_choice
    else:
        assert "tool_choice" not in payloads[0]
