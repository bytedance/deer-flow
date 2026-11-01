"""Tool invocation identity survives provider ID reuse and graph serialization."""

from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, LLMResult
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import Command

from deerflow.agents.thread_state import get_thread_state_schema
from deerflow.runtime.checkpoint_state import CheckpointStateAccessor
from deerflow.runtime.events.message_identity import message_identity
from deerflow.runtime.events.message_seq import stamp_messages_with_seq
from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.journal import RunJournal


def test_idless_legacy_results_do_not_claim_a_shared_identity():
    assert message_identity({"type": "tool", "tool_call_id": "call_0"}) is None


@pytest.mark.anyio
@pytest.mark.parametrize("backend", ["memory", "jsonl", "db"])
@pytest.mark.parametrize("second_run", ["run-a", "run-b"])
async def test_reused_provider_ids_keep_distinct_seqs(backend, second_run, tmp_path):
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
    from deerflow.runtime.events.store.db import DbRunEventStore
    from deerflow.runtime.events.store.jsonl import JsonlRunEventStore

    if backend == "db":
        await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path / 'events.db'}", sqlite_dir=str(tmp_path))
        store = DbRunEventStore(get_session_factory())
    elif backend == "jsonl":
        store = JsonlRunEventStore(base_dir=tmp_path / "events")
    else:
        store = MemoryRunEventStore()
    first = {"type": "tool", "id": "result-first", "tool_call_id": "call_0", "content": "first"}
    second = {**first, "id": "result-second", "content": "second"}
    try:
        for run_id, message in [("run-a", first), (second_run, second), (second_run, {**second, "content": "replayed"})]:
            await store.put(thread_id="thread", run_id=run_id, event_type="llm.tool.result", category="message", content=message)
        stamped = await stamp_messages_with_seq(store, "thread", [first, second])
        assert [message["additional_kwargs"]["deerflow_seq"] for message in stamped] == [1, 2]
        assert [message_identity(message) for message in stamped] == ["message:result-first", "message:result-second"]
    finally:
        if backend == "db":
            await close_engine()


@pytest.mark.anyio
@pytest.mark.parametrize("command_result", [False, True])
@pytest.mark.parametrize("mode", ["full", "delta"])
async def test_tool_callback_ids_match_reloaded_checkpoint(command_result, mode):
    """Exercise real BaseTool callbacks, ToolNode, reducer and checkpointer."""

    @tool
    def lookup(value: str) -> str | Command:
        """Return the requested value."""
        if command_result:
            return Command(update={"messages": [ToolMessage(content=value, tool_call_id="call_0")]})
        return value

    builder = StateGraph(get_thread_state_schema(mode))
    builder.add_node("tools", ToolNode([lookup]))
    builder.set_entry_point("tools")
    builder.set_finish_point("tools")
    saver = InMemorySaver()
    graph = builder.compile(checkpointer=saver)
    accessor = CheckpointStateAccessor.bind(graph, saver, mode=mode)
    store = MemoryRunEventStore()
    journal = RunJournal("run-a", "thread", store)
    config = {"configurable": {"thread_id": "thread"}, "callbacks": [journal]}
    try:
        for index in range(2):
            await graph.ainvoke(
                {"messages": [AIMessage(id=f"assistant-{index}", content="", tool_calls=[{"id": "call_0", "name": "lookup", "args": {"value": f"result-{index}"}}])]},
                config,
            )
        await journal.flush()
        events = await store.list_messages("thread")
        feed_tools = [event["content"] for event in events if event["content"].get("type") == "tool"]
        snapshot = await accessor.aget(config)
        tools = [message for message in snapshot.values["messages"] if isinstance(message, ToolMessage)]
        assert len(feed_tools) == len(tools) == 2
        assert len({message["id"] for message in feed_tools}) == 2
        assert all(message["id"] for message in feed_tools)
        assert [message["id"] for message in feed_tools] == [message.id for message in tools]
        stamped = await stamp_messages_with_seq(store, "thread", [message.model_dump() for message in tools])
        assert [message["additional_kwargs"]["deerflow_seq"] for message in stamped] == [event["seq"] for event in events if event["content"].get("type") == "tool"]
    finally:
        await journal.close()


@pytest.mark.anyio
@pytest.mark.parametrize("with_id", [False, True])
@pytest.mark.parametrize("callback", [False, True])
@pytest.mark.parametrize("same_content", [False, True])
async def test_middleware_results_with_reused_call_id_are_reconciled_once(with_id, callback, same_content):
    store = MemoryRunEventStore()
    journal = RunJournal("run-a", "thread", store)
    try:
        for index in range(2):
            assistant = AIMessage(id=f"assistant-{index}", content="", tool_calls=[{"id": "call_0", "name": "blocked", "args": {}}])
            response = LLMResult(generations=[[ChatGeneration(message=assistant)]])
            completion_id = uuid4()
            journal.on_llm_end(response, run_id=completion_id, tags=["lead_agent"])
            result = ToolMessage(id=f"result-{index}" if with_id else None, content="blocked" if same_content else f"blocked-{index}", tool_call_id="call_0")
            # Capture the wire shape before either callback can assign an ID.
            snapshot = result.model_dump()
            if callback:
                journal.on_tool_end(result, run_id=uuid4())
            journal.on_chat_model_start({}, [[assistant, result]], run_id=uuid4(), tags=["lead_agent"])
            # A duplicate completion callback must not reopen the occurrence.
            journal.on_llm_end(response, run_id=completion_id, tags=["lead_agent"])
            replay = ToolMessage.model_validate(snapshot)
            journal.on_chat_model_start({}, [[assistant, replay]], run_id=uuid4(), tags=["lead_agent"])
            assert replay.id == result.id
            assert result.id
        await journal.flush()
        results = [event["content"] for event in await store.list_messages("thread") if event["content"].get("type") == "tool"]
        assert [result["content"] for result in results] == (["blocked", "blocked"] if same_content else ["blocked-0", "blocked-1"])
        assert len({result["id"] for result in results}) == 2
    finally:
        await journal.close()


@pytest.mark.anyio
async def test_deferred_task_completion_keeps_its_pending_id_when_provider_ids_repeat():
    from deerflow.subagents.status_contract import make_subagent_additional_kwargs

    store = MemoryRunEventStore()
    journal = RunJournal("run-a", "thread", store)
    try:
        for index in range(2):
            assistant = AIMessage(id=f"assistant-{index}", content="", tool_calls=[{"id": "call_0", "name": "task", "args": {}}])
            journal.on_llm_end(LLMResult(generations=[[ChatGeneration(message=assistant)]]), run_id=uuid4(), tags=["lead_agent"])
            pending = ToolMessage(id=f"result-{index}", content="Pending", name="task", tool_call_id="call_0", additional_kwargs={"subagent_pending": True})
            journal.on_chat_model_start({}, [[assistant, pending]], run_id=uuid4(), tags=["lead_agent"])
            terminal = ToolMessage(id=pending.id, content="Completed", name="task", tool_call_id="call_0", additional_kwargs=make_subagent_additional_kwargs("completed", result="Done"))
            journal.record_deferred_task_result(terminal)
            journal.record_deferred_task_result(terminal)
        await journal.flush()
        messages = [row["content"] for row in await store.list_messages("thread") if row["content"].get("type") == "tool"]
        assert [(message["id"], message["content"]) for message in messages] == [("result-0", "Pending"), ("result-0", "Completed"), ("result-1", "Pending"), ("result-1", "Completed")]
    finally:
        await journal.close()
