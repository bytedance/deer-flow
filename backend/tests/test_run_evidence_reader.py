from __future__ import annotations

import asyncio
import hashlib
from types import SimpleNamespace

import pytest
from deerflow_extension_api import ExtensionPrincipal, InvalidRunEvidenceCursor, require_run_evidence_reader, resolve_run_evidence_reader

from deerflow.extensions.run_evidence import StoreRunEvidenceReader, StoreRunEvidenceReaderFactory
from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.runs.store.memory import MemoryRunStore


async def _put_run(store: MemoryRunStore, run_id: str, thread_id: str, *, user_id: str = "user-1") -> None:
    await store.put(run_id, thread_id=thread_id, user_id=user_id)


@pytest.mark.asyncio
async def test_changed_run_cursor_pages_without_loss_and_replays_updates():
    runs = MemoryRunStore()
    events = MemoryRunEventStore()
    reader = StoreRunEvidenceReader(runs, events, user_id="user-1")
    await _put_run(runs, "run-a", "thread-a")
    await _put_run(runs, "run-b", "thread-b")

    first = await reader.list_changed_runs(cursor=None, limit=1)
    assert [item.run_id for item in first.items] == ["run-a"]
    assert first.has_more is True
    assert first.next_cursor

    await runs.update_status("run-a", "running")
    second = await reader.list_changed_runs(cursor=first.next_cursor, limit=10)
    assert [item.run_id for item in second.items] == ["run-b", "run-a"]
    assert second.has_more is False


@pytest.mark.asyncio
async def test_changed_run_reader_is_bound_to_one_user():
    runs = MemoryRunStore()
    events = MemoryRunEventStore()
    await _put_run(runs, "mine", "thread-1", user_id="user-1")
    await _put_run(runs, "theirs", "thread-2", user_id="user-2")

    page = await StoreRunEvidenceReader(runs, events, user_id="user-1").list_changed_runs(cursor=None, limit=10)
    assert [item.run_id for item in page.items] == ["mine"]


@pytest.mark.asyncio
async def test_event_pages_resume_and_status_is_authoritative():
    runs = MemoryRunStore()
    events = MemoryRunEventStore()
    await _put_run(runs, "run-a", "thread-a")
    await runs.update_status("run-a", "error", error="failed")
    for index in range(3):
        await events.put(
            thread_id="thread-a",
            run_id="run-a",
            event_type="test.event",
            category="trace",
            content={"index": index},
        )

    reader = StoreRunEvidenceReader(runs, events, user_id="user-1")
    first = await reader.list_run_events(thread_id="thread-a", run_id="run-a", after_seq=None, limit=2)
    assert [item.content for item in first.items] == [{"index": 0}, {"index": 1}]
    assert first.has_more is True
    second = await reader.list_run_events(
        thread_id="thread-a",
        run_id="run-a",
        after_seq=first.next_after_seq,
        limit=2,
    )
    assert [item.content for item in second.items] == [{"index": 2}]
    assert second.has_more is False

    status = await reader.get_run_status(thread_id="thread-a", run_id="run-a")
    assert status is not None
    assert status.status == "error"
    assert status.error == "failed"


@pytest.mark.asyncio
@pytest.mark.parametrize("event_backend", ["memory", "jsonl", "db"])
async def test_event_views_detach_nested_payloads_from_store(tmp_path, event_backend):
    engine = None
    runs = MemoryRunStore()
    if event_backend == "memory":
        events = MemoryRunEventStore()
    elif event_backend == "jsonl":
        from deerflow.runtime.events.store.jsonl import JsonlRunEventStore

        events = JsonlRunEventStore(tmp_path / "events")
    else:
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from deerflow.persistence.base import Base
        from deerflow.runtime.events.store.db import DbRunEventStore

        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'events.db'}")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        events = DbRunEventStore(async_sessionmaker(engine, expire_on_commit=False))

    await _put_run(runs, "run-a", "thread-a")
    try:
        await events.put(
            thread_id="thread-a",
            run_id="run-a",
            event_type="test.event",
            category="trace",
            content={"text": ["original"]},
            metadata={"custom": {"value": "original"}},
        )

        reader = StoreRunEvidenceReader(runs, events, user_id=None)
        page = await reader.list_run_events(thread_id="thread-a", run_id="run-a", after_seq=None, limit=10)
        page.items[0].content["text"][0] = "changed"
        page.items[0].metadata["custom"]["value"] = "changed"

        reread = await reader.list_run_events(thread_id="thread-a", run_id="run-a", after_seq=None, limit=10)
        stored = await events.list_events("thread-a", "run-a", user_id=None)
        assert reread.items[0].content == {"text": ["original"]}
        assert reread.items[0].metadata["custom"] == {"value": "original"}
        assert stored[0]["content"] == {"text": ["original"]}
        assert stored[0]["metadata"]["custom"] == {"value": "original"}
    finally:
        if engine is not None:
            await engine.dispose()


