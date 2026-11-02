"""Offline Responses SDK regressions for provider safety termination.

Synthetic HTTP/SSE packets exercise the real adapter; no provider is contacted.
"""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from deerflow.agents.middlewares.safety_finish_reason_middleware import SafetyFinishReasonMiddleware
from deerflow.agents.middlewares.safety_termination_detectors import default_detectors


def _packet(reason="content_filter", arguments="{}", final=False):
    output = (
        [{"type": "message", "id": "msg_final", "role": "assistant", "status": "completed", "content": [{"type": "output_text", "text": "Done.", "annotations": []}]}]
        if final
        else [{"type": "function_call", "id": "fc_probe", "call_id": "call_probe", "name": "record_probe", "arguments": arguments, "status": "incomplete" if reason else "completed"}]
    )
    return {
        "id": "resp_final" if final else "resp_probe",
        "object": "response",
        "created_at": 1700000000,
        "model": "gpt-4.1-mini",
        "status": "incomplete" if reason and not final else "completed",
        "incomplete_details": {"reason": reason} if reason and not final else None,
        "output": output,
        "parallel_tool_calls": True,
        "tools": [],
        "tool_choice": "auto",
    }


@pytest.fixture
def sdk_model():
    clients = []

    def make(*, streaming=False, reason="content_filter", arguments="{}"):
        requests = []

        def transport(request):
            requests.append(json.loads(request.content))
            response = _packet(reason, arguments, final=len(requests) > 1)
            if not streaming:
                return httpx.Response(200, json=response)
            created = {**response, "output": [], "status": "in_progress", "incomplete_details": None}
            events = [{"type": "response.created", "response": created, "sequence_number": 0}]
            if len(requests) == 1:
                events.append({"type": "response.output_item.added", "output_index": 0, "item": response["output"][0], "sequence_number": 1})
            else:
                events.append({"type": "response.output_text.delta", "output_index": 0, "content_index": 0, "item_id": "msg_final", "delta": "Done.", "sequence_number": 1})
            events.append({"type": "response.incomplete" if response["status"] == "incomplete" else "response.completed", "response": response, "sequence_number": 2})
            body = "".join(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events)
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body.encode())

        client = httpx.Client(transport=httpx.MockTransport(transport))
        async_client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
        clients.append((client, async_client))
        return ChatOpenAI(model="gpt-4.1-mini", api_key="offline-placeholder", base_url="https://offline.invalid/v1", use_responses_api=True, http_client=client, http_async_client=async_client, max_retries=0, streaming=streaming), requests

    yield make
    import asyncio

    for client, async_client in clients:
        client.close()
        asyncio.run(async_client.aclose())


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("arguments", ["{}", '{"unfinished":'])
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.asyncio
async def test_sdk_safety_calls_removed_from_replay(sdk_model, streaming, arguments, asynchronous):
    model, requests = sdk_model(streaming=streaming, arguments=arguments)
    original = await model.ainvoke("probe") if asynchronous else model.invoke("probe")
    assert original.response_metadata["incomplete_details"] == {"reason": "content_filter"}
    assert original.tool_calls or original.invalid_tool_calls
    runtime = SimpleNamespace(context={})
    guard = SafetyFinishReasonMiddleware()
    state = {"messages": [original]}
    update = await guard.aafter_model(state, runtime) if asynchronous else guard.after_model(state, runtime)
    assert update is not None
    cleaned = update["messages"][0]
    assert not cleaned.tool_calls and not cleaned.invalid_tool_calls
    assert cleaned.response_metadata == original.response_metadata
    assert original.tool_calls or original.invalid_tool_calls  # no mutation
    assert runtime.context["stop_reason"] == "safety_capped"
    assert cleaned.additional_kwargs["safety_termination"]["suppressed_tool_call_count"] == 1
    history = [HumanMessage(content="probe"), cleaned, HumanMessage(content="continue")]
    if asynchronous:
        await model.ainvoke(history)
    else:
        model.invoke(history)
    assert all(item.get("type") not in ("function_call", "function_call_output") for item in requests[-1]["input"])


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("reason", ["content_filter", None])
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.asyncio
async def test_compiled_agent_suppresses_only_filtered_tool(sdk_model, streaming, reason, asynchronous):
    effects = []

    @tool
    def record_probe() -> str:
        """Record a harmless in-memory marker."""
        effects.append("ran")
        return "recorded"

    model, requests = sdk_model(streaming=streaming, reason=reason)
    graph = create_agent(model, tools=[record_probe], middleware=[SafetyFinishReasonMiddleware()])
    state = {"messages": [HumanMessage(content="probe")]}
    result = await graph.ainvoke(state) if asynchronous else graph.invoke(state)
    assert effects == ([] if reason else ["ran"])
    assert len(requests) == (1 if reason else 2)
    assert not result["messages"][-1].tool_calls


