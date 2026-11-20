"""Terminal singleton confirmation across supported event stores."""

from __future__ import annotations

import asyncio
import os
from copy import copy, deepcopy
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from support.postgres import asyncpg_test_url

import deerflow.runtime.events.terminal as terminal_module
from deerflow.persistence.models.run_event import RunEventRow, RunEventThreadSeqRow
from deerflow.persistence.run.model import CompletedRunSnapshotRow, RunChangeClockRow, RunRow
from deerflow.runtime.events.store.base import RunEventLifecycleRejected
from deerflow.runtime.events.store.db import DbRunEventStore
from deerflow.runtime.events.store.jsonl import JsonlRunEventStore
from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.events.terminal import (
    RecoveryTerminalPublisher,
    RecoveryTerminalTargetConsumed,
    TerminalEventConfirmation,
    confirm_terminal_event,
)
from deerflow.runtime.runs.store.memory import MemoryRunStore
from deerflow.runtime.user_context import AUTO


@pytest_asyncio.fixture(params=["memory", "jsonl", "sqlite", "postgresql"])
async def stores(request, tmp_path):
    backend = request.param
    if backend in ("memory", "jsonl"):
        store = MemoryRunEventStore() if backend == "memory" else JsonlRunEventStore(base_dir=tmp_path)
        yield SimpleNamespace(first=store, second=store, backend=backend)
        return
    schema = None
    if backend == "postgresql":
        uri = os.getenv("TEST_POSTGRES_URI")
        if not uri:
            pytest.skip("requires TEST_POSTGRES_URI for real PostgreSQL event confirmation")
        schema = f"terminal_{uuid4().hex}"
        url = asyncpg_test_url(uri)
        options = {"connect_args": {"server_settings": {"search_path": schema}}}
    else:
        url = f"sqlite+aiosqlite:///{tmp_path / 'events.db'}"
        options = {}
    first_engine = create_async_engine(url, **options)
    second_engine = create_async_engine(url, **options)
    try:
        async with first_engine.begin() as conn:
            if schema:
                await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            await conn.run_sync(
                lambda c: RunEventRow.metadata.create_all(
                    c,
                    tables=[
                        RunEventRow.__table__,
                        RunEventThreadSeqRow.__table__,
                        RunRow.__table__,
                        RunChangeClockRow.__table__,
                        CompletedRunSnapshotRow.__table__,
                    ],
                )
            )
        first = DbRunEventStore(async_sessionmaker(first_engine, expire_on_commit=False))
        second = DbRunEventStore(async_sessionmaker(second_engine, expire_on_commit=False))
        yield SimpleNamespace(first=first, second=second, backend=backend)
    finally:
        await second_engine.dispose()
        if schema:
            async with first_engine.begin() as conn:
                await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await first_engine.dispose()


async def confirm(store, status="success", *, authorized=lambda: True):
    return await confirm_terminal_event(store, thread_id="thread", run_id="run", status=status, user_id="alice", authorized=authorized)


async def recovery_publisher(store):
    run_store = MemoryRunStore()
    await run_store.put("run", thread_id="thread", user_id="alice", status="error", operation_kind="run")
    return RecoveryTerminalPublisher(store, run_store)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["success", "error", "interrupted", "timeout"])
async def test_confirmed_existing_retains_singleton_and_original_source(stores, status):
    assert await confirm(stores.first, status) == TerminalEventConfirmation.CONFIRMED_NEW
    first = await stores.first.list_events("thread", "run", user_id="alice")
    assert len(first) == 1
    assert first[0]["category"] == "trace"
    assert first[0]["content"] == {"status": status}
    assert first[0]["metadata"]["protocol_version"] == 1
    assert first[0]["metadata"]["recovered"] is False
    assert await confirm(stores.first, status) == TerminalEventConfirmation.CONFIRMED_EXISTING
    assert await stores.first.list_events("thread", "run", user_id="alice") == first
    assert not await stores.first.list_messages("thread", user_id="alice")


@pytest.mark.asyncio
async def test_changed_outcome_conflicts_instead_of_overwriting(stores):
    assert (await confirm(stores.first)).confirmed
    first = await stores.first.list_events("thread", "run", user_id="alice")
    assert await confirm(stores.first, "error") == TerminalEventConfirmation.CONFLICT
    assert await stores.first.list_events("thread", "run", user_id="alice") == first


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [("run_id", "other"), ("thread_id", "other"), ("event_type", "run.end"), ("category", "outputs"), ("content", {"status": "success", "outputs": "private"}), ("seq", True), ("seq", 0)])
async def test_invalid_returned_record_cannot_confirm(stores, monkeypatch, field, value):
    original = stores.first.put_if_absent

    async def corrupt_ack(**kwargs):
        event, created = await original(**kwargs)
        event = deepcopy(event)
        event[field] = value
        return event, created

    monkeypatch.setattr(stores.first, "put_if_absent", corrupt_ack)
    assert await confirm(stores.first) == TerminalEventConfirmation.CONFLICT
    assert len(await stores.first.list_events("thread", "run", user_id="alice")) == 1


