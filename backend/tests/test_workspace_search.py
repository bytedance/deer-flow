"""Search must find the visible transcript, with the same owner and identity rules."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from langgraph.store.memory import InMemoryStore
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from deerflow.persistence.thread_meta.memory import MemoryThreadMetaStore
from deerflow.persistence.thread_meta.model import ThreadMetaRow
from deerflow.persistence.thread_meta.sql import ThreadMetaRepository
from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.runs.manager import EditReplayVisibility


@pytest.fixture(params=["memory", "sqlite"])
async def threads(request, tmp_path):
    if request.param == "memory":
        yield MemoryThreadMetaStore(InMemoryStore())
        return
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'threads.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(ThreadMetaRow.metadata.create_all)
    yield ThreadMetaRepository(async_sessionmaker(engine, expire_on_commit=False))
    await engine.dispose()


@pytest.mark.anyio
async def test_title_query_is_literal_unicode_and_precedes_pagination(threads):
    for thread_id, title in [("a", "旧调研报告"), ("b", "新调研报告"), ("c", "无关标题"), ("d", "Straße_100%")]:
        await threads.create(thread_id, display_name=title, user_id="alice")
    await threads.create("foreign", display_name="调研报告", user_id="bob")
    assert [r["thread_id"] for r in await threads.search(query="报告", user_id="alice", limit=1, offset=1)] == ["a"]
    assert [r["thread_id"] for r in await threads.search(query="STRASSE_100%", user_id="alice")] == ["d"]
    assert [r["thread_id"] for r in await threads.search(query="%", user_id="alice")] == ["d"]
    assert len(await threads.search(query="  ", user_id="alice")) == 4


@pytest.mark.anyio
async def test_search_corpus_hides_internal_and_superseded_text_and_normalizes_ids(threads):
    from app.gateway.search_corpus import GatewaySearchCorpus

    events = MemoryRunEventStore()
    manager = AsyncMock()
    manager.list_successful_regenerate_sources.return_value = {"old"}
    manager.list_edit_replay_visibility.return_value = EditReplayVisibility()
    await threads.create("t", user_id="alice", display_name="报告")
    for run, mid, kind, extra, caller, body in [
        ("r", "u__user", "human", {"original_user_content": "原始报告"}, "lead_agent", "注入的提示"),
        ("r", "a", "ai", {}, "lead_agent", "回答报告"),
        ("r", "hidden", "ai", {"hide_from_ui": True}, "lead_agent", "隐藏报告"),
        ("old", "old", "ai", {}, "lead_agent", "旧版本报告"),
        ("r", "sub", "ai", {}, "subagent:research", "子任务报告"),
        ("r", "tool", "tool", {}, "lead_agent", "工具日志报告"),
    ]:
        await events.put(thread_id="t", run_id=run, event_type="message", category="message", content={"id": mid, "type": kind, "content": body, "additional_kwargs": extra}, metadata={"caller": caller})
    corpus = GatewaySearchCorpus(threads, events, manager, "alice")
    thread = (await corpus.threads())[0]
    page = await corpus.messages(thread, before_seq=None)
    assert [(m.message_id, m.text) for m in page.items] == [("u", "原始报告"), ("a", "回答报告")]
    assert await GatewaySearchCorpus(threads, events, manager, "bob").threads() == ()
    assert (await GatewaySearchCorpus(threads, events, manager, "bob").messages(thread, before_seq=None)).items == ()


@pytest.mark.anyio
async def test_message_window_finds_unloaded_history_and_rejects_hidden_target(threads):
    from app.gateway.search_corpus import GatewaySearchCorpus

    events = MemoryRunEventStore()
    manager = AsyncMock()
    manager.list_successful_regenerate_sources.return_value = set()
    manager.list_edit_replay_visibility.return_value = EditReplayVisibility()
    await threads.create("t", user_id="alice")
    for i in range(140):
        await events.put(thread_id="t", run_id="r", event_type="message", category="message", content={"id": f"m-{i}", "type": "human" if i % 2 == 0 else "ai", "content": f"报告 {i}"})
    corpus = GatewaySearchCorpus(threads, events, manager, "alice")
    window = await corpus.around("t", "m-4", limit=3)
    assert window["target_seq"] == 5
    assert [r["seq"] for r in window["data"]] == list(range(2, 9))
    assert window["has_before"] and window["has_after"]
    manager.list_successful_regenerate_sources.return_value = {"r"}
    assert await corpus.around("t", "m-4", limit=3) is None
    assert await GatewaySearchCorpus(threads, events, manager, "bob").around("t", "m-4", limit=3) is None


@pytest.fixture
async def index(tmp_path, monkeypatch):
    from pathlib import Path

    from deerflow_extension_api import ExtensionRuntimeDeps

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "examples/deerflow-extension-workspace-search"))
    from deerflow_workspace_search.index import WorkspaceSearchIndex

    instance = WorkspaceSearchIndex(path=str(tmp_path / "search.db"), wait_seconds=10)
    await instance.start(ExtensionRuntimeDeps())
    yield instance
    await instance.stop()


def manager():
    result = AsyncMock()
    result.list_successful_regenerate_sources.return_value = set()
    result.list_edit_replay_visibility.return_value = EditReplayVisibility()
    return result


async def put(events, thread_id, message_id, body, *, run_id="r", extra=None):
    return await events.put(thread_id=thread_id, run_id=run_id, event_type="llm.ai.response", category="message", content={"id": message_id, "type": "ai", "content": body, "additional_kwargs": extra or {}})


@pytest.mark.anyio
@pytest.mark.parametrize("event_backend", ["memory", "jsonl", "sqlite"])
async def test_index_backfills_short_chinese_code_unicode_and_literal_punctuation(index, tmp_path, event_backend):
    from app.gateway.search_corpus import GatewaySearchCorpus
    from deerflow.persistence.models.run_event import RunEventRow
    from deerflow.runtime.events.store.db import DbRunEventStore
    from deerflow.runtime.events.store.jsonl import JsonlRunEventStore
    from deerflow.runtime.user_context import get_effective_user_id

    owner = str(get_effective_user_id())
    threads = MemoryThreadMetaStore(InMemoryStore())
    await threads.create("t", user_id=owner)
    engine = None
    if event_backend == "sqlite":
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'events.db'}")
        async with engine.begin() as connection:
            await connection.run_sync(RunEventRow.metadata.create_all)
        events = DbRunEventStore(async_sessionmaker(engine, expire_on_commit=False))
    else:
        events = MemoryRunEventStore() if event_backend == "memory" else JsonlRunEventStore(tmp_path / "events")
    try:
        for i in range(230):
            await put(events, "t", f"m-{i}", f"普通历史 {i}")
        await put(events, "t", "match", "旧版调研报告")
        await put(events, "t", "match", "调研报告 Straße parse_config_v2 100%_done ")
        await put(events, "t", "hidden", "机密报告", extra={"hide_from_ui": True})
        corpus = GatewaySearchCorpus(threads, events, manager(), owner)
        scope = await corpus.threads()
        for query in ["报告", "调研报告", "STRASSE", "parse_config_v2", "%_", "100%_done"]:
            page = await index.search(corpus, query=query, threads=scope, limit=10)
            assert not page.indexing
            assert [m.message_id for m in page.items] == ["match"]
            assert "旧版" not in page.items[0].text
        for query in ["机密", '" OR *', "100X_done"]:
            assert not (await index.search(corpus, query=query, threads=scope, limit=10)).items
    finally:
        if engine:
            await engine.dispose()


@pytest.mark.anyio
async def test_index_refreshes_regeneration_deletion_recreation_and_owner_scope(index):
    from app.gateway.search_corpus import GatewaySearchCorpus

    threads = MemoryThreadMetaStore(InMemoryStore())
    events = MemoryRunEventStore()
    runs = manager()
    await threads.create("t", user_id="alice")
    await threads.create("other", user_id="bob")
    await put(events, "t", "first", "报告第一版", run_id="old")
    await put(events, "other", "foreign", "报告秘密")
    corpus = GatewaySearchCorpus(threads, events, runs, "alice")

    async def search(query="报告", limit=10, cursor=None):
        return await index.search(corpus, query=query, threads=await corpus.threads(), limit=limit, cursor=cursor)

    assert [m.message_id for m in (await search()).items] == ["first"]
    await put(events, "t", "second", "报告第二版", run_id="new")
    runs.list_successful_regenerate_sources.return_value = {"old"}
    assert [m.message_id for m in (await search()).items] == ["second"]
    await threads.delete("t", user_id="alice")
    assert not (await search()).items
    await events.delete_by_thread("t", user_id="alice")
    await threads.create("t", user_id="alice")
    assert not (await search()).items


@pytest.mark.anyio
async def test_index_cursor_pages_every_match_and_rejects_another_query(index):
    from app.gateway.search_corpus import GatewaySearchCorpus

    threads = MemoryThreadMetaStore(InMemoryStore())
    await threads.create("t", user_id="alice")
    events = MemoryRunEventStore()
    for i in range(7):
        await put(events, "t", f"m-{i}", "报告")
    corpus = GatewaySearchCorpus(threads, events, manager(), "alice")
    scope = await corpus.threads()
    first = await index.search(corpus, query="报告", threads=scope, limit=2)
    assert first.cursor
    with pytest.raises(ValueError):
        await index.search(corpus, query="other", threads=scope, limit=2, cursor=first.cursor)
    ids = [m.message_id for m in first.items]
    page = first
    while page.cursor:
        page = await index.search(corpus, query="报告", threads=scope, limit=2, cursor=page.cursor)
        ids.extend(m.message_id for m in page.items)
    assert ids == [f"m-{i}" for i in reversed(range(7))]


@pytest.mark.anyio
async def test_http_search_and_jump_are_owner_bound_and_keep_title_contract(index):
    from types import SimpleNamespace
    from uuid import UUID

    from _router_auth_helpers import make_authed_test_app
    from httpx import ASGITransport, AsyncClient

    from app.gateway.auth.models import User
    from app.gateway.routers import search
    from app.gateway.routers import threads as thread_routes

    user = User(id=UUID("00000000-0000-0000-0000-000000000123"), email="search@example.com", password_hash="unused")
    app = make_authed_test_app(user_factory=lambda: user, bind_current_user=True)
    app.include_router(search.router)
    app.include_router(thread_routes.router)
    app.state.thread_store = MemoryThreadMetaStore(InMemoryStore())
    app.state.run_event_store = MemoryRunEventStore()
    app.state.run_manager = manager()
    app.state.extensions = SimpleNamespace(workspace_search_providers=(("test", index),))
    await app.state.thread_store.create("t", user_id=str(user.id), display_name="调研报告", assistant_id="researcher")
    await app.state.thread_store.create("other", user_id="bob", display_name="调研报告秘密")
    await put(app.state.run_event_store, "t", "old-message", "包含报告正文")
    await put(app.state.run_event_store, "other", "secret", "报告秘密")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        title = await client.post("/api/threads/search", json={"query": "报告"})
        assert title.status_code == 200
        assert [r["thread_id"] for r in title.json()] == ["t"]
        response = await client.post("/api/search", json={"query": "报告"})
        assert response.status_code == 200, response.text
        hits = response.json()["items"]
        assert [h["type"] for h in hits] == ["thread", "message"]
        assert all(h["agent_name"] == "researcher" for h in hits)
        assert hits[1]["snippet"][1] == {"text": "报告", "matched": True}
        jump = await client.get("/api/threads/t/messages/around", params={"message_id": "old-message", "seq": 1})
        assert jump.status_code == 200, jump.text
        assert jump.json()["messages"][0]["text"] == "包含报告正文"
        assert (await client.get("/api/threads/other/messages/around", params={"message_id": "secret"})).status_code in {403, 404}
        assert (await client.post("/api/search", json={"query": "报告", "cursor": "invalid"})).status_code == 400
        await app.state.thread_store.delete("t", user_id=str(user.id))
        assert not (await client.post("/api/search", json={"query": "报告"})).json()["items"]


def test_provider_registration_rolls_back_and_rejects_duplicates():
    from deerflow.extensions.registry import ExtensionRegistry

    registry = ExtensionRegistry()
    provider = AsyncMock()
    before = registry.mark()
    with registry.attributed_to("search"):
        assert registry.workspace_search(provider)
        with pytest.raises(ValueError):
            registry.workspace_search(provider)
    assert registry.build().workspace_search_providers == (("search", provider),)
    registry.rollback_to(before)
    assert registry.build().workspace_search_providers == ()


def test_snippet_preserves_unicode_expansions_and_never_returns_markup():
    from app.gateway.routers.search import snippet

    parts = snippet("前缀 Straße <script>alert(1)</script>", "STRASSE")
    assert parts[1] == {"text": "Straße", "matched": True}
    assert "".join(p["text"] for p in parts) == "前缀 Straße <script>alert(1)</script>"


@pytest.mark.anyio
async def test_search_projection_matches_chat_control_message_exclusions(index):
    from app.gateway.search_corpus import GatewaySearchCorpus

    threads = MemoryThreadMetaStore(InMemoryStore())
    events = MemoryRunEventStore()
    await threads.create("t", user_id="alice")
    for name in ("summary", "loop_warning", "todo_reminder", "todo_completion_reminder"):
        await events.put(thread_id="t", run_id="r", event_type="llm.ai.response", category="message", content={"type": "ai", "id": name, "name": name, "content": "hidden marker"})
    await events.put(thread_id="t", run_id="r", event_type="llm.human.input", category="message", content={"type": "human", "id": "activation", "content": "<slash_skill_activation>hidden marker</slash_skill_activation>"})
    await events.put(thread_id="t", run_id="r", event_type="llm.human.input", category="message", content={"type": "human", "id": "upload", "content": "user text<current_uploads>hidden marker</current_uploads>"})
    corpus = GatewaySearchCorpus(threads, events, manager(), "alice")
    scope = await corpus.threads()
    assert not (await index.search(corpus, query="hidden marker", threads=scope, limit=20)).items
    assert (await index.search(corpus, query="user text", threads=scope, limit=20)).items[0].text == "user text"


@pytest.mark.anyio
async def test_slow_backfill_is_reported_and_reused(index, monkeypatch):
    import asyncio
    from types import SimpleNamespace

    completed = asyncio.Event()
    refresh = AsyncMock(side_effect=lambda _: completed.wait())

    async def wait_for_release(_):
        await completed.wait()
        return True

    refresh.side_effect = wait_for_release
    monkeypatch.setattr(index, "_refresh", refresh)
    index.wait_seconds = 0.001
    corpus = SimpleNamespace(user_id="alice")
    pending = await index.search(corpus, query="报告", threads=(), limit=10)
    assert pending.indexing and not pending.items
    completed.set()
    index.wait_seconds = 10
    ready = await index.search(corpus, query="报告", threads=(), limit=10)
    assert not ready.indexing
    assert refresh.await_count == 1


@pytest.mark.anyio
async def test_route_filters_and_permission_boundary(monkeypatch, index):
    from types import SimpleNamespace

    import _router_auth_helpers as auth_helpers
    from httpx import ASGITransport, AsyncClient

    from app.gateway.auth.models import User
    from app.gateway.routers import search

    user = User(email="filters@example.com")
    app = auth_helpers.make_authed_test_app(user_factory=lambda: user, bind_current_user=True)
    app.include_router(search.router)
    app.state.thread_store = MemoryThreadMetaStore(InMemoryStore())
    app.state.run_event_store = MemoryRunEventStore()
    app.state.run_manager = manager()
    app.state.extensions = SimpleNamespace(workspace_search_providers=(("test", index),))
    for tid, meta in (("active", {}), ("archived", {"deerflow_archived": True}), ("project", {"deerflow_project_id": "p"}), ("sidecar", {"deerflow_sidecar": True})):
        await app.state.thread_store.create(tid, user_id=str(user.id), display_name="报告", metadata=meta)
        await put(app.state.run_event_store, tid, "m", "报告正文")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/search", json={"query": "报告", "archived": False, "project_id": None})
        assert response.status_code == 200, response.text
        assert [h["thread_id"] for h in response.json()["items"]] == ["active", "active"]
        monkeypatch.setattr(auth_helpers, "_STUB_PERMISSIONS", ["threads:read"])
        response = await client.post("/api/search", json={"query": "报告", "project_id": "p"})
        assert response.status_code == 200
        assert not response.json()["messages_available"]
        assert [h["type"] for h in response.json()["items"]] == ["thread"]
        assert (await client.get("/api/threads/project/messages/around?message_id=m")).status_code == 403
        monkeypatch.setattr(auth_helpers, "_STUB_PERMISSIONS", [])
        assert (await client.post("/api/search", json={"query": "报告"})).status_code == 403
