"""Behavioral checks for checkpoint-reachable parent-task recall."""

from types import SimpleNamespace

import pytest
from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver

from deerflow.agents.middlewares.durable_context_middleware import DurableContextMiddleware
from deerflow.agents.middlewares.summarization_middleware import DeerFlowSummarizationMiddleware
from deerflow.agents.task_continuity import archive
from deerflow.agents.task_continuity.state import merge_task_notes
from deerflow.agents.task_continuity.tools import append_task_continuity_tools, history_read, history_search, task_note
from deerflow.agents.thread_state import ThreadState
from deerflow.config.paths import Paths
from deerflow.config.task_continuity_config import TaskContinuityConfig


class StaticModel(BaseChatModel):
    @property
    def _llm_type(self):
        return "continuity-test"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="summary without the original identifier"))])


@pytest.fixture
def scoped(tmp_path, monkeypatch):
    paths = Paths(base_dir=tmp_path)
    monkeypatch.setattr(archive, "get_paths", lambda: paths)
    return SimpleNamespace(context={"thread_id": "thread-a", "user_id": "alice"}, state={}, tool_call_id="call-1")


def compacting(config=None):
    return DeerFlowSummarizationMiddleware(model=StaticModel(), trigger=("messages", 4), keep=("messages", 2), task_continuity_config=config)


def conversation():
    return [HumanMessage(content="Project Citrine batch code ZX-731. 决策保留备份。", id="u1"), AIMessage(content="Accepted", id="a1"), HumanMessage(content="Continue", id="u2"), AIMessage(content="Working", id="a2")]


def test_compaction_preserves_exact_source_and_excludes_it_from_summary(scoped):
    state = {"messages": conversation()}
    update = compacting(TaskContinuityConfig(enabled=True))._maybe_summarize(state, scoped)
    assert update is not None
    assert "ZX-731" not in update["summary_text"]
    after = {**state, **update, "messages": list(update["messages"])[1:]}
    result = archive.lookup(after, scoped, query="Citrine")
    assert result["results"][0]["text"].endswith("决策保留备份。")
    assert result["results"][0]["id"] == archive.records(conversation())[0]["id"]


@pytest.mark.asyncio
async def test_async_compaction_and_source_pagination(scoped):
    messages = conversation()
    messages[0].content = "Citrine " + "x" * 9000
    update = await compacting(TaskContinuityConfig(enabled=True))._amaybe_summarize({"messages": messages}, scoped)
    scoped.state = {"task_history": update["task_history"], "messages": []}
    import json

    result = json.loads(await history_search.coroutine(scoped, "Citrine"))
    assert len(result["results"][0]["excerpt"]) == 600
    source_id = result["results"][0]["id"]
    page1 = json.loads(await history_read.coroutine(scoped, source_id))
    page2 = json.loads(await history_read.coroutine(scoped, source_id, page1["next_offset"]))
    assert len(page1["text"]) == 4000
    assert len(page2["text"]) == 4000
    assert page2["next_offset"] == 8000


@pytest.mark.parametrize("context", [{"thread_id": "thread-b", "user_id": "alice"}, {"thread_id": "thread-a", "user_id": "bob"}])
def test_copied_checkpoint_cannot_read_another_scope(scoped, context):
    history = archive.capture({}, scoped, conversation(), TaskContinuityConfig(enabled=True))
    foreign = SimpleNamespace(context=context)
    result = archive.lookup({"task_history": history}, foreign, query="Citrine")
    assert result == {"results": [], "status": "scope_unavailable"}


def test_old_checkpoint_cannot_see_future_batch(scoped):
    config = TaskContinuityConfig(enabled=True)
    old = {"task_history": archive.capture({}, scoped, conversation(), config)}
    archive.capture(old, scoped, [HumanMessage(content="future secret ORCHID", id="future")], config)
    assert not archive.lookup(old, scoped, query="ORCHID")["results"]
    assert archive.lookup(old, scoped, query="Citrine")["results"]


def test_retention_is_explicit_and_duplicate_capture_is_idempotent(scoped):
    config = TaskContinuityConfig(enabled=True, max_batches=1)
    old = {"task_history": archive.capture({}, scoped, conversation(), config)}
    assert archive.capture(old, scoped, conversation(), config)["batches"] == old["task_history"]["batches"]
    archive.capture(old, scoped, [HumanMessage(content="new batch", id="new")], config)
    assert archive.lookup(old, scoped, query="Citrine") == {"results": [], "status": "partially_expired"}


def test_serialization_allowlist_omits_reasoning_and_binary():
    source = AIMessage(
        content=[{"type": "text", "text": "visible"}, {"type": "reasoning", "reasoning": "private-thought"}, {"type": "image_url", "image_url": {"url": "data:secret"}}],
        additional_kwargs={"reasoning_content": "private"},
        tool_calls=[{"id": "call", "name": "probe", "args": {"part": "bolt"}}],
    )
    hidden = HumanMessage(content="internal", additional_kwargs={"hide_from_ui": True})
    result = archive.records([SystemMessage(content="system-secret"), source, hidden, ToolMessage(content="tool-visible", tool_call_id="call", artifact={"secret": "artifact"})])
    assert len(result) == 2
    assert "probe" in result[0]["text"] and "bolt" in result[0]["text"]
    assert "secret" not in str(result) and "private" not in str(result) and "internal" not in str(result)


