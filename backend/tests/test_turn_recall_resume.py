"""Real worker/checkpoint coverage for query-aware recall on regeneration."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, convert_to_messages
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

from deerflow.agents.middlewares.durable_context_middleware import DurableContextMiddleware
from deerflow.agents.middlewares.dynamic_context_middleware import DynamicContextMiddleware
from deerflow.agents.middlewares.thread_data_middleware import ThreadDataMiddleware
from deerflow.agents.thread_state import get_thread_state_schema, normalize_middleware_state_schemas
from deerflow.extensions.registry import LoadedExtensions
from deerflow.runtime.checkpoint_mode import inject_checkpoint_mode
from deerflow.runtime.checkpoint_state import CheckpointStateAccessor, build_state_mutation_graph
from deerflow.runtime.context_keys import CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY, CURRENT_RUN_RECALL_BOUNDARY_MESSAGE_IDS_KEY
from deerflow.runtime.runs.manager import RunManager
from deerflow.runtime.runs.schemas import RunStatus
from deerflow.runtime.runs.worker import RunContext, run_agent


class _Model(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


class _Observe(AgentMiddleware):
    def __init__(self):
        super().__init__()
        self.calls = []

    async def awrap_model_call(self, request, handler):
        self.calls.append((list(request.messages), dict(request.runtime.context)))
        return await handler(request)


@tool
def task(description: str, subagent_type: str) -> str:
    """Stand in for a completed delegated task without launching a service."""
    return "done"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,stamp_run_id", [("full", True), ("full", False), ("delta", True)])
@pytest.mark.parametrize("turn_number", [1, 3])
async def test_regenerate_recalls_with_separate_boundary_and_preserves_delegations(monkeypatch, mode, stamp_run_id, turn_number):
    from app.gateway.checkpoint_lineage import find_checkpoint_before_message
    from app.gateway.routers.thread_runs import _clean_human_message_for_regenerate

    manager = SimpleNamespace(supports_query_aware_context=True, get_context=Mock(return_value="baseline"), aget_context=AsyncMock(return_value="recalled"))
    monkeypatch.setattr("deerflow.agents.memory.get_memory_manager", lambda: manager)
    app_config = SimpleNamespace(memory=SimpleNamespace(enabled=True, injection_enabled=True, session_injection_enabled=False, turn_injection_enabled=True, backend_config={}))
    checkpointer = InMemorySaver()
    config = {"configurable": {"thread_id": "recall-replay", "checkpoint_ns": ""}}
    schema = get_thread_state_schema(mode)
    seed = CheckpointStateAccessor.bind(build_state_mutation_graph("seed", mode, schema), checkpointer, mode=mode)
    await seed.aupdate(config, {"messages": []}, as_node="seed")

    def build(responses, observer):
        chain = ([ThreadDataMiddleware(lazy_init=True)] if stamp_run_id else []) + [DynamicContextMiddleware(app_config=app_config), observer, DurableContextMiddleware()]
        return create_agent(model=_Model(responses=responses), tools=[task], middleware=normalize_middleware_state_schemas(chain, mode), state_schema=schema, checkpointer=checkpointer)

    # Seed real history, including the first-turn ID swap and older run stamp.
    for turn in range(1, turn_number + 1):
        graph = build([AIMessage(content="old answer", id=f"a{turn}")], _Observe())
        accessor = CheckpointStateAccessor.bind(graph, checkpointer, mode=mode)
        run_config = {"configurable": dict(config["configurable"])}
        inject_checkpoint_mode(run_config, mode)
        await graph.ainvoke(
            {"messages": [HumanMessage(content=f"question {turn}", id=f"m{turn}", additional_kwargs={"run_id": f"old-{turn}"})]}, run_config, context={"thread_id": "recall-replay", "run_id": f"old-{turn}", "user_id": "default"}
        )

    head = await accessor.aget(config)
    original = next(message for message in reversed(head.values["messages"]) if isinstance(message, HumanMessage) and not message.additional_kwargs.get("dynamic_context_reminder"))
    selected = await find_checkpoint_before_message(accessor, head, original.id, max_depth=100)
    source_ids = frozenset(message.id for message in selected.values.get("messages", []))
    head_ids = frozenset(message.id for message in head.values["messages"])
    replayed = convert_to_messages([_clean_human_message_for_regenerate(original)])[0]
    assert replayed.id == f"m{turn_number}"  # Never give regeneration a fresh ID.
    manager.aget_context.reset_mock()
    observer = _Observe()
    graph = build([AIMessage(content="", id="a-new", tool_calls=[{"name": "task", "args": {"description": "work", "subagent_type": "general-purpose"}, "id": "delegated-task"}]), AIMessage(content="new answer", id="a-final")], observer)
    run_manager = RunManager()
    record = await run_manager.create("recall-replay")
    replay_config = {"configurable": {**config["configurable"], "checkpoint_id": selected.config["configurable"]["checkpoint_id"]}}
    bridge = SimpleNamespace(publish=AsyncMock(), publish_end=AsyncMock(), cleanup=AsyncMock())
    await run_agent(
        bridge,
        run_manager,
        record,
        ctx=RunContext(checkpointer=checkpointer, checkpoint_channel_mode=mode, extensions=LoadedExtensions(app_store=None)),
        agent_factory=lambda config: graph,
        graph_input={"messages": [replayed]},
        config=replay_config,
        stream_modes=["values"],
    )

    assert record.status == RunStatus.success, record.error
    assert len(observer.calls) == 2
    for messages, context in observer.calls:
        # The old consumers retain precisely their existing full/delta behavior.
        assert context[CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY] == (head_ids if mode == "full" else source_ids)
        assert context[CURRENT_RUN_RECALL_BOUNDARY_MESSAGE_IDS_KEY] == source_ids
        recalled = [message for message in messages if message.additional_kwargs.get("dynamic_turn_memory")]
        assert len(recalled) == 1
        assert messages[messages.index(recalled[0]) + 1].text == f"question {turn_number}"
    manager.aget_context.assert_awaited_once()
    assert manager.aget_context.await_args.kwargs["query"] == f"question {turn_number}"
    final = await CheckpointStateAccessor.bind(graph, checkpointer, mode=mode).aget(config)
    assert any(entry["id"] == "delegated-task" and entry["run_id"] == record.run_id for entry in final.values["delegations"])
    assert not any(message.additional_kwargs.get("dynamic_turn_memory") for message in final.values["messages"])
    assert CURRENT_RUN_RECALL_BOUNDARY_MESSAGE_IDS_KEY not in replay_config["context"]
