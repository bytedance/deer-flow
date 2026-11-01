"""Gateway history backfills must remain usable with strict producer fencing."""

from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from _agent_e2e_helpers import FakeToolCallingModel
from _router_auth_helpers import make_authed_test_app
from fastapi import Request
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from support.postgres import asyncpg_test_url
from test_threads_router import _patch_checkpoint_state_builder as _patch_checkpoint_state_builder
from test_threads_router import _RawStateAccessor, _write_checkpoint

from app.gateway import services
from app.gateway.auth.models import User
from app.gateway.routers import threads
from app.gateway.routers.thread_runs import RunCreateRequest
from deerflow.config import paths as paths_module
from deerflow.config.app_config import AppConfig, pop_current_app_config, push_current_app_config
from deerflow.config.paths import Paths
from deerflow.persistence.models.run_event import RunEventRow, RunEventThreadSeqRow
from deerflow.persistence.projects import ProjectRepository
from deerflow.persistence.run.model import CompletedRunSnapshotRow, RunChangeClockRow, RunProducerPolicyRow, RunRow
from deerflow.persistence.run.sql import RunRepository
from deerflow.persistence.thread_meta import ThreadMetaRepository
from deerflow.persistence.thread_meta.model import ThreadMetaRow
from deerflow.runtime import ConflictError, RunManager, RunStatus
from deerflow.runtime.events.producer import RunEventProducerRejected
from deerflow.runtime.events.store.db import DbRunEventStore
from deerflow.runtime.stream_bridge.memory import MemoryStreamBridge
from deerflow.runtime.user_context import reset_current_user, set_current_user


@pytest_asyncio.fixture
async def history_gateway(monkeypatch, tmp_path):
    uri = os.environ.get("TEST_POSTGRES_URI")
    if not uri:
        pytest.skip("requires TEST_POSTGRES_URI")
    schema = "history_seed_" + uuid4().hex
    engine = create_async_engine(asyncpg_test_url(uri), connect_args={"server_settings": {"search_path": schema}})
    sf = async_sessionmaker(engine, expire_on_commit=False)
    tables = [RunRow.__table__, RunChangeClockRow.__table__, RunEventRow.__table__, RunEventThreadSeqRow.__table__, CompletedRunSnapshotRow.__table__, RunProducerPolicyRow.__table__, ThreadMetaRow.__table__]
    manager = None
    try:
        async with engine.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            await conn.run_sync(lambda c: RunRow.metadata.create_all(c, tables=tables))
            await conn.execute(text("INSERT INTO run_producer_policy(id,strict,cutover_id) VALUES (1,true,'history-seed-test')"))
        events = DbRunEventStore(sf, producer_fencing="strict", producer_cutover_id="history-seed-test")
        await events.validate_producer_fencing()
        runs = RunRepository(sf)
        manager = RunManager(store=runs, event_store=events, worker_id="history-seed-worker")
        user = User(id=uuid4(), email="history-seed@example.com", password_hash="unused", system_role="user")
        app = make_authed_test_app(user_factory=lambda: user, bind_current_user=True)
        app.state.thread_store = ThreadMetaRepository(sf)
        app.state.run_manager = manager
        app.state.run_event_store = events
        app.state.checkpointer = InMemorySaver()
        app.state.store = InMemoryStore()
        app.state.project_repo = ProjectRepository(sf)
        app.state.stream_bridge = MemoryStreamBridge()
        app.include_router(threads.router)
        monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path / "home"))
        monkeypatch.setattr(paths_module, "_paths", Paths(tmp_path / "home"))
        extensions_path = tmp_path / "extensions_config.json"
        extensions_path.write_text('{"mcpServers": {}, "skills": {}}', encoding="utf-8")
        monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))
        config = AppConfig.model_validate(
            {
                "models": [{"name": "history-test-model", "use": "langchain_openai:ChatOpenAI", "model": "unused", "api_key": "unused"}],
                "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
                "skills": {"path": str(tmp_path / "skills")},
                "title": {"enabled": False},
                "memory": {"enabled": False},
                "run_events": {"backend": "db", "producer_fencing": "strict", "producer_cutover_id": "history-seed-test"},
            }
        )
        app.state.run_events_config = config.run_events

        def accessor(request, *, thread_id, assistant_id=None, checkpoint_id=None):
            config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
            if checkpoint_id is not None:
                config["configurable"]["checkpoint_id"] = checkpoint_id
            return _RawStateAccessor(request.app.state.checkpointer), config

        monkeypatch.setattr(services, "build_checkpoint_state_accessor", accessor)
        token = set_current_user(user)
        push_current_app_config(config)
        try:
            yield SimpleNamespace(app=app, sf=sf, runs=runs, events=events, manager=manager, user=user, user_id=str(user.id))
        finally:
            try:
                await manager.shutdown()
            finally:
                manager = None
                await app.state.stream_bridge.close()
                pop_current_app_config()
                reset_current_user(token)
    finally:
        if manager is not None:
            await manager.shutdown()
        try:
            async with engine.begin() as conn:
                await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        finally:
            await engine.dispose()


