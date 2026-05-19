"""Integration tests for :class:`ClosureService` against a temp SQLite DB.

Coverage:

- ``create_ticket`` succeeds and publishes ``closure.create``.
- Idempotency: a second create with the same ``(tenant_id, source_type,
  source_run_id, device_id)`` returns the existing row with ``created=False``
  and does NOT publish a duplicate event.
- Permission gating: missing ``closure:write`` returns a service error with
  code ``permission_denied``; transitions through verify-style actions need
  ``closure:verify``.
- Tenant isolation: a ticket created in tenant A cannot be read or updated
  from tenant B.
- ``transition`` walks pending->assigned->in_progress->pending_verification->
  closed, stamping lifecycle timestamps and emitting one event per step.
- ``update_ticket`` rejects an attempt to smuggle ``status`` via raw_body.
- ``list_tickets`` honours filter and pagination params.
- Metadata is validated by source type; bad metadata raises a validation
  service error.
- ``scan_overdue_once`` flips ``is_overdue`` and emits ``closure.overdue``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio

from deerflow.closed_loop.events import ClosureEventPublisher
from deerflow.closed_loop.permissions import (
    CLOSURE_READ,
    CLOSURE_VERIFY,
    CLOSURE_WRITE,
)
from deerflow.closed_loop.repository import ClosureRepository
from deerflow.closed_loop.schemas import (
    ClosurePriority,
    ClosureSourceType,
    CreateTicketRequest,
    ListTicketsFilter,
    UpdateTicketRequest,
)
from deerflow.closed_loop.service import ClosureService, ClosureServiceError


class _FakeRunEventStore:
    """Stand-in for :class:`RunEventStore` capturing publish calls in memory.

    We don't import the real store here — only the ``put`` signature matters,
    and tying this test to that import would create coupling we don't need.
    """

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def put(
        self,
        *,
        thread_id: str,
        run_id: str,
        event_type: str,
        category: str,
        content: dict[str, Any],
        metadata: dict[str, Any],
    ) -> None:
        self.events.append(
            {
                "thread_id": thread_id,
                "run_id": run_id,
                "event_type": event_type,
                "category": category,
                "content": content,
                "metadata": metadata,
            }
        )


@pytest_asyncio.fixture()
async def service(tmp_path):
    """Spin up a ClosureService backed by a per-test SQLite engine.

    Each test gets a fresh DB file, a fresh repo, a fresh fake event store,
    and a fresh service. We tear the engine down on exit so subsequent tests
    don't see stale rows.
    """
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine

    db_path = tmp_path / f"closure-{uuid.uuid4().hex}.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
    factory = get_session_factory()
    assert factory is not None

    fake_store = _FakeRunEventStore()
    repository = ClosureRepository(factory)
    publisher = ClosureEventPublisher(fake_store)
    svc = ClosureService(repository=repository, event_publisher=publisher)
    try:
        yield svc, repository, fake_store
    finally:
        await close_engine()


WRITE_PERMS = (CLOSURE_READ, CLOSURE_WRITE)
VERIFY_PERMS = (CLOSURE_READ, CLOSURE_WRITE, CLOSURE_VERIFY)


def _make_create_request(
    *,
    title: str = "fan over-temp",
    source_type: ClosureSourceType = ClosureSourceType.DIAGNOSIS,
    source_run_id: str | None = "run-1",
    device_id: str | None = "dev-1",
    priority: ClosurePriority = ClosurePriority.URGENT,
    metadata: dict[str, Any] | None = None,
) -> CreateTicketRequest:
    return CreateTicketRequest(
        title=title,
        priority=priority,
        device_id=device_id,
        source_type=source_type,
        source_run_id=source_run_id,
        metadata=metadata or {"findings": ["temp_high"], "confidence": 0.9},
    )


@pytest.mark.asyncio
async def test_create_ticket_publishes_event(service) -> None:
    svc, _repo, store = service
    ticket, created = await svc.create_ticket(
        tenant_id="tenant-a",
        actor_id="alice",
        permissions=WRITE_PERMS,
        request=_make_create_request(),
    )
    assert created is True
    assert ticket.tenant_id == "tenant-a"
    assert ticket.status == "pending"
    assert ticket.priority == "urgent"
    assert ticket.source_type == "diagnosis"

    assert len(store.events) == 1
    event = store.events[0]
    assert event["event_type"] == "closure.create"
    assert event["category"] == "lifecycle"
    assert event["thread_id"] == "closure:tenant-a"
    assert event["run_id"] == ticket.id


@pytest.mark.asyncio
async def test_create_ticket_idempotent_dedup(service) -> None:
    svc, _repo, store = service
    request = _make_create_request()
    first, created_first = await svc.create_ticket(
        tenant_id="tenant-a",
        actor_id="alice",
        permissions=WRITE_PERMS,
        request=request,
    )
    second, created_second = await svc.create_ticket(
        tenant_id="tenant-a",
        actor_id="bob",
        permissions=WRITE_PERMS,
        request=request,
    )
    assert created_first is True
    assert created_second is False
    assert first.id == second.id
    # Only the first call should have published an event.
    assert len(store.events) == 1


@pytest.mark.asyncio
async def test_create_ticket_requires_write_permission(service) -> None:
    svc, _repo, _store = service
    with pytest.raises(ClosureServiceError) as excinfo:
        await svc.create_ticket(
            tenant_id="tenant-a",
            actor_id="alice",
            permissions=(CLOSURE_READ,),
            request=_make_create_request(),
        )
    assert excinfo.value.code == "permission_denied"


@pytest.mark.asyncio
async def test_create_ticket_requires_tenant_id(service) -> None:
    svc, _repo, _store = service
    with pytest.raises(ClosureServiceError) as excinfo:
        await svc.create_ticket(
            tenant_id="",
            actor_id="alice",
            permissions=WRITE_PERMS,
            request=_make_create_request(),
        )
    assert excinfo.value.code == "validation"


@pytest.mark.asyncio
async def test_create_ticket_validates_metadata_shape(service) -> None:
    svc, _repo, _store = service
    bad = _make_create_request(metadata={"confidence": 2.5})  # out of [0, 1]
    with pytest.raises(ClosureServiceError) as excinfo:
        await svc.create_ticket(
            tenant_id="tenant-a",
            actor_id="alice",
            permissions=WRITE_PERMS,
            request=bad,
        )
    assert excinfo.value.code == "validation"


@pytest.mark.asyncio
async def test_get_ticket_tenant_isolation(service) -> None:
    svc, _repo, _store = service
    ticket, _ = await svc.create_ticket(
        tenant_id="tenant-a",
        actor_id="alice",
        permissions=WRITE_PERMS,
        request=_make_create_request(),
    )

    # Same tenant, can read.
    got = await svc.get_ticket(
        tenant_id="tenant-a",
        ticket_id=ticket.id,
        permissions=(CLOSURE_READ,),
    )
    assert got.id == ticket.id

    # Different tenant — should be invisible.
    with pytest.raises(ClosureServiceError) as excinfo:
        await svc.get_ticket(
            tenant_id="tenant-b",
            ticket_id=ticket.id,
            permissions=(CLOSURE_READ,),
        )
    assert excinfo.value.code == "not_found"


@pytest.mark.asyncio
async def test_full_happy_path_walks_state_machine(service) -> None:
    svc, _repo, store = service
    ticket, _ = await svc.create_ticket(
        tenant_id="tenant-a",
        actor_id="alice",
        permissions=WRITE_PERMS,
        request=_make_create_request(priority=ClosurePriority.NORMAL),
    )

    # assign
    after_assign = await svc.transition(
        tenant_id="tenant-a",
        ticket_id=ticket.id,
        actor_id="alice",
        permissions=WRITE_PERMS,
        action="assign",
        payload={"assignee_id": "bob"},
    )
    assert after_assign.status == "assigned"
    assert after_assign.assignee_id == "bob"
    assert after_assign.due_at is not None
    assert after_assign.assigned_at is not None

    # start
    after_start = await svc.transition(
        tenant_id="tenant-a",
        ticket_id=ticket.id,
        actor_id="bob",
        permissions=WRITE_PERMS,
        action="start",
    )
    assert after_start.status == "in_progress"
    assert after_start.started_at is not None

    # submit_verification
    after_submit = await svc.transition(
        tenant_id="tenant-a",
        ticket_id=ticket.id,
        actor_id="bob",
        permissions=WRITE_PERMS,
        action="submit_verification",
        payload={"verification_summary": "fixed"},
    )
    assert after_submit.status == "pending_verification"
    assert after_submit.submitted_at is not None

    # verify_close — needs verify permission
    after_close = await svc.transition(
        tenant_id="tenant-a",
        ticket_id=ticket.id,
        actor_id="carol",
        permissions=VERIFY_PERMS,
        action="verify_close",
    )
    assert after_close.status == "closed"
    assert after_close.verifier_id == "carol"
    assert after_close.closed_at is not None

    actions = [e["event_type"] for e in store.events]
    assert actions == [
        "closure.create",
        "closure.assign",
        "closure.start",
        "closure.submit_verification",
        "closure.verify_close",
    ]


@pytest.mark.asyncio
async def test_verify_close_requires_verify_permission(service) -> None:
    svc, _repo, _store = service
    ticket, _ = await svc.create_ticket(
        tenant_id="tenant-a",
        actor_id="alice",
        permissions=WRITE_PERMS,
        request=_make_create_request(priority=ClosurePriority.NORMAL),
    )
    await svc.transition(
        tenant_id="tenant-a",
        ticket_id=ticket.id,
        actor_id="alice",
        permissions=WRITE_PERMS,
        action="assign",
        payload={"assignee_id": "bob"},
    )
    await svc.transition(
        tenant_id="tenant-a",
        ticket_id=ticket.id,
        actor_id="bob",
        permissions=WRITE_PERMS,
        action="start",
    )
    await svc.transition(
        tenant_id="tenant-a",
        ticket_id=ticket.id,
        actor_id="bob",
        permissions=WRITE_PERMS,
        action="submit_verification",
    )

    with pytest.raises(ClosureServiceError) as excinfo:
        await svc.transition(
            tenant_id="tenant-a",
            ticket_id=ticket.id,
            actor_id="bob",
            permissions=WRITE_PERMS,  # no verify
            action="verify_close",
        )
    assert excinfo.value.code == "permission_denied"


@pytest.mark.asyncio
async def test_transition_invalid_returns_conflict(service) -> None:
    svc, _repo, _store = service
    ticket, _ = await svc.create_ticket(
        tenant_id="tenant-a",
        actor_id="alice",
        permissions=WRITE_PERMS,
        request=_make_create_request(),
    )
    # ``start`` from ``pending`` is not legal.
    with pytest.raises(ClosureServiceError) as excinfo:
        await svc.transition(
            tenant_id="tenant-a",
            ticket_id=ticket.id,
            actor_id="alice",
            permissions=WRITE_PERMS,
            action="start",
        )
    assert excinfo.value.code == "conflict"


@pytest.mark.asyncio
async def test_transition_missing_payload_returns_validation(service) -> None:
    svc, _repo, _store = service
    ticket, _ = await svc.create_ticket(
        tenant_id="tenant-a",
        actor_id="alice",
        permissions=WRITE_PERMS,
        request=_make_create_request(),
    )
    with pytest.raises(ClosureServiceError) as excinfo:
        await svc.transition(
            tenant_id="tenant-a",
            ticket_id=ticket.id,
            actor_id="alice",
            permissions=WRITE_PERMS,
            action="assign",
            payload={},  # missing assignee_id
        )
    assert excinfo.value.code == "validation"


@pytest.mark.asyncio
async def test_transition_unknown_action_returns_validation(service) -> None:
    svc, _repo, _store = service
    ticket, _ = await svc.create_ticket(
        tenant_id="tenant-a",
        actor_id="alice",
        permissions=WRITE_PERMS,
        request=_make_create_request(),
    )
    with pytest.raises(ClosureServiceError) as excinfo:
        await svc.transition(
            tenant_id="tenant-a",
            ticket_id=ticket.id,
            actor_id="alice",
            permissions=WRITE_PERMS,
            action="bogus_action",
        )
    assert excinfo.value.code == "validation"


@pytest.mark.asyncio
async def test_update_ticket_rejects_status_smuggling(service) -> None:
    svc, _repo, _store = service
    ticket, _ = await svc.create_ticket(
        tenant_id="tenant-a",
        actor_id="alice",
        permissions=WRITE_PERMS,
        request=_make_create_request(),
    )
    with pytest.raises(ClosureServiceError) as excinfo:
        await svc.update_ticket(
            tenant_id="tenant-a",
            ticket_id=ticket.id,
            actor_id="alice",
            permissions=WRITE_PERMS,
            request=UpdateTicketRequest(),
            raw_body={"status": "closed"},
        )
    assert excinfo.value.code == "validation"


@pytest.mark.asyncio
async def test_update_ticket_patches_columns_and_metadata(service) -> None:
    svc, _repo, _store = service
    ticket, _ = await svc.create_ticket(
        tenant_id="tenant-a",
        actor_id="alice",
        permissions=WRITE_PERMS,
        request=_make_create_request(),
    )
    updated = await svc.update_ticket(
        tenant_id="tenant-a",
        ticket_id=ticket.id,
        actor_id="alice",
        permissions=WRITE_PERMS,
        request=UpdateTicketRequest(
            description="initial diagnosis pending",
            priority=ClosurePriority.IMPORTANT,
            metadata_patch={"resolution_plan": "replace fan"},
        ),
    )
    assert updated.description == "initial diagnosis pending"
    assert updated.priority == "important"
    assert updated.metadata.get("resolution_plan") == "replace fan"


@pytest.mark.asyncio
async def test_list_tickets_filters_and_paginates(service) -> None:
    svc, _repo, _store = service
    for idx in range(5):
        await svc.create_ticket(
            tenant_id="tenant-a",
            actor_id="alice",
            permissions=WRITE_PERMS,
            request=_make_create_request(
                title=f"ticket-{idx}",
                source_run_id=f"run-{idx}",
                device_id=f"dev-{idx}",
                priority=ClosurePriority.URGENT if idx % 2 == 0 else ClosurePriority.NORMAL,
            ),
        )
    # Other-tenant noise that must NOT leak into tenant-a's listing.
    await svc.create_ticket(
        tenant_id="tenant-b",
        actor_id="bob",
        permissions=WRITE_PERMS,
        request=_make_create_request(source_run_id="run-other", device_id="dev-other"),
    )

    page = await svc.list_tickets(
        tenant_id="tenant-a",
        permissions=(CLOSURE_READ,),
        filters=ListTicketsFilter(page=1, page_size=2, priority=ClosurePriority.URGENT),
    )
    assert page.meta.total == 3  # idx 0, 2, 4 are urgent
    assert len(page.items) == 2
    assert all(t.priority == "urgent" for t in page.items)
    assert all(t.tenant_id == "tenant-a" for t in page.items)


@pytest.mark.asyncio
async def test_list_events_returns_audit_trail(service) -> None:
    svc, _repo, _store = service
    ticket, _ = await svc.create_ticket(
        tenant_id="tenant-a",
        actor_id="alice",
        permissions=WRITE_PERMS,
        request=_make_create_request(),
    )
    await svc.transition(
        tenant_id="tenant-a",
        ticket_id=ticket.id,
        actor_id="alice",
        permissions=WRITE_PERMS,
        action="assign",
        payload={"assignee_id": "bob"},
    )
    events = await svc.list_events(
        tenant_id="tenant-a",
        ticket_id=ticket.id,
        permissions=(CLOSURE_READ,),
    )
    actions = [e.action for e in events]
    assert actions == ["assign"]
    assert events[0].from_status == "pending"
    assert events[0].to_status == "assigned"


@pytest.mark.asyncio
async def test_notifications_summary_counts_open_and_overdue(service) -> None:
    svc, repo, _store = service
    # Create two open tickets and one closed.
    for idx in range(2):
        await svc.create_ticket(
            tenant_id="tenant-a",
            actor_id="alice",
            permissions=WRITE_PERMS,
            request=_make_create_request(source_run_id=f"open-{idx}", device_id=f"d-{idx}"),
        )
    closing, _ = await svc.create_ticket(
        tenant_id="tenant-a",
        actor_id="alice",
        permissions=WRITE_PERMS,
        request=_make_create_request(source_run_id="to-close", device_id="d-x"),
    )
    await svc.transition(
        tenant_id="tenant-a",
        ticket_id=closing.id,
        actor_id="alice",
        permissions=WRITE_PERMS,
        action="reject",
    )
    # Mark one of the open tickets overdue at the repo layer (bypasses scanner).
    open_list = await svc.list_tickets(
        tenant_id="tenant-a",
        permissions=(CLOSURE_READ,),
        filters=ListTicketsFilter(status="pending"),
    )
    target_id = open_list.items[0].id
    await repo.mark_overdue(ticket_id=target_id, now=datetime.now(UTC))

    summary = await svc.notifications_summary(
        tenant_id="tenant-a",
        actor_id=None,
        permissions=(CLOSURE_READ,),
    )
    assert summary.open_count == 2
    assert summary.overdue_count == 1
    assert summary.pending_verification_count == 0


@pytest.mark.asyncio
async def test_scan_overdue_once_flips_flag_and_publishes(service) -> None:
    svc, repo, store = service
    ticket, _ = await svc.create_ticket(
        tenant_id="tenant-a",
        actor_id="alice",
        permissions=WRITE_PERMS,
        request=_make_create_request(priority=ClosurePriority.URGENT),
    )
    await svc.transition(
        tenant_id="tenant-a",
        ticket_id=ticket.id,
        actor_id="alice",
        permissions=WRITE_PERMS,
        action="assign",
        payload={"assignee_id": "bob"},
    )
    # Force the SLA into the past.
    await repo.update_ticket_fields(
        tenant_id="tenant-a",
        ticket_id=ticket.id,
        column_updates={"due_at": datetime.now(UTC) - timedelta(hours=1)},
    )

    store.events.clear()
    rows = await svc.scan_overdue_once()
    assert len(rows) == 1
    assert rows[0]["id"] == ticket.id
    assert any(e["event_type"] == "closure.overdue" for e in store.events)

    # Subsequent scans are idempotent — the row is already flagged so nothing fires.
    store.events.clear()
    second_pass = await svc.scan_overdue_once()
    assert second_pass == []
    assert store.events == []
