"""Length caps through real Responses serialization and Agent tool execution."""

import json
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, message_chunk_to_message
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver

from deerflow.agents.middlewares.model_length_finish_reason_middleware import (
    MODEL_LENGTH_CAPPED_STOP_REASON,
    ModelLengthFinishReasonMiddleware,
)


def _response(*, arguments="{}", status="incomplete", reason="max_output_tokens", final=False):
    output = (
        [{"type": "message", "id": "msg-final", "role": "assistant", "status": "completed", "content": [{"type": "output_text", "text": "Finished.", "annotations": []}]}]
        if final
        else [
            {"type": "reasoning", "id": "rs-length", "summary": [{"type": "summary_text", "text": "Preparing the result."}]},
            {"type": "function_call", "id": "fc-length", "call_id": "call-length", "name": "record_write", "arguments": arguments, "status": status},
        ]
    )
    return {
        "id": "resp-final" if final else "resp-length",
        "object": "response",
        "created_at": 1,
        "model": "gpt-6",
        "status": "completed" if final else status,
        "error": None,
        "incomplete_details": None if final or reason is None else {"reason": reason},
        "output": output,
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
        "usage": {"input_tokens": 10, "input_tokens_details": {"cached_tokens": 0}, "output_tokens": 8, "output_tokens_details": {"reasoning_tokens": 2}, "total_tokens": 18},
    }


@pytest.fixture
def responses_transport():
    requests = []
    state = SimpleNamespace(arguments="{}", status="incomplete", reason="max_output_tokens")

    def send(request):
        body = json.loads(request.content)
        requests.append(body)
        assert request.url.path == "/v1/responses"
        input_items = body["input"]
        pending = {item["call_id"] for item in input_items if item.get("type") == "function_call"}
        answered = {item["call_id"] for item in input_items if item.get("type") == "function_call_output"}
        if pending - answered:
            return httpx.Response(400, json={"error": {"message": "No tool output found for function call call-length", "type": "invalid_request_error"}})
        payload = _response(arguments=state.arguments, status=state.status, reason=state.reason, final=len(requests) > 1)
        if body.get("stream"):
            events = [{"type": "response.created", "response": {**payload, "status": "in_progress", "incomplete_details": None, "output": [], "usage": None}}]
            for index, item in enumerate(payload["output"]):
                added = {**item, "arguments": ""} if item["type"] == "function_call" else item
                events.append({"type": "response.output_item.added", "output_index": index, "item": added})
                if item["type"] == "function_call":
                    events.append({"type": "response.function_call_arguments.delta", "output_index": index, "item_id": item["id"], "delta": item["arguments"]})
                elif item["type"] == "message":
                    events.append({"type": "response.output_text.delta", "output_index": index, "content_index": 0, "item_id": item["id"], "delta": item["content"][0]["text"]})
                events.append({"type": "response.output_item.done", "output_index": index, "item": item})
            events.append({"type": "response.completed" if payload["status"] == "completed" else "response.incomplete", "response": payload})
            for sequence_number, event in enumerate(events):
                event["sequence_number"] = sequence_number
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content="".join(f"data: {json.dumps(event)}\n\n" for event in events))
        return httpx.Response(200, json=payload)

    return httpx.MockTransport(send), requests, state


@pytest.fixture
def responses_provider(responses_transport):
    transport, requests, state = responses_transport
    with httpx.Client(transport=transport) as http:
        model = ChatOpenAI(model="gpt-6", api_key="offline-not-a-key", use_responses_api=True, http_client=http, max_retries=0, max_tokens=8)
        yield model, requests, state


@pytest_asyncio.fixture
async def async_responses_provider(responses_transport):
    transport, requests, state = responses_transport
    with httpx.Client(transport=transport) as http:
        async with httpx.AsyncClient(transport=transport) as async_http:
            model = ChatOpenAI(model="gpt-6", api_key="offline-not-a-key", use_responses_api=True, http_client=http, http_async_client=async_http, max_retries=0, max_tokens=8)
            yield model, requests, state


