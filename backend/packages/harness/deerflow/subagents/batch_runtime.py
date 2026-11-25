"""Process-local bridge from harness tools to the Gateway batch service."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Literal, NotRequired, Protocol, TypedDict, get_args

BATCH_CONTINUATION_NAMESPACE = "native-subagent-batches"
BatchItemStatus = Literal["pending", "queued", "leased", "running", "succeeded", "failed", "cancelled"]
BATCH_ITEM_STATUSES = get_args(BatchItemStatus)


def batch_continuation_key(batch_id: str) -> str:
    return "native-batch-followup:" + batch_id


class BatchItemInput(TypedDict):
    key: str
    prompt: str
    acceptance_criteria: NotRequired[list[str] | None]
    depends_on: NotRequired[list[str]]


class BatchItemSummary(TypedDict):
    position: int
    item_key: str
    status: str


@dataclass(frozen=True)
class BatchSubmitRequest:
    user_id: str
    thread_id: str
    run_id: str | None
    tool_call_id: str
    submission_key: str
    title: str
    subagent_type: str
    items: list[BatchItemInput]
    max_live_items: int | None
    max_running_items: int | None
    execution_spec: dict[str, Any]
    continuation: str | None = None
    continuation_authority: Any = None
    continuation_context: dict[str, Any] | None = None


class SubagentBatchSubmitter(Protocol):
    async def submit(self, request: BatchSubmitRequest) -> dict[str, Any]: ...

    async def get_batch(self, *, batch_id: str, user_id: str) -> dict[str, Any] | None: ...

    async def list_batch_items(self, *, batch_id: str, user_id: str, thread_id: str, after_position: int, limit: int, status: BatchItemStatus | None) -> list[BatchItemSummary] | None: ...

    async def read_batch_item(self, *, batch_id: str, user_id: str, thread_id: str, position: int) -> dict[str, Any] | None: ...

    async def cancel_batch(self, *, batch_id: str, user_id: str) -> dict[str, Any] | None: ...


_submitter: SubagentBatchSubmitter | None = None
_lock = threading.Lock()


def set_subagent_batch_submitter(submitter: SubagentBatchSubmitter | None) -> None:
    global _submitter
    with _lock:
        _submitter = submitter


def get_subagent_batch_submitter() -> SubagentBatchSubmitter | None:
    with _lock:
        return _submitter


def is_subagent_batch_runtime_available() -> bool:
    return get_subagent_batch_submitter() is not None
