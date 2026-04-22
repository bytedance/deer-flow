"""Public runs domain types."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal

# Intent: 表示请求的意图
RunIntent = Literal[
    "create_background",
    "create_and_stream",
    "create_and_wait",
    "join_stream",
    "join_wait",
]

# Scope kind: stateful (需要 thread_id) vs stateless (临时 thread)
RunScopeKind = Literal["stateful", "stateless"]

class RunStatus(StrEnum):
    pending = "pending"
    starting = "starting"
    running = "running"
    success = "success"
    error = "error"
    interrupted = "interrupted"
    timeout = "timeout"

CancelAction = Literal["interrupt", "rollback"]


@dataclass(frozen=True)
class RunScope:
    """Run 的作用域 - stateful 需要 thread_id, stateless 自动创建临时 thread."""

    kind: RunScopeKind
    thread_id: str
    temporary: bool = False


@dataclass(frozen=True)
class CheckpointRequest:
    """Checkpoint 恢复请求 - phase1 只接受但不实现 restore."""

    checkpoint_id: str | None = None
    checkpoint: dict[str, Any] | None = None


@dataclass(frozen=True)
class RunSpec:
    """
    Run 规格对象 - 由 app 输入层构建，是执行器的输入。

    Phase 1 限制:
    - multitask_strategy 只支持 reject/interrupt
    - 不支持 enqueue/rollback/after_seconds/batch
    """

    intent: RunIntent
    scope: RunScope
    assistant_id: str | None
    input: dict[str, Any] | None
    command: dict[str, Any] | None
    runnable_config: dict[str, Any]
    context: dict[str, Any] | None
    metadata: dict[str, Any]
    stream_modes: list[str]
    stream_subgraphs: bool
    stream_resumable: bool
    on_disconnect: Literal["cancel", "continue"]
    on_completion: Literal["delete", "keep"]
    multitask_strategy: Literal["reject", "interrupt"]
    interrupt_before: list[str] | Literal["*"] | None
    interrupt_after: list[str] | Literal["*"] | None
    checkpoint_request: CheckpointRequest | None
    follow_up_to_run_id: str | None = None
    webhook: str | None = None
    feedback_keys: list[str] | None = None


type WaitResult = dict[str, Any] | None


@dataclass
class RunRecord:
    """
    运行时 Run 记录 - 由 RuntimeRunRegistry 管理。

    与 ORM 模型解耦，只在内存中维护。
    """

    run_id: str
    thread_id: str
    assistant_id: str | None
    status: RunStatus
    temporary: bool
    multitask_strategy: str
    metadata: dict[str, Any] = field(default_factory=dict)
    follow_up_to_run_id: str | None = None
    created_at: str = ""
    updated_at: str = ""
    started_at: str | None = None
    ended_at: str | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if not self.created_at:
            now = datetime.now(timezone.utc).isoformat()
            self.created_at = now
            self.updated_at = now


# Terminal statuses for quick checks
TERMINAL_STATUSES: frozenset[RunStatus] = frozenset({"success", "error", "interrupted"})
INFLIGHT_STATUSES: frozenset[RunStatus] = frozenset({"pending", "starting", "running"})