@pytest.mark.asyncio
async def test_db_event_reads_use_reader_scope_not_ambient_user(tmp_path):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from deerflow.persistence.base import Base
    from deerflow.persistence.run import RunRepository
    from deerflow.runtime import user_context
    from deerflow.runtime.events.store.db import DbRunEventStore

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'scoped-events.db'}")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        runs = RunRepository(factory)
        events = DbRunEventStore(factory)
        await runs.put("run-a", thread_id="thread-a", user_id="alice")

        alice_token = user_context.set_current_user(SimpleNamespace(id="alice"))
        try:
            await events.put(
                thread_id="thread-a",
                run_id="run-a",
                event_type="test.event",
                category="trace",
                content={"owner": "alice"},
            )
        finally:
            user_context.reset_current_user(alice_token)

        for ambient_user in (None, SimpleNamespace(id="bob")):
            ambient_token = user_context._current_user.set(ambient_user)
            try:
                for reader_user in (None, "alice"):
                    reader = StoreRunEvidenceReader(runs, events, user_id=reader_user)
                    page = await reader.list_run_events(
                        thread_id="thread-a",
                        run_id="run-a",
                        after_seq=None,
                        limit=10,
                    )
                    assert [item.content for item in page.items] == [{"owner": "alice"}]
            finally:
                user_context._current_user.reset(ambient_token)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reader_hides_runs_outside_scope_and_rejects_cursor_from_another_scope():
    runs = MemoryRunStore()
    events = MemoryRunEventStore()
    await _put_run(runs, "run-a", "thread-a", user_id="user-1")
    first = await StoreRunEvidenceReader(runs, events, user_id="user-1").list_changed_runs(cursor=None, limit=1)

    other = StoreRunEvidenceReader(runs, events, user_id="user-2")
    with pytest.raises(InvalidRunEvidenceCursor, match="cursor scope"):
        await other.list_changed_runs(cursor=first.next_cursor, limit=1)
    assert await other.get_run_status(thread_id="thread-a", run_id="run-a") is None
    assert (await other.list_run_events(thread_id="thread-a", run_id="run-a", after_seq=None, limit=10)).items == ()


