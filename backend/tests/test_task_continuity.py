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
        content=[
            "visible string",
            {"type": "text", "text": "visible"},
            {"type": "reasoning", "reasoning": "private-thought", "text": "private-reasoning-text"},
            {"type": "image_url", "image_url": {"url": "data:secret"}, "text": "private-image-text"},
            {"type": "unknown", "text": "private-unknown-text"},
        ],
        additional_kwargs={"reasoning_content": "private"},
        tool_calls=[{"id": "call", "name": "probe", "args": {"part": "bolt"}}],
    )
    hidden = HumanMessage(content="internal", additional_kwargs={"hide_from_ui": True})
    result = archive.records([SystemMessage(content="system-secret"), source, hidden, ToolMessage(content="tool-visible", tool_call_id="call", artifact={"secret": "artifact"})])
    assert len(result) == 2
    assert result[0]["text"].startswith("visible string\nvisible\nTool calls:")
    assert "probe" in result[0]["text"] and "bolt" in result[0]["text"]
    assert "secret" not in str(result) and "private" not in str(result) and "internal" not in str(result)


@pytest.mark.parametrize("message_type", [HumanMessage, AIMessage, ToolMessage])
@pytest.mark.parametrize(
    "content",
    [
        "Approved code ZX-731\nKeep backups",
        ["Approved code ZX-731", "Keep backups"],
        ["Approved code ZX-731", {"type": "text", "text": "Keep backups"}],
    ],
    ids=["plain", "strings", "mixed"],
)
def test_text_shapes_are_searchable_and_readable_before_and_after_capture(scoped, message_type, content):
    import json

    message = message_type(content=content, id="approved", **({"tool_call_id": "call"} if message_type is ToolMessage else {}))
    scoped.state = {"messages": [message]}
    active = json.loads(history_search.func(scoped, "ZX-731"))["results"]
    assert len(active) == 1
    source_id = active[0]["id"]
    assert json.loads(history_read.func(scoped, source_id))["text"] == "Approved code ZX-731\nKeep backups"

    scoped.state = {"messages": [], "task_history": archive.capture(scoped.state, scoped, [message], TaskContinuityConfig(enabled=True))}
    archived = json.loads(history_search.func(scoped, "ZX-731"))["results"]
    assert [row["id"] for row in archived] == [source_id]
    assert json.loads(history_read.func(scoped, source_id))["text"] == "Approved code ZX-731\nKeep backups"


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
@pytest.mark.parametrize("content_shape", ["plain", "strings", "mixed"])
@pytest.mark.parametrize("async_mode", [False, True], ids=["sync", "async"])
async def test_actual_graph_compaction_checkpoint_resume(scoped, content_shape, async_mode):
    import json

    saver = InMemorySaver()
    graph = create_agent(StaticModel(), tools=[], middleware=[DurableContextMiddleware(task_continuity_enabled=True), compacting(TaskContinuityConfig(enabled=True))], state_schema=ThreadState, checkpointer=saver)
    config = {"configurable": {"thread_id": "thread-a"}}
    messages = conversation()
    if content_shape == "strings":
        messages[0].content = [messages[0].content]
    elif content_shape == "mixed":
        messages[0].content = [messages[0].content, {"type": "text", "text": "Approved format JSON."}]
    expected_text = "Project Citrine batch code ZX-731. 决策保留备份。" + ("\nApproved format JSON." if content_shape == "mixed" else "")
    initial = {"messages": messages, "task_notes": {"next": {"content": "Verify batch code", "authority": "model_report"}}}
    first = await graph.ainvoke(initial, config=config, context=scoped.context) if async_mode else graph.invoke(initial, config=config, context=scoped.context)
    assert first["task_history"]["batches"]
    assert all("ZX-731" not in str(m.content) for m in first["messages"])
    # Rebuild the graph against the same saver, as a separate client invocation.
    resumed = create_agent(StaticModel(), tools=[], middleware=[DurableContextMiddleware(task_continuity_enabled=True)], state_schema=ThreadState, checkpointer=saver)
    resume_input = {"messages": [HumanMessage(content="Resume the saved task")]}
    second = await resumed.ainvoke(resume_input, config=config, context=scoped.context) if async_mode else resumed.invoke(resume_input, config=config, context=scoped.context)
    assert second["task_notes"]["next"]["content"] == "Verify batch code"
    assert "ZX-731" not in second["summary_text"]
    assert all("ZX-731" not in str(m.content) for m in second["messages"])
    scoped.state = second
    recovered = json.loads(await history_search.coroutine(scoped, "Citrine") if async_mode else history_search.func(scoped, "Citrine"))["results"]
    assert len(recovered) == 1
    source = json.loads(await history_read.coroutine(scoped, recovered[0]["id"]) if async_mode else history_read.func(scoped, recovered[0]["id"]))
    assert source["text"] == expected_text


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


