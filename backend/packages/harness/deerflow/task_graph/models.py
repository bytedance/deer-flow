from dataclasses import dataclass, field
from enum import StrEnum


class TaskStatus(StrEnum):
    """任务状态"""

    pending = "pending"
    in_progress = "in_progress"
    completed = "completed"
    failed = "failed"


@dataclass
class CodingTask:
    """任务的数据结构"""

    id: str
    subject: str
    description: str
    status: TaskStatus = TaskStatus.pending
    owner: str | None = None
    failure_reason: str | None = None
    blocked_by: list[str] = field(default_factory=list)
    # 目标仓库中已验证存在的 Worktree 完整路径，供子 Agent 直接切换工作区。
    worktree: str | None = None