def _request(db):
    request = Request({"type": "http", "app": db.app, "method": "POST", "path": "/", "headers": []})
    request.state.user = db.user
    return request


async def _wait_for_gate(event, task):
    waiter = asyncio.create_task(event.wait())
    try:
        done, _ = await asyncio.wait((waiter, task), timeout=5, return_when=asyncio.FIRST_COMPLETED)
        if task in done:
            await task
        assert waiter in done, "history seed did not reach the observation gate"
    finally:
        waiter.cancel()
        await asyncio.gather(waiter, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("metadata_state", ["current", "absent", "null_incarnation"])
@pytest.mark.parametrize("turns", [1, 2])
@pytest.mark.parametrize("ownerless", [False, True], ids=["owned", "ownerless"])
async def test_strict_checkpoint_only_history_is_seeded(history_gateway, metadata_state, turns, ownerless):
    db = history_gateway
    thread_id = "checkpoint-only"
    owner = None if ownerless else db.user_id
    if metadata_state != "absent":
        await db.app.state.thread_store.create(thread_id, user_id=owner)
        if metadata_state == "null_incarnation":
            async with db.sf() as session:
                await session.execute(update(ThreadMetaRow).where(ThreadMetaRow.thread_id == thread_id).values(incarnation=None))
                await session.commit()
    messages = [HumanMessage(id="h1", content="old question"), AIMessage(id="a1", content="old answer")]
    if turns == 2:
        messages.extend([HumanMessage(id="h2", content="another question"), AIMessage(id="a2", content="another answer")])
    await _write_checkpoint(
        db.app.state.checkpointer,
        thread_id,
        "legacy-head",
        messages,
        step=1,
    )
    request = _request(db)

    token = set_current_user(None) if ownerless else None
    try:
        await services.ensure_checkpoint_history_seeded(request, thread_id=thread_id, assistant_id=None)
        rows = await db.events.list_messages(thread_id, user_id=None)
        await services.ensure_checkpoint_history_seeded(request, thread_id=thread_id, assistant_id=None)
        assert await db.events.list_messages(thread_id, user_id=None) == rows
    finally:
        if token is not None:
            reset_current_user(token)

    assert [row["content"]["id"] for row in rows] == ["h1", "a1", "h2", "a2"][: 2 * turns]
    assert all(row["metadata"]["checkpoint_history_seed"] is True for row in rows)
    assert [row["run_id"] for row in rows] == [f"checkpoint-seed-{thread_id}-{turn}" for turn in range(1, turns + 1) for _ in range(2)]
    assert [row["seq"] for row in rows] == list(range(1, 2 * turns + 1))
    assert all(row["user_id"] == owner for row in rows)
    metadata = await db.app.state.thread_store.get(thread_id, user_id=None)
    assert metadata is not None
    assert metadata["user_id"] == owner
    if metadata_state == "null_incarnation":
        assert metadata["incarnation"] is None
    async with db.sf() as session:
        assert await session.scalar(select(RunRow.run_id).where(RunRow.thread_id == thread_id)) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("turns", [1, 2])
async def test_strict_branch_history_is_seeded(history_gateway, turns):
    db = history_gateway
    source_id = "branch-source"
    await db.app.state.thread_store.create(source_id)
    messages = []
    parent_config = None
    for turn in range(1, turns + 2):
        messages.extend([HumanMessage(id=f"h{turn}", content=f"question {turn}"), AIMessage(id=f"a{turn}", content=f"answer {turn}")])
        parent_config = await _write_checkpoint(db.app.state.checkpointer, source_id, f"turn-{turn}", list(messages), step=turn, parent_config=parent_config)

    async with AsyncClient(transport=ASGITransport(app=db.app), base_url="http://test") as client:
        response = await client.post(f"/api/threads/{source_id}/branches", json={"message_id": f"a{turns}"})

    assert response.status_code == 200, response.text
    branch = response.json()
    assert branch["history_seed_mode"] == "seeded", branch
    rows = await db.events.list_messages(branch["thread_id"], user_id=db.user_id)
    assert [row["content"]["id"] for row in rows] == [f"{role}{turn}" for turn in range(1, turns + 1) for role in ("h", "a")]
    assert [row["run_id"] for row in rows] == [f"branch-seed-{branch['thread_id']}-{turn}" for turn in range(1, turns + 1) for _ in range(2)]
    assert all(row["metadata"]["branch_parent_thread_id"] == source_id for row in rows)


@pytest.mark.asyncio
@pytest.mark.parametrize("turns", [1, 2])
async def test_strict_first_branch_run_is_admitted_with_inherited_history(history_gateway, monkeypatch, turns):
    from deerflow.agents.lead_agent import agent as lead_agent

    db = history_gateway
    # The raw router helper uses integer channel versions. Let the real
    # mutation graph write the branch consumed by the real agent graph.
    monkeypatch.setattr(threads, "build_checkpoint_state_mutation_accessor", services.build_checkpoint_state_mutation_accessor)
    source_id = "first-run-source"
    await db.app.state.thread_store.create(source_id)
    messages = [HumanMessage(id="h1", content="old question"), AIMessage(id="a1", content="old answer")]
    if turns == 2:
        messages.extend([HumanMessage(id="h2", content="second question"), AIMessage(id="a2", content="second answer")])
    parent_config = await _write_checkpoint(db.app.state.checkpointer, source_id, "inherited-turn", messages, step=turns)
    await _write_checkpoint(
        db.app.state.checkpointer,
        source_id,
        "later-turn",
        [*messages, HumanMessage(id="later-human", content="later question"), AIMessage(id="later-ai", content="later answer")],
        step=turns + 1,
        parent_config=parent_config,
    )
    async with AsyncClient(transport=ASGITransport(app=db.app), base_url="http://test") as client:
        response = await client.post(f"/api/threads/{source_id}/branches", json={"message_id": f"a{turns}"})
    assert response.status_code == 200, response.text
    branch = response.json()
    model = FakeToolCallingModel(responses=[AIMessage(id="new-ai", content="new answer")])
    monkeypatch.setattr(lead_agent, "create_chat_model", lambda **kwargs: model)

    record = await services.start_run(
        RunCreateRequest(assistant_id="lead_agent", input={"messages": [{"role": "user", "id": "new-human", "content": "new question"}]}, context={"thinking_enabled": False}),
        branch["thread_id"],
        _request(db),
    )
    assert record.task is not None
    await asyncio.wait_for(asyncio.shield(record.task), timeout=15)

    durable = await db.runs.get(record.run_id, user_id=db.user_id)
    assert durable["status"] == RunStatus.success.value, durable
    assert branch["history_seed_mode"] == "seeded", branch
    rows = await db.events.list_messages(branch["thread_id"], user_id=db.user_id)
    inherited = ["h1", "a1", "h2", "a2"][: 2 * turns]
    assert [row["content"]["id"] for row in rows] == [*inherited, "new-human__user", "new-ai"]
    assert [row["run_id"] for row in rows[2 * turns :]] == [record.run_id, record.run_id]
    assert all(row["metadata"]["branch_seed"] is True for row in rows[: 2 * turns])
    assert all(row["user_id"] == db.user_id for row in rows)
    async with db.sf() as session:
        assert list(await session.scalars(select(RunRow.run_id).where(RunRow.thread_id == branch["thread_id"]))) == [record.run_id]


@pytest.mark.asyncio
async def test_checkpoint_seed_rechecks_stale_empty_feed_across_managers(history_gateway, monkeypatch):
    db = history_gateway
    thread_id = "concurrent-checkpoint-only"
    await _write_checkpoint(
        db.app.state.checkpointer,
        thread_id,
        "legacy-head",
        [HumanMessage(id="h1", content="first"), AIMessage(id="a1", content="answer one"), HumanMessage(id="h2", content="second"), AIMessage(id="a2", content="answer two")],
        step=1,
    )
    peer_events = DbRunEventStore(db.sf, producer_fencing="strict", producer_cutover_id="history-seed-test")
    peer_manager = RunManager(store=RunRepository(db.sf), event_store=peer_events, worker_id="history-seed-peer")
    peer = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(**db.app.state._state)), user=db.user)
    peer.app.state.run_manager = peer_manager
    peer.app.state.run_event_store = peer_events
    empty_observed = asyncio.Event()
    release_probe = asyncio.Event()
    list_messages = peer_events.list_messages

    async def pause_first_empty_probe(*args, **kwargs):
        rows = await list_messages(*args, **kwargs)
        if not empty_observed.is_set():
            assert rows == []
            empty_observed.set()
            await release_probe.wait()
        return rows

    monkeypatch.setattr(peer_events, "list_messages", pause_first_empty_probe)
    pending = asyncio.create_task(services.ensure_checkpoint_history_seeded(_request(peer), thread_id=thread_id, assistant_id=None))
    try:
        await _wait_for_gate(empty_observed, pending)
        assert await db.app.state.thread_store.get(thread_id, user_id=None) is None
        await services.ensure_checkpoint_history_seeded(_request(db), thread_id=thread_id, assistant_id=None)
        metadata = await db.app.state.thread_store.get(thread_id, user_id=None)
        assert metadata is not None
        rows = await db.events.list_messages(thread_id, user_id=None)
        assert [row["content"]["id"] for row in rows] == ["h1", "a1", "h2", "a2"]

        release_probe.set()
        await asyncio.wait_for(asyncio.shield(pending), timeout=5)

        assert await peer_events.list_messages(thread_id, user_id=None) == rows
        assert await db.app.state.thread_store.get(thread_id, user_id=None) == metadata
        async with db.sf() as session:
            assert await session.scalar(select(RunRow.run_id).where(RunRow.thread_id == thread_id)) is None
    finally:
        release_probe.set()
        await asyncio.wait_for(asyncio.gather(pending, return_exceptions=True), timeout=5)
        await peer_manager.shutdown()


