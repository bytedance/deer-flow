"""Host-only event authority; never reconstructed from event metadata."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, replace
from functools import wraps
from typing import Literal

from deerflow.runtime.events.store.base import RunEventStoreNotCommittedError


class RunEventProducerRejected(RunEventStoreNotCommittedError):
    """Admission rejected the whole batch before any event/seq was written."""


@dataclass(frozen=True)
class RunEventAuthority:
    run_id: str
    thread_id: str
    user_id: str | None
    run_incarnation: str
    producer_epoch: str | None
    owner_worker_id: str | None
    retention_revision: int
    source: Literal["producer", "publisher", "takeover", "audit"] = "producer"
    event_types: tuple[str, ...] = ()

    def to_storage(self) -> dict:
        return asdict(self)


_authority: ContextVar[RunEventAuthority | None] = ContextVar("deerflow_event_authority", default=None)


def current_producer() -> RunEventAuthority | None:
    return _authority.get()


def producer_authority(record) -> RunEventAuthority | None:
    """Bind the actual host admission, not a user-provided context/metadata map."""
    if getattr(record, "store_only", False):
        return None
    incarnation = getattr(record, "run_incarnation", None)
    epoch = getattr(record, "producer_epoch", None)
    if not incarnation or not epoch:
        return None
    return RunEventAuthority(record.run_id, record.thread_id, record.user_id, incarnation, epoch, getattr(record, "owner_worker_id", None), getattr(record, "evidence_retention_revision", 0))


def run_producer_context(function):
    """Keep host authority out of graph/checkpoint/user context carriers."""

    @wraps(function)
    async def scoped(bridge, run_manager, record, **kwargs):
        authority = producer_authority(record)
        if record.store_only or (authority is not None and (run_manager._runs.get(record.run_id) is not record or record.owner_worker_id != run_manager._worker_id)):
            from deerflow.runtime.runs.manager import RunStartupError

            raise RunStartupError("Only the locally admitted Worker may produce Run events")
        with producer_scope(authority):
            return await function(bridge, run_manager, record, **kwargs)

    return scoped


@contextmanager
def producer_scope(authority: RunEventAuthority | None):
    token = _authority.set(authority)
    try:
        yield
    finally:
        _authority.reset(token)


@contextmanager
def publisher_scope(event_type: str):
    """Called only after the existing host publisher's authority checks."""
    current = current_producer()
    if current is not None and current.source == "producer":
        current = replace(current, source="publisher", event_types=(event_type,))
    with producer_scope(current):
        yield


def takeover_authority(*, run_id, thread_id, user_id, run_incarnation, retention_revision=0):
    """Issue only from a successful atomic takeover's one-shot target."""
    if not run_incarnation:
        return None
    return RunEventAuthority(run_id, thread_id, user_id, run_incarnation, None, None, retention_revision, "takeover", ("run.terminal", "run.delivery"))


def audit_authority(record, *, event_types: tuple[str, ...]) -> RunEventAuthority:
    """Explicit host audit grant; no model/tool-visible bypass flag."""
    if not event_types or any(not event_type.startswith("audit.") for event_type in event_types):
        raise ValueError("Audit authority is limited to named audit.* events")
    authority = producer_authority(record)
    if authority is None:
        raise ValueError("Audit authority requires an admitted Run incarnation")
    return replace(authority, source="audit", producer_epoch=None, event_types=event_types)