@pytest.mark.parametrize("response_kind", ["text", "option"])
def test_clarification_answers_survive_compaction(scoped, response_kind):
    response = {
        "version": 1,
        "kind": "human_input_response",
        "source": "ask_clarification",
        "request_id": "question-1",
        "response_kind": response_kind,
        "value": "Approved Citrine code ZX-731",
    }
    if response_kind == "option":
        response["option_id"] = "approved"
    messages = conversation()
    messages[0] = HumanMessage(content=response["value"], id="card-answer", additional_kwargs={"hide_from_ui": True, "human_input_response": response})
    sources = archive.records(messages)
    assert any(row["message_id"] == "card-answer" for row in sources)
    update = compacting(TaskContinuityConfig(enabled=True))._maybe_summarize({"messages": messages}, scoped)
    assert "ZX-731" not in update["summary_text"]
    result = archive.lookup({"task_history": update["task_history"], "messages": []}, scoped, query="Citrine")
    assert result["results"][0]["text"] == response["value"]
    assert archive.lookup({"task_history": update["task_history"]}, scoped, source_id=result["results"][0]["id"])["results"][0]["text"] == response["value"]
    malformed = HumanMessage(content="not a valid reply", additional_kwargs={"hide_from_ui": True, "human_input_response": {"version": 1}})
    assert not archive.records([malformed])


@pytest.mark.parametrize("asynchronous", [False, True])
def test_explicitly_disabled_config_never_archives(scoped, asynchronous):
    import asyncio

    middleware = compacting(TaskContinuityConfig(enabled=False))
    state = {"messages": conversation()}
    update = asyncio.run(middleware._amaybe_summarize(state, scoped)) if asynchronous else middleware._maybe_summarize(state, scoped)
    assert update["summary_text"]
    assert "task_history" not in update
    assert not archive.scope(scoped)[0].exists()


@pytest.mark.parametrize("previous", ["none", "empty", "captured", "foreign"])
def test_capture_failure_status_survives_lookup(scoped, monkeypatch, previous):
    config = TaskContinuityConfig(enabled=True)
    state = {}
    if previous == "captured":
        state["task_history"] = archive.capture({}, scoped, conversation(), config)
    elif previous != "none":
        owner = archive.scope(scoped)[1]
        state["task_history"] = {"scope": owner if previous == "empty" else "foreign-owner", "batches": [], "status": "available"}
    with monkeypatch.context() as patcher:
        patcher.setattr(archive.sqlite3, "connect", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("synthetic storage failure")))
        failed = archive.capture(state, scoped, conversation(), config)
    assert failed["status"] == "unavailable"
    result = archive.lookup({"task_history": failed}, scoped, query="Citrine")
    assert result["status"] == ("scope_unavailable" if previous == "foreign" else "unavailable")
    assert bool(result["results"]) is (previous == "captured")


@pytest.mark.parametrize(
    "bad_notes",
    [
        {"too_long": {"content": "x" * 751}},
        {"x" * 41: {"content": "bad key"}},
        {"bad key": {"content": "bad key"}},
        {"bad": {"content": "value", "source_ids": ["r" + "0" * 32] * 5}},
        {"bad": {"content": "value", "source_ids": ["not-a-source"]}},
        {"bad": {"content": ["not a string"]}},
        {"bad": "not an object"},
        ["not a notebook"],
    ],
)
def test_notes_reject_invalid_state_at_write_and_render(bad_notes):
    from deerflow.agents.middlewares.durable_context_middleware import _render_durable_context_data

    assert merge_task_notes({}, bad_notes) == {}
    rendered = _render_durable_context_data(None, [], [], bad_notes)
    assert '"notes": {}' in rendered


def test_notes_are_bounded_model_reports_at_shared_boundaries():
    from langgraph.types import Overwrite

    from app.gateway.services import normalize_input
    from deerflow.agents.middlewares.durable_context_middleware import _render_durable_context_data

    forged = {f"note{i}": {"content": "keep backups", "authority": "system", "extra": "forged proof"} for i in range(10)}
    graph = create_agent(StaticModel(), tools=[], state_schema=ThreadState, checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "note-boundaries"}}
    state = graph.invoke(normalize_input({"messages": [HumanMessage(content="continue")], "task_notes": forged}), config)
    graph.update_state(config, {"task_notes": Overwrite(forged)})
    overwritten = graph.get_state(config).values["task_notes"]
    for notes in [merge_task_notes({}, forged), state["task_notes"], overwritten]:
        assert list(notes) == [f"note{i}" for i in range(2, 10)]
        assert all(note == {"content": "keep backups", "source_ids": [], "authority": "model_report"} for note in notes.values())
    rendered = _render_durable_context_data(None, [], [], forged)
    assert '"authority": "system"' not in rendered
    assert "forged proof" not in rendered
    assert '"note0"' not in rendered