@pytest.mark.asyncio
async def test_ack_loss_uses_atomic_confirmation_without_duplicate(stores, monkeypatch):
    original = stores.first.put_if_absent
    attempts = []

    async def lose_ack(**kwargs):
        result = await original(**kwargs)
        attempts.append(result)
        if len(attempts) == 1:
            raise OSError("ACK lost after commit")
        return result

    monkeypatch.setattr(stores.first, "put_if_absent", lose_ack)
    assert await confirm(stores.first) == TerminalEventConfirmation.CONFIRMED_EXISTING
    assert [created for _event, created in attempts] == [True, False]
    assert attempts[0][0] == attempts[1][0]
    assert len(await stores.first.list_events("thread", "run", user_id="alice")) == 1


@pytest.mark.asyncio
async def test_lost_authority_blocks_ack_loss_retry(stores, monkeypatch):
    original = stores.first.put_if_absent
    authorized = True
    attempts = []

    async def lose_ack(**kwargs):
        nonlocal authorized
        attempts.append(await original(**kwargs))
        authorized = False
        raise OSError("ACK lost after commit")

    monkeypatch.setattr(stores.first, "put_if_absent", lose_ack)
    with pytest.raises(RuntimeError, match="final commit ACK"):
        await confirm(stores.first, authorized=lambda: authorized)
    assert len(attempts) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("second_status", ["success", "error"])
async def test_postgres_independent_writers_contend_on_one_terminal(stores, monkeypatch, second_status):
    if stores.backend != "postgresql":
        pytest.skip("requires PostgreSQL independent connection pools and advisory locks")
    first, second = stores.first, stores.second
    held, attempted, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    original_max = first._max_seq_for_thread
    original_second_max = second._max_seq_for_thread
    waiting_pid = None

    async def hold_first(session, thread_id):
        maximum = await original_max(session, thread_id)
        held.set()
        await release.wait()
        return maximum

    async def observe_second(session, thread_id):
        nonlocal waiting_pid
        waiting_pid = await session.scalar(select(func.pg_backend_pid()))
        attempted.set()
        return await original_second_max(session, thread_id)

    monkeypatch.setattr(first, "_max_seq_for_thread", hold_first)
    monkeypatch.setattr(second, "_max_seq_for_thread", observe_second)
    first_task = asyncio.create_task(confirm(first))
    second_task = None
    try:
        await asyncio.wait_for(held.wait(), timeout=5)
        second_task = asyncio.create_task(confirm(second, second_status))
        await asyncio.wait_for(attempted.wait(), timeout=5)
        async with first._sf() as observer:
            async with asyncio.timeout(5):
                while not await observer.scalar(text("SELECT EXISTS (SELECT 1 FROM pg_locks WHERE pid=:pid AND locktype='advisory' AND NOT granted)"), {"pid": waiting_pid}):
                    await asyncio.sleep(0.01)
        assert not second_task.done()
    finally:
        release.set()
        await asyncio.wait_for(asyncio.gather(first_task, *([second_task] if second_task else []), return_exceptions=True), timeout=5)
    assert first_task.result() == TerminalEventConfirmation.CONFIRMED_NEW
    assert second_task.result() == (TerminalEventConfirmation.CONFIRMED_EXISTING if second_status == "success" else TerminalEventConfirmation.CONFLICT)
    terminal = await second.list_events("thread", "run", user_id="alice")
    assert len(terminal) == 1
    assert terminal[0]["content"] == {"status": "success"}
    later = await second.put(thread_id="thread", run_id="run", event_type="test.later", category="trace")
    assert later["seq"] > terminal[0]["seq"]


@pytest.mark.asyncio
async def test_database_ack_must_retain_owner_identity(stores, monkeypatch):
    if not isinstance(stores.first, DbRunEventStore):
        pytest.skip("only database records declare user ownership")
    original = stores.first.put_if_absent

    async def omit_owner(**kwargs):
        event, created = await original(**kwargs)
        event.pop("user_id")
        return event, created

    monkeypatch.setattr(stores.first, "put_if_absent", omit_owner)
    assert await confirm(stores.first) == TerminalEventConfirmation.CONFLICT


