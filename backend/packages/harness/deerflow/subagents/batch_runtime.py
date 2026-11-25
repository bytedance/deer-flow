"""Process-local bridge from harness tools to the Gateway batch service."""

from __future__ import annotations

import threading
from collections.abc import Awaitable, Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any, NotRequired, Protocol, TypedDict

from langchain_core.messages import AIMessage, ToolMessage

BATCH_CONTINUATION_NAMESPACE = "native-subagent-batches"
BATCH_RECEIPT_ID_KEY = "subagent_batch_id"
COMPACTED_BATCH_RECEIPTS_CHANNEL = "compacted_batch_receipt_ids"
BATCH_SUBMISSION_DIGEST_KEY = "_submission_digest"


def iter_batch_dispatch_receipts(messages: Iterable[object]) -> Iterator[tuple[AIMessage, ToolMessage, str]]:
    """Pair successful receipts with the model response that issued their call."""
    dispatch = None
    for message in messages:
        if isinstance(message, AIMessage):
            dispatch = message
        elif not isinstance(message, ToolMessage):
            dispatch = None
        elif dispatch is not None and message.name == "batch_task" and message.status == "success":
            batch_id = message.additional_kwargs.get(BATCH_RECEIPT_ID_KEY)
            if not isinstance(batch_id, str):
                continue
            calls = [call for call in dispatch.tool_calls or () if isinstance(call, dict) and call.get("id") == message.tool_call_id]
            if len(calls) == 1 and calls[0].get("name") == "batch_task":
                yield dispatch, message, batch_id


def compacted_batch_receipt_ids(state: object) -> set[str]:
    values = state.get(COMPACTED_BATCH_RECEIPTS_CHANNEL) if isinstance(state, Mapping) else getattr(state, COMPACTED_BATCH_RECEIPTS_CHANNEL, None)
    return {value for value in values if isinstance(value, str)} if isinstance(values, list) else set()


def compacted_batch_receipt_update(state: Mapping[str, Any], removed_messages: Iterable[object]) -> dict[str, list[str]]:
    removed = {id(message) for message in removed_messages}
    batch_ids = {batch_id for dispatch, receipt, batch_id in iter_batch_dispatch_receipts(state["messages"]) if id(dispatch) in removed and id(receipt) in removed}
    if not batch_ids:
        return {}
    # Checkpoint these IDs in the same write that removes the paired messages.
    return {COMPACTED_BATCH_RECEIPTS_CHANNEL: sorted(compacted_batch_receipt_ids(state) | batch_ids)}


def batch_continuation_key(batch_id: str) -> str:
    return "native-batch-followup:" + batch_id


class BatchItemInput(TypedDict):
    key: str
    prompt: str
    acceptance_criteria: NotRequired[list[str] | None]
    depends_on: NotRequired[list[str]]


@dataclass(frozen=True)
class BatchDispatchReceipts:
    """Persisted receipt IDs paired with their dispatch in the graph state."""

    current: frozenset[str]
    previous: frozenset[str]
    confirm_previous: Callable[[frozenset[str]], Awaitable[bool]] | None = None


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
    dispatch_receipts: BatchDispatchReceipts | None = None


class SubagentBatchSubmitter(Protocol):
    async def submit(self, request: BatchSubmitRequest) -> dict[str, Any]: ...

    async def get_batch(self, *, batch_id: str, user_id: str) -> dict[str, Any] | None: ...

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