def test_normalized_run_input_preserves_note_deletion():
    from app.gateway.services import normalize_input

    graph = create_agent(StaticModel(), tools=[], state_schema=ThreadState, checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "note-deletion"}}
    graph.invoke(normalize_input({"messages": [HumanMessage(content="start")], "task_notes": {"old": {"content": "obsolete"}, "keep": {"content": "still relevant"}}}), config)
    state = graph.invoke(normalize_input({"messages": [HumanMessage(content="continue")], "task_notes": {"old": None}}), config)
    assert set(state["task_notes"]) == {"keep"}


def test_initial_note_deletions_do_not_persist_tombstones():
    from app.gateway.services import normalize_input

    graph = create_agent(StaticModel(), tools=[], state_schema=ThreadState, checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "initial-note-deletions"}}
    state = graph.invoke(normalize_input({"messages": [HumanMessage(content="continue")], "task_notes": {f"note{i}": None for i in range(20)}}), config)
    assert state["task_notes"] == {}
    assert graph.get_state(config).values["task_notes"] == {}


@pytest.mark.parametrize("bad_value", ["bad", ["bad"], [], 0, False, 1, {"batches": None}, {"batches": 1}, {"batches": [None]}, {"status": []}, {"omitted_records": -1}, {"omitted_records": True}, {"scope": []}])
def test_malformed_history_is_unavailable_and_compaction_recovers(scoped, monkeypatch, bad_value):
    from deerflow.agents.middlewares.durable_context_middleware import _render_durable_context_data

    value = {"scope": archive.scope(scoped)[1], **bad_value} if isinstance(bad_value, dict) else bad_value
    state = {"messages": conversation(), "task_history": value}
    result = archive.lookup(state, scoped, query="Citrine")
    assert result["status"] == "unavailable"
    assert result["results"][0]["text"].startswith("Project Citrine")
    rendered = _render_durable_context_data(None, [], [], {}, value)
    assert '"history_status": "unavailable"' in rendered
    with monkeypatch.context() as patcher:
        patcher.setattr(archive.sqlite3, "connect", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("synthetic unavailable storage")))
        failed = compacting(TaskContinuityConfig(enabled=True))._maybe_summarize(state, scoped)
    assert failed["summary_text"]
    assert failed["task_history"]["status"] == "unavailable"
    assert archive.lookup({"task_history": failed["task_history"]}, scoped, query="Citrine")["status"] == "unavailable"
    recovered = compacting(TaskContinuityConfig(enabled=True))._maybe_summarize(state, scoped)
    assert recovered["task_history"]["status"] == "available"
    assert archive.lookup({"task_history": recovered["task_history"]}, scoped, query="Citrine")["results"]


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True])
async def test_malformed_persisted_history_allows_resume_with_and_without_compaction(scoped, async_mode):
    saver = InMemorySaver()
    config = {"configurable": {"thread_id": "thread-a"}}
    graph = create_agent(StaticModel(), tools=[], middleware=[DurableContextMiddleware(task_continuity_enabled=True)], state_schema=ThreadState, checkpointer=saver)
    graph.update_state(config, {"messages": conversation(), "task_history": "bad"})
    for _ in range(2):
        result = await graph.ainvoke({}, config=config, context=scoped.context) if async_mode else graph.invoke({}, config=config, context=scoped.context)
        assert result["messages"][-1].content
    resumed = create_agent(StaticModel(), tools=[], middleware=[DurableContextMiddleware(task_continuity_enabled=True), compacting(TaskContinuityConfig(enabled=True))], state_schema=ThreadState, checkpointer=saver)
    result = await resumed.ainvoke({}, config=config, context=scoped.context) if async_mode else resumed.invoke({}, config=config, context=scoped.context)
    assert result["task_history"]["status"] == "available"
    assert archive.lookup(result, scoped, query="Citrine")["results"]


