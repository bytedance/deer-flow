"""通过真实工具图验证任务笔记的批次容量与回执。"""

import asyncio
import json
import threading

import pytest
from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver

from deerflow.agents.task_continuity.tools import task_note
from deerflow.agents.thread_state import ThreadState, get_thread_state_schema


class NoteModel(BaseChatModel):
    calls: list[dict]

    @property
    def _llm_type(self):
        return "task-note-capacity-test"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        message = AIMessage(content="done") if isinstance(messages[-1], ToolMessage) else AIMessage(content="", tool_calls=self.calls)
        return ChatResult(generations=[ChatGeneration(message=message)])


def note_call(key, content="new note", *, call_id=None, **kwargs):
    return {"name": "task_note", "id": call_id or key, "args": {"key": key, "content": content, **kwargs}}


def notebook(count):
    return {f"keep{i}": {"content": f"original {i}"} for i in range(count)}


def replies(state):
    return {message.tool_call_id: json.loads(message.content) for message in state["messages"] if isinstance(message, ToolMessage)}


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True], ids=["sync", "async"])
async def test_parallel_new_notes_preserve_existing_notes_and_report_capacity(async_mode):
    graph = create_agent(NoteModel(calls=[note_call("new_a"), note_call("new_b")]), tools=[task_note], state_schema=ThreadState)
    initial = {"messages": [HumanMessage(content="save both notes")], "task_notes": {f"keep{i}": {"content": f"original {i}"} for i in range(7)}}
    state = await graph.ainvoke(initial) if async_mode else graph.invoke(initial)
    results = replies(state)

    assert set(state["task_notes"]) == {"keep0", "keep1", "keep2", "keep3", "keep4", "keep5", "keep6", "new_a"}, results
    assert results["new_a"]["status"] == "saved"
    assert results["new_b"]["error"] == "note_capacity"
    assert all(state["task_notes"][f"keep{i}"]["content"] == f"original {i}" for i in range(7))


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("mode", ["full", "delta"])
@pytest.mark.parametrize("count", [0, 6, 8])
async def test_batch_admission_matches_checkpointed_notebook(async_mode, mode, count):
    graph = create_agent(NoteModel(calls=[note_call(f"new{i}") for i in range(10)]), tools=[task_note], state_schema=get_thread_state_schema(mode), checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "capacity"}}
    initial = {"messages": [HumanMessage(content="save notes")], "task_notes": notebook(count)}
    state = await graph.ainvoke(initial, config) if async_mode else graph.invoke(initial, config)
    snapshot = await graph.aget_state(config) if async_mode else graph.get_state(config)
    assert snapshot.values["task_notes"] == state["task_notes"]
    assert len(state["task_notes"]) == 8
    assert set(notebook(count)) <= state["task_notes"].keys()
    for index in range(10):
        if index < 8 - count:
            assert replies(state)[f"new{index}"]["status"] == "saved"
            assert state["task_notes"][f"new{index}"]["content"] == "new note"
        else:
            assert replies(state)[f"new{index}"]["error"] == "note_capacity"
            assert f"new{index}" not in state["task_notes"]