@pytest.mark.asyncio
async def test_memory_fact_counts_reach_owner_evidence_and_reuse_the_frozen_snapshot(tmp_path, monkeypatch):
    from langchain.agents.middleware.types import ModelRequest, ModelResponse
    from langchain_core.language_models.fake_chat_models import FakeListChatModel
    from langchain_core.messages import AIMessage, HumanMessage, messages_from_dict, messages_to_dict
    from langgraph.graph.message import add_messages
    from langgraph.runtime import Runtime

    from deerflow.agents import memory
    from deerflow.agents.memory.backends.deermem.deer_mem import DeerMem
    from deerflow.agents.middlewares.dynamic_context_middleware import DynamicContextMiddleware
    from deerflow.config.app_config import AppConfig
    from deerflow.runtime.context_keys import CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY
    from deerflow.runtime.journal import RunJournal

    manager = DeerMem(backend_config={"storage_path": str(tmp_path / "memory"), "token_counting": "char", "max_injection_tokens": 100})
    selected_content = "first scoped fact " + "a" * 220
    withheld_content = "second scoped fact " + "b" * 220
    manager.create_fact(selected_content, confidence=0.9, user_id="user-1", agent_name="lead")
    manager.create_fact(withheld_content, confidence=0.8, user_id="user-1", agent_name="lead")
    manager.create_fact("another agent's fact", user_id="user-1", agent_name="other")
    manager.create_fact("another owner's fact", user_id="user-2", agent_name="lead")
    monkeypatch.setattr(memory, "get_memory_manager", lambda: manager)
    config = AppConfig(sandbox={"use": "deerflow.sandbox.local:LocalSandboxProvider"}, memory={"enabled": True, "injection_enabled": True})
    runs = MemoryRunStore()
    events = MemoryRunEventStore()
    readers = StoreRunEvidenceReaderFactory(runs, events)
    owner = readers.for_principal(ExtensionPrincipal(user_id="user-1"))
    outsider = readers.for_principal(ExtensionPrincipal(user_id="user-2"))
    model = FakeListChatModel(responses=["response"])
    delivered = []

    def model_handler(request):
        delivered.append(list(request.messages))
        return ModelResponse(result=[AIMessage(content="response")])

    await _put_run(runs, "fresh-run", "thread-a")
    journal = RunJournal("fresh-run", "thread-a", events)
    try:
        runtime = Runtime(context={"run_id": "fresh-run", "user_id": "user-1", "__run_journal": journal})
        middleware = DynamicContextMiddleware(agent_name="lead", app_config=config)
        initial = [HumanMessage(content="Use what you remember", id="first-user")]
        update = middleware.before_agent({"messages": initial}, runtime)
        messages = add_messages(initial, update["messages"])
        memory_message = next(message for message in messages if str(message.id).endswith("__memory"))
        request = ModelRequest(model=model, messages=messages, runtime=runtime, tools=[])
        middleware.wrap_model_call(request, model_handler)
        middleware.wrap_model_call(request, model_handler)
        await journal.flush()

        page = await owner.list_run_events(thread_id="thread-a", run_id="fresh-run", after_seq=None, limit=10)
        assert len(page.items) == 1
        event = page.items[0]
        assert event.event_type == "context:memory"
        assert event.category == "context"
        fingerprint = hashlib.sha256(memory_message.content.encode("utf-8")).hexdigest()
        assert event.content == {
            "content_sha256": fingerprint,
            "project_context_revision": None,
            "project_shelf_revision": None,
            "memory_injection": {"status": "fresh", "eligible": 2, "selected": 1, "injected": 1, "withheld": 1},
        }
        assert selected_content in memory_message.content
        assert withheld_content not in memory_message.content
        assert all(any(message.content == memory_message.content for message in request_messages) for request_messages in delivered)
        assert (await outsider.list_run_events(thread_id="thread-a", run_id="fresh-run", after_seq=None, limit=10)).items == ()
    finally:
        await journal.close()

    manager.create_fact("new fact after the frozen snapshot", confidence=0.95, user_id="user-1", agent_name="lead")
    assert len(manager.get_memory(user_id="user-1", agent_name="lead")["facts"]) == 3
    messages = messages_from_dict(messages_to_dict(messages))
    reloads = []

    def reject_backend_reload():
        reloads.append("reload")
        raise AssertionError("A reused snapshot must not consult the memory backend")

    monkeypatch.setattr(memory, "get_memory_manager", reject_backend_reload)
    await _put_run(runs, "reused-run", "thread-a")
    journal = RunJournal("reused-run", "thread-a", events)
    try:
        runtime = Runtime(
            context={
                "run_id": "reused-run",
                "user_id": "user-1",
                "__run_journal": journal,
                CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY: frozenset(message.id for message in messages),
            }
        )
        middleware = DynamicContextMiddleware(agent_name="lead", app_config=config)
        messages = add_messages(messages, [AIMessage(content="response"), HumanMessage(content="Continue", id="second-user")])
        update = middleware.before_agent({"messages": messages}, runtime)
        if update is not None:
            messages = add_messages(messages, update["messages"])
        request = ModelRequest(model=model, messages=messages, runtime=runtime, tools=[])
        middleware.wrap_model_call(request, model_handler)
        middleware.wrap_model_call(request, model_handler)
        await journal.flush()

        page = await owner.list_run_events(thread_id="thread-a", run_id="reused-run", after_seq=None, limit=10)
        assert len(page.items) == 1
        assert page.items[0].content == {
            "content_sha256": fingerprint,
            "project_context_revision": None,
            "project_shelf_revision": None,
            "memory_injection": {"status": "reused", "eligible": 2, "selected": 1, "injected": 1, "withheld": 1},
        }
        assert reloads == []
        assert "new fact after the frozen snapshot" not in "\n".join(str(message.content) for message in delivered[-1])
        assert (await outsider.list_run_events(thread_id="thread-a", run_id="reused-run", after_seq=None, limit=10)).items == ()
    finally:
        await journal.close()


@pytest.mark.parametrize(
    "principal",
    [None, SimpleNamespace(user_id="user-1"), *[ExtensionPrincipal(user_id=value) for value in (None, 1, "", " \t", " user-1", "user-1 ", "\tuser-1\n")]],
)
def test_reader_factory_rejects_invalid_principals(principal):
    factory = StoreRunEvidenceReaderFactory(MemoryRunStore(), MemoryRunEventStore())
    with pytest.raises(ValueError, match="principal"):
        factory.for_principal(principal)


def test_request_resolver_binds_reader_to_principal_and_fails_when_unavailable():
    runs = MemoryRunStore()
    events = MemoryRunEventStore()
    factory = StoreRunEvidenceReaderFactory(runs, events)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(deerflow_extension_run_evidence_reader_resolver=lambda _request: factory.for_principal(ExtensionPrincipal(user_id="user-1")))))

    reader = resolve_run_evidence_reader(request)
    assert isinstance(reader, StoreRunEvidenceReader)
    assert reader._user_id == "user-1"

    unsupported = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    assert resolve_run_evidence_reader(unsupported) is None
    with pytest.raises(NotImplementedError, match="unavailable"):
        require_run_evidence_reader(unsupported)


