"""Integration tests for the closure overdue-scan background job.

Covers spec §4.4 acceptance:

* Inject several tickets whose ``due_at`` has lapsed and run a single
  scan cycle. Assert the scanner flips ``is_overdue=True`` on every
  candidate and emits a ``closure.overdue`` event per ticket.
* A second cycle on the same data is a no-op (idempotent).
* The asyncio fallback skips when the in-process lock is already held.
* The PostgreSQL path skips when the advisory lock is held by a peer.
* The scanner survives transient failures and resumes on the next tick.

We exercise the real ``ClosureService`` + ``ClosureRepository`` over a
per-test SQLite engine and a ``MemoryRunEventStore`` so we can assert the
exact events that landed on the run-event channel.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio


@pytest_asyncio.fixture()
async def scanner_ctx(tmp_path) -> AsyncIterator[dict[str, Any]]:
    """Spin up a fresh SQLite engine + service + memory event store.

    Yields a dict with the moving parts every test needs:

    * ``service`` -- the live :class:`ClosureService`
    * ``repository`` -- to seed tickets directly
    * ``session_factory`` -- passed to ``_run_one_cycle``
    * ``event_store`` -- assert published events here
    * ``tenant_id`` / ``actor_id`` -- stable ids for assertions
    """
    from deerflow.closed_loop.events import ClosureEventPublisher, closure_thread_id
    from deerflow.closed_loop.repository import ClosureRepository
    from deerflow.closed_loop.service import ClosureService
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
    from deerflow.runtime.events.store.memory import MemoryRunEventStore

    db_path = tmp_path / f"closure-scan-{uuid.uuid4().hex}.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
    session_factory = get_session_factory()
    assert session_factory is not None

    event_store = MemoryRunEventStore()
    publisher = ClosureEventPublisher(event_store)
    repository = ClosureRepository(session_factory)
    service = ClosureService(repository=repository, event_publisher=publisher)

    try:
        yield {
            "service": service,
            "repository": repository,
            "session_factory": session_factory,
            "event_store": event_store,
            "tenant_id": "tenant-a",
            "actor_id": "alice",
            "closure_thread_id": closure_thread_id,
        }
    finally:
        await close_engine()


async def _seed_overdue_ticket(
    *,
    repository,
    session_factory,
    tenant_id: str,
    actor_id: str,
    suffix: str,
    due_at: datetime,
    status: str = "in_progress",
) -> dict[str, Any]:
    """Insert a ticket and force ``due_at`` + ``status`` into "open and overdue".

    The state machine refuses to set ``due_at`` directly, and ``status``
    can only be moved through transitions. For tests that need a row the
    scanner will pick up, the cleanest path is to insert via the
    repository, then UPDATE the two columns directly via SQL.
    """
    from sqlalchemy import update

    from deerflow.persistence.models.closure_ticket import ClosureTicketRow

    row, created = await repository.create_ticket(
        tenant_id=tenant_id,
        title=f"overdue-{suffix}",
        created_by=actor_id,
        priority="urgent",
        source_type="diagnosis",
        device_id=f"dev-{suffix}",
        source_run_id=f"run-{suffix}",
        metadata={"findings": ["t"], "confidence": 0.9},
    )
    assert created

    async with session_factory() as session:
        await session.execute(
            update(ClosureTicketRow)
            .where(ClosureTicketRow.id == row["id"])
            .values(due_at=due_at, status=status)
        )
        await session.commit()
    return row


@pytest.mark.asyncio
async def test_run_one_cycle_marks_candidates_and_publishes_events(scanner_ctx) -> None:
    """The scanner flips ``is_overdue`` and emits ``closure.overdue`` per candidate."""
    from deerflow.closed_loop.jobs import _run_one_cycle

    service = scanner_ctx["service"]
    repository = scanner_ctx["repository"]
    session_factory = scanner_ctx["session_factory"]
    event_store = scanner_ctx["event_store"]
    tenant_id = scanner_ctx["tenant_id"]
    closure_thread_id = scanner_ctx["closure_thread_id"]

    past = datetime.now(UTC) - timedelta(hours=1)
    seeded: list[dict[str, Any]] = []
    for idx in range(3):
        seeded.append(
            await _seed_overdue_ticket(
                repository=repository,
                session_factory=session_factory,
                tenant_id=tenant_id,
                actor_id=scanner_ctx["actor_id"],
                suffix=str(idx),
                due_at=past,
            )
        )

    # Also seed a non-overdue ticket -- must NOT be picked up.
    not_overdue = await _seed_overdue_ticket(
        repository=repository,
        session_factory=session_factory,
        tenant_id=tenant_id,
        actor_id=scanner_ctx["actor_id"],
        suffix="future",
        due_at=datetime.now(UTC) + timedelta(hours=1),
    )

    process_lock = asyncio.Lock()
    published = await _run_one_cycle(
        service=service,
        session_factory=session_factory,
        process_lock=process_lock,
    )

    assert published is not None
    assert {row["id"] for row in published} == {row["id"] for row in seeded}

    # Each candidate is now flagged.
    for row in seeded:
        latest = await repository.get_ticket(tenant_id=tenant_id, ticket_id=row["id"])
        assert latest is not None
        assert latest["is_overdue"] is True

    # The non-overdue row stayed untouched.
    untouched = await repository.get_ticket(tenant_id=tenant_id, ticket_id=not_overdue["id"])
    assert untouched is not None
    assert untouched["is_overdue"] is False

    # Each ticket got exactly one closure.overdue lifecycle event.
    events = await event_store.list_events(
        thread_id=closure_thread_id(tenant_id),
        run_id=seeded[0]["id"],
    )
    assert len(events) == 1
    assert events[0]["event_type"] == "closure.overdue"
    body = events[0]["content"]
    assert body["action"] == "overdue"
    assert body["ticket_id"] == seeded[0]["id"]


@pytest.mark.asyncio
async def test_run_one_cycle_is_idempotent(scanner_ctx) -> None:
    """Re-running the scanner on the same data returns no new candidates."""
    from deerflow.closed_loop.jobs import _run_one_cycle

    service = scanner_ctx["service"]
    repository = scanner_ctx["repository"]
    session_factory = scanner_ctx["session_factory"]

    await _seed_overdue_ticket(
        repository=repository,
        session_factory=session_factory,
        tenant_id=scanner_ctx["tenant_id"],
        actor_id=scanner_ctx["actor_id"],
        suffix="solo",
        due_at=datetime.now(UTC) - timedelta(hours=2),
    )

    lock = asyncio.Lock()
    first = await _run_one_cycle(service=service, session_factory=session_factory, process_lock=lock)
    second = await _run_one_cycle(service=service, session_factory=session_factory, process_lock=lock)

    assert first is not None and len(first) == 1
    assert second == []  # candidates were already flipped on first pass


@pytest.mark.asyncio
async def test_run_one_cycle_skips_when_process_lock_held(scanner_ctx) -> None:
    """Asyncio fallback path: skip when a sibling tick is still running."""
    from deerflow.closed_loop.jobs import _run_one_cycle

    service = scanner_ctx["service"]
    repository = scanner_ctx["repository"]
    session_factory = scanner_ctx["session_factory"]

    seeded = await _seed_overdue_ticket(
        repository=repository,
        session_factory=session_factory,
        tenant_id=scanner_ctx["tenant_id"],
        actor_id=scanner_ctx["actor_id"],
        suffix="lockheld",
        due_at=datetime.now(UTC) - timedelta(hours=3),
    )

    lock = asyncio.Lock()
    await lock.acquire()
    try:
        result = await _run_one_cycle(
            service=service,
            session_factory=session_factory,
            process_lock=lock,
        )
    finally:
        lock.release()

    assert result is None  # signals "skipped"
    # Ticket remains un-flipped because the cycle was skipped.
    latest = await repository.get_ticket(
        tenant_id=scanner_ctx["tenant_id"], ticket_id=seeded["id"]
    )
    assert latest is not None and latest["is_overdue"] is False


@pytest.mark.asyncio
async def test_run_one_cycle_skips_when_pg_advisory_lock_unavailable(monkeypatch, scanner_ctx) -> None:
    """PG path: peer holds advisory lock -> we skip cleanly without scanning."""
    from deerflow.closed_loop import jobs as jobs_mod

    service = scanner_ctx["service"]
    session_factory = scanner_ctx["session_factory"]

    monkeypatch.setattr(jobs_mod, "_is_postgres", lambda _sf: True)

    async def _peer_holds_lock(_session) -> bool:
        return False

    monkeypatch.setattr(jobs_mod, "_try_pg_advisory_lock", _peer_holds_lock)

    sentinel = object()

    async def _should_not_run(*, now=None):  # noqa: ARG001 -- mirrors signature
        return sentinel

    monkeypatch.setattr(service, "scan_overdue_once", _should_not_run)

    result = await jobs_mod._run_one_cycle(
        service=service,
        session_factory=session_factory,
        process_lock=asyncio.Lock(),
    )
    assert result is None  # peer held the lock -> skip


@pytest.mark.asyncio
async def test_scanner_loop_recovers_from_transient_error(scanner_ctx) -> None:
    """A failing cycle is logged but never kills the periodic loop."""
    from deerflow.closed_loop import jobs as jobs_mod

    service = scanner_ctx["service"]
    session_factory = scanner_ctx["session_factory"]

    calls = {"n": 0}
    seeded = await _seed_overdue_ticket(
        repository=scanner_ctx["repository"],
        session_factory=session_factory,
        tenant_id=scanner_ctx["tenant_id"],
        actor_id=scanner_ctx["actor_id"],
        suffix="boom",
        due_at=datetime.now(UTC) - timedelta(hours=4),
    )

    real_scan = service.scan_overdue_once

    async def _flaky_scan(*, now=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient db blip")
        return await real_scan(now=now)

    service.scan_overdue_once = _flaky_scan  # type: ignore[assignment]

    stop_event = asyncio.Event()
    task = asyncio.create_task(
        jobs_mod._scanner_loop(
            service=service,
            session_factory=session_factory,
            interval=0.05,
            stop_event=stop_event,
        )
    )

    # Wait long enough for the initial grace, the failing tick, and the
    # successful retry on the next interval.
    await asyncio.sleep(0.4)
    stop_event.set()
    try:
        await asyncio.wait_for(task, timeout=2.0)
    except asyncio.TimeoutError:
        task.cancel()
        with pytest.raises((asyncio.CancelledError, Exception)):
            await task
        pytest.fail("scanner loop did not exit on stop_event")

    assert calls["n"] >= 2
    latest = await scanner_ctx["repository"].get_ticket(
        tenant_id=scanner_ctx["tenant_id"], ticket_id=seeded["id"]
    )
    assert latest is not None and latest["is_overdue"] is True


@pytest.mark.asyncio
async def test_start_scanner_returns_false_when_service_missing() -> None:
    """No closure_service on app.state (memory backend) -> scanner is a no-op."""
    from types import SimpleNamespace

    from deerflow.closed_loop.jobs import start_overdue_scanner

    app = SimpleNamespace(state=SimpleNamespace())
    started = start_overdue_scanner(app)
    assert started is False
    assert getattr(app.state, "_closure_overdue_scanner_task", None) is None


@pytest.mark.asyncio
async def test_start_scanner_is_idempotent(scanner_ctx) -> None:
    """A second start while the task is alive returns False without churn."""
    from types import SimpleNamespace

    from deerflow.closed_loop.jobs import start_overdue_scanner, stop_overdue_scanner

    app = SimpleNamespace(state=SimpleNamespace())
    app.state.closure_service = scanner_ctx["service"]

    started_once = start_overdue_scanner(
        app,
        session_factory=scanner_ctx["session_factory"],
        interval_seconds=60.0,
    )
    started_again = start_overdue_scanner(
        app,
        session_factory=scanner_ctx["session_factory"],
        interval_seconds=60.0,
    )

    try:
        assert started_once is True
        assert started_again is False
    finally:
        await stop_overdue_scanner(app, timeout=2.0)
