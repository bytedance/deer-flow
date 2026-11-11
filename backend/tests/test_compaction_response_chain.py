"""Compaction must reach the next Responses request as a fresh local history."""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
from langchain.agents.middleware.types import ModelRequest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_openai import ChatOpenAI
from langgraph.graph.message import add_messages

from deerflow.agents.middlewares.durable_context_middleware import DurableContextMiddleware
from deerflow.agents.middlewares.summarization_middleware import DeerFlowSummarizationMiddleware, SummaryGenerationError

_SUMMARY = "COMPACTED_SUMMARY_SENTINEL"


class _SummaryModel(BaseChatModel):
    fail: bool = False
    calls: int = 0

    @property
    def _llm_type(self) -> str:
        return "offline-compaction-summary"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls += 1
        if self.fail:
            raise RuntimeError("offline summary failure")
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=_SUMMARY))])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def _history():
    return [
        HumanMessage(content="obsolete request", id="old-user"),
        AIMessage(content="obsolete answer", id="old-ai", response_metadata={"id": "resp_old"}),
        HumanMessage(content="read the report", id="current-user"),
        AIMessage(
            content=[
                {"type": "reasoning", "id": "rs_report", "summary": [{"type": "summary_text", "text": "Need to read the report"}]},
                {"type": "function_call", "id": "fc_report", "call_id": "call_report", "name": "read_report", "arguments": "{}", "status": "completed"},
            ],
            id="tool-ai",
            tool_calls=[{"name": "read_report", "args": {}, "id": "call_report", "type": "tool_call"}],
            response_metadata={"id": "resp_tool", "model_name": "gpt-4.1", "token_usage": {"total_tokens": 12}},
            additional_kwargs={"audit_marker": "keep-me"},
        ),
        ToolMessage(content="report contents", tool_call_id="call_report", id="tool-result"),
        AIMessage(
            content=[{"type": "text", "text": "recent work", "id": "msg_recent", "annotations": []}],
            id="recent-ai",
            response_metadata={"id": "resp_recent", "model_name": "gpt-4.1"},
        ),
        HumanMessage(content="continue", id="next-user"),
    ]


def _payload(state, runtime, model):
    request = ModelRequest(model=model, messages=state["messages"], state=state, runtime=runtime)
    return DurableContextMiddleware().wrap_model_call(request, lambda injected: model._get_request_payload(injected.messages))


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("manual", [False, True], ids=["automatic", "manual"])
async def test_compaction_starts_a_fresh_responses_history(asynchronous, manual):
    messages = _history()
    originals = [message.model_dump() for message in messages]
    state = {"messages": messages}
    runtime = SimpleNamespace(context={"thread_id": "offline-thread", "user_id": "offline-user"})
    middleware = DeerFlowSummarizationMiddleware(model=_SummaryModel(), trigger=("messages", 100 if manual else 6), keep=("messages", 5), token_counter=len)

    if manual:
        compact = middleware.acompact_state if asynchronous else middleware.compact_state
        result = compact(state, runtime, force=True, raise_on_failure=True)
        if asynchronous:
            result = await result
        assert result is not None
        compacted = {"messages": list(result.preserved_messages), "summary_text": result.summary_text}
    else:
        result = await middleware.abefore_model(state, runtime) if asynchronous else middleware.before_model(state, runtime)
        assert result is not None
        compacted = {**state, **result, "messages": add_messages(messages, result["messages"])}

    model = ChatOpenAI(model="gpt-4.1", api_key="offline-test", use_responses_api=True, use_previous_response_id=True)
    payload = _payload(compacted, runtime, model)

    assert "previous_response_id" not in payload
    serialized = json.dumps(payload["input"])
    assert _SUMMARY in serialized
    assert "recent work" in serialized
    assert "report contents" in serialized
    assert "call_report" in serialized
    assert {item.get("id") for item in payload["input"]} >= {"rs_report", "fc_report", "msg_recent"}
    assert "obsolete" not in serialized
    assert [message.model_dump() for message in messages] == originals
    assert [message.id for message in compacted["messages"]] == [message.id for message in messages[2:]]
    for original, preserved in zip(messages[2:], compacted["messages"], strict=True):
        expected = original.model_dump()
        if isinstance(original, AIMessage):
            expected["response_metadata"].pop("id")
        assert preserved.model_dump() == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("reason", ["below-threshold", "nothing-to-summarize", "generation-failed"])
async def test_unsuccessful_compaction_preserves_the_response_chain(asynchronous, reason):
    messages = _history()
    originals = [message.model_dump() for message in messages]
    state = {"messages": messages, "summary_text": "previous summary"}
    runtime = SimpleNamespace(context={})
    summary_model = _SummaryModel(fail=reason == "generation-failed")
    middleware = DeerFlowSummarizationMiddleware(
        model=summary_model,
        trigger=("messages", 100 if reason == "below-threshold" else 6),
        keep=("messages", len(messages) if reason == "nothing-to-summarize" else 5),
        token_counter=len,
    )

    result = await middleware.abefore_model(state, runtime) if asynchronous else middleware.before_model(state, runtime)

    assert result is None
    assert bool(summary_model.calls) is (reason == "generation-failed")
    assert state["summary_text"] == "previous summary"
    assert [message.model_dump() for message in messages] == originals
    model = ChatOpenAI(model="gpt-4.1", api_key="offline-test", use_responses_api=True, use_previous_response_id=True)
    assert _payload(state, runtime, model)["previous_response_id"] == "resp_recent"


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
async def test_failed_manual_compaction_leaves_original_messages_unchanged(asynchronous):
    messages = _history()
    originals = [message.model_dump() for message in messages]
    summary_model = _SummaryModel(fail=True)
    middleware = DeerFlowSummarizationMiddleware(model=summary_model, trigger=("messages", 100), keep=("messages", 5), token_counter=len)

    with pytest.raises(SummaryGenerationError):
        if asynchronous:
            await middleware.acompact_state({"messages": messages}, SimpleNamespace(context={}), force=True, raise_on_failure=True)
        else:
            middleware.compact_state({"messages": messages}, SimpleNamespace(context={}), force=True, raise_on_failure=True)

    assert summary_model.calls > 0
    assert [message.model_dump() for message in messages] == originals


