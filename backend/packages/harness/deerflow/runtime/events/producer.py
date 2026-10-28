"""Host-only event authority; never reconstructed from event metadata."""

from __future__ import annotations

import re
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


@dataclass(frozen=True)
class HistorySeedAuthority:
    """Host grant tied to a durable checkpoint-write reservation, not a Run."""

    thread_id: str
    user_id: str | None
    thread_incarnation: str | None
    thread_user_id: str | None
    reservation_id: str
    reservation_incarnation: str
    producer_epoch: str
    owner_worker_id: str
    retention_revision: int
    seed_kind: Literal["checkpoint", "branch"]
    source: Literal["history_seed"] = "history_seed"

    def to_storage(self) -> dict:
        return asdict(self)

    def allows(self, event: dict) -> bool:
        prefix = f"{self.seed_kind}-seed-{self.thread_id}-"
        return (
            self.seed_kind in ("checkpoint", "branch")
            and event["thread_id"] == self.thread_id
            and event.get("user_id", self.user_id) == self.user_id
            and re.fullmatch(re.escape(prefix) + r"[1-9][0-9]*", event["run_id"]) is not None
            and event.get("category") == "message"
            and event["event_type"] in ("llm.human.input", "llm.ai.response", "llm.tool.result")
        )


def history_seed_authority(reservation, thread: dict, *, seed_kind: Literal["checkpoint", "branch"]) -> HistorySeedAuthority:
    """Use only the host's committed reservation and captured thread identity."""
    if (
        seed_kind not in ("checkpoint", "branch")
        or getattr(reservation, "operation_kind", None) != "checkpoint_write"
        or getattr(reservation, "store_only", False)
        or not getattr(reservation, "run_incarnation", None)
        or not getattr(reservation, "producer_epoch", None)
        or not getattr(reservation, "owner_worker_id", None)
        or thread.get("thread_id") != reservation.thread_id
        or "incarnation" not in thread
        or (thread.get("user_id") is not None and thread["user_id"] != reservation.user_id)
    ):
        raise RunEventProducerRejected("History seeding requires a host reservation and matching thread owner")
    return HistorySeedAuthority(
        thread_id=reservation.thread_id,
        user_id=reservation.user_id,
        thread_incarnation=thread["incarnation"],
        thread_user_id=thread.get("user_id"),
        reservation_id=reservation.run_id,
        reservation_incarnation=reservation.run_incarnation,
        producer_epoch=reservation.producer_epoch,
        owner_worker_id=reservation.owner_worker_id,
        retention_revision=reservation.evidence_retention_revision,
        seed_kind=seed_kind,
    )


_authority: ContextVar[RunEventAuthority | HistorySeedAuthority | None] = ContextVar("deerflow_event_authority", default=None)


def current_producer() -> RunEventAuthority | HistorySeedAuthority | None:
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
def producer_scope(authority: RunEventAuthority | HistorySeedAuthority | None):
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
