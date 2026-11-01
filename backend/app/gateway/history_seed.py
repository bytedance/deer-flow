"""Host-authorized history copies under durable thread-operation admission."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import Request

from app.gateway.deps import get_run_manager, get_thread_store
from app.gateway.internal_auth import get_trusted_internal_owner_user_id
from deerflow.persistence.run.sql import RunRepository
from deerflow.persistence.thread_meta.sql import ThreadMetaRepository
from deerflow.runtime.events.producer import RunEventProducerRejected, history_seed_authority, producer_scope
from deerflow.runtime.events.store.db import DbRunEventStore
from deerflow.runtime.runs.manager import RunRecord
from deerflow.runtime.runs.schemas import ThreadOperationKind


@dataclass(frozen=True)
class HistorySeedReservation:
    record: RunRecord
    thread: dict | None


@asynccontextmanager
async def reserve_history_seed(request: Request, thread_id: str) -> AsyncIterator[HistorySeedReservation | None]:
    """Keep snapshot reads and seed writes exclusive with delete and admission."""
    events = request.app.state.run_event_store
    manager = getattr(request.app.state, "run_manager", None)
    runs = getattr(manager, "_store", None)
    threads = getattr(request.app.state, "thread_store", None)
    if not isinstance(events, DbRunEventStore):
        yield None
        return
    if not isinstance(runs, RunRepository) or not isinstance(threads, ThreadMetaRepository):
        if events._producer_fencing == "strict":
            raise RunEventProducerRejected("History seeding requires shared SQL lifecycle stores")
        yield None
        return
    if runs._sf.kw.get("bind") is not events._sf.kw.get("bind") or threads._sf.kw.get("bind") is not events._sf.kw.get("bind"):
        raise RunEventProducerRejected("History seeding requires shared SQL lifecycle stores")
    async with get_run_manager(request).reserve_thread_operation(
        thread_id,
        kind=ThreadOperationKind.checkpoint_write,
        user_id=get_trusted_internal_owner_user_id(request),
    ) as reservation:
        yield HistorySeedReservation(reservation, await threads.get(thread_id, user_id=None))


async def write_history_seed(
    request: Request,
    events: list[dict],
    *,
    reservation: HistorySeedReservation | None,
    seed_kind: str,
    thread: dict | None = None,
    assistant_id: str | None = None,
) -> None:
    store = request.app.state.run_event_store
    if reservation is None:
        await store.put_batch(events)
        return
    if thread is None:
        # Only the checkpoint migration may materialize missing legacy metadata.
        # The caller read that checkpoint while holding this same reservation.
        if seed_kind != "checkpoint":
            raise RunEventProducerRejected("Branch seeding requires its original thread identity")
        threads = get_thread_store(request)
        thread = reservation.thread
        if thread is None:
            thread = await threads.create(reservation.record.thread_id, assistant_id=assistant_id, user_id=reservation.record.user_id)
    authority = history_seed_authority(reservation.record, thread, seed_kind=seed_kind)
    with producer_scope(authority):
        await store.put_batch(events)