class ReverseCompletion(AgentMiddleware):
    """用真实中间件使后一个调用先完成，验证接纳不取决于调度时机。"""

    def __init__(self):
        self.sync_done = threading.Event()
        self.async_done = asyncio.Event()
        self.completed = []

    def wrap_tool_call(self, request, handler):
        if request.tool_call["id"] == "first":
            assert self.sync_done.wait(5)
        result = handler(request)
        self.completed.append(request.tool_call["id"])
        self.sync_done.set()
        return result

    async def awrap_tool_call(self, request, handler):
        if request.tool_call["id"] == "first":
            await asyncio.wait_for(self.async_done.wait(), 5)
        result = await handler(request)
        self.completed.append(request.tool_call["id"])
        self.async_done.set()
        return result


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True], ids=["sync", "async"])
async def test_admission_uses_call_order_not_completion_order(async_mode):
    middleware = ReverseCompletion()
    graph = create_agent(NoteModel(calls=[note_call("new_a", call_id="first"), note_call("new_b", call_id="second")]), tools=[task_note], middleware=[middleware], state_schema=ThreadState)
    initial = {"messages": [HumanMessage(content="save notes")], "task_notes": notebook(7)}
    state = await graph.ainvoke(initial) if async_mode else graph.invoke(initial)
    assert middleware.completed == ["second", "first"]
    assert replies(state)["first"]["status"] == "saved"
    assert replies(state)["second"]["error"] == "note_capacity"
    assert set(state["task_notes"]) == set(notebook(7)) | {"new_a"}


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("last_content", ["replacement", ""])
async def test_same_new_key_shares_one_slot_and_keeps_ordered_update_delete_semantics(async_mode, last_content):
    calls = [note_call("new_a", call_id="first"), note_call("new_a", last_content, call_id="last"), note_call("new_b")]
    graph = create_agent(NoteModel(calls=calls), tools=[task_note], state_schema=ThreadState)
    initial = {"messages": [HumanMessage(content="update or delete")], "task_notes": notebook(7)}
    state = await graph.ainvoke(initial) if async_mode else graph.invoke(initial)
    assert set(notebook(7)) <= state["task_notes"].keys()
    assert replies(state)["first"]["status"] == "saved"
    assert replies(state)["last"]["status"] == ("saved" if last_content else "deleted")
    assert replies(state)["new_b"]["error"] == "note_capacity"
    if last_content:
        assert state["task_notes"]["new_a"]["content"] == "replacement"
        assert len(state["task_notes"]) == 8
    else:
        assert set(state["task_notes"]) == set(notebook(7))


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True], ids=["sync", "async"])
async def test_full_notebook_allows_replace_delete_and_new_key_in_next_batch(async_mode):
    saver = InMemorySaver()
    config = {"configurable": {"thread_id": "next-batch"}}
    graph = create_agent(NoteModel(calls=[note_call("keep0", "updated"), note_call("keep1", ""), note_call("new_a")]), tools=[task_note], state_schema=ThreadState, checkpointer=saver)
    initial = {"messages": [HumanMessage(content="update and delete")], "task_notes": notebook(8)}
    state = await graph.ainvoke(initial, config) if async_mode else graph.invoke(initial, config)
    assert len(state["task_notes"]) == 7
    assert state["task_notes"]["keep0"]["content"] == "updated"
    assert "keep1" not in state["task_notes"]
    assert replies(state)["keep0"]["status"] == "saved"
    assert replies(state)["keep1"]["status"] == "deleted"
    assert replies(state)["new_a"]["error"] == "note_capacity"

    resumed = create_agent(NoteModel(calls=[note_call("new_a", call_id="retry")]), tools=[task_note], state_schema=ThreadState, checkpointer=saver)
    state = await resumed.ainvoke({"messages": [HumanMessage(content="retry")]}, config) if async_mode else resumed.invoke({"messages": [HumanMessage(content="retry")]}, config)
    assert len(state["task_notes"]) == 8
    assert replies(state)["retry"]["status"] == "saved"
    assert state["task_notes"]["new_a"]["content"] == "new note"


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize(
    ("first_call", "error"),
    [
        (note_call("invalid", "x" * 751), "invalid_note"),
        (note_call("invalid", source_ids=["not-a-source"]), "invalid_source_id"),
        (note_call("invalid", source_ids=["r" + "0" * 32] * 5), "invalid_note"),
    ],
)
async def test_failed_sibling_does_not_promise_its_reserved_slot(async_mode, first_call, error):
    graph = create_agent(NoteModel(calls=[first_call, note_call("new_a")]), tools=[task_note], state_schema=ThreadState)
    initial = {"messages": [HumanMessage(content="save notes")], "task_notes": notebook(7)}
    state = await graph.ainvoke(initial) if async_mode else graph.invoke(initial)
    assert set(state["task_notes"]) == set(notebook(7))
    assert replies(state)["invalid"]["error"] == error
    assert replies(state)["new_a"]["error"] == "note_capacity"
    # 新模型批次重新计算容量，失败预留不能泄漏到后续执行。
    retry = create_agent(NoteModel(calls=[note_call("new_a")]), tools=[task_note], state_schema=ThreadState)
    state["messages"].append(HumanMessage(content="retry"))
    state = await retry.ainvoke(state) if async_mode else retry.invoke(state)
    assert len(state["task_notes"]) == 8
    assert replies(state)["new_a"]["status"] == "saved"


@pytest.mark.asyncio
async def test_shared_graph_keeps_simultaneous_task_capacity_independent():
    graph = create_agent(NoteModel(calls=[note_call("new_a"), note_call("new_b")]), tools=[task_note], state_schema=ThreadState, checkpointer=InMemorySaver())

    async def run(user, thread, count):
        return await graph.ainvoke(
            {"messages": [HumanMessage(content="save notes")], "task_notes": notebook(count)},
            {"configurable": {"thread_id": thread}},
            context={"user_id": user, "thread_id": thread},
        )

    nearly_full, empty, full = await asyncio.gather(run("alice", "thread-a", 7), run("bob", "thread-b", 0), run("alice", "thread-c", 8))
    assert set(nearly_full["task_notes"]) == set(notebook(7)) | {"new_a"}
    assert replies(nearly_full)["new_b"]["error"] == "note_capacity"
    assert set(empty["task_notes"]) == {"new_a", "new_b"}
    assert all(result["status"] == "saved" for result in replies(empty).values())
    assert set(full["task_notes"]) == set(notebook(8))
    assert all(result["error"] == "note_capacity" for result in replies(full).values())