@pytest.mark.asyncio
async def test_checkpoint_seed_rejects_metadata_replaced_after_snapshot_read(history_gateway, monkeypatch):
    db = history_gateway
    thread_id = "recreated-checkpoint-thread"
    original = await db.app.state.thread_store.create(thread_id)
    await _write_checkpoint(db.app.state.checkpointer, thread_id, "legacy-head", [HumanMessage(id="h1", content="old question"), AIMessage(id="a1", content="old answer")], step=1)
    snapshot_read = asyncio.Event()
    release_snapshot = asyncio.Event()
    build_accessor = services.abuild_checkpoint_state_accessor

    async def pause_after_snapshot(request, **kwargs):
        accessor, config = await build_accessor(request, **kwargs)
        if request.app is not db.app:
            return accessor, config
        read = accessor.aget

        async def gated_read(config):
            snapshot = await read(config)
            async with db.sf() as session:
                reservation = await session.scalar(select(RunRow.run_id).where(RunRow.thread_id == thread_id, RunRow.operation_kind == "checkpoint_write", RunRow.status == "pending"))
            if reservation is None:
                return snapshot
            snapshot_read.set()
            await release_snapshot.wait()
            return snapshot

        monkeypatch.setattr(accessor, "aget", gated_read)
        return accessor, config

    monkeypatch.setattr(services, "abuild_checkpoint_state_accessor", pause_after_snapshot)
    pending = asyncio.create_task(services.ensure_checkpoint_history_seeded(_request(db), thread_id=thread_id, assistant_id=None))
    peer_manager = RunManager(store=RunRepository(db.sf), event_store=DbRunEventStore(db.sf, producer_fencing="strict"), worker_id="history-seed-peer")
    try:
        await _wait_for_gate(snapshot_read, pending)
        # A second Gateway must respect the reservation around the real read.
        peer = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(**db.app.state._state)), user=db.user)
        peer.app.state.run_manager = peer_manager
        with pytest.raises(ConflictError):
            await services.ensure_checkpoint_history_seeded(_request(peer), thread_id=thread_id, assistant_id=None)
        await db.app.state.thread_store.delete(thread_id)
        replacement = await db.app.state.thread_store.create(thread_id)
        assert replacement["incarnation"] != original["incarnation"]

        release_snapshot.set()
        with pytest.raises(RunEventProducerRejected):
            await asyncio.wait_for(asyncio.shield(pending), timeout=5)

        assert await db.events.list_messages(thread_id, user_id=None) == []
        assert await db.app.state.thread_store.get(thread_id, user_id=None) == replacement
        async with db.sf() as session:
            assert await session.scalar(select(RunEventThreadSeqRow.seq).where(RunEventThreadSeqRow.thread_id == thread_id)) is None
            assert await session.scalar(select(RunRow.run_id).where(RunRow.thread_id == thread_id)) is None
    finally:
        release_snapshot.set()
        await asyncio.wait_for(asyncio.gather(pending, return_exceptions=True), timeout=5)
        await peer_manager.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("empty_checkpoint", [False, True])
async def test_no_history_does_not_reserve_an_active_thread(history_gateway, empty_checkpoint):
    db = history_gateway
    record = await db.manager.create_or_reject("fresh-active-thread", user_id=db.user_id)
    if empty_checkpoint:
        await _write_checkpoint(db.app.state.checkpointer, record.thread_id, "empty-head", [], step=-1)
    await services.ensure_checkpoint_history_seeded(_request(db), thread_id=record.thread_id, assistant_id=None)
    assert await db.events.list_messages(record.thread_id, user_id=None) == []
    async with db.sf() as session:
        assert list(await session.scalars(select(RunRow.run_id).where(RunRow.thread_id == record.thread_id))) == [record.run_id]