@pytest.mark.parametrize(
    "metadata",
    [
        {},
        {"status": "completed", "incomplete_details": {"reason": "content_filter"}},
        {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}},
        {"status": "incomplete", "incomplete_details": None},
        {"status": "incomplete", "incomplete_details": "content_filter"},
        {"status": "incomplete", "incomplete_details": {"reason": []}},
    ],
)
def test_non_safety_responses_metadata_ignored(metadata):
    message = AIMessage(content="", response_metadata=metadata)
    assert all(detector.detect(message) is None for detector in default_detectors())


@pytest.mark.parametrize("container", ["response_metadata", "additional_kwargs"])
def test_responses_signal_detected_in_one_container(container):
    message = AIMessage(content="", **{container: {"status": "incomplete", "incomplete_details": {"reason": "content_filter"}}})
    hits = [hit for detector in default_detectors() if (hit := detector.detect(message)) is not None]
    assert len(hits) == 1
    assert hits[0].reason_field == "incomplete_details.reason"


def test_responses_signal_not_combined_across_containers():
    message = AIMessage(content="", response_metadata={"status": "incomplete"}, additional_kwargs={"incomplete_details": {"reason": "content_filter"}})
    assert all(detector.detect(message) is None for detector in default_detectors())


@pytest.mark.parametrize("content", ["", "Partial answer"])
def test_filtered_text_keeps_existing_empty_and_visible_behavior(content):
    message = AIMessage(content=content, response_metadata={"status": "incomplete", "incomplete_details": {"reason": "content_filter"}})
    update = SafetyFinishReasonMiddleware().after_model({"messages": [message]}, SimpleNamespace(context={}))
    if content:
        assert update is None
    else:
        assert update is not None
        assert "returned no content" in update["messages"][0].content


@pytest.mark.parametrize("native", [False, True])
def test_invalid_safety_call_with_partial_text_is_suppressed_and_audited(native):
    metadata = {"status": "incomplete", "incomplete_details": {"reason": "content_filter"}} if native else {"finish_reason": "content_filter"}
    message = AIMessage(
        id="msg_probe",
        content=[{"type": "text", "text": "Partial answer"}, {"type": "function_call", "call_id": "call_probe", "name": "record_probe", "arguments": "{"}],
        invalid_tool_calls=[{"name": "record_probe", "id": "call_probe", "args": "{", "error": "truncated"}],
        response_metadata=metadata,
    )
    journal = MagicMock()
    runtime = SimpleNamespace(context={"__run_journal": journal})
    update = SafetyFinishReasonMiddleware().after_model({"messages": [message]}, runtime)
    assert update is not None
    cleaned = update["messages"][0]
    assert cleaned.id == message.id
    assert cleaned.content[0] == message.content[0]
    assert all(block["type"] != "function_call" for block in cleaned.content)
    assert not cleaned.invalid_tool_calls
    changes = journal.record_middleware.call_args.kwargs["changes"]
    assert changes["suppressed_tool_call_count"] == 1
    assert changes["suppressed_tool_call_ids"] == ["call_probe"]
    assert "args" not in json.dumps(changes)
