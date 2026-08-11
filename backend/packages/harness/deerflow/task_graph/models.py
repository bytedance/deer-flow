from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class TaskStatus(StrEnum):
    """任务状态"""

    pending = "pending"
    in_progress = "in_progress"
    completed = "completed"
    failed = "failed"


@dataclass
class CodingRunPlan:
    """一个 Coding Run 已经由用户确认的目标契约。"""

    coding_brief: dict[str, Any]
    task_ids: list[str]
    version: int = 1


@dataclass
class CodingTask:
    """任务的数据结构"""

    id: str
    subject: str
    description: str
    status: TaskStatus = TaskStatus.pending
    owner: str | None = None
    # 最近一次失败的诊断信息。任务恢复为 pending 后仍保留，供下一次执行接手现场。
    last_failure_reason: str | None = None
    blocked_by: list[str] = field(default_factory=list)
    # 目标仓库中已验证存在的 Worktree 完整路径，供子 Agent 直接切换工作区。
    worktree: str | None = None
    agent_type: str | None = None
    artifact: dict[str, Any] | None = None