def _message(model, streaming):
    if not streaming:
        return model.invoke([HumanMessage("Save the result.")])
    collected = None
    for chunk in model.stream([HumanMessage("Save the result.")]):
        collected = chunk if collected is None else collected + chunk
    assert collected is not None
    return message_chunk_to_message(collected)


@pytest.mark.parametrize("streaming", [False, True])
def test_native_responses_length_signal_stops_tool_calls(responses_provider, streaming):
    model, requests, _ = responses_provider
    message = _message(model, streaming)
    assert message.response_metadata["status"] == "incomplete"
    assert message.response_metadata["incomplete_details"] == {"reason": "max_output_tokens"}
    assert message.tool_calls
    assert "finish_reason" not in message.response_metadata
    context = {}
    update = ModelLengthFinishReasonMiddleware().after_model({"messages": [message]}, SimpleNamespace(context=context))
    assert update is not None
    assert context["stop_reason"] == MODEL_LENGTH_CAPPED_STOP_REASON
    replacement = update["messages"][0]
    assert replacement.tool_calls == []
    assert replacement.invalid_tool_calls == []
    assert len(requests) == 1


@pytest.mark.parametrize("streaming", [False, True])
def test_responses_length_cap_prevents_agent_write_and_keeps_history_replayable(responses_provider, streaming):
    model, requests, _ = responses_provider
    model.streaming = streaming
    writes = []

    @tool
    def record_write() -> str:
        """Record one observable write."""
        writes.append("written")
        return "Saved."

    graph = create_agent(model, [record_write], middleware=[ModelLengthFinishReasonMiddleware()], checkpointer=InMemorySaver())
    context = {"thread_id": "length-regression", "run_id": "length-run"}
    config = {"configurable": {"thread_id": "length-regression"}}
    result = graph.invoke({"messages": [HumanMessage("Save the result.")]}, config=config, context=context)
    assert writes == [], "A length-capped provider response must not execute its tool call"
    assert context["stop_reason"] == MODEL_LENGTH_CAPPED_STOP_REASON
    assert result["messages"][-1].additional_kwargs["model_length_termination"]["suppressed_tool_call_count"] == 1
    assert len(requests) == 1
    graph.invoke({"messages": [HumanMessage("Continue with a new turn.")]}, config=config, context={})
    assert len(requests) == 2
    assert not any(item.get("type") in ("function_call", "function_call_output") for item in requests[-1]["input"])
    assert writes == []


@pytest.mark.parametrize("arguments", ["{}", '{"value":'])
@pytest.mark.parametrize("streaming", [False, True])
def test_length_cleanup_removes_native_frames_before_next_responses_request(responses_provider, arguments, streaming):
    model, requests, state = responses_provider
    state.arguments = arguments
    message = _message(model, streaming)
    # Isolate cleanup independently of the missing native detector. A provider
    # adapter may also expose the established Chat Completions length spelling.
    message = message.model_copy(update={"response_metadata": {**message.response_metadata, "finish_reason": "length"}})
    original = message.model_dump()
    update = ModelLengthFinishReasonMiddleware().after_model({"messages": [message]}, SimpleNamespace(context={}))
    assert update is not None
    replacement = update["messages"][0]
    assert replacement.tool_calls == []
    assert replacement.invalid_tool_calls == []
    final = model.invoke([HumanMessage("Save the result."), replacement, HumanMessage("Continue.")])
    assert final.text == "Finished."
    assert not any(item.get("type") == "function_call" for item in requests[-1]["input"])
    assert message.model_dump() == original
    assert any(block.get("type") == "reasoning" for block in replacement.content)