@pytest.mark.asyncio
async def test_guarded_singleton_rejects_false_lifecycle(stores):
    async def reject():
        return False

    with pytest.raises(RunEventLifecycleRejected):
        await stores.first.put_if_absent(
            thread_id="thread",
            run_id="run",
            event_type="run.terminal",
            category="trace",
            content={"status": "error"},
            metadata={"protocol_version": 1, "recovered": True},
            user_id="alice",
            lifecycle_guard=reject,
        )
    assert await stores.first.list_events("thread", "run", user_id="alice") == []


@pytest.mark.asyncio
async def test_lifecycle_guard_holds_store_fence_against_thread_delete(stores, monkeypatch):
    entered, release, delete_started = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def guard():
        entered.set()
        await release.wait()
        return True

    original_delete = stores.first.delete_by_thread

    async def observed_delete(thread_id, **kwargs):
        delete_started.set()
        return await original_delete(thread_id, **kwargs)

    monkeypatch.setattr(stores.first, "delete_by_thread", observed_delete)
    put_task = asyncio.create_task(
        stores.first.put_if_absent(
            thread_id="thread",
            run_id="run",
            event_type="run.terminal",
            category="trace",
            content={"status": "error"},
            metadata={"protocol_version": 1, "recovered": True},
            user_id="alice",
            lifecycle_guard=guard,
        )
    )
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        delete_task = asyncio.create_task(stores.first.delete_by_thread("thread", user_id="alice"))
        await asyncio.wait_for(delete_started.wait(), timeout=5)
        assert not delete_task.done()
    finally:
        release.set()
    await asyncio.wait_for(put_task, timeout=5)
    await asyncio.wait_for(delete_task, timeout=5)
    assert await stores.first.list_events("thread", "run", user_id="alice") == []


@pytest.mark.asyncio
async def test_owner_confirmation_supports_legacy_store_signature():
    class LegacyRunEventStore(MemoryRunEventStore):
        async def put_if_absent(
            self,
            *,
            thread_id,
            run_id,
            event_type,
            category,
            content="",
            metadata=None,
            created_at=None,
            user_id: str | None | type(AUTO) = AUTO,
        ):
            return await super().put_if_absent(
                thread_id=thread_id,
                run_id=run_id,
                event_type=event_type,
                category=category,
                content=content,
                metadata=metadata,
                created_at=created_at,
                user_id=user_id,
            )

    store = LegacyRunEventStore()
    confirmation = await confirm_terminal_event(
        store,
        thread_id="thread",
        run_id="run",
        status="error",
        user_id="alice",
        authorized=lambda: True,
    )
    assert confirmation == TerminalEventConfirmation.CONFIRMED_NEW
    assert len(await store.list_events("thread", "run", user_id="alice")) == 1


@pytest.mark.asyncio
async def test_recovery_confirmation_fails_closed_for_legacy_store_signature():
    class LegacyRunEventStore(MemoryRunEventStore):
        async def put_if_absent(
            self,
            *,
            thread_id,
            run_id,
            event_type,
            category,
            content="",
            metadata=None,
            created_at=None,
            user_id: str | None | type(AUTO) = AUTO,
        ):
            return await super().put_if_absent(
                thread_id=thread_id,
                run_id=run_id,
                event_type=event_type,
                category=category,
                content=content,
                metadata=metadata,
                created_at=created_at,
                user_id=user_id,
            )

    store = LegacyRunEventStore()
    publisher = await recovery_publisher(store)
    target = publisher.authorize_takeover(claimed=True, thread_id="thread", run_id="run", user_id="alice", operation_kind="run")
    assert target is not None

    assert await publisher.publish(target) == TerminalEventConfirmation.UNKNOWN
    assert await store.list_events("thread", "run", event_types=["run.terminal"], user_id="alice") == []


