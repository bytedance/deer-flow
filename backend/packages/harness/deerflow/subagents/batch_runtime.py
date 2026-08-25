"""Process-local bridge from harness tools to the Gateway batch service."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class BatchSubmitRequest:
    user_id: str
    thread_id: str
    run_id: str | None
    tool_call_id: str
    submission_key: str
    title: str
    subagent_type: str
    items: list[dict[str, str]]
    max_live_items: int | None
    max_running_items: int | None
    execution_spec: dict[str, Any]


class SubagentBatchSubmitter(Protocol):
    async def submit(self, request: BatchSubmitRequest) -> dict[str, Any]: ...

    async def get_batch(self, *, batch_id: str, user_id: str) -> dict[str, Any] | None: ...

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
