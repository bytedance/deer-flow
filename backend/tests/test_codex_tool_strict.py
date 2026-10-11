"""Keep caller-supplied function strictness through real Codex HTTP requests."""

from __future__ import annotations

import asyncio
import copy
import json

import httpx
import pytest
from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langchain_core.utils import function_calling

from deerflow.models import openai_codex_provider as provider
from deerflow.models.credential_loader import CodexCliCredential


@pytest.mark.parametrize("shape,binding", [(shape, binding) for shape in ("wrapped", "flat", "bare") for binding in ("direct", "bound")] + [("base_tool", "bound")])
@pytest.mark.parametrize("strict", [True, False, None, "omitted"])
@pytest.mark.parametrize("invocation", ["invoke", "ainvoke"])
def test_function_strictness_survives_tool_followup(monkeypatch, shape, strict, binding, invocation):
    function = {
        "name": "read_report",
        "description": "Read a prepared report.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}, "limit": {"type": ["integer", "null"]}},
            "required": ["query"] if strict is False else ["query", "limit"],
            "additionalProperties": False,
        },
    }
    if strict != "omitted":
        function["strict"] = strict
    if shape == "wrapped":
        definition = {"type": "function", "function": function}
    elif shape == "flat":
        definition = {"type": "function", **function}
    elif shape == "bare":
        definition = function
    else:
        definition = StructuredTool.from_function(lambda query, limit=None: "unused", name=function["name"], description=function["description"], args_schema=function["parameters"])
        convert = function_calling.convert_to_openai_function

        def convert_with_strict(tool):
            converted = convert(tool)
            if "strict" in function:
                converted["strict"] = function["strict"]
            return converted

        if "strict" in function:
            # Exercise a converter-emitted setting without claiming the locked
            # LangChain release currently adds strictness to BaseTool schemas.
            monkeypatch.setattr(function_calling, "convert_to_openai_function", convert_with_strict)
    original_definition = copy.deepcopy(definition)
    expected_tool = {"type": "function", **function}
    if expected_tool.get("strict") is None:
        expected_tool.pop("strict", None)
    arguments = {"query": "quarterly"}
    if strict is not False:
        arguments["limit"] = None

    monkeypatch.setattr(provider, "load_codex_cli_credential", lambda: CodexCliCredential("fake-token", "fake-account"))
    model = provider.CodexChatModel(retry_max_attempts=1)
    runnable = model.bind_tools([definition]) if binding == "bound" else model
    kwargs = {} if binding == "bound" else {"tools": [definition]}
    requests = []
    clients = []
    responses = []
    client_class = httpx.Client

    def handle(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if len(requests) == 1:
            output = [{"type": "function_call", "name": "read_report", "arguments": json.dumps(arguments), "call_id": "call-report"}]
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
        call = runnable.invoke(history, **kwargs)
        followup = [*history, call, ToolMessage(content="Report contents", tool_call_id="call-report")]
        answer = runnable.invoke(followup, **kwargs)
    else:

        async def exchange():
            call = await runnable.ainvoke(history, **kwargs)
            followup = [*history, call, ToolMessage(content="Report contents", tool_call_id="call-report")]
            answer = await runnable.ainvoke(followup, **kwargs)
            return call, followup, answer

        call, followup, answer = asyncio.run(exchange())

    assert call.tool_calls == [{"name": "read_report", "args": arguments, "id": "call-report", "type": "tool_call"}]
    assert answer.content == "Report ready."
    assert len(requests) == 2
    assert all(payload["tools"] == [expected_tool] for payload in requests)
    assert requests[1]["input"][-2:] == [
        {"type": "function_call", "name": "read_report", "arguments": json.dumps(arguments), "call_id": "call-report"},
        {"type": "function_call_output", "call_id": "call-report", "output": "Report contents"},
    ]
    assert definition == original_definition
    assert history == [HumanMessage(content="Read the quarterly report.")]
    assert followup[-1].content == "Report contents"
    assert all(client.is_closed for client in clients)
    assert all(response.is_closed for response in responses)
