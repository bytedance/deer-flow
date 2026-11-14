"""Durable snapshots and hidden updates across real middleware/replay boundaries."""

import asyncio
from copy import deepcopy

import pytest
from _agent_e2e_helpers import FakeToolCallingModel
from fastapi import HTTPException
from langchain.agents import create_agent
from langchain.agents.middleware.types import ExtendedModelResponse, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from deerflow.agents.middlewares.durable_context_middleware import DurableContextMiddleware
from deerflow.agents.middlewares.llm_error_handling_middleware import LLMErrorHandlingMiddleware
from deerflow.agents.middlewares.model_response import last_ai_message
from deerflow.agents.middlewares.pii_redaction_middleware import PiiRedactionMiddleware, redact_text
from deerflow.agents.thread_state import ThreadState
from deerflow.config.app_config import AppConfig, LlmCallConfig
from deerflow.config.pii_redaction_config import PiiRedactionConfig
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.runtime.context_keys import CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY
from deerflow.runtime.serialization import serialize


class RecordingModel(FakeToolCallingModel):
    received: list[list] = []

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.received.append(list(messages))
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def _request_view(messages):
    return [(message.type, message.content) for message in messages]


@pytest.mark.parametrize("async_call", [False, True], ids=["sync", "async"])
def test_valid_snapshot_response_survives_the_error_handling_wrapper(async_call):
    model = RecordingModel(responses=[AIMessage(content="valid model reply")] * 3)
    app_config = AppConfig(sandbox=SandboxConfig(use="test"), llm_call=LlmCallConfig(retry_max_attempts=2, retry_base_delay_ms=1, retry_cap_delay_ms=1))
    agent = create_agent(
        model=model,
        tools=[],
        middleware=[LLMErrorHandlingMiddleware(app_config=app_config), DurableContextMiddleware()],
        state_schema=ThreadState,
    )
    inputs = {"messages": [HumanMessage(content="continue")], "summary_text": "existing summary"}

    result = asyncio.run(agent.ainvoke(inputs)) if async_call else agent.invoke(inputs)

    assert result["messages"][-1].content == "valid model reply"
    assert len(model.received) == 1
    assert "existing summary" in result["durable_context_snapshot"]["content"]


@pytest.mark.parametrize("messages", [[AIMessage(content="reply")], [AIMessage(content="earlier"), HumanMessage(content="hidden"), AIMessage(content="latest")]])
def test_last_ai_message_reads_the_extended_response_without_losing_its_command(messages):
    response = ExtendedModelResponse(model_response=ModelResponse(result=messages), command=Command(update={"durable_context_snapshot": {"content": "snapshot"}}))

    assert last_ai_message(response) is messages[-1]
    assert response.command.update["durable_context_snapshot"] == {"content": "snapshot"}


@pytest.mark.parametrize("history_blocks", [False, True], ids=["text", "content-blocks"])
@pytest.mark.parametrize("old_policy_enabled", [False, True], ids=["enable-policy", "enable-detector"])
def test_policy_change_redacts_the_frozen_snapshot_and_persisted_updates(old_policy_enabled, history_blocks):
    config = {"configurable": {"thread_id": "durable-policy-transition"}}
    saver = InMemorySaver()
    old_policy = PiiRedactionConfig(enabled=old_policy_enabled, redact_email=False, token_secret="synthetic-redaction-test-key")
    before_model = RecordingModel(responses=[AIMessage(content="saved reply")] * 2)
    old_agent = create_agent(model=before_model, tools=[], middleware=[DurableContextMiddleware(pii_redaction_config=old_policy)], state_schema=ThreadState, checkpointer=saver)
    old_agent.invoke({"messages": [HumanMessage(content="first")], "summary_text": "contact alpha.person@example.test"}, config)
    old_agent.invoke({"messages": [HumanMessage(content="second")], "summary_text": "contact beta.person@example.test"}, config)
    if history_blocks:
        history = old_agent.get_state(config).values["messages"]
        old_agent.update_state(config, {"messages": [message.model_copy(update={"content": [{"type": "text", "text": message.content}]}) for message in history if message.additional_kwargs.get("durable_context_data")]})
    saved = old_agent.get_state(config).values
    snapshot = deepcopy(saved["durable_context_snapshot"])
    old_updates = {message.id: message.content for message in saved["messages"] if message.additional_kwargs.get("durable_context_data")}
    assert old_updates and "alpha.person@example.test" in snapshot["content"]
    assert any("beta.person@example.test" in str(content) for content in old_updates.values())

    policy = PiiRedactionConfig(enabled=True, token_secret="synthetic-redaction-test-key")
    model = RecordingModel(responses=[AIMessage(content="safe reply")] * 2)
    agent = create_agent(model=model, tools=[], middleware=[PiiRedactionMiddleware(policy), DurableContextMiddleware(pii_redaction_config=policy)], state_schema=ThreadState, checkpointer=saver)
    result = agent.invoke({"messages": [HumanMessage(content="resume safely")]}, config)

    visible = "\n".join(str(message.content) for message in model.received[-1])
    assert "alpha.person@example.test" not in visible
    assert "beta.person@example.test" not in visible
    assert redact_text("alpha.person@example.test", policy) in visible
    assert redact_text("beta.person@example.test", policy) in visible
    assert result["durable_context_snapshot"] == snapshot
    assert {message.id: message.content for message in result["messages"] if message.id in old_updates} == old_updates

    agent.invoke({"messages": [HumanMessage(content="same policy")]}, config)
    previous, current = map(_request_view, model.received[-2:])
    assert current[: len(previous)] == previous