@pytest.mark.parametrize(
    "metadata",
    [
        {"status": "completed", "incomplete_details": {"reason": "max_output_tokens"}},
        {"status": "incomplete", "incomplete_details": {"reason": "content_filter"}},
        {"status": "in_progress", "incomplete_details": {"reason": "max_output_tokens"}},
        {"status": "incomplete"},
        {"incomplete_details": {"reason": "max_output_tokens"}},
        {"status": "incomplete", "incomplete_details": None},
        {"status": "incomplete", "incomplete_details": "max_output_tokens"},
        {"status": "incomplete", "incomplete_details": {"reason": ["max_output_tokens"]}},
        {"status": ["incomplete"], "incomplete_details": {"reason": "max_output_tokens"}},
        {"status": "incomplete", "incomplete_details": []},
        {"status": "incomplete", "incomplete_details": {"reason": "MAX_OUTPUT_TOKENS"}},
    ],
)
def test_other_responses_statuses_do_not_become_length_caps(metadata):
    message = AIMessage(content="Ordinary answer.", response_metadata=metadata)
    context = {}
    assert ModelLengthFinishReasonMiddleware().after_model({"messages": [message]}, SimpleNamespace(context=context)) is None
    assert "stop_reason" not in context


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
async def test_async_responses_length_signal_stops_tool_calls(async_responses_provider, streaming):
    model, requests, _ = async_responses_provider
    if streaming:
        collected = None
        async for chunk in model.astream([HumanMessage("Save the result.")]):
            collected = chunk if collected is None else collected + chunk
        assert collected is not None
        message = message_chunk_to_message(collected)
    else:
        message = await model.ainvoke([HumanMessage("Save the result.")])
    assert message.tool_calls
    assert message.response_metadata["status"] == "incomplete"
    context = {}
    update = await ModelLengthFinishReasonMiddleware().aafter_model({"messages": [message]}, SimpleNamespace(context=context))
    assert update is not None
    assert update["messages"][0].tool_calls == []
    assert context["stop_reason"] == MODEL_LENGTH_CAPPED_STOP_REASON
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
async def test_async_capped_agent_does_not_write_and_resumes_from_checkpoint(async_responses_provider, streaming):
    model, requests, _ = async_responses_provider
    model.streaming = streaming
    writes = []

    @tool
    async def record_write() -> str:
        """Record one observable write."""
        writes.append("written")
        return "Saved."

    graph = create_agent(model, [record_write], middleware=[ModelLengthFinishReasonMiddleware()], checkpointer=InMemorySaver())
    context = {"thread_id": "async-length-regression", "run_id": "async-length-run"}
    config = {"configurable": {"thread_id": "async-length-regression"}}
    result = await graph.ainvoke({"messages": [HumanMessage("Save the result.")]}, config=config, context=context)
    assert writes == []
    assert context["stop_reason"] == MODEL_LENGTH_CAPPED_STOP_REASON
    assert result["messages"][-1].additional_kwargs["model_length_termination"]["suppressed_tool_call_names"] == ["record_write"]
    assert len(requests) == 1
    continued = await graph.ainvoke({"messages": [HumanMessage("Continue.")]}, config=config, context={})
    assert continued["messages"][-1].text == "Finished."
    assert len(requests) == 2
    assert not any(item.get("type") in ("function_call", "function_call_output") for item in requests[-1]["input"])
    assert writes == []


@pytest.mark.parametrize("streaming", [False, True])
def test_completed_responses_agent_executes_tool_normally(responses_provider, streaming):
    model, requests, state = responses_provider
    state.status, state.reason = "completed", None
    model.streaming = streaming
    writes = []

    @tool
    def record_write() -> str:
        """Record one observable write."""
        writes.append("written")
        return "Saved."

    context = {}
    graph = create_agent(model, [record_write], middleware=[ModelLengthFinishReasonMiddleware()])
    result = graph.invoke({"messages": [HumanMessage("Save the result.")]}, context=context)
    assert writes == ["written"]
    assert result["messages"][-1].text == "Finished."
    assert len(requests) == 2
    assert "stop_reason" not in context
    assert any(item.get("type") == "function_call_output" for item in requests[-1]["input"])