@pytest.mark.asyncio
async def test_recovery_target_requires_successful_run_takeover():
    store = MemoryRunEventStore()
    publisher = await recovery_publisher(store)
    identity = dict(thread_id="thread", run_id="run", user_id="alice")

    assert publisher.authorize_takeover(claimed=False, operation_kind="run", **identity) is None
    assert publisher.authorize_takeover(claimed=True, operation_kind="checkpoint_write", **identity) is None
    target = publisher.authorize_takeover(claimed=True, operation_kind="run", **identity)
    assert target is not None
    assert (target.thread_id, target.run_id, target.user_id, target.operation_kind, target.committed_status) == (
        "thread",
        "run",
        "alice",
        "run",
        "error",
    )

    assert await publisher.publish(target) == TerminalEventConfirmation.CONFIRMED_NEW
    delivery = await store.list_events("thread", "run", event_types=["run.delivery"], user_id="alice")
    terminal = await store.list_events("thread", "run", event_types=["run.terminal"], user_id="alice")
    assert len(delivery) == 1
    assert len(terminal) == 1
    assert delivery[0]["seq"] < terminal[0]["seq"]
    assert terminal[0]["content"] == {"status": "error"}
    assert terminal[0]["metadata"] == {"protocol_version": 1, "recovered": True}


@pytest.mark.asyncio
async def test_recovery_target_cannot_be_replaced_or_reauthorized():
    store = MemoryRunEventStore()
    publisher = await recovery_publisher(store)
    target = publisher.authorize_takeover(claimed=True, thread_id="thread", run_id="run", user_id="alice", operation_kind="run")
    assert target is not None

    with pytest.raises(TypeError):
        replace(target, run_id="another-run")
    with pytest.raises(AttributeError):
        target.run_id = "another-run"
    with pytest.raises(AttributeError):
        target._claim_state = type(target._claim_state)()
    with pytest.raises(AttributeError):
        target._claim_state._consumed = False

    copied = copy(target)
    assert await publisher.publish(target) == TerminalEventConfirmation.CONFIRMED_NEW
    with pytest.raises(RecoveryTerminalTargetConsumed):
        await publisher.publish(copied)


@pytest.mark.asyncio
async def test_recovery_target_is_one_shot_across_lost_ack_retry():
    store = MemoryRunEventStore()
    publisher = await recovery_publisher(store)
    target = publisher.authorize_takeover(claimed=True, thread_id="thread", run_id="run", user_id="alice", operation_kind="run")
    assert target is not None
    entered, release = asyncio.Event(), asyncio.Event()
    original = store.put_if_absent
    attempts = []

    async def commit_then_lose_first_terminal_ack(**kwargs):
        if kwargs["event_type"] != "run.terminal":
            return await original(**kwargs)
        result = await original(**kwargs)
        attempts.append(result)
        if len(attempts) == 1:
            entered.set()
            await release.wait()
            raise OSError("ACK lost after commit")
        return result

    store.put_if_absent = commit_then_lose_first_terminal_ack
    first = asyncio.create_task(publisher.publish(target))
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        with pytest.raises(RecoveryTerminalTargetConsumed):
            await publisher.publish(target)
    finally:
        release.set()
    assert await asyncio.wait_for(first, timeout=5) == TerminalEventConfirmation.CONFIRMED_EXISTING
    assert [created for _event, created in attempts] == [True, False]
    terminal = await store.list_events("thread", "run", event_types=["run.terminal"], user_id="alice")
    assert len(terminal) == 1
    assert terminal[0]["metadata"]["recovered"] is True


@pytest.mark.asyncio
async def test_recovery_target_isolates_unexpected_confirmation_error(monkeypatch):
    store = MemoryRunEventStore()
    publisher = await recovery_publisher(store)
    target = publisher.authorize_takeover(claimed=True, thread_id="thread", run_id="run", user_id="alice", operation_kind="run")
    assert target is not None

    async def unexpected_failure(*args, **kwargs):
        raise RuntimeError("unexpected confirmation failure")

    monkeypatch.setattr(terminal_module, "confirm_terminal_event", unexpected_failure)

    assert await publisher.publish(target) == TerminalEventConfirmation.UNKNOWN
    with pytest.raises(RecoveryTerminalTargetConsumed):
        await publisher.publish(target)
    assert await store.list_events("thread", "run", event_types=["run.delivery"], user_id="alice")
    assert await store.list_events("thread", "run", event_types=["run.terminal"], user_id="alice") == []


@pytest.mark.asyncio
async def test_recovery_target_propagates_cancellation_after_consumption(monkeypatch):
    store = MemoryRunEventStore()
    publisher = await recovery_publisher(store)
    target = publisher.authorize_takeover(claimed=True, thread_id="thread", run_id="run", user_id="alice", operation_kind="run")
    assert target is not None

    async def cancelled(*args, **kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(terminal_module, "confirm_terminal_event", cancelled)

    with pytest.raises(asyncio.CancelledError):
        await publisher.publish(target)
    with pytest.raises(RecoveryTerminalTargetConsumed):
        await publisher.publish(target)