@pytest.mark.parametrize("responses_api", [False, True], ids=["chat-completions", "responses-without-chaining"])
def test_compaction_keeps_non_response_metadata_and_other_request_modes(responses_api):
    messages = [
        HumanMessage(content="old question", id="old-user"),
        AIMessage(content="old answer", id="old-ai"),
        HumanMessage(content="current question", id="current-user"),
        AIMessage(content="recent answer", id="recent-ai", response_metadata={"id": "chatcmpl_recent", "model_name": "test-model"}),
    ]
    originals = [message.model_dump() for message in messages]
    runtime = SimpleNamespace(context={})
    middleware = DeerFlowSummarizationMiddleware(model=_SummaryModel(), trigger=("messages", 4), keep=("messages", 2), token_counter=len)
    result = middleware.before_model({"messages": messages}, runtime)
    assert result is not None
    compacted = {**result, "messages": add_messages(messages, result["messages"])}
    model = ChatOpenAI(model="gpt-4.1", api_key="offline-test", use_responses_api=responses_api, use_previous_response_id=False)

    payload = _payload(compacted, runtime, model)

    assert "previous_response_id" not in payload
    assert _SUMMARY in json.dumps(payload["input" if responses_api else "messages"])
    assert compacted["messages"][-1].response_metadata == originals[-1]["response_metadata"]
    assert [message.model_dump() for message in messages] == originals


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
async def test_reusing_an_unchanged_summary_still_starts_a_fresh_response_chain(asynchronous):
    state = {"messages": _history(), "summary_text": _SUMMARY}
    runtime = SimpleNamespace(context={})
    summary_model = _SummaryModel()
    middleware = DeerFlowSummarizationMiddleware(model=summary_model, trigger=("messages", 6), keep=("messages", 5), token_counter=len)
    model = ChatOpenAI(model="gpt-4.1", api_key="offline-test", use_responses_api=True, use_previous_response_id=True)

    # The first identical result populates the no-op cache. The second call
    # reuses the summary but still removes source history from the checkpoint.
    for _ in range(2):
        result = await middleware.abefore_model(state, runtime) if asynchronous else middleware.before_model(state, runtime)
        assert result is not None
        compacted = {**result, "messages": add_messages(state["messages"], result["messages"])}
        assert result["summary_text"] == _SUMMARY
        assert len(compacted["messages"]) < len(state["messages"])
        assert "previous_response_id" not in _payload(compacted, runtime, model)

    assert summary_model.calls == 1


def test_sdk_sends_compacted_context_then_resumes_chaining_on_the_new_response():
    requests = []

    def transport(request):
        assert request.url.path == "/v1/responses"
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "resp_compacted",
                "object": "response",
                "created_at": 0,
                "model": "gpt-4.1",
                "status": "completed",
                "error": None,
                "output": [{"type": "message", "id": "msg_reply", "status": "completed", "role": "assistant", "content": [{"type": "output_text", "text": "done", "annotations": []}]}],
                "usage": None,
            },
        )

    runtime = SimpleNamespace(context={})
    messages = _history()
    middleware = DeerFlowSummarizationMiddleware(model=_SummaryModel(), trigger=("messages", 6), keep=("messages", 5), token_counter=len)
    result = middleware.before_model({"messages": messages}, runtime)
    assert result is not None
    state = {**result, "messages": add_messages(messages, result["messages"])}

    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        model = ChatOpenAI(model="gpt-4.1", api_key="offline-test", base_url="https://offline.invalid/v1", use_responses_api=True, use_previous_response_id=True, http_client=client, max_retries=0)
        request = ModelRequest(model=model, messages=state["messages"], state=state, runtime=runtime)
        response = DurableContextMiddleware().wrap_model_call(request, lambda injected: model.invoke(injected.messages))
        continued = {**state, "messages": add_messages(state["messages"], [response, HumanMessage(content="next turn")])}
        request = ModelRequest(model=model, messages=continued["messages"], state=continued, runtime=runtime)
        DurableContextMiddleware().wrap_model_call(request, lambda injected: model.invoke(injected.messages))

    assert len(requests) == 2
    assert "previous_response_id" not in requests[0]
    assert _SUMMARY in json.dumps(requests[0]["input"])
    assert "report contents" in json.dumps(requests[0]["input"])
    assert requests[1]["previous_response_id"] == "resp_compacted"
    assert requests[1]["input"] == [{"type": "message", "role": "user", "content": "next turn"}]