@pytest.mark.parametrize("container", ["response_metadata", "additional_kwargs"])
@pytest.mark.parametrize("content", ["Partial answer.", [{"type": "reasoning", "id": "rs-capped", "summary": []}]])
def test_native_length_cap_preserves_content_metadata_and_earlier_stop_reason(container, content):
    metadata = {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}}
    message = AIMessage(content=content, **{container: metadata})
    original = message.model_dump()
    context = {"stop_reason": "token_capped"}
    middleware = ModelLengthFinishReasonMiddleware()
    update = middleware.after_model({"messages": [message]}, SimpleNamespace(context=context))
    assert context["stop_reason"] == "token_capped"
    if isinstance(content, str):
        assert update is None
    else:
        assert update is not None
        replacement = update["messages"][0]
        assert replacement.content[0] == content[0]
        assert "output limit" in replacement.content[-1]["text"]
        assert getattr(replacement, container)["incomplete_details"] == metadata["incomplete_details"]
        assert middleware.after_model({"messages": [replacement]}, SimpleNamespace(context=context)) is None
    assert message.model_dump() == original
    fresh_context = {}
    middleware.after_model({"messages": [message]}, SimpleNamespace(context=fresh_context))
    assert fresh_context["stop_reason"] == MODEL_LENGTH_CAPPED_STOP_REASON


@pytest.mark.parametrize("swap", [False, True])
def test_responses_detector_does_not_combine_unrelated_metadata_containers(swap):
    status = {"status": "incomplete"}
    details = {"incomplete_details": {"reason": "max_output_tokens"}}
    message = AIMessage(content="Ordinary answer.", response_metadata=details if swap else status, additional_kwargs=status if swap else details)
    context = {}
    assert ModelLengthFinishReasonMiddleware().after_model({"messages": [message]}, SimpleNamespace(context=context)) is None
    assert "stop_reason" not in context


@pytest.mark.parametrize("block_type", ["function_call", "custom_tool_call", "tool_call", "tool_call_chunk", "tool_use"])
@pytest.mark.parametrize("surface", ["content_only", "invalid", "raw"])
def test_length_cleanup_clears_every_tool_surface_and_preserves_non_call_blocks(block_type, surface):
    call = {"type": block_type, "id": "call-capped", "call_id": "call-capped", "name": "record_write", "arguments": "{}", "input": {}}
    kept = [{"type": "reasoning", "id": "rs-capped", "summary": []}, {"type": "text", "text": "Partial answer."}, {"type": [], "text": "Malformed type."}]
    message = AIMessage(
        id="msg-capped",
        content=[*kept, call],
        response_metadata={"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}, "model_provider": "openai"},
        additional_kwargs={"kept": "metadata"},
        usage_metadata={"input_tokens": 10, "output_tokens": 8, "total_tokens": 18},
    )
    if surface == "invalid":
        message.invalid_tool_calls = [{"type": "invalid_tool_call", "id": "call-capped", "name": "record_write", "args": "{", "error": "Incomplete JSON"}]
    elif surface == "raw":
        message = message.model_copy(
            update={"additional_kwargs": {"kept": "metadata", "tool_calls": [{"id": "call-capped", "function": {"name": "record_write", "arguments": "{"}}], "function_call": {"name": "record_write", "arguments": "{"}}}
        )
    original = message.model_dump()
    middleware = ModelLengthFinishReasonMiddleware()
    update = middleware.after_model({"messages": [message]}, SimpleNamespace(context={}))
    assert update is not None
    replacement = update["messages"][0]
    assert replacement.content[:-1] == kept
    assert "output limit" in replacement.content[-1]["text"]
    assert replacement.tool_calls == replacement.invalid_tool_calls == []
    assert "tool_calls" not in replacement.additional_kwargs
    assert "function_call" not in replacement.additional_kwargs
    assert replacement.additional_kwargs["kept"] == "metadata"
    assert replacement.additional_kwargs["model_length_termination"]["suppressed_tool_call_names"] == ["record_write"]
    assert replacement.response_metadata == message.response_metadata
    assert replacement.usage_metadata == message.usage_metadata
    assert replacement.id == message.id
    assert message.model_dump() == original
    assert middleware.after_model({"messages": [replacement]}, SimpleNamespace(context={})) is None
    completed = message.model_copy(update={"response_metadata": {"status": "completed"}})
    assert middleware.after_model({"messages": [completed]}, SimpleNamespace(context={})) is None