@pytest.mark.parametrize("query", ["Citrine", "保留备份", 'Citrine" OR "x', '" OR * NOT NEAR( x )'])
def test_keywords_and_fts_syntax_are_data(scoped, query):
    state = {"task_history": archive.capture({}, scoped, conversation(), TaskContinuityConfig(enabled=True))}
    result = archive.lookup(state, scoped, query=query)
    assert result["status"] == "available"
    if query in ("Citrine", "保留备份"):
        assert result["results"]


def test_truncation_and_omitted_sources_are_reported(scoped):
    config = TaskContinuityConfig(enabled=True, max_records_per_batch=1, max_record_chars=1000)
    history = archive.capture({}, scoped, [HumanMessage(content="old"), HumanMessage(content="Citrine " + "x" * 2000)], config)
    assert history["omitted_records"] == 1
    result = archive.lookup({"task_history": history}, scoped, query="Citrine")
    assert result["results"][0]["truncated"]
    assert len(result["results"][0]["text"]) == 1000


def test_disabled_compaction_does_not_create_archive(scoped):
    update = compacting()._maybe_summarize({"messages": conversation()}, scoped)
    assert "task_history" not in update
    assert not archive.scope(scoped)[0].exists()


def test_failed_summary_does_not_archive(scoped, monkeypatch):
    middleware = compacting(TaskContinuityConfig(enabled=True))
    monkeypatch.setattr(middleware, "_summarize_with", lambda *args, **kwargs: None)
    assert middleware.compact_state({"messages": conversation()}, scoped) is None
    assert not archive.scope(scoped)[0].exists()


def test_archive_failure_preserves_summary(scoped, monkeypatch):
    monkeypatch.setattr(archive, "scope", lambda runtime: (_ for _ in ()).throw(ValueError("unavailable")))
    update = compacting(TaskContinuityConfig(enabled=True))._maybe_summarize({"messages": conversation()}, scoped)
    assert update["summary_text"]
    assert update["task_history"]["status"] == "unavailable"


@pytest.mark.asyncio
async def test_notes_validate_sources_and_merge_parallel_keys(scoped):
    scoped.state = {"messages": conversation()}
    source_id = archive.records(conversation())[0]["id"]
    command = await task_note.coroutine(scoped, "constraint", "Keep backups", [source_id])
    assert command.update["task_notes"]["constraint"]["authority"] == "model_report"
    assert "source_unavailable" in await task_note.coroutine(scoped, "wrong", "bad", ["r" + "0" * 32])
    merged = merge_task_notes({"other": {"content": "next step"}}, command.update["task_notes"])
    assert set(merged) == {"other", "constraint"}
    deleted = await task_note.coroutine(scoped, "constraint", "")
    assert set(merge_task_notes(merged, deleted.update["task_notes"])) == {"other"}


def test_tools_are_opt_in_and_do_not_replace_existing_names():
    tools = []
    append_task_continuity_tools(tools, SimpleNamespace(task_continuity=TaskContinuityConfig()))
    assert not tools
    config = SimpleNamespace(task_continuity=TaskContinuityConfig(enabled=True))
    append_task_continuity_tools(tools, config)
    append_task_continuity_tools(tools, config)
    assert {t.name for t in tools} == {"task_note", "history_search", "history_read"}
    assert len(tools) == 3


@pytest.mark.asyncio
async def test_actual_graph_compaction_checkpoint_resume(scoped):
    saver = InMemorySaver()
    graph = create_agent(StaticModel(), tools=[], middleware=[DurableContextMiddleware(task_continuity_enabled=True), compacting(TaskContinuityConfig(enabled=True))], state_schema=ThreadState, checkpointer=saver)
    config = {"configurable": {"thread_id": "thread-a"}}
    first = await graph.ainvoke({"messages": conversation(), "task_notes": {"next": {"content": "Verify batch code", "authority": "model_report"}}}, config=config, context=scoped.context)
    assert first["task_history"]["batches"]
    assert all("ZX-731" not in str(m.content) for m in first["messages"])
    # Rebuild the graph against the same saver, as a separate client invocation.
    resumed = create_agent(StaticModel(), tools=[], middleware=[DurableContextMiddleware(task_continuity_enabled=True)], state_schema=ThreadState, checkpointer=saver)
    second = await resumed.ainvoke({"messages": [HumanMessage(content="Resume the saved task")]}, config=config, context=scoped.context)
    assert second["task_notes"]["next"]["content"] == "Verify batch code"
    recovered = archive.lookup(second, scoped, query="Citrine")["results"]
    assert "ZX-731" in recovered[0]["text"]


