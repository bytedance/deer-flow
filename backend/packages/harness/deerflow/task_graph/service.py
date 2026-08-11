from typing import Any

from .models import CodingRunPlan, CodingTask, TaskStatus
from .store import JsonTaskStore


class TaskGraph:
    """管理任务依赖和状态流转规则"""

    def __init__(self, store: JsonTaskStore):
        self.store = store

    @staticmethod
    def validate_coding_brief(coding_brief: dict[str, Any]) -> None:
        if not isinstance(coding_brief, dict):
            raise ValueError("coding_brief must be an object")
        if not isinstance(coding_brief.get("goal"), str) or not coding_brief["goal"].strip():
            raise ValueError("coding_brief.goal is required")
        acceptance_criteria = coding_brief.get("acceptance_criteria")
        if not isinstance(acceptance_criteria, list) or not acceptance_criteria or not all(isinstance(item, str) and item.strip() for item in acceptance_criteria):
            raise ValueError("coding_brief.acceptance_criteria must be a non-empty list of strings")
        tasks = coding_brief.get("tasks")
        if not isinstance(tasks, list) or not tasks:
            raise ValueError("coding_brief.tasks must be a non-empty list")
        workflow_type = coding_brief.get("workflow_type", "implement_and_review")
        if workflow_type not in {
            "analyze_only",
            "review_only",
            "implement_and_review",
        }:
            raise ValueError("coding_brief.workflow_type is invalid")

    def save_run_plan(self, coding_brief: dict[str, Any], task_ids: list[str]) -> CodingRunPlan:
        """持久化已确认目标，供每次独立子 Agent 上下文重新读取。"""
        self.validate_coding_brief(coding_brief)
        try:
            version = self.store.load_run_plan().version + 1
        except FileNotFoundError:
            version = 1
        plan = CodingRunPlan(coding_brief=coding_brief, task_ids=task_ids, version=version)
        self.store.save_run_plan(plan)
        return plan

    def get_run_plan(self) -> CodingRunPlan:
        return self.store.load_run_plan()

    def bind_worktree(self, task_ids: list[str], worktree: str) -> list[CodingTask]:
        """给一组 CodingTask 绑定同一个已验证 Worktree 的完整路径。"""
        task_list = []
        for task_id in task_ids:
            task_list.append(self.store.load(task_id))
        for task in task_list:
            task.worktree = worktree
            self.store.save(task)
        return task_list

    def add_tasks(self, tasks: list[CodingTask]) -> list[CodingTask]:
        """校验并追加任务；新任务可以依赖已持久化的历史节点。"""
        existing_tasks = self.store.list_all()
        all_tasks = [*existing_tasks, *tasks]
        seen: set[str] = set()
        task_map = {task.id: task for task in all_tasks}
        for task in all_tasks:
            if task.id in seen:
                raise ValueError("duplicate task id")
            seen.add(task.id)
            for dep_id in task.blocked_by:
                if dep_id not in task_map:
                    raise ValueError("missing dependency")
        visiting = set()
        visited = set()

        def check(task_id: str):
            if task_id in visiting:
                raise ValueError("cycle detected")
            if task_id in visited:
                return

            visiting.add(task_id)

            for dep_id in task_map[task_id].blocked_by:
                check(dep_id)

            visiting.remove(task_id)
            visited.add(task_id)

        for task_id in task_map:
            check(task_id)
        for task in tasks:
            self.store.save(task)
        return tasks

    def can_start(self, task_id: str) -> bool:
        """是否可执行"""
        #    加载当前任务
        #   -> 遍历 blocked_by
        #   -> 依赖文件不存在：False
        #   -> 依赖状态不是 completed：False
        #   -> 全部检查通过：True
        task = self.store.load(task_id)
        for dep_id in task.blocked_by:
            try:
                dependency = self.store.load(dep_id)
                if dependency.status != TaskStatus.completed:
                    return False
            except FileNotFoundError:
                return False
        else:
            return True

    def claim(self, task_id: str, owner: str) -> CodingTask:
        """认领任务"""
        # 加载任务
        # -> status 不是 pending：抛出 ValueError
        # -> can_start() 是 False：抛出 ValueError
        # -> 设置 owner
        # -> 状态改成 in_progress
        # -> save()
        # -> 返回修改后的 CodingTask
        task = self.store.load(task_id)
        if task.status is not TaskStatus.pending:
            raise ValueError("task must be pending")
        if task.agent_type is not None and task.agent_type != owner:
            raise ValueError(f"task requires agent '{task.agent_type}', got '{owner}'")
        if not self.can_start(task_id):
            raise ValueError("task is blocked")
        task.owner = owner
        task.status = TaskStatus.in_progress
        self.store.save(task)
        return task

    def fail(self, task_id: str, reason: str) -> CodingTask:
        task = self.store.load(task_id)
        if task.status is not TaskStatus.in_progress:
            raise ValueError("Only in_progress task can fail")
        task.status = TaskStatus.failed
        task.failure_reason = reason
        self.store.save(task)
        return task

    def recover(self, task_id: str) -> CodingTask:
        task = self.store.load(task_id)
        if task.status is not TaskStatus.failed:
            raise ValueError("Only failed task can recover")
        task.status = TaskStatus.pending
        task.owner = None
        task.failure_reason = None
        self.store.save(task)
        return task

    def complete(self, task_id: str, artifact: dict | None = None) -> list[str]:
        """标记为完成"""
        # 加载任务
        # -> status 不是 in_progress：抛出 ValueError
        # -> 状态改为 completed
        # -> save()
        # -> 扫描所有任务
        # -> 找出刚刚可以执行的下游任务
        # -> 返回这些任务的 ID
        task = self.store.load(task_id)
        if task.status is not TaskStatus.in_progress:
            raise ValueError("task must be in_progress")
        task.status = TaskStatus.completed
        task.artifact = artifact
        self.store.save(task)
        tasks = self.store.list_all()
        ids = []
        for task in tasks:
            # status 是 pending
            # blocked_by 不是空列表
            # can_start(task.id) 是 True
            if task.status is TaskStatus.pending and task.blocked_by and self.can_start(task.id):
                ids.append(task.id)
        return ids

    def get_upstream_artifacts(self, task_id: str) -> list[dict]:
        """按依赖顺序读取当前任务的全部已完成上游产物。"""
        task = self.store.load(task_id)
        artifacts: list[dict] = []
        visited: set[str] = set()

        def collect(dependency_id: str) -> None:
            if dependency_id in visited:
                return
            dependency = self.store.load(dependency_id)
            for parent_id in dependency.blocked_by:
                collect(parent_id)
            if dependency.status is not TaskStatus.completed:
                raise ValueError(f"dependency '{dependency_id}' is not completed")
            if dependency.artifact is None:
                raise ValueError(f"dependency '{dependency_id}' has no artifact")
            artifacts.append(dependency.artifact)
            visited.add(dependency_id)

        for dependency_id in task.blocked_by:
            collect(dependency_id)
        return artifacts