@pytest.mark.asyncio
async def test_memory_progress_updates_do_not_advance_changed_run_cursor():
    runs = MemoryRunStore()
    reader = StoreRunEvidenceReader(runs, MemoryRunEventStore(), user_id="user-1")
    await _put_run(runs, "run-a", "thread-a")
    await runs.start_run("run-a")
    before_progress = await reader.list_changed_runs(cursor=None, limit=10)

    await runs.update_run_progress("run-a", total_tokens=10, last_ai_message="working")

    after_progress = await reader.list_changed_runs(cursor=before_progress.next_cursor, limit=10)
    assert after_progress.items == ()
    assert after_progress.next_cursor == before_progress.next_cursor


@pytest.mark.asyncio
async def test_sql_changed_run_cursor_survives_repository_restart(tmp_path):
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
    from deerflow.persistence.run import RunRepository

    url = f"sqlite+aiosqlite:///{tmp_path / 'evidence.db'}"
    await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
    try:
        repo = RunRepository(get_session_factory())
        await repo.put("run-a", thread_id="thread-a", user_id="user-1")
        reader = StoreRunEvidenceReader(repo, MemoryRunEventStore(), user_id="user-1")
        first = await reader.list_changed_runs(cursor=None, limit=1)
        await repo.put("run-b", thread_id="thread-b", user_id="user-1")
        cursor = first.next_cursor
    finally:
        await close_engine()

    await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
    try:
        restarted = StoreRunEvidenceReader(
            RunRepository(get_session_factory()),
            MemoryRunEventStore(),
            user_id="user-1",
        )
        page = await restarted.list_changed_runs(cursor=cursor, limit=10)
        assert [item.run_id for item in page.items] == ["run-b"]
    finally:
        await close_engine()


@pytest.mark.asyncio
async def test_sql_progress_updates_do_not_advance_changed_run_cursor(tmp_path):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from deerflow.persistence.base import Base
    from deerflow.persistence.run import RunRepository

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'progress.db'}")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        repo = RunRepository(async_sessionmaker(engine, expire_on_commit=False))
        await repo.put("run-a", thread_id="thread-a", user_id="user-1")
        await repo.start_run("run-a")
        reader = StoreRunEvidenceReader(repo, MemoryRunEventStore(), user_id="user-1")
        before_progress = await reader.list_changed_runs(cursor=None, limit=10)

        await repo.update_run_progress("run-a", total_tokens=10, last_ai_message="working")

        after_progress = await reader.list_changed_runs(cursor=before_progress.next_cursor, limit=10)
        assert after_progress.items == ()
        assert after_progress.next_cursor == before_progress.next_cursor
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_sql_atomic_interrupt_allocates_before_run_lock_and_shares_position(tmp_path):
    from sqlalchemy import event
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from deerflow.persistence.base import Base
    from deerflow.persistence.run import RunRepository

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'atomic.db'}")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        repo = RunRepository(async_sessionmaker(engine, expire_on_commit=False))
        await repo.put(
            "run-old",
            thread_id="thread-a",
            user_id="user-1",
            status="running",
            owner_worker_id="worker-1",
        )
        statements: list[str] = []

        @event.listens_for(engine.sync_engine, "before_cursor_execute")
        def capture_statement(_connection, _cursor, statement, _parameters, _context, _executemany):
            statements.append(" ".join(statement.lower().split()))

        new_run, claimed = await repo.create_thread_operation_atomic(
            "run-new",
            thread_id="thread-a",
            user_id="user-1",
            owner_worker_id="worker-1",
            lease_expires_at=None,
            multitask_strategy="interrupt",
        )

        assert [run["run_id"] for run in claimed] == ["run-old"]
        assert claimed[0]["change_seq"] == new_run["change_seq"]
        clock_update = next(index for index, statement in enumerate(statements) if statement.startswith("update run_change_clock"))
        run_lock_query = next(index for index, statement in enumerate(statements) if statement.startswith("select runs."))
        assert clock_update < run_lock_query
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_sql_change_positions_are_unique_across_concurrent_threads(tmp_path):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from deerflow.persistence.base import Base
    from deerflow.persistence.run import RunRepository

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'concurrent.db'}")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        repositories = [RunRepository(factory) for _ in range(12)]
        await asyncio.gather(
            *(
                repository.put(
                    f"run-{index:02d}",
                    thread_id=f"thread-{index:02d}",
                    user_id="user-1",
                )
                for index, repository in enumerate(repositories)
            )
        )

        rows = await repositories[0].list_changed(
            after_change_seq=-1,
            after_run_id="",
            user_id="user-1",
            limit=20,
        )
        positions = [row["change_seq"] for row in rows]
        assert len(rows) == 12
        assert positions == sorted(positions)
        assert len(set(positions)) == len(positions)
    finally:
        await engine.dispose()