def test_long_source_indexes_late_words(scoped):
    text = " ".join(f"word{i}" for i in range(120)) + " needlefragment"
    state = {"task_history": archive.capture({}, scoped, [HumanMessage(content=text)], TaskContinuityConfig(enabled=True))}
    assert archive.lookup(state, scoped, query="word80")["results"]
    assert archive.lookup(state, scoped, query="needlefragment")["results"]


@pytest.mark.asyncio
async def test_cancelled_capture_drains_write(scoped, monkeypatch):
    import asyncio
    import threading

    started, finish = threading.Event(), threading.Event()

    def blocking_capture(*args):
        started.set()
        finish.wait(timeout=5)
        return {"status": "available"}

    monkeypatch.setattr(archive, "capture", blocking_capture)
    task = asyncio.create_task(archive.acapture({}, scoped, [], TaskContinuityConfig(enabled=True)))
    await asyncio.to_thread(started.wait, 2)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    finish.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert finish.is_set()


@pytest.mark.asyncio
async def test_repeated_manual_compaction_keeps_earlier_source_batches(scoped, monkeypatch):
    from langgraph.types import Overwrite

    from app.gateway import services
    from deerflow.runtime import context_compaction

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(checkpointer=InMemorySaver(), checkpoint_channel_mode="delta", store=None)))
    accessor, config = services.build_checkpoint_state_mutation_accessor(request, thread_id="thread-a", as_node="manual_compaction")
    await accessor.aupdate(config, {"messages": Overwrite(conversation()), "task_notes": {"next": {"content": "keep going"}}}, as_node="manual_compaction")
    monkeypatch.setattr(context_compaction, "_create_compaction_middleware", lambda **kwargs: compacting(TaskContinuityConfig(enabled=True)))
    first = await context_compaction.compact_thread_context(accessor, "thread-a", user_id="alice", app_config=SimpleNamespace())
    assert first.compacted
    snapshot = await accessor.aget(config)
    first_batch = snapshot.values["task_history"]["batches"][0]
    await accessor.aupdate(
        snapshot.config, {"messages": [HumanMessage(content="Orchid approved value V-92", id="orchid"), AIMessage(content="approved"), HumanMessage(content="continue again"), AIMessage(content="ready")]}, as_node="manual_compaction"
    )
    second = await context_compaction.compact_thread_context(accessor, "thread-a", user_id="alice", app_config=SimpleNamespace())
    assert second.compacted
    final = await accessor.aget(config)
    assert first_batch in final.values["task_history"]["batches"]
    assert "ZX-731" in archive.lookup(final.values, scoped, query="Citrine")["results"][0]["text"]
    assert archive.lookup(final.values, scoped, query="Orchid")["results"]
    assert final.values["task_notes"]["next"]["content"] == "keep going"


def test_split_client_tool_catalog_preserves_configured_names():
    late = []
    config = SimpleNamespace(task_continuity=TaskContinuityConfig(enabled=True))
    append_task_continuity_tools(late, config, existing_names={"history_read"})
    assert {tool.name for tool in late} == {"task_note", "history_search"}


def test_disabled_graph_does_not_add_state_or_wire_events():
    graph = create_agent(StaticModel(), tools=[], middleware=[DurableContextMiddleware()], state_schema=ThreadState)
    result = graph.invoke({"messages": [HumanMessage(content="hello")]})
    assert "task_notes" not in result
    assert "task_history" not in result


def test_synchronous_graph_executes_search_read_and_note(scoped):
    import json

    class SyncRecallModel(StaticModel):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            last = messages[-1]
            if isinstance(last, ToolMessage) and last.name == "history_search":
                source = json.loads(last.content)["results"][0]["id"]
                call = {"name": "history_read", "args": {"source_id": source}, "id": "read"}
            elif isinstance(last, ToolMessage) and last.name == "history_read":
                source = json.loads(last.content)
                call = {"name": "task_note", "args": {"key": "verified", "content": source["text"], "source_ids": [source["id"]]}, "id": "note"}
            elif isinstance(last, ToolMessage) and last.name == "task_note":
                return ChatResult(generations=[ChatGeneration(message=AIMessage(content="recovered"))])
            else:
                call = {"name": "history_search", "args": {"query": "Citrine"}, "id": "search"}
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content="", tool_calls=[call]))])

    history = archive.capture({}, scoped, conversation(), TaskContinuityConfig(enabled=True))
    graph = create_agent(SyncRecallModel(), tools=[task_note, history_search, history_read], middleware=[DurableContextMiddleware(task_continuity_enabled=True)], state_schema=ThreadState)
    state = graph.invoke({"messages": [HumanMessage(content="Resume")], "task_history": history}, context=scoped.context)
    assert "ZX-731" in state["task_notes"]["verified"]["content"]
    assert state["messages"][-1].content == "recovered"
