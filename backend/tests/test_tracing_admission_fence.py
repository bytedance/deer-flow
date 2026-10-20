"""Profile activation and durable run admission share one database commit order."""

import asyncio
import threading

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_tracing_profiles import _provider, _save
from test_tracing_profiles import control as _control_fixture

control = _control_fixture


def _refs(snapshot, **values):
    return {"deerflow_tracing_snapshot_id": snapshot.snapshot_id, "deerflow_tracing_agent_name": snapshot.agent_name, **values}


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["binding", "profile", "first-binding"])
async def test_admission_rejects_a_captured_snapshot_after_activation_commits(control, change):
    from deerflow.persistence.tracing_profiles.sql import validate_tracing_admission
    from deerflow.tracing.profiles import TracingConflictError

    service, _, _, path = control
    if change != "first-binding":
        _save(service)
        service.set_binding("worker", "alice", mode="configured", profile_id="profile-a", expected_revision=0)
    captured = service.resolve_snapshot("worker", "alice")
    if change == "profile":
        service.save_profile(profile_id="profile-a", name="Activated", providers=(_provider(),), allowed_user_ids=["alice"], expected_revision=1)
    else:
        service.set_binding("worker", "alice", mode="disabled", profile_id=None, expected_revision=0 if change == "first-binding" else 1)
    engine = create_async_engine(f"sqlite+aiosqlite:///{path / 'tracing.db'}")
    try:
        async with async_sessionmaker(engine).begin() as session:
            with pytest.raises(TracingConflictError):
                await validate_tracing_admission(session, _refs(captured), owner_user_id="alice")
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_pinned_history_can_admit_after_activation_but_cannot_change_owner_or_agent(control):
    from deerflow.persistence.tracing_profiles.sql import validate_tracing_admission
    from deerflow.tracing.profiles import TracingAuthorizationError

    service, _, _, path = control
    snapshot = service.resolve_snapshot("worker", "alice")
    service.set_binding("worker", "alice", mode="disabled", profile_id=None, expected_revision=0)
    engine = create_async_engine(f"sqlite+aiosqlite:///{path / 'tracing.db'}")
    try:
        async with async_sessionmaker(engine).begin() as session:
            await validate_tracing_admission(session, _refs(snapshot, deerflow_tracing_pinned=True), owner_user_id="alice")
        for metadata, owner in [(_refs(snapshot, deerflow_tracing_pinned=True), "bob"), (_refs(snapshot, deerflow_tracing_agent_name="other"), "alice")]:
            async with async_sessionmaker(engine).begin() as session:
                with pytest.raises(TracingAuthorizationError):
                    await validate_tracing_admission(session, metadata, owner_user_id=owner)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_profile_activation_waits_until_the_admitting_transaction_commits(control):
    from deerflow.persistence.tracing_profiles.sql import validate_tracing_admission

    service, sync_factory, _, path = control
    _save(service)
    snapshot = service.resolve_snapshot("worker", "alice")
    attempted, finished = threading.Event(), threading.Event()

    def mark_attempt(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("UPDATE TRACING_ADMISSION_FENCE"):
            attempted.set()

    def activate():
        service.save_profile(profile_id="profile-a", name="Activated", providers=(_provider(),), allowed_user_ids=["alice"], expected_revision=1)
        finished.set()

    event.listen(sync_factory.kw["bind"], "before_cursor_execute", mark_attempt)
    engine = create_async_engine(f"sqlite+aiosqlite:///{path / 'tracing.db'}")
    activation = None
    try:
        async with async_sessionmaker(engine).begin() as session:
            await validate_tracing_admission(session, _refs(snapshot), owner_user_id="alice")
            activation = asyncio.create_task(asyncio.to_thread(activate))
            assert await asyncio.to_thread(attempted.wait, 5)
            assert not finished.is_set()
        await activation
        assert finished.is_set()
    finally:
        event.remove(sync_factory.kw["bind"], "before_cursor_execute", mark_attempt)
        if activation is not None:
            await activation
        await engine.dispose()