@pytest.mark.parametrize(
    "snapshot",
    [
        {},
        {"content": [], "sections": {}},
        {"content": "invalid checkpoint", "sections": []},
        {"content": "invalid checkpoint", "sections": {"summary": 7}},
        {"content": False, "sections": {}},
    ],
)
def test_malformed_restored_snapshot_is_rebuilt_from_current_state(snapshot):
    model = RecordingModel(responses=[AIMessage(content="recovered reply")])
    agent = create_agent(model=model, tools=[], middleware=[DurableContextMiddleware()], state_schema=ThreadState)

    result = agent.invoke({"messages": [HumanMessage(content="resume")], "summary_text": "current durable summary", "durable_context_snapshot": snapshot})

    assert result["messages"][-1].content == "recovered reply"
    rebuilt = result["durable_context_snapshot"]
    assert isinstance(rebuilt["content"], str)
    assert "current durable summary" in rebuilt["content"]
    assert isinstance(rebuilt["sections"], dict)
    assert all(isinstance(value, str) for value in rebuilt["sections"].values())
    assert not any("invalid checkpoint" in str(message.content) for message in model.received[-1])


@pytest.mark.parametrize("boundary", ["run", "state"])
def test_external_writers_cannot_set_the_durable_snapshot(boundary):
    from app.gateway.services import normalize_input, strip_server_owned_state_metadata

    transform = normalize_input if boundary == "run" else strip_server_owned_state_metadata
    with pytest.raises(HTTPException) as error:
        transform({"durable_context_snapshot": {"content": "synthetic caller data", "sections": {}}})

    assert error.value.status_code == 400
    assert "durable_context_snapshot" in error.value.detail
    assert "synthetic caller data" not in error.value.detail


def test_a_resumed_run_does_not_treat_its_hidden_update_as_a_new_user_turn():
    model = RecordingModel(responses=[AIMessage(content="first reply", id="reply-1"), AIMessage(content="resumed reply", id="reply-2")])
    agent = create_agent(model=model, tools=[], middleware=[DurableContextMiddleware()], state_schema=ThreadState, checkpointer=InMemorySaver(), context_schema=dict)
    config = {"configurable": {"thread_id": "durable-resume"}}
    delegation = {"id": "old-call", "run_id": "original-run", "description": "still active", "subagent_type": "general-purpose", "status": "in_progress", "created_at": "2026-11-12T00:00:00Z"}
    agent.invoke({"messages": [HumanMessage(content="original request", id="user-1", additional_kwargs={"run_id": "original-run"})], "delegations": [delegation]}, config, context={"run_id": "original-run"})
    agent.update_state(config, {"summary_text": "new checkpoint observation"})
    previous = agent.get_state(config).values
    context = {"run_id": "resumed-run", CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY: frozenset(message.id for message in previous["messages"])}

    result = agent.invoke({"messages": []}, config, context=context)

    assert any(message.additional_kwargs.get("durable_context_data") for message in result["messages"])
    assert result["delegations"][0]["status"] == "in_progress"
    assert result["delegations"][0]["run_id"] == "original-run"


@pytest.mark.parametrize("node", ["model", "DurableContextMiddleware.before_model"])
def test_updates_stream_filters_internal_channels_only_at_the_node_boundary(node):
    raw = {
        node: {"durable_context_snapshot": {"content": "checkpoint-only"}, "summary_text": "public summary", "payload": {"durable_context_snapshot": "ordinary application data"}, "messages": [AIMessage(content="public reply")]},
        "__interrupt__": ({"value": "approve", "id": "pause"},),
    }
    original = deepcopy(raw)

    result = serialize(raw, mode="updates")

    assert "durable_context_snapshot" not in result[node]
    assert result[node]["summary_text"] == "public summary"
    assert result[node]["payload"]["durable_context_snapshot"] == "ordinary application data"
    assert result[node]["messages"][0]["content"] == "public reply"
    assert result["__interrupt__"] == [{"value": "approve", "id": "pause"}]
    assert raw == original
