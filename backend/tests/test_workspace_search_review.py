"""Review regressions use real message stores and the SQL index."""

import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langgraph.store.memory import InMemoryStore
from sqlalchemy import event
from test_workspace_search import index, manager, put  # noqa: F401

from app.gateway.search_corpus import GatewaySearchCorpus
from deerflow.persistence.thread_meta.memory import MemoryThreadMetaStore
from deerflow.runtime.events.store.memory import MemoryRunEventStore


@pytest.mark.anyio
async def test_latest_versions_cross_pages_and_single_thread_lookup(monkeypatch):
    from app.gateway.routers import search

    threads = MemoryThreadMetaStore(InMemoryStore())
    events = MemoryRunEventStore()
    await threads.create("t", user_id="alice")
    await put(events, "t", "same", "obsolete needle")
    for number in range(220):
        await put(events, "t", f"middle-{number}", "context")
    await put(events, "t", "same", "current answer")
    corpus = GatewaySearchCorpus(threads, events, manager(), "alice")
    thread = await corpus.thread("t")
    assert (await corpus.latest_message(thread, "same")).text == "current answer"
    assert await corpus.around("t", "same", seq=1) is None
    window = await corpus.around("t", "same", seq=222, limit=50)
    assert len({row["content"]["id"] for row in window["data"]}) == len(window["data"])
    assert "obsolete needle" not in str(window)
    threads.search = AsyncMock(side_effect=AssertionError("jump must not enumerate other threads"))
    monkeypatch.setattr(search, "_corpus", lambda request: corpus)
    result = await inspect.unwrap(search.message_context)("t", SimpleNamespace(), message_id="same", seq=222, limit=5)
    assert result["target_seq"] == 222
    threads.search.assert_not_called()


@pytest.mark.anyio
async def test_provider_bounds_membership_parameters(index):  # noqa: F811
    from deerflow_extension_api.search import SearchMessage, SearchThread

    threads = tuple(SearchThread(f"t-{i}", "v1", "Title", "2026-01-01") for i in range(1200))
    await index._replace("alice", threads[-1], "revision", [SearchMessage(threads[-1].thread_id, "v1", "message", "run", 1, "assistant", "needle", "2026-01-01")])
    index._refresh = AsyncMock(return_value=True)
    counts = []

    def record(connection, cursor, statement, parameters, context, executemany):
        if "extension_workspace_search_documents" in statement:
            counts.append(len(parameters))

    event.listen(index._engine.sync_engine, "before_cursor_execute", record)
    try:
        result = await index.search(SimpleNamespace(user_id="alice"), query="needle", threads=threads, limit=20)
        assert [item.thread_id for item in result.items] == [threads[-1].thread_id]
        assert max(counts) < 300
    finally:
        event.remove(index._engine.sync_engine, "before_cursor_execute", record)


@pytest.mark.anyio
async def test_fts_startup_skips_clean_rebuild_and_repairs_fallback_writes(index):  # noqa: F811
    from deerflow_extension_api import ExtensionRuntimeDeps
    from deerflow_extension_api.search import SearchMessage, SearchThread

    if not index._fts:
        pytest.skip("SQLite has no trigram FTS")
    thread = SearchThread("t", "v1", "Title", "2026-01-01")

    def message(body):
        return SearchMessage("t", "v1", "message", "run", 1, "assistant", body, "2026-01-01")

    await index._replace("alice", thread, "one", [message("old needle")])
    await index.stop()
    original = index.__class__(path=index.path)
    await original.start(ExtensionRuntimeDeps())
    original._owns_engine = False
    sf = original._sf
    statements = []
    event.listen(original._engine.sync_engine, "before_cursor_execute", lambda c, cu, sql, p, ctx, many: statements.append(sql))
    try:
        await original.start(ExtensionRuntimeDeps(session_factory=sf))
        assert not any(sql.strip() == "DELETE FROM extension_workspace_search_fts" for sql in statements)
        original._fts = False
        await original._replace("alice", thread, "two", [message("fresh needle")])
        statements.clear()
        await original.start(ExtensionRuntimeDeps(session_factory=sf))
        assert any(sql.strip() == "DELETE FROM extension_workspace_search_fts" for sql in statements)
        original._refresh = AsyncMock(return_value=True)
        result = await original.search(SimpleNamespace(user_id="alice"), query="fresh", threads=(thread,), limit=20)
        assert [item.text for item in result.items] == ["fresh needle"]
    finally:
        await original.stop()
        await original._engine.dispose()


@pytest.mark.anyio
async def test_legacy_checkpoint_is_seeded_before_revision_completion(monkeypatch):
    from langchain_core.messages import HumanMessage
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, MessagesState, StateGraph

    from app.gateway import services

    saver = InMemorySaver()
    builder = StateGraph(MessagesState)
    builder.add_edge(START, END)
    graph = builder.compile(checkpointer=saver)
    config = {"configurable": {"thread_id": "legacy"}}
    await graph.ainvoke({"messages": [HumanMessage(content="legacy needle", id="old")]}, config)
    threads = MemoryThreadMetaStore(InMemoryStore())
    await threads.create("legacy", user_id="alice")
    events = MemoryRunEventStore()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(run_event_store=events, checkpointer=saver)))
    monkeypatch.setattr(services, "abuild_checkpoint_state_accessor", AsyncMock(return_value=(SimpleNamespace(aget=graph.aget_state), config)))
    corpus = GatewaySearchCorpus(threads, events, manager(), "alice", request=request)
    thread = await corpus.thread("legacy")
    assert await corpus.revision(thread)
    assert [message.text for message in (await corpus.messages(thread, before_seq=None)).items] == ["legacy needle"]
    assert (await corpus.around("legacy", "old"))["target_seq"] > 0