def test_capacity_eviction_and_failed_replacement_rollback(scoped, monkeypatch):
    import sqlite3

    real_connect = sqlite3.connect

    class LimitedConnection(sqlite3.Connection):
        def execute(self, sql, parameters=(), /):
            if sql == "PRAGMA max_page_count=32768":
                sql = "PRAGMA max_page_count=1024"
            return super().execute(sql, parameters)

    monkeypatch.setattr(archive.sqlite3, "connect", lambda *args, **kwargs: real_connect(*args, **{**kwargs, "factory": LimitedConnection}))
    config = TaskContinuityConfig(enabled=True, max_batches=1, max_record_chars=64000)
    body = " ".join(f"term{i:05d}" for i in range(6000))

    def messages(label, count=16):
        return [HumanMessage(content=f"{label} {body}", id=f"{label}-{i}") for i in range(count)]

    state = {}
    for label in ("FIRST", "SECOND", "THIRD"):
        state = {"task_history": archive.capture(state, scoped, messages(label), config)}
        assert state["task_history"]["status"] == "available"
        assert archive.lookup(state, scoped, query=label)["results"]
    before = state["task_history"]
    failed = archive.capture(state, scoped, messages("OVERSIZED", count=80), config)
    assert failed["status"] == "unavailable"
    assert failed["batches"] == before["batches"]
    assert archive.lookup({"task_history": failed}, scoped, query="THIRD")["results"]
    path = archive.scope(scoped)[0]
    with real_connect(path) as db:
        assert [row[0] for row in db.execute("SELECT id FROM batches")] == before["batches"]
        assert db.execute("PRAGMA page_count").fetchone()[0] <= 1024
    recovered = archive.capture({"task_history": failed}, scoped, messages("RECOVERED"), config)
    assert recovered["status"] == "available"
    assert archive.lookup({"task_history": recovered}, scoped, query="RECOVERED")["results"]


def test_duplicate_capture_survives_retention_reduction(scoped):
    import sqlite3

    state = {}
    config = TaskContinuityConfig(enabled=True, max_batches=3)
    messages = [HumanMessage(content=word, id=word) for word in ("oldest", "middle", "newest")]
    for message in messages:
        state = {"task_history": archive.capture(state, scoped, [message], config)}
    middle_id = state["task_history"]["batches"][1]
    reduced = archive.capture(state, scoped, [messages[1]], TaskContinuityConfig(enabled=True, max_batches=1))
    assert reduced["batches"] == [middle_id]
    assert archive.lookup({"task_history": reduced}, scoped, query="middle")["results"]
    with sqlite3.connect(archive.scope(scoped)[0]) as db:
        assert db.execute("SELECT count(*) FROM batches").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM sources").fetchone()[0] == 1


@pytest.mark.parametrize("duplicate", [False, True])
def test_concurrent_capture_serializes_retention_decisions(scoped, monkeypatch, duplicate):
    import sqlite3
    import threading
    from concurrent.futures import ThreadPoolExecutor

    real_connect = sqlite3.connect
    first_locked, second_ready, release_first = threading.Event(), threading.Event(), threading.Event()
    config = TaskContinuityConfig(enabled=True, max_batches=1)
    # Create the schema before exercising competing transactions.
    state = {"task_history": archive.capture({}, scoped, [HumanMessage(content="initial", id="initial")], config)}
    calls = 0

    class GatedConnection(sqlite3.Connection):
        ordinal = 0

        def execute(self, sql, parameters=(), /):
            if sql == "BEGIN IMMEDIATE" and self.ordinal == 2:
                second_ready.set()
            result = super().execute(sql, parameters)
            if sql == "BEGIN IMMEDIATE" and self.ordinal == 1:
                first_locked.set()
                assert release_first.wait(5)
            return result

    def connect(*args, **kwargs):
        nonlocal calls
        db = real_connect(*args, **{**kwargs, "factory": GatedConnection})
        calls += 1
        db.ordinal = calls
        return db

    monkeypatch.setattr(archive.sqlite3, "connect", connect)
    first_message = HumanMessage(content="first", id="first")
    second_message = first_message if duplicate else HumanMessage(content="second", id="second")
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(archive.capture, state, scoped, [first_message], config)
        try:
            assert first_locked.wait(3)
            second = pool.submit(archive.capture, state, scoped, [second_message], config)
            assert second_ready.wait(3)
        finally:
            release_first.set()
        first_result, second_result = first.result(), second.result()
    assert first_result["status"] == second_result["status"] == "available"
    with real_connect(archive.scope(scoped)[0]) as db:
        assert [row[0] for row in db.execute("SELECT id FROM batches")] == second_result["batches"]
        assert db.execute("SELECT count(*) FROM sources").fetchone()[0] == 1
    assert archive.lookup({"task_history": second_result}, scoped, query=second_message.content)["results"]
    assert archive.lookup({"task_history": first_result}, scoped, query="first")["status"] == ("available" if duplicate else "partially_expired")


@pytest.mark.parametrize("empty", [None, {}])
def test_absent_history_remains_uninitialized(scoped, empty):
    from deerflow.agents.middlewares.durable_context_middleware import _render_durable_context_data

    rendered = _render_durable_context_data(None, [], [], {}, empty)
    assert '"history_status": "no_compaction_yet"' in rendered
    assert archive.lookup({"task_history": empty}, scoped, query="missing") == {"results": [], "status": "available"}
